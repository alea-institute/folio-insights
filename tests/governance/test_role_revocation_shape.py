"""SHACL fi:RoleRevocationShape positive + negative polarity tests (D-11).

Tests 4-5 from PLAN 07-04a Task 2:
  * Test 4 (POSITIVE): valid revocation where a successor admin exists →
    conforms=True.
  * Test 5 (NEGATIVE): revocation in a graph with only one active corpus_admin
    → conforms=False with a message referencing the lockout (SHACL belt
    mirrors the code suspenders).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import (
    RoleAssertionEvent,
    RoleRevocationEvent,
)
from folio_insights.governance.shape_validation import (
    validate_role_revocation_shape,
)
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"
BOB = "did:fi:bob"


def _sig(did: str, action: str, signed_at: datetime) -> AttestedSignature:
    return AttestedSignature(
        did=did,
        action=action,  # type: ignore[arg-type]
        signed_at=signed_at,
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{did}#key-1",
        did_doc_snapshot_at=signed_at,
        verified=None,
    )


# ── POSITIVE ──


def test_revocation_with_successor_conforms() -> None:
    """Test 4: successor admin (Bob) exists → revoking Alice conforms."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    t2 = datetime(2026, 1, 3, tzinfo=UTC)
    history = [
        RoleAssertionEvent(
            corpus=CORPUS,
            position=0,
            signature=_sig(ALICE, "role_assertion", t0),
            subject_did=ALICE,
            role="corpus_admin",
        ),
        RoleAssertionEvent(
            corpus=CORPUS,
            position=1,
            signature=_sig(ALICE, "role_assertion", t1),
            subject_did=BOB,
            role="corpus_admin",
        ),
    ]
    # Revoke Alice — Bob is the successor.
    revoke_alice = RoleRevocationEvent(
        corpus=CORPUS,
        position=2,
        signature=_sig(BOB, "role_revocation", t2),
        subject_did=ALICE,
        revoked_role="corpus_admin",
    )
    result = validate_role_revocation_shape(revoke_alice, history=history)
    assert result.conforms is True, f"violations: {result.violations}"


# ── NEGATIVE ──


def test_last_admin_revocation_refused_with_lockout_message() -> None:
    """Test 5: only Alice is active corpus_admin; revoking her → conforms=False
    with a message referencing the lockout."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    history = [
        RoleAssertionEvent(
            corpus=CORPUS,
            position=0,
            signature=_sig(ALICE, "role_assertion", t0),
            subject_did=ALICE,
            role="corpus_admin",
        ),
    ]
    self_revoke = RoleRevocationEvent(
        corpus=CORPUS,
        position=1,
        signature=_sig(ALICE, "role_revocation", t1),
        subject_did=ALICE,
        revoked_role="corpus_admin",
    )
    result = validate_role_revocation_shape(self_revoke, history=history)
    assert result.conforms is False
    assert len(result.violations) >= 1
    # The message should reference the lockout — at least one of these
    # substrings must appear.
    blob = " ".join(result.violations).lower() + " " + result.results_text.lower()
    assert any(
        marker in blob
        for marker in ("lockout", "0 active", "successor", "last", "leave the corpus")
    ), f"expected lockout reference; got violations: {result.violations}"
