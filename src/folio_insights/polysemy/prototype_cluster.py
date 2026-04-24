"""Phase 1 prototype cluster — per-framework centroid embeddings over axiom_summary.

Reuses services/boundary/semantic.py::_get_model lazy singleton (assumption A8
from 01-CONTEXT: no new embedding-model load beyond the one already warm in
Phase 0.1 services/boundary/semantic.py).

Per PITFALLS Pitfall 1: embeddings are computed over axiom_summary (hand-curated
ground-truth axiom), NOT over extracted_text (which would reproduce the
framework-conflicting-context footgun). The per-framework centroid is an
EVIDENCE score surfaced on the verdict — never the final polysemy signal.
Rule 1 (owl:disjointWith SPARQL) is the authoritative axiom-conflict check;
see similarity_query.py and detector.py Rule 1.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from folio_insights.polysemy.fixture_loader import ShardFixture


@dataclass
class PrototypeCluster:
    """Per-term cluster of framework-scoped shards + centroid embeddings.

    Fields:
      cluster_id:   fi:PrototypeCluster_<hex8>   (sha256[:8] of term|sorted_frameworks)
      term:         the term-of-art under consideration (e.g., "consideration")
      shards_by_framework: {framework_label: [ShardFixture, ...]}
      centroids:    {framework_label: L2-normalized 384-D mean-pool embedding}
      cross_framework_cosine_distance: {(fw_a, fw_b): distance}  symmetric,
          both directions stored for cheap lookup (1 - dot since centroids
          are L2-normalized).
    """

    cluster_id: str  # fi:PrototypeCluster_<hex8>
    term: str
    shards_by_framework: dict[str, list["ShardFixture"]]
    centroids: dict[str, np.ndarray]
    cross_framework_cosine_distance: dict[tuple[str, str], float] = field(
        default_factory=dict,
    )


def _mint_cluster_id(term: str, frameworks: list[str]) -> str:
    """Deterministic fi:PrototypeCluster_<hex8> IRI from term + sorted frameworks.

    Sorted so that cluster_id is invariant to iteration order over
    shards_by_framework (dicts are insertion-ordered in CPython 3.7+; we
    normalize explicitly to be defensive).
    """
    key = "|".join([term] + sorted(frameworks)).encode("utf-8")
    return "fi:PrototypeCluster_" + hashlib.sha256(key).hexdigest()[:8]


def compute_cluster_centroids(
    shards_by_framework: dict[str, list["ShardFixture"]],
) -> dict[str, np.ndarray]:
    """Compute per-framework centroid of axiom_summary embeddings.

    Uses the services.boundary.semantic._get_model lazy singleton — inherits
    Phase 0.1 CPU-only sentence-transformers model load. Embeddings are
    L2-normalized so cosine distance reduces to 1 - dot_product.

    Empty frameworks (shard list []) are silently skipped — centroid dict
    will not contain a key for them. Callers should sanity-check keys before
    indexing.

    Returns: {framework_label: mean-pool centroid (np.ndarray, shape (384,))}.
    """
    # Lazy-imported inside function to match the project's established
    # lazy-singleton discipline (assumption A8 from 01-CONTEXT).
    from folio_insights.services.boundary.semantic import _get_model

    model = _get_model("all-MiniLM-L6-v2")
    centroids: dict[str, np.ndarray] = {}
    for framework, shards in shards_by_framework.items():
        axioms = [s.axiom_summary for s in shards]  # NOT extracted_text (Pitfall 1)
        if not axioms:
            continue
        embeddings = model.encode(
            axioms,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        centroids[framework] = embeddings.mean(axis=0)
    return centroids


def _pairwise_cosine_distances(
    centroids: dict[str, np.ndarray],
) -> dict[tuple[str, str], float]:
    """All ordered cross-framework cosine distances, symmetric.

    Stores both (a, b) and (b, a) so downstream lookup is free of ordering
    concerns. Self-pairs (a, a) are NOT stored (always 0).
    """
    frameworks = sorted(centroids.keys())
    out: dict[tuple[str, str], float] = {}
    for i, a in enumerate(frameworks):
        for b in frameworks[i + 1:]:
            # centroids L2-normalized → cosine similarity == dot;
            # cosine distance = 1 - sim in [0, 2].
            sim = float(np.dot(centroids[a], centroids[b]))
            dist = float(1.0 - sim)
            out[(a, b)] = dist
            out[(b, a)] = dist  # symmetric
    return out


def build_prototype_cluster(shards: list["ShardFixture"]) -> PrototypeCluster:
    """Group shards by framework, compute centroids + pairwise distances.

    Assumes all shards share the same `term`. The cluster_id is minted from
    shards[0].term + sorted frameworks; if shards is empty, term=="" and
    cluster_id is a hash of that empty input (documented but not expected
    to occur in production — 01-06 FP audit always passes non-empty clusters).
    """
    grouped: dict[str, list["ShardFixture"]] = {}
    term = shards[0].term if shards else ""
    for s in shards:
        grouped.setdefault(s.framework, []).append(s)
    centroids = compute_cluster_centroids(grouped)
    distances = _pairwise_cosine_distances(centroids)
    cluster_id = _mint_cluster_id(term, list(grouped.keys()))
    return PrototypeCluster(
        cluster_id=cluster_id,
        term=term,
        shards_by_framework=grouped,
        centroids=centroids,
        cross_framework_cosine_distance=distances,
    )


def centroid_distance_signal(
    cluster: PrototypeCluster,
    framework_a: str,
    framework_b: str,
) -> float:
    """Cosine distance in [0, 2] between two framework centroids.

    EVIDENCE SCORE ONLY — never a final polysemy verdict (Pitfall 1).
    Rule 1 (owl:disjointWith SPARQL) is the authoritative axiom-conflict
    signal; this distance is only an ordering/reporting aid passed through
    on RuleVerdict.evidence_score and LLMVerdict.evidence_score.

    Returns 0.0 for missing pairs (e.g., same-framework self-pair or
    framework not present in the cluster).
    """
    return cluster.cross_framework_cosine_distance.get(
        (framework_a, framework_b), 0.0,
    )
