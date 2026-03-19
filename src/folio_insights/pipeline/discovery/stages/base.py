"""Base ABC for task discovery pipeline stages.

Mirrors InsightsPipelineStage but typed for DiscoveryJob,
keeping the extraction and discovery pipelines independent.
"""

from __future__ import annotations

import abc

from folio_insights.models.task import DiscoveryJob


class DiscoveryStage(abc.ABC):
    """Abstract base for all task discovery pipeline stages.

    Each stage receives a DiscoveryJob, mutates it, and returns it.
    Same contract as InsightsPipelineStage but for the second-pass pipeline.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @abc.abstractmethod
    async def execute(self, job: DiscoveryJob) -> DiscoveryJob:
        """Execute this discovery stage, mutating the job in place and returning it."""
