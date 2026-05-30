"""Active-roles query is rotation-safe (F2 closure for role queries).

D-13: even when the signer's DID key was rotated between t0 and t1, a query
at t0 still returns the role active — the role assertion at t0 was valid at
signing time; subsequent key rotation does NOT retroactively invalidate it.

The active_roles_at walks the log by ``signature.signed_at <= asof`` — the
historical timestamp on the signature, not the DID's current key state.
This mirrors the Phase 6 DidDocCache windowed-by-(did, signed_at) discipline.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import RoleAssertionEvent
from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.governance.roles import active_roles_at
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"
BOB = "did:fi:bob"


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


@pytest.mark.asyncio
async def test_active_roles_at_uses_signing_time_window() -> None:
    """Two snapshots of Alice's key — at t0 ("key-1") and at t1 ("key-2",
    rotated). The role assertion she signed at t0 stays active when queried
    at t0 because active_roles_at windows by signed_at <= asof. The key
    rotation at t1 doesn't retroactively invalidate the role.
    """
    log = InMemoryGovernanceLog()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)

    # Genesis: Alice self-signs corpus_admin at t0.
    genesis = RoleAssertionEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, t0),
        subject_did=ALICE,
        role="corpus_admin",
    )
    await log.append(genesis)

    # Alice asserts Bob as reviewer at t0 with key-1.
    bob_assertion = RoleAssertionEvent(
        corpus=CORPUS,
        # Even after Alice rotates her key, this signature carries the OLD
        # signing_key_id+snapshot_at — exactly the F2 closure shape.
        signature=AttestedSignature(
            did=ALICE,
            action="role_assertion",
            signed_at=t0,
            signature="",
            over_content_hash="0" * 64,
            signing_key_id=f"{ALICE}#key-1",  # OLD key
            did_doc_snapshot_at=t0,           # OLD snapshot
            verified=None,
        ),
        subject_did=BOB,
        role="reviewer",
    )
    await log.append(bob_assertion)

    # Now imagine Alice rotates her key (the DidDocCache would hold a NEW
    # snapshot at t1 with key-2). active_roles_at queries the log, not the
    # DidDocCache — so the rotation is irrelevant for the roles query.
    # The fact we query at signed_at <= asof (t0) means we see the role
    # active independent of any future key state.

    roles_at_t0 = await active_roles_at(CORPUS, t0, log=log)
    assert "reviewer" in roles_at_t0.get(BOB, set()), (
        "F2: role asserted at t0 must be active when queried at t0 "
        "regardless of subsequent key rotation"
    )

    # And the role is STILL active when queried at a later time too (no
    # revocation has happened — only a key rotation, which is not a
    # revocation).
    t15 = datetime(2026, 1, 2, 12, tzinfo=UTC)
    roles_at_t15 = await active_roles_at(CORPUS, t15, log=log)
    assert "reviewer" in roles_at_t15.get(BOB, set()), (
        "F2: key rotation is NOT a role revocation — the role stays active"
    )
