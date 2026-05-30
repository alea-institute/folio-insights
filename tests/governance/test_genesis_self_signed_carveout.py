"""Genesis self-signed carve-out polarity tests (D-10 at the log-append layer).

Tests 3, 4, 5 from PLAN 07-04a:
  * Test 3 (POSITIVE): self-signed RoleAssertionEvent at position=0 granting
    role=corpus_admin to its own signer DID succeeds.
  * Test 4 (NEGATIVE): self-signed RoleAssertion at position >= 1 fails
    (NotAuthorized — non-genesis self-signed refused).
  * Test 5 (NEGATIVE): self-signed RoleAssertion at position=0 granting a
    non-corpus_admin role fails (carve-out is ONLY for role=corpus_admin).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import RoleAssertionEvent
from folio_insights.governance.log import (
    InMemoryGovernanceLog,
    NotAuthorized,
)
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"


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


@pytest.mark.asyncio
async def test_genesis_self_signed_corpus_admin_at_position_zero_succeeds() -> None:
    """D-10 carve-out POSITIVE — self-signed corpus_admin at log row 0."""
    log = InMemoryGovernanceLog()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    genesis = RoleAssertionEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, t0),
        subject_did=ALICE,
        role="corpus_admin",
    )
    persisted = await log.append(genesis)
    assert persisted.position == 0
    assert await log.latest_position(CORPUS) == 0


# ── NEGATIVE ──


@pytest.mark.asyncio
async def test_non_genesis_self_signed_refused() -> None:
    """Test 4: a self-signed RoleAssertion at row >= 1 (no active admin signer)
    fails with NotAuthorized — the SHACL+code refuses non-genesis self-signed.
    """
    log = InMemoryGovernanceLog()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)

    # Genesis OK at row 0.
    genesis = RoleAssertionEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, t0),
        subject_did=ALICE,
        role="corpus_admin",
    )
    await log.append(genesis)

    # Now Eve tries to self-sign herself as corpus_admin at row 1 — refused
    # (Eve has no active corpus_admin role at signed_at, and she is not the
    # genesis bootstrap because the log already has rows).
    eve = "did:fi:eve"
    eve_self = RoleAssertionEvent(
        corpus=CORPUS,
        signature=_sig(eve, t1),
        subject_did=eve,
        role="corpus_admin",
    )
    with pytest.raises(NotAuthorized):
        await log.append(eve_self)


@pytest.mark.asyncio
async def test_genesis_carveout_requires_corpus_admin_role() -> None:
    """Test 5: self-signed RoleAssertion at position=0 with role != corpus_admin
    is refused — carve-out is ONLY for role=corpus_admin (the bootstrap role)."""
    log = InMemoryGovernanceLog()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    # Try to bootstrap with role=reviewer instead of corpus_admin.
    bad_genesis = RoleAssertionEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, t0),
        subject_did=ALICE,
        role="reviewer",
    )
    with pytest.raises(NotAuthorized):
        await log.append(bad_genesis)
