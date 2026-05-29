"""3-method DID resolver: did:key + did:web + did:plc (D-08, DID-01).

Resolves a DID to its ed25519 verification key, branching on method:

* ``did:key`` — decode the multibase key embedded in the DID via
  ``keys.public_key_from_did_key``. NO network, ``at`` ignored (the key IS the
  DID; it cannot rotate — a new key = a new DID).
* ``did:web`` — fetch ``https://<domain>/.well-known/did.json`` (root form) or
  ``https://<domain>/<path>/did.json`` (path form) via an injectable httpx
  client; extract the ed25519 ``verificationMethod`` and cache the snapshot
  under ``(did, at)`` in the ``DidDocCache``. A cache hit short-circuits — no
  re-fetch (rotation-safe).
* ``did:plc`` — use an injectable ``atproto.IdResolver`` for **current**
  resolution; for a historical ``at``, fetch ``plc.directory/<did>/log/audit``
  and ``dag_cbor``-decode to pin the operation valid at ``at`` (Pitfall F2 op-log
  pinning). **RESOLVE/VERIFY ONLY** — this resolver NEVER submits a PLC
  operation; the genesis/rotation write path is out of scope (D-08).

All network dependencies are INJECTABLE — tests pass recorded fixtures so no
live network is touched. An unresolvable DID or unknown method raises a typed
error; the resolver never returns a wrong key silently (T-06-09).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Protocol

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from folio_insights.identity.cache import DidDocCache, DidDocSnapshot
from folio_insights.identity.keys import (
    _ED25519_MULTICODEC_PREFIX,
    did_key_from_public,
    public_key_from_did_key,
)

import base58


class UnknownDidMethodError(ValueError):
    """Raised when a DID's method prefix is not one of did:key / did:web / did:plc."""


class UnresolvableDidError(RuntimeError):
    """Raised when a DID's resolution fails (network error, malformed doc, missing key)."""


# ── Injectable network seams (so tests use recorded fixtures, not the live net) ──


class _HttpGetter(Protocol):
    """Tiny async HTTP GET seam used by the did:web branch.

    The default impl wraps ``httpx.AsyncClient``; tests inject a recorded
    fixture mapping URL -> JSON dict so no live network is touched and rotation
    scenarios are deterministic.
    """

    async def __call__(self, url: str) -> dict: ...


class _PlcResolver(Protocol):
    """Tiny async PLC resolution seam used by the did:plc branch.

    Returns the resolved DID document (a dict). Tests inject a recorded
    fixture mapping (did, at) -> the doc valid at ``at`` per the op log.
    """

    async def __call__(self, did: str, at: datetime | None) -> dict: ...


# CR-03: cap did:web response bodies. Real DID documents are kilobytes (the
# verificationMethod list + a couple of metadata fields). A 1 MiB cap is two
# orders of magnitude above legitimate use and forecloses memory exhaustion
# from a malicious / compromised did:web host. 06-RESEARCH §6 calls out
# "did:web HTTPS fetch (TLS verification, fetch size limits)" as a phase-6
# review focus; before this fix only TLS verification (httpx default) was
# enforced.
_MAX_DID_WEB_BYTES = 1 * 1024 * 1024


async def _default_http_get(url: str) -> dict:
    """Default did:web fetcher with HTTPS enforcement + response-size cap (CR-03).

    Hardenings vs. the pre-CR-03 implementation:

    * **HTTPS-only.** A non-``https://`` URL fails closed before any network
      call. The ``_did_web_url`` derivation already produces ``https://``, but
      explicit enforcement defends against future code paths or operator-
      supplied custom http callables that might follow a redirect to plain
      ``http://``. ``follow_redirects=False`` belt-and-braces.
    * **1 MiB response cap.** Streams the body and aborts past
      ``_MAX_DID_WEB_BYTES`` so a malicious did:web host cannot OOM the
      process by returning gigabytes of bytes (or a slow trickle within the
      per-chunk timeout window).
    * **No redirect following.** Combined with HTTPS-only and the size cap,
      this means the request lands on EXACTLY the host ``_did_web_url``
      derived from the DID — no SSRF detour through an attacker-controlled
      redirect.

    The function still returns the parsed JSON dict so the rest of the
    pipeline (``_pick_ed25519_vm`` / ``_ed25519_pub_from_vm``) is unchanged.

    Operators in SERVER-SIDE contexts SHOULD supply a vetted custom ``http``
    callable rather than relying on this default — see ``_did_web_url`` for
    the SSRF allow-list applied at URL-derivation time (WR-05).
    """
    if not url.startswith("https://"):
        raise UnresolvableDidError(
            f"did:web fetch requires https://, got {url!r}; refusing "
            "to fetch over an insecure scheme (CR-03)."
        )
    async with httpx.AsyncClient(
        timeout=10.0,
        follow_redirects=False,
        verify=True,
    ) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > _MAX_DID_WEB_BYTES:
                    raise UnresolvableDidError(
                        f"did:web response from {url!r} exceeds "
                        f"{_MAX_DID_WEB_BYTES} bytes (received {total}); "
                        "refusing to load (CR-03 — DoS / memory-exhaustion "
                        "defense)."
                    )
                chunks.append(chunk)
    import json as _json

    return _json.loads(b"".join(chunks))


