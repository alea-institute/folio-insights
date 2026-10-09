"""Per-unit prompt identity in lineage (drain plan U1, R6, KTD2).

Every lineage event written as the direct result of an LLM call names the registered prompt
template that call used, so a unit's prompt hash is derivable from the unit alone. The stages run
against the real LLM port (instructor + the openai SDK) with an ``httpx.MockTransport`` that
answers each request with a synthetic tool call for the schema it asked for, so the tests also
prove the template a stage records is the template the port actually sent (the run context's
``templates_used``), not a parallel guess.

All text here is synthetic.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from folio_insights.llm import use_context
from folio_insights.llm.port import set_default_port
from folio_insights.llm.templates import (
    BOUNDARY,
    BRANCH_JUDGE,
    CLASSIFY,
    CONCEPT,
    DISTILL,
    NOVELTY,
    PromptTemplate,
    combined_prompt_hash,
    template_for_task,
    unit_prompt_hash,
    unit_template_hashes,
)
from folio_insights.models.knowledge_unit import (
    ConceptTag,
    KnowledgeType,
    KnowledgeUnit,
    Span,
    StageEvent,
)
from folio_insights.pipeline.stages.base import InsightsJob, record_lineage
from tests.llm.conftest import load_fixture, make_context, make_port

SUBSTANTIVE = (
    "Before the hearing, confirm that every synthetic exhibit has a witness who can lay its "
    "foundation, or the exhibit may never reach the invented tribunal."
)

# Synthetic structured outputs, keyed by the output schema name the port sends as the tool name.
PAYLOADS: dict[str, dict[str, Any]] = {
    "DistilledOutput": {"distilled_text": "Line up a foundation witness for each exhibit.",
                        "preserved_nuances": ["timing"]},
    "ClassificationOutput": {"unit_type": "advice", "confidence": 0.8, "reasoning": "synthetic"},
    "NoveltyOutput": {"score": 0.4, "reasoning": "synthetic"},
    "ConceptOutput": {"concepts": [{"concept_text": "Synthetic Exhibit", "confidence": 0.7}]},
    "JudgeOutput": {"judged": [{"iri_hash": "c0", "adjusted_score": 80, "verdict": "confirmed"},
                               {"iri_hash": "c1", "adjusted_score": 0, "verdict": "rejected"}]},
}


class SchemaRouter:
    """A MockTransport handler answering each request with the payload for its tool's schema."""

    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = payloads
        self.template = load_fixture("openai")["valid"]
        self.requests: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        name = body["tools"][0]["function"]["name"]
        reply = copy.deepcopy(self.template)
        call = reply["body"]["choices"][0]["message"]["tool_calls"][0]["function"]
        call["name"] = name
        call["arguments"] = json.dumps(self.payloads[name])
        return httpx.Response(reply["status"], json=reply["body"])

    def factory(self):  # noqa: ANN201 - mirrors tests.llm.conftest.Recorder.factory
        return lambda _spec: httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture()
