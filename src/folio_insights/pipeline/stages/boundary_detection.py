"""Boundary detection pipeline stage: tiered split of text into knowledge units.

Tier 1: Structural heuristics (headings, bullets, paragraph breaks) ~70-80%
Tier 2: Embedding-based semantic segmentation (topic shifts) ~15-20%
Tier 3: LLM refinement (truly ambiguous multi-idea paragraphs) ~5%
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
from folio_insights.pipeline.stages.base import (
    InsightsJob,
    InsightsPipelineStage,
    record_lineage,
)
from folio_insights.pipeline.stages.structure_parser import StructuredElement
from folio_insights.services.boundary.structural import Boundary, detect_structural_boundaries

logger = logging.getLogger(__name__)

# Threshold for "ambiguous" segments that need Tier 2/3
_AMBIGUOUS_CHAR_THRESHOLD = 500


class BoundaryDetectionStage(InsightsPipelineStage):
    """Split structured text into one-idea-per-unit knowledge units.

    Uses a tiered approach to minimize expensive LLM calls:
    1. Structural heuristics (FREE)
    2. Embedding semantic segmentation (cheap CPU)
    3. LLM refinement (expensive, only for ambiguity)
    """

    @property
    def name(self) -> str:
        return "boundary_detection"

    async def execute(self, job: InsightsJob) -> InsightsJob:
        """Run tiered boundary detection on all documents in the job."""
        structured_data = job.metadata.get("structured", {})
        if not structured_data:
            logger.warning("No structured data found; skipping boundary detection")
            return job

        all_boundaries: list[Boundary] = []

        for file_key, elements_raw in structured_data.items():
            # Reconstruct StructuredElement objects from dicts
            elements = [StructuredElement(**e) for e in elements_raw]

            # --- Tier 1: Structural heuristics ---
            tier1 = detect_structural_boundaries(elements, source_file=file_key)

            # Identify ambiguous segments (long text without clear splits)
            final_boundaries: list[Boundary] = []
            ambiguous: list[Boundary] = []

            for b in tier1:
                text_len = b.end - b.start
                if (
                    text_len > _AMBIGUOUS_CHAR_THRESHOLD
                    and b.method == "structural_paragraph"
                ):
                    ambiguous.append(b)
                else:
                    final_boundaries.append(b)

            # --- Tier 2: Semantic segmentation for ambiguous paragraphs ---
            for amb in ambiguous:
                tier2_splits = await self._run_tier2(amb)
                if tier2_splits:
                    final_boundaries.extend(tier2_splits)
                else:
                    # Tier 2 found no splits -- try Tier 3 if still ambiguous
                    tier3_splits = await self._run_tier3(amb)
                    if tier3_splits:
                        final_boundaries.extend(tier3_splits)
                    else:
                        final_boundaries.append(amb)

            all_boundaries.extend(final_boundaries)

        # Convert boundaries to KnowledgeUnit objects
        units: list[KnowledgeUnit] = []
        for b in all_boundaries:
            # Skip heading-only boundaries (they define structure, not knowledge)
            if b.method == "structural_heading":
                continue

            text = b.text.strip()
            if not text or len(text) < 10:
                continue

            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

            unit = KnowledgeUnit(
                text=text,
                original_span=Span(
                    start=b.start,
                    end=b.end,
                    source_file=b.source_file,
                ),
                unit_type=KnowledgeType.ADVICE,  # placeholder, classified in next stage
                source_file=b.source_file,
                source_section=list(b.section_path),
                content_hash=content_hash,
            )

            record_lineage(
                unit,
                stage="boundary_detection",
                action="split",
                detail=f"method={b.method}",
                confidence=b.confidence,
            )
            units.append(unit)

        job.units.extend(units)

        logger.info(
            "Boundary detection: %d units from %d files (%d boundaries total)",
            len(units),
            len(structured_data),
            len(all_boundaries),
        )
        return job

    async def _run_tier2(self, boundary: Boundary) -> list[Boundary] | None:
        """Run Tier 2 semantic segmentation on an ambiguous boundary."""
        try:
            from folio_insights.services.boundary.semantic import (
                detect_semantic_boundaries,
            )
        except ImportError:
            logger.warning("sentence-transformers not available for Tier 2")
            return None

        # Split the boundary text into sentences
        sentences = _split_into_sentences(boundary.text)
        if len(sentences) < 2:
            return None

        try:
            split_indices = detect_semantic_boundaries(sentences)
        except Exception:
            logger.warning("Tier 2 semantic boundary detection failed", exc_info=True)
            return None

        if not split_indices:
            return None

        # Convert sentence-level splits back to character-level boundaries
        return _indices_to_boundaries(
            sentences,
            split_indices,
            boundary,
        )

    async def _run_tier3(self, boundary: Boundary) -> list[Boundary] | None:
        """Run Tier 3 LLM refinement on a truly ambiguous boundary."""
        try:
            from folio_insights.services.boundary.llm_refiner import (
                refine_boundaries_with_llm,
            )
            from folio_insights.services.bridge.llm_bridge import LLMBridge

            llm_bridge = LLMBridge()
            refined = await refine_boundaries_with_llm(
                boundary.text, [boundary], llm_bridge
            )
            if len(refined) > 1:
                return refined
            return None
        except Exception:
            logger.warning("Tier 3 LLM boundary refinement failed", exc_info=True)
            return None


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences using nupunkt via the bridge, or fallback."""
    try:
        from folio_insights.services.bridge.folio_bridge import get_normalizer

        normalizer = get_normalizer()
        return normalizer["split_sentences"](text)
    except Exception:
        # Fallback to simple regex split
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
        return [p for p in parts if p.strip()]


def _indices_to_boundaries(
    sentences: list[str],
    split_indices: list[int],
    parent: Boundary,
) -> list[Boundary]:
    """Convert sentence split indices into Boundary objects.

    Groups sentences between split points into contiguous segments.
    """
    # Build segment groups
    all_splits = [0] + sorted(split_indices) + [len(sentences)]
    segments: list[list[str]] = []
    for i in range(len(all_splits) - 1):
        segment = sentences[all_splits[i] : all_splits[i + 1]]
        if segment:
            segments.append(segment)

    if len(segments) <= 1:
        return []

    boundaries: list[Boundary] = []
    char_offset = 0

    for seg in segments:
        seg_text = " ".join(seg).strip()
        if not seg_text:
            continue

        # Find position in parent text
        seg_start = parent.text.find(seg[0].strip(), char_offset)
        if seg_start == -1:
            seg_start = char_offset

        seg_end = seg_start + len(seg_text)
        char_offset = seg_end

        boundaries.append(
            Boundary(
                start=parent.start + seg_start,
                end=parent.start + seg_end,
                source_file=parent.source_file,
                text=seg_text,
                section_path=parent.section_path,
                confidence=0.75,
                method="semantic",
            )
        )

    return boundaries if len(boundaries) > 1 else []