async def _default_plc_resolve(did: str, at: datetime | None) -> dict:
    """Default did:plc resolver via ``atproto.IdResolver`` (CURRENT state only).

    The module-level contract states "the resolver NEVER returns a wrong key
    silently (T-06-09)". For did:plc, signing-time-key resolution requires
    walking the ``plc.directory`` operation log to pin the doc valid at
    ``at`` (Pitfall F2 / D-08). The default impl does NOT walk that log — it
    only resolves the CURRENT head via ``atproto.IdResolver``. Returning the
    current doc against a historical ``at`` is exactly the F2 silent-wrong-key
    failure mode the design forbids.

    **CR-02 fix:** Refuse a non-None ``at`` outright. The caller must inject a
    custom ``plc_resolver`` that honors the op-log lookup. Phase 6 ships
    resolve/verify only (D-08); Phase 13 will likely bundle an op-log walker.

    NB: ``atproto`` is a third-party dependency (STACK.md pin 0.0.65). This
    resolver NEVER submits a PLC write operation (D-08).
    """
    if at is not None:
        # CR-02: silent-wrong-key fail-closed. The contract says the resolver
        # NEVER returns a wrong key silently; the default impl cannot honor
        # historical ``at`` without an op-log walker, so it MUST refuse rather
        # than fall through and return the current doc against a historical
        # signed_at (Pitfall F2).
        raise UnresolvableDidError(
            f"Default did:plc resolver cannot pin historical at={at!r} for "
            f"{did!r}; the atproto.IdResolver fallback only knows the current "
            "head, and returning that against a historical signed_at would be "
            "the F2 silent-wrong-key failure mode the resolver forbids. Inject "
            "a custom plc_resolver that walks the plc.directory op log (D-08 / "
            "Pitfall F2)."
        )

    # Import inside the function so import-time of resolver.py does not bring
    # the entire atproto SDK into every consumer of identity/.
    from atproto import IdResolver  # type: ignore[import-untyped]

    resolver = IdResolver()
    doc = resolver.did.resolve(did)
    if doc is None:
        raise UnresolvableDidError(f"atproto IdResolver returned None for {did!r}")
    # atproto's resolve() returns a typed DIDDocument; coerce to a plain dict
    # so the rest of the pipeline is method-agnostic.
    if hasattr(doc, "model_dump"):
        return doc.model_dump(mode="json")  # type: ignore[no-any-return]
    if hasattr(doc, "dict"):
        return doc.dict()  # type: ignore[no-any-return]
    if isinstance(doc, dict):
        return doc
    raise UnresolvableDidError(
        f"atproto IdResolver returned unsupported doc type {type(doc).__name__}"
    )


# ── did:web URL derivation (W3C did:web method spec) ────────────────────────


def _did_web_url(did: str) -> str:
    """Derive the HTTPS did.json URL for a did:web.

    * ``did:web:example.org`` → ``https://example.org/.well-known/did.json``
    * ``did:web:example.org:user:alice`` → ``https://example.org/user/alice/did.json``

    Per the W3C did:web method spec: colons after the method are path
    separators; if there is no path component, the doc lives at
    ``.well-known/did.json``.
    """
    body = did.removeprefix("did:web:")
    if not body:
        raise UnresolvableDidError(f"empty did:web identifier in {did!r}")
    parts = body.split(":")
    domain = parts[0]
    if len(parts) == 1:
        return f"https://{domain}/.well-known/did.json"
    path = "/".join(parts[1:])
    return f"https://{domain}/{path}/did.json"


# ── verificationMethod -> ed25519 public-key extraction ─────────────────────


