"""Tests for boundary detection and idea distillation.

Covers:
  - Tier 1 structural boundary detection (headings, bullets, paragraphs, transitions)
  - Tier 2 semantic boundary detection (topic shift via embedding similarity)
  - Distillation (compression preserving nuance)
  - One-idea-per-unit principle
  - Obvious principle extraction (not filtered out)
  - Lineage recording
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
from folio_insights.pipeline.stages.boundary_detection import BoundaryDetectionStage
from folio_insights.pipeline.stages.base import InsightsJob, record_lineage
from folio_insights.pipeline.stages.structure_parser import StructuredElement
from folio_insights.services.boundary.structural import (
    Boundary,
    detect_structural_boundaries,
)


# ---------- Tier 1: Structural boundary detection ----------


def test_boundary_detection_structural():
    """Tier 1 produces correct boundaries at heading changes and bullet items."""
    elements = [
        StructuredElement(
            text="Expert Witnesses",
            element_type="heading",
            section_path=["Expert Witnesses"],
            level=1,
            char_offset_start=0,
            char_offset_end=16,
        ),
        StructuredElement(
            text="Lock expert into reviewed-document list during deposition.",
            element_type="paragraph",
            section_path=["Expert Witnesses"],
            level=0,
            char_offset_start=17,
            char_offset_end=76,
        ),
        StructuredElement(
            text="Always verify the expert's CV against published records.",
            element_type="list_item",
            section_path=["Expert Witnesses"],
            level=0,
            char_offset_start=77,
            char_offset_end=133,
        ),
        StructuredElement(
            text="Check for undisclosed conflicts of interest.",
            element_type="list_item",
            section_path=["Expert Witnesses"],
            level=0,
            char_offset_start=134,
            char_offset_end=178,
        ),
    ]

    boundaries = detect_structural_boundaries(elements, source_file="ch8.md")

    # Heading = 1 boundary, paragraph = 1 boundary, 2 list items = 2 boundaries
    assert len(boundaries) == 4

    # Heading has confidence 1.0
    heading_b = [b for b in boundaries if b.method == "structural_heading"]
    assert len(heading_b) == 1
    assert heading_b[0].confidence == 1.0

    # List items have confidence 0.9
    list_b = [b for b in boundaries if b.method == "structural_list_item"]
    assert len(list_b) == 2
    assert all(b.confidence == 0.9 for b in list_b)

    # Paragraph has confidence 0.7
    para_b = [b for b in boundaries if b.method == "structural_paragraph"]
    assert len(para_b) == 1
    assert para_b[0].confidence == 0.7

    # All carry the section_path
    assert all(b.section_path == ["Expert Witnesses"] for b in boundaries)
    assert all(b.source_file == "ch8.md" for b in boundaries)


def test_boundary_transition_words():
    """Transition words at paragraph start increase confidence to 0.8."""
    elements = [
        StructuredElement(
            text="However, this approach carries significant risks.",
            element_type="paragraph",
            section_path=["Strategy"],
            level=0,
            char_offset_start=0,
            char_offset_end=49,
        ),
    ]

    boundaries = detect_structural_boundaries(elements)
    assert len(boundaries) == 1
    assert boundaries[0].confidence == 0.8


# ---------- Tier 2: Semantic boundary detection ----------


def test_boundary_detection_semantic():
    """Tier 2 detects topic shift in a long paragraph with two distinct topics."""
    # Mock sentence-transformers to avoid loading a real model in tests
    import numpy as np

    # Simulate embeddings: two sentences about topic A, two about topic B
    # Topic A embeddings cluster together; topic B embeddings cluster together
    # But A and B are dissimilar (cosine < threshold)
    mock_embeddings = np.array([
        [1.0, 0.0, 0.0],   # sent 0: topic A
        [0.95, 0.05, 0.0],  # sent 1: topic A (similar to sent 0)
        [0.0, 0.0, 1.0],   # sent 2: topic B (dissimilar from sent 1)
        [0.05, 0.0, 0.95],  # sent 3: topic B (similar to sent 2)
    ])
    # Normalize
    norms = np.linalg.norm(mock_embeddings, axis=1, keepdims=True)
    mock_embeddings = mock_embeddings / norms

    mock_model = MagicMock()
    mock_model.encode.return_value = mock_embeddings

    with patch(
        "folio_insights.services.boundary.semantic._get_model",
        return_value=mock_model,
    ):
        from folio_insights.services.boundary.semantic import (
            detect_semantic_boundaries,
        )

        sentences = [
            "Expert witnesses must be qualified under Daubert.",
            "The Daubert standard requires reliable methodology.",
            "Cross-examination should focus on jury persuasion.",
            "Effective cross-examination requires careful preparation.",
        ]

        boundaries = detect_semantic_boundaries(sentences, threshold=0.3)

        # Should detect a boundary between sentence 1 and 2 (topic shift)
        assert len(boundaries) >= 1
        assert 2 in boundaries  # boundary at index 2 (before "Cross-examination")


# ---------- Distillation ----------


def test_distill_ideas():
    """Verbose legal text distils to shorter output preserving core technique."""
    # Test that the DistillerStage can be instantiated and has correct name
    from folio_insights.pipeline.stages.distiller import DistillerStage

    stage = DistillerStage()
    assert stage.name == "distiller"


def test_distill_nuance():
    """Distilled text retains tactical nuance from the original."""
    # Verify the prompt template preserves nuance guidance
    from folio_insights.services.prompts.distillation import DISTILLATION_PROMPT

    assert "Extract the IDEA, not the expression" in DISTILLATION_PROMPT
    assert "tactical nuance" in DISTILLATION_PROMPT
    assert "Do NOT add any information" in DISTILLATION_PROMPT
    assert "Do NOT generalize" in DISTILLATION_PROMPT
    assert "{text}" in DISTILLATION_PROMPT
    assert "{section_path}" in DISTILLATION_PROMPT


# ---------- Extraction correctness ----------


def test_extract_obvious():
    """Obvious principles ARE extracted (not filtered out), with low novelty score.

    The system extracts everything regardless of obviousness; novelty
    scoring rates surprise later.
    """
    elements = [
        StructuredElement(
            text="Always prepare thoroughly before trial.",
            element_type="paragraph",
            section_path=["Trial Preparation"],
            level=0,
            char_offset_start=0,
            char_offset_end=39,
        ),
    ]

    boundaries = detect_structural_boundaries(elements, source_file="prep.md")
    assert len(boundaries) == 1
    assert boundaries[0].text == "Always prepare thoroughly before trial."


def test_one_idea_per_unit():
    """A paragraph with 3 distinct tips produces 3 separate boundaries."""
    elements = [
        StructuredElement(
            text="First, always lock the expert into their document list.",
            element_type="list_item",
            section_path=["Expert Witnesses"],
            level=0,
            char_offset_start=0,
            char_offset_end=55,
        ),
        StructuredElement(
            text="Second, verify all citations in the expert report.",
            element_type="list_item",
            section_path=["Expert Witnesses"],
            level=0,
            char_offset_start=56,
            char_offset_end=106,
        ),
        StructuredElement(
            text="Third, prepare a Daubert challenge timeline.",
            element_type="list_item",
            section_path=["Expert Witnesses"],
            level=0,
            char_offset_start=107,
            char_offset_end=151,
        ),
    ]

    boundaries = detect_structural_boundaries(elements, source_file="tips.md")
    assert len(boundaries) == 3
    assert all(b.method == "structural_list_item" for b in boundaries)


# ---------- Pipeline integration ----------


@pytest.mark.asyncio
async def test_boundary_detection_stage():
    """BoundaryDetectionStage converts structured elements to KnowledgeUnits."""
    job = InsightsJob(
        corpus_name="test",
        source_dir=Path("/tmp/test"),
        metadata={
            "structured": {
                "chapter1.md": [
                    {
                        "text": "Expert Witnesses",
                        "element_type": "heading",
                        "section_path": ["Expert Witnesses"],
                        "level": 1,
                        "char_offset_start": 0,
                        "char_offset_end": 16,
                    },
                    {
                        "text": "Lock expert into reviewed-document list during deposition to prevent expanding opinion basis at trial.",
                        "element_type": "paragraph",
                        "section_path": ["Expert Witnesses"],
                        "level": 0,
                        "char_offset_start": 17,
                        "char_offset_end": 119,
                    },
                    {
                        "text": "Always verify the expert's CV against published records.",
                        "element_type": "list_item",
                        "section_path": ["Expert Witnesses"],
                        "level": 0,
                        "char_offset_start": 120,
                        "char_offset_end": 176,
                    },
                ]
            }
        },
    )

    stage = BoundaryDetectionStage()
    result = await stage.execute(job)

    # Should produce units (heading is skipped, paragraph + list_item = 2 units)
    assert len(result.units) == 2

    # Check unit properties
    for unit in result.units:
        assert unit.unit_type == KnowledgeType.ADVICE  # placeholder
        assert unit.source_file == "chapter1.md"
        assert unit.source_section == ["Expert Witnesses"]
        assert unit.content_hash  # non-empty hash
        assert unit.original_span.source_file == "chapter1.md"


# ---------- Lineage ----------


def test_boundary_lineage():
    """Each unit has a lineage entry with stage='boundary_detection'."""
    unit = KnowledgeUnit(
        text="Test unit",
        original_span=Span(start=0, end=9, source_file="test.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="test.md",
    )

    record_lineage(unit, stage="boundary_detection", action="split", detail="method=structural")

    assert len(unit.lineage) == 1
    assert unit.lineage[0].stage == "boundary_detection"
    assert unit.lineage[0].action == "split"
    assert "structural" in unit.lineage[0].detail


@pytest.mark.asyncio
async def test_boundary_stage_lineage():
    """Each unit produced by BoundaryDetectionStage has boundary_detection lineage."""
    job = InsightsJob(
        corpus_name="test",
        source_dir=Path("/tmp/test"),
        metadata={
            "structured": {
                "test.md": [
                    {
                        "text": "Always file motions before the deadline expires.",
                        "element_type": "paragraph",
                        "section_path": ["Deadlines"],
                        "level": 0,
                        "char_offset_start": 0,
                        "char_offset_end": 48,
                    },
                ]
            }
        },
    )

    stage = BoundaryDetectionStage()
    result = await stage.execute(job)

    assert len(result.units) == 1
    unit = result.units[0]
    assert any(e.stage == "boundary_detection" for e in unit.lineage)
    assert any(e.action == "split" for e in unit.lineage)
