"""Phase 9 U2 (R5, KTD12) — the framework detector and the confidence gate.

Deterministic stages first; the LLM chooses among registered frameworks only
and a fake provider that proposes an unregistered ID is rejected. Synthetic
metadata only; no provider is called.
"""
from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from folio_insights.frameworks.detector import (
    FrameworkDetector,
    FrameworkLLMChoice,
    PortFrameworkLLM,
    SourceMetadata,
)
from folio_insights.frameworks.valid_time import SourceTimeMetadata
from folio_insights.models.framework import FrameworkRegistry, UnregisteredFramework
from folio_insights.quality.confidence_gate import ConfidenceGate


class FakeLLM:
    def __init__(self, framework_id: str | None, confidence: float = 0.95) -> None:
        self.choice = FrameworkLLMChoice(framework_id=framework_id, confidence=confidence)
        self.calls: list[list[tuple[str, str]]] = []

    def choose(self, metadata, candidates):  # noqa: ANN001, ANN201
        self.calls.append(candidates)
        return self.choice


@pytest.fixture
def registry() -> FrameworkRegistry:
    return FrameworkRegistry.with_defaults()


def test_explicit_metadata_wins(registry: FrameworkRegistry) -> None:
    llm = FakeLLM("us.ucc")
    det = FrameworkDetector(registry, corpus_default="us.common_law", llm=llm).detect(
        SourceMetadata(framework_id="us.federal.fre", citations=("U.C.C. § 2-207",))
    )
    assert (det.framework_id, det.source, det.confidence) == ("us.federal.fre", "metadata", 1.0)
    assert det.evidence == ("metadata: framework_id=us.federal.fre",)
    assert llm.calls == []


def test_v1_year_suffix_is_migrated_with_a_warning(registry: FrameworkRegistry) -> None:
    det = FrameworkDetector(registry).detect(SourceMetadata(framework_id="us.federal.frcp.2024"))
    assert det.framework_id == "us.federal.frcp" and det.source == "metadata"
    assert any("year suffix stripped" in w for w in det.migration_warnings)


def test_corpus_default_then_citations(registry: FrameworkRegistry) -> None:
    default = FrameworkDetector(registry, corpus_default="us.common_law").detect(
        SourceMetadata(framework_id="us.delaware.dgcl")  # unregistered: ignored, recorded
    )
    assert (default.framework_id, default.source) == ("us.common_law", "corpus_default")
    assert "not registered" in default.evidence[0]

    cited = FrameworkDetector(registry).detect(
        SourceMetadata(citations=("Fed. R. Evid. 702", "FRE 403", "synthetic note"))
    )
    assert (cited.framework_id, cited.source) == ("us.federal.fre", "citation")
    assert cited.confidence == pytest.approx(0.95)


def test_mixed_citations_are_not_confident_and_fail_the_gate(registry: FrameworkRegistry) -> None:
    det = FrameworkDetector(registry).detect(
        SourceMetadata(citations=("Fed. R. Evid. 702", "U.C.C. § 2-207"))
    )
    assert det.framework_id is None and det.source is None
    assert "tie" in det.evidence[0]
    gate = ConfidenceGate().check_framework(det)
    assert not gate.passed and "refusing to default" in gate.reason


def test_llm_chooses_only_among_registered(registry: FrameworkRegistry) -> None:
    llm = FakeLLM("us.louisiana.civil_code", 0.9)
    det = FrameworkDetector(registry, llm=llm).detect(SourceMetadata(title="synthetic code"))
    assert (det.framework_id, det.source) == ("us.louisiana.civil_code", "llm")
    assert [fid for fid, _ in llm.calls[0]] == registry.ids()


@pytest.mark.parametrize("proposed", ["us.delaware.dgcl", "Made Up Framework", "us.federal.frcp.2024"])
def test_llm_cannot_mint_an_unregistered_id(registry: FrameworkRegistry, proposed: str) -> None:
    det = FrameworkDetector(registry, llm=FakeLLM(proposed, 0.99)).detect(SourceMetadata())
    assert det.framework_id is None and det.source is None
    assert any("rejected" in e and "never mints" in e for e in det.evidence)
    assert not ConfidenceGate().check_framework(det).passed


