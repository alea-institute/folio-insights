"""Shared fixtures for folio-insights tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from folio_insights.models.knowledge_unit import (
    ConceptTag,
    KnowledgeType,
    KnowledgeUnit,
    Span,
)


@pytest.fixture
def sample_text_elements() -> list[dict]:
    """Return a list of TextElement-like dicts with various element types."""
    return [
        {
            "text": "Chapter 8: Expert Witnesses",
            "element_type": "heading",
            "section_path": [],
            "page": None,
            "level": 1,
        },
        {
            "text": "Methodology Challenges",
            "element_type": "heading",
            "section_path": ["Chapter 8: Expert Witnesses"],
            "page": None,
            "level": 2,
        },
        {
            "text": "Lock expert into reviewed-document list during deposition.",
            "element_type": "paragraph",
            "section_path": [
                "Chapter 8: Expert Witnesses",
                "Methodology Challenges",
            ],
            "page": None,
            "level": None,
        },
        {
            "text": "Always verify the expert's CV against published records.",
            "element_type": "list_item",
            "section_path": [
                "Chapter 8: Expert Witnesses",
                "Methodology Challenges",
            ],
            "page": None,
            "level": None,
        },
    ]


@pytest.fixture
def sample_knowledge_unit() -> KnowledgeUnit:
    """Return a fully populated KnowledgeUnit instance."""
    return KnowledgeUnit(
        text="Lock expert into reviewed-document list during deposition",
        original_span=Span(start=100, end=162, source_file="chapter8.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="chapter8.md",
        source_section=["Chapter 8: Expert Witnesses", "Methodology Challenges"],
        folio_tags=[
            ConceptTag(
                iri="https://folio.openlegalstandard.org/RCz1SYWoNDDTDvPr0kSJBq",
                label="Cross-Examination of Witness",
                confidence=0.85,
                extraction_path="entity_ruler",
                branch="Litigation",
            )
        ],
        surprise_score=0.7,
        confidence=0.85,
        content_hash="abc123",
    )


@pytest.fixture
def tmp_source_dir(tmp_path: Path) -> Path:
    """Create a temp directory with sample .md and .txt files."""
    md_file = tmp_path / "chapter1.md"
    md_file.write_text(
        "# Introduction\n\n"
        "This is the opening paragraph of the chapter.\n\n"
        "## Key Concepts\n\n"
        "Understanding the basics is essential.\n",
        encoding="utf-8",
    )

    txt_file = tmp_path / "notes.txt"
    txt_file.write_text(
        "Important note about trial preparation.\n"
        "Always review exhibits before presenting.\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def mock_folio_service() -> MagicMock:
    """Provide a mock FolioService with canned search results."""
    mock = MagicMock()
    mock.search_by_label.return_value = [
        (
            MagicMock(
                iri="https://folio.openlegalstandard.org/test123",
                preferred_label="Cross-Examination",
                definition="The questioning of a witness by the opposing party.",
                alternative_labels=["Cross Exam"],
                parent_iris=[],
                branch="Litigation",
            ),
            0.92,
        )
    ]
    mock.get_all_labels.return_value = {"cross-examination": MagicMock()}
    return mock
