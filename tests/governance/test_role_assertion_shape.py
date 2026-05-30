"""SHACL fi:RoleAssertionShape positive + negative polarity tests (D-10).

Tests 1-3 from PLAN 07-04a Task 2:
  * Test 1 (POSITIVE): valid genesis-row-0 self-signed corpus_admin assertion
    → conforms=True.
  * Test 2 (NEGATIVE): non-genesis self-signed (position > 0 + signer == subject
    + signer has no active corpus_admin role) → conforms=False.
  * Test 3 (NEGATIVE): non-corpus_admin role at row 0 → conforms=False
    (the carve-out is corpus_admin only).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import RoleAssertionEvent
from folio_insights.governance.shape_validation import (
    ValidationResult,
    validate_role_assertion_shape,
)
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"
BOB = "did:fi:bob"
EVE = "did:fi:eve"


def _sig(did: str, signed_at: datetime) -> AttestedSignature:
    return AttestedSignature(
        did=did,
        action="role_assertion",
        signed_at=signed_at,
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{did}#key-1",
        did_doc_snapshot_at=signed_at,
        verified=None,
    )


# ── POSITIVE ──


def test_genesis_self_signed_corpus_admin_conforms() -> None:
    """Test 1: valid genesis row-0 self-signed corpus_admin → conforms=True."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    genesis = RoleAssertionEvent(
        corpus=CORPUS,
        position=0,
        signature=_sig(ALICE, t0),
        subject_did=ALICE,
        role="corpus_admin",
    )
    result = validate_role_assertion_shape(genesis, history=[])
    assert isinstance(result, ValidationResult)
    assert result.conforms is True, f"violations: {result.violations}"


def test_admin_signed_non_genesis_assertion_conforms() -> None:
    """Polarity-positive companion: an admin (Alice in history) signs a
    RoleAssertion granting reviewer to Bob at position 1 → conforms=True."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    history = [
        RoleAssertionEvent(
            corpus=CORPUS,
            position=0,
            signature=_sig(ALICE, t0),
            subject_did=ALICE,
            role="corpus_admin",
        ),
    ]
    assertion = RoleAssertionEvent(
        corpus=CORPUS,
        position=1,
        signature=_sig(ALICE, t1),  # Alice (admin) signs Bob's reviewer role
        subject_did=BOB,
        role="reviewer",
    )
    result = validate_role_assertion_shape(assertion, history=history)
    assert result.conforms is True, f"violations: {result.violations}"


# ── NEGATIVE ──


def test_non_genesis_self_signed_refused() -> None:
    """Test 2: position > 0 + signer == subject + signer NOT an active admin
    → conforms=False."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    history = [
        RoleAssertionEvent(
            corpus=CORPUS,
            position=0,
            signature=_sig(ALICE, t0),
            subject_did=ALICE,
            role="corpus_admin",
        ),
    ]
    # Eve self-signs herself as corpus_admin at row 1 — refused.
    eve_self = RoleAssertionEvent(
        corpus=CORPUS,
        position=1,
        signature=_sig(EVE, t1),
        subject_did=EVE,
        role="corpus_admin",
    )
    result = validate_role_assertion_shape(eve_self, history=history)
    assert result.conforms is False
    assert len(result.violations) >= 1


def test_genesis_carveout_requires_corpus_admin_role() -> None:
    """Test 3: position=0 + role=reviewer (not corpus_admin) → conforms=False
    (carve-out is ONLY for role=corpus_admin)."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    bad_genesis = RoleAssertionEvent(
        corpus=CORPUS,
        position=0,
        signature=_sig(ALICE, t0),
        subject_did=ALICE,
        role="reviewer",  # NOT corpus_admin — refused
    )
    result = validate_role_assertion_shape(bad_genesis, history=[])
    assert result.conforms is False
    assert len(result.violations) >= 1
