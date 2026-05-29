"""Client-side local ed25519 keystore (D-07, DID-06).

EXTENDS the Phase-1 ``polysemy/reviewer.py`` keystore pattern:

* ``~/.folio-insights/`` dir mode ``0o700``
* JWK keyfile mode ``0o600``
* Ed25519 keypair, persisted as JWK (kty=OKP, crv=Ed25519, d=priv, x=pub)
* did:key derivation = ``"did:key:z" + base58btc(0xed01 || raw_pub)``

The DID-06 invariant — *no signing key is ever server-resident, for any DID
method or surface* — is enforced by **construction**:

* This is the ONLY module under ``identity/`` (or anywhere server-reachable)
  that writes or serializes a private key.
* ``load_signing_key`` refuses a keyfile whose POSIX mode is group/world
  readable — a key on a server filesystem with permissive mode is treated as
  compromised.
* The signer (signer.py) and verifier (verifier.py) ACCEPT key material as
  parameters; they never persist or transmit a private key.

The contract test ``tests/identity/test_no_server_keys_contract.py`` (EC4)
parses every module under ``identity/`` with ``ast`` and asserts no module
OTHER than this one persists a private key. If a future plan adds a second
keystore module, the contract test is the gate that catches it.
"""
from __future__ import annotations

import json
import os
import stat
import warnings
from pathlib import Path

import base58
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# WR-09 fix: import the centralized base64url helpers from identity/_b64.py
# instead of redefining them here. The signer and verifier import from the same
# module so a future change to the helper (e.g. a Pydantic-versioning bytes/str
# fix) cannot desynchronize signer and verifier.
from folio_insights.identity._b64 import (
    _b64url_nopad_decode,
    _b64url_nopad_encode,
)

# Default home-dir keystore location — mirrors polysemy/reviewer.py L20-21.
KEY_DIR = Path.home() / ".folio-insights"
KEY_PATH = KEY_DIR / "signer.jwk"

# multicodec varint prefix for ed25519-pub (code 0xed, 1-byte varint encoding)
# Identical to polysemy/reviewer.py L24 — the W3C did:key spec is the source of
# truth, not a duplicated constant.
_ED25519_MULTICODEC_PREFIX = b"\xed\x01"


# ── base64url-no-pad helpers — now imported from identity/_b64.py (WR-09) ───


# ── did:key <-> raw public key round-trip (W3C did:key ed25519) ─────────────


def did_key_from_public(raw_pub: bytes) -> str:
    """Build the W3C did:key for an ed25519 public key.

    ``did:key:z`` + base58btc(``0xed01`` || raw_pub). Round-trips with
    ``public_key_from_did_key``. Phase-1 parity (``polysemy/reviewer.py`` L49-51).
    """
    if len(raw_pub) != 32:
        raise ValueError(
            f"raw ed25519 public key must be 32 bytes, got {len(raw_pub)}"
        )
    multibase = base58.b58encode(_ED25519_MULTICODEC_PREFIX + raw_pub).decode("ascii")
    return f"did:key:z{multibase}"


def public_key_from_did_key(did: str) -> Ed25519PublicKey:
    """Decode a did:key into an ``Ed25519PublicKey``.

    Strict: rejects non-``did:key`` DIDs, non-``z`` (non-base58btc) multibase
    prefixes, and any multicodec other than 0xed01 (ed25519-pub). The decode is
    the entire historical-key-resolution path for did:key — the key IS the DID,
    so this is also why did:key cannot rotate (rotation = a new DID, not a new
    key under the same DID).
    """
    if not did.startswith("did:key:"):
        raise ValueError(f"not a did:key: {did!r}")
    body = did.removeprefix("did:key:")
    if not body.startswith("z"):
        raise ValueError(
            f"unsupported did:key multibase prefix in {did!r} — only 'z' "
            "(base58btc) is supported"
        )
    raw = base58.b58decode(body[1:])
    if raw[:2] != _ED25519_MULTICODEC_PREFIX:
        raise ValueError(
            f"did:key {did!r} is not ed25519 (multicodec prefix "
            f"{raw[:2]!r} != {_ED25519_MULTICODEC_PREFIX!r})"
        )
    raw_pub = raw[2:]
    if len(raw_pub) != 32:
        raise ValueError(
            f"did:key {did!r} decodes to {len(raw_pub)}-byte key (expected 32)"
        )
    return Ed25519PublicKey.from_public_bytes(raw_pub)


# ── JWK <-> Ed25519 private/public key serialization ────────────────────────


def _sk_to_jwk(sk: Ed25519PrivateKey) -> dict[str, str]:
    """Serialize an ed25519 private key as JWK (kty=OKP, crv=Ed25519).

    Mirrors ``polysemy/reviewer.py::_sk_to_jwk`` byte-for-byte.
    """
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
        "d": _b64url_nopad_encode(raw_priv),
        "x": _b64url_nopad_encode(raw_pub),
    }


