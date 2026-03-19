"""Stage 6: Contradiction Detection -- detect semantic opposition within tasks.

For each task, screens all knowledge unit pairs using NLI cross-encoder,
then performs deep LLM analysis on pairs above the contradiction threshold.
Only compares units within the same task (cross-task contradictions are expected).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from folio_insights.models.task import Contradiction
from folio_insights.pipeline.discovery.stages.base import DiscoveryStage, DiscoveryJob
from folio_insights.services.contradiction_detector import ContradictionDetector

if TYPE_CHECKING:
    from folio_insights.models.knowledge_unit import KnowledgeUnit

logger = logging.getLogger(__name__)


class ContradictionDetectionStage(DiscoveryStage):
    """Detect semantic contradictions between knowledge units within each task.

    Uses two-phase approach:
      1. NLI cross-encoder screening (fast, batch)
      2. LLM deep analysis (slow, nuanced) for pairs above threshold

    Only compares units within the same task -- cross-task contradictions
    are expected and not flagged.
    """

    def __init__(
        self,
        contradiction_threshold: float = 0.7,
        detector: ContradictionDetector | None = None,
    ) -> None:
        self._threshold = contradiction_threshold
        self._detector = detector

    @property
    def name(self) -> str:
        return "contradiction_detection"

    def _get_detector(self) -> ContradictionDetector:
        """Lazy-initialize the ContradictionDetector."""
        if self._detector is None:
            self._detector = ContradictionDetector()
        return self._detector

    async def execute(self, job: DiscoveryJob) -> DiscoveryJob:
        """Screen each task's units for contradictions."""
        if job.task_hierarchy is None:
            logger.warning("No task hierarchy for contradiction detection; skipping")
            return job

        detector = self._get_detector()
        unit_map: dict[str, KnowledgeUnit] = {u.id: u for u in job.knowledge_units}
        all_contradictions: list[Contradiction] = []

        for task in job.task_hierarchy.tasks:
            # Get linked knowledge units for this task
            linked_ids = job.task_hierarchy.task_unit_links.get(task.id, [])
            if len(linked_ids) < 2:
                continue  # Need at least 2 units to compare

            task_units = [
                unit_map[uid] for uid in linked_ids if uid in unit_map
            ]
            if len(task_units) < 2:
                continue

            # Phase 1: NLI screening
            try:
                candidates = await detector.screen_pairs(
                    task_units, threshold=self._threshold
                )
            except Exception:
                logger.warning(
                    "NLI screening failed for task '%s'; skipping",
                    task.label,
                    exc_info=True,
                )
                continue

            if not candidates:
                continue

            # Phase 2: Deep LLM analysis for each candidate pair
            for uid_a, uid_b, nli_score in candidates:
                unit_a = unit_map.get(uid_a)
                unit_b = unit_map.get(uid_b)
                if unit_a is None or unit_b is None:
                    continue

                try:
                    contradiction = await detector.deep_analyze(
                        unit_a, unit_b, task_label=task.label
                    )
                except Exception:
                    logger.debug(
                        "Deep analysis failed for %s vs %s",
                        uid_a[:8],
                        uid_b[:8],
                        exc_info=True,
                    )
                    continue

                if contradiction is not None:
                    contradiction.task_id = task.id
                    contradiction.nli_score = nli_score
                    all_contradictions.append(contradiction)
                    task.has_contradictions = True

            if task.has_contradictions:
                logger.info(
                    "Task '%s': %d contradiction candidates, %d confirmed",
                    task.label,
                    len(candidates),
                    sum(
                        1
                        for c in all_contradictions
                        if c.task_id == task.id
                    ),
                )

        # Update job state
        job.contradictions = all_contradictions
        job.task_hierarchy.contradictions = all_contradictions

        logger.info(
            "Contradiction detection: %d tasks screened, %d contradictions found",
            len(job.task_hierarchy.tasks),
            len(all_contradictions),
        )

        return job