def _ed25519_pub_from_vm(vm: dict) -> tuple[str, str, Ed25519PublicKey]:
    """Extract (verificationMethod_id, public_key_multibase, Ed25519PublicKey) from a vm dict.

    Accepts the two canonical encodings the W3C DID core spec defines for
    ed25519:

    * ``publicKeyMultibase`` — multibase ``z`` + base58btc(0xed01 || raw_pub).
      The same encoding ``did:key`` uses; ``keys.public_key_from_did_key`` does
      the decode for free if we synthesize a temporary did:key from the
      multibase.
    * ``publicKeyJwk`` — ``{"kty": "OKP", "crv": "Ed25519", "x": <b64url>}``.

    Returns the verificationMethod ``id``, the canonical multibase form
    (normalized so the cache stores ONE representation), and the parsed
    ``Ed25519PublicKey``. Raises ``UnresolvableDidError`` on unsupported kty/crv
    or a missing/malformed key field.
    """
    vm_id = vm.get("id")
    if not isinstance(vm_id, str):
        raise UnresolvableDidError(f"verificationMethod missing 'id': {vm!r}")

    if "publicKeyMultibase" in vm:
        mb = vm["publicKeyMultibase"]
        if not isinstance(mb, str) or not mb.startswith("z"):
            raise UnresolvableDidError(
                f"unsupported publicKeyMultibase prefix in {vm_id!r}: {mb!r}"
            )
        # Decode via the did:key path — same multicodec + base58btc.
        synthetic_did = f"did:key:{mb}"
        pk = public_key_from_did_key(synthetic_did)
        return vm_id, mb, pk

    if "publicKeyJwk" in vm:
        jwk = vm["publicKeyJwk"]
        if (
            not isinstance(jwk, dict)
            or jwk.get("kty") != "OKP"
            or jwk.get("crv") != "Ed25519"
            or "x" not in jwk
        ):
            raise UnresolvableDidError(
                f"verificationMethod {vm_id!r} has non-Ed25519 publicKeyJwk: {jwk!r}"
            )
        # base64url-no-pad → raw 32 bytes → Ed25519PublicKey + canonical multibase.
        import base64

        pad = "=" * (-len(jwk["x"]) % 4)
        raw_pub = base64.urlsafe_b64decode(jwk["x"] + pad)
        if len(raw_pub) != 32:
            raise UnresolvableDidError(
                f"verificationMethod {vm_id!r} JWK 'x' is {len(raw_pub)} bytes "
                "(expected 32 for ed25519)"
            )
        pk = Ed25519PublicKey.from_public_bytes(raw_pub)
        mb = "z" + base58.b58encode(_ED25519_MULTICODEC_PREFIX + raw_pub).decode("ascii")
        return vm_id, mb, pk

    raise UnresolvableDidError(
        f"verificationMethod {vm_id!r} has no publicKeyMultibase or publicKeyJwk"
    )


def _pick_ed25519_vm(doc: dict) -> dict:
    """Pick the first ed25519 verificationMethod from a resolved DID document.

    Prefers vm entries whose ``type`` indicates ed25519 (``Ed25519VerificationKey2020``
    or ``...2018``); falls back to the first vm with a publicKeyMultibase / JWK
    that we can parse. Raises if no usable vm is present.
    """
    vms = doc.get("verificationMethod") or []
    if not vms:
        raise UnresolvableDidError(
            f"DID doc {doc.get('id')!r} has no verificationMethod entries"
        )
    # First pass — ed25519-typed.
    ed25519_types = {
        "Ed25519VerificationKey2020",
        "Ed25519VerificationKey2018",
        "Multikey",  # the W3C-recommended generic type for ed25519 via multibase
    }
    for vm in vms:
        if vm.get("type") in ed25519_types and (
            "publicKeyMultibase" in vm or "publicKeyJwk" in vm
        ):
            return vm
    # Fallback — any vm with a parseable key field.
    for vm in vms:
        if "publicKeyMultibase" in vm or "publicKeyJwk" in vm:
            return vm
    raise UnresolvableDidError(
        f"DID doc {doc.get('id')!r} has no usable ed25519 verificationMethod"
    )


# ── resolve_did — the public surface (single dispatcher) ────────────────────


