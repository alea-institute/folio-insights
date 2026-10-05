"""Distiller pipeline stage: compress knowledge units to core insight.

Preserves tactical nuance while stripping filler, hedging, repetition,
and attribution phrases. Calls the LLM port (``folio_insights.llm``) for validated
structured output under the ``distiller.distill`` prompt template.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

from folio_insights.config import get_settings
from folio_insights.llm.schemas import DistilledOutput
from folio_insights.llm.templates import DISTILL
from folio_insights.models.knowledge_unit import KnowledgeUnit
from folio_insights.pipeline.stages.base import (
    InsightsJob,
    InsightsPipelineStage,
    LLMFailureTracker,
    record_lineage,
)
from folio_insights.services.substance import is_substantive

logger = logging.getLogger(__name__)

# Batch size for LLM calls
_BATCH_SIZE = 15


__all__ = ["DistilledOutput", "DistillerStage"]


class DistillerStage(InsightsPipelineStage):
    """Distill knowledge unit text to its core insight.

    Replaces unit.text with compressed distilled form while keeping
    the original text accessible via original_span. Updates
    content_hash with hash of distilled text.
    """

    @property
    def name(self) -> str:
        return "distiller"

    async def execute(self, job: InsightsJob) -> InsightsJob:
        """Distill all knowledge units in the job via LLM.

        Batches units in groups for efficiency. Temperature=0 for
        extraction consistency.
        """
        if not job.units:
            logger.info("No units to distill")
            return job

        from folio_insights.services.bridge.llm_bridge import LLMBridge

        llm_bridge = LLMBridge()
        tracker = LLMFailureTracker("distiller", "distill")

        # Process in batches
        for batch_start in range(0, len(job.units), _BATCH_SIZE):
            batch = job.units[batch_start : batch_start + _BATCH_SIZE]
            tasks = [self._distill_unit(unit, llm_bridge, tracker) for unit in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
        tracker.check(job)

        logger.info("Distilled %d knowledge units", len(job.units))
        return job

    async def _distill_unit(
        self,
        unit: KnowledgeUnit,
        llm_bridge: object,
        tracker: LLMFailureTracker | None = None,
    ) -> None:
        """Distill a single knowledge unit's text."""
        # B6, defence in depth: never hand a heading, contents entry or attribution line to the
        # generative distiller (boundary detection already drops them; this catches any that
        # arrive another way). The unit keeps its text and records why it was not distilled.
        if not is_substantive(unit.text, get_settings().min_substantive_chars):
            record_lineage(
                unit,
                stage="distiller",
                action="distill_skipped",
                detail="non-substantive input (heading/contents/attribution); not distilled",
            )
            return

        section_context = " > ".join(unit.source_section) if unit.source_section else "N/A"

        prompt = DISTILL.render(text=unit.text, section_path=section_context)

        if tracker is not None:
            tracker.attempt()
        try:
            llm_provider = llm_bridge.get_llm_for_task("distiller")  # type: ignore[union-attr]
            result = await llm_provider.structured(
                prompt, schema=DistilledOutput, temperature=0
            )

            distilled_text = result.get("distilled_text", "").strip()
            if distilled_text:
                unit.text = distilled_text
                unit.content_hash = hashlib.sha256(
                    distilled_text.encode("utf-8")
                ).hexdigest()

            record_lineage(
                unit,
                stage="distiller",
                action="distill",
                detail=f"compressed from {len(unit.original_span.source_file)} chars",
            )

        except Exception as exc:
            if tracker is not None:
                tracker.failure(unit.id, exc)
            logger.warning(
                "Distillation failed for unit %s; keeping original text",
                unit.id,
                exc_info=True,
            )
            record_lineage(
                unit,
                stage="distiller",
                action="distill_failed",
                detail="LLM call failed; original text retained",
            )
