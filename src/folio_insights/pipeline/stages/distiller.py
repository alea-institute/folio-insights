"""Distiller pipeline stage: compress knowledge units to core insight.

Preserves tactical nuance while stripping filler, hedging, repetition,
and attribution phrases. Uses LLM (large model) with instructor for
structured output.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

from pydantic import BaseModel, Field

from folio_insights.models.knowledge_unit import KnowledgeUnit
from folio_insights.pipeline.stages.base import (
    InsightsJob,
    InsightsPipelineStage,
    record_lineage,
)
from folio_insights.services.prompts.distillation import DISTILLATION_PROMPT

logger = logging.getLogger(__name__)

# Batch size for LLM calls
_BATCH_SIZE = 15


class DistilledOutput(BaseModel):
    """Structured output from the distillation LLM call."""

    distilled_text: str
    preserved_nuances: list[str] = Field(default_factory=list)


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

        # Process in batches
        for batch_start in range(0, len(job.units), _BATCH_SIZE):
            batch = job.units[batch_start : batch_start + _BATCH_SIZE]
            tasks = [self._distill_unit(unit, llm_bridge) for unit in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("Distilled %d knowledge units", len(job.units))
        return job

    async def _distill_unit(
        self,
        unit: KnowledgeUnit,
        llm_bridge: object,
    ) -> None:
        """Distill a single knowledge unit's text."""
        section_context = " > ".join(unit.source_section) if unit.source_section else "N/A"

        prompt = DISTILLATION_PROMPT.format(
            text=unit.text,
            section_path=section_context,
        )

        try:
            llm_provider = llm_bridge.get_llm_for_task("distiller")  # type: ignore[union-attr]
            result = await llm_provider.structured(
                prompt,
                schema={
                    "type": "object",
                    "properties": {
                        "distilled_text": {"type": "string"},
                        "preserved_nuances": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["distilled_text"],
                },
                temperature=0,
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

        except Exception:
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
