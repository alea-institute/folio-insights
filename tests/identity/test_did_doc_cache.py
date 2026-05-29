"""DidDocCache + resolver branch tests (Plan 06-02 Task 2 — D-11, D-08).

Exercises the in-memory cache seam + the three-method resolver:

* ``InMemoryDidDocCache`` satisfies the ``DidDocCache`` ``Protocol`` (round-trips
  put/get; tuple key with a datetime second leg).
* ``resolve_did`` decodes did:key locally (no network, ``at`` ignored, key IS
  the DID — cannot rotate).
* ``resolve_did`` for did:web fetches via the injectable ``http`` seam, caches
  the snapshot under ``(did, at)``, and serves from the cache on a second call
  (no second fetch).
* ``resolve_did`` for did:plc uses the injectable ``plc_resolver`` seam (no
  live network), caches, and returns the resolved verificationMethod. NO write
  to the PLC directory is attempted at any point.
* Unknown method prefixes raise ``UnknownDidMethodError`` — the resolver never
  returns a wrong key silently.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.identity import (
    DidDocCache,
    DidDocSnapshot,
    InMemoryDidDocCache,
    UnknownDidMethodError,
    UnresolvableDidError,
    did_key_from_public,
    generate_keypair,
    resolve_did,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

pytestmark = pytest.mark.identity


# ── DidDocCache as a Protocol ────────────────────────────────────────────────


def test_inmemory_cache_satisfies_protocol() -> None:
    """``InMemoryDidDocCache`` is a structural ``DidDocCache``.

    ``DidDocCache`` is ``@runtime_checkable`` so the isinstance probe is
    legitimate; Phase 13 will substitute a different implementation behind the
    same Protocol with no caller-side change.
    """
    assert isinstance(InMemoryDidDocCache(), DidDocCache)


@pytest.mark.asyncio
async def test_inmemory_cache_roundtrips_tuple_key() -> None:
    """put((did, signed_at), snapshot) -> get returns the same snapshot; miss returns None."""
    cache = InMemoryDidDocCache()
    when = datetime(2026, 5, 1, tzinfo=UTC)
    snap = DidDocSnapshot(
        did="did:web:example.org",
        fetched_at=when,
        verification_method_id="did:web:example.org#key-1",
        public_key_multibase="z6MkfakeFAKEfake",
        raw_doc=None,
    )
    miss = await cache.get(("did:web:example.org", when))
    assert miss is None
    await cache.put(("did:web:example.org", when), snap)
    hit = await cache.get(("did:web:example.org", when))
    assert hit is snap
    # A DIFFERENT signed_at MUST miss — rotation safety: a current snapshot
    # cannot retro-validate a historical signature.
    other = datetime(2026, 5, 2, tzinfo=UTC)
    assert await cache.get(("did:web:example.org", other)) is None


# ── did:key resolver branch (no network, no rotation) ────────────────────────


@pytest.mark.asyncio
async def test_resolve_did_key_decodes_locally(tmp_path) -> None:
    """did:key resolves with no network and no cache (key IS the DID; cannot rotate)."""
    did = generate_keypair(tmp_path / "signer.jwk")
    snap = await resolve_did(did)
    assert snap.did == did
    # The verification method id is "<did>#<multibase>" by did:key convention.
    assert snap.verification_method_id.startswith(did + "#")
    # public_key_multibase recovers the same did:key when fed back through the
    # synthesis path used by the multibase decoder.
    assert snap.public_key_multibase == did.removeprefix("did:key:")


@pytest.mark.asyncio
async def test_resolve_did_key_ignores_signed_at(tmp_path) -> None:
    """did:key cannot rotate — different ``at`` values produce the same key."""
    did = generate_keypair(tmp_path / "signer.jwk")
    snap_a = await resolve_did(did, at=datetime(2026, 1, 1, tzinfo=UTC))
    snap_b = await resolve_did(did, at=datetime(2030, 1, 1, tzinfo=UTC))
    assert snap_a.public_key_multibase == snap_b.public_key_multibase


# ── did:web resolver branch (fetch + cache snapshot) ─────────────────────────


def _ed25519_pub_multibase(sk: Ed25519PrivateKey) -> str:
    """Build the ``z…`` multibase form of an Ed25519 private key's public half."""
    raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    did = did_key_from_public(raw)
    return did.removeprefix("did:key:")


@pytest.mark.asyncio
async def test_resolve_did_web_fetches_and_caches() -> None:
    """did:web fetches via the injectable http seam and caches under (did, at)."""
    sk = Ed25519PrivateKey.generate()
    mb = _ed25519_pub_multibase(sk)
    did = "did:web:example.org"
    expected_url = "https://example.org/.well-known/did.json"
    fetched_urls: list[str] = []
    doc = {
        "id": did,
        "verificationMethod": [
            {
                "id": f"{did}#key-1",
                "type": "Multikey",
                "controller": did,
                "publicKeyMultibase": mb,
            }
        ],
    }

    async def fake_http(url: str) -> dict:
        fetched_urls.append(url)
        return doc

    cache = InMemoryDidDocCache()
    signed_at = datetime(2026, 5, 1, 12, tzinfo=UTC)

    snap1 = await resolve_did(did, at=signed_at, cache=cache, http=fake_http)
    assert fetched_urls == [expected_url]
    assert snap1.public_key_multibase == mb
    assert snap1.verification_method_id == f"{did}#key-1"

    # Second call at the SAME signed_at — must serve from cache (no second fetch).
    snap2 = await resolve_did(did, at=signed_at, cache=cache, http=fake_http)
    assert fetched_urls == [expected_url]  # still only ONE fetch
    assert snap2.public_key_multibase == mb


