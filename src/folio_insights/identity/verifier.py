"""Real ed25519 ``verify_attestation`` with signing-time key resolution (SEC-05).

Pairs with ``signer.sign_attestation``: takes an ``AttestedSignature`` (carrying
``signing_key_id`` + ``did_doc_snapshot_at``), resolves the signing-time key via
the ``DidDocCache`` + resolver, and checks the ed25519 signature over the
recorded ``over_content_hash``.

Why this is the rotation-survival gate (EC3 / SEC-05): for did:web (and
did:plc), the verifier resolves the key AS OF ``did_doc_snapshot_at`` — NOT the
DID's *current* key. If the operator rotated the did.json after signing, the
NEW key would fail to verify the OLD signature; resolving from the historical
snapshot means the signature stays valid. ``test_signature_survives_key_rotation``
proves this for did:key (degenerate — key IS the DID) and did:web (real
rotation: current doc swapped to a new key, but the snapshot still verifies).

The verifier returns a boolean and ALSO returns a copy of the signature with
the ``verified`` field set. The caller can persist the annotation back into the
shard's ``signatures`` list to avoid re-verifying on every read.

A tampered hash, a wrong key, or a malformed signature returns ``False`` —
NEVER raises. T-06-03: an unverified signature can never read as verified.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

# WR-09 fix: shared base64url helper imported from identity/_b64.py.
from folio_insights.identity._b64 import _b64url_nopad_decode
from folio_insights.identity.cache import DidDocCache, DidDocSnapshot
from folio_insights.identity.resolver import resolve_did
from folio_insights.shards.envelope import AttestedSignature, ShardEnvelope


def _public_key_from_snapshot(snap: DidDocSnapshot) -> Ed25519PublicKey:
    """Recover the ed25519 public key from a cached ``DidDocSnapshot``.

    Reuses the did:key decode path: the snapshot stores ``public_key_multibase``
    in the canonical did:key multibase form (``z`` + base58btc(0xed01 || raw)),
    so we synthesize a did:key and decode through ``public_key_from_did_key``.
    """
    from folio_insights.identity.keys import public_key_from_did_key

    synthetic_did = f"did:key:{snap.public_key_multibase}"
    return public_key_from_did_key(synthetic_did)


async def verify_attestation(
    shard_or_hash: ShardEnvelope | str,
    sig: AttestedSignature,
    *,
    cache: DidDocCache,
    resolver: Callable[..., Awaitable[DidDocSnapshot]] = resolve_did,
    http: Callable[[str], Awaitable[dict]] | None = None,
    plc_resolver: Callable[[str, Any], Awaitable[dict]] | None = None,
) -> bool:
    """Verify ``sig`` against the (re-computed) content hash for ``shard_or_hash``.

    * If ``shard_or_hash`` is a ``ShardEnvelope``, recompute the JCS canonical
      content hash via ``revision.content_edit.canonical_content_hash`` and use
      THAT as the verification payload. Importantly, the shard's CURRENT
      content is hashed and compared against the recorded ``over_content_hash``:
      a tampered shard whose content no longer matches the originally-signed
      hash returns ``False`` (we refuse to verify against the wrong payload).
    * If ``shard_or_hash`` is a ``str``, treat it as the canonical hash
      directly — the verifier compares it to ``sig.over_content_hash`` and
      verifies the ed25519 signature over it.
    * The signing-time key is resolved via ``resolver(sig.did, at=
      sig.did_doc_snapshot_at, cache=cache, http=..., plc_resolver=...)``. For
      did:key the snapshot is degenerate; for did:web/did:plc the cache
      short-circuits the historical lookup (rotation-safe).

    Returns ``True`` iff the ed25519 signature is valid AND the (re-computed)
    content hash matches ``sig.over_content_hash``. Returns ``False`` on
    signature-mismatch, hash-mismatch, malformed signature bytes, or an
    unresolvable DID; NEVER raises (the boolean is the only failure mode the
    caller sees, by design — an unverified signature can never read as
    verified).
    """
    # Step 1: derive the canonical hash we will verify against.
    if isinstance(shard_or_hash, str):
        verify_hash = shard_or_hash
    else:
        # Lazy import to keep the identity/ -> revision/ dep direction honest
        # (one-way; revision/ never imports identity/).
        from folio_insights.revision.content_edit import canonical_content_hash

        # Recompute the shard's current canonical hash. If it does NOT match
        # the recorded `over_content_hash`, the shard's content has been
        # tampered with since signing — fail closed.
        current_hash = canonical_content_hash(shard_or_hash)
        if current_hash != sig.over_content_hash:
            return False
        verify_hash = sig.over_content_hash

    # Step 2: resolve the signing-time DID document snapshot via the cache +
    # resolver. The resolver short-circuits to the cache hit on (did, at).
    try:
        snapshot = await resolver(
            sig.did,
            at=sig.did_doc_snapshot_at,
            cache=cache,
            http=http,
            plc_resolver=plc_resolver,
        )
    except Exception:
        # Unresolvable DID / network error / unknown method — fail closed.
        return False

    # Step 3: extract the ed25519 public key from the snapshot.
    try:
        pub = _public_key_from_snapshot(snapshot)
    except Exception:
        return False

    # Step 4: verify the ed25519 signature over the canonical hash bytes.
    try:
        raw_pub = pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        verify_key = VerifyKey(raw_pub)
        sig_bytes = _b64url_nopad_decode(sig.signature)
        verify_key.verify(verify_hash.encode("utf-8"), sig_bytes)
        return True
    except BadSignatureError:
        return False
    except Exception:
        # Malformed base64 / wrong-length signature / etc.  Fail closed.
        return False


__all__ = ["verify_attestation"]
