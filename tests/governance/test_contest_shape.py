"""SHACL fi:ContestShape positive + negative polarity tests (07-05a Task 1).

Constraints:
  * ``fi:shardIri`` non-empty xsd:string.
  * ``fi:voterDid`` non-empty xsd:string starting with ``"did:"``.
  * ``fi:positionText`` non-empty xsd:string.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import ContestEvent
from folio_insights.governance.shape_validation import (
    ValidationResult,
    validate_contest_shape,
)
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"
BOB = "did:fi:bob"


def _sig() -> AttestedSignature:
    return AttestedSignature(
        did=ALICE,
        action="contest",
        signed_at=datetime(2026, 1, 1, tzinfo=UTC),
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{ALICE}#key-1",
        did_doc_snapshot_at=datetime(2026, 1, 1, tzinfo=UTC),
        verified=None,
    )


# ── POSITIVE ──


def test_valid_contest_conforms() -> None:
    """A well-formed contest event conforms."""
    event = ContestEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:disputed",
        voter_did=BOB,
        position_text="I disagree because the cited authority is incomplete.",
    )
    result = validate_contest_shape(event)
    assert isinstance(result, ValidationResult)
    assert result.conforms is True, f"violations: {result.violations}"


# ── NEGATIVE ──


def test_empty_position_text_refused_by_shape() -> None:
    """Empty position_text triggers the SHACL belt (sh:minLength 1)."""
    event = ContestEvent.model_construct(
        corpus=CORPUS,
        position=-1,
        signature=_sig(),
        action="contest",
        shard_iri="fi:shard:disputed",
        voter_did=BOB,
        position_text="",  # empty — refused by sh:minLength
    )
    result = validate_contest_shape(event)
    assert result.conforms is False
    assert len(result.violations) >= 1


def test_non_did_voter_refused_by_shape() -> None:
    """voter_did not starting with did: triggers the SHACL pattern constraint."""
    event = ContestEvent.model_construct(
        corpus=CORPUS,
        position=-1,
        signature=_sig(),
        action="contest",
        shard_iri="fi:shard:disputed",
        voter_did="bob",  # not a DID
        position_text="I disagree.",
    )
    result = validate_contest_shape(event)
    assert result.conforms is False
    assert len(result.violations) >= 1
