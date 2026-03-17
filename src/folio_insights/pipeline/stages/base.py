"""Base pipeline stage ABC and job model for folio-insights."""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from folio_insights.models.corpus import CorpusDocument
from folio_insights.models.knowledge_unit import KnowledgeUnit, StageEvent


class InsightsJob(BaseModel):
    """Pipeline job carrying state across stages."""

    corpus_name: str
    source_dir: Path
    documents: list[CorpusDocument] = Field(default_factory=list)
    units: list[KnowledgeUnit] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class InsightsPipelineStage(abc.ABC):
    """Abstract base for all folio-insights pipeline stages.

    Mirrors folio-enrich's PipelineStage interface (name property +
    async execute) but uses InsightsJob instead of Job.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @abc.abstractmethod
    async def execute(self, job: InsightsJob) -> InsightsJob:
        """Execute this pipeline stage, mutating the job in place and returning it."""


def record_lineage(
    unit: KnowledgeUnit,
    stage: str,
    action: str,
    detail: str = "",
    confidence: float | None = None,
) -> None:
    """Append a StageEvent to a knowledge unit's lineage trail."""
    unit.lineage.append(
        StageEvent(
            stage=stage,
            action=action,
            detail=detail,
            confidence=confidence,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )
