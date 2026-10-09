# Vendored from folio-enrich backend/app/services/embedding/service.py
# (EmbeddingService) and backend/app/services/embedding/providers/local.py @ 510a652 (MIT).
"""In-repo embedding service over a local sentence-transformers model.

Replaces the sys.path bridge to folio-enrich's
``app.services.embedding.service.EmbeddingService``. folio-insights obtained it via
``EmbeddingService.get_instance()``, whose default provider is folio-enrich's
``LocalEmbeddingProvider()`` = sentence-transformers ``all-MiniLM-L6-v2`` with
``normalize_embeddings=True`` (enrich's ``embedding_provider`` default is ``"local"``).
This module reproduces that object: same model, same normalization, same
``search`` / ``similarity`` / ``similarity_batch`` / ``index_labels`` /
``index_size`` contract.

Like the enrich singleton insights received, the instance starts with an EMPTY
label index (``index_size == 0``): nothing in folio-insights calls
``index_folio_labels``, so ``folio_tagger``'s semantic path stays gated off and
only ``similarity_batch`` (reconciler triage) does real work. Enrich's on-disk
label-embedding cache and the remote (ollama / openai) providers are not
vendored; insights never used them.

The model is loaded through ``folio_insights.services.boundary.semantic._get_model``
so the deduplicator, the semantic boundary detector and this service share one
copy. Parity (cosine similarities within 1e-4 of the enrich service) is pinned by
``tests/test_bridge_retirement_parity.py``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


@dataclass
class SearchResult:
    label: str
    score: float
    metadata: dict


class EmbeddingService:
    """Embedding service with an in-memory label index for similarity search."""

    _instance: EmbeddingService | None = None
    _instance_lock = threading.Lock()

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        self._model_name = model_name
        self._labels: list[str] = []
        self._metadata: list[dict] = []
        self._embeddings: np.ndarray | None = None

    @classmethod
    def get_instance(cls) -> EmbeddingService:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = EmbeddingService()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Test hook: drop the singleton."""
        with cls._instance_lock:
            cls._instance = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts to L2-normalized vectors, shape (N, dim)."""
        from folio_insights.services.boundary.semantic import _get_model

        model = _get_model(self._model_name)
        return model.encode(texts, normalize_embeddings=True)

    def encode_single(self, text: str) -> np.ndarray:
        return self.encode([text])[0]

    def index_labels(self, labels: list[str], metadata: list[dict] | None = None) -> None:
        self._labels = labels
        self._metadata = metadata or [{} for _ in labels]
        if labels:
            self._embeddings = self.encode(labels)
            logger.info("Indexed %d labels (%d dims)", len(labels), self._embeddings.shape[1])
        else:
            self._embeddings = None

    @staticmethod
    def _top_k_indices(scores: np.ndarray, top_k: int) -> np.ndarray:
        """Indices of the top_k highest scores, descending (argpartition, then sort winners)."""
        n = scores.shape[0]
        k = min(top_k, n)
        if k <= 0:
            return np.empty(0, dtype=int)
        if k >= n:
            return np.argsort(scores)[::-1]
        part = np.argpartition(scores, n - k)[-k:]
        return part[np.argsort(scores[part])[::-1]]

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        if self._embeddings is None or len(self._labels) == 0:
            return []

        query_vec = self.encode_single(query)
        scores = self._embeddings @ query_vec  # cosine (vectors are normalized)
        return [
            SearchResult(
                label=self._labels[idx],
                score=float(scores[idx]),
                metadata=self._metadata[idx],
            )
            for idx in self._top_k_indices(scores, top_k)
        ]

    def search_batch(self, queries: list[str], top_k: int = 5) -> list[list[SearchResult]]:
        if self._embeddings is None or len(self._labels) == 0 or not queries:
            return [[] for _ in queries]

        query_vecs = self.encode(queries)
        all_scores = query_vecs @ self._embeddings.T
        results = []
        for i in range(len(queries)):
            scores = all_scores[i]
            results.append([
                SearchResult(
                    label=self._labels[idx],
                    score=float(scores[idx]),
                    metadata=self._metadata[idx],
                )
                for idx in self._top_k_indices(scores, top_k)
            ])
        return results

    def similarity(self, text_a: str, text_b: str) -> float:
        vecs = self.encode([text_a, text_b])
        return float(np.dot(vecs[0], vecs[1]))

    def similarity_batch(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Similarity for several text pairs with one batch embedding call."""
        if not pairs:
            return []
        all_texts: list[str] = []
        for a, b in pairs:
            all_texts.extend([a, b])
        vecs = self.encode(all_texts)
        return [float(np.dot(vecs[i], vecs[i + 1])) for i in range(0, len(all_texts), 2)]

    @property
    def index_size(self) -> int:
        return len(self._labels)
