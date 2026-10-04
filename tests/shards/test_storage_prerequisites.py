"""Phase 13 U1 storage prerequisites: synthetic round trips, hashes, signatures.

Canary for the persistent journal (Phase 13 U2). The journal stores what
``load_shard_record`` returns (``original_bytes`` + ``source_schema_version``)
and writes new revisions with ``dump_shard_record``. These tests pin the
properties that storage relies on before any backend exists:

* every subtype round-trips byte-identically through a simulated journal row,
  for legacy (v1) and current (v2) records alike;
* the canonical content hash and the record bytes are stable (golden values),
  so a silent hashing or serialization drift cannot strand stored signatures;
* explicit nulls and identity fields survive repeated store/reload cycles;
* an original signature still verifies after the record is stored and reloaded;
* a stored row carrying an unsupported version is refused, never guessed.

Synthetic data only (``tests/shards/conftest.py`` builders); no book fixtures.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.identity import did_key_from_public, sign_attestation, verify_attestation
from folio_insights.identity.cache import InMemoryDidDocCache
from folio_insights.revision import canonical_content_hash
from folio_insights.shards import (
    ENVELOPE_SCHEMA_VERSION,
    ShardEnvelope,
    SimpleAssertionShard,
    UnsupportedEnvelopeVersion,
    dump_shard_record,
    load_shard_record,
)
from folio_insights.shards.records import IDENTITY_FIELDS, NULLABLE_ENVELOPE_KEYS

from tests.shards.conftest import _SUBTYPE_TABLE, _sample_shard

pytestmark = pytest.mark.shards

_FIXED_TT = datetime(2026, 4, 24, 12, 30, tzinfo=UTC)

# Golden values captured on 2026-10-03 (U1). A change here means the canonical
# hash or the stored record bytes moved: that requires an envelope schema
# version bump plus a registered migration, never a silent golden update.
_GOLDEN: dict[str, tuple[str, str]] = {
    "simple_assertion": (
        "25a556b88edb9d153c72d1ffca15a80f6118cd4229a0520322ffd00b9765c322",
        "f14b7aee13de1aefebf712dbcd5294799a4f5319c4145b51d8d162c287e9010e",
    ),
    "disputed_proposition": (
        "2c55ecc4025632f23c72dd47a3fa283507443ddc75f63e2e42b54d99a5d886cc",
        "b3f5ef572fe18cd276e8ae2930655343f3011c5ce98063a0d7d99f5dd543e18c",
    ),
    "conflicting_authorities": (
        "9fd4a7718a112146d0558ceeb064eaf1b7ec0a8a340e8c7206c74df6f86f3bf0",
        "c0d4caf8690e9243112d572a504b079548d8a6c797fa63f4d156a766cd126778",
    ),
    "gloss": (
        "c6449e0da46865f144b67707115a5723b0c186aea73e169672c6fe20cce10546",
        "aac92435c1961d2eb9bcebe1a24a7e93347fb69a0e893da727f244077163f0e2",
    ),
    "hypothesis": (
        "6f90f002ebe632379d73c14ca02082c52cdaf9e106c2e7defa2483693fc2ef38",
        "c8c67f6684a1971bdb81bf065bbf7712161d96bca5f1ad262797487eeff0e016",
    ),
}


@dataclass(frozen=True)
class _JournalRow:
    """What the U2 journal persists for one shard record."""

    payload: bytes
    original_bytes: bytes
    source_schema_version: int


def _store(raw: bytes | dict[str, Any]) -> _JournalRow:
    loaded = load_shard_record(raw)
    return _JournalRow(
        payload=dump_shard_record(loaded.shard),
        original_bytes=loaded.original_bytes,
        source_schema_version=loaded.source_schema_version,
    )


def _legacy_bytes(shard: ShardEnvelope) -> bytes:
    data = json.loads(dump_shard_record(shard))
    del data["schema_version"]
    return json.dumps(data, indent=2).encode("utf-8")


def _signing_identity() -> tuple[Ed25519PrivateKey, str]:
    sk = Ed25519PrivateKey.generate()
    raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return sk, did_key_from_public(raw)


@pytest.mark.parametrize("tag,cls", _SUBTYPE_TABLE)
def test_golden_canonical_hash_and_record_bytes(tag: str, cls: type[ShardEnvelope]) -> None:
    shard = _sample_shard(cls, transaction_time=_FIXED_TT)
    content_hash, record_sha = _GOLDEN[tag]
    assert canonical_content_hash(shard) == content_hash
    assert hashlib.sha256(dump_shard_record(shard)).hexdigest() == record_sha


@pytest.mark.parametrize("tag,cls", _SUBTYPE_TABLE)
@pytest.mark.parametrize("legacy", [False, True], ids=["current", "legacy"])
def test_journal_round_trip_is_byte_stable(
    tag: str, cls: type[ShardEnvelope], legacy: bool
) -> None:
    shard = _sample_shard(cls, transaction_time=_FIXED_TT)
    raw = _legacy_bytes(shard) if legacy else dump_shard_record(shard)

    row = _store(raw)
    assert row.original_bytes == raw
    assert row.source_schema_version == (1 if legacy else ENVELOPE_SCHEMA_VERSION)

    # Reading the payload back is a current-version, no-migration load.
    reloaded = load_shard_record(row.payload)
    assert reloaded.migrated is False
    assert reloaded.shard == shard
    assert dump_shard_record(reloaded.shard) == row.payload
    assert canonical_content_hash(reloaded.shard) == canonical_content_hash(shard)

    # Replaying the original bytes is deterministic: same shard, same version.
    replayed = load_shard_record(row.original_bytes)
    assert replayed.shard == reloaded.shard
    assert replayed.source_schema_version == row.source_schema_version

    # A second store/reload cycle changes nothing.
    assert _store(row.payload).payload == row.payload


def test_identity_and_explicit_nulls_survive_repeated_cycles() -> None:
    shard = _sample_shard(
        SimpleAssertionShard,
        transaction_time=_FIXED_TT,
        supersedes=None,
        valid_time_start=None,
    )
    legacy = json.loads(_legacy_bytes(shard))
    for key in ("valid_time_end", "superseded_by"):
        del legacy[key]  # absent in the legacy source
    row = _store(legacy)
    for _ in range(3):
        row = _store(row.payload)
    out = json.loads(row.payload)
    for key in NULLABLE_ENVELOPE_KEYS:
        assert key in out and out[key] is None
    for key in IDENTITY_FIELDS:
        assert out[key] == legacy[key]


async def test_original_signature_verifies_after_store_and_reload() -> None:
    sk, did = _signing_identity()
    shard = _sample_shard(SimpleAssertionShard, sense="synthetic signed content")
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
    cache = InMemoryDidDocCache()

    row = _store(_legacy_bytes(shard))
    reloaded = load_shard_record(row.payload).shard
    assert await verify_attestation(reloaded, reloaded.signatures[0], cache=cache)
    original = load_shard_record(row.original_bytes).shard
    assert await verify_attestation(original, original.signatures[0], cache=cache)


async def test_changed_signed_content_fails_old_signature() -> None:
    sk, did = _signing_identity()
    shard = _sample_shard(SimpleAssertionShard, sense="synthetic signed content")
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
    row = _store(dump_shard_record(shard))

    tampered = json.loads(row.payload)
    tampered["sense"] = "synthetic changed content"
    changed = _store(tampered)
    loaded = load_shard_record(changed.payload).shard
    assert not await verify_attestation(
        loaded, loaded.signatures[0], cache=InMemoryDidDocCache()
    )


@pytest.mark.parametrize("version", [0, 3, 99, "2", True])
def test_stored_row_with_unsupported_version_is_refused(version: object) -> None:
    data = json.loads(dump_shard_record(_sample_shard(SimpleAssertionShard)))
    data["schema_version"] = version
    with pytest.raises(UnsupportedEnvelopeVersion):
        _store(json.dumps(data).encode("utf-8"))
