"""Checkpointed extraction, independent judges and exhaustive omission coverage."""
from __future__ import annotations

import json
import threading

import pytest

from folio_insights.measurement.annotations import AnnotationStore
from folio_insights.measurement.gold import load_gold, load_ontology
from folio_insights.measurement.judges import JudgeResult, JudgeVerdict
from folio_insights.measurement.matching import MATCHER_POLICY, content_digest
from folio_insights.measurement.runs import (
    MeasurementCoordinator, PipelineExtraction, judge_template_sha256,
)
from folio_insights.measurement.schema import EvaluationInputs, JudgeIdentity
from folio_insights.measurement.scoring import SCORER_VERSION
from folio_insights.measurement.store import RunStore


class FakeJudge:
    def __init__(self, provider, *, error=None, partial=False, uncertain=False):
        self.provider, self.error, self.partial = provider, error, partial
        self.uncertain = uncertain
        self.calls = []

    def judge(self, packet, *, cancelled=None):
        self.calls.append(packet)
        items = packet.items[:1] if self.partial else (() if self.error else packet.items)
        judgments = tuple(JudgeVerdict(
            item_id=i.item_id, verdict="uncertain" if self.uncertain else "correct",
            reason="Reviewed against source and candidate context.", omission=None,
            concept_ids=i.concept_ids,
        ) for i in items)
        return JudgeResult(
            provider=self.provider, identity=JudgeIdentity(cli_version="fake-1", model="fake"),
            input_sha256=packet.sha256, prompt_sha256="a" * 64, isolation=("fake",),
            status="incomplete" if self.error else "complete", error=self.error,
            judgments=judgments,
            missing_item_ids=tuple(i.item_id for i in packet.items[len(items):]),
        )


@pytest.fixture
def setup_run(tmp_path):
    full = load_gold()
    suite = full.model_copy(update={"documents": (full.documents[0],)})
    doc = suite.documents[0]
    units = [dict(
        id=p.item_id, text=p.text, unit_type="advice", proposition_kind=p.kind,
        original_span=dict(start=p.span.start, end=p.span.end, source_file="source.txt"),
        source_file="source.txt", source_snippet=p.span.source_slice(doc.source.text),
        folio_tags=[dict(iri=load_ontology().resolve(t.label, t.branch).iri,
                        label=t.label, branch=t.branch, confidence=1, extraction_path="entity_ruler")
                    for t in p.tags],
        links=[link.model_dump() for link in p.links],
    ) for p in doc.propositions]
    path = tmp_path / "extraction.json"
    path.write_text(json.dumps({"units": units}))
    extractor = PipelineExtraction({doc.source.source_id: path})
    pins = EvaluationInputs(
        source_snapshots={doc.source.source_id: doc.source.sha256},
        gold_revision=suite.gold_revision, gold_sha256=content_digest(suite.model_dump(mode="json")),
        split_manifest_sha256="1" * 64, ontology_sha256=suite.ontology_sha256,
        scorer_version=SCORER_VERSION, matcher_version=MATCHER_POLICY.version,
        baseline_commit="2" * 40, candidate_commit="3" * 40,
        baseline_config_sha256="4" * 64, candidate_config_sha256="5" * 64,
        extraction_prompt_sha256={"distill": "6" * 64},
        judge_prompt_sha256={p: judge_template_sha256() for p in ("codex", "claude")},
        judge_identities={p: JudgeIdentity(cli_version="fake-1", model="fake")
                          for p in ("codex", "claude")}, sampling_seed=17,
    )
    store = RunStore(tmp_path / "measurement")
    annotations = AnnotationStore(tmp_path / "review.db")
    coordinator = MeasurementCoordinator(store, annotations, batch_size=2)
    return suite, pins, extractor, store, annotations, coordinator


async def execute(setup_run, *, codex=None, claude=None, **kwargs):
    suite, pins, extractor, _, _, coordinator = setup_run
    return await coordinator.run(suite, pins, extractor=extractor, ontology=load_ontology(),
                                 codex=codex or FakeJudge("codex"),
                                 claude=claude or FakeJudge("claude"), **kwargs)


