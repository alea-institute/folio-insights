"""Phase 9 U1 (R4): reconciliation proposals draw only on the eight
``ReconciliationStrategy`` values and are never applied."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import get_args

import pytest
from pydantic import ValidationError

from folio_insights.shards.subtypes import ReconciliationStrategy
from folio_insights.validation.proposals import (
    RECONCILIATION_STRATEGIES,
    Proposal,
    propose_for_conflict_set,
    propose_for_contradiction,
)

from tests.validation.conftest import vshard

JURISDICTION = {"us.common_law": "us", "uk.england.common_law": "uk.england",
                "us.ucc": "us"}.get


def strategies(proposals):
    return [p.strategy for p in proposals]


def test_the_strategy_vocabulary_is_the_envelope_literal() -> None:
    assert RECONCILIATION_STRATEGIES == get_args(ReconciliationStrategy)
    assert len(RECONCILIATION_STRATEGIES) == 8
    with pytest.raises(ValidationError):
        Proposal(strategy="prefer_latest", rank=1, rationale="not a strategy")  # type: ignore[arg-type]


def test_jurisdiction_first_then_framework_then_voice() -> None:
    a = vshard(1, framework_id="us.common_law", speech_act="holding")
    b = vshard(2, framework_id="uk.england.common_law", speech_act="dictum")
    got = strategies(propose_for_contradiction(a, b, jurisdiction_of=JURISDICTION))
    assert got[:3] == ["jurisdictional_scoping", "contextual_limitation", "voice_attribution"]
    assert got[-1] == "unreconciled" and len(got) == len(set(got))


def test_time_shared_terms_and_shared_source() -> None:
    a = vshard(1, source_uri="urn:x:doc", reference="urn:x:term",
               valid_time_start=datetime(2001, 1, 1, tzinfo=UTC))
    b = vshard(2, source_uri="urn:x:doc", reference="urn:x:term",
               valid_time_start=datetime(2010, 1, 1, tzinfo=UTC))
    proposals = propose_for_contradiction(a, b, jurisdiction_of=JURISDICTION)
    got = strategies(proposals)
    assert got == ["subsequent_overruling", "sense_distinction", "textual_correction",
                   "retraction_later", "unreconciled"]
    assert b.shard_iri in proposals[0].rationale
    assert set(got) <= set(RECONCILIATION_STRATEGIES)


def test_conflict_sets_of_one_and_many() -> None:
    one = strategies(propose_for_conflict_set([vshard(1)]))
    assert one == ["textual_correction", "sense_distinction", "unreconciled"]
    many = propose_for_conflict_set(
        [vshard(1, framework_id="us.common_law"), vshard(2, framework_id="us.ucc"), vshard(3)],
        jurisdiction_of=JURISDICTION)
    assert strategies(many)[-1] == "unreconciled"
    assert [p.rank for p in many] == list(range(1, len(many) + 1))
    assert strategies(propose_for_conflict_set([])) == ["unreconciled"]