@pytest.mark.asyncio
async def test_resolve_did_web_path_form_url() -> None:
    """did:web with a path-segmented identifier resolves to the path-form URL."""
    sk = Ed25519PrivateKey.generate()
    mb = _ed25519_pub_multibase(sk)
    did = "did:web:example.org:user:alice"
    expected_url = "https://example.org/user/alice/did.json"
    fetched_urls: list[str] = []
    doc = {
        "id": did,
        "verificationMethod": [
            {
                "id": f"{did}#key-1",
                "type": "Ed25519VerificationKey2020",
                "controller": did,
                "publicKeyMultibase": mb,
            }
        ],
    }

    async def fake_http(url: str) -> dict:
        fetched_urls.append(url)
        return doc

    await resolve_did(did, at=datetime(2026, 5, 1, tzinfo=UTC), http=fake_http)
    assert fetched_urls == [expected_url]


@pytest.mark.asyncio
async def test_resolve_did_web_jwk_form() -> None:
    """did:web doc with a publicKeyJwk (ed25519) resolves equivalently to multibase."""
    sk = Ed25519PrivateKey.generate()
    raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    import base64

    x_b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    did = "did:web:example.org"
    doc = {
        "id": did,
        "verificationMethod": [
            {
                "id": f"{did}#jwk-1",
                "type": "Ed25519VerificationKey2018",
                "controller": did,
                "publicKeyJwk": {"kty": "OKP", "crv": "Ed25519", "x": x_b64},
            }
        ],
    }

    async def fake_http(url: str) -> dict:
        return doc

    snap = await resolve_did(did, at=datetime(2026, 5, 1, tzinfo=UTC), http=fake_http)
    assert snap.verification_method_id == f"{did}#jwk-1"
    # The JWK branch produces the same canonical multibase as the multibase branch.
    expected_mb = _ed25519_pub_multibase(sk)
    assert snap.public_key_multibase == expected_mb


# ── did:plc resolver branch (injectable resolver — no live network) ─────────


@pytest.mark.asyncio
async def test_resolve_did_plc_uses_injected_resolver_and_caches() -> None:
    """did:plc uses the injected plc_resolver, caches, and never writes to the PLC."""
    sk = Ed25519PrivateKey.generate()
    mb = _ed25519_pub_multibase(sk)
    did = "did:plc:abc123"
    calls: list[tuple[str, datetime | None]] = []
    doc = {
        "id": did,
        "verificationMethod": [
            {
                "id": f"{did}#atproto",
                "type": "Multikey",
                "controller": did,
                "publicKeyMultibase": mb,
            }
        ],
    }

    async def fake_plc(did_arg: str, at: datetime | None) -> dict:
        calls.append((did_arg, at))
        return doc

    cache = InMemoryDidDocCache()
    when = datetime(2026, 5, 1, tzinfo=UTC)
    snap1 = await resolve_did(did, at=when, cache=cache, plc_resolver=fake_plc)
    assert calls == [(did, when)]
    assert snap1.public_key_multibase == mb

    # Cache hit on the second call at the same `at`.
    snap2 = await resolve_did(did, at=when, cache=cache, plc_resolver=fake_plc)
    assert calls == [(did, when)]  # still ONE call
    assert snap2.public_key_multibase == mb


# ── unknown method / malformed doc safety ────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_did_unknown_method_raises() -> None:
    """An unsupported DID method raises ``UnknownDidMethodError``."""
    with pytest.raises(UnknownDidMethodError):
        await resolve_did("did:example:foo")


@pytest.mark.asyncio
async def test_resolve_did_web_missing_vm_raises() -> None:
    """A did.json without an ed25519 verificationMethod raises ``UnresolvableDidError``."""
    async def fake_http(url: str) -> dict:
        return {"id": "did:web:example.org", "verificationMethod": []}

    with pytest.raises(UnresolvableDidError):
        await resolve_did(
            "did:web:example.org",
            at=datetime(2026, 5, 1, tzinfo=UTC),
            http=fake_http,
        )


# ── CR-02 — default did:plc resolver refuses historical ``at`` ──────────────


