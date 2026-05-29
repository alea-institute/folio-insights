"""Per-method ed25519 sign/verify round-trip (Plan 06-02 Task 4).

Exhaustive coverage over the three DID methods Phase 6 ships:

* ``did:key`` — full sign + verify (the key IS the DID; cannot rotate).
* ``did:web`` — full sign + verify; resolver fetches via the injectable http
  seam against a recorded ``did.json`` fixture.
* ``did:plc`` — resolve + verify via the injectable ``plc_resolver`` seam
  against a recorded fixture (D-08: no PLC writes, no live network).

For each method the test asserts:

1. ``verify_attestation(sign_attestation(x)) == True`` (round-trip).
2. A tampered content hash fails verification (boolean ``False``, never
   raises — T-06-03 anti-spoofing).
3. ``AttestedSignature.signing_key_id`` and (where applicable)
   ``did_doc_snapshot_at`` are populated — DID-04 / SEC-05.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.identity import (
    did_key_from_public,
    sign_attestation,
    verify_attestation,
)
from folio_insights.identity.cache import DidDocSnapshot, InMemoryDidDocCache

pytestmark = pytest.mark.identity


# WR-06 fix support — pre-seed the DidDocCache with a snapshot built from the
# given key + did so the strict snapshot-required verifier path finds it.
# Before WR-06 the verifier fell through to ``http=fake_http`` on cache miss;
# the snapshot mechanism is now load-bearing (no silent F2 re-fetch).
async def _seed_snapshot(
    cache: InMemoryDidDocCache,
    *,
    did: str,
    sk: Ed25519PrivateKey,
    when: datetime,
    vm_fragment: str,
) -> None:
    """Insert a ``DidDocSnapshot`` for ``(did, when)`` carrying ``sk``'s public key."""
    raw_pub = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    mb = did_key_from_public(raw_pub).removeprefix("did:key:")
    snap = DidDocSnapshot(
        did=did,
        fetched_at=when,
        verification_method_id=f"{did}#{vm_fragment}",
        public_key_multibase=mb,
        raw_doc=None,
    )
    await cache.put((did, when), snap)


_SIGNED_AT = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def _hash_a() -> str:
    """A representative SHA-256 hex (the canonical_content_hash output shape)."""
    return "a" * 64


def _hash_b() -> str:
    """A DIFFERENT content hash, used as the "tampered" payload."""
    return "b" * 64


# ── did:key — full sign/verify (degenerate rotation: cannot happen) ────────


@pytest.mark.asyncio
async def test_did_key_sign_verify_round_trip() -> None:
    """did:key: sign over a hash, verify resolves the embedded key, round-trip OK."""
    sk = Ed25519PrivateKey.generate()
    raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    did = did_key_from_public(raw)
    mb = did.removeprefix("did:key:")
    sig = sign_attestation(
        _hash_a(),
        sk,
        did,
        "extract",
        signing_key_id=f"{did}#{mb}",
        did_doc_snapshot_at=None,  # key cannot rotate; snapshot is degenerate
        now=_SIGNED_AT,
    )
    assert sig.signature  # non-empty (real ed25519 signature)
    assert sig.signing_key_id == f"{did}#{mb}"
    assert sig.verified is None  # anti-spoofing default

    cache = InMemoryDidDocCache()
    assert await verify_attestation(_hash_a(), sig, cache=cache) is True


@pytest.mark.asyncio
async def test_did_key_tampered_hash_fails() -> None:
    """did:key: a tampered content hash fails verification (returns False, never raises)."""
    sk = Ed25519PrivateKey.generate()
    raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    did = did_key_from_public(raw)
    sig = sign_attestation(
        _hash_a(), sk, did, "extract",
        signing_key_id=f"{did}#{did.removeprefix('did:key:')}",
        did_doc_snapshot_at=None, now=_SIGNED_AT,
    )
    cache = InMemoryDidDocCache()
    # `verify_attestation(hash_b, sig)` — the recorded over_content_hash is
    # hash_a; passing hash_b as the canonical hash to verify against still
    # compares-and-verifies against sig.over_content_hash. So we tamper a
    # different way: alter the sig.over_content_hash to a value the signature
    # does NOT cover, then assert verify returns False.
    tampered = sig.model_copy(update={"over_content_hash": _hash_b()})
    assert await verify_attestation(_hash_b(), tampered, cache=cache) is False


@pytest.mark.asyncio
async def test_did_key_wrong_key_fails() -> None:
    """did:key: a signature produced by key X but the DID's embedded key is Y → False."""
    sk_x = Ed25519PrivateKey.generate()
    sk_y = Ed25519PrivateKey.generate()
    # The DID embeds Y's public key, but we sign with X — verify must fail.
    raw_y = sk_y.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    did_y = did_key_from_public(raw_y)
    sig = sign_attestation(
        _hash_a(), sk_x, did_y, "extract",
        signing_key_id=f"{did_y}#{did_y.removeprefix('did:key:')}",
        did_doc_snapshot_at=None, now=_SIGNED_AT,
    )
    cache = InMemoryDidDocCache()
    assert await verify_attestation(_hash_a(), sig, cache=cache) is False


