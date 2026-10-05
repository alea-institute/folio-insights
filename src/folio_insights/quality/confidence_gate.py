"""Confidence-based filtering and gating for knowledge units.

Partitions units into confidence bands (high/medium/low) and provides
auto-approve logic: high-confidence units are approved automatically,
while low-confidence units are flagged for manual review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from folio_insights.models.knowledge_unit import KnowledgeUnit

if TYPE_CHECKING:
    from folio_insights.frameworks.detector import FrameworkDetection


@dataclass(frozen=True)
class FrameworkGateResult:
    """Whether a unit's framework detection passes the gate (Phase 9 U2, R5)."""

    passed: bool
    framework_id: str | None
    confidence: float
    reason: str


class ConfidenceGate:
    """Partition knowledge units by confidence band.

    Default thresholds match CONTEXT.md and Settings defaults:
      - high: >= 0.8  (green, quick-approve)
      - medium: 0.5 - 0.8  (yellow, careful review)
      - low: < 0.5  (red, deep review)
    """

    def __init__(
        self,
        high_threshold: float = 0.8,
        medium_threshold: float = 0.5,
        framework_threshold: float = 0.8,
    ) -> None:
        self.high_threshold = high_threshold
        self.medium_threshold = medium_threshold
        self.framework_threshold = framework_threshold

    def check_framework(self, detection: FrameworkDetection) -> FrameworkGateResult:
        """PRD §8 P2: every new extraction records a confident framework or
        fails this gate. There is no default framework to fall back on."""
        if detection.framework_id is None:
            return FrameworkGateResult(
                False, None, detection.confidence, "no framework detected; refusing to default"
            )
        if detection.confidence < self.framework_threshold:
            return FrameworkGateResult(
                False,
                detection.framework_id,
                detection.confidence,
                f"framework confidence {detection.confidence:.2f} is below "
                f"{self.framework_threshold:.2f}",
            )
        return FrameworkGateResult(
            True, detection.framework_id, detection.confidence,
            f"framework detected from {detection.source}",
        )

    def categorize(self, unit: KnowledgeUnit) -> str:
        """Return the confidence band for a single unit.

        Returns:
            "high" if confidence >= high_threshold,
            "medium" if confidence >= medium_threshold,
            "low" otherwise.
        """
        if unit.confidence >= self.high_threshold:
            return "high"
        if unit.confidence >= self.medium_threshold:
            return "medium"
        return "low"

    def gate_units(
        self, units: list[KnowledgeUnit]
    ) -> dict[str, list[KnowledgeUnit]]:
        """Partition units into confidence bands.

        Returns:
            Dict with keys "high", "medium", "low", each containing
            a list of units in that band.
        """
        gated: dict[str, list[KnowledgeUnit]] = {
            "high": [],
            "medium": [],
            "low": [],
        }
        for unit in units:
            band = self.categorize(unit)
            gated[band].append(unit)
        return gated

    def auto_approve(
        self, units: list[KnowledgeUnit]
    ) -> tuple[list[KnowledgeUnit], list[KnowledgeUnit]]:
        """Split units into auto-approved and needs-review.

        Auto-approved: confidence >= high_threshold.
        Needs review: everything else (medium + low).

        Returns:
            Tuple of (auto_approved, needs_review).
        """
        approved: list[KnowledgeUnit] = []
        needs_review: list[KnowledgeUnit] = []

        for unit in units:
            if unit.confidence >= self.high_threshold:
                approved.append(unit)
            else:
                needs_review.append(unit)

        return approved, needs_review
