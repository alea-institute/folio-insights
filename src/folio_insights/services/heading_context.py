"""Heading context extractor: fourth FOLIO extraction path.

Uses document structure (headings at all levels) to suggest FOLIO
concept tags, weighted by proximity:
  - Immediate subheading (last in section_path): weight 1.0
  - Parent heading (second-to-last): weight 0.7
  - Chapter title (first in section_path): weight 0.4
"""

from __future__ import annotations

import logging
from typing import Any

from folio_insights.models.knowledge_unit import ConceptTag

logger = logging.getLogger(__name__)

# Proximity weights: index 0 = most specific (last heading),
# index 1 = parent, index 2+ = grandparent/chapter
_PROXIMITY_WEIGHTS = [1.0, 0.7, 0.4]


class HeadingContextExtractor:
    """Extract FOLIO concepts from document heading context.

    The fourth extraction path alongside EntityRuler, LLM, and Semantic.
    """

    def __init__(self, folio_service: Any = None) -> None:
        self._folio_service = folio_service

    async def extract_heading_concepts(
        self,
        section_path: list[str],
        folio_service: Any | None = None,
    ) -> list[ConceptTag]:
        """Extract FOLIO concepts from heading hierarchy.

        Searches each heading level against FOLIO, with confidence
        weighted by proximity to the knowledge unit.

        Args:
            section_path: Heading hierarchy, e.g.
                ["Chapter 8: Expert Witnesses", "Methodology Challenges"]
            folio_service: FolioService instance for label search.

        Returns:
            List of ConceptTags with extraction_path="heading_context".
        """
        svc = folio_service or self._folio_service
        if svc is None or not section_path:
            return []

        tags: list[ConceptTag] = []

        # Process from most specific to least (reverse order)
        reversed_path = list(reversed(section_path))

        for depth, heading_text in enumerate(reversed_path):
            # Clean heading text (strip numbering like "Chapter 8:")
            clean = _clean_heading(heading_text)
            if not clean or len(clean) < 3:
                continue

            # Determine proximity weight
            weight = _PROXIMITY_WEIGHTS[min(depth, len(_PROXIMITY_WEIGHTS) - 1)]

            try:
                results = svc.search_by_label(clean)
            except Exception:
                logger.debug("FOLIO search failed for heading '%s'", clean, exc_info=True)
                continue

            if not results:
                continue

            # Take the top match
            top_match, top_score = results[0]

            if top_score >= 0.7:
                # Strong match: use full proximity weight
                confidence = top_score * weight
            elif top_score >= 0.5:
                # Moderate match: reduce weight further
                confidence = top_score * weight * 0.7
            else:
                # Weak match: skip unless it's the immediate subheading
                if depth == 0 and top_score >= 0.3:
                    confidence = top_score * weight * 0.5
                else:
                    continue

            tag = ConceptTag(
                iri=getattr(top_match, "iri", ""),
                label=getattr(top_match, "preferred_label", clean),
                confidence=round(confidence, 3),
                extraction_path="heading_context",
                branch=getattr(top_match, "branch", ""),
            )
            tags.append(tag)

        return tags


def _clean_heading(heading: str) -> str:
    """Clean heading text for FOLIO search.

    Strips common prefixes like "Chapter 8:", section numbers,
    and trailing punctuation.
    """
    import re

    # Remove "Chapter N:" or "Section N:" prefixes
    cleaned = re.sub(
        r"^(?:Chapter|Section|Part|Appendix)\s+\d+[.:]\s*",
        "",
        heading,
        flags=re.IGNORECASE,
    )
    # Remove leading numbers and dots (e.g., "1.2.3 Title")
    cleaned = re.sub(r"^[\d.]+\s+", "", cleaned)
    return cleaned.strip()
