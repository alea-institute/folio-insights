"""Deduplicator pipeline stage: exact and near-duplicate detection.

Catches duplicate advice expressed differently across source files
via two methods:
  1. Exact dedup: identical content_hash (SHA-256 of distilled text)
  2. Near dedup: embedding cosine similarity > 0.85 (sentence-transformers)

Canonical unit (highest confidence) is kept; duplicates are linked
via cross_references and removed from the unit list.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from folio_insights.models.knowledge_unit import KnowledgeUnit
from folio_insights.pipeline.stages.base import (
    InsightsJob,
    InsightsPipelineStage,
    record_lineage,
)

logger = logging.getLogger(__name__)

_NEAR_DEDUP_THRESHOLD = 0.85


class DeduplicatorStage(InsightsPipelineStage):
    """Detect and merge duplicate knowledge units.

    Two passes:
      1. Exact dedup by content_hash (free, instant)
      2. Near dedup by embedding cosine similarity > 0.85 (CPU)
    """

    @property
    def name(self) -> str:
        return "deduplicator"

    async def execute(self, job: InsightsJob) -> InsightsJob:
        """Run exact then near deduplication on all units."""
        if len(job.units) < 2:
            return job

        initial_count = len(job.units)

        # Pass 1: Exact dedup
        units, exact_count = self._exact_dedup(job.units)

        # Pass 2: Near dedup
        units, near_count = self._near_dedup(units)

        job.units = units

        logger.info(
            "Deduplication: %d -> %d units (exact=%d, near=%d removed)",
            initial_count,
            len(units),
            exact_count,
            near_count,
        )

        return job

    def _exact_dedup(
        self, units: list[KnowledgeUnit]
    ) -> tuple[list[KnowledgeUnit], int]:
        """Remove units with identical content_hash, keeping highest confidence."""
        by_hash: dict[str, list[KnowledgeUnit]] = {}

        for unit in units:
            key = unit.content_hash or unit.id
            by_hash.setdefault(key, []).append(unit)

        deduped: list[KnowledgeUnit] = []
        removed_count = 0

        for hash_key, group in by_hash.items():
            if len(group) == 1:
                deduped.append(group[0])
                continue

            # Sort by confidence descending; keep the best
            group.sort(key=lambda u: u.confidence, reverse=True)
            canonical = group[0]

            for duplicate in group[1:]:
                canonical.cross_references.append(duplicate.id)
                record_lineage(
                    canonical,
                    stage="deduplicator",
                    action="merge",
                    detail=f"merged_from={duplicate.id}",
                )
                removed_count += 1

            deduped.append(canonical)

        return deduped, removed_count

    def _near_dedup(
        self, units: list[KnowledgeUnit]
    ) -> tuple[list[KnowledgeUnit], int]:
        """Remove near-duplicates via embedding cosine similarity > threshold.

        Uses sentence-transformers (all-MiniLM-L6-v2) to encode unit texts,
        then computes pairwise cosine similarity.
        """
        if len(units) < 2:
            return units, 0

        try:
            embeddings = self._encode_units(units)
        except Exception:
            logger.warning("Near dedup skipped: embedding encoding failed", exc_info=True)
            return units, 0

        if embeddings is None:
            return units, 0

        # Compute pairwise similarities
        # Embeddings are normalized, so dot product = cosine similarity
        sim_matrix = embeddings @ embeddings.T

        # Find pairs above threshold (upper triangle only)
        remove_indices: set[int] = set()
        removed_count = 0

        for i in range(len(units)):
            if i in remove_indices:
                continue
            for j in range(i + 1, len(units)):
                if j in remove_indices:
                    continue
                if sim_matrix[i, j] > _NEAR_DEDUP_THRESHOLD:
                    # Keep higher confidence as canonical
                    if units[i].confidence >= units[j].confidence:
                        canonical_idx, dup_idx = i, j
                    else:
                        canonical_idx, dup_idx = j, i

                    units[canonical_idx].cross_references.append(
                        units[dup_idx].id
                    )
                    record_lineage(
                        units[canonical_idx],
                        stage="deduplicator",
                        action="merge",
                        detail=f"merged_from={units[dup_idx].id}",
                    )
                    remove_indices.add(dup_idx)
                    removed_count += 1

        deduped = [u for i, u in enumerate(units) if i not in remove_indices]
        return deduped, removed_count

    # Design choice: Uses standalone sentence-transformers (all-MiniLM-L6-v2)
    # instead of the folio_bridge embedding service. This is intentional:
    # the deduplicator runs in the extraction pipeline which may execute
    # before folio_bridge is configured. The model is identical to what
    # folio_bridge wraps, loaded as a lazy singleton via _get_model().
    def _encode_units(self, units: list[KnowledgeUnit]) -> np.ndarray | None:
        """Encode unit texts using sentence-transformers."""
        try:
            from folio_insights.services.boundary.semantic import _get_model

            model = _get_model("all-MiniLM-L6-v2")
            texts = [u.text for u in units]
            embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
            return embeddings
        except Exception:
            logger.warning("sentence-transformers encoding failed", exc_info=True)
            return None
