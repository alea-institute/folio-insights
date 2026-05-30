"""Contest workflow: appending a ContestEvent records the vote on the log (07-05a Task 1).

End-to-end through ``InMemoryGovernanceLog.append`` + ``iter_events``:
  * Bob casts a contest on a shard with a position-text.
  * The contest is appended; query the log; assert all fields preserved.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.contest import ContestEvent, validate_contest
from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
BOB = "did:fi:bob"
SHARD = "fi:shard:abc"


def _sig() -> AttestedSignature:
    return AttestedSignature(
        did=BOB,
        action="contest",
        signed_at=datetime(2026, 1, 1, tzinfo=UTC),
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{BOB}#key-1",
        did_doc_snapshot_at=datetime(2026, 1, 1, tzinfo=UTC),
        verified=None,
    )


async def test_contest_event_appends_and_is_iterable() -> None:
    """A ContestEvent appends + appears in iter_events with all fields preserved."""
    log = InMemoryGovernanceLog()
    event = ContestEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri=SHARD,
        voter_did=BOB,
        position_text="I disagree because...",
    )
    persisted = await log.append(event)
    assert persisted.position == 0
    assert persisted.voter_did == BOB
    assert persisted.position_text == "I disagree because..."
    assert persisted.shard_iri == SHARD
    # iter_events yields the persisted event.
    collected = [ev async for ev in log.iter_events(CORPUS)]
    assert len(collected) == 1
    assert collected[0].voter_did == BOB


def test_validate_contest_refuses_non_did_voter() -> None:
    """validate_contest() defense-in-depth refuses non-DID voter prefix."""
    event = ContestEvent.model_construct(
        corpus=CORPUS,
        position=-1,
        signature=_sig(),
        action="contest",
        shard_iri=SHARD,
        voter_did="bob",  # not a DID
        position_text="reason",
    )
    with pytest.raises(ValueError, match="did:"):
        validate_contest(event)


def test_validate_contest_refuses_empty_position_text() -> None:
    """validate_contest() refuses empty position_text."""
    event = ContestEvent.model_construct(
        corpus=CORPUS,
        position=-1,
        signature=_sig(),
        action="contest",
        shard_iri=SHARD,
        voter_did=BOB,
        position_text="",
    )
    with pytest.raises(ValueError, match="position_text"):
        validate_contest(event)
