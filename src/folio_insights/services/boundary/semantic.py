"""Tier 2: Embedding-based semantic boundary detection (CPU-only, handles ~15-20%).

Uses sentence-transformers to detect topic shifts within paragraphs
by measuring cosine similarity drops between consecutive sentences.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Module-level model cache to avoid reloading on every call
_cached_model: Any = None
_cached_model_name: str = ""


def _get_model(model_name: str = "all-MiniLM-L6-v2") -> Any:
    """Load and cache sentence-transformers model."""
    global _cached_model, _cached_model_name

    if _cached_model is not None and _cached_model_name == model_name:
        return _cached_model

    from sentence_transformers import SentenceTransformer

    _cached_model = SentenceTransformer(model_name)
    _cached_model_name = model_name
    logger.info("Loaded sentence-transformers model: %s", model_name)
    return _cached_model


def detect_semantic_boundaries(
    sentences: list[str],
    model_name: str = "all-MiniLM-L6-v2",
    threshold: float = 0.3,
) -> list[int]:
    """Detect topic-shift boundaries via embedding cosine similarity drops.

    Encodes all sentences into embeddings and computes cosine similarity
    between consecutive pairs. Where similarity drops below ``threshold``,
    marks that position as a boundary.

    Use for paragraphs that Tier 1 did NOT split (long paragraphs
    without structural markers).

    Args:
        sentences: List of sentence strings.
        model_name: Sentence-transformers model to use.
        threshold: Cosine similarity threshold; drops below this
            mark a boundary (default 0.3).

    Returns:
        List of sentence indices where boundaries occur. If index ``i``
        is returned, the boundary falls *between* sentence ``i-1`` and
        sentence ``i`` (i.e., sentence ``i`` starts a new segment).
    """
    if len(sentences) < 2:
        return []

    model = _get_model(model_name)
    embeddings = model.encode(sentences, convert_to_numpy=True, normalize_embeddings=True)

    boundary_indices: list[int] = []
    for i in range(1, len(sentences)):
        sim = float(np.dot(embeddings[i - 1], embeddings[i]))
        if sim < threshold:
            boundary_indices.append(i)

    logger.debug(
        "Semantic boundaries: %d found in %d sentences (threshold=%.2f)",
        len(boundary_indices),
        len(sentences),
        threshold,
    )
    return boundary_indices
