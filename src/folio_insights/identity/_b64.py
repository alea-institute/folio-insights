"""Centralized base64url-no-pad helpers (RFC 7515 §2).

WR-09 fix: previously these helpers were duplicated identically in
``keys.py``, ``signer.py``, and ``verifier.py``. Drift between the three
implementations would silently desync signer and verifier (e.g. a
Pydantic-version-induced bytes/str fix in one but not the others would
make every signature stop verifying). This module is the single source of
truth — both functions are private (``_b64url_nopad_*``) and re-exported
from the module-level for the identity-internal consumers.

The leading-underscore filename keeps this module out of the
``test_no_server_keys_contract`` AST walk (it filters ``glob("*.py")`` to
exclude ``_*.py``), which is also what we want: nothing here writes a
private key. The contract surface stays unchanged.
"""
from __future__ import annotations

import base64


def _b64url_nopad_encode(data: bytes) -> str:
    """base64url-encode without padding (RFC 7515 §2)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_nopad_decode(s: str) -> bytes:
    """base64url-decode tolerating missing padding (RFC 7515 §2)."""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


__all__ = ["_b64url_nopad_encode", "_b64url_nopad_decode"]