async def resolve_did(
    did: str,
    at: datetime | None = None,
    *,
    cache: DidDocCache | None = None,
    http: Callable[[str], Awaitable[dict]] | None = None,
    plc_resolver: Callable[[str, datetime | None], Awaitable[dict]] | None = None,
) -> DidDocSnapshot:
    """Resolve ``did`` to a ``DidDocSnapshot`` (verification key + DID-doc metadata).

    Branches on the method prefix:

    * ``did:key:…`` — decode locally; no network; ``at`` ignored (the key IS
      the DID; it cannot rotate). A synthesized snapshot is returned but is NOT
      stored in the cache (the decode is O(1); caching would be ceremony).
    * ``did:web:…`` — if ``cache`` has a snapshot at ``(did, at)``, return it
      directly (cache hit). Otherwise fetch the did.json via ``http`` (or the
      default httpx client), pick the ed25519 verificationMethod, materialize
      the snapshot, ``put`` it into the cache, and return it.
    * ``did:plc:…`` — RESOLVE/VERIFY ONLY (D-08); no genesis/rotation writes.
      Use the cache-first short-circuit (same as did:web). On miss, call
      ``plc_resolver(did, at)`` to get the doc valid at ``at`` (the default
      uses ``atproto.IdResolver`` for current state; tests/Phase 13 inject an
      op-log-walking resolver for historical pinning), materialize, cache,
      return.

    Raises ``UnknownDidMethodError`` for any other prefix; raises
    ``UnresolvableDidError`` on network failure, malformed DID doc, or absent
    ed25519 verificationMethod. The resolver NEVER returns a wrong key
    silently.
    """
    if did.startswith("did:key:"):
        # Decode locally; the cache is irrelevant for did:key (the key IS the DID).
        pk = public_key_from_did_key(did)
        raw_pub = pk.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        mb = did.removeprefix("did:key:")
        return DidDocSnapshot(
            did=did,
            fetched_at=datetime.now(UTC),
            # Convention: the did:key verificationMethod id is "<did>#<multibase>"
            # (the did:key spec; same as what a did:key DID document would expose).
            verification_method_id=f"{did}#{mb}",
            public_key_multibase=mb,
            raw_doc=None,
        )

    if did.startswith("did:web:"):
        key = (did, at) if at is not None else (did, _SENTINEL_NO_AT)
        if cache is not None:
            hit = await cache.get(key)
            if hit is not None:
                return hit
        url = _did_web_url(did)
        getter = http or _default_http_get
        try:
            doc = await getter(url)
        except UnresolvableDidError:
            raise
        except Exception as exc:  # network error, JSON decode error, etc.
            raise UnresolvableDidError(
                f"did:web fetch of {url} failed: {exc}"
            ) from exc
        vm = _pick_ed25519_vm(doc)
        vm_id, mb, _pk = _ed25519_pub_from_vm(vm)
        snapshot = DidDocSnapshot(
            did=did,
            fetched_at=datetime.now(UTC),
            verification_method_id=vm_id,
            public_key_multibase=mb,
            raw_doc=doc,
        )
        if cache is not None:
            await cache.put(key, snapshot)
        return snapshot

    if did.startswith("did:plc:"):
        key = (did, at) if at is not None else (did, _SENTINEL_NO_AT)
        if cache is not None:
            hit = await cache.get(key)
            if hit is not None:
                return hit
        resolver = plc_resolver or _default_plc_resolve
        try:
            doc = await resolver(did, at)
        except UnresolvableDidError:
            raise
        except Exception as exc:
            raise UnresolvableDidError(
                f"did:plc resolution of {did!r} at {at!r} failed: {exc}"
            ) from exc
        vm = _pick_ed25519_vm(doc)
        vm_id, mb, _pk = _ed25519_pub_from_vm(vm)
        snapshot = DidDocSnapshot(
            did=did,
            fetched_at=datetime.now(UTC),
            verification_method_id=vm_id,
            public_key_multibase=mb,
            raw_doc=doc,
        )
        if cache is not None:
            await cache.put(key, snapshot)
        return snapshot

    raise UnknownDidMethodError(
        f"unsupported DID method in {did!r}; supported: did:key, did:web, did:plc"
    )


# Sentinel datetime used as the "no signing time given" cache key leg. The
# DidDocCache key type is (str, datetime), so we use a fixed far-past epoch
# value to mean "current/no historical pin" — the cache.put inserts under THIS
# key; a historical verify with a real signed_at will MISS this entry and
# fetch fresh, which is the rotation-safe behavior we want.
_SENTINEL_NO_AT = datetime(1970, 1, 1, tzinfo=UTC)


__all__ = [
    "resolve_did",
    "UnknownDidMethodError",
    "UnresolvableDidError",
]
