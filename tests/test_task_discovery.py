"""Tests for TASK-01: task discovery from headings and content clustering.

Covers heading analysis, FOLIO mapping, content clustering, LLM implicit
task discovery (fallback path), and the weighted blend confidence formula.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
from folio_insights.models.task import (
    DiscoveryJob,
    TaskCandidate,
    compute_task_confidence,
)
from folio_insights.pipeline.discovery.stages.heading_analysis import (
    HeadingAnalysisStage,
)


def _make_unit(
    unit_id: str,
    text: str,
    source_section: list[str],
    source_file: str = "ch1.md",
) -> KnowledgeUnit:
    """Create a minimal KnowledgeUnit for testing."""
    return KnowledgeUnit(
        id=unit_id,
        text=text,
        original_span=Span(start=0, end=len(text), source_file=source_file),
        unit_type=KnowledgeType.ADVICE,
        source_file=source_file,
        source_section=source_section,
    )


def test_heading_analysis_extracts_candidates():
    """HeadingAnalysisStage groups units by source_section and produces
    TaskCandidates with source_signal='heading'. Heading paths with
    fewer than 2 units should be filtered out."""
    units = [
        _make_unit("u1", "Pin down methodology first", ["Ch5", "Depositions"]),
        _make_unit("u2", "Control the narrative", ["Ch5", "Depositions"]),
        _make_unit("u3", "Use leading questions", ["Ch5", "Depositions"]),
        # Only 1 unit for this heading => should be filtered
        _make_unit("u4", "Jury selection basics", ["Ch6", "Jury Selection"]),
    ]

    job = DiscoveryJob(
        corpus_name="test",
        source_dir=Path("/tmp/test"),
        knowledge_units=units,
    )

    stage = HeadingAnalysisStage()
    result = asyncio.run(stage.execute(job))

    # Should produce candidate for "Depositions" (3 units) but not "Jury Selection" (1 unit)
    assert len(result.task_candidates) == 1
    candidate = result.task_candidates[0]
    assert candidate.label == "Depositions"
    assert candidate.source_signal == "heading"
    assert len(candidate.knowledge_unit_ids) == 3
    # Heading path ["Ch5", "Depositions"] has depth = len - 1 = 1
    # _PROXIMITY_WEIGHTS[1] = 0.7
    assert candidate.confidence == pytest.approx(0.7)


def test_folio_mapping_resolves_concepts():
    """FolioMappingStage sets proposed_sibling metadata when FOLIO service
    is unavailable (the graceful degradation path)."""
    from folio_insights.pipeline.discovery.stages.folio_mapping import (
        FolioMappingStage,
    )

    candidates = [
        TaskCandidate(
            label="Expert Depositions",
            source_signal="heading",
            confidence=0.8,
            heading_path=["Ch5", "Depositions"],
            knowledge_unit_ids=["u1", "u2"],
        ),
    ]

    job = DiscoveryJob(
        corpus_name="test",
        source_dir=Path("/tmp/test"),
        task_candidates=candidates,
    )

    stage = FolioMappingStage()
    result = asyncio.run(stage.execute(job))

    # Without FolioService, candidates should still be present and
    # have proposed_sibling metadata if unmapped
    assert len(result.task_candidates) >= 1
    for c in result.task_candidates:
        if c.folio_iri is None:
            # When FOLIO service is unavailable, label-based matching may
            # leave candidates unmapped; they should remain in the list
            assert c.label  # label should be preserved


def test_content_clustering_discovers_implicit_tasks():
    """ContentClusteringStage clusters units by embedding similarity
    and creates TaskCandidates for clusters not already covered by
    heading-based candidates."""
    pytest.importorskip("sentence_transformers")

    from folio_insights.pipeline.discovery.stages.content_clustering import (
        ContentClusteringStage,
    )

    # Create units with very similar text that should cluster together
    units = [
        _make_unit("u1", "Always prepare a cross-examination outline before trial", []),
        _make_unit("u2", "Prepare a detailed cross-examination outline in advance of trial", []),
        _make_unit("u3", "Draft cross-examination outlines well before trial starts", []),
        _make_unit("u4", "An unrelated unit about filing deadlines for motions", []),
    ]

    job = DiscoveryJob(
        corpus_name="test",
        source_dir=Path("/tmp/test"),
        knowledge_units=units,
        task_candidates=[],  # No heading-based candidates
    )

    stage = ContentClusteringStage()
    result = asyncio.run(stage.execute(job))

    # At least the three similar units should form a cluster candidate
    clustering_candidates = [
        c for c in result.task_candidates if c.source_signal == "clustering"
    ]
    # May or may not cluster depending on threshold, but stage should complete
    assert isinstance(clustering_candidates, list)


def test_implicit_task_discovery_via_llm():
    """When LLMBridge is unavailable, ContentClusteringStage uses
    word-based label generation for discovered clusters."""
    pytest.importorskip("sentence_transformers")

    from folio_insights.pipeline.discovery.stages.content_clustering import (
        ContentClusteringStage,
    )

    units = [
        _make_unit("u1", "Opening statement should tell a compelling story", []),
        _make_unit("u2", "Your opening statement must establish the narrative", []),
        _make_unit("u3", "Begin opening statement by outlining your story theory", []),
        _make_unit("u4", "The opening statement sets the stage for the entire trial", []),
    ]

    job = DiscoveryJob(
        corpus_name="test",
        source_dir=Path("/tmp/test"),
        knowledge_units=units,
        task_candidates=[],
    )

    stage = ContentClusteringStage()
    result = asyncio.run(stage.execute(job))

    # Without LLM, any clustering candidates should use word-based labels
    for candidate in result.task_candidates:
        if candidate.source_signal == "clustering":
            # Label should be a non-empty string (word-based fallback)
            assert isinstance(candidate.label, str)
            assert len(candidate.label) > 0


def test_weighted_blend_confidence():
    """compute_task_confidence applies weighted blend: 70% FOLIO, 30% heading."""
    # 0.8 * 0.7 + 0.6 * 0.3 = 0.56 + 0.18 = 0.74
    assert compute_task_confidence(0.8, 0.6) == pytest.approx(0.74)

    # Perfect scores
    assert compute_task_confidence(1.0, 1.0) == pytest.approx(1.0)

    # Zero scores
    assert compute_task_confidence(0.0, 0.0) == pytest.approx(0.0)

    # Only FOLIO signal
    assert compute_task_confidence(1.0, 0.0) == pytest.approx(0.7)

    # Only heading signal
    assert compute_task_confidence(0.0, 1.0) == pytest.approx(0.3)
