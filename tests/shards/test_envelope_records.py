"""U17 versioned shard-record adapter: migration, rejection, preservation.

Synthetic records only. A "legacy" record is a current dump with the U17
``schema_version`` stamp removed — exactly the unstamped shape shipped through
Phase 8.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.identity import (
    did_key_from_public,
    sign_attestation,
    verify_attestation,
)
from folio_insights.identity.cache import InMemoryDidDocCache
from folio_insights.revision import canonical_content_hash
from folio_insights.shards import (
    ENVELOPE_SCHEMA_VERSION,
    MalformedEnvelopeRecord,
    ShardEnvelope,
    SimpleAssertionShard,
    UnsupportedEnvelopeVersion,
    dump_shard_record,
    load_shard_record,
)
from folio_insights.shards.records import (
    IDENTITY_FIELDS,
    MIGRATIONS,
    NULLABLE_ENVELOPE_KEYS,
    EnvelopeMigration,
)

from tests.shards.conftest import _SUBTYPE_TABLE, _sample_shard

pytestmark = pytest.mark.shards


def _legacy_record(shard: ShardEnvelope, *, drop: tuple[str, ...] = ()) -> dict[str, Any]:
    data = json.loads(shard.model_dump_json())
    del data["schema_version"]
    for key in drop:
        del data[key]
    return data


def _signed_shard() -> tuple[ShardEnvelope, str]:
    sk = Ed25519PrivateKey.generate()
    raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    did = did_key_from_public(raw)
    shard = _sample_shard(SimpleAssertionShard, sense="synthetic signed sense")
    sig = sign_attestation(
        canonical_content_hash(shard),
        sk,
        did,
        "extract",
        signing_key_id=f"{did}#{did.removeprefix('did:key:')}",
        did_doc_snapshot_at=None,
        now=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    )
    shard.signatures.append(sig)
    return shard, did


# ── legacy v1 -> v2 migration ─────────────────────────────────────────────


@pytest.mark.parametrize("tag,cls", _SUBTYPE_TABLE)
def test_legacy_record_migrates_every_subtype(tag: str, cls: type[ShardEnvelope]) -> None:
    shard = _sample_shard(cls)
    legacy = _legacy_record(shard)
    loaded = load_shard_record(json.dumps(legacy).encode("utf-8"))
    assert type(loaded.shard) is cls
    assert loaded.source_schema_version == 1
    assert loaded.migrated is True
    assert loaded.content_preserved is True
    assert loaded.steps == ((1, 2),)
    assert loaded.shard.schema_version == ENVELOPE_SCHEMA_VERSION
    assert loaded.shard == shard


def test_migration_preserves_identity_and_explicit_nulls() -> None:
    shard = _sample_shard(SimpleAssertionShard, supersedes=None, valid_time_end=None)
    legacy = _legacy_record(shard)
    assert legacy["supersedes"] is None  # explicit null in the source
    loaded = load_shard_record(legacy)
    out = json.loads(dump_shard_record(loaded.shard))
    for key in IDENTITY_FIELDS:
        assert out[key] == legacy[key]
    assert "supersedes" in out and out["supersedes"] is None
    assert "valid_time_end" in out and out["valid_time_end"] is None


def test_migration_materializes_absent_nullable_keys_as_null() -> None:
    shard = _sample_shard(SimpleAssertionShard)
    legacy = _legacy_record(shard, drop=NULLABLE_ENVELOPE_KEYS)
    loaded = load_shard_record(legacy)
    out = json.loads(dump_shard_record(loaded.shard))
    for key in NULLABLE_ENVELOPE_KEYS:
        assert key in out and out[key] is None


def test_migration_never_mutates_input() -> None:
    legacy = _legacy_record(_sample_shard(SimpleAssertionShard), drop=("supersedes",))
    snapshot = json.loads(json.dumps(legacy))
    load_shard_record(legacy)
    assert legacy == snapshot


def test_original_bytes_preserved_exactly() -> None:
    legacy = _legacy_record(_sample_shard(SimpleAssertionShard))
    # Deliberately non-canonical whitespace and key order.
    raw = json.dumps(legacy, indent=3, sort_keys=False).encode("utf-8")
    loaded = load_shard_record(raw)
    assert loaded.original_bytes == raw
    as_text = load_shard_record(raw.decode("utf-8"))
    assert as_text.original_bytes == raw


# ── current-version records ───────────────────────────────────────────────


@pytest.mark.parametrize("tag,cls", _SUBTYPE_TABLE)
def test_current_record_round_trips(tag: str, cls: type[ShardEnvelope]) -> None:
    shard = _sample_shard(cls)
    raw = dump_shard_record(shard)
    loaded = load_shard_record(raw)
    assert loaded.migrated is False
    assert loaded.steps == ()
    assert loaded.source_schema_version == ENVELOPE_SCHEMA_VERSION
    assert loaded.shard == shard
    assert loaded.original_bytes == raw
    assert dump_shard_record(loaded.shard) == raw


@pytest.mark.parametrize("key", NULLABLE_ENVELOPE_KEYS)
def test_current_record_missing_nullable_key_is_malformed(key: str) -> None:
    data = json.loads(dump_shard_record(_sample_shard(SimpleAssertionShard)))
    del data[key]
    with pytest.raises(MalformedEnvelopeRecord, match="null is data"):
        load_shard_record(data)


# ── unsupported versions ──────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [0, -1, 3, 99, "2", "1", True, False, None, 2.0, [2]])
def test_unsupported_versions_rejected(bad: object) -> None:
    data = json.loads(dump_shard_record(_sample_shard(SimpleAssertionShard)))
    data["schema_version"] = bad
    with pytest.raises(UnsupportedEnvelopeVersion):
        load_shard_record(data)


def test_missing_migration_path_rejected() -> None:
    legacy = _legacy_record(_sample_shard(SimpleAssertionShard))
    with pytest.raises(UnsupportedEnvelopeVersion, match="no migration registered"):
        load_shard_record(legacy, migrations={})


@pytest.mark.parametrize("raw", [b"not json", b"[1, 2]", b"\xff\xfe", 42])
def test_malformed_input_rejected(raw: object) -> None:
    with pytest.raises(MalformedEnvelopeRecord):
        load_shard_record(raw)  # type: ignore[arg-type]


def test_identity_altering_step_refused() -> None:
    def _bad(record: dict[str, Any]) -> dict[str, Any]:
        record = MIGRATIONS[(1, 2)].apply(record)
        record["source_span"] = "rewritten span"
        return record

    legacy = _legacy_record(_sample_shard(SimpleAssertionShard))
    with pytest.raises(MalformedEnvelopeRecord, match="identity boundary"):
        load_shard_record(
            legacy,
            migrations={(1, 2): EnvelopeMigration(1, 2, False, _bad)},
        )


# ── signatures: preserved over unchanged content, never inherited ─────────


async def test_signature_still_verifies_after_content_preserving_migration() -> None:
    shard, _did = _signed_shard()
    cache = InMemoryDidDocCache()
    assert await verify_attestation(shard, shard.signatures[0], cache=cache)

    loaded = load_shard_record(_legacy_record(shard))
    assert loaded.content_preserved is True
    assert canonical_content_hash(loaded.shard) == canonical_content_hash(shard)
    assert await verify_attestation(loaded.shard, loaded.shard.signatures[0], cache=cache)


async def test_transformed_content_never_inherits_old_signature() -> None:
    shard, _did = _signed_shard()
    legacy = _legacy_record(shard)
    legacy["signatures"][0]["verified"] = True  # a stale cached annotation

    def _rewrite_sense(record: dict[str, Any]) -> dict[str, Any]:
        record = MIGRATIONS[(1, 2)].apply(record)
        record["sense"] = "transformed sense"
        return record

    loaded = load_shard_record(
        legacy,
        migrations={(1, 2): EnvelopeMigration(1, 2, False, _rewrite_sense)},
    )
    assert loaded.content_preserved is False
    sig = loaded.shard.signatures[0]
    # The append-only signature list is kept, but its cached flag is cleared
    # and it no longer verifies over the transformed content.
    assert sig.verified is None
    assert sig.over_content_hash != canonical_content_hash(loaded.shard)
    assert not await verify_attestation(loaded.shard, sig, cache=InMemoryDidDocCache())
    # The original signed bytes are still available for verification.
    original = json.loads(loaded.original_bytes)
    assert original["sense"] == "synthetic signed sense"


def test_legacy_load_clears_cached_verified_flags_even_when_preserving() -> None:
    shard, _did = _signed_shard()
    legacy = _legacy_record(shard)
    legacy["signatures"][0]["verified"] = True
    loaded = load_shard_record(legacy)
    assert loaded.shard.signatures[0].verified is None


def test_current_record_keeps_cached_verified_flag() -> None:
    shard, _did = _signed_shard()
    data = json.loads(dump_shard_record(shard))
    data["signatures"][0]["verified"] = True
    loaded = load_shard_record(data)
    assert loaded.shard.signatures[0].verified is True


@pytest.mark.parametrize(
    "name",
    [
        "example_a1_simple_assertion.json",
        "example_a2_conflicting_authorities.json",
        "example_a3_disputed_proposition.json",
    ],
)
def test_shipped_legacy_fixtures_load_through_adapter(name: str) -> None:
    from pathlib import Path

    raw = (Path(__file__).parent / "fixtures" / name).read_bytes()
    loaded = load_shard_record(raw)
    assert loaded.source_schema_version == 1
    assert loaded.original_bytes == raw
    source = json.loads(raw)
    assert loaded.shard.shard_iri == source["shard_iri"]
    assert loaded.shard.provenance_hash == source["provenance_hash"]
