"""Boundary detection pipeline stage: tiered split of text into knowledge units.

Tier 1: Structural heuristics (headings, bullets, paragraph breaks) ~70-80%
Tier 2: Embedding-based semantic segmentation (topic shifts) ~15-20%
Tier 3: LLM refinement (truly ambiguous multi-idea paragraphs) ~5%
"""

from __future__ import annotations

import asyncio
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
from folio_insights.services.anchoring import resolve_anchor
from folio_insights.services.boundary.structural import Boundary, detect_structural_boundaries
from folio_insights.services.substance import is_substantive

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

            # --- Tier 2/3: refine ambiguous paragraphs CONCURRENTLY ---
            # Each ambiguous paragraph is independent I/O-bound work; running
            # them serially was the >11-min stall (B7). Bounded concurrency
            # keeps wall-clock flat as the document grows without hammering the
            # LLM endpoint.
            from folio_insights.config import get_settings

            concurrency = max(1, get_settings().boundary_tier_concurrency)
            sem = asyncio.Semaphore(concurrency)

            async def _refine(amb: Boundary) -> list[Boundary]:
                async with sem:
                    return await self._refine_ambiguous(amb)

            refined_groups = await asyncio.gather(
                *(_refine(amb) for amb in ambiguous)
            )
            for group in refined_groups:
                final_boundaries.extend(group)

            all_boundaries.extend(final_boundaries)

        # Canonical per-file source text (what the pipeline actually ingested);
        # boundary text is a verbatim substring of this, so it is the ground truth
        # for resolving a verifiable anchor (RUB-EXTRACT-05, HYBRID-STRICT).
        ingested = job.metadata.get("ingested", {})
        source_text_by_file = {
            key: data.get("text", "") for key, data in ingested.items()
        }

        # Substance floor for unit-ization (B6). Below this, a boundary is a
        # heading/TOC/attribution line, not knowledge — dropping it here is the
        # primary fix that stops the distiller inventing authority to fill the
        # void (docs/solutions/heading-as-unit-fabrication.md).
        from folio_insights.config import get_settings

        min_chars = get_settings().min_substantive_chars

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

            # B6: drop heading/TOC/attribution boundaries at the source.
            if not is_substantive(text, min_chars):
                skipped_non_substantive += 1
                continue

            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

            # Resolve a real, verifiable anchor against the ingested source text.
            # Store the located char-span, the exact matched snippet, and the
            # rapidfuzz score so the judge can verify provenance deterministically
            # instead of trusting synthetic running offsets.
            src_text = source_text_by_file.get(b.source_file, "")
            anchor = resolve_anchor(text, src_text) if src_text else None
            if anchor is not None:
                span = Span(
                    start=anchor.start,
                    end=anchor.end,
                    source_file=b.source_file,
                )
                snippet = anchor.snippet
                anchor_verified = anchor.verified
                anchor_score = anchor.score
            else:
                # No source text available (e.g. bridge-only ingest without text);
                # keep the structural offsets but flag the anchor unverified.
                span = Span(start=b.start, end=b.end, source_file=b.source_file)
                snippet = ""
                anchor_verified = False
                anchor_score = 0.0

            unit = KnowledgeUnit(
                text=text,
                original_span=span,
                source_snippet=snippet,
                anchor_verified=anchor_verified,
                anchor_score=anchor_score,
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

        job.metadata.setdefault("boundary_detection", {})
        job.metadata["boundary_detection"]["skipped_non_substantive"] = (
            skipped_non_substantive
        )

        logger.info(
            "Boundary detection: %d units from %d files (%d boundaries total, "
            "%d non-substantive heading/TOC boundaries dropped)",
            len(units),
            len(structured_data),
            len(all_boundaries),
            skipped_non_substantive,
        )
        return job

    async def _refine_ambiguous(self, amb: Boundary) -> list[Boundary]:
        """Refine one ambiguous (>500-char) paragraph into finer boundaries.

        Order: Tier-2 semantic split (cheap CPU) → deterministic sentence-group
        split as the default fallback → optional Tier-3 LLM refinement (only
        when ``boundary_llm_refine`` is set). Always returns a non-empty list
        covering the paragraph; no content is dropped. Any resulting segment
        that is still larger than ``boundary_max_unit_chars`` is further split
        deterministically so no giant single unit survives.
        """
        from folio_insights.config import get_settings

        settings = get_settings()
        max_chars = settings.boundary_max_unit_chars

        # Tier 2: embedding-based topic-shift split (cheap, deterministic-ish).
        tier2_splits = await self._run_tier2(amb)
        if tier2_splits:
            return self._cap_sizes(tier2_splits, max_chars)

        # Tier 3 (optional, off by default): LLM refinement. Bounded by the
        # caller's concurrency semaphore. Flaky/expensive — opt-in only.
        if settings.boundary_llm_refine:
            tier3_splits = await self._run_tier3(amb)
            if tier3_splits:
                return self._cap_sizes(tier3_splits, max_chars)

        # Deterministic fallback: split the coherent large paragraph into
        # contiguous sentence groups <= max_chars. No LLM, no network, no
        # content dropped — replaces the serial per-paragraph LLM call that
        # caused the B7 stall.
        det = self._split_sentence_groups(amb, max_chars)
        return det if det else [amb]

    def _split_sentence_groups(
        self, boundary: Boundary, max_chars: int
    ) -> list[Boundary]:
        """Split a boundary into contiguous sentence groups <= ``max_chars``.

        Deterministic and content-preserving: groups whole sentences until the
        next would exceed ``max_chars``, then starts a new unit. Char spans are
        located back into the parent text.
        """
        sentences = _split_into_sentences(boundary.text)
        if len(sentences) < 2:
            return []

        groups: list[list[str]] = []
        current: list[str] = []
        current_len = 0
        for sent in sentences:
            s = sent.strip()
            if not s:
                continue
            if current and current_len + len(s) + 1 > max_chars:
                groups.append(current)
                current = []
                current_len = 0
            current.append(s)
            current_len += len(s) + 1
        if current:
            groups.append(current)

        if len(groups) <= 1:
            return []

        split_indices: list[int] = []
        idx = 0
        for g in groups[:-1]:
            idx += len(g)
            split_indices.append(idx)
        return _indices_to_boundaries(
            [s.strip() for s in sentences if s.strip()], split_indices, boundary
        )

    def _cap_sizes(
        self, boundaries: list[Boundary], max_chars: int
    ) -> list[Boundary]:
        """Ensure no boundary exceeds ``max_chars`` by sentence-group splitting."""
        capped: list[Boundary] = []
        for b in boundaries:
            if (b.end - b.start) > max_chars and len(b.text) > max_chars:
                sub = self._split_sentence_groups(b, max_chars)
                capped.extend(sub if sub else [b])
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
