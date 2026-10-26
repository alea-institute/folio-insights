"""Deduplicate atomic occurrences, retaining similarity as diagnostics.

Snapshot-backed output coalesces only the same source/offset/NFC statement.
Legacy output retains content-hash and embedding removal until atomic extraction
is activated. The highest-confidence exact occurrence survives, with link aliases
resolved within its source snapshot.
"""

from __future__ import annotations

import logging
import unicodedata

import numpy as np

from folio_insights.models.knowledge_unit import KnowledgeUnit, PropositionLink
from folio_insights.pipeline.stages.base import (
    InsightsJob,
    InsightsPipelineStage,
    record_lineage,
)

logger = logging.getLogger(__name__)

_NEAR_DEDUP_THRESHOLD = 0.85


def _document_key(unit: KnowledgeUnit) -> tuple[str, str, str]:
    """Scope local IDs to one source document and snapshot."""
    assert unit.provenance is not None
    return (unit.source_file, unit.provenance.source_snapshot_id,
            unit.provenance.source_sha256)


class DeduplicatorStage(InsightsPipelineStage):
    """Merge exact occurrences; only legacy units permit similarity removal."""

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
        """Coalesce atomic occurrences or legacy hashes, keeping highest confidence."""
        by_identity: dict[tuple, list[KnowledgeUnit]] = {}

        for unit in units:
            if unit.provenance is not None:
                span = unit.original_span
                key = ("atomic-v1", _document_key(unit), span.source_file,
                       span.start, span.end, unicodedata.normalize("NFC", unit.text))
            else:
                key = ("legacy", unit.content_hash or unit.id)
            by_identity.setdefault(key, []).append(unit)

        deduped: list[KnowledgeUnit] = []
        aliases: dict[tuple[tuple[str, str, str], str], str] = {}
        removed_count = 0

        for group in by_identity.values():
            if len(group) == 1:
                deduped.append(group[0])
                continue

            # Sort by confidence descending; keep the best
            group.sort(key=lambda u: u.confidence, reverse=True)
            canonical = group[0]

            for duplicate in group[1:]:
                canonical.cross_references.append(duplicate.id)
                if canonical.provenance is not None:
                    aliases[(_document_key(duplicate), duplicate.id)] = canonical.id
                    # Outbound links on an alias describe the same occurrence too.
                    canonical.links.extend(duplicate.links)
                    for citation in duplicate.unresolved_citations:
                        if citation not in canonical.unresolved_citations:
                            canonical.unresolved_citations.append(citation)
                record_lineage(
                    canonical,
                    stage="deduplicator",
                    action="merge",
                    detail=f"merged_from={duplicate.id}",
                )
                removed_count += 1

            deduped.append(canonical)

        if aliases:
            for unit in deduped:
                if unit.provenance is None:
                    continue
                links: list[PropositionLink] = []
                for link in unit.links:
                    target = aliases.get((_document_key(unit), link.target_id), link.target_id)
                    # Aliases can turn a between-predictions link into a self link.
                    if target == unit.id:
                        record_lineage(unit, stage="deduplicator", action="coalesce_link",
                                       detail=f"{link.relation} to alias={link.target_id}")
                        continue
                    resolved = PropositionLink(relation=link.relation, target_id=target)
                    if resolved not in links:
                        links.append(resolved)
                unit.links = links

        return deduped, removed_count

    def _near_dedup(
        self, units: list[KnowledgeUnit]
    ) -> tuple[list[KnowledgeUnit], int]:
        """Diagnose atomic similarity; remove only legacy near-duplicates.

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
                    if units[i].provenance is not None or units[j].provenance is not None:
                        record_lineage(
                            units[i], stage="deduplicator", action="similar",
                            detail=f"similar_to={units[j].id};cosine={sim_matrix[i, j]:.6f}",
                        )
                        continue
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
