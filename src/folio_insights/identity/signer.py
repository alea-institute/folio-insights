"""Real ed25519 ``sign_attestation`` over the JCS canonical content hash (DID-04).

Replaces the Phase-5 unsigned stub (``revision/content_edit.sign_attestation`` —
``signature=""``) with a real ed25519 signature, populating the post-Plan-01
``AttestedSignature`` fields ``signing_key_id`` and ``did_doc_snapshot_at`` so
the verifier resolves the **signing-time** key, not the DID's current key
(Pitfall F2 / SEC-05).

Signing primitive: PyNaCl ``SigningKey`` (libsodium, ~6× the ``cryptography``
ed25519 hot path; STACK.md L47). The signature bytes are encoded
``base64url-no-pad`` so the ``AttestedSignature.signature: str`` field carries a
single canonical form across signer/verifier.

Signed payload: the SHA-256 hex string returned by
``revision.content_edit.canonical_content_hash`` (the RFC-8785 JCS hash from
Plan 01). Signing over the HEX STRING (not raw bytes) means the wire
representation in ``AttestedSignature.over_content_hash`` is what is actually
signed — there is no hidden re-hash step the verifier can disagree with.

The private key never leaves this function frame. It is accepted as a
parameter, used to sign the canonical bytes, and the reference is dropped.
DID-06 stays absolute (the test_no_server_keys_contract test parses this
module with ``ast`` and confirms no private-key persistence).
"""
from __future__ import annotations

from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from nacl.signing import SigningKey

# WR-09 fix: shared base64url helper imported from identity/_b64.py so signer
# and verifier cannot drift apart.
from folio_insights.identity._b64 import _b64url_nopad_encode
from folio_insights.shards.envelope import AttestedSignature, SignedAction


def _ed25519_key_to_nacl(signing_key: Ed25519PrivateKey) -> SigningKey:
    """Convert a ``cryptography`` Ed25519PrivateKey into a PyNaCl ``SigningKey``.

    Both libraries expose the same 32-byte raw seed; the conversion is just a
    re-wrap. We accept ``cryptography``'s Ed25519PrivateKey at the public API
    because Phase 1's keystore (``keys.py``) returns that type, and the
    Phase-5 ``edit_shard_content(..., signing_key)`` parameter has been
    consistently shaped against ``cryptography`` since Phase 1.
    """
    raw_seed = signing_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return SigningKey(raw_seed)


def sign_attestation(
    content_hash: str,
    signing_key: Ed25519PrivateKey,
    did: str,
    action: SignedAction,
    *,
    signing_key_id: str,
    did_doc_snapshot_at: datetime | None,
    now: datetime | None = None,
) -> AttestedSignature:
    """Real ed25519 ``AttestedSignature`` over ``content_hash`` (Plan 02 / DID-04).

    Arguments:

    * ``content_hash`` — the SHA-256 hex from
      ``revision.content_edit.canonical_content_hash`` (RFC-8785 JCS over the
      shard's content; Plan 01). The signature is over the **hex string bytes**
      (UTF-8), so the wire representation in ``AttestedSignature.over_content_hash``
      IS what is signed — no second hash step the verifier can disagree with.
    * ``signing_key`` — a ``cryptography`` ``Ed25519PrivateKey`` loaded via
      ``identity.keys.load_signing_key`` from the local home-dir keystore
      (DID-06). NEVER persisted by this function.
    * ``did`` — the signer DID (e.g. ``did:key:z…``, ``did:web:example.org``).
    * ``action`` — one of the 12 ``SignedAction`` Literal values (the 8
      DID-07 governance subset + ``content_edit`` + ``reparent`` + ``reconcile``
      + ``resolve_contest``).
    * ``signing_key_id`` — DID URL + ``#fragment`` of the verificationMethod
      used (DID-04 / SEC-05). Verification resolves THIS id at
      ``did_doc_snapshot_at``, not the DID's current key.
    * ``did_doc_snapshot_at`` — the wall-clock at which the signer's DID
      doc snapshot was captured into the ``DidDocCache``. May be ``None`` for
      did:key (key cannot rotate; the snapshot is degenerate).
    * ``now`` — override for the ``signed_at`` timestamp (tests only); defaults
      to ``datetime.now(UTC)``.

    Returns an ``AttestedSignature`` with ``signature`` populated (base64url-no-pad
    of the 64-byte ed25519 signature), ``verified=None`` (the anti-spoofing
    default — an unverified signature can never read as verified).
    """
    nacl_key = _ed25519_key_to_nacl(signing_key)
    sig_bytes = nacl_key.sign(content_hash.encode("utf-8")).signature
    return AttestedSignature(
        did=did,
        action=action,
        signed_at=now if now is not None else datetime.now(UTC),
        signature=_b64url_nopad_encode(sig_bytes),
        over_content_hash=content_hash,
        signing_key_id=signing_key_id,
        did_doc_snapshot_at=did_doc_snapshot_at,
        verified=None,
    )


__all__ = ["sign_attestation"]
