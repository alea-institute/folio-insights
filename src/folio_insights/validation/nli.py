"""The NLI textual-contradiction screen, adapted to shards (Phase 9 U1, KTD4).

``services/contradiction_detector.py`` screens KnowledgeUnit pairs with the
``cross-encoder/nli-deberta-v3-base`` cross-encoder (label order
contradiction, entailment, neutral). This module adapts that screen to shard
pairs behind a small protocol so the cluster consistency checker can take any
scorer, and tests can inject a fake one:

* ``NliScorer.contradiction_probabilities(pairs)`` returns, per
  ``(premise, hypothesis)`` pair, the probability in ``[0, 1]`` that the two
  contradict.
* ``CrossEncoderNliScorer`` is the default: the same model as the existing
  detector, loaded lazily on first use (sentence-transformers and torch are
  imported only then), with a softmax over the three logits so the threshold
  is a probability rather than a raw logit.

The checker scores both directions of a pair and keeps the larger value, so a
contradiction is symmetric whichever shard comes first.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

# The model and label order of services/contradiction_detector.py.
NLI_MODEL_NAME = "cross-encoder/nli-deberta-v3-base"
CONTRADICTION_LABEL_INDEX = 0
NLI_BATCH_SIZE = 64


@runtime_checkable
class NliScorer(Protocol):
    """Probability that each (premise, hypothesis) pair contradicts."""

    @property
    def name(self) -> str: ...

    def contradiction_probabilities(self, pairs: Sequence[tuple[str, str]]) -> list[float]: ...


def _softmax(row: Sequence[float]) -> list[float]:
    peak = max(row)
    exps = [math.exp(v - peak) for v in row]
    total = sum(exps)
    return [e / total for e in exps]


class CrossEncoderNliScorer:
    """The cross-encoder NLI screen (lazy; worker tier in practice)."""

    def __init__(self, model_name: str = NLI_MODEL_NAME, *, batch_size: int = NLI_BATCH_SIZE) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._model: Any | None = None

    @property
    def name(self) -> str:
        return f"nli:{self.model_name}"

    def _get_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    def contradiction_probabilities(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        model = self._get_model()
        out: list[float] = []
        for start in range(0, len(pairs), self.batch_size):
            batch = list(pairs[start : start + self.batch_size])
            for row in model.predict(batch):
                values = [float(v) for v in row]
                out.append(_softmax(values)[CONTRADICTION_LABEL_INDEX])
        return out


def default_nli_scorer() -> NliScorer:
    """The scorer ``validate clusters`` uses unless told otherwise."""
    return CrossEncoderNliScorer()


__all__ = [
    "CONTRADICTION_LABEL_INDEX",
    "CrossEncoderNliScorer",
    "NLI_MODEL_NAME",
    "NliScorer",
    "default_nli_scorer",
]