def test_low_confidence_llm_fails_the_gate(registry: FrameworkRegistry) -> None:
    det = FrameworkDetector(registry, llm=FakeLLM("us.ucc", 0.4)).detect(SourceMetadata())
    assert det.framework_id is None and det.confidence == pytest.approx(0.4)
    result = ConfidenceGate().check_framework(det)
    assert not result.passed


def test_gate_passes_a_confident_detection(registry: FrameworkRegistry) -> None:
    det = FrameworkDetector(registry).detect(SourceMetadata(framework_id="us.ucc"))
    result = ConfidenceGate().check_framework(det)
    assert result.passed and result.framework_id == "us.ucc"


def test_corpus_default_must_be_registered(registry: FrameworkRegistry) -> None:
    with pytest.raises(UnregisteredFramework):
        FrameworkDetector(registry, corpus_default="us.delaware.dgcl")


def test_detection_carries_valid_time_evidence(registry: FrameworkRegistry) -> None:
    det = FrameworkDetector(registry).detect(
        SourceMetadata(
            framework_id="us.federal.fre",
            time=SourceTimeMetadata(kind="rules", effective_date=date(1975, 7, 1),
                                    amendment_dates=(date(2000, 12, 1),),
                                    version_date=date(2005, 1, 1)),
        )
    )
    assert det.valid_time is not None
    assert det.valid_time.start.year == 2000 and det.valid_time.end is None
    assert "amendment_date=2000-12-01" in det.valid_time.evidence


def test_port_adapter_routes_through_the_llm_port_template(registry: FrameworkRegistry) -> None:
    from folio_insights.llm.schemas import FrameworkChoice
    from folio_insights.llm.templates import FRAMEWORK_DETECT, template_for_task

    seen = {}

    class FakeTaskLLM:
        def structured_model_sync(self, prompt, schema, *, template):  # noqa: ANN001, ANN201
            seen.update(prompt=prompt, schema=schema, template=template)
            return FrameworkChoice(framework_id="us.ucc", confidence=0.88, rationale="synthetic")

    choice = PortFrameworkLLM(FakeTaskLLM()).choose(
        SourceMetadata(title="Synthetic sales code"), [(f.id, f.label) for f in registry]
    )
    assert choice.framework_id == "us.ucc"
    assert seen["schema"] is FrameworkChoice and seen["template"] is FRAMEWORK_DETECT
    assert "us.louisiana.civil_code" in seen["prompt"] and "Never invent" in seen["prompt"]
    assert template_for_task("framework_detector") is FRAMEWORK_DETECT


_framework_ids = st.sampled_from(
    [None, "us.federal.fre", "us.ucc", "us.delaware.dgcl", "us.federal.frcp.2024", "bad id"]
)
_citations = st.lists(
    st.sampled_from(["Fed. R. Evid. 702", "Fed. R. Civ. P. 26", "U.C.C. § 2-207",
                     "Restatement (Second) of Contracts § 71", "La. Civ. Code art. 1967",
                     "synthetic cite"]),
    max_size=4,
).map(tuple)


@settings(max_examples=1000, deadline=None)
@given(framework_id=_framework_ids, citations=_citations,
       llm_id=st.sampled_from([None, "us.ucc", "us.delaware.dgcl"]),
       llm_conf=st.floats(0, 1, allow_nan=False))
def test_identical_inputs_give_identical_outputs(framework_id, citations, llm_id, llm_conf) -> None:  # noqa: ANN001
    meta = SourceMetadata(framework_id=framework_id, citations=citations)
    first = FrameworkDetector(FrameworkRegistry.with_defaults(), llm=FakeLLM(llm_id, llm_conf))
    second = FrameworkDetector(FrameworkRegistry.with_defaults(), llm=FakeLLM(llm_id, llm_conf))
    a, b = first.detect(meta), second.detect(meta)
    assert a == b and a == first.detect(meta)
    # whatever happens, a returned framework is always a registered one
    assert a.framework_id is None or a.framework_id in first.registry
