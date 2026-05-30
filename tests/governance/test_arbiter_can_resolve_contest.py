"""Arbiter resolution path (07-05a Task 1): a ContestResolutionEvent with
``resolution_path="arbiter"`` is appended after a prior ContestEvent for the
same shard. The shard's state moves from contested → resolved-by-arbiter.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.contest import ContestEvent
from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.governance.resolve_contest import (
    ContestResolutionEvent,
    validate_contest_resolution,
)
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"  # the arbiter
BOB = "did:fi:bob"      # the contester
SHARD = "fi:shard:abc"


def _sig(did: str, action: str) -> AttestedSignature:
    return AttestedSignature(
        did=did,
        action=action,  # type: ignore[arg-type]
        signed_at=datetime(2026, 1, 1, tzinfo=UTC),
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{did}#key-1",
        did_doc_snapshot_at=datetime(2026, 1, 1, tzinfo=UTC),
        verified=None,
    )


async def test_arbiter_resolves_after_contest() -> None:
    """Contest at position 0 followed by arbiter resolution at position 1 appends cleanly."""
    log = InMemoryGovernanceLog()
    contest = ContestEvent(
        corpus=CORPUS,
        signature=_sig(BOB, "contest"),
        shard_iri=SHARD,
        voter_did=BOB,
        position_text="I disagree.",
    )
    await log.append(contest)

    resolution = ContestResolutionEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, "resolve_contest"),
        shard_iri=SHARD,
        resolution_path="arbiter",
    )
    # validator confirms a prior contest exists.
    await validate_contest_resolution(resolution, log=log)
    persisted = await log.append(resolution)
    assert persisted.position == 1
    assert persisted.resolution_path == "arbiter"
    assert persisted.shard_iri == SHARD


async def test_resolve_without_prior_contest_refused_by_validator() -> None:
    """No prior ContestEvent for the shard → validate_contest_resolution refuses."""
    log = InMemoryGovernanceLog()
    resolution = ContestResolutionEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, "resolve_contest"),
        shard_iri="fi:shard:never-contested",
        resolution_path="arbiter",
    )
    with pytest.raises(ValueError, match="no prior ContestEvent"):
        await validate_contest_resolution(resolution, log=log)