@pytest.mark.asyncio
async def test_current_pipeline_run_judges_matches_scores_and_pins_annotations(setup_run):
    suite, pins, _, store, annotations, _ = setup_run
    codex, claude = FakeJudge("codex"), FakeJudge("claude")
    result = await execute(setup_run, codex=codex, claude=claude)
    assert result.status == "complete"
    assert result.scores["micro"]["propositions"]["precision"] == 1
    assert result.scores["micro"]["tags"]["recall"] == 1
    assert result.scores["micro"]["label"] == "judge agreement, unanchored"
    assert store.load(result.run_id).inputs == pins
    history = await annotations.history(run_id=result.run_id)
    assert len(history) == sum(len(p.items) for p in codex.calls + claude.calls)
    assert {a.author_identity for a in history} == {"codex/fake/fake-1", "claude/fake/fake-1"}
    assert all(a.reason and a.source_sha256 == suite.documents[0].source.sha256 for a in history)
    kinds = {i.kind for p in codex.calls for i in p.items}
    assert kinds == {"prediction", "gold", "omission", "tag"}
    assert all(p.predictions for p in claude.calls)
    assert result.sample["denominator"] == sum(len(p.items) for p in codex.calls)
    assert result.artifacts and result.annotation_ids
    # Finished runs are immutable and do no work on retry.
    again = await execute(setup_run, codex=codex, claude=claude)
    assert again == result
    assert len(await annotations.history(run_id=result.run_id)) == len(history)


@pytest.mark.asyncio
async def test_cancelled_claude_resumes_only_missing_items_and_input_change_forks(setup_run):
    codex, partial = FakeJudge("codex"), FakeJudge("claude", error="cancelled", partial=True)
    first = await execute(setup_run, codex=codex, claude=partial)
    assert first.status == "incomplete" and first.errors == {"claude": "cancelled"}
    completed = {j.item_id for p in partial.calls for j in [
        JudgeVerdict(item_id=p.items[0].item_id, verdict="correct", reason="test", omission=None,
                     concept_ids=())]}
    resumed = FakeJudge("claude")
    second = await execute(setup_run, codex=codex, claude=resumed)
    assert second.run_id == first.run_id and second.status == "complete"
    assert not completed.intersection(i.item_id for p in resumed.calls for i in p.items)
    old_count = len(codex.calls)
    changed = list(setup_run)
    changed[1] = changed[1].model_copy(update={"sampling_seed": 99})
    third = await execute(changed, codex=codex)
    assert third.run_id != first.run_id and len(codex.calls) > old_count


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["quota", "subscription-auth-required", "timeout"])
async def test_unavailable_judge_and_total_extraction_miss_remain_truthful(setup_run, error):
    suite, _, extractor, store, annotations, _ = setup_run
    path = next(iter(extractor.paths.values()))
    path.write_text('{"units": []}')
    failing = FakeJudge("codex", error=error)
    first = await execute(setup_run, codex=failing)
    assert first.status == "incomplete" and first.errors == {"codex": error}
    assert store.load(first.run_id) == first
    assert not await annotations.history(run_id=first.run_id)
    assert first.scores["micro"]["propositions"]["fn"] == len(suite.documents[0].propositions)
    assert first.scores["micro"]["propositions"]["recall"] is None
    recovered = FakeJudge("codex")
    second = await execute(setup_run, codex=recovered)
    assert second.run_id == first.run_id and second.status == "complete"
    assert second.scores["micro"]["propositions"]["recall"] == 0
    assert second.scores["micro"]["propositions"]["precision"] is None
    assert any(i.kind == "omission" for p in recovered.calls for i in p.items)
    assert all(not p.predictions for p in failing.calls)


@pytest.mark.asyncio
async def test_changed_extraction_bytes_create_new_run(setup_run):
    first = await execute(setup_run)
    path = next(iter(setup_run[2].paths.values()))
    path.write_text('{"units": []}')
    second = await execute(setup_run)
    assert first.run_id != second.run_id


@pytest.mark.asyncio
async def test_disagreements_block_ready_scores_without_erasing_judgments(setup_run):
    result = await execute(setup_run, claude=FakeJudge("claude", uncertain=True))
    assert result.status == "adjudication"
    assert result.adjudication
    assert result.scores["readiness"] == "incomplete"
    assert all(a["codex"] and a["claude"] for a in result.adjudication)


@pytest.mark.asyncio
async def test_cancel_before_extraction_is_checkpointed(setup_run):
    cancelled = threading.Event()
    cancelled.set()
    result = await execute(setup_run, cancelled=cancelled)
    assert result.status == "incomplete" and result.errors == {"run": "cancelled"}
    assert (await execute(setup_run)).run_id == result.run_id


@pytest.mark.asyncio
async def test_stale_pins_are_refused_before_judging(setup_run):
    altered = list(setup_run)
    altered[1] = altered[1].model_copy(update={"gold_sha256": "f" * 64})
    judge = FakeJudge("codex")
    with pytest.raises(ValueError, match="pins"):
        await execute(altered, codex=judge)
    assert not judge.calls