# ── did:web — full sign/verify (resolver uses injected http) ───────────────


@pytest.mark.asyncio
async def test_did_web_sign_verify_round_trip(did_web_doc_for) -> None:
    """did:web: sign with key A, verifier uses pre-seeded snapshot, round-trips OK.

    WR-06: a historical did:web signature requires its snapshot to be in the
    cache; the verifier no longer silently fetches the CURRENT doc on cache
    miss. Seeding the cache with key A's snapshot at ``_SIGNED_AT`` is what
    a Phase-5/Phase-13 persistence layer would do at sign time.
    """
    sk = Ed25519PrivateKey.generate()
    did = "did:web:example.org"

    sig = sign_attestation(
        _hash_a(), sk, did, "promote",
        signing_key_id=f"{did}#key-1",
        did_doc_snapshot_at=_SIGNED_AT,
        now=_SIGNED_AT,
    )
    assert sig.signing_key_id == f"{did}#key-1"
    assert sig.did_doc_snapshot_at == _SIGNED_AT
    cache = InMemoryDidDocCache()
    await _seed_snapshot(cache, did=did, sk=sk, when=_SIGNED_AT, vm_fragment="key-1")
    ok = await verify_attestation(_hash_a(), sig, cache=cache)
    assert ok is True


@pytest.mark.asyncio
async def test_did_web_tampered_hash_fails(did_web_doc_for) -> None:
    """did:web: altering the signed-over hash fails verification."""
    sk = Ed25519PrivateKey.generate()
    did = "did:web:example.org"
    doc = did_web_doc_for(did, sk)

    async def fake_http(url: str) -> dict:
        return doc

    sig = sign_attestation(
        _hash_a(), sk, did, "promote",
        signing_key_id=f"{did}#key-1",
        did_doc_snapshot_at=_SIGNED_AT,
        now=_SIGNED_AT,
    )
    tampered = sig.model_copy(update={"over_content_hash": _hash_b()})
    cache = InMemoryDidDocCache()
    assert await verify_attestation(_hash_b(), tampered, cache=cache, http=fake_http) is False


# ── did:plc — resolve + verify via injected plc_resolver (recorded fixture) ─


@pytest.mark.asyncio
async def test_did_plc_sign_verify_round_trip(did_plc_doc_for) -> None:
    """did:plc: sign with the recorded fixture's key, verify resolves via pre-seeded snapshot.

    WR-06: did:plc shares the strict snapshot-required path with did:web —
    the cache must hold the snapshot at ``_SIGNED_AT`` or the verifier fails
    closed without consulting ``plc_resolver``.
    """
    sk = Ed25519PrivateKey.generate()
    did = "did:plc:abc123"

    sig = sign_attestation(
        _hash_a(), sk, did, "supersede",
        signing_key_id=f"{did}#atproto",
        did_doc_snapshot_at=_SIGNED_AT,
        now=_SIGNED_AT,
    )
    cache = InMemoryDidDocCache()
    await _seed_snapshot(cache, did=did, sk=sk, when=_SIGNED_AT, vm_fragment="atproto")
    ok = await verify_attestation(_hash_a(), sig, cache=cache)
    assert ok is True


@pytest.mark.asyncio
async def test_did_plc_tampered_hash_fails(did_plc_doc_for) -> None:
    """did:plc: altering the signed-over hash fails verification."""
    sk = Ed25519PrivateKey.generate()
    did = "did:plc:abc123"
    doc = did_plc_doc_for(did, sk)

    async def fake_plc(did_arg, at) -> dict:
        return doc

    sig = sign_attestation(
        _hash_a(), sk, did, "supersede",
        signing_key_id=f"{did}#atproto",
        did_doc_snapshot_at=_SIGNED_AT,
        now=_SIGNED_AT,
    )
    tampered = sig.model_copy(update={"over_content_hash": _hash_b()})
    cache = InMemoryDidDocCache()
    assert await verify_attestation(
        _hash_b(), tampered, cache=cache, plc_resolver=fake_plc
    ) is False


