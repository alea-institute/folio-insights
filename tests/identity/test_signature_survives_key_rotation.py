"""EC3 — historical signatures survive key rotation (SEC-05, DID-04, Pitfall F2).

The exit-criterion-3 gate of Phase 6. Proves that a signature produced at time
``signed_at`` with key A continues to verify AFTER the operator rotates to a
NEW key B in the DID's current document — because the verifier resolves the
**signing-time** key via ``DidDocCache((did, signed_at)) -> snapshot``, not
the DID's *current* key.

Coverage:

* ``did:key`` — degenerate / trivial. The key IS the DID; a "rotation" is
  literally a new DID, not a new key under the same DID. We exercise this as a
  no-op rotation to prove the cache key still serves and current-vs-historical
  resolution is consistent.
* ``did:web`` — the real rotation case. Sign with key A → cache the
  snapshot at ``(did, signed_at)`` → swap the resolver's "current" did.json
  to advertise key B → assert:
  1. ``verify_attestation(..., cache=cache_with_snapshot)`` STILL returns True
     against the historical signature (resolves from the cached snapshot).
  2. A naive verifier that fetches the CURRENT doc and uses key B would fail —
     i.e. resolving the current doc yields key B's multibase, which is
     DIFFERENT from the snapshot's key A multibase. This proves the snapshot
     mechanism is what makes rotation survival work, not a bug-by-coincidence.

did:plc is exercised in the per-method test (recorded fixture, resolve/verify
ONLY — D-08 forbids the write path that would simulate a real plc rotation
end-to-end in this phase).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.identity import (
    DidDocSnapshot,
    did_key_from_public,
    resolve_did,
    sign_attestation,
    verify_attestation,
)
from folio_insights.identity.cache import InMemoryDidDocCache

pytestmark = pytest.mark.identity


_SIGNED_AT = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
_HASH = "c" * 64


# ── did:key — degenerate rotation (key IS the DID; cannot rotate) ──────────


@pytest.mark.asyncio
async def test_did_key_rotation_is_a_no_op() -> None:
    """did:key cannot rotate — historical and current resolution yield the same key.

    "Rotation" for did:key is a contradiction in terms: rotating the key means
    minting a NEW DID, not changing the key under an existing DID. We assert
    that resolving at the historical ``signed_at`` and at "now" yields the
    identical key material, so a verifier that ignores ``signed_at`` would
    still get the right answer for did:key (and only for did:key).
    """
    sk = Ed25519PrivateKey.generate()
    raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    did = did_key_from_public(raw)
    sig = sign_attestation(
        _HASH, sk, did, "extract",
        signing_key_id=f"{did}#{did.removeprefix('did:key:')}",
        did_doc_snapshot_at=_SIGNED_AT,
        now=_SIGNED_AT,
    )
    cache = InMemoryDidDocCache()
    # Historical verify (snapshot-resolved) — passes.
    assert await verify_attestation(_HASH, sig, cache=cache) is True
    # "Current" resolution yields the same key (the key IS the DID).
    current = await resolve_did(did)
    historical = await resolve_did(did, at=_SIGNED_AT)
    assert current.public_key_multibase == historical.public_key_multibase


# ── did:web — REAL rotation (the gate this test exists for) ────────────────


@pytest.mark.asyncio
async def test_did_web_signature_survives_key_rotation(
    ed25519_keypair_a,
    ed25519_keypair_b,
    did_web_doc_for,
) -> None:
    """EC3: a did:web signature signed with key A still verifies AFTER rotation to key B.

    Sequence:

    1. Cache the did.json snapshot with key A under ``(did, signed_at)``.
    2. Sign the content hash with key A (signing_key_id + did_doc_snapshot_at
       captured).
    3. The operator rotates: the LIVE http now returns a did.json with key B.
    4. Historical verify (via the cache) — passes (key A from snapshot).
    5. Resolving the CURRENT doc yields key B's multibase, DIFFERENT from
       the snapshot's key A multibase — proving the snapshot mechanism is
       load-bearing for rotation survival (not a bug-by-coincidence).
    """
    sk_a = ed25519_keypair_a
    sk_b = ed25519_keypair_b
    did = "did:web:example.org"

    # Pre-seed the cache with the snapshot AT signing time (real flow: the
    # signer computes this snapshot before signing and persists it through the
    # cache; here we pre-seed to model exactly that).
    doc_a = did_web_doc_for(did, sk_a)
    mb_a = doc_a["verificationMethod"][0]["publicKeyMultibase"]
    snapshot_a = DidDocSnapshot(
        did=did,
        fetched_at=_SIGNED_AT,
        verification_method_id=f"{did}#key-1",
        public_key_multibase=mb_a,
        raw_doc=doc_a,
    )
    cache = InMemoryDidDocCache()
    await cache.put((did, _SIGNED_AT), snapshot_a)

    # Sign with key A.
    sig = sign_attestation(
        _HASH, sk_a, did, "promote",
        signing_key_id=f"{did}#key-1",
        did_doc_snapshot_at=_SIGNED_AT,
        now=_SIGNED_AT,
    )

    # Rotation: the LIVE did.json now publishes key B (NOT key A).
    doc_b = did_web_doc_for(did, sk_b)
    fetch_calls: list[str] = []

    async def rotated_http(url: str) -> dict:
        fetch_calls.append(url)
        return doc_b

    # (1) Historical verify — passes (snapshot serves; no live fetch needed).
    ok = await verify_attestation(
        _HASH, sig, cache=cache, http=rotated_http
    )
    assert ok is True
    assert fetch_calls == [], "historical verify must NOT re-fetch the rotated current doc"

    # (2) Resolving the CURRENT doc (no snapshot for "now") yields key B.
    current_snap = await resolve_did(
        did, at=datetime(2026, 6, 1, tzinfo=UTC),
        cache=InMemoryDidDocCache(),  # fresh cache, force a fetch
        http=rotated_http,
    )
    assert current_snap.public_key_multibase != mb_a, (
        "current doc must publish key B; otherwise rotation is not actually "
        "exercised and the test is asserting a tautology"
    )

    # (3) Sanity: a naive verifier that resolves the CURRENT key and uses it
    # against the signed hash would fail — key B does not sign that signature.
    # We assert this by constructing a fresh cache that only has the CURRENT
    # doc (no signing-time snapshot) and observing verify returns False.
    fresh_cache = InMemoryDidDocCache()
    naive_sig = sig.model_copy(update={"did_doc_snapshot_at": datetime(2026, 6, 1, tzinfo=UTC)})
    naive_ok = await verify_attestation(
        _HASH, naive_sig, cache=fresh_cache, http=rotated_http
    )
    assert naive_ok is False, (
        "a naive verifier that resolves the CURRENT key (key B) after rotation "
        "must FAIL — this is what makes the snapshot mechanism load-bearing"
    )
