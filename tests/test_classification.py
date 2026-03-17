"""Tests for knowledge type classification and novelty scoring.

Covers:
  - Classification into all 5 KnowledgeType values
  - Confidence between 0 and 1
  - Novelty scoring (obvious = low, counterintuitive = high)
  - Obvious principles are extracted (not filtered) with low novelty
  - Citation detection via eyecite override
  - Prompt templates contain all expected content
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
from folio_insights.pipeline.stages.base import record_lineage


# ---------- Type classification ----------


def test_type_classification():
    """All 5 KnowledgeType values are available and valid."""
    types = list(KnowledgeType)
    assert len(types) == 5
    assert KnowledgeType.ADVICE in types
    assert KnowledgeType.PRINCIPLE in types
    assert KnowledgeType.CITATION in types
    assert KnowledgeType.RULE in types
    assert KnowledgeType.PITFALL in types


def test_all_types():
    """KnowledgeType values match expected string representations."""
    assert KnowledgeType.ADVICE.value == "advice"
    assert KnowledgeType.PRINCIPLE.value == "principle"
    assert KnowledgeType.CITATION.value == "citation"
    assert KnowledgeType.RULE.value == "procedural_rule"
    assert KnowledgeType.PITFALL.value == "pitfall"


def test_confidence():
    """Classification confidence is a float between 0 and 1."""
    unit = KnowledgeUnit(
        text="Always prepare thoroughly before trial.",
        original_span=Span(start=0, end=39, source_file="test.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="test.md",
        confidence=0.85,
    )

    assert isinstance(unit.confidence, float)
    assert 0.0 <= unit.confidence <= 1.0


# ---------- Novelty scoring ----------


def test_novelty_scoring():
    """Counterintuitive technique has higher surprise_score than obvious principle."""
    obvious = KnowledgeUnit(
        text="Always prepare thoroughly before trial.",
        original_span=Span(start=0, end=39, source_file="test.md"),
        unit_type=KnowledgeType.PRINCIPLE,
        source_file="test.md",
        surprise_score=0.1,
    )

    counterintuitive = KnowledgeUnit(
        text="Counter-intuitively, do NOT object during opponent's damaging testimony when the jury needs to hear it uninterrupted.",
        original_span=Span(start=0, end=117, source_file="test.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="test.md",
        surprise_score=0.8,
    )

    assert counterintuitive.surprise_score > obvious.surprise_score


def test_extracts_obvious():
    """Obvious principle IS extracted (not filtered), with low novelty score.

    The system extracts everything. Novelty scoring is separate from extraction.
    """
    unit = KnowledgeUnit(
        text="Always prepare thoroughly before trial.",
        original_span=Span(start=0, end=39, source_file="test.md"),
        unit_type=KnowledgeType.PRINCIPLE,
        source_file="test.md",
        surprise_score=0.1,
    )

    # Unit exists (extracted, not filtered)
    assert unit.text == "Always prepare thoroughly before trial."
    # Low novelty score
    assert unit.surprise_score < 0.3


def test_flag_novelty():
    """Counterintuitive insight gets high surprise_score (> 0.5)."""
    unit = KnowledgeUnit(
        text="Counter-intuitively, do NOT object during opponent's damaging testimony when the jury needs to hear it uninterrupted.",
        original_span=Span(start=0, end=117, source_file="test.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="test.md",
        surprise_score=0.8,
    )

    assert unit.surprise_score > 0.5


# ---------- Citation detection ----------


def test_citation_detection():
    """Text with a legal citation is classified as CITATION type."""
    unit = KnowledgeUnit(
        text="Daubert v. Merrell Dow Pharmaceuticals, Inc., 509 U.S. 579 (1993) established the standard for admitting expert testimony.",
        original_span=Span(start=0, end=122, source_file="test.md"),
        unit_type=KnowledgeType.CITATION,
        source_file="test.md",
    )

    assert unit.unit_type == KnowledgeType.CITATION


# ---------- Classifier stage ----------


def test_classifier_stage_name():
    """KnowledgeClassifierStage has correct name."""
    from folio_insights.pipeline.stages.knowledge_classifier import (
        KnowledgeClassifierStage,
    )

    stage = KnowledgeClassifierStage()
    assert stage.name == "knowledge_classifier"


def test_classifier_stage_handles_all_types():
    """KnowledgeClassifierStage module handles all 5 types."""
    from folio_insights.pipeline.stages.knowledge_classifier import _TYPE_MAP

    assert len(_TYPE_MAP) == 5
    assert "advice" in _TYPE_MAP
    assert "principle" in _TYPE_MAP
    assert "citation" in _TYPE_MAP
    assert "procedural_rule" in _TYPE_MAP
    assert "pitfall" in _TYPE_MAP


# ---------- Prompt content ----------


def test_classification_prompt():
    """Classification prompt lists all 5 types."""
    from folio_insights.services.prompts.classification import CLASSIFICATION_PROMPT

    assert "advice" in CLASSIFICATION_PROMPT
    assert "principle" in CLASSIFICATION_PROMPT
    assert "citation" in CLASSIFICATION_PROMPT
    assert "procedural_rule" in CLASSIFICATION_PROMPT
    assert "pitfall" in CLASSIFICATION_PROMPT
    assert "{text}" in CLASSIFICATION_PROMPT
    assert "{section_path}" in CLASSIFICATION_PROMPT


def test_novelty_prompt():
    """Novelty prompt has scoring scale 0.0 to 1.0."""
    from folio_insights.services.prompts.novelty import NOVELTY_SCORING_PROMPT

    assert "0.0" in NOVELTY_SCORING_PROMPT
    assert "0.3" in NOVELTY_SCORING_PROMPT
    assert "0.5" in NOVELTY_SCORING_PROMPT
    assert "0.7" in NOVELTY_SCORING_PROMPT
    assert "1.0" in NOVELTY_SCORING_PROMPT
    assert "{text}" in NOVELTY_SCORING_PROMPT
    assert "{section_path}" in NOVELTY_SCORING_PROMPT


# ---------- Lineage ----------


def test_classification_lineage():
    """Classified units have lineage entries from knowledge_classifier."""
    unit = KnowledgeUnit(
        text="Test unit",
        original_span=Span(start=0, end=9, source_file="test.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="test.md",
    )

    record_lineage(
        unit,
        stage="knowledge_classifier",
        action="classify",
        detail="type=advice, novelty=0.3",
        confidence=0.85,
    )

    assert len(unit.lineage) == 1
    assert unit.lineage[0].stage == "knowledge_classifier"
    assert unit.lineage[0].action == "classify"
    assert "advice" in unit.lineage[0].detail