# ── Parametrized method-coverage proof (acceptance criterion explicit) ──────


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["did:key", "did:web", "did:plc"])
async def test_sign_verify_methods_parametrized(
    method: str,
    did_web_doc_for,
    did_plc_doc_for,
) -> None:
    """Parametrized round-trip over all three DID methods (acceptance criterion).

    Each branch asserts:
    * verify(sign(x)) is True
    * verify(sign(x), with tampered hash) is False
    * signing_key_id is populated (DID-04)
    """
    sk = Ed25519PrivateKey.generate()
    raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    cache = InMemoryDidDocCache()
    http = None
    plc_resolver = None

    if method == "did:key":
        did = did_key_from_public(raw)
        key_id = f"{did}#{did.removeprefix('did:key:')}"
        snapshot_at = None
    elif method == "did:web":
        did = "did:web:example.org"
        key_id = f"{did}#key-1"
        snapshot_at = _SIGNED_AT
        # WR-06: pre-seed the cache with the signing-time snapshot. http
        # remains None — the strict path doesn't consult it.
        await _seed_snapshot(
            cache, did=did, sk=sk, when=_SIGNED_AT, vm_fragment="key-1"
        )
    else:  # did:plc
        did = "did:plc:abc123"
        key_id = f"{did}#atproto"
        snapshot_at = _SIGNED_AT
        await _seed_snapshot(
            cache, did=did, sk=sk, when=_SIGNED_AT, vm_fragment="atproto"
        )

    sig = sign_attestation(
        _hash_a(), sk, did, "extract",
        signing_key_id=key_id,
        did_doc_snapshot_at=snapshot_at,
        now=_SIGNED_AT,
    )
    assert sig.signing_key_id  # DID-04 populated
    assert sig.signature

    ok = await verify_attestation(
        _hash_a(), sig, cache=cache, http=http, plc_resolver=plc_resolver
    )
    assert ok is True, f"verify(sign(x)) failed for {method}"

    tampered = sig.model_copy(update={"over_content_hash": _hash_b()})
    bad = await verify_attestation(
        _hash_b(), tampered, cache=cache, http=http, plc_resolver=plc_resolver
    )
    assert bad is False, f"tampered hash should fail verify for {method}"


# ── WR-06 — cold-cache historical did:web/did:plc fails CLOSED ─────────────


@pytest.mark.asyncio
async def test_verify_cold_cache_for_historical_didweb_fails_closed(
    did_web_doc_for,
) -> None:
    """WR-06: a cold cache + historical did:web signature must fail closed.

    Before the fix, the verifier would silently fetch the CURRENT did.json
    via the default ``_default_http_get`` (or the injected ``http``) on a
    cache miss — which after a rotation publishes a different key. The fix
    refuses to fetch when ``sig.did_doc_snapshot_at`` is non-None and the
    cache misses; verification returns False without ever touching the
    network.

    We assert two things:
    * verify returns False.
    * No ``http`` call was made.
    """
    sk = Ed25519PrivateKey.generate()
    did = "did:web:example.org"

    sig = sign_attestation(
        _hash_a(), sk, did, "promote",
        signing_key_id=f"{did}#key-1",
        did_doc_snapshot_at=_SIGNED_AT,
        now=_SIGNED_AT,
    )

    fetch_calls: list[str] = []

    async def tracking_http(url: str) -> dict:
        fetch_calls.append(url)
        # If WR-06 were absent, we'd return the doc here and verify would
        # succeed against the live key — exactly the silent F2 hole.
        return did_web_doc_for(did, sk)

    cache = InMemoryDidDocCache()  # COLD
    ok = await verify_attestation(_hash_a(), sig, cache=cache, http=tracking_http)
    assert ok is False, (
        "WR-06: cold cache for a historical did:web signature must fail "
        "closed without re-fetching the current doc"
    )
    assert fetch_calls == [], (
        f"WR-06: verifier must NOT touch the http seam on a cold-cache "
        f"historical verify; got fetches: {fetch_calls!r}"
    )


@pytest.mark.asyncio
async def test_verify_cold_cache_for_historical_didplc_fails_closed(
    did_plc_doc_for,
) -> None:
    """WR-06: cold cache + historical did:plc must fail closed (no plc_resolver call)."""
    sk = Ed25519PrivateKey.generate()
    did = "did:plc:abc123"

    sig = sign_attestation(
        _hash_a(), sk, did, "supersede",
        signing_key_id=f"{did}#atproto",
        did_doc_snapshot_at=_SIGNED_AT,
        now=_SIGNED_AT,
    )

    plc_calls: list[tuple] = []

    async def tracking_plc(did_arg: str, at) -> dict:
        plc_calls.append((did_arg, at))
        return did_plc_doc_for(did, sk)

    cache = InMemoryDidDocCache()  # COLD
    ok = await verify_attestation(
        _hash_a(), sig, cache=cache, plc_resolver=tracking_plc
    )
    assert ok is False
    assert plc_calls == [], (
        f"WR-06: verifier must NOT touch the plc_resolver seam on a cold-"
        f"cache historical verify; got calls: {plc_calls!r}"
    )
