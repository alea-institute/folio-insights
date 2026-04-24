"""LLM fallback returns a Literal-typed discriminated-union verdict, never a raw float."""
from unittest.mock import patch

import numpy as np
import pytest

from folio_insights.polysemy.detector import (
    LLMVerdict,
    PolysemyVerdict,
    _invoke_llm_fallback,
)
from folio_insights.polysemy.fixture_loader import ShardFixture
from folio_insights.polysemy.prototype_cluster import PrototypeCluster

pytestmark = pytest.mark.polysemy_spike


def _mini_cluster() -> PrototypeCluster:
    shard = ShardFixture(
        iri="fi:Shard_a",
        framework="CommonLaw",
        source_doc="s",
        extracted_text="ax",
        axiom_summary="ax",
        term="consideration",
    )
    return PrototypeCluster(
        cluster_id="fi:PrototypeCluster_mini0000",
        term="consideration",
        shards_by_framework={"CommonLaw": [shard]},
        centroids={"CommonLaw": np.zeros(384)},
        cross_framework_cosine_distance={("CommonLaw", "CommonLaw"): 0.0},
    )


@pytest.mark.parametrize(
    "provider,expected_family",
    [
        ("claude-haiku-4-5", "anthropic"),
        ("gpt-4o-mini", "openai"),
        ("gemini-1.5-flash", "google"),
        ("ollama/llama3.2", "ollama"),
    ],
)
def test_llm_fallback_returns_discriminated_union(
    provider: str, expected_family: str,
) -> None:
    cluster = _mini_cluster()
    canned = PolysemyVerdict(
        decision="polysemy",
        polysemy_vs_homonymy_reasoning="Same doctrine, framework-specific applications.",
        rationale="Per prime-analogate reading.",
    )

    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return canned

    captured: dict[str, str] = {}

    def _fake_from_provider(spec: str):
        captured["spec"] = spec
        return _FakeClient()

    with patch("instructor.from_provider", side_effect=_fake_from_provider):
        verdict = _invoke_llm_fallback(
            cluster, llm_provider=provider, matched_rules=["test"],
        )

    assert isinstance(verdict, LLMVerdict)
    assert verdict.decision == "polysemy"
    assert verdict.provider == expected_family
    assert captured["spec"].startswith(expected_family + ":")
    # No raw-float confidence in verdict shape (Pitfall A6 discipline)
    assert not hasattr(verdict, "confidence_score")


def test_llm_fallback_swallows_exceptions() -> None:
    """If instructor raises, detector returns uncertain verdict — never propagates."""
    cluster = _mini_cluster()
    with patch("instructor.from_provider", side_effect=RuntimeError("network")):
        verdict = _invoke_llm_fallback(
            cluster, llm_provider="claude-haiku-4-5", matched_rules=["test"],
        )
    assert verdict.decision == "uncertain"
    assert "RuntimeError" in verdict.polysemy_vs_homonymy_reasoning
