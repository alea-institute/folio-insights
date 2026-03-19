"""Stage 1: Heading Analysis -- extract task candidates from heading hierarchy.

Groups knowledge units by their source_section (heading breadcrumb path)
and creates TaskCandidates for each heading path with sufficient units.
Confidence is weighted by heading depth following HeadingContextExtractor's
proximity weights: top-level=1.0, sub-heading=0.7, deep=0.4.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from folio_insights.models.task import TaskCandidate
from folio_insights.pipeline.discovery.stages.base import DiscoveryStage, DiscoveryJob

logger = logging.getLogger(__name__)

# Same proximity weights as HeadingContextExtractor
_DEPTH_CONFIDENCE = [1.0, 0.7, 0.4]

# Minimum number of knowledge units under a heading to form a task candidate
_MIN_UNITS_PER_HEADING = 2


class HeadingAnalysisStage(DiscoveryStage):
    """Extract task candidates from document heading hierarchy.

    Groups knowledge units by source_section and creates TaskCandidates
    for heading paths with at least 2 units.
    """

    @property
    def name(self) -> str:
        return "heading_analysis"

    async def execute(self, job: DiscoveryJob) -> DiscoveryJob:
        """Group units by heading path and create task candidates."""
        # Group units by their heading path (tuple for hashability)
        heading_groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
        source_files: dict[tuple[str, ...], str] = {}

        for unit in job.knowledge_units:
            if not unit.source_section:
                continue
            key = tuple(unit.source_section)
            heading_groups[key].append(unit.id)
            if key not in source_files:
                source_files[key] = unit.source_file

        # Create candidates for heading paths with enough units
        candidates: list[TaskCandidate] = []
        for heading_path, unit_ids in heading_groups.items():
            if len(unit_ids) < _MIN_UNITS_PER_HEADING:
                continue

            # Determine confidence based on heading depth
            depth = len(heading_path) - 1  # 0-indexed depth
            confidence_idx = min(depth, len(_DEPTH_CONFIDENCE) - 1)
            confidence = _DEPTH_CONFIDENCE[confidence_idx]

            candidate = TaskCandidate(
                label=heading_path[-1],  # deepest heading
                source_signal="heading",
                confidence=confidence,
                heading_path=list(heading_path),
                knowledge_unit_ids=unit_ids,
                source_file=source_files.get(heading_path, ""),
            )
            candidates.append(candidate)

        job.task_candidates.extend(candidates)

        logger.info(
            "Heading analysis: %d heading paths -> %d task candidates "
            "(filtered %d paths with < %d units)",
            len(heading_groups),
            len(candidates),
            len(heading_groups) - len(candidates),
            _MIN_UNITS_PER_HEADING,
        )

        return job
