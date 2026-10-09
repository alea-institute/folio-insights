"""Boundary detection pipeline stage: tiered split of text into knowledge units.

Tier 1: Structural heuristics (headings, bullets, paragraph breaks) ~70-80%
Tier 2: Embedding-based semantic segmentation (topic shifts) ~15-20%
Tier 3: LLM refinement (truly ambiguous multi-idea paragraphs) ~5%

Ambiguous paragraphs are refined concurrently under a bounded semaphore (B7). Tier 3 is opt-in
(``boundary_llm_refine``); by default a deterministic sentence-group split handles a long
paragraph that Tier 2 could not split, and every segment is capped at
``boundary_max_unit_chars``. Non-substantive boundaries (headings, contents entries,
attributions) are dropped before they become units (B6), and every unit carries a verifiable
anchor into the ingested source text (RUB-EXTRACT-05).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re

from folio_insights.config import get_settings
from folio_insights.llm.templates import BOUNDARY, PromptTemplate
from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
from folio_insights.pipeline.stages.base import (
    InsightsJob,
    InsightsPipelineStage,
    record_lineage,
)
from folio_insights.pipeline.stages.structure_parser import StructuredElement
from folio_insights.services.anchoring import resolve_anchor
from folio_insights.services.boundary.structural import Boundary, detect_structural_boundaries
from folio_insights.services.substance import is_structural

logger = logging.getLogger(__name__)

# Threshold for "ambiguous" segments that need Tier 2/3
_AMBIGUOUS_CHAR_THRESHOLD = 500

# Boundary methods produced by an LLM call, and the registered template each call used (KTD2).
# A segment of an LLM-refined boundary that the size cap re-splits keeps the LLM method as its
# prefix ("llm_refined+sentence_group"): its cut points still came from the model.
_LLM_REFINED = "llm_refined"
_LLM_METHOD_TEMPLATES: dict[str, PromptTemplate] = {_LLM_REFINED: BOUNDARY}


def _template_for_method(method: str) -> PromptTemplate | None:
    """The prompt template behind a boundary ``method``, or ``None`` for a deterministic one."""
    return _LLM_METHOD_TEMPLATES.get(method.split("+", 1)[0])


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

        settings = get_settings()
        sem = asyncio.Semaphore(max(1, settings.boundary_tier_concurrency))

        async def _refine(amb: Boundary) -> list[Boundary]:
            async with sem:
                return await self._refine_ambiguous(amb)

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

            # --- Tier 2/3: refine ambiguous paragraphs concurrently (B7) ---
            # Each paragraph is independent work; refining them one after another made the stage
            # wall-clock grow with the number of long paragraphs. gather keeps the input order.
            for group in await asyncio.gather(*(_refine(amb) for amb in ambiguous)):
                final_boundaries.extend(group)

            all_boundaries.extend(final_boundaries)

        # The ingested text of each file is the ground truth for a unit's anchor.
        source_text_by_file = {
            key: (data or {}).get("text", "") or ""
            for key, data in job.metadata.get("ingested", {}).items()
        }

        # Convert boundaries to KnowledgeUnit objects
        units: list[KnowledgeUnit] = []
        skipped_non_substantive = 0
        for b in all_boundaries:
            # Skip heading-only boundaries (they define structure, not knowledge)
            if b.method == "structural_heading":
                continue

            text = b.text.strip()
            if not text or len(text) < 10:
                continue

            # B6: a heading, contents entry or attribution line is not knowledge. Only the
            # shape decides here; short genuine advice stays a unit.
            if is_structural(text):
                skipped_non_substantive += 1
                continue

            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

            source_text = source_text_by_file.get(b.source_file, "")
            anchor = resolve_anchor(text, source_text) if source_text else None
            if anchor is not None:
                span = Span(start=anchor.start, end=anchor.end, source_file=b.source_file)
            else:
                # No ingested text to anchor against: keep the structural offsets, unverified.
                span = Span(start=b.start, end=b.end, source_file=b.source_file)

            unit = KnowledgeUnit(
                text=text,
                original_span=span,
                source_snippet=anchor.snippet if anchor else "",
                anchor_verified=anchor.verified if anchor else False,
                anchor_score=anchor.score if anchor else 0.0,
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
                template=_template_for_method(b.method),
            )
            units.append(unit)

        job.units.extend(units)
        job.metadata.setdefault("boundary_detection", {})[
            "skipped_non_substantive"
        ] = skipped_non_substantive

        logger.info(
            "Boundary detection: %d units from %d files (%d boundaries total, "
            "%d non-substantive boundaries dropped)",
            len(units),
            len(structured_data),
            len(all_boundaries),
            skipped_non_substantive,
        )
        return job

    async def _refine_ambiguous(self, amb: Boundary) -> list[Boundary]:
        """Refine one long paragraph. Never drops content; always returns >= 1 boundary.

        Order: Tier-2 semantic split, then (only with ``boundary_llm_refine``) Tier-3 LLM
        refinement, then a deterministic sentence-group split. Any segment still longer than
        ``boundary_max_unit_chars`` is split into sentence groups too.
        """
        settings = get_settings()
        max_chars = settings.boundary_max_unit_chars

        tier2 = await self._run_tier2(amb)
        if tier2:
            return self._cap_sizes(tier2, max_chars)

        if settings.boundary_llm_refine:
            tier3 = await self._run_tier3(amb)
            if tier3:
                return self._cap_sizes(tier3, max_chars)

        return self._split_sentence_groups(amb, max_chars) or [amb]

    def _split_sentence_groups(self, boundary: Boundary, max_chars: int) -> list[Boundary]:
        """Contiguous groups of whole sentences, each at most ``max_chars`` (a single longer
        sentence stays whole). Returns ``[]`` when there is nothing to split."""
        sentences = [s.strip() for s in _split_into_sentences(boundary.text) if s.strip()]
        if len(sentences) < 2:
            return []
        split_indices: list[int] = []
        current = 0
        for index, sentence in enumerate(sentences):
            added = len(sentence) + (1 if current else 0)
            if current and current + added > max_chars:
                split_indices.append(index)
                current = len(sentence)
            else:
                current += added
        if not split_indices:
            return []
        method = "sentence_group"
        if _template_for_method(boundary.method) is not None:
            method = f"{boundary.method.split('+', 1)[0]}+sentence_group"
        return _indices_to_boundaries(sentences, split_indices, boundary, method=method)

    def _cap_sizes(self, boundaries: list[Boundary], max_chars: int) -> list[Boundary]:
        capped: list[Boundary] = []
        for b in boundaries:
            if len(b.text) > max_chars:
                capped.extend(self._split_sentence_groups(b, max_chars) or [b])
            else:
                capped.append(b)
        return capped

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
    *,
    method: str = "semantic",
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
                method=method,
            )
        )

    return boundaries if len(boundaries) > 1 else []
