"""Deduplicate atomic occurrences, retaining similarity as diagnostics.

Snapshot-backed output coalesces only the same source/offset/NFC statement.
Legacy output retains content-hash and embedding removal until atomic extraction
is activated. The highest-confidence exact occurrence survives, with link aliases
resolved within its source snapshot.
"""

from __future__ import annotations

import heapq
import json
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
_SIMILARITY_NEIGHBOR_LIMIT = 3


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

        atomic_groups = self._record_atomic_groups(units)

        try:
            embeddings = self._encode_units(units)
        except Exception:
            logger.warning("Near dedup skipped: embedding encoding failed", exc_info=True)
            return units, 0

        if embeddings is None:
            return units, 0

        # Compute pairwise similarities
        # Embeddings are normalized, so dot product = cosine similarity
        # Preserve the legacy matrix path exactly. Atomic/mixed corpora use one
        # O(n) row at a time, plus O(n*d) embeddings and O(n*K) diagnostics.
        # Exact nearest-neighbor comparisons still take O(n²*d) time.
        sim_matrix = None if atomic_groups else embeddings @ embeddings.T

        # Find pairs above threshold (upper triangle only)
        remove_indices: set[int] = set()
        removed_count = 0

        for i in range(len(units)):
            if i in remove_indices or i in atomic_groups:
                continue
            similarities = embeddings[i] @ embeddings.T if sim_matrix is None else sim_matrix[i]
            for j in range(i + 1, len(units)):
                if j in remove_indices or j in atomic_groups:
                    continue
                if similarities[j] > _NEAR_DEDUP_THRESHOLD:
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

        if atomic_groups:
            self._record_atomic_neighbors(units, embeddings, atomic_groups, remove_indices)

        deduped = [u for i, u in enumerate(units) if i not in remove_indices]
        return deduped, removed_count

    def _record_atomic_groups(self, units: list[KnowledgeUnit]) -> dict[int, int]:
        """Summarize identical statements in a snapshot; return each member's group."""
        groups: dict[tuple, list[int]] = {}
        for i, unit in enumerate(units):
            if unit.provenance is not None:
                key = (_document_key(unit), unicodedata.normalize("NFC", unit.text))
                groups.setdefault(key, []).append(i)

        for members in groups.values():
            if len(members) > 1:
                sample = [units[i].id for i in members[:_SIMILARITY_NEIGHBOR_LIMIT]]
                record_lineage(
                    units[members[0]], stage="deduplicator", action="similar_group",
                    detail=f"group_size={len(members)};sample_ids={json.dumps(sample)}",
                )
        return {i: members[0] for members in groups.values() for i in members}

    def _record_atomic_neighbors(
        self, units: list[KnowledgeUnit], embeddings: np.ndarray,
        groups: dict[int, int], removed: set[int],
    ) -> None:
        """Keep K highest-scoring neighbors per atomic unit, with input-order ties.

        Within-group similarities are already represented by one aggregate event.
        Each row uses O(n) similarity storage and an O(K) selection heap; no full
        matrix or list of all qualifying pairs is built for atomic/mixed input.
        """
        for i, group in groups.items():
            similarities = embeddings[i] @ embeddings.T
            candidates = (
                j for j in range(len(units))
                if j not in removed and groups.get(j) != group
                and similarities[j] > _NEAR_DEDUP_THRESHOLD
            )
            neighbors = heapq.nlargest(
                _SIMILARITY_NEIGHBOR_LIMIT, candidates,
                key=lambda j: (similarities[j], -j),
            )
            for j in neighbors:
                record_lineage(
                    units[i], stage="deduplicator", action="similar",
                    detail=f"similar_to={units[j].id};cosine={similarities[j]:.6f}",
                )

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
