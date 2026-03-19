"""Stage 2: FOLIO Mapping -- resolve task candidates to FOLIO concepts.

For each TaskCandidate, collects FOLIO tags from associated knowledge units,
finds the most frequent IRI, traverses the FOLIO hierarchy to the deepest
appropriate concept, and recomputes confidence using a weighted blend.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from folio_insights.models.task import TaskCandidate, compute_task_confidence
from folio_insights.pipeline.discovery.stages.base import DiscoveryStage, DiscoveryJob

logger = logging.getLogger(__name__)


class FolioMappingStage(DiscoveryStage):
    """Map task candidates to FOLIO concept IRIs.

    Uses the most frequent FOLIO tag among a candidate's knowledge units,
    traverses the hierarchy to the deepest appropriate concept, and
    recomputes confidence via weighted blend.
    """

    def __init__(self, folio_service: Any | None = None) -> None:
        self._folio_service = folio_service

    @property
    def name(self) -> str:
        return "folio_mapping"

    def _get_folio_service(self) -> Any:
        """Lazy-load FolioService from bridge."""
        if self._folio_service is not None:
            return self._folio_service
        try:
            from folio_insights.services.bridge.folio_bridge import get_folio_service
            self._folio_service = get_folio_service()
        except Exception:
            logger.warning("FolioService unavailable; FOLIO mapping will be skipped")
            self._folio_service = None
        return self._folio_service

    async def execute(self, job: DiscoveryJob) -> DiscoveryJob:
        """Resolve each candidate to a FOLIO concept."""
        # Build unit lookup by ID for fast access
        unit_map = {u.id: u for u in job.knowledge_units}
        folio_service = self._get_folio_service()

        mapped_count = 0
        proposed_count = 0

        for candidate in job.task_candidates:
            # Collect FOLIO tags from associated units
            iri_counter: Counter[str] = Counter()
            iri_labels: dict[str, str] = {}
            tag_confidences: list[float] = []

            for uid in candidate.knowledge_unit_ids:
                unit = unit_map.get(uid)
                if unit is None:
                    continue
                for tag in unit.folio_tags:
                    iri_counter[tag.iri] += 1
                    iri_labels[tag.iri] = tag.label
                    tag_confidences.append(tag.confidence)

            if not iri_counter:
                # No FOLIO tags found -- propose as new sibling
                job.metadata.setdefault("proposed_siblings", []).append(
                    candidate.label
                )
                proposed_count += 1
                continue

            # Use the most frequent IRI
            best_iri, _count = iri_counter.most_common(1)[0]
            best_label = iri_labels.get(best_iri, "")

            # Try to find a deeper concept via FolioService
            if folio_service is not None:
                try:
                    deeper = _find_deepest_concept(
                        folio_service, best_iri, candidate.label
                    )
                    if deeper is not None:
                        best_iri, best_label = deeper
                except Exception:
                    logger.debug(
                        "FOLIO hierarchy traversal failed for %s",
                        best_iri,
                        exc_info=True,
                    )

            candidate.folio_iri = best_iri
            candidate.folio_label = best_label

            # Recompute confidence using weighted blend
            folio_confidence = (
                sum(tag_confidences) / len(tag_confidences)
                if tag_confidences
                else 0.0
            )
            heading_confidence = candidate.confidence
            candidate.confidence = compute_task_confidence(
                folio_confidence, heading_confidence
            )
            mapped_count += 1

        logger.info(
            "FOLIO mapping: %d candidates mapped, %d proposed new concepts",
            mapped_count,
            proposed_count,
        )

        return job


def _find_deepest_concept(
    folio_service: Any, iri: str, label: str
) -> tuple[str, str] | None:
    """Traverse FOLIO hierarchy to find the deepest appropriate concept.

    Per CONTEXT.md: "as deep as possible, but no deeper."
    Searches children of the current concept for a label match,
    recursing into the best match.

    Args:
        folio_service: FolioService instance with search_by_label/get_concept.
        iri: Starting concept IRI.
        label: Task candidate label to match against children.

    Returns:
        (iri, label) of the deepest matching concept, or None if no better match.
    """
    try:
        concept = folio_service.get_concept(iri)
        if concept is None:
            return None

        children = getattr(concept, "children", [])
        if not children:
            return None

        # Search children for a better label match
        results = folio_service.search_by_label(label)
        if not results:
            return None

        # Check if any result is a child (deeper) of the current concept
        child_iris = {getattr(c, "iri", "") for c in children}
        for match, score in results:
            match_iri = getattr(match, "iri", "")
            if match_iri in child_iris and score >= 0.5:
                match_label = getattr(match, "preferred_label", label)
                return (match_iri, match_label)

    except Exception:
        logger.debug("Hierarchy traversal error", exc_info=True)

    return None
