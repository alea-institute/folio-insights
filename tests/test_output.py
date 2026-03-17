"""Tests for quality output layer: confidence gating and JSON formatting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from folio_insights.models.corpus import CorpusDocument, CorpusManifest
from folio_insights.models.knowledge_unit import (
    ConceptTag,
    KnowledgeType,
    KnowledgeUnit,
    Span,
)
from folio_insights.quality.confidence_gate import ConfidenceGate
from folio_insights.quality.output_formatter import OutputFormatter


def _make_unit(
    text: str = "Test unit",
    confidence: float = 0.5,
    unit_type: KnowledgeType = KnowledgeType.ADVICE,
    source_file: str = "chapter1.md",
    folio_tags: list[ConceptTag] | None = None,
) -> KnowledgeUnit:
    """Helper to create a KnowledgeUnit with minimal boilerplate."""
    return KnowledgeUnit(
        text=text,
        original_span=Span(start=0, end=len(text), source_file=source_file),
        unit_type=unit_type,
        source_file=source_file,
        source_section=["Chapter 1", "Section A"],
        folio_tags=folio_tags or [],
        confidence=confidence,
        content_hash="test_hash",
    )


def _make_corpus(name: str = "test_corpus", doc_count: int = 2) -> CorpusManifest:
    """Helper to create a CorpusManifest."""
    docs = [
        CorpusDocument(
            file_path=f"file{i}.md",
            content_hash=f"hash{i}",
            format="markdown",
        )
        for i in range(doc_count)
    ]
    return CorpusManifest(
        name=name,
        documents=docs,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


# --- Confidence gating tests ---


class TestConfidenceGating:
    """Test ConfidenceGate categorization and auto-approve logic."""

    def test_confidence_gating(self) -> None:
        """Units are correctly partitioned into high/medium/low bands."""
        gate = ConfidenceGate()

        high_unit = _make_unit(text="High confidence", confidence=0.9)
        medium_unit = _make_unit(text="Medium confidence", confidence=0.6)
        low_unit = _make_unit(text="Low confidence", confidence=0.3)

        gated = gate.gate_units([high_unit, medium_unit, low_unit])

        assert len(gated["high"]) == 1
        assert gated["high"][0].confidence == 0.9
        assert len(gated["medium"]) == 1
        assert gated["medium"][0].confidence == 0.6
        assert len(gated["low"]) == 1
        assert gated["low"][0].confidence == 0.3

    def test_auto_approve_threshold(self) -> None:
        """Auto-approve separates high from medium+low correctly."""
        gate = ConfidenceGate(high_threshold=0.8)

        above = _make_unit(text="Above threshold", confidence=0.85)
        below = _make_unit(text="Below threshold", confidence=0.75)

        approved, needs_review = gate.auto_approve([above, below])

        assert len(approved) == 1
        assert approved[0].confidence == 0.85
        assert len(needs_review) == 1
        assert needs_review[0].confidence == 0.75

    def test_categorize_boundary_values(self) -> None:
        """Exact boundary values are categorized correctly."""
        gate = ConfidenceGate(high_threshold=0.8, medium_threshold=0.5)

        # Exactly at high threshold -> high
        assert gate.categorize(_make_unit(confidence=0.8)) == "high"
        # Exactly at medium threshold -> medium
        assert gate.categorize(_make_unit(confidence=0.5)) == "medium"
        # Just below medium -> low
        assert gate.categorize(_make_unit(confidence=0.49)) == "low"

    def test_custom_thresholds(self) -> None:
        """Custom thresholds are respected."""
        gate = ConfidenceGate(high_threshold=0.9, medium_threshold=0.7)

        assert gate.categorize(_make_unit(confidence=0.85)) == "medium"
        assert gate.categorize(_make_unit(confidence=0.95)) == "high"
        assert gate.categorize(_make_unit(confidence=0.6)) == "low"


# --- Output formatting tests ---


class TestOutputFormatting:
    """Test OutputFormatter JSON generation."""

    def test_human_reviewable(self, tmp_path: Path) -> None:
        """Output JSON is human-readable with indentation and labeled fields."""
        formatter = OutputFormatter()
        units = [
            _make_unit(
                text="Expert deposition technique",
                confidence=0.85,
                folio_tags=[
                    ConceptTag(
                        iri="https://folio.openlegalstandard.org/test123",
                        label="Cross-Examination",
                        confidence=0.85,
                        extraction_path="entity_ruler",
                        branch="Litigation",
                    )
                ],
            )
        ]
        corpus = _make_corpus()
        result = formatter.format_units_json(units, corpus)

        # Serialize to JSON string with indent
        json_str = json.dumps(result, indent=2, default=str)

        # Human-readable: has indentation (contains newlines + spaces)
        assert "\n" in json_str
        assert "  " in json_str

        # Contains expected labeled fields
        assert "units" in result
        assert isinstance(result["units"], list)
        assert len(result["units"]) == 1

        unit_data = result["units"][0]
        assert "text" in unit_data
        assert "folio_tags" in unit_data
        assert unit_data["text"] == "Expert deposition technique"

    def test_machine_parseable(self) -> None:
        """Output JSON round-trips through json.loads and supports field access."""
        formatter = OutputFormatter()
        units = [
            _make_unit(
                text="Trial preparation tip",
                confidence=0.9,
                folio_tags=[
                    ConceptTag(
                        iri="https://folio.openlegalstandard.org/abc456",
                        label="Trial Preparation",
                        confidence=0.88,
                        extraction_path="semantic",
                        branch="Litigation",
                    )
                ],
            )
        ]
        corpus = _make_corpus()
        result = formatter.format_units_json(units, corpus)

        # Serialize and re-parse
        json_str = json.dumps(result, indent=2, default=str)
        parsed = json.loads(json_str)

        # Can iterate units and access nested tags
        assert len(parsed["units"]) == 1
        unit = parsed["units"][0]
        assert "folio_tags" in unit
        tags = unit["folio_tags"]
        assert len(tags) == 1
        assert "iri" in tags[0]
        assert tags[0]["iri"] == "https://folio.openlegalstandard.org/abc456"

    def test_no_original_text_in_output(self) -> None:
        """Output JSON units do NOT contain 'original_text' -- copyright safety.

        Source references should only contain: source_file, source_section,
        original_span (start/end). No original text copied.
        """
        formatter = OutputFormatter()
        units = [_make_unit(text="Some advice")]
        corpus = _make_corpus()
        result = formatter.format_units_json(units, corpus)

        json_str = json.dumps(result, default=str)

        # The KnowledgeUnit model does not have an 'original_text' field
        for unit_data in result["units"]:
            assert "original_text" not in unit_data

        # Verify original_span has start/end but source references
        # contain only structural references, not copied text
        unit_data = result["units"][0]
        assert "original_span" in unit_data
        assert "start" in unit_data["original_span"]
        assert "end" in unit_data["original_span"]
        assert "source_file" in unit_data
        assert "source_section" in unit_data

    def test_summary_stats(self) -> None:
        """Output JSON contains by_confidence and by_type that match actual data."""
        formatter = OutputFormatter()
        units = [
            _make_unit(text="Advice 1", confidence=0.9, unit_type=KnowledgeType.ADVICE),
            _make_unit(text="Advice 2", confidence=0.6, unit_type=KnowledgeType.ADVICE),
            _make_unit(text="Pitfall 1", confidence=0.3, unit_type=KnowledgeType.PITFALL),
            _make_unit(text="Principle 1", confidence=0.85, unit_type=KnowledgeType.PRINCIPLE),
        ]
        corpus = _make_corpus()
        result = formatter.format_units_json(units, corpus)

        # by_confidence counts match
        assert result["by_confidence"]["high"] == 2   # 0.9 and 0.85
        assert result["by_confidence"]["medium"] == 1  # 0.6
        assert result["by_confidence"]["low"] == 1     # 0.3

        # by_type counts match
        assert result["by_type"]["advice"] == 2
        assert result["by_type"]["pitfall"] == 1
        assert result["by_type"]["principle"] == 1

        # total_units matches
        assert result["total_units"] == 4

    def test_proposed_classes_report(self) -> None:
        """Proposed classes report lists tags with empty IRIs (no FOLIO match)."""
        formatter = OutputFormatter()

        # Unit with a tag that has an existing IRI
        existing_tag = ConceptTag(
            iri="https://folio.openlegalstandard.org/existing",
            label="Cross-Examination",
            confidence=0.9,
            extraction_path="entity_ruler",
        )
        # Unit with a tag that LACKS an IRI (proposed new class)
        proposed_tag = ConceptTag(
            iri="",
            label="Expert Witness Voir Dire",
            confidence=0.7,
            extraction_path="llm",
        )

        units = [
            _make_unit(text="Unit with existing", folio_tags=[existing_tag], confidence=0.9),
            _make_unit(text="Unit with proposed", folio_tags=[proposed_tag], confidence=0.7),
        ]

        report = formatter.format_proposed_classes_report(units)

        assert report["total_proposed"] == 1
        assert len(report["proposed_classes"]) == 1
        assert report["proposed_classes"][0]["proposed_label"] == "Expert Witness Voir Dire"
        assert report["proposed_classes"][0]["extraction_path"] == "llm"

    def test_write_output_creates_files(self, tmp_path: Path) -> None:
        """write_output creates all three JSON files in the corpus directory."""
        formatter = OutputFormatter()
        corpus_name = "test_corpus"

        units_json = {"corpus": corpus_name, "units": [], "total_units": 0}
        review_json = {"auto_approved": [], "needs_review": [], "spot_check": []}
        proposed_json = {"total_proposed": 0, "proposed_classes": []}

        output_dir = formatter.write_output(
            tmp_path, corpus_name, units_json, review_json, proposed_json
        )

        assert (output_dir / "extraction.json").exists()
        assert (output_dir / "review.json").exists()
        assert (output_dir / "proposed_classes.json").exists()

        # Verify content is valid JSON with indent=2
        with open(output_dir / "extraction.json") as f:
            content = f.read()
            parsed = json.loads(content)
            assert parsed["corpus"] == corpus_name
            # Check indentation (indent=2 means lines start with "  ")
            assert "\n  " in content

    def test_review_report_structure(self) -> None:
        """Review report has correct structure with auto_approved/needs_review/spot_check."""
        formatter = OutputFormatter()
        gate = ConfidenceGate()

        units = [
            _make_unit(text="High conf", confidence=0.9),
            _make_unit(text="Medium conf", confidence=0.6),
            _make_unit(text="Low conf", confidence=0.3),
        ]
        gated = gate.gate_units(units)
        report = formatter.format_review_report(gated)

        assert len(report["auto_approved"]) == 1
        assert report["auto_approved"][0]["text"] == "High conf"

        assert len(report["needs_review"]) == 1
        assert report["needs_review"][0]["text"] == "Low conf"
        assert report["needs_review"][0]["reason"] == "low_confidence"

        assert len(report["spot_check"]) == 1
        assert report["spot_check"][0]["text"] == "Medium conf"