def _jwk_to_sk(jwk: dict[str, str]) -> Ed25519PrivateKey:
    """Reconstruct an ed25519 private key from a JWK (kty=OKP, crv=Ed25519)."""
    if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
        raise ValueError(
            f"JWK is not an Ed25519 OKP key (kty={jwk.get('kty')!r}, "
            f"crv={jwk.get('crv')!r})"
        )
    if "d" not in jwk:
        raise ValueError("JWK has no private component 'd' — not a private key")
    raw_priv = _b64url_nopad_decode(jwk["d"])
    if len(raw_priv) != 32:
        raise ValueError(
            f"JWK 'd' decodes to {len(raw_priv)} bytes (expected 32 for ed25519)"
        )
    return Ed25519PrivateKey.from_private_bytes(raw_priv)


# ── generate / load — the keystore public API ───────────────────────────────


def generate_keypair(key_path: Path = KEY_PATH) -> str:
    """Generate (or REUSE) the local ed25519 keypair; return its did:key.

    On first call: ``mkdir`` the parent dir mode ``0o700``, generate an ed25519
    keypair, persist it as JWK at ``key_path`` mode ``0o600``, and return the
    derived ``did:key:z…`` string.

    On a subsequent call: load the existing JWK (no regeneration, no new mtime)
    and return the SAME did:key. This is the Phase-1 ``ensure_reviewer_did``
    idempotency contract.

    The keyfile NEVER leaves ``key_path``. There is no API surface that returns
    or transmits the private bytes — only the public did:key — so accidental
    leakage requires a deliberate read of the on-disk file (DID-06).
    """
    if key_path.exists():
        # Reuse — match the Phase-1 ``ensure_reviewer_did`` contract.
        sk = load_signing_key(key_path)
        raw_pub = sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return did_key_from_public(raw_pub)

    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # mkdir's mode is masked by umask on creation — re-chmod to be explicit.
    key_path.parent.chmod(0o700)

    sk = Ed25519PrivateKey.generate()
    jwk = _sk_to_jwk(sk)
    raw_pub = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    did = did_key_from_public(raw_pub)

    key_path.write_text(json.dumps(jwk), encoding="utf-8")
    key_path.chmod(0o600)
    return did


def load_signing_key(key_path: Path = KEY_PATH) -> Ed25519PrivateKey:
    """Load the local ed25519 private key from ``key_path``.

    Refuses to load if:

    * the file does not exist (clear error directs the operator to
      ``generate_keypair`` first),
    * the file is group- or world-readable (mode > 0o600 in the low bits) —
      a key with permissive POSIX mode is treated as compromised. The check
      is skipped on platforms without POSIX mode bits (e.g. plain Windows),
      but the same code path is what enforces DID-06 on every Linux/macOS
      server the operator might run signing on.

    Returns the ``Ed25519PrivateKey`` — the caller passes it to
    ``signer.sign_attestation`` and DROPS the reference. The key never crosses
    a network boundary, is never serialized again, and is never logged.
    """
    if not key_path.exists():
        raise FileNotFoundError(
            f"signing keyfile not found at {key_path}; "
            "run identity.keys.generate_keypair() to create one (DID-06: keys "
            "live ONLY on the operator's machine)"
        )

    # WR-02 fix — POSIX mode check is meaningful only on POSIX-mode platforms.
    # On Windows, ``Path.stat().st_mode`` is a synthesized mode where files
    # default to 0o666 (rw for owner/group/other), so the previous unconditional
    # bit-mask check raised ``PermissionError`` for EVERY Windows key load with
    # no way for the operator to fix via ``chmod``. We now branch on
    # ``os.name``: enforce the bit mask on POSIX, surface a warning on Windows
    # (operator MUST rely on NTFS ACLs there), skip silently elsewhere.
    if os.name == "posix":
        try:
            mode = key_path.stat().st_mode
        except OSError as exc:  # pragma: no cover — stat rarely fails after exists()
            raise OSError(f"could not stat {key_path}: {exc}") from exc
        # The low 9 bits are rwxrwxrwx; we want owner-only (0o600 = 0o400|0o200).
        # If ANY group or other read/write bit is set, refuse.
        forbidden_bits = stat.S_IRWXG | stat.S_IRWXO
        if mode & forbidden_bits:
            raise PermissionError(
                f"signing keyfile {key_path} is group/world readable (mode "
                f"{oct(mode & 0o777)}); DID-06 requires 0o600. Run "
                f"`chmod 600 {key_path}` to fix."
            )
    elif os.name == "nt":  # pragma: no cover — exercised under Windows only
        # On Windows, the POSIX mode bits Path.stat() reports are synthesized and
        # never reflect real ACL state. We can't enforce DID-06 here; emit a
        # warning so the operator knows NTFS ACLs are their responsibility.
        warnings.warn(
            f"On Windows, POSIX mode bits on {key_path} are synthesized; rely "
            "on NTFS ACLs to restrict access to the keyfile (DID-06).",
            stacklevel=2,
        )

    jwk = json.loads(key_path.read_text(encoding="utf-8"))
    return _jwk_to_sk(jwk)


__all__ = [
    "KEY_DIR",
    "KEY_PATH",
    "did_key_from_public",
    "public_key_from_did_key",
    "generate_keypair",
    "load_signing_key",
]
