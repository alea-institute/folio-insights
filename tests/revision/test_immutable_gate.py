"""IMMUTABLE_FIELD_PATHS gate (D-06) — raises BEFORE any mutation.

The gate is the SINGLE source of truth for what may not be edited: the 6
Pydantic-frozen identity fields, the identity-defining ``triple.subject`` /
``triple.predicate`` (the ``Triple`` submodel is mutable, so frozen=True does
NOT protect them — the gate is their only protection), and the append-only
lists ``content_edits`` / ``signatures``. ``triple.object`` is editable
(re-parenting, D-04) and must NOT be in the set.
"""
from __future__ import annotations

import pytest

from folio_insights.revision import IMMUTABLE_FIELD_PATHS, edit_shard_content

pytestmark = pytest.mark.shards

_IDENTITY_FIELDS = {
    "shard_iri",
    "provenance_hash",
    "source_uri",
    "source_span",
    "extracted_at",
    "first_extractor_did",
}


def test_immutable_set_contents() -> None:
    """The set is exactly the 6 identity fields + 2 triple parts + 2 lists (10)."""
    assert _IDENTITY_FIELDS <= IMMUTABLE_FIELD_PATHS
    assert "triple.subject" in IMMUTABLE_FIELD_PATHS
    assert "triple.predicate" in IMMUTABLE_FIELD_PATHS
    assert "content_edits" in IMMUTABLE_FIELD_PATHS
    assert "signatures" in IMMUTABLE_FIELD_PATHS
    assert len(IMMUTABLE_FIELD_PATHS) == 10


def test_triple_object_not_immutable() -> None:
    """triple.object is editable (re-parenting, D-04) — NOT in the gate set."""
    assert "triple.object" not in IMMUTABLE_FIELD_PATHS


@pytest.mark.parametrize(
    "path",
    sorted(_IDENTITY_FIELDS | {"triple.subject", "triple.predicate", "content_edits", "signatures"}),
)
async def test_gate_raises_before_mutation(stored_shard, store, path: str) -> None:
    """Editing any immutable path raises ValueError and appends NO edit."""
    shard_iri, shard = stored_shard
    edits_before = len(shard.content_edits)

    with pytest.raises(ValueError):
        await edit_shard_content(
            shard_iri, path, "attacker-value", "did:key:zX", "r", None, store
        )

    # Gate fired BEFORE any mutation: no edit appended on the stored shard.
    after = await store.get(shard_iri)
    assert len(after.content_edits) == edits_before


async def test_triple_subject_blocked_object_allowed(stored_shard, store) -> None:
    """triple.subject is gated; triple.object goes through (the D-04 asymmetry)."""
    shard_iri, shard = stored_shard

    with pytest.raises(ValueError):
        await edit_shard_content(
            shard_iri, "triple.subject", "new-subj", "did:key:zX", "r", None, store
        )

    edit = await edit_shard_content(
        shard_iri, "triple.object", "new-obj", "did:key:zX", "re-parent", None, store
    )
    assert edit.field_path == "triple.object"
    after = await store.get(shard_iri)
    assert after.triple.object == "new-obj"
    assert after.triple.subject == "s"  # untouched
