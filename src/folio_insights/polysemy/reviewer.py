"""Phase 1 reviewer did:key generator — real ed25519 + JWK persistence (OQ-4 RESOLVED).

Generates a W3C did:key (Ed25519 + multibase z-base58btc) on first CLI use.
Private key persisted as JWK at ~/.folio-insights/reviewer.jwk (mode 0600);
public DID cached at ~/.folio-insights/reviewer.did for cheap re-reads.

Multicodec prefix for ed25519-pub is 0xed 0x01 (per did:key method spec);
full multibase string is "did:key:z" + base58btc(\\xed\\x01 || raw_public_key).
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import base58
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_PATH = Path.home() / ".folio-insights" / "reviewer.jwk"
DID_PATH = Path.home() / ".folio-insights" / "reviewer.did"

# multicodec varint prefix for ed25519-pub (code 0xed, 1-byte varint encoding)
_ED25519_MULTICODEC_PREFIX = b"\xed\x01"


def _b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sk_to_jwk(sk: Ed25519PrivateKey) -> dict[str, str]:
    raw_priv = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_pub = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "d": _b64url_nopad(raw_priv),
        "x": _b64url_nopad(raw_pub),
    }


def _did_key_from_pub(raw_pub: bytes) -> str:
    multibase = base58.b58encode(_ED25519_MULTICODEC_PREFIX + raw_pub).decode("ascii")
    return f"did:key:z{multibase}"


def ensure_reviewer_did() -> str:
    """Return the maintainer's did:key. Generate-once; reuse thereafter.

    First call: generates ed25519 keypair, writes JWK + DID files (mode 0600),
    returns did:key:z... string.
    Subsequent calls: reads DID_PATH directly — no regeneration, no new mtime.
    """
    if DID_PATH.exists():
        return DID_PATH.read_text(encoding="utf-8").strip()

    KEY_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    sk = Ed25519PrivateKey.generate()
    jwk = _sk_to_jwk(sk)
    raw_pub = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    did = _did_key_from_pub(raw_pub)

    KEY_PATH.write_text(json.dumps(jwk), encoding="utf-8")
    KEY_PATH.chmod(0o600)
    DID_PATH.write_text(did + "\n", encoding="utf-8")
    DID_PATH.chmod(0o600)

    return did
