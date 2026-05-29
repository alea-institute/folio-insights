"""WR-02 — ``load_signing_key`` POSIX-mode behavior on Windows vs. POSIX.

Before WR-02, the POSIX bit-mask check ran unconditionally; on Windows
``Path.stat().st_mode`` is synthesized so every key load raised
``PermissionError`` with no fix available. After WR-02, the check branches
on ``os.name`` — enforce on POSIX, warn on Windows, skip silently elsewhere.

These tests simulate the two branches by monkey-patching ``os.name`` rather
than running on a real Windows host (CI runs Linux).
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.identity import keys as _keys_mod
from folio_insights.identity.keys import (
    _sk_to_jwk,
    load_signing_key,
)

pytestmark = pytest.mark.identity


def _write_keyfile(tmp_path: Path, mode: int = 0o600) -> Path:
    """Build a real JWK keyfile at the requested mode and return its path."""
    sk = Ed25519PrivateKey.generate()
    jwk = _sk_to_jwk(sk)
    key_path = tmp_path / "signer.jwk"
    key_path.write_text(json.dumps(jwk), encoding="utf-8")
    key_path.chmod(mode)
    return key_path


def test_load_signing_key_accepts_posix_600(tmp_path: Path) -> None:
    """A POSIX 0o600 keyfile loads cleanly (regression baseline)."""
    key_path = _write_keyfile(tmp_path, mode=0o600)
    sk = load_signing_key(key_path)
    assert isinstance(sk, Ed25519PrivateKey)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits required")
def test_load_signing_key_rejects_world_readable_on_posix(tmp_path: Path) -> None:
    """0o644 keyfile is rejected on POSIX (the DID-06 invariant — unchanged by WR-02)."""
    key_path = _write_keyfile(tmp_path, mode=0o644)
    with pytest.raises(PermissionError):
        load_signing_key(key_path)


def test_load_signing_key_windows_warns_no_posix_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-02: under ``os.name == 'nt'``, load_signing_key emits a warning instead of raising.

    We simulate Windows by monkey-patching ``os.name`` inside the keys
    module's import binding. A world-readable file (0o644) that would raise
    on POSIX must instead surface a warning and proceed to load — the bit
    mask is meaningless on a synthesized Windows mode.
    """
    key_path = _write_keyfile(tmp_path, mode=0o644)
    monkeypatch.setattr(_keys_mod.os, "name", "nt")
    with pytest.warns(UserWarning, match="NTFS ACLs"):
        sk = load_signing_key(key_path)
    assert isinstance(sk, Ed25519PrivateKey)
