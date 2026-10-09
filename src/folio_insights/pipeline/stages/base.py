"""Base pipeline stage ABC and job model for folio-insights."""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from folio_insights.models.corpus import CorpusDocument
from folio_insights.models.knowledge_unit import KnowledgeUnit, StageEvent

if TYPE_CHECKING:  # the stage base must not import the LLM layer at runtime
    from folio_insights.llm.templates import PromptTemplate


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
    *,
    template: PromptTemplate | None = None,
    template_id: str | None = None,
    template_hash: str | None = None,
) -> None:
    """Append a StageEvent to a knowledge unit's lineage trail.

    An event written as the direct result of an LLM call names the prompt template that call
    used (KTD2), so the unit's prompt hash is derivable from its lineage alone. Pass the
    registered :class:`~folio_insights.llm.templates.PromptTemplate` the call site rendered as
    ``template`` (its id and hash are read from it, never recomputed), or the identity directly
    as ``template_id`` + ``template_hash`` (both or neither). Giving ``template`` together with
    an id or hash that disagrees with it is an error. Deterministic events pass none of them.
    """
    if template is not None:
        if template_id is not None and template_id != template.id:
            raise ValueError(
                f"record_lineage: template_id {template_id!r} disagrees with template "
                f"{template.id!r}"
            )
        if template_hash is not None and template_hash != template.hash:
            raise ValueError(
                f"record_lineage: template_hash disagrees with template {template.id!r}'s hash"
            )
        template_id, template_hash = template.id, template.hash
    unit.lineage.append(
        StageEvent(
            stage=stage,
            action=action,
            detail=detail,
            confidence=confidence,
            timestamp=datetime.now(timezone.utc).isoformat(),
            template_id=template_id,
            template_hash=template_hash,
        )
    )


class StageFailureRatioError(RuntimeError):
    """Too many units failed in one stage path for the run's output to be trusted (KTD7)."""


class LLMFailureTracker:
    """Counts per-unit LLM-path failures in one stage and fails the run above the ratio (KTD7).

    A failed call no longer just leaves the unit unprocessed: it is counted, its unit id is
    recorded in ``job.metadata["llm_failures"]``, and :meth:`check` raises
    :class:`StageFailureRatioError` when more than ``llm_max_unit_failure_ratio`` (default 5%) of
    the attempted units failed. Run-halting errors (missing or rejected key, spend cap, unknown
    model) are not counted here: they stop the whole run through the LLM run context.
    """

    def __init__(self, stage: str, path: str) -> None:
        self.stage = stage
        self.path = path
        self.attempted = 0
        self.failed: list[str] = []

    def attempt(self) -> None:
        self.attempted += 1

    def failure(self, unit_id: str, exc: BaseException) -> None:
        from folio_insights.llm.errors import RunHalted

        if not isinstance(exc, RunHalted):
            self.failed.append(unit_id)

    def check(self, job: InsightsJob) -> None:
        from folio_insights.config import get_settings
        from folio_insights.llm.context import current_context

        current_context().raise_if_halted()  # a halt outranks a ratio failure
        job.metadata.setdefault("llm_failures", {})[f"{self.stage}.{self.path}"] = {
            "attempted": self.attempted,
            "failed": len(self.failed),
            "unit_ids": list(self.failed),
        }
        if not self.failed or self.attempted == 0:
            return
        limit = get_settings().llm_max_unit_failure_ratio
        ratio = len(self.failed) / self.attempted
        if ratio > limit:
            raise StageFailureRatioError(
                f"{self.stage}: the {self.path} LLM call failed on {len(self.failed)} of "
                f"{self.attempted} units ({ratio:.1%} > {limit:.1%} allowed); see "
                f"metadata.llm_failures"
            )
