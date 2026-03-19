"""Task clustering: group knowledge units by embedding similarity.

Uses agglomerative clustering with cosine affinity and average linkage
to discover implicit task groupings from knowledge unit embeddings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sentence_transformers import SentenceTransformer

if TYPE_CHECKING:
    from folio_insights.models.knowledge_unit import KnowledgeUnit

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Lazy-load the sentence-transformers model (singleton)."""
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def cluster_units_for_task_discovery(
    units: list[KnowledgeUnit],
    distance_threshold: float = 0.5,
) -> list[list[int]]:
    """Cluster knowledge units by embedding similarity to discover implicit tasks.

    Uses agglomerative clustering with cosine affinity and average linkage.
    ``distance_threshold`` controls granularity: lower values produce more
    clusters (finer-grained tasks), higher values produce fewer clusters.

    Args:
        units: Knowledge units to cluster.
        distance_threshold: Maximum inter-cluster distance (cosine).
            Default 0.5 is a reasonable starting point for advocacy text.

    Returns:
        List of clusters, where each cluster is a list of indices into
        the input ``units`` list.
    """
    if len(units) < 2:
        # Edge case: not enough units to cluster
        return [list(range(len(units)))] if units else []

    model = _get_model()
    texts = [u.text for u in units]
    embeddings = model.encode(texts, normalize_embeddings=True)

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(embeddings)

    # Group unit indices by cluster label
    clusters: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        clusters.setdefault(int(label), []).append(idx)

    result = list(clusters.values())
    logger.info(
        "Clustered %d units into %d groups (threshold=%.2f)",
        len(units),
        len(result),
        distance_threshold,
    )

    return result
