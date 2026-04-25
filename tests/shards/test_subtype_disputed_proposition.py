"""Phase 03 DisputedPropositionShard (REQ SHARD-03; PRD §6.2.2 Example A.3).

Covers exit criterion 1 (A.3 round-trips) + CONTEXT D-02/D-03 invariants:
epistemic_status 4-subset, ≥1 objection, valid Reply.objection_index.

NOTE: D-03 4-subset is {"hypothesis", "authority_only", "contested", "aporetic"};
"authority_only" substitutes for the PRD's "attested" (envelope ships no
"attested" Literal — planner-resolved 2026-04-25; see 03-CONTEXT.md D-03).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from folio_insights.shards import (
    DisputedPropositionShard,
    Objection,
    Reply,
    Shard,
)

from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.shards

_FIXTURE = Path(__file__).parent / "fixtures" / "example_a3_disputed_proposition.json"

# D-03 4-subset (must match _DISPUTED_EPISTEMIC_STATUS_SUBSET in subtypes.py).
_DISPUTED_EPISTEMIC_STATUS = ["hypothesis", "authority_only", "contested", "aporetic"]
# The 4 envelope values OUTSIDE the disputed subset (must trigger validator).
_OUTSIDE_SUBSET = [
    "per_se_nota_quoad_se",
    "per_se_nota_quoad_nos",
    "demonstrable",
    "superseded",
]


def test_a3_fixture_round_trips() -> None:
    """PRD §6.2.2 Example A.3 round-trips via TypeAdapter(Shard) (SHARD-03 exit 1)."""
    payload = json.loads(_FIXTURE.read_text())
    parsed = TypeAdapter(Shard).validate_python(payload)
    assert isinstance(parsed, DisputedPropositionShard)
    assert parsed.shard_type == "disputed_proposition"
    assert parsed.utrum == payload["utrum"]
    assert len(parsed.objections) == len(payload["objections"])
    redumped = parsed.model_dump(mode="json")
    assert redumped == payload


@pytest.mark.parametrize("status", _DISPUTED_EPISTEMIC_STATUS)
def test_each_in_subset_status_constructs(status: str) -> None:
    """D-03: all 4 in-subset epistemic_status values construct successfully."""
    shard = _sample_shard(DisputedPropositionShard, epistemic_status=status)
    assert shard.epistemic_status == status


@pytest.mark.parametrize("status", _OUTSIDE_SUBSET)
def test_out_of_subset_status_raises(status: str) -> None:
    """D-03: epistemic_status outside the 4-subset raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(DisputedPropositionShard, epistemic_status=status)
    msg = str(exc_info.value)
    assert "epistemic_status" in msg
    assert "4-subset" in msg or "hypothesis" in msg


def test_empty_objections_raises() -> None:
    """D-02: objections must have ≥1 element."""
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(DisputedPropositionShard, objections=[], replies=[])
    msg = str(exc_info.value)
    assert "objections" in msg
    assert "at least one" in msg.lower() or "≥1" in msg


def test_reply_objection_index_out_of_range_raises() -> None:
    """D-02: Reply.objection_index must be a valid range(len(objections)) index."""
    bad_reply = Reply(
        objection_index=99,
        replies_via="distinguo",
        argument="(invalid index)",
    )
    objection = Objection(cites="urn:x:1", argues="a", strength=0.5)
    sed_contra = Objection(cites="urn:x:2", argues="b", strength=0.8)
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(
            DisputedPropositionShard,
            objections=[objection],
            sed_contra=sed_contra,
            replies=[bad_reply],
        )
    msg = str(exc_info.value)
    assert "objection_index" in msg or "out of range" in msg.lower()


def test_objection_strength_outside_range_raises() -> None:
    """Objection.strength is bounded ge=0.0, le=1.0 (Phase 3 nested-model invariant)."""
    with pytest.raises(ValidationError):
        Objection(cites="urn:x:1", argues="a", strength=1.5)
    with pytest.raises(ValidationError):
        Objection(cites="urn:x:1", argues="a", strength=-0.1)


def test_reply_replies_via_invalid_value_raises() -> None:
    """Reply.replies_via Literal[4] rejects unknown values."""
    with pytest.raises(ValidationError):
        Reply(objection_index=0, replies_via="custom_strategy", argument="...")
