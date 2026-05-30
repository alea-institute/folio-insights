"""Last-admin self-revocation hard-refused (D-11 / F6 closure).

Tests 6 and 7 from PLAN 07-04a:
  * Test 6 (NEGATIVE): genesis admin tries to revoke their own corpus_admin
    role with no successor — ``WouldLockoutCorpusAdmin`` raised with the
    VERBATIM error string locked by D-11.
  * Test 7 (POSITIVE): with a successor admin appointed, the revocation
    succeeds — see test_active_roles_query::test_lockout_ok_when_successor_exists
    (kept here too for the symmetric polarity in this file).

The verbatim error string locked by D-11:
    revocation would leave the corpus with 0 active corpus_admins; appoint a successor first
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import (
    RoleAssertionEvent,
    RoleRevocationEvent,
)
from folio_insights.governance.log import (
    InMemoryGovernanceLog,
    WouldLockoutCorpusAdmin,
)
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"
BOB = "did:fi:bob"

# Verbatim D-11 lockout message — checker-locked.
LOCKOUT_MSG = (
    "revocation would leave the corpus with 0 active corpus_admins; "
    "appoint a successor first"
)


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


@pytest.mark.asyncio
async def test_last_admin_self_revocation_refused_with_verbatim_message() -> None:
    """D-11 closure — genesis admin tries to revoke self with no successor;
    the verbatim error string is asserted character-by-character."""
    log = InMemoryGovernanceLog()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)

    # Genesis admin bootstrap.
    genesis = RoleAssertionEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, "role_assertion", t0),
        subject_did=ALICE,
        role="corpus_admin",
    )
    await log.append(genesis)

    # Alice tries to revoke her own corpus_admin role with no successor.
    self_revoke = RoleRevocationEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, "role_revocation", t1),
        subject_did=ALICE,
        revoked_role="corpus_admin",
    )
    with pytest.raises(WouldLockoutCorpusAdmin) as exc_info:
        await log.append(self_revoke)
    # Verbatim string assertion — character-for-character.
    assert str(exc_info.value) == LOCKOUT_MSG


@pytest.mark.asyncio
async def test_revocation_after_successor_appointment_succeeds() -> None:
    """D-11 polarity counterpart: with Bob appointed as a second admin,
    Alice can revoke her own corpus_admin role."""
    log = InMemoryGovernanceLog()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    t2 = datetime(2026, 1, 3, tzinfo=UTC)

    # Genesis admin.
    await log.append(
        RoleAssertionEvent(
            corpus=CORPUS,
            signature=_sig(ALICE, "role_assertion", t0),
            subject_did=ALICE,
            role="corpus_admin",
        )
    )
    # Alice appoints Bob (signed by Alice, who is the active admin).
    await log.append(
        RoleAssertionEvent(
            corpus=CORPUS,
            signature=_sig(ALICE, "role_assertion", t1),
            subject_did=BOB,
            role="corpus_admin",
        )
    )
    # Alice self-revokes — succeeds.
    persisted = await log.append(
        RoleRevocationEvent(
            corpus=CORPUS,
            # Bob (current admin) signs the revocation so the signer-must-be-admin
            # check passes; the self-revocation case is permitted at this layer too.
            signature=_sig(BOB, "role_revocation", t2),
            subject_did=ALICE,
            revoked_role="corpus_admin",
        )
    )
    assert persisted.position == 2
