"""Phase 03 HypothesisShard (REQ SHARD-06; PRD §6.2.5, §21.3 RESOLVED).

Covers exit criterion 2 (Hypothesis parses + validates) + exit criterion 3
(citation_required: bool = True ships). CONTEXT D-06 defers the promotion-time
gate to Phase 7 governance — Phase 3 ships the field, NOT the workflow.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from folio_insights.shards import HypothesisShard

from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.shards

_GENERATION_METHODS = ["combinatorial", "inductive", "analogical"]


@pytest.mark.parametrize("method", _GENERATION_METHODS)
def test_each_generation_method_constructs(method: str) -> None:
    """D-06: all 3 GenerationMethod values construct successfully."""
    shard = _sample_shard(HypothesisShard, generation_method=method)
    assert shard.generation_method == method


def test_invalid_generation_method_rejected() -> None:
    """D-06: GenerationMethod Literal[3] rejects unknown values."""
    with pytest.raises(ValidationError):
        _sample_shard(HypothesisShard, generation_method="speculative")


def test_ttl_days_default_is_90() -> None:
    """D-06: ttl_days defaults to 90 (PRD §6.2.5)."""
    shard = _sample_shard(HypothesisShard)
    assert shard.ttl_days == 90


def test_citation_required_defaults_true() -> None:
    """D-06 / §21.3 RESOLVED: citation_required defaults to True (Phase 3 ships field)."""
    shard = _sample_shard(HypothesisShard)
    assert shard.citation_required is True


def test_promotion_requirements_defaults_empty() -> None:
    """D-06: promotion_requirements defaults to []."""
    shard = _sample_shard(HypothesisShard)
    assert shard.promotion_requirements == []


@pytest.mark.parametrize("ttl", [1, 7, 30, 90, 365, 1_000_000])
def test_ttl_days_positive_accepted(ttl: int) -> None:
    """D-06: ttl_days >= 1 accepted across boundary + interior values."""
    shard = _sample_shard(HypothesisShard, ttl_days=ttl)
    assert shard.ttl_days == ttl


@pytest.mark.parametrize("ttl", [0, -1, -999])
def test_ttl_days_zero_or_negative_rejected(ttl: int) -> None:
    """D-06: ttl_days < 1 raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(HypothesisShard, ttl_days=ttl)
    msg = str(exc_info.value)
    assert "ttl_days" in msg


def test_citation_required_true_with_empty_deps_constructs() -> None:
    """D-06: Phase 3 ships the field, NOT the gate. A HypothesisShard with
    citation_required=True and empty depends_on_* lists MUST construct
    successfully — Phase 7 governance enforces the promotion-time gate.
    Adding a Phase-3 construction-time block would prevent the legitimate
    workflow of accumulating citations between extraction and promotion.
    """
    shard = _sample_shard(
        HypothesisShard,
        citation_required=True,
        depends_on_axioms=[],
        depends_on_definitions=[],
        depends_on_precedents=[],
        depends_on_shards=[],
    )
    assert shard.citation_required is True
    assert shard.depends_on_axioms == []
    assert shard.depends_on_definitions == []
    assert shard.depends_on_precedents == []
    assert shard.depends_on_shards == []


def test_hypothesis_round_trip() -> None:
    """HypothesisShard round-trips via model_dump + model_validate."""
    original = _sample_shard(HypothesisShard)
    rehydrated = HypothesisShard.model_validate(original.model_dump())
    assert rehydrated == original
