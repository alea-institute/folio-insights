"""Phase 03 ConflictingAuthoritiesShard (REQ SHARD-04; PRD §6.2.3 Example A.2).

Covers exit criterion 1 (A.2 round-trips) + CONTEXT D-04: 8-value
ReconciliationStrategy lock (NO 9th "custom" escape hatch), sic/non non-empty,
non-blank reconciliation_note, AuthorityPosition.weight 4-value Literal.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from folio_insights.shards import (
    AuthorityPosition,
    ConflictingAuthoritiesShard,
    ReconciliationStrategy,
    Shard,
)

from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.shards

_FIXTURE = Path(__file__).parent / "fixtures" / "example_a2_conflicting_authorities.json"

# REVIEW IN-03 (Phase 03): derive from the public Literal alias rather than
# hand-typing the 8-tuple, so the 8-value lock in subtypes.py stays the single
# source of truth. ``get_args`` returns a tuple in declaration order.
_RECONCILIATION_STRATEGIES = list(get_args(ReconciliationStrategy))
# AuthorityPosition.weight is an inline Literal[4] on the nested model (no
# public alias). Hand-typed mirror is acceptable per IN-03 scope.
_AUTHORITY_WEIGHTS = ["binding", "persuasive", "minority", "majority"]


def test_a2_fixture_round_trips() -> None:
    """PRD §6.2.3 Example A.2 round-trips via TypeAdapter(Shard) (SHARD-04 exit 1)."""
    payload = json.loads(_FIXTURE.read_text())
    parsed = TypeAdapter(Shard).validate_python(payload)
    assert isinstance(parsed, ConflictingAuthoritiesShard)
    assert parsed.shard_type == "conflicting_authorities"
    assert parsed.reconciliation_strategy == payload["reconciliation_strategy"]
    redumped = parsed.model_dump(mode="json")
    assert redumped == payload


@pytest.mark.parametrize("strategy", _RECONCILIATION_STRATEGIES)
def test_each_reconciliation_strategy_constructs(strategy: str) -> None:
    """D-04: all 8 ReconciliationStrategy values construct successfully."""
    shard = _sample_shard(ConflictingAuthoritiesShard, reconciliation_strategy=strategy)
    assert shard.reconciliation_strategy == strategy


def test_ninth_reconciliation_strategy_rejected() -> None:
    """D-04: 'custom' (or any 9th value) raises ValidationError (Literal lock)."""
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(ConflictingAuthoritiesShard, reconciliation_strategy="custom")
    msg = str(exc_info.value)
    assert "reconciliation_strategy" in msg or "literal" in msg.lower()


@pytest.mark.parametrize("weight", _AUTHORITY_WEIGHTS)
def test_each_authority_weight_constructs(weight: str) -> None:
    """D-04: all 4 AuthorityPosition.weight values construct."""
    pos = AuthorityPosition(
        authority_iri="urn:x:authority/test",
        position="...",
        jurisdiction="us.federal",
        weight=weight,
    )
    assert pos.weight == weight


def test_invalid_authority_weight_rejected() -> None:
    """AuthorityPosition.weight Literal[4] rejects unknown values."""
    with pytest.raises(ValidationError):
        AuthorityPosition(
            authority_iri="urn:x:authority/test",
            position="...",
            jurisdiction="us.federal",
            weight="dispositive",
        )


def test_empty_sic_raises() -> None:
    """D-04: sic must have ≥1 element."""
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(ConflictingAuthoritiesShard, sic=[])
    msg = str(exc_info.value)
    assert "sic" in msg


def test_empty_non_raises() -> None:
    """D-04: non must have ≥1 element."""
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(ConflictingAuthoritiesShard, non=[])
    msg = str(exc_info.value)
    assert "non" in msg


@pytest.mark.parametrize("note", ["", "   ", "\t\n"])
def test_blank_reconciliation_note_raises(note: str) -> None:
    """D-04: reconciliation_note must not be empty/whitespace-only."""
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(ConflictingAuthoritiesShard, reconciliation_note=note)
    msg = str(exc_info.value)
    assert "reconciliation_note" in msg
