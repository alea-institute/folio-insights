"""Tier 3: LLM-based boundary refinement (expensive, handles ~5%).

Only called for text segments where:
  - Tier 1 produced a single boundary for >500 chars (likely multiple ideas)
  - Tier 2 produced boundaries that split mid-sentence (possibly wrong)
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from folio_insights.services.boundary.structural import Boundary
from folio_insights.services.prompts.boundary import BOUNDARY_REFINEMENT_PROMPT

logger = logging.getLogger(__name__)


class BoundaryRefinement(BaseModel):
    """An LLM-suggested boundary split within a text segment."""

    start_char: int
    end_char: int
    rationale: str = ""


class BoundaryRefinementResponse(BaseModel):
    """Structured response from the LLM boundary refinement call."""

    boundaries: list[BoundaryRefinement] = Field(default_factory=list)


async def refine_boundaries_with_llm(
    text: str,
    candidate_boundaries: list[Boundary],
    llm_bridge: Any,
) -> list[Boundary]:
    """Refine boundaries using LLM for ambiguous text segments.

    Uses instructor for structured output. Temperature=0 for consistency.
    Each refined boundary gets confidence based on LLM agreement with
    structural cues.

    Args:
        text: The ambiguous text segment to refine.
        candidate_boundaries: Existing candidate boundaries from Tier 1/2.
        llm_bridge: LLMBridge instance for accessing the LLM.

    Returns:
        List of refined Boundary objects replacing the ambiguous candidates.
    """
    if not text.strip():
        return candidate_boundaries

    # Get the source_file and section_path from existing candidates
    source_file = candidate_boundaries[0].source_file if candidate_boundaries else ""
    section_path = candidate_boundaries[0].section_path if candidate_boundaries else []
    base_offset = candidate_boundaries[0].start if candidate_boundaries else 0

    prompt = BOUNDARY_REFINEMENT_PROMPT.format(text=text)

    try:
        import instructor

        llm_provider = llm_bridge.get_llm_for_task("boundary")

        # Use instructor for structured output with the LLM
        result = await llm_provider.structured(
            prompt,
            schema={
                "type": "object",
                "properties": {
                    "boundaries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start_char": {"type": "integer"},
                                "end_char": {"type": "integer"},
                                "rationale": {"type": "string"},
                            },
                            "required": ["start_char", "end_char"],
                        },
                    }
                },
            },
            temperature=0,
        )

        refinements = result.get("boundaries", [])

    except Exception:
        logger.warning("LLM boundary refinement failed; keeping original boundaries", exc_info=True)
        return candidate_boundaries

    if not refinements:
        return candidate_boundaries

    refined: list[Boundary] = []
    for ref in refinements:
        start = ref.get("start_char", 0)
        end = ref.get("end_char", len(text))
        rationale = ref.get("rationale", "")

        # Clamp to text bounds
        start = max(0, min(start, len(text)))
        end = max(start, min(end, len(text)))

        segment = text[start:end].strip()
        if not segment:
            continue

        # Confidence: LLM agrees with structural cue = higher confidence
        confidence = 0.75
        for cb in candidate_boundaries:
            # Check if LLM boundary aligns with an existing structural boundary
            if abs((base_offset + start) - cb.start) < 20:
                confidence = 0.85
                break

        refined.append(
            Boundary(
                start=base_offset + start,
                end=base_offset + end,
                source_file=source_file,
                text=segment,
                section_path=section_path,
                confidence=confidence,
                method="llm_refined",
            )
        )

    return refined if refined else candidate_boundaries
