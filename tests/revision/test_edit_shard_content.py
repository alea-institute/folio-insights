"""edit_shard_content async write path + store seam + helpers (D-01..D-06).

Covers the PRD §6.4 store-backed write path, the in-memory store round-trip
(D-02), the dotted-path get/set helpers, the real ``canonical_content_hash``
(D-05), the ``sign_attestation`` unsigned stub (D-05), and the post-edit
``validate_shard`` re-validation hook (V5 / RESEARCH Pitfall 2).
"""
from __future__ import annotations

import re
import time

import pytest

from folio_insights.revision import (
    InMemoryShardStore,
    canonical_content_hash,
    edit_shard_content,
    get_field,
    set_field,
    sign_attestation,
    validate_shard,
)
from folio_insights.shards import SimpleAssertionShard

pytestmark = pytest.mark.shards


# ── ShardStore (D-02) ────────────────────────────────────────────────────────


async def test_store_put_get_roundtrip(store, sample_shard) -> None:
    await store.put(sample_shard.shard_iri, sample_shard)
    got = await store.get(sample_shard.shard_iri)
    assert got is sample_shard


async def test_store_get_unknown_returns_none(store) -> None:
    assert await store.get("urn:folio:shard/deadbeef") is None


def test_inmemory_store_is_dict_backed() -> None:
    s = InMemoryShardStore()
    assert hasattr(s, "_d") and isinstance(s._d, dict)


# ── dotted-path get_field / set_field ────────────────────────────────────────


def test_get_field_top_level(sample_shard) -> None:
    assert get_field(sample_shard, "sense") == sample_shard.sense


def test_get_field_nested(sample_shard) -> None:
    assert get_field(sample_shard, "triple.object") == sample_shard.triple.object


def test_set_field_top_level(sample_shard) -> None:
    set_field(sample_shard, "sense", "new-sense")
    assert sample_shard.sense == "new-sense"


def test_set_field_nested(sample_shard) -> None:
    set_field(sample_shard, "triple.object", "new-object")
    assert sample_shard.triple.object == "new-object"


# ── WR-02: field_path bounded to declared model fields (no path injection) ────

# Non-declared / dunder / descriptor paths that used to resolve via bare getattr
# but are NOT schema-declared content. Each must be rejected with a clear error
# BEFORE any attribute access (so no internal state leaks into old_value).
_NON_DECLARED_PATHS = [
    "__class__",
    "model_fields",
    "model_config",
    "triple.__class__",
    "triple.__class__.__bases__",
    "sense.__len__",
    "not_a_real_field",
    "",
]


@pytest.mark.parametrize("path", _NON_DECLARED_PATHS)
def test_get_field_rejects_non_declared_path(sample_shard, path: str) -> None:
    """get_field rejects dunders/descriptors/non-declared paths (WR-02): the
    metaclass / field-descriptor / class hierarchy must never leak through the
    reader (which would otherwise land in a ContentEdit's old_value slot)."""
    with pytest.raises(ValueError, match=r"declared model field|Empty field_path"):
        get_field(sample_shard, path)


@pytest.mark.parametrize("path", _NON_DECLARED_PATHS)
def test_set_field_rejects_non_declared_path(sample_shard, path: str) -> None:
    """set_field rejects non-declared paths BEFORE any attribute access (WR-02)."""
    with pytest.raises(ValueError, match=r"declared model field|Empty field_path"):
        set_field(sample_shard, path, "attacker-value")


@pytest.mark.parametrize("path", ["__class__", "model_fields", "triple.__class__"])
async def test_edit_shard_content_rejects_non_declared_path(
    stored_shard, store, path: str
) -> None:
    """edit_shard_content rejects a non-declared field_path and records NO audit
    entry — the WR-02 whitelist hardens the write path end to end."""
    shard_iri, shard = stored_shard
    edits_before = len(shard.content_edits)
    with pytest.raises(ValueError):
        await edit_shard_content(
            shard_iri, path, "attacker-value", "did:key:zX", "r", None, store
        )
    after = await store.get(shard_iri)
    assert len(after.content_edits) == edits_before  # no phantom audit record


# ── canonical_content_hash (D-05) ────────────────────────────────────────────


def test_hash_is_64_hex_lowercase(sample_shard) -> None:
    h = canonical_content_hash(sample_shard)
    assert re.fullmatch(r"[0-9a-f]{64}", h)


def test_hash_same_instance_stable(sample_shard) -> None:
    assert canonical_content_hash(sample_shard) == canonical_content_hash(sample_shard)


def test_hash_changes_with_content(sample_shard) -> None:
    before = canonical_content_hash(sample_shard)
    set_field(sample_shard, "sense", "mutated")
    assert canonical_content_hash(sample_shard) != before


