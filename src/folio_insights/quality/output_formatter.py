"""JSON output formatting for extraction pipeline results.

Produces three output files:
  - extraction.json: full extraction results with units and summary stats
  - review.json: review report with auto-approved / needs-review / spot-check
  - proposed_classes.json: units with FOLIO tags lacking existing IRIs

All output uses indent=2 for human readability and ensure_ascii=False
for proper Unicode support. Source references contain ONLY file path,
section, and character span -- no original text copied (copyright safety).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from folio_insights.models.corpus import CorpusManifest
from folio_insights.models.knowledge_unit import KnowledgeUnit

logger = logging.getLogger(__name__)


class OutputFormatter:
    """Format and write pipeline output as JSON files."""

    def format_units_json(
        self,
        units: list[KnowledgeUnit],
        corpus: CorpusManifest,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the main extraction output dict.

        The output is both human-readable (indented JSON with labels)
        and machine-parseable (structured dict with typed fields).

        Args:
            units: All extracted knowledge units.
            corpus: Corpus manifest with document info.
            metadata: Pipeline metadata (e.g. dedup_count).

        Returns:
            Dict ready for JSON serialization.
        """
        metadata = metadata or {}

        # Count by confidence band
        by_confidence: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for u in units:
            if u.confidence >= 0.8:
                by_confidence["high"] += 1
            elif u.confidence >= 0.5:
                by_confidence["medium"] += 1
            else:
                by_confidence["low"] += 1

        # Count by knowledge type
        by_type: dict[str, int] = {}
        for u in units:
            type_name = u.unit_type.value
            by_type[type_name] = by_type.get(type_name, 0) + 1

        # Collect unique FOLIO concept IRIs used
        folio_iris: set[str] = set()
        for u in units:
            for tag in u.folio_tags:
                if tag.iri:
                    folio_iris.add(tag.iri)

        return {
            "corpus": corpus.name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_units": len(units),
            "by_confidence": by_confidence,
            "by_type": by_type,
            "units": [u.model_dump() for u in units],
            "summary": {
                "documents_processed": len(corpus.documents),
                "folio_concepts_used": len(folio_iris),
                "dedup_count": metadata.get("dedup_count", 0),
            },
        }

    def format_review_report(
        self, gated: dict[str, list[KnowledgeUnit]]
    ) -> dict[str, Any]:
        """Build a review report from confidence-gated units.

        Args:
            gated: Dict with keys "high", "medium", "low", each
                containing a list of KnowledgeUnit objects.

        Returns:
            Dict with auto_approved, needs_review, and spot_check lists.
        """
        return {
            "auto_approved": [
                {
                    "id": u.id,
                    "text": u.text,
                    "confidence": u.confidence,
                }
                for u in gated.get("high", [])
            ],
            "needs_review": [
                {
                    "id": u.id,
                    "text": u.text,
                    "confidence": u.confidence,
                    "reason": "low_confidence",
                }
                for u in gated.get("low", [])
            ],
            "spot_check": [
                {
                    "id": u.id,
                    "text": u.text,
                    "confidence": u.confidence,
                }
                for u in gated.get("medium", [])
            ],
        }

    def format_proposed_classes_report(
        self, units: list[KnowledgeUnit]
    ) -> dict[str, Any]:
        """Build a report of proposed new FOLIO classes.

        A proposed class is any ConceptTag on a unit that lacks an
        existing IRI (empty string), meaning it was identified as a
        concept but has no match in the FOLIO ontology.

        Per CONTEXT.md: "Proposed new FOLIO classes: both flagged in
        main output AND a separate summary report."

        Returns:
            Dict with a list of proposed classes and their source units.
        """
        proposed: list[dict[str, Any]] = []
        seen_labels: set[str] = set()

        for unit in units:
            for tag in unit.folio_tags:
                if not tag.iri and tag.label and tag.label not in seen_labels:
                    seen_labels.add(tag.label)
                    proposed.append({
                        "proposed_label": tag.label,
                        "extraction_path": tag.extraction_path,
                        "confidence": tag.confidence,
                        "source_unit_id": unit.id,
                        "source_text": unit.text,
                        "source_section": unit.source_section,
                    })

        return {
            "total_proposed": len(proposed),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "proposed_classes": proposed,
        }

    def write_output(
        self,
        output_dir: Path,
        corpus_name: str,
        units_json: dict[str, Any],
        review_json: dict[str, Any],
        proposed_classes_json: dict[str, Any],
    ) -> Path:
        """Write all output files to the corpus output directory.

        Creates:
          - {output_dir}/{corpus_name}/extraction.json
          - {output_dir}/{corpus_name}/review.json
          - {output_dir}/{corpus_name}/proposed_classes.json

        All files use indent=2, ensure_ascii=False, default=str.

        Returns:
            Path to the corpus output directory.
        """
        corpus_dir = Path(output_dir) / corpus_name
        corpus_dir.mkdir(parents=True, exist_ok=True)

        files = {
            "extraction.json": units_json,
            "review.json": review_json,
            "proposed_classes.json": proposed_classes_json,
        }

        for filename, data in files.items():
            file_path = corpus_dir / filename
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            logger.info("Wrote %s", file_path)

        return corpus_dir
