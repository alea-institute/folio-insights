"""Similarity queries over prototype clusters — and nothing else (Phase 9 U6, KTD10).

PRD §8 P6 separation invariant: "Subsumption queries go through the reasoner.
Similarity queries go through the prototype cluster. The API must not let the
caller confuse them." This module is the similarity half. It answers how far
apart two framework senses' prototype centroids are, as a ``SimilarityResult``.

It never answers subsumption or disjointness: those are entailment questions,
answered by a ``reason.reasoner.SubsumptionReasoner`` as a ``SubsumptionResult``
(the Rule 1 call lives in ``polysemy.tbox``). The Phase 1 version of this
module held only the Rule 1 disjointness SPARQL, the opposite of its name; that
moved to ``polysemy.tbox``. ``tests/polysemy/test_similarity_subsumption_guard.py``
keeps this module free of SPARQL, OWL axioms and reasoner imports.

A distance is an EVIDENCE score (Pitfall 1), never a polysemy verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from folio_insights.polysemy.prototype_cluster import PrototypeCluster


@dataclass(frozen=True)
class SimilarityResult:
    """Centroid cosine distance between two framework senses of one term.

    ``distance`` is in [0, 2] (1 - cosine similarity of L2-normalized
    centroids); ``similarity`` is ``1 - distance``. Not a subsumption answer
    and not a ``SubsumptionResult`` (KTD10).
    """

    term: str
    framework_a: str
    framework_b: str
    distance: float

    @property
    def similarity(self) -> float:
        return 1.0 - self.distance


def framework_similarity(
    cluster: PrototypeCluster, framework_a: str, framework_b: str
) -> SimilarityResult | None:
    """The similarity of two frameworks' senses in ``cluster`` (None if either
    framework has no centroid in it)."""
    distance = cluster.cross_framework_cosine_distance.get((framework_a, framework_b))
    if distance is None:
        return None
    return SimilarityResult(cluster.term, framework_a, framework_b, distance)


def pairwise_similarities(cluster: PrototypeCluster) -> list[SimilarityResult]:
    """Every unordered framework pair's similarity, sorted by framework pair."""
    return [
        SimilarityResult(cluster.term, a, b, distance)
        for (a, b), distance in sorted(cluster.cross_framework_cosine_distance.items())
        if a < b
    ]


def strongest_divergence(cluster: PrototypeCluster) -> SimilarityResult | None:
    """The least similar framework pair (on a tie, the first in pair order)."""
    pairs = pairwise_similarities(cluster)
    return max(pairs, key=lambda r: r.distance) if pairs else None


__all__ = [
    "SimilarityResult",
    "framework_similarity",
    "pairwise_similarities",
    "strongest_divergence",
]
