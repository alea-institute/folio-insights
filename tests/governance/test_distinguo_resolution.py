"""Distinguo resolution path (07-05a Task 1).

A ContestResolutionEvent with ``resolution_path="distinguo"`` is appended
after a prior ContestEvent; the resolution acknowledges that both sides of
the dispute have been distinguished (sense-fork).
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
ALICE = "did:fi:alice"
BOB = "did:fi:bob"
SHARD = "fi:shard:distinguo-target"


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


async def test_distinguo_resolution_appends() -> None:
    """A distinguo resolution follows a contest and lands at the next position."""
    log = InMemoryGovernanceLog()
    contest = ContestEvent(
        corpus=CORPUS,
        signature=_sig(BOB, "contest"),
        shard_iri=SHARD,
        voter_did=BOB,
        position_text="The two senses are distinct.",
    )
    await log.append(contest)

    resolution = ContestResolutionEvent(
        corpus=CORPUS,
        signature=_sig(ALICE, "resolve_contest"),
        shard_iri=SHARD,
        resolution_path="distinguo",
    )
    await validate_contest_resolution(resolution, log=log)
    persisted = await log.append(resolution)
    assert persisted.resolution_path == "distinguo"
    assert persisted.position == 1
