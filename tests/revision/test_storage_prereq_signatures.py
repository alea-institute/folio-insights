"""Phase 13 U1: a revision never inherits the signature over earlier content.

Storage keeps every revision; signatures are append-only and outside the
content hash. After a content edit, the ORIGINAL extract signature must fail
verification against the revised content, yet still verify against the
historical state that ``get_shard_at`` reconstructs. Synthetic data only.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.identity import did_key_from_public, sign_attestation, verify_attestation
from folio_insights.identity.cache import InMemoryDidDocCache
from folio_insights.revision import (
    InMemoryShardStore,
    canonical_content_hash,
    edit_shard_content,
    get_shard_at,
)
from folio_insights.shards import SimpleAssertionShard, dump_shard_record, load_shard_record

from tests.shards.conftest import _sample_shard


async def test_revision_fails_old_signature_but_history_still_verifies() -> None:
    sk = Ed25519PrivateKey.generate()
    did = did_key_from_public(
        sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
    )
    shard = _sample_shard(SimpleAssertionShard, sense="synthetic original sense")
    shard.signatures.append(
        sign_attestation(
            canonical_content_hash(shard),
            sk,
            did,
            "extract",
            signing_key_id=f"{did}#{did.removeprefix('did:key:')}",
            did_doc_snapshot_at=None,
            now=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
    )
    store = InMemoryShardStore()
    await store.put(shard.shard_iri, shard)
    original_sig = shard.signatures[0]
    cache = InMemoryDidDocCache()

    await edit_shard_content(
        shard.shard_iri,
        "sense",
        "synthetic revised sense",
        did,
        "synthetic revision",
        sk,
        store,
    )
    current = await store.get(shard.shard_iri)
    assert current is not None
    # Round-trip the revision through the stored-record adapter, as the journal will.
    current = load_shard_record(dump_shard_record(current)).shard
    assert current.signatures[0] == original_sig
    assert not await verify_attestation(current, original_sig, cache=cache)
    # The edit's own signature commits to the pre-edit hash, not the new content.
    assert current.content_edits[-1].signature.over_content_hash == canonical_content_hash(
        shard
    )

    historical = await get_shard_at(shard.shard_iri, shard.extracted_at, store)
    assert historical is not None
    assert historical.sense == "synthetic original sense"
    assert await verify_attestation(historical, original_sig, cache=cache)


@pytest.mark.parametrize("field_path", ["shard_iri", "schema_version", "signatures"])
async def test_identity_and_signature_paths_stay_immutable(field_path: str) -> None:
    shard = _sample_shard(SimpleAssertionShard)
    store = InMemoryShardStore()
    await store.put(shard.shard_iri, shard)
    before = dump_shard_record(shard)
    with pytest.raises(ValueError, match="immutable"):
        await edit_shard_content(
            shard.shard_iri, field_path, "x", "did:key:zEditor", "r", None, store
        )
    stored = await store.get(shard.shard_iri)
    assert stored is not None and dump_shard_record(stored) == before
