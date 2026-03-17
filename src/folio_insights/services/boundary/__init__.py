"""Tiered boundary detection services for folio-insights.

Three tiers minimize LLM cost:
  - Tier 1 (structural): headings, bullets, paragraph breaks (~70-80%)
  - Tier 2 (semantic): embedding cosine similarity drops (~15-20%)
  - Tier 3 (LLM): instructor-guided refinement for ambiguity (~5%)
"""

from folio_insights.services.boundary.structural import (
    Boundary,
    detect_structural_boundaries,
)

__all__ = ["Boundary", "detect_structural_boundaries"]
