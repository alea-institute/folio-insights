"""Active-roles query windowed by signed_at <= asof (D-13 / Pitfall F2).

Tests 1 (boundary + assertion/revocation windowing) and 7 (lockout-ok-if-successor)
from PLAN 07-04a. ``active_roles_at(corpus, asof, log=log)`` walks the log
applying assertions minus revocations, each windowed by
``signature.signed_at <= asof``.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import (
    RoleAssertionEvent,
    RoleRevocationEvent,
)
from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.governance.roles import (
    active_roles_at,
    active_roles_for_did,
)
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"  # genesis admin
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


async def _bootstrap_genesis(log: InMemoryGovernanceLog, signed_at: datetime) -> None:
    """Append the genesis self-signed corpus_admin assertion at position 0."""
    genesis = RoleAssertionEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, "role_assertion", signed_at),
        subject_did=ALICE,
        role="corpus_admin",
    )
    await log.append(genesis)


@pytest.mark.asyncio
async def test_active_roles_windowed_boundary_inclusive() -> None:
    """Assert role at t0; revoke at t1; query at t0.5 active, t1.5 inactive,
    t0 inclusive boundary active."""
    log = InMemoryGovernanceLog()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t05 = datetime(2026, 1, 1, 12, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    t15 = datetime(2026, 1, 2, 12, tzinfo=UTC)

    await _bootstrap_genesis(log, t0)
    # Alice (admin) asserts Bob as reviewer at t0.
    assertion = RoleAssertionEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, "role_assertion", t0),
        subject_did=BOB,
        role="reviewer",
    )
    await log.append(assertion)
    # Alice revokes Bob's reviewer role at t1.
    revocation = RoleRevocationEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, "role_revocation", t1),
        subject_did=BOB,
        revoked_role="reviewer",
    )
    await log.append(revocation)

    # Boundary-inclusive at t0: assertion windowed in -> bob active.
    roles_at_t0 = await active_roles_at(CORPUS, t0, log=log)
    assert "reviewer" in roles_at_t0.get(BOB, set())
    # Between assertion and revocation: bob still active.
    roles_at_t05 = await active_roles_at(CORPUS, t05, log=log)
    assert "reviewer" in roles_at_t05.get(BOB, set())
    # After revocation: bob inactive (set empty).
    roles_at_t15 = await active_roles_at(CORPUS, t15, log=log)
    assert "reviewer" not in roles_at_t15.get(BOB, set())


@pytest.mark.asyncio
async def test_lockout_ok_when_successor_exists() -> None:
    """Test 7: appoint a second corpus_admin then revoke the original — OK."""
    log = InMemoryGovernanceLog()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    t2 = datetime(2026, 1, 3, tzinfo=UTC)

    await _bootstrap_genesis(log, t0)

    # Alice appoints Bob as a second corpus_admin.
    appoint_bob = RoleAssertionEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, "role_assertion", t1),
        subject_did=BOB,
        role="corpus_admin",
    )
    await log.append(appoint_bob)

    # Now Alice can safely revoke her own corpus_admin role (Bob is successor).
    revoke_self = RoleRevocationEvent(
        corpus=CORPUS,
        signature=_sig(BOB, "role_revocation", t2),  # Bob signs (must be admin)
        subject_did=ALICE,
        revoked_role="corpus_admin",
    )
    await log.append(revoke_self)

    # At t2.5: only Bob is corpus_admin.
    t25 = datetime(2026, 1, 3, 12, tzinfo=UTC)
    roles_now = await active_roles_at(CORPUS, t25, log=log)
    assert "corpus_admin" in roles_now.get(BOB, set())
    assert "corpus_admin" not in roles_now.get(ALICE, set())


@pytest.mark.asyncio
async def test_active_roles_for_did_convenience() -> None:
    """active_roles_for_did returns just the roles for one DID."""
    log = InMemoryGovernanceLog()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    await _bootstrap_genesis(log, t0)

    roles = await active_roles_for_did(CORPUS, ALICE, t0, log=log)
    assert roles == {"corpus_admin"}

    no_roles = await active_roles_for_did(CORPUS, BOB, t0, log=log)
    assert no_roles == set()
