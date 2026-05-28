"""DID-02 per-action ``AttestedSignature`` shape test (Plan 06-03 Task 4).

REQUIREMENTS DID-02: "every write action signs". Parametrized over the
8-action DID-07 governance subset (the same set ``identity.preview``
iterates for EC5), asserting that ``sign_attestation`` yields a fully-
populated ``AttestedSignature`` for each:

* the recorded ``action`` matches the input,
* the ``signature`` field is non-empty (real ed25519, not the stub's ""),
* the ``signing_key_id`` is populated (DID-04 / SEC-05),
* the ``over_content_hash`` matches the input,
* ``verified`` defaults to ``None`` (T-06-03 anti-spoofing — an unverified
  signature can never read as verified).

This is the "every write action signs" contract proven exhaustively for the
8 governance actions Plan 03 ships.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.identity import (
    GOVERNANCE_ACTIONS,
    did_key_from_public,
    sign_attestation,
)
from folio_insights.shards.envelope import SignedAction

pytestmark = pytest.mark.identity


_HASH = "f" * 64
_SIGNED_AT = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize("action", list(GOVERNANCE_ACTIONS))
def test_sign_attestation_yields_populated_record_per_action(
    action: SignedAction,
) -> None:
    """DID-02: every signed-action yields a populated ``AttestedSignature``.

    For each of the 8 DID-07 governance actions, assert:
    * ``action`` round-trips,
    * ``signature`` is non-empty (real ed25519),
    * ``signing_key_id`` is populated (DID-04 / SEC-05),
    * ``over_content_hash`` matches the input,
    * ``verified is None`` (T-06-03 anti-spoofing default).
    """
    sk = Ed25519PrivateKey.generate()
    raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    did = did_key_from_public(raw)
    key_id = f"{did}#{did.removeprefix('did:key:')}"
    sig = sign_attestation(
        _HASH,
        sk,
        did,
        action,
        signing_key_id=key_id,
        did_doc_snapshot_at=None,
        now=_SIGNED_AT,
    )

    assert sig.action == action
    assert sig.signature  # non-empty
    assert sig.signing_key_id == key_id
    assert sig.over_content_hash == _HASH
    assert sig.did == did
    assert sig.signed_at == _SIGNED_AT
    # Anti-spoofing default: an unverified signature must NEVER default to True.
    assert sig.verified is None


def test_sign_attestation_covers_all_8_governance_actions() -> None:
    """GOVERNANCE_ACTIONS is exactly the 8 DID-07 subset (DID-02 contract)."""
    assert len(GOVERNANCE_ACTIONS) == 8
    assert set(GOVERNANCE_ACTIONS) == {
        "extract", "promote", "demote", "contest",
        "supersede", "retract", "distinguo", "role_assertion",
    }
