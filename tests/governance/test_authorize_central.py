"""Central authorize() table-driven tests (D-19).

Test 8 (table-driven (role, action) cells) and Test 9 (typed result; NEVER
raises) from PLAN 07-04a. >=12 parametrized rows cover the action-permission
table:

  * extractor  -> {extract, content_edit}
  * reviewer   -> above + {promote, demote, contest, supersede, retract,
                            distinguo, content_edit, reparent, reconcile}
  * arbiter    -> above + {resolve_contest}
  * corpus_admin -> above + {role_assertion, role_revocation}
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.authorize import Allow, Deny, authorize
from folio_insights.governance.events import RoleAssertionEvent
from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"  # genesis corpus_admin
EXTRACTOR_DID = "did:fi:e"
REVIEWER_DID = "did:fi:r"
ARBITER_DID = "did:fi:ar"


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


@pytest.fixture
async def populated_log() -> InMemoryGovernanceLog:
    """A log with: Alice (corpus_admin from genesis), an extractor, a reviewer,
    an arbiter all asserted by Alice at t0."""
    log = InMemoryGovernanceLog()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    # Genesis.
    await log.append(
        RoleAssertionEvent(
            corpus=CORPUS,
            signature=_sig(ALICE, t0),
            subject_did=ALICE,
            role="corpus_admin",
        )
    )
    # Alice grants roles.
    for subject, role in [
        (EXTRACTOR_DID, "extractor"),
        (REVIEWER_DID, "reviewer"),
        (ARBITER_DID, "arbiter"),
    ]:
        await log.append(
            RoleAssertionEvent(
                corpus=CORPUS,
                signature=_sig(ALICE, t0),
                subject_did=subject,
                role=role,
            )
        )
    return log


# (role-bearing DID, action, expected_class)
_TABLE = [
    # extractor: {extract, content_edit}
    (EXTRACTOR_DID, "extract", Allow),
    (EXTRACTOR_DID, "content_edit", Allow),
    (EXTRACTOR_DID, "promote", Deny),
    (EXTRACTOR_DID, "role_assertion", Deny),
    # reviewer: above + {promote, demote, contest, supersede, retract, distinguo, reparent, reconcile}
    (REVIEWER_DID, "extract", Allow),
    (REVIEWER_DID, "promote", Allow),
    (REVIEWER_DID, "demote", Allow),
    (REVIEWER_DID, "contest", Allow),
    (REVIEWER_DID, "supersede", Allow),
    (REVIEWER_DID, "retract", Allow),
    (REVIEWER_DID, "distinguo", Allow),
    (REVIEWER_DID, "reparent", Allow),
    (REVIEWER_DID, "reconcile", Allow),
    (REVIEWER_DID, "role_assertion", Deny),
    (REVIEWER_DID, "resolve_contest", Deny),
    # arbiter: reviewer set + resolve_contest
    (ARBITER_DID, "resolve_contest", Allow),
    (ARBITER_DID, "promote", Allow),
    (ARBITER_DID, "role_assertion", Deny),
    # corpus_admin: arbiter set + {role_assertion, role_revocation}
    (ALICE, "role_assertion", Allow),
    (ALICE, "role_revocation", Allow),
    (ALICE, "promote", Allow),
    (ALICE, "extract", Allow),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("did,action,expected", _TABLE)
async def test_authorize_table(populated_log, did, action, expected) -> None:
    """For each (DID, action) cell, authorize returns the expected outcome.

    >=12 rows; covers all (role, action) cells in PRD §3.1 + the inverted
    Deny cases that prove roles don't carry actions they shouldn't.
    """
    result = await authorize(did, action, CORPUS, log=populated_log)
    assert isinstance(result, expected), (
        f"({did!r}, {action!r}) expected {expected.__name__}; got {result!r}"
    )


@pytest.mark.asyncio
async def test_authorize_never_raises_on_unknown_did() -> None:
    """Test 9: an unknown DID returns Deny(reason="no_active_role"); never raises."""
    log = InMemoryGovernanceLog()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    await log.append(
        RoleAssertionEvent(
            corpus=CORPUS,
            signature=_sig(ALICE, t0),
            subject_did=ALICE,
            role="corpus_admin",
        )
    )
    result = await authorize("did:fi:nobody", "promote", CORPUS, log=log)
    assert isinstance(result, Deny)
    assert result.reason == "no_active_role"


@pytest.mark.asyncio
async def test_authorize_never_raises_on_unknown_action(populated_log) -> None:
    """Test 9: an unknown action returns Deny; never raises."""
    result = await authorize(ALICE, "unknown_action", CORPUS, log=populated_log)
    assert isinstance(result, Deny)
    # Reason is informative — references the unknown action.
    assert "unknown_action" in result.reason or "lacks" in result.reason
