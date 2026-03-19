"""Stage 5: Cross-Source Merging -- consolidate duplicate tasks across files.

Two merge strategies:
  1. FOLIO IRI matching (exact): tasks with same folio_iri from different sources
  2. Embedding similarity (fuzzy): task labels with cosine similarity > 0.85

Canonical task (highest aggregate confidence) is kept; merged task's units
are transferred and the merged task is removed.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import numpy as np

from folio_insights.models.task import DiscoveredTask
from folio_insights.pipeline.discovery.stages.base import DiscoveryStage, DiscoveryJob

logger = logging.getLogger(__name__)

# Embedding similarity threshold for fuzzy merging (same as Phase 1 dedup)
_MERGE_SIMILARITY_THRESHOLD = 0.85


class CrossSourceMergingStage(DiscoveryStage):
    """Merge duplicate tasks discovered across different source files.

    Uses FOLIO IRI exact matching and embedding similarity to find
    merge candidates, then consolidates them keeping the highest-confidence
    task as canonical.
    """

    @property
    def name(self) -> str:
        return "cross_source_merging"

    async def execute(self, job: DiscoveryJob) -> DiscoveryJob:
        """Find and merge duplicate tasks across sources."""
        if job.task_hierarchy is None:
            logger.warning("No task hierarchy to merge; skipping")
            return job

        locked_ids: set[str] = set(job.metadata.get("locked_task_ids", []))
        tasks = job.task_hierarchy.tasks
        task_unit_links = job.task_hierarchy.task_unit_links
        unit_task_links = job.task_hierarchy.unit_task_links

        initial_count = len(tasks)

        # Strategy 1: FOLIO IRI matching (exact)
        iri_merges = self._find_iri_merge_candidates(tasks, locked_ids)

        # Strategy 2: Embedding similarity (fuzzy)
        embedding_merges = self._find_embedding_merge_candidates(tasks, locked_ids)

        # Combine merge sets, avoiding duplicates
        all_merges: list[tuple[str, str, str]] = []  # (canonical_id, merged_id, reason)
        merged_ids: set[str] = set()

        for canonical_id, merged_id, reason in iri_merges + embedding_merges:
            if merged_id not in merged_ids and canonical_id not in merged_ids:
                all_merges.append((canonical_id, merged_id, reason))
                merged_ids.add(merged_id)

        # Execute merges
        task_map = {t.id: t for t in tasks}
        for canonical_id, merged_id, reason in all_merges:
            canonical = task_map.get(canonical_id)
            merged = task_map.get(merged_id)
            if canonical is None or merged is None:
                continue

            # Transfer unit links from merged -> canonical
            merged_units = task_unit_links.pop(merged_id, [])
            canonical_units = task_unit_links.setdefault(canonical_id, [])
            for uid in merged_units:
                if uid not in canonical_units:
                    canonical_units.append(uid)
                # Update unit_task_links
                task_ids = unit_task_links.get(uid, [])
                if merged_id in task_ids:
                    task_ids.remove(merged_id)
                if canonical_id not in task_ids:
                    task_ids.append(canonical_id)

            # Merge source signals
            for signal in merged.source_signals:
                if signal not in canonical.source_signals:
                    canonical.source_signals.append(signal)

            logger.info(
                "Merged '%s' into '%s' (reason: %s)",
                merged.label,
                canonical.label,
                reason,
            )

        # Remove merged tasks
        remaining_tasks = [t for t in tasks if t.id not in merged_ids]

        # Recompute unit_type_counts for affected tasks
        self._recompute_unit_type_counts(
            remaining_tasks, task_unit_links, job.knowledge_units
        )

        # Update hierarchy
        job.task_hierarchy.tasks = remaining_tasks
        job.task_hierarchy.task_unit_links = task_unit_links
        job.task_hierarchy.unit_task_links = unit_task_links
        job.discovered_tasks = remaining_tasks

        logger.info(
            "Cross-source merging: %d -> %d tasks (%d merged)",
            initial_count,
            len(remaining_tasks),
            len(all_merges),
        )

        return job

    # ------------------------------------------------------------------
    # Merge strategies
    # ------------------------------------------------------------------

    def _find_iri_merge_candidates(
        self,
        tasks: list[DiscoveredTask],
        locked_ids: set[str],
    ) -> list[tuple[str, str, str]]:
        """Find tasks with the same FOLIO IRI from different source files.

        Returns list of (canonical_id, merged_id, "iri_match") tuples.
        """
        iri_groups: dict[str, list[DiscoveredTask]] = defaultdict(list)
        for task in tasks:
            if task.folio_iri and task.id not in locked_ids:
                iri_groups[task.folio_iri].append(task)

        merges: list[tuple[str, str, str]] = []
        for iri, group in iri_groups.items():
            if len(group) < 2:
                continue

            # Check they come from different source files
            source_files = {
                t.metadata.get("source_file", "") for t in group
            }
            if len(source_files) < 2 and "" not in source_files:
                continue  # Same source file, not a cross-source merge

            # Sort by confidence descending; highest is canonical
            group.sort(key=lambda t: t.confidence, reverse=True)
            canonical = group[0]
            for merged in group[1:]:
                if merged.id not in locked_ids:
                    merges.append((canonical.id, merged.id, "iri_match"))

        return merges

    def _find_embedding_merge_candidates(
        self,
        tasks: list[DiscoveredTask],
        locked_ids: set[str],
    ) -> list[tuple[str, str, str]]:
        """Find tasks with similar labels (cosine > 0.85) across sources.

        Returns list of (canonical_id, merged_id, "embedding_similarity") tuples.
        """
        # Filter to unlocked tasks without IRI matches
        eligible = [t for t in tasks if t.id not in locked_ids]
        if len(eligible) < 2:
            return []

        try:
            from folio_insights.services.task_clustering import _get_model

            model = _get_model()
            labels = [t.label for t in eligible]
            embeddings = model.encode(labels, normalize_embeddings=True)

            # Cosine similarity matrix (normalized -> dot product)
            sim_matrix = embeddings @ embeddings.T

            merges: list[tuple[str, str, str]] = []
            merged_indices: set[int] = set()

            for i in range(len(eligible)):
                if i in merged_indices:
                    continue
                for j in range(i + 1, len(eligible)):
                    if j in merged_indices:
                        continue
                    if sim_matrix[i, j] > _MERGE_SIMILARITY_THRESHOLD:
                        # Check different source files
                        src_i = eligible[i].metadata.get("source_file", "")
                        src_j = eligible[j].metadata.get("source_file", "")
                        if src_i == src_j and src_i != "":
                            continue

                        # Higher confidence is canonical
                        if eligible[i].confidence >= eligible[j].confidence:
                            merges.append(
                                (eligible[i].id, eligible[j].id, "embedding_similarity")
                            )
                            merged_indices.add(j)
                        else:
                            merges.append(
                                (eligible[j].id, eligible[i].id, "embedding_similarity")
                            )
                            merged_indices.add(i)

            return merges

        except Exception:
            logger.warning(
                "Embedding-based merge skipped: model unavailable",
                exc_info=True,
            )
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _recompute_unit_type_counts(
        tasks: list[DiscoveredTask],
        task_unit_links: dict[str, list[str]],
        units: list[Any],
    ) -> None:
        """Recompute unit_type_counts for tasks affected by merging."""
        from collections import Counter

        unit_map = {u.id: u for u in units}
        for task in tasks:
            linked_ids = task_unit_links.get(task.id, [])
            type_counter: Counter[str] = Counter()
            for uid in linked_ids:
                unit = unit_map.get(uid)
                if unit is not None:
                    type_counter[unit.unit_type.value] += 1
            task.unit_type_counts = dict(type_counter)
