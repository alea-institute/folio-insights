"""authorize()-layer genesis carve-out polarity (D-10 / D-19 / Issue #3 closure).

Tests 10, 11, 12, 13 from PLAN 07-04a. The genesis carve-out is STRUCTURAL
INSIDE ``authorize()`` itself — no CLI is exempt from the authorize-first rule.
``action="corpus_init"`` is the bookkeeping action name authorize() recognizes
for the bootstrap step.

  * Test 10 (POSITIVE rows=0, did==admin_did): Allow w/ "genesis bootstrap" reason.
  * Test 11 (NEGATIVE rows>0): Deny(reason="corpus_already_initialized").
  * Test 12 (NEGATIVE rows=0, mismatched DID): Deny(reason="genesis_mismatch").
  * Test 13 (NEGATIVE rows=0, non-corpus_init action): Deny(reason="no_active_role").
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
ALICE = "did:fi:alice"
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


@pytest.mark.asyncio
async def test_genesis_carve_out_positive_allow_on_empty_log() -> None:
    """Test 10: rows=0 + did==admin_did + action=corpus_init -> Allow."""
    log = InMemoryGovernanceLog()
    result = await authorize(
        ALICE,
        "corpus_init",
        CORPUS,
        log=log,
        admin_did=ALICE,
    )
    assert isinstance(result, Allow)
    assert result.reason is not None
    assert "genesis bootstrap" in result.reason


# ── NEGATIVE polarity (3 cases) ──


@pytest.mark.asyncio
async def test_genesis_carve_out_refused_on_non_empty_log() -> None:
    """Test 11: rows>0 -> Deny(reason="corpus_already_initialized")."""
    log = InMemoryGovernanceLog()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    # Bootstrap so the log has rows>0.
    await log.append(
        RoleAssertionEvent(
            corpus=CORPUS,
            signature=_sig(ALICE, t0),
            subject_did=ALICE,
            role="corpus_admin",
        )
    )
    result = await authorize(
        ALICE,
        "corpus_init",
        CORPUS,
        log=log,
        admin_did=ALICE,
    )
    assert isinstance(result, Deny)
    assert result.reason == "corpus_already_initialized"


@pytest.mark.asyncio
async def test_genesis_carve_out_refused_on_did_mismatch() -> None:
    """Test 12: rows=0 + did != admin_did -> Deny(reason="genesis_mismatch")."""
    log = InMemoryGovernanceLog()
    result = await authorize(
        EVE,
        "corpus_init",
        CORPUS,
        log=log,
        admin_did=ALICE,
    )
    assert isinstance(result, Deny)
    assert result.reason == "genesis_mismatch"


@pytest.mark.asyncio
async def test_genesis_carve_out_action_specific() -> None:
    """Test 13: rows=0 + action != corpus_init -> Deny(reason="no_active_role").

    The carve-out is action-specific — non-corpus_init actions at rows=0 fall
    through to the standard authorization path, which returns no_active_role
    because no roles have been asserted yet.
    """
    log = InMemoryGovernanceLog()
    result = await authorize(
        ALICE,
        "promote",
        CORPUS,
        log=log,
        admin_did=ALICE,
    )
    assert isinstance(result, Deny)
    assert result.reason == "no_active_role"


@pytest.mark.asyncio
async def test_corpus_init_without_admin_did_refused() -> None:
    """Extra polarity: corpus_init with admin_did=None -> Deny."""
    log = InMemoryGovernanceLog()
    result = await authorize(
        ALICE,
        "corpus_init",
        CORPUS,
        log=log,
        # admin_did omitted -> None.
    )
    assert isinstance(result, Deny)
    assert result.reason == "genesis_admin_did_required"
