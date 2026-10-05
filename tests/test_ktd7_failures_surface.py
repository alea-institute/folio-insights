"""KTD7: failures are counted and surfaced, never swallowed (Phase 10, U4 error-handling items).

* per-unit tagging failures are counted, recorded, and fail the run above the ratio (5%);
* a judge outage marks non-ruler tags ``unjudged`` instead of passing them off as judged;
* the B5 canary (``verify_deterministic_bridge``) runs at job start and aborts under
  ``require_deterministic_iri``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from folio_insights.models.knowledge_unit import ConceptTag, KnowledgeType, KnowledgeUnit, Span
from folio_insights.pipeline.stages.base import InsightsJob, InsightsPipelineStage


@pytest.fixture()
def settings_env(monkeypatch):
    from folio_insights.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("FOLIO_INSIGHTS_REQUIRE_DETERMINISTIC_IRI", "false")
    monkeypatch.delenv("FOLIO_JUDGE_ENABLED", raising=False)
    yield monkeypatch
    get_settings.cache_clear()


def _unit(i: int) -> KnowledgeUnit:
    text = f"Synthetic sentence {i} about a synthetic objection rule for the tests."
    return KnowledgeUnit(text=text, original_span=Span(start=0, end=len(text), source_file="s.md"),
                         unit_type=KnowledgeType.ADVICE, source_file="s.md",
                         source_section=["Synthetic Part"])


def _stage(monkeypatch, failing: set[int]):
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    stage = FolioTaggerStage()
    monkeypatch.setattr(stage, "_get_folio_service", lambda: None)
    monkeypatch.setattr(stage, "_get_embedding_service", lambda: None)
    calls = {"n": 0}

    async def _tag(unit, **_kw):
        idx = calls["n"]
        calls["n"] += 1
        if idx in failing:
            raise RuntimeError("synthetic per-unit failure")
        unit.folio_tags = []

    monkeypatch.setattr(stage, "_tag_unit", _tag)
    return stage


async def test_unit_failures_above_the_ratio_fail_the_run_with_a_count(settings_env) -> None:
    from folio_insights.pipeline.stages.folio_tagger import TaggerFailureRatioError

    stage = _stage(settings_env, failing={0, 1})  # 2 of 20 = 10% > 5%
    job = InsightsJob(corpus_name="c", source_dir=Path("."), units=[_unit(i) for i in range(20)])
    with pytest.raises(TaggerFailureRatioError, match="2 of 20"):
        await stage.execute(job)
    meta = job.metadata["folio_tagger"]
    assert meta["unit_failures"] == 2 and meta["units_attempted"] == 20
    failed = [u for u in job.units if any(e.action == "tag_failed" for e in u.lineage)]
    assert len(failed) == 2


async def test_unit_failures_within_the_ratio_are_reported_not_hidden(settings_env) -> None:
    stage = _stage(settings_env, failing={3})  # 1 of 25 = 4% <= 5%
    job = InsightsJob(corpus_name="c", source_dir=Path("."), units=[_unit(i) for i in range(25)])
    job = await stage.execute(job)
    meta = job.metadata["folio_tagger"]
    assert meta["unit_failures"] == 1 and len(meta["unit_failure_ids"]) == 1
    assert meta["unit_failure_ids"][0] == job.units[3].id


async def test_the_ratio_is_configurable(settings_env) -> None:
    settings_env.setenv("FOLIO_INSIGHTS_TAGGER_MAX_UNIT_FAILURE_RATIO", "0.5")
    stage = _stage(settings_env, failing={0, 1})
    job = InsightsJob(corpus_name="c", source_dir=Path("."), units=[_unit(i) for i in range(20)])
    job = await stage.execute(job)
    assert job.metadata["folio_tagger"]["unit_failures"] == 2


class _DownJudge:
    async def structured(self, prompt, *, schema=None, temperature=0):  # noqa: ARG002
        raise ConnectionError("synthetic judge outage")


class _PartialJudge:
    async def structured(self, prompt, *, schema=None, temperature=0):  # noqa: ARG002
        return {"judged": [{"iri_hash": "c0", "adjusted_score": 80, "verdict": "confirmed"}]}


def _tags() -> list[ConceptTag]:
    return [
        ConceptTag(iri="https://folio.test/a", label="A", confidence=0.8, extraction_path="llm"),
        ConceptTag(iri="https://folio.test/b", label="B", confidence=0.7,
                   extraction_path="semantic"),
        ConceptTag(iri="https://folio.test/r", label="R", confidence=0.9,
                   extraction_path="entity_ruler"),
    ]


async def test_judge_outage_marks_tags_unjudged_never_silently_kept() -> None:
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    stage = FolioTaggerStage()
    stage._judge_provider = _DownJudge()
    unit = _unit(0)
    out = await stage._run_judge(unit, _tags(), folio_service=None, prior_context="")
    by_label = {t.label: t.judge_status for t in out}
    assert by_label == {"A": "unjudged", "B": "unjudged", "R": None}  # ruler needs no judge
    assert any(e.action == "judge_unavailable" for e in unit.lineage)
    assert stage._judge_outages == 1


async def test_candidates_the_judge_skipped_are_unjudged() -> None:
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    stage = FolioTaggerStage()
    stage._judge_provider = _PartialJudge()
    out = await stage._run_judge(_unit(0), _tags(), folio_service=None, prior_context="")
    assert {t.label: t.judge_status for t in out} == {"A": "judged", "B": "unjudged", "R": None}


class _Noop(InsightsPipelineStage):
    def __init__(self, name: str) -> None:
        self._name = name
        self.ran = False

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, job):
        self.ran = True
        return job


async def test_b5_canary_failure_aborts_before_any_stage(tmp_path, monkeypatch) -> None:
    from folio_insights.config import Settings
    from folio_insights.pipeline.orchestrator import PipelineOrchestrator
    from folio_insights.services.bridge import folio_bridge

    def _broken():
        raise folio_bridge.BridgeIntegrityError("synthetic: ruler missing")

    monkeypatch.setattr(folio_bridge, "verify_deterministic_bridge", _broken)
    first = _Noop("ingestion")
    orch = PipelineOrchestrator(Settings(output_dir=tmp_path, require_deterministic_iri=True),
                                stages=[first, _Noop("folio_tagger")])
    with pytest.raises(folio_bridge.BridgeIntegrityError):
        await orch.run(tmp_path, corpus_name="c")
    assert first.ran is False


async def test_b5_canary_runs_and_is_recorded(tmp_path, monkeypatch) -> None:
    from folio_insights.config import Settings
    from folio_insights.pipeline.orchestrator import PipelineOrchestrator
    from folio_insights.services.bridge import folio_bridge

    calls: list[str] = []
    monkeypatch.setattr(folio_bridge, "verify_deterministic_bridge", lambda: calls.append("ok"))
    orch = PipelineOrchestrator(Settings(output_dir=tmp_path), stages=[_Noop("folio_tagger")])
    job = await orch.run(tmp_path, corpus_name="c")
    assert calls == ["ok"] and job.metadata["b5_canary"] == {"status": "ok"}

    # Degraded mode (require off): the run continues and records the failure.
    def _broken():
        raise RuntimeError("synthetic")

    monkeypatch.setattr(folio_bridge, "verify_deterministic_bridge", _broken)
    orch = PipelineOrchestrator(Settings(output_dir=tmp_path / "d", require_deterministic_iri=False),
                                stages=[_Noop("folio_tagger")])
    job = await orch.run(tmp_path, corpus_name="c", resume=False)
    assert job.metadata["b5_canary"]["status"] == "failed"


async def test_real_canary_passes_on_this_install(tmp_path) -> None:
    from folio_insights.services.bridge.folio_bridge import verify_deterministic_bridge

    assert verify_deterministic_bridge() is not None
