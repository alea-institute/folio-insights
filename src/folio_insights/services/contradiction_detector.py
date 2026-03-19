"""Two-phase contradiction detection: NLI cross-encoder screening + LLM deep analysis.

Phase 1 (fast): Cross-encoder NLI model scores all unit pairs within a task.
Phase 2 (deep): LLM analysis for pairs above the contradiction threshold.

Uses cross-encoder/nli-deberta-v3-base (92.38% SNLI accuracy) for screening.
Label mapping: 0=contradiction, 1=entailment, 2=neutral.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from folio_insights.models.task import Contradiction

if TYPE_CHECKING:
    from folio_insights.models.knowledge_unit import KnowledgeUnit

logger = logging.getLogger(__name__)

# Batch size for cross-encoder predictions
_NLI_BATCH_SIZE = 64


class ContradictionDetector:
    """Detect contradictions between knowledge units within the same task.

    Two-phase approach:
      1. Fast NLI screening via cross-encoder (batch predictions)
      2. Deep LLM analysis for nuanced contradiction assessment

    The NLI model is lazy-loaded on first use to avoid heavy imports at startup.
    """

    def __init__(self, llm_bridge: Any | None = None) -> None:
        self._nli_model: Any | None = None
        self._label_mapping = ["contradiction", "entailment", "neutral"]
        self._llm_bridge = llm_bridge

    def _get_nli_model(self) -> Any:
        """Lazy-load the cross-encoder NLI model.

        Uses cross-encoder/nli-deberta-v3-base for high-accuracy
        contradiction/entailment/neutral classification.
        """
        if self._nli_model is None:
            from sentence_transformers import CrossEncoder

            self._nli_model = CrossEncoder("cross-encoder/nli-deberta-v3-base")
            logger.info("Loaded NLI cross-encoder model: nli-deberta-v3-base")
        return self._nli_model

    async def screen_pairs(
        self,
        units: list[KnowledgeUnit],
        threshold: float = 0.7,
    ) -> list[tuple[str, str, float]]:
        """Phase 1: Fast NLI screening of all unit pairs within a task.

        Encodes all pairwise combinations and returns pairs where the
        contradiction score exceeds the threshold.

        Batch predictions in groups of 64 pairs for efficiency.

        Args:
            units: Knowledge units belonging to the same task.
            threshold: Minimum contradiction score for LLM follow-up.

        Returns:
            List of (unit_id_a, unit_id_b, contradiction_score) tuples
            for pairs above the threshold.
        """
        if len(units) < 2:
            return []

        # Build all pairwise text combinations
        pairs: list[tuple[str, str]] = []
        pair_ids: list[tuple[str, str]] = []
        for i, u1 in enumerate(units):
            for u2 in units[i + 1 :]:
                pairs.append((u1.text, u2.text))
                pair_ids.append((u1.id, u2.id))

        if not pairs:
            return []

        model = self._get_nli_model()

        # Batch predict in groups of _NLI_BATCH_SIZE
        all_scores: list[Any] = []
        for batch_start in range(0, len(pairs), _NLI_BATCH_SIZE):
            batch = pairs[batch_start : batch_start + _NLI_BATCH_SIZE]
            batch_scores = model.predict(batch)
            all_scores.extend(batch_scores)

        # Filter for contradiction scores above threshold
        candidates: list[tuple[str, str, float]] = []
        for idx, scores in enumerate(all_scores):
            # scores shape: (3,) -> [contradiction, entailment, neutral]
            contradiction_score = float(scores[0])
            if contradiction_score > threshold:
                uid_a, uid_b = pair_ids[idx]
                candidates.append((uid_a, uid_b, contradiction_score))

        logger.info(
            "NLI screening: %d pairs checked, %d above threshold %.2f",
            len(pairs),
            len(candidates),
            threshold,
        )
        return candidates

    async def deep_analyze(
        self,
        unit_a: KnowledgeUnit,
        unit_b: KnowledgeUnit,
        task_label: str = "",
    ) -> Contradiction | None:
        """Phase 2: LLM analysis for nuanced contradiction assessment.

        Uses structured LLM output (via Instructor or raw JSON parsing)
        to determine contradiction type, explanation, and suggested resolution.

        Args:
            unit_a: First knowledge unit.
            unit_b: Second knowledge unit.
            task_label: Label of the task these units belong to.

        Returns:
            Contradiction object if confirmed, None if false positive.
        """
        from folio_insights.services.prompts.contradiction import (
            CONTRADICTION_ANALYSIS_PROMPT,
        )

        prompt = CONTRADICTION_ANALYSIS_PROMPT.format(
            text_a=unit_a.text,
            text_b=unit_b.text,
            task_label=task_label or "Unknown Task",
        )

        try:
            llm = self._get_llm()
            if llm is None:
                logger.warning(
                    "LLM unavailable for deep contradiction analysis; "
                    "accepting NLI screening result as-is"
                )
                return None

            response = await llm.generate(prompt)
            parsed = json.loads(response)

            if not parsed.get("is_contradiction", False):
                logger.debug(
                    "LLM ruled false positive: %s vs %s",
                    unit_a.id[:8],
                    unit_b.id[:8],
                )
                return None

            return Contradiction(
                id=str(uuid4()),
                task_id="",  # Caller sets this
                unit_id_a=unit_a.id,
                unit_id_b=unit_b.id,
                nli_score=0.0,  # Caller sets this from screening
                contradiction_type=parsed.get("contradiction_type", "full"),
                explanation=parsed.get("explanation", ""),
                context_dependency=parsed.get("context_dependency", ""),
                resolution=parsed.get("suggested_resolution"),
            )

        except Exception:
            logger.warning(
                "Deep contradiction analysis failed for %s vs %s; skipping",
                unit_a.id[:8],
                unit_b.id[:8],
                exc_info=True,
            )
            return None

    def _get_llm(self) -> Any | None:
        """Get LLM provider for contradiction analysis."""
        if self._llm_bridge is not None:
            return self._llm_bridge

        try:
            from folio_insights.services.bridge.llm_bridge import LLMBridge

            bridge = LLMBridge()
            return bridge.get_llm_for_task("contradiction")
        except Exception:
            logger.debug("LLMBridge unavailable for contradiction", exc_info=True)
            return None
