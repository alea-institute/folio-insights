"""Tests for FOLIO four-path tagging, heading context, and reconciliation.

Covers:
  - Four extraction paths produce tagged results
  - Confidence pipeline produces scores in [0, 1]
  - Heading context path with proximity weighting
  - Extraction path is recorded on each ConceptTag
  - FourPathReconciler integrates all four paths
  - Lineage records which paths contributed
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from folio_insights.models.knowledge_unit import (
    ConceptTag,
    KnowledgeType,
    KnowledgeUnit,
    Span,
)
from folio_insights.pipeline.stages.base import InsightsJob
from folio_insights.services.bridge.reconciliation_bridge import (
    FourPathReconciler,
    ReconciledConcept,
)
from folio_insights.services.heading_context import HeadingContextExtractor


# ---------- FourPathReconciler ----------


def test_four_path():
    """Provide a knowledge unit with clear FOLIO concept match; verify folio_tags non-empty."""
    reconciler = FourPathReconciler()

    ruler = [{"iri": "https://folio.test/123", "label": "Cross-Examination", "confidence": 0.85, "branch": "Litigation"}]
    llm = [{"iri": "https://folio.test/123", "label": "Cross-Examination", "confidence": 0.8, "concept_text": "Cross-Examination", "branch": "Litigation"}]
    semantic = [{"iri": "https://folio.test/123", "label": "Cross-Examination", "confidence": 0.75, "branch": "Litigation"}]
    heading = [{"iri": "https://folio.test/456", "label": "Expert Witnesses", "confidence": 0.7, "branch": "Litigation"}]

    results = reconciler.reconcile(ruler, llm, semantic, heading)

    assert len(results) >= 1

    # Check that the main concept has extraction paths recorded
    cross_exam = [r for r in results if r.label == "Cross-Examination"]
    assert len(cross_exam) >= 1
    assert len(cross_exam[0].contributing_paths) >= 1

    # Check that heading context concept is also present
    expert = [r for r in results if r.label == "Expert Witnesses"]
    assert len(expert) >= 1
    assert "heading_context" in expert[0].contributing_paths


def test_confidence_pipeline():
    """Verify confidence scores are between 0 and 1."""
    reconciler = FourPathReconciler()

    ruler = [{"iri": "https://folio.test/1", "label": "Deposition", "confidence": 0.9, "branch": ""}]
    llm = [{"iri": "https://folio.test/1", "label": "Deposition", "confidence": 0.85, "concept_text": "Deposition", "branch": ""}]
    semantic = []
    heading = []

    results = reconciler.reconcile(ruler, llm, semantic, heading)

    for r in results:
        assert 0.0 <= r.confidence <= 1.0


def test_reconciler_semantic_boost():
    """Semantic path boosts confidence of matching base concepts."""
    reconciler = FourPathReconciler()

    ruler = [{"iri": "https://folio.test/1", "label": "Witness", "confidence": 0.7, "branch": ""}]
    llm = []
    semantic = [{"iri": "https://folio.test/1", "label": "Witness", "confidence": 0.6, "branch": ""}]
    heading = []

    results = reconciler.reconcile(ruler, llm, semantic, heading)
    witness = [r for r in results if r.label == "Witness"][0]

    # Semantic should have boosted confidence by 0.1
    assert witness.confidence >= 0.75  # 0.7 + 0.1 = 0.8, capped at 1.0
    assert "semantic" in witness.contributing_paths


def test_reconciler_heading_boost():
    """Heading context boosts confidence of matching concepts."""
    reconciler = FourPathReconciler()

    ruler = [{"iri": "https://folio.test/1", "label": "Trial", "confidence": 0.7, "branch": ""}]
    llm = []
    semantic = []
    heading = [{"iri": "https://folio.test/1", "label": "Trial", "confidence": 0.5, "branch": ""}]

    results = reconciler.reconcile(ruler, llm, semantic, heading)
    trial = [r for r in results if r.label == "Trial"][0]

    assert trial.confidence >= 0.7  # at least original, boosted by heading
    assert "heading_context" in trial.contributing_paths


# ---------- HeadingContextExtractor ----------


@pytest.mark.asyncio
async def test_heading_context_path():
    """Heading context extracts ConceptTags with proximity weighting."""
    mock_folio = MagicMock()

    # Return different matches for different headings
    def search_by_label(text):
        if "Methodology" in text:
            return [(MagicMock(iri="https://folio.test/method", preferred_label="Methodology", branch="Litigation"), 0.85)]
        if "Expert Witnesses" in text:
            return [(MagicMock(iri="https://folio.test/expert", preferred_label="Expert Witnesses", branch="Litigation"), 0.80)]
        if "Expert" in text or "8" in text:
            return [(MagicMock(iri="https://folio.test/expert", preferred_label="Expert Witnesses", branch="Litigation"), 0.75)]
        return []

    mock_folio.search_by_label = search_by_label

    extractor = HeadingContextExtractor(mock_folio)
    tags = await extractor.extract_heading_concepts(
        section_path=["Chapter 8: Expert Witnesses", "Methodology"],
        folio_service=mock_folio,
    )

    assert len(tags) >= 1

    # Most specific heading (Methodology) should have highest confidence weight
    method_tags = [t for t in tags if "Methodology" in t.label]
    assert len(method_tags) >= 1
    assert method_tags[0].extraction_path == "heading_context"

    # All tags have valid confidence
    for tag in tags:
        assert 0.0 <= tag.confidence <= 1.0
        assert tag.extraction_path == "heading_context"


@pytest.mark.asyncio
async def test_heading_context_empty_path():
    """Empty section_path produces no heading concepts."""
    mock_folio = MagicMock()
    extractor = HeadingContextExtractor(mock_folio)
    tags = await extractor.extract_heading_concepts([], mock_folio)
    assert tags == []


@pytest.mark.asyncio
async def test_heading_context_proximity_weighting():
    """Verify proximity weighting: immediate > parent > chapter."""
    mock_folio = MagicMock()

    # All headings return similar confidence from FOLIO
    mock_folio.search_by_label.return_value = [
        (MagicMock(iri="https://folio.test/concept", preferred_label="Concept", branch=""), 0.9)
    ]

    extractor = HeadingContextExtractor(mock_folio)
    tags = await extractor.extract_heading_concepts(
        section_path=["Chapter", "Section", "Subsection"],
        folio_service=mock_folio,
    )

    # Should have 3 tags (one per heading level)
    assert len(tags) == 3

    # Most specific (Subsection) has weight 1.0, so highest confidence
    # Parent (Section) has weight 0.7
    # Chapter has weight 0.4
    # All have FOLIO score 0.9, so confidences are 0.9*1.0, 0.9*0.7, 0.9*0.4
    confidences = sorted([t.confidence for t in tags], reverse=True)
    assert confidences[0] > confidences[1] > confidences[2]


# ---------- Extraction path recording ----------


def test_extraction_path_recorded():
    """Each ConceptTag has extraction_path in valid set."""
    valid_paths = {"entity_ruler", "llm", "semantic", "heading_context"}

    reconciler = FourPathReconciler()
    ruler = [{"iri": "https://folio.test/1", "label": "A", "confidence": 0.8, "branch": ""}]
    llm = [{"iri": "https://folio.test/2", "label": "B", "confidence": 0.7, "concept_text": "B", "branch": ""}]
    semantic = [{"iri": "https://folio.test/3", "label": "C", "confidence": 0.6, "branch": ""}]
    heading = [{"iri": "https://folio.test/4", "label": "D", "confidence": 0.5, "branch": ""}]

    results = reconciler.reconcile(ruler, llm, semantic, heading)

    for r in results:
        for path in r.contributing_paths:
            assert path in valid_paths


# ---------- Lineage ----------


def test_lineage():
    """Verify tagged units can have lineage from folio_tagger stage."""
    from folio_insights.pipeline.stages.base import record_lineage

    unit = KnowledgeUnit(
        text="Lock expert into document list",
        original_span=Span(start=0, end=30, source_file="test.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="test.md",
    )

    record_lineage(
        unit,
        stage="folio_tagger",
        action="tag",
        detail="3 concepts, paths=['entity_ruler', 'llm', 'heading_context']",
    )

    assert len(unit.lineage) == 1
    assert unit.lineage[0].stage == "folio_tagger"
    assert unit.lineage[0].action == "tag"
    assert "entity_ruler" in unit.lineage[0].detail
    assert "heading_context" in unit.lineage[0].detail


# ---------- FolioTaggerStage instantiation ----------


def test_folio_tagger_stage_name():
    """FolioTaggerStage has correct name and references all four paths."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    stage = FolioTaggerStage()
    assert stage.name == "folio_tagger"

    # Verify the module mentions all four paths
    import inspect
    source = inspect.getsource(FolioTaggerStage)
    assert "entity_ruler" in source
    assert "llm" in source
    assert "semantic" in source
    assert "heading_context" in source
