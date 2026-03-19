"""Stage 3: Content Clustering -- discover implicit tasks from unit embeddings.

Clusters knowledge units by embedding similarity using agglomerative
clustering. Creates new TaskCandidates for clusters not already covered
by heading-based candidates. Uses LLM to label discovered implicit tasks.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from folio_insights.models.task import TaskCandidate
from folio_insights.pipeline.discovery.stages.base import DiscoveryStage, DiscoveryJob
from folio_insights.services.task_clustering import cluster_units_for_task_discovery

logger = logging.getLogger(__name__)

# Minimum cluster size to form a task candidate
_MIN_CLUSTER_SIZE = 3

# Overlap threshold: if >70% of cluster units are already covered
# by an existing heading candidate, skip the cluster
_OVERLAP_THRESHOLD = 0.7


class ContentClusteringStage(DiscoveryStage):
    """Discover implicit cross-cutting tasks via content clustering.

    Uses agglomerative clustering of unit embeddings, then LLM
    analysis to label clusters that aren't already covered by
    heading-based candidates.
    """

    def __init__(
        self,
        llm_bridge: Any | None = None,
        distance_threshold: float = 0.5,
    ) -> None:
        self._llm_bridge = llm_bridge
        self._distance_threshold = distance_threshold

    @property
    def name(self) -> str:
        return "content_clustering"

    async def execute(self, job: DiscoveryJob) -> DiscoveryJob:
        """Cluster units and create candidates for uncovered clusters."""
        if len(job.knowledge_units) < 2:
            logger.info("Content clustering: too few units (%d), skipping", len(job.knowledge_units))
            return job

        # Cluster units by embedding similarity
        clusters = cluster_units_for_task_discovery(
            job.knowledge_units,
            distance_threshold=self._distance_threshold,
        )

        # Build set of unit IDs already covered by heading candidates
        covered_unit_ids: set[str] = set()
        for candidate in job.task_candidates:
            if candidate.source_signal == "heading":
                covered_unit_ids.update(candidate.knowledge_unit_ids)

        new_candidates: list[TaskCandidate] = []
        clusters_found = 0
        clusters_skipped = 0

        for cluster_indices in clusters:
            if len(cluster_indices) < _MIN_CLUSTER_SIZE:
                continue

            clusters_found += 1
            cluster_unit_ids = [
                job.knowledge_units[i].id for i in cluster_indices
            ]

            # Check overlap with existing heading candidates
            overlap = len(set(cluster_unit_ids) & covered_unit_ids)
            if overlap / len(cluster_unit_ids) > _OVERLAP_THRESHOLD:
                clusters_skipped += 1
                continue

            # Use LLM to label the implicit task
            cluster_texts = [
                job.knowledge_units[i].text for i in cluster_indices
            ]
            label, is_procedural, confidence = await self._label_cluster(
                cluster_texts
            )

            candidate = TaskCandidate(
                label=label,
                source_signal="clustering",
                confidence=confidence,
                knowledge_unit_ids=cluster_unit_ids,
                is_procedural=is_procedural,
            )
            new_candidates.append(candidate)

        job.task_candidates.extend(new_candidates)

        logger.info(
            "Content clustering: %d clusters found, %d skipped (overlap), "
            "%d new implicit tasks discovered",
            clusters_found,
            clusters_skipped,
            len(new_candidates),
        )

        return job

    async def _label_cluster(
        self, unit_texts: list[str]
    ) -> tuple[str, bool, float]:
        """Use LLM to label a cluster of knowledge units as a task.

        Returns:
            (label, is_procedural, confidence) tuple.
        """
        from folio_insights.services.prompts.task_discovery import (
            TASK_DISCOVERY_PROMPT,
        )

        formatted_texts = "\n".join(
            f"- {text}" for text in unit_texts[:20]  # limit context window
        )
        prompt = TASK_DISCOVERY_PROMPT.format(unit_texts=formatted_texts)

        try:
            llm = self._get_llm()
            if llm is None:
                return self._fallback_label(unit_texts)

            response = await llm.generate(prompt)
            parsed = json.loads(response)

            return (
                parsed.get("task_label", "Unnamed Task"),
                parsed.get("is_procedural", False),
                parsed.get("confidence", 0.5),
            )
        except Exception:
            logger.warning("LLM labeling failed; using fallback", exc_info=True)
            return self._fallback_label(unit_texts)

    def _get_llm(self) -> Any | None:
        """Get LLM for task discovery."""
        if self._llm_bridge is not None:
            return self._llm_bridge

        try:
            from folio_insights.services.bridge.llm_bridge import LLMBridge
            bridge = LLMBridge()
            return bridge.get_llm_for_task("task_discovery")
        except Exception:
            logger.debug("LLMBridge unavailable", exc_info=True)
            return None

    @staticmethod
    def _fallback_label(unit_texts: list[str]) -> tuple[str, bool, float]:
        """Generate a simple fallback label when LLM is unavailable.

        Uses the first few words of the longest unit text as the label.
        """
        if not unit_texts:
            return ("Unnamed Task", False, 0.3)

        longest = max(unit_texts, key=len)
        words = longest.split()[:5]
        label = " ".join(words)
        if len(label) > 60:
            label = label[:57] + "..."

        return (label, False, 0.3)
