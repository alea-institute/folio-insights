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
from folio_insights.identity.cache import InMemoryDidDocCache

pytestmark = pytest.mark.identity


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
    """did:web: sign with key A, verifier fetches did.json via fake http, round-trips OK."""
    sk = Ed25519PrivateKey.generate()
    did = "did:web:example.org"
    doc = did_web_doc_for(did, sk)

    async def fake_http(url: str) -> dict:
        assert url == "https://example.org/.well-known/did.json"
        return doc

    sig = sign_attestation(
        _hash_a(), sk, did, "promote",
        signing_key_id=f"{did}#key-1",
        did_doc_snapshot_at=_SIGNED_AT,
        now=_SIGNED_AT,
    )
    assert sig.signing_key_id == f"{did}#key-1"
    assert sig.did_doc_snapshot_at == _SIGNED_AT
    cache = InMemoryDidDocCache()
    ok = await verify_attestation(_hash_a(), sig, cache=cache, http=fake_http)
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
    """did:plc: sign with the key the recorded plc fixture publishes, verify round-trips."""
    sk = Ed25519PrivateKey.generate()
    did = "did:plc:abc123"
    doc = did_plc_doc_for(did, sk)

    async def fake_plc(did_arg: str, at) -> dict:
        return doc

    sig = sign_attestation(
        _hash_a(), sk, did, "supersede",
        signing_key_id=f"{did}#atproto",
        did_doc_snapshot_at=_SIGNED_AT,
        now=_SIGNED_AT,
    )
    cache = InMemoryDidDocCache()
    ok = await verify_attestation(
        _hash_a(), sig, cache=cache, plc_resolver=fake_plc
    )
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
        doc = did_web_doc_for(did, sk)

        async def http(_url: str) -> dict:  # type: ignore[no-redef]
            return doc

        key_id = f"{did}#key-1"
        snapshot_at = _SIGNED_AT
    else:  # did:plc
        did = "did:plc:abc123"
        doc = did_plc_doc_for(did, sk)

        async def plc_resolver(_did, _at) -> dict:  # type: ignore[no-redef]
            return doc

        key_id = f"{did}#atproto"
        snapshot_at = _SIGNED_AT

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