def test_hash_deterministic_across_instances() -> None:
    """CR-02 regression: identical content built at different wall-clock times
    must hash IDENTICALLY.

    ``transaction_time`` (``default_factory=datetime.now(UTC)``) is re-stamped on
    every construction; before the fix that volatile timestamp leaked into the
    ``model_dump`` payload and made two logically-identical shards hash
    differently. The content hash must bind the CONTENT only, so it is
    reproducible from the stored record (a hash that cannot be independently
    recomputed is not a content binding).
    """
    from tests.shards.conftest import _sample_shard

    first = _sample_shard(SimpleAssertionShard)
    time.sleep(0.01)  # guarantee a distinct wall-clock transaction_time
    second = _sample_shard(SimpleAssertionShard)

    # Sanity: the volatile field really does differ between the two instances.
    assert first.transaction_time != second.transaction_time
    # ...yet the CONTENT hash is identical (transaction_time excluded, CR-02).
    assert canonical_content_hash(first) == canonical_content_hash(second)


def test_hash_ignores_audit_log_and_storage_metadata(sample_shard) -> None:
    """CR-02: the content hash binds CONTENT, not the audit log, signatures, or
    bitemporal storage-window markers.

    Stamping the bitemporal window or appending a signature must NOT change the
    content hash — those are storage/attestation metadata, not content. (Editing
    actual content fields DOES change it — see ``test_hash_changes_with_content``.)
    """
    from datetime import UTC, datetime

    from folio_insights.shards import AttestedSignature

    before = canonical_content_hash(sample_shard)

    # Bitemporal window markers are storage metadata, not content.
    sample_shard.valid_time_start = datetime(2026, 1, 1, tzinfo=UTC)
    sample_shard.valid_time_end = datetime(2027, 1, 1, tzinfo=UTC)
    # Signatures are attestations OVER content, not content.
    sample_shard.signatures.append(AttestedSignature(did="did:key:zX"))

    assert canonical_content_hash(sample_shard) == before


# ── sign_attestation stub (D-05) ─────────────────────────────────────────────


def test_sign_attestation_is_unsigned_stub() -> None:
    sig = sign_attestation("did:key:zEd", "abc123")
    assert sig.action == "content_edit"
    assert sig.over_content_hash == "abc123"
    assert sig.signature == ""  # unmistakably unsigned (Phase 6 fills crypto)
    assert sig.did == "did:key:zEd"
    assert sig.signed_at is not None


# ── edit_shard_content (D-01, D-03) ──────────────────────────────────────────


async def test_edit_appends_one_edit_and_assigns(stored_shard, store) -> None:
    shard_iri, shard = stored_shard
    edit = await edit_shard_content(
        shard_iri, "sense", "edited-sense", "did:key:zX", "fix typo", None, store
    )
    assert edit.field_path == "sense"
    assert edit.old_value == "default sense"
    assert edit.new_value == "edited-sense"
    assert edit.editor_did == "did:key:zX"
    assert edit.rationale == "fix typo"
    # The pre-edit hash is captured in the signature slot.
    assert edit.signature.action == "content_edit"
    assert edit.signature.over_content_hash != ""  # a real pre-edit hash

    after = await store.get(shard_iri)
    assert after.sense == "edited-sense"
    assert len(after.content_edits) == 1
    assert after.content_edits[0] is edit


async def test_edit_old_value_is_pre_edit_value(stored_shard, store) -> None:
    """old_value captures the value BEFORE assignment (capture-before-assign)."""
    shard_iri, _ = stored_shard
    edit = await edit_shard_content(
        shard_iri, "reference", "urn:folio:concept/new", "did:key:zX", "r", None, store
    )
    assert edit.old_value == "urn:folio:concept/default"


async def test_edit_nested_triple_object(stored_shard, store) -> None:
    shard_iri, _ = stored_shard
    edit = await edit_shard_content(
        shard_iri, "triple.object", "urn:new:obj", "did:key:zX", "re-parent", None, store
    )
    assert edit.old_value == "o"
    after = await store.get(shard_iri)
    assert after.triple.object == "urn:new:obj"


async def test_edit_unknown_iri_raises(store) -> None:
    with pytest.raises(ValueError):
        await edit_shard_content(
            "urn:folio:shard/nothere", "sense", "x", "did:key:zX", "r", None, store
        )


async def test_two_sequential_edits_chain(stored_shard, store) -> None:
    shard_iri, _ = stored_shard
    await edit_shard_content(shard_iri, "sense", "s1", "did:key:zX", "r1", None, store)
    await edit_shard_content(shard_iri, "sense", "s2", "did:key:zX", "r2", None, store)
    after = await store.get(shard_iri)
    assert len(after.content_edits) == 2
    assert after.sense == "s2"
    # monotonic chain survives the authoritative forward-only validator.
    assert after.content_edits[0].edited_at <= after.content_edits[1].edited_at


# ── validate_shard post-edit hook (V5 / Pitfall 2) ───────────────────────────


def test_validate_shard_returns_revalidated_instance(sample_shard) -> None:
    out = validate_shard(sample_shard)
    assert isinstance(out, SimpleAssertionShard)
    assert out.shard_iri == sample_shard.shard_iri


def test_validate_shard_rejects_silent_wrong_type(stored_shard) -> None:
    """validate_assignment is OFF, so set_field lets a bad type through silently;
    validate_shard must re-run validation and reject it (the real guard, D-09)."""
    _, shard = stored_shard
    # confidence must be a float in [0, 1]; assign garbage via the silent setter.
    set_field(shard, "confidence", "not-a-float")
    with pytest.raises(Exception):
        validate_shard(shard)