def llm_run(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Route every stage's LLM call through the real port, offline, inside one run context."""
    for name in ("FOLIO_JUDGE_ENABLED", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    router = SchemaRouter(PAYLOADS)
    set_default_port(make_port(router))  # type: ignore[arg-type]
    ctx = make_context("openai")
    try:
        with use_context(ctx):
            yield ctx
    finally:
        set_default_port(None)


def _unit(text: str = SUBSTANTIVE) -> KnowledgeUnit:
    return KnowledgeUnit(
        text=text,
        original_span=Span(start=0, end=len(text), source_file="synthetic.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="synthetic.md",
        source_section=["Synthetic Part", "Synthetic Chapter"],
    )


def _events(unit: KnowledgeUnit, action: str) -> list[StageEvent]:
    return [e for e in unit.lineage if e.action == action]


def _llm_identity(unit: KnowledgeUnit) -> dict[str, str]:
    return {e.template_id: e.template_hash for e in unit.lineage if e.template_id}


async def _distill(unit: KnowledgeUnit) -> None:
    from folio_insights.pipeline.stages.distiller import DistillerStage
    from folio_insights.services.bridge.llm_bridge import LLMBridge

    await DistillerStage()._distill_unit(unit, LLMBridge())


async def _classify(unit: KnowledgeUnit) -> None:
    from folio_insights.pipeline.stages.knowledge_classifier import KnowledgeClassifierStage

    stage = KnowledgeClassifierStage()
    await stage._classify_unit(unit)
    await stage._score_novelty(unit)


# ---- StageEvent / record_lineage -----------------------------------------------------------------


def test_record_lineage_takes_the_identity_from_the_registered_template() -> None:
    unit = _unit()
    record_lineage(unit, "distiller", "distill", template=DISTILL)
    record_lineage(unit, "knowledge_classifier", "classify",
                   template_id=CLASSIFY.id, template_hash=CLASSIFY.hash)
    record_lineage(unit, "deduplicator", "merge")
    assert [(e.template_id, e.template_hash) for e in unit.lineage] == [
        (DISTILL.id, DISTILL.hash), (CLASSIFY.id, CLASSIFY.hash), (None, None)]


def test_record_lineage_template_arguments_are_keyword_only_and_consistent() -> None:
    unit = _unit()
    with pytest.raises(TypeError):
        record_lineage(unit, "distiller", "distill", "", None, DISTILL)  # type: ignore[misc]
    with pytest.raises(ValueError, match="disagrees"):
        record_lineage(unit, "distiller", "distill", template=DISTILL, template_id=CLASSIFY.id)
    with pytest.raises(ValueError, match="disagrees"):
        record_lineage(unit, "distiller", "distill", template=DISTILL,
                       template_hash=CLASSIFY.hash)
    with pytest.raises(ValueError, match="together"):
        record_lineage(unit, "distiller", "distill", template_id=DISTILL.id)
    assert unit.lineage == []


def test_stage_event_rejects_half_a_template_identity() -> None:
    with pytest.raises(ValueError, match="together"):
        StageEvent(stage="s", action="a", template_hash=DISTILL.hash)


# ---- LLM-backed stages record the template the port used -----------------------------------------


async def test_distiller_event_carries_the_distill_template(llm_run) -> None:
    unit = _unit()
    await _distill(unit)
    (event,) = _events(unit, "distill")
    assert (event.template_id, event.template_hash) == (DISTILL.id, DISTILL.hash)
    assert llm_run.templates_used == {DISTILL.id: DISTILL.hash}


async def test_classifier_and_novelty_events_carry_their_templates(llm_run) -> None:
    unit = _unit()
    await _classify(unit)
    (classify,) = _events(unit, "classify")
    (novelty,) = _events(unit, "novelty_score")
    assert (classify.template_id, classify.template_hash) == (CLASSIFY.id, CLASSIFY.hash)
    assert (novelty.template_id, novelty.template_hash) == (NOVELTY.id, NOVELTY.hash)
    assert _llm_identity(unit) == llm_run.templates_used


async def test_tagger_concept_and_judge_events_carry_their_templates(llm_run) -> None:
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage
    from folio_insights.services.heading_context import HeadingContextExtractor

    stage = FolioTaggerStage()
    unit = _unit()
    await stage._tag_unit(
        unit, folio_service=None, embedding_service=None, aho_matcher=None,
        heading_extractor=HeadingContextExtractor(None),
        reconciler=stage._get_reconciler(None),
    )
    (tag,) = _events(unit, "tag")
    assert (tag.template_id, tag.template_hash) == (CONCEPT.id, CONCEPT.hash)

    candidates = [
        ConceptTag(iri="https://folio.test/a", label="A", confidence=0.8, extraction_path="llm"),
        ConceptTag(iri="https://folio.test/b", label="B", confidence=0.7,
                   extraction_path="semantic"),
        ConceptTag(iri="https://folio.test/r", label="R", confidence=0.9,
                   extraction_path="entity_ruler"),
    ]
    kept = await stage._run_judge(unit, candidates, folio_service=None, prior_context="")
    assert [t.label for t in kept] == ["A", "R"]
    (judge,) = _events(unit, "judge")
    assert (judge.template_id, judge.template_hash) == (BRANCH_JUDGE.id, BRANCH_JUDGE.hash)
    assert _llm_identity(unit) == llm_run.templates_used == {
        CONCEPT.id: CONCEPT.hash, BRANCH_JUDGE.id: BRANCH_JUDGE.hash}


async def test_judge_records_its_template_even_when_it_rejects_nothing(
    llm_run, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    monkeypatch.setitem(PAYLOADS, "JudgeOutput", {
        "judged": [{"iri_hash": "c0", "adjusted_score": 80, "verdict": "confirmed"}]})
    unit = _unit()
    tags = [ConceptTag(iri="https://folio.test/a", label="A", confidence=0.8,
                       extraction_path="llm")]
    await FolioTaggerStage()._run_judge(unit, tags, folio_service=None, prior_context="")
    (judge,) = _events(unit, "judge")
    assert judge.template_id == BRANCH_JUDGE.id
    assert "rejected 0/1" in judge.detail


async def test_llm_refined_boundaries_carry_the_boundary_template(
    llm_run, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from folio_insights.config import get_settings
    from folio_insights.pipeline.stages.boundary_detection import BoundaryDetectionStage

    sentences = [f"Synthetic sentence {i} sets out one more step of the invented procedure."
                 for i in range(12)]
    paragraph = " ".join(sentences)
    half = len(" ".join(sentences[:6]))
    # Two LLM segments: a short one, and one longer than the size cap so it is re-split.
    monkeypatch.setitem(PAYLOADS, "BoundaryRefinementResponse", {"boundaries": [
        {"start_char": 0, "end_char": 160, "rationale": "synthetic"},
        {"start_char": 160, "end_char": len(paragraph), "rationale": "synthetic"},
    ]})
    monkeypatch.setenv("FOLIO_INSIGHTS_BOUNDARY_LLM_REFINE", "true")
    monkeypatch.setenv("FOLIO_INSIGHTS_BOUNDARY_MAX_UNIT_CHARS", str(half))
    get_settings.cache_clear()
    try:
        stage = BoundaryDetectionStage()

        async def _no_tier2(boundary):  # noqa: ARG001, ANN001, ANN202
            return None

        monkeypatch.setattr(stage, "_run_tier2", _no_tier2)
        element = {"text": paragraph, "element_type": "paragraph",
                   "section_path": ["Synthetic Part"], "level": 0,
                   "char_offset_start": 0, "char_offset_end": len(paragraph)}
        job = InsightsJob(corpus_name="synthetic", source_dir=Path("/nonexistent"), metadata={
            "structured": {"synthetic.md": [element]},
            "ingested": {"synthetic.md": {"text": paragraph}}})
        job = await stage.execute(job)
    finally:
        get_settings.cache_clear()

    methods = {e.detail for u in job.units for e in u.lineage if e.action == "split"}
    assert methods == {"method=llm_refined", "method=llm_refined+sentence_group"}
    for unit in job.units:
        (split,) = _events(unit, "split")
        assert (split.template_id, split.template_hash) == (BOUNDARY.id, BOUNDARY.hash)
    assert llm_run.templates_used == {BOUNDARY.id: BOUNDARY.hash}


async def test_tag_event_names_no_template_when_the_concept_call_failed(
    llm_run, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage
    from folio_insights.services.bridge import llm_bridge
    from folio_insights.services.heading_context import HeadingContextExtractor

    class _DownConcept:
        async def structured(self, *_a, **_kw):  # noqa: ANN002, ANN003, ANN202
            raise ConnectionError("synthetic outage")

    monkeypatch.setattr(llm_bridge.LLMBridge, "get_llm_for_task",
                        lambda self, task, **kw: _DownConcept())  # noqa: ARG005
    stage = FolioTaggerStage()
    unit = _unit()
    await stage._tag_unit(
        unit, folio_service=None, embedding_service=None, aho_matcher=None,
        heading_extractor=HeadingContextExtractor(None),
        reconciler=stage._get_reconciler(None),
    )
    (tag,) = _events(unit, "tag")
    assert tag.template_id is None and tag.template_hash is None
    assert unit_prompt_hash(unit.lineage) is None


def test_every_lineage_template_is_its_tasks_routed_template() -> None:
    """The template a stage records is the default its routing task resolves to."""
    for task, template in {"distiller": DISTILL, "classifier": CLASSIFY, "novelty": NOVELTY,
                           "concept": CONCEPT, "branch_judge": BRANCH_JUDGE,
                           "boundary": BOUNDARY}.items():
        assert template_for_task(task) is template


# ---- deterministic events record nothing ---------------------------------------------------------


async def test_deterministic_and_failed_events_record_no_template(monkeypatch) -> None:
    from folio_insights.config import get_settings
    from folio_insights.pipeline.stages.boundary_detection import BoundaryDetectionStage
    from folio_insights.pipeline.stages.deduplicator import DeduplicatorStage
    from folio_insights.pipeline.stages.distiller import DistillerStage

    element = {"text": SUBSTANTIVE, "element_type": "paragraph",
               "section_path": ["Synthetic Part"], "level": 0,
               "char_offset_start": 0, "char_offset_end": len(SUBSTANTIVE)}
    job = InsightsJob(corpus_name="synthetic", source_dir=Path("/nonexistent"), metadata={
        "structured": {"synthetic.md": [element, dict(element)]},
        "ingested": {"synthetic.md": {"text": SUBSTANTIVE}}})
    get_settings.cache_clear()
    job = await BoundaryDetectionStage().execute(job)
    assert len(job.units) == 2
    job = await DeduplicatorStage().execute(job)

    class _DownBridge:
        def get_llm_for_task(self, task):  # noqa: ARG002, ANN001, ANN202
            raise ConnectionError("synthetic outage")

    skipped = _unit("Chapter 3")
    await DistillerStage()._distill_unit(skipped, _DownBridge())
    failed = _unit()
    await DistillerStage()._distill_unit(failed, _DownBridge())

    events = [e for u in [*job.units, skipped, failed] for e in u.lineage]
    assert {e.action for e in events} >= {"split", "distill_skipped", "distill_failed"}
    assert all(e.template_id is None and e.template_hash is None for e in events)
    assert all(unit_prompt_hash(u.lineage) is None for u in [*job.units, skipped, failed])


# ---- unit_prompt_hash ----------------------------------------------------------------------------


async def test_unit_prompt_hash_is_the_combined_hash_of_its_stage_hashes(llm_run) -> None:
    unit = _unit()
    record_lineage(unit, "boundary_detection", "split", detail="method=structural")
    await _distill(unit)
    await _classify(unit)
    expected = combined_prompt_hash([DISTILL.hash, CLASSIFY.hash, NOVELTY.hash])
    assert unit_prompt_hash(unit.lineage) == expected
    assert unit_prompt_hash(reversed(unit.lineage)) == expected
    assert unit_template_hashes(unit.lineage) == {
        CLASSIFY.id: CLASSIFY.hash, DISTILL.id: DISTILL.hash, NOVELTY.id: NOVELTY.hash}
    # A repeated call through the same template does not change the identity.
    await _classify(unit)
    assert unit_prompt_hash(unit.lineage) == expected


async def test_unit_prompt_hash_is_stable_across_runs(llm_run) -> None:
    first, second = _unit(), _unit()
    for unit in (first, second):
        await _distill(unit)
        await _classify(unit)
    assert first.lineage[0].timestamp != "" and first.id != second.id
    assert unit_prompt_hash(first.lineage) == unit_prompt_hash(second.lineage) is not None


async def test_unit_prompt_hash_changes_when_a_template_text_changes(
    llm_run, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from folio_insights.pipeline.stages import distiller

    baseline = _unit()
    await _distill(baseline)

    edited = PromptTemplate(id=DISTILL.id, version=DISTILL.version, task=DISTILL.task,
                            user=DISTILL.user + "\nKeep it under twenty words.",
                            output_schema=DISTILL.output_schema)
    monkeypatch.setattr(distiller, "DISTILL", edited)
    changed = _unit()
    await _distill(changed)

    (event,) = _events(changed, "distill")
    assert event.template_hash == edited.hash != DISTILL.hash
    # The port sent the edited template too: the call and the lineage event cannot diverge.
    assert llm_run.templates_used[DISTILL.id] == edited.hash
    assert unit_prompt_hash(changed.lineage) != unit_prompt_hash(baseline.lineage)

    system_edit = PromptTemplate(id=DISTILL.id, version=DISTILL.version, task=DISTILL.task,
                                 user=DISTILL.user, system="Answer tersely.",
                                 output_schema=DISTILL.output_schema)
    record = [StageEvent(stage="distiller", action="distill", template_id=system_edit.id,
                         template_hash=system_edit.hash)]
    assert unit_prompt_hash(record) not in {unit_prompt_hash(baseline.lineage),
                                            unit_prompt_hash(changed.lineage)}


def test_unit_template_hashes_keeps_the_latest_hash_per_id() -> None:
    old = PromptTemplate(id="synthetic.t", version="1", task="synthetic", user="old {x}")
    new = PromptTemplate(id="synthetic.t", version="2", task="synthetic", user="new {x}")
    lineage = [StageEvent(stage="s", action="a", template_id=t.id, template_hash=t.hash)
               for t in (old, new)]
    assert unit_template_hashes(lineage) == {"synthetic.t": new.hash}
    assert unit_prompt_hash(lineage) == combined_prompt_hash([old.hash, new.hash])


# ---- backward compatibility ----------------------------------------------------------------------

_OLD_UNIT = {
    "id": "u-old",
    "text": "Synthetic legacy unit text.",
    "original_span": {"start": 0, "end": 27, "source_file": "legacy.md"},
    "unit_type": "advice",
    "source_file": "legacy.md",
    "lineage": [
        {"stage": "boundary_detection", "action": "split", "detail": "method=structural",
         "confidence": 0.7, "timestamp": "2026-01-01T00:00:00+00:00"},
        {"stage": "distiller", "action": "distill", "detail": "compressed",
         "confidence": None, "timestamp": "2026-01-01T00:00:01+00:00"},
    ],
}


def test_old_format_extraction_json_still_loads(tmp_path: Path) -> None:
    """An extraction.json written before the template fields existed loads unchanged."""
    path = tmp_path / "extraction.json"
    path.write_text(json.dumps({"corpus": "legacy", "units": [_OLD_UNIT]}), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    # TaskDiscoveryOrchestrator.run builds its units exactly like this.
    (unit,) = [KnowledgeUnit(**u) for u in data["units"]]
    assert [e.template_id for e in unit.lineage] == [None, None]
    assert unit_prompt_hash(unit.lineage) is None
    assert unit_prompt_hash(data["units"][0]["lineage"]) is None  # raw dicts work too


def test_old_format_checkpoint_resumes(tmp_path: Path) -> None:
    from folio_insights.pipeline.orchestrator import PipelineCheckpoint

    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    (checkpoints / "distiller.json").write_text(json.dumps({
        "stage": "distiller",
        "job": {"corpus_name": "legacy", "source_dir": str(tmp_path), "units": [_OLD_UNIT]},
    }), encoding="utf-8")
    job = PipelineCheckpoint.load("distiller", tmp_path)
    assert job is not None
    assert [e.action for e in job.units[0].lineage] == ["split", "distill"]
    assert all(e.template_hash is None for e in job.units[0].lineage)


def test_new_lineage_round_trips_through_json() -> None:
    unit = _unit()
    record_lineage(unit, "distiller", "distill", template=DISTILL)
    dumped = json.loads(json.dumps(unit.model_dump(mode="json")))
    assert dumped["lineage"][0]["template_id"] == DISTILL.id
    restored = KnowledgeUnit(**dumped)
    assert unit_prompt_hash(restored.lineage) == unit_prompt_hash(unit.lineage) == (
        combined_prompt_hash([DISTILL.hash]))
    assert unit_prompt_hash(dumped["lineage"]) == unit_prompt_hash(unit.lineage)
