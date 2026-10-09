"""Phase 9 U1 (KTD4): the shard NLI adapter — softmax probabilities, batching,
lazy model load. The model itself is replaced by a stub; no weights load."""
from __future__ import annotations

import sys

from folio_insights.validation.nli import (
    CrossEncoderNliScorer,
    NLI_MODEL_NAME,
    NliScorer,
    default_nli_scorer,
)


class StubModel:
    def __init__(self) -> None:
        self.batches: list[int] = []

    def predict(self, batch):
        self.batches.append(len(batch))
        # logits in label order contradiction, entailment, neutral
        return [[4.0, 0.0, 0.0] if "not" in b else [0.0, 4.0, 0.0] for _a, b in batch]


def test_scores_are_softmax_contradiction_probabilities_in_batches() -> None:
    scorer = CrossEncoderNliScorer(batch_size=2)
    stub = StubModel()
    scorer._model = stub
    probs = scorer.contradiction_probabilities(
        [("x", "is not"), ("x", "is"), ("y", "not y")])
    assert stub.batches == [2, 1]
    assert 0.96 < probs[0] < 0.97 and probs[1] < 0.02 and probs[2] == probs[0]
    assert scorer.contradiction_probabilities([]) == []


def test_default_scorer_is_lazy_and_names_its_model() -> None:
    scorer = default_nli_scorer()
    assert isinstance(scorer, NliScorer)
    assert scorer.name == f"nli:{NLI_MODEL_NAME}"
    assert "sentence_transformers" not in sys.modules or scorer._model is None
