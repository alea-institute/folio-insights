"""Knowledge classifier pipeline stage: type classification and novelty scoring.

Classifies each KnowledgeUnit into one of five types (advice, principle,
citation, procedural_rule, pitfall) with confidence score, and assigns
a novelty/surprise score (0.0 = obvious, 1.0 = highly counterintuitive).

Also runs eyecite citation detection: if citations are found in the text,
the unit is classified as CITATION regardless of LLM output.
"""

from __future__ import annotations

import asyncio
import logging

from folio_insights.llm.schemas import ClassificationOutput, NoveltyOutput
from folio_insights.llm.templates import CLASSIFY, NOVELTY
from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit
from folio_insights.pipeline.stages.base import (
    InsightsJob,
    InsightsPipelineStage,
    LLMFailureTracker,
    record_lineage,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 15

# Valid type mappings from LLM output
_TYPE_MAP = {
    "advice": KnowledgeType.ADVICE,
    "principle": KnowledgeType.PRINCIPLE,
    "citation": KnowledgeType.CITATION,
    "procedural_rule": KnowledgeType.RULE,
    "pitfall": KnowledgeType.PITFALL,
}


# Validated output models for the two LLM calls (defined with the template registry).
ClassificationResult = ClassificationOutput
NoveltyResult = NoveltyOutput


class KnowledgeClassifierStage(InsightsPipelineStage):
    """Classify knowledge units by type and score novelty.

    Uses medium-model LLM for both classification and novelty scoring.
    Also runs eyecite for citation detection: if a citation is found,
    the unit is classified as CITATION regardless of LLM output.
    """

    @property
    def name(self) -> str:
        return "knowledge_classifier"

    async def execute(self, job: InsightsJob) -> InsightsJob:
        """Classify and score all units in the job."""
        if not job.units:
            logger.info("No units to classify")
            return job

        classify_tracker = LLMFailureTracker("knowledge_classifier", "classify")
        novelty_tracker = LLMFailureTracker("knowledge_classifier", "novelty")

        # Process in batches
        for batch_start in range(0, len(job.units), _BATCH_SIZE):
            batch = job.units[batch_start : batch_start + _BATCH_SIZE]

            # Run classification and novelty scoring in parallel
            classify_tasks = [self._classify_unit(unit, classify_tracker) for unit in batch]
            novelty_tasks = [self._score_novelty(unit, novelty_tracker) for unit in batch]

            await asyncio.gather(
                *classify_tasks, *novelty_tasks, return_exceptions=True
            )
        classify_tracker.check(job)
        novelty_tracker.check(job)

        # Post-processing: citation detection override
        await self._detect_citations(job.units)

        classified = {t: 0 for t in KnowledgeType}
        for u in job.units:
            classified[u.unit_type] = classified.get(u.unit_type, 0) + 1

        logger.info(
            "Classified %d units: %s",
            len(job.units),
            {t.value: c for t, c in classified.items()},
        )
        return job

    async def _classify_unit(
        self, unit: KnowledgeUnit, tracker: LLMFailureTracker | None = None
    ) -> None:
        """Classify a single unit's type via LLM."""
        section_context = " > ".join(unit.source_section) if unit.source_section else "N/A"

        prompt = CLASSIFY.render(text=unit.text, section_path=section_context)

        if tracker is not None:
            tracker.attempt()
        try:
            from folio_insights.services.bridge.llm_bridge import LLMBridge

            llm_bridge = LLMBridge()
            llm_provider = llm_bridge.get_llm_for_task("classifier")

            result = await llm_provider.structured(
                prompt, schema=ClassificationOutput, template=CLASSIFY, temperature=0
            )

            unit_type_str = result.get("unit_type", "advice").lower().strip()
            confidence = result.get("confidence", 0.5)

            unit.unit_type = _TYPE_MAP.get(unit_type_str, KnowledgeType.ADVICE)
            unit.confidence = max(0.0, min(1.0, confidence))

            record_lineage(
                unit,
                stage="knowledge_classifier",
                action="classify",
                detail=f"type={unit.unit_type.value}, confidence={unit.confidence:.2f}",
                confidence=unit.confidence,
                template=CLASSIFY,
            )

        except Exception as exc:
            if tracker is not None:
                tracker.failure(unit.id, exc)
            logger.warning(
                "Classification failed for unit %s; keeping default ADVICE",
                unit.id,
                exc_info=True,
            )

    async def _score_novelty(
        self, unit: KnowledgeUnit, tracker: LLMFailureTracker | None = None
    ) -> None:
        """Score novelty/surprise for a single unit via LLM."""
        section_context = " > ".join(unit.source_section) if unit.source_section else "N/A"

        prompt = NOVELTY.render(text=unit.text, section_path=section_context)

        if tracker is not None:
            tracker.attempt()
        try:
            from folio_insights.services.bridge.llm_bridge import LLMBridge

            llm_bridge = LLMBridge()
            llm_provider = llm_bridge.get_llm_for_task("novelty")

            result = await llm_provider.structured(
                prompt, schema=NoveltyOutput, template=NOVELTY, temperature=0
            )

            score = result.get("score", 0.5)
            unit.surprise_score = max(0.0, min(1.0, score))

            record_lineage(
                unit,
                stage="knowledge_classifier",
                action="novelty_score",
                detail=f"novelty={unit.surprise_score:.2f}",
                confidence=unit.surprise_score,
                template=NOVELTY,
            )

        except Exception as exc:
            if tracker is not None:
                tracker.failure(unit.id, exc)
            logger.warning(
                "Novelty scoring failed for unit %s; keeping default 0.0",
                unit.id,
                exc_info=True,
            )

    async def _detect_citations(self, units: list[KnowledgeUnit]) -> None:
        """Run eyecite citation detection; override type to CITATION if found."""
        try:
            from folio_insights.services.bridge.folio_bridge import (
                get_citation_extractor,
            )

            CitationExtractorClass = get_citation_extractor()
            extractor = CitationExtractorClass()

            for unit in units:
                citations = await extractor.extract(unit.text)
                if citations:
                    unit.unit_type = KnowledgeType.CITATION
                    record_lineage(
                        unit,
                        stage="knowledge_classifier",
                        action="citation_override",
                        detail=f"eyecite found {len(citations)} citation(s)",
                    )

        except Exception:
            logger.debug(
                "eyecite citation detection not available; skipping",
                exc_info=True,
            )