@pytest.mark.asyncio
async def test_default_plc_resolver_refuses_historical_at() -> None:
    """CR-02: the default did:plc resolver MUST refuse a non-None ``at``.

    The default impl only knows the current PLC head (``atproto.IdResolver``);
    returning that against a historical signed_at would be the F2 silent-
    wrong-key failure mode. The resolver fails closed with
    ``UnresolvableDidError`` to force the caller to inject a custom
    plc_resolver that walks the op log (D-08 / Pitfall F2).

    NB: the resolve_did dispatcher wraps the default resolver's raise in a
    generic UnresolvableDidError too, so either way the caller sees a
    fail-closed error rather than a silently-wrong key.
    """
    when = datetime(2026, 5, 1, tzinfo=UTC)
    with pytest.raises(UnresolvableDidError):
        await resolve_did("did:plc:abc123", at=when)


@pytest.mark.asyncio
async def test_default_plc_resolver_used_when_at_is_none(monkeypatch) -> None:
    """CR-02 boundary: the default plc resolver IS still used when ``at`` is None.

    The fix only refuses historical ``at`` — current-head resolution
    (``at=None``) still flows through the atproto.IdResolver fallback. We
    monkeypatch the import inside ``_default_plc_resolve`` so the test
    doesn't hit the real network.
    """
    from folio_insights.identity import resolver as _resolver

    class _FakeIdResolver:
        class _DidNs:
            def resolve(self, did: str):
                return {
                    "id": did,
                    "verificationMethod": [
                        {
                            "id": f"{did}#atproto",
                            "type": "Multikey",
                            "controller": did,
                            # A deterministic multibase the resolver can parse —
                            # generated from a known seed (this test cares about
                            # the at=None path, not the key contents).
                            "publicKeyMultibase": (
                                "z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"
                            ),
                        }
                    ],
                }
        did = _DidNs()

    class _FakeAtprotoModule:
        IdResolver = _FakeIdResolver

    # Patch the import target so ``from atproto import IdResolver`` inside the
    # default plc resolver picks up our fake.
    import sys
    monkeypatch.setitem(sys.modules, "atproto", _FakeAtprotoModule)

    snap = await _resolver.resolve_did("did:plc:abc123", at=None)
    assert snap.did == "did:plc:abc123"
    assert snap.public_key_multibase.startswith("z")


# ── CR-03 — did:web fetch hardening (HTTPS + response-size cap) ─────────────


@pytest.mark.asyncio
async def test_did_web_non_https_url_refused() -> None:
    """CR-03: a non-HTTPS URL must fail closed at the default http fetcher.

    We exercise the default fetcher directly. A custom fetcher that bypasses
    the scheme check is out of scope (operators choosing to do so accept the
    SSRF/MITM risk explicitly).
    """
    from folio_insights.identity.resolver import (
        _default_http_get,
        UnresolvableDidError as _Unresolvable,
    )

    with pytest.raises(_Unresolvable):
        await _default_http_get("http://example.org/.well-known/did.json")


@pytest.mark.asyncio
async def test_did_web_response_too_large_rejected() -> None:
    """CR-03: a response body exceeding 1 MiB must fail closed.

    We patch the default fetcher's httpx client with a fake that streams
    chunks past the cap, then assert ``UnresolvableDidError`` fires. This
    keeps the test offline and deterministic.
    """
    from folio_insights.identity.resolver import (
        _default_http_get,
        _MAX_DID_WEB_BYTES,
        UnresolvableDidError as _Unresolvable,
    )

    # Build a fake httpx.AsyncClient context manager whose .stream() yields
    # chunks adding up to just over the cap.
    class _FakeResp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            # Yield 1 KiB chunks until we cross the cap; +1 chunk pushes us
            # over and the function must abort.
            chunk = b"x" * 1024
            yielded = 0
            target = _MAX_DID_WEB_BYTES + 4096
            while yielded < target:
                yield chunk
                yielded += len(chunk)

    class _FakeStream:
        def __init__(self, resp):
            self._resp = resp

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url):
            return _FakeStream(_FakeResp())

    import folio_insights.identity.resolver as _resolver_mod

    # Patch httpx.AsyncClient inside the resolver module's import binding.
    orig_async_client = _resolver_mod.httpx.AsyncClient
    _resolver_mod.httpx.AsyncClient = lambda *a, **kw: _FakeClient()
    try:
        with pytest.raises(_Unresolvable):
            await _default_http_get("https://example.org/.well-known/did.json")
    finally:
        _resolver_mod.httpx.AsyncClient = orig_async_client


@pytest.mark.asyncio
async def test_did_web_response_within_cap_succeeds() -> None:
    """CR-03 boundary: a small valid response still flows through normally."""
    from folio_insights.identity.resolver import _default_http_get
    import folio_insights.identity.resolver as _resolver_mod

    payload = b'{"id": "did:web:example.org", "verificationMethod": []}'

    class _FakeResp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield payload

    class _FakeStream:
        def __init__(self, resp):
            self._resp = resp

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url):
            return _FakeStream(_FakeResp())

    orig_async_client = _resolver_mod.httpx.AsyncClient
    _resolver_mod.httpx.AsyncClient = lambda *a, **kw: _FakeClient()
    try:
        doc = await _default_http_get("https://example.org/.well-known/did.json")
        assert doc["id"] == "did:web:example.org"
    finally:
        _resolver_mod.httpx.AsyncClient = orig_async_client