def test_cli_runs_frozen_current_pipeline_outputs_and_resumes(setup_run, tmp_path, monkeypatch):
    from click.testing import CliRunner
    from folio_insights.measurement import cli

    suite, pins, extractor, _, _, _ = setup_run
    gold_file, inputs_file, manifest = (tmp_path / name for name in ("gold.json", "inputs.json", "manifest.json"))
    gold_file.write_text(suite.model_dump_json())
    inputs_file.write_text(pins.model_dump_json())
    manifest.write_text(json.dumps({sid: str(path) for sid, path in extractor.paths.items()}))
    codex, claude = FakeJudge("codex"), FakeJudge("claude")
    monkeypatch.setattr(cli, "CodexJudge", lambda **kwargs: codex)
    monkeypatch.setattr(cli, "ClaudeJudge", lambda **kwargs: claude)
    args = ["run", "--inputs", str(inputs_file), "--extractions", str(manifest),
            "--gold", str(gold_file), "--output", str(tmp_path / "cli-output")]
    first = CliRunner().invoke(cli.measurement_group, args)
    assert first.exit_code == 0, first.output
    report = json.loads(first.output)
    assert report["status"] == "complete" and report["scores"]["micro"]["propositions"]["precision"] == 1
    assert "adjudication" not in report
    calls = len(codex.calls), len(claude.calls)
    second = CliRunner().invoke(cli.measurement_group, args)
    assert second.exit_code == 0 and json.loads(second.output) == report
    assert (len(codex.calls), len(claude.calls)) == calls


@pytest.mark.asyncio
async def test_crash_between_annotation_append_and_checkpoint_is_idempotent(setup_run, monkeypatch):
    annotations = setup_run[4]
    append = annotations.append
    crashed = False

    async def interrupt_after_append(*args, **kwargs):
        nonlocal crashed
        record = await append(*args, **kwargs)
        if not crashed:
            crashed = True
            raise InterruptedError
        return record

    monkeypatch.setattr(annotations, "append", interrupt_after_append)
    first = await execute(setup_run)
    assert first.errors == {"run": "cancelled"}
    second = await execute(setup_run)
    assert second.run_id == first.run_id and second.status == "complete"
    history = await annotations.history(run_id=second.run_id)
    assert len(history) == len(second.annotation_ids) == len(set(a.idempotency_key for a in history))
    assert all(result.judge_identity_sha256 and result.prompt_sha256
               for result in setup_run[3].results(second.run_id))


@pytest.mark.asyncio
async def test_unknown_concept_results_cannot_become_completed_on_retry(setup_run):
    class UnknownConceptJudge(FakeJudge):
        def judge(self, packet, **kwargs):
            result = super().judge(packet, **kwargs)
            return result.model_copy(update={"unresolved_concept_ids": ("unknown",)})

    judge = UnknownConceptJudge("codex")
    first = await execute(setup_run, codex=judge)
    second = await execute(setup_run, codex=judge)
    assert first.run_id == second.run_id
    assert second.status == "incomplete"
    assert second.errors == {"codex": "unresolved-concept-selections"}
    assert not setup_run[3].judgments(second.run_id, "codex")
    assert (await execute(setup_run)).status == "complete"


@pytest.mark.asyncio
async def test_authored_semantic_edges_are_pinned_to_extraction_and_survive_judge_readiness(setup_run):
    from folio_insights.measurement.matching import EquivalenceEdge, freeze_equivalences

    suite, _, extractor, _, _, _ = setup_run
    path = next(iter(extractor.paths.values()))
    data = json.loads(path.read_text())
    data["units"][0]["text"] = "An independently reviewed paraphrase of the rule."
    path.write_text(json.dumps(data))
    extractor.sha256
    row = await extractor.extract(suite.documents[0].source)
    edge = EquivalenceEdge(source_id=row.source_id, prediction_id=row.propositions[0].item_id,
                           gold_id=suite.documents[0].propositions[0].item_id,
                           verdict="equivalent", author="reviewer", reason="Same atomic meaning.")
    edges = freeze_equivalences(suite, (row,), (edge,))
    first = await execute(setup_run, codex=FakeJudge("codex", error="quota"), equivalences=edges)
    assert first.status == "incomplete"
    second = await execute(setup_run, equivalences=edges)
    assert second.run_id == first.run_id and second.status == "complete"
    assert second.scores["micro"]["propositions"]["precision"] == 1
