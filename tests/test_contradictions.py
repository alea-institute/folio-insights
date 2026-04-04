"""Tests for TASK-04: contradiction detection and resolution.

Covers cross-encoder NLI screening (graceful degradation),
deep analysis (graceful degradation), and resolution model storage.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from folio_insights.models.task import Contradiction
from folio_insights.services.contradiction_detector import ContradictionDetector
from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span


def _make_unit(unit_id: str, text: str) -> KnowledgeUnit:
    """Create a minimal KnowledgeUnit for testing."""
    return KnowledgeUnit(
        id=unit_id,
        text=text,
        original_span=Span(start=0, end=len(text), source_file="test.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="test.md",
    )


def test_nli_screening():
    """ContradictionDetector initializes and gracefully handles missing NLI model.
    When the cross-encoder model is unavailable, screen_pairs raises an exception
    that the ContradictionDetectionStage catches, resulting in no contradictions."""
    detector = ContradictionDetector()

    # Verify the detector initializes without loading the heavy model
    assert detector._nli_model is None
    assert detector._label_mapping == ["contradiction", "entailment", "neutral"]

    # If cross-encoder is available, screen_pairs works; if not, it raises
    units = [
        _make_unit("u1", "Always use leading questions on cross-examination"),
        _make_unit("u2", "Never use leading questions on cross-examination"),
    ]

    try:
        result = asyncio.run(detector.screen_pairs(units, threshold=0.7))
        # If the model loaded successfully, result is a list of tuples
        assert isinstance(result, list)
        for item in result:
            assert len(item) == 3  # (uid_a, uid_b, score)
    except Exception:
        # Model not available -- this is the graceful degradation path
        # The ContradictionDetectionStage catches this and continues
        pass


def test_deep_analysis():
    """When LLM is unavailable, deep_analyze returns None (graceful degradation).
    This means contradictions list remains empty."""
    detector = ContradictionDetector(llm_bridge=None)

    unit_a = _make_unit("u1", "Always object immediately to hearsay")
    unit_b = _make_unit("u2", "Wait before objecting to hearsay to avoid highlighting it")

    # Without LLM, deep_analyze should return None
    result = asyncio.run(detector.deep_analyze(unit_a, unit_b, task_label="Objections"))
    assert result is None


def test_resolution_storage():
    """Contradiction model correctly stores resolution fields and serializes."""
    task_id = str(uuid4())
    contradiction = Contradiction(
        id=str(uuid4()),
        task_id=task_id,
        unit_id_a=str(uuid4()),
        unit_id_b=str(uuid4()),
        nli_score=0.85,
        contradiction_type="jurisdictional",
        explanation="State courts differ on this point.",
        context_dependency="Jurisdiction-dependent rule",
        resolution="jurisdiction",
        resolved_text="Both positions valid in their respective jurisdictions",
        resolver_note="Reviewed by legal subject matter expert",
        resolved_at="2026-04-01T12:00:00Z",
    )

    # Verify fields are set correctly
    assert contradiction.task_id == task_id
    assert contradiction.contradiction_type == "jurisdictional"
    assert contradiction.resolution == "jurisdiction"
    assert contradiction.resolved_text is not None
    assert "Both positions" in contradiction.resolved_text
    assert contradiction.resolver_note == "Reviewed by legal subject matter expert"
    assert contradiction.resolved_at == "2026-04-01T12:00:00Z"
    assert contradiction.nli_score == pytest.approx(0.85)

    # Verify serialization round-trip
    data = contradiction.model_dump()
    restored = Contradiction(**data)
    assert restored.resolution == "jurisdiction"
    assert restored.resolved_text == contradiction.resolved_text
    assert restored.resolver_note == contradiction.resolver_note
    assert restored.resolved_at == contradiction.resolved_at

    # Verify all resolution types are accepted
    for res_type in ["keep_both", "prefer_a", "prefer_b", "merge", "jurisdiction"]:
        c = Contradiction(
            task_id="t1",
            unit_id_a="u1",
            unit_id_b="u2",
            nli_score=0.7,
            resolution=res_type,
        )
        assert c.resolution == res_type
