"""EC4 — no server-side private signing keys, ever (DID-06, T-06-05).

A STATIC AST contract test that parses every module under
``src/folio_insights/identity/`` and asserts:

1. NO module other than ``keys.py`` writes a private-key serialization to disk
   (no ``private_bytes(...)`` whose result is written; no JWK dict with key
   ``"d"`` written to a file).
2. The signer/verifier modules accept key material as PARAMETERS only — no
   module-global private-key constants.

The check is intentionally `ast`-based (not a regex / grep): a regex over
``"private_bytes"`` would false-positive on a docstring or a comment that
discusses key material. The ast walk inspects actual ``Call`` nodes inside the
function bodies, so a future contributor cannot accidentally sneak a server-
side persistence call past the gate.

Scope: this contract test runs across ``src/folio_insights/identity/*.py``. The
``keys.py`` module is the SOLE allowed persistence point (it writes the JWK to
``~/.folio-insights/`` — the operator's machine, never the server filesystem).
Every OTHER module is held to the no-write rule.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from folio_insights import identity as _identity_pkg

pytestmark = pytest.mark.identity


_IDENTITY_DIR = pathlib.Path(_identity_pkg.__file__).parent

# Only this module is permitted to call private-key-serializing APIs OR to
# write a JWK with a "d" component to disk. Every other module in identity/
# must hold to the no-server-keys invariant.
_KEYSTORE_MODULE = "keys.py"

# AST predicates we treat as "private-key serialization that flows to a file".
_PRIVATE_KEY_SERIALIZATION_ATTRS = {
    "private_bytes",  # cryptography.Ed25519PrivateKey.private_bytes(...)
}
# Method-call names we treat as "file write" sinks. A private-key value that
# flows into one of these from any module OTHER than keys.py is a violation.
_WRITE_SINK_METHODS = {"write_text", "write_bytes", "write"}


def _identity_modules() -> list[pathlib.Path]:
    """Every .py file under src/folio_insights/identity/."""
    return sorted(p for p in _IDENTITY_DIR.glob("*.py") if not p.name.startswith("_"))


def _modules_other_than_keys() -> list[pathlib.Path]:
    return [p for p in _identity_modules() if p.name != _KEYSTORE_MODULE]


# ── No private_bytes() call in any non-keys.py identity module ──────────────


@pytest.mark.parametrize("module_path", _modules_other_than_keys(), ids=lambda p: p.name)
def test_no_private_bytes_call_outside_keystore(module_path: pathlib.Path) -> None:
    """Only ``keys.py`` may call an ed25519-private-key serialization method.

    ``signer.py`` legitimately reads a private key (it signs), but the right
    way to do that is via PyNaCl's ``SigningKey`` over the raw seed it
    receives from the keystore — NOT by re-extracting raw bytes for any
    purpose other than that one-shot conversion. A serialization call inside
    any non-keys.py module is a DID-06 regression.

    Exception: ``signer.py`` calls ``Ed25519PrivateKey.private_bytes`` exactly
    ONCE, inside ``_ed25519_key_to_nacl``, to convert the in-memory key into
    the PyNaCl signing primitive. The raw bytes are immediately handed to
    ``SigningKey(...)`` and the reference is dropped — nothing is written to
    disk or to a network. This is the SINGLE permitted call site; the test
    enforces a hard upper bound of 1 ``private_bytes`` call per non-keystore
    module so any second call site forces a contract review.
    """
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))

    private_bytes_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in _PRIVATE_KEY_SERIALIZATION_ATTRS
            ):
                private_bytes_calls += 1

    # signer.py is allowed exactly ONE private_bytes call (the SigningKey
    # conversion inside _ed25519_key_to_nacl). All other modules: zero.
    allowance = 1 if module_path.name == "signer.py" else 0
    assert private_bytes_calls <= allowance, (
        f"{module_path.name}: found {private_bytes_calls} private_bytes() "
        f"calls; DID-06 caps non-keystore modules at {allowance}. Move any "
        "private-key serialization into keys.py (the only allowed persistence "
        "point) and pass the key as a parameter instead."
    )


# ── No file-write sink that receives a JWK private component ───────────────


@pytest.mark.parametrize("module_path", _modules_other_than_keys(), ids=lambda p: p.name)
def test_no_jwk_d_written_to_disk_outside_keystore(module_path: pathlib.Path) -> None:
    """No non-keys.py module references a JWK private component ``"d"`` AND a write sink.

    A combination of both is the textbook DID-06 violation — JWK ``"d"`` is the
    base64url-encoded private seed; a write sink takes it to disk. Detect both
    co-presence patterns in the same module and fail loudly.

    A single condition (the literal ``"d"`` appearing in a JWK construction OR
    a write_text call existing) is not enough on its own — keys.py legitimately
    writes JWKs with ``"d"`` to the home-dir keystore, and many modules call
    write_text on benign things. The AND of both in the SAME non-keys module
    is the regression.
    """
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))

    has_jwk_d_literal = False
    has_write_sink = False

    for node in ast.walk(tree):
        # Look for a dict literal containing a string key "d" alongside a key
        # like "kty" or "crv" — a JWK private-key dict.
        if isinstance(node, ast.Dict):
            string_keys: set[str] = set()
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    string_keys.add(k.value)
            if "d" in string_keys and (
                "kty" in string_keys or "crv" in string_keys
            ):
                has_jwk_d_literal = True
        # Look for write_text / write_bytes / write calls (file-write sinks).
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _WRITE_SINK_METHODS:
                has_write_sink = True

    assert not (has_jwk_d_literal and has_write_sink), (
        f"{module_path.name}: contains both a JWK 'd' literal AND a file-write "
        "sink — that pattern is reserved for keys.py (the home-dir keystore). "
        "Move any private-key persistence to keys.py and pass the key as a "
        "parameter instead. (DID-06)"
    )


# ── signer/verifier accept key material as a parameter (not module-global) ──


def test_signer_accepts_signing_key_as_parameter() -> None:
    """``signer.sign_attestation`` takes the signing key as a parameter (not a global)."""
    from folio_insights.identity.signer import sign_attestation

    sig = inspect.signature(sign_attestation)
    assert "signing_key" in sig.parameters, (
        "sign_attestation must accept `signing_key` as a parameter so the "
        "private key flows from caller-managed memory, not a module-global "
        "(DID-06)."
    )


def test_verifier_accepts_cache_as_parameter() -> None:
    """``verifier.verify_attestation`` takes the cache (and resolver) as parameters."""
    from folio_insights.identity.verifier import verify_attestation

    sig = inspect.signature(verify_attestation)
    assert "cache" in sig.parameters, (
        "verify_attestation must accept `cache` as a parameter — verification "
        "must not depend on a module-global resolver/cache."
    )


def test_no_module_global_private_key_constant() -> None:
    """No identity/ module declares a module-level ``Ed25519PrivateKey`` constant.

    A module-global private key would mean the key lives in the process forever
    and is shared across requests — the textbook server-side-key anti-pattern.
    """
    for module_path in _identity_modules():
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_path))
        # Walk only the top-level body; nested defs are fine.
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        # If the value is a Call to Ed25519PrivateKey.generate
                        # at module level, that's a module-global private key.
                        if (
                            isinstance(node.value, ast.Call)
                            and isinstance(node.value.func, ast.Attribute)
                            and node.value.func.attr == "generate"
                        ):
                            value_obj = node.value.func.value
                            if (
                                isinstance(value_obj, ast.Name)
                                and "Ed25519Private" in value_obj.id
                            ):
                                pytest.fail(
                                    f"{module_path.name}: module-global "
                                    f"private-key constant {target.id!r} "
                                    "violates DID-06 — keys must be loaded "
                                    "per-call from the keystore, not held in "
                                    "module memory."
                                )
