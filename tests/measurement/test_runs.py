"""Checkpointed extraction, independent judges and exhaustive omission coverage."""
from __future__ import annotations

import json
import threading
import unicodedata

import pytest

from folio_insights.measurement.annotations import AnnotationStore
from folio_insights.measurement.gold import load_gold, load_ontology
from folio_insights.measurement.judges import JudgeResult, JudgeSpan, JudgeVerdict, ProposedOmission
from folio_insights.measurement.matching import MATCHER_POLICY, content_digest
from folio_insights.measurement.runs import (
    MeasurementCoordinator, PipelineExtraction, build_packet, claude_sample, judge_template_sha256,
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


class OmissionJudge(FakeJudge):
    def __init__(self, provider, document, *, new=False):
        super().__init__(provider)
        self.document, self.new = document, new

    def judge(self, packet, **kwargs):
        result = super().judge(packet, **kwargs)
        gold = {p.item_id: p for p in self.document.propositions}
        judgments = []
        for item, judgment in zip(packet.items, result.judgments, strict=True):
            if (item.kind == "gold" and not self.new) or (item.kind == "omission" and self.new):
                span = (item.span if self.new else
                        JudgeSpan(**gold[item.proposition_id].span.model_dump()))
                judgment = judgment.model_copy(update={"omission": ProposedOmission(
                    source_id=item.source_id, span=span)})
            judgments.append(judgment)
        return result.model_copy(update={"judgments": tuple(judgments)})


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
@pytest.mark.parametrize("canonical_providers", [("codex", "claude"), ("codex",)])
async def test_canonical_selections_for_accepted_concepts_complete(setup_run, canonical_providers):
    ontology = load_ontology()

    class CanonicalJudge(FakeJudge):
        def judge(self, packet, **kwargs):
            result = super().judge(packet, **kwargs)
            catalog = {c.concept_id: c for c in packet.catalog}
            canonical = {c.label: c.concept_id for c in packet.catalog if c.label == c.branch}
            return result.model_copy(update={"judgments": tuple(j.model_copy(update={
                "concept_ids": tuple(canonical[ontology.resolve(
                    catalog[c].label, catalog[c].branch).label] for c in j.concept_ids),
            }) for j in result.judgments)})

    judges = {provider: CanonicalJudge(provider) for provider in canonical_providers}
    result = await execute(setup_run, **judges)
    assert not result.adjudication
    assert result.status == "complete"
    assert result.scores["readiness"] == "ready"
    calls = {provider: len(judge.calls) for provider, judge in judges.items()}
    assert await execute(setup_run, **judges) == result
    assert calls == {provider: len(judge.calls) for provider, judge in judges.items()}


@pytest.mark.asyncio
async def test_new_concept_aliases_queue_additions_without_false_disagreement(setup_run):
    ontology = load_ontology()
    suite, pins, extractor, _, _, _ = setup_run
    doc = suite.documents[0]
    extractor.sha256
    packet = build_packet(suite, (await extractor.extract(doc.source),), ontology)
    sample = claude_sample(packet, FakeJudge("codex").judge(packet).judgments, seed=pins.sampling_seed)
    target_id = next(i.proposition_id for i in packet.items
                     if i.kind == "gold" and i.item_id in sample.item_ids)
    target = next(p for p in doc.propositions if p.item_id == target_id)
    existing = {ontology.resolve(t.label, t.branch).iri for t in target.tags}
    new_tag = next(t for p in doc.propositions for t in p.tags
                   if t.label != t.branch and ontology.resolve(t.label, t.branch).iri not in existing)

    class AdditionJudge(FakeJudge):
        def judge(self, packet, **kwargs):
            result = super().judge(packet, **kwargs)
            label, branch = ((new_tag.label, new_tag.label) if self.provider == "codex"
                             else (new_tag.label, new_tag.branch))
            selection = next(c.concept_id for c in packet.catalog
                             if (c.label, c.branch) == (label, branch))
            return result.model_copy(update={"judgments": tuple(
                j.model_copy(update={"concept_ids": (selection,)})
                if i.kind == "gold" and i.proposition_id == target.item_id else j
                for i, j in zip(packet.items, result.judgments, strict=True))})

    result = await execute(setup_run, **{
        provider: AdditionJudge(provider) for provider in ("codex", "claude")})
    additions = [a for a in result.adjudication if "proposed-addition" in a["reasons"]]
    assert {a["provider"] for a in additions} == {"codex", "claude"}
    assert not any("concept-difference" in a["reasons"] for a in result.adjudication)
    assert result.status == "adjudication"
    assert result.scores["readiness"] == "incomplete"
    assert len({tuple(a["judgment"]["concept_ids"]) for a in additions}) == 2


@pytest.mark.asyncio
async def test_cancelled_claude_retries_failed_batch_and_input_change_forks(setup_run):
    codex, partial = FakeJudge("codex"), FakeJudge("claude", error="cancelled", partial=True)
    first = await execute(setup_run, codex=codex, claude=partial)
    assert first.status == "incomplete" and first.errors == {"claude": "cancelled"}
    completed = {j.item_id for p in partial.calls for j in [
        JudgeVerdict(item_id=p.items[0].item_id, verdict="correct", reason="test", omission=None,
                     concept_ids=())]}
    resumed = FakeJudge("claude")
    second = await execute(setup_run, codex=codex, claude=resumed)
    assert second.run_id == first.run_id and second.status == "complete"
    assert completed <= {i.item_id for p in resumed.calls for i in p.items}
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
async def test_agreed_existing_gold_omissions_complete_empty_extraction_with_zero_recall(setup_run):
    suite, _, extractor, store, _, _ = setup_run
    doc = suite.documents[0]
    next(iter(extractor.paths.values())).write_text('{"units": []}')
    codex, claude = (OmissionJudge(provider, doc) for provider in ("codex", "claude"))
    result = await execute(setup_run, codex=codex, claude=claude)
    counts = result.scores["micro"]
    assert counts["propositions"]["fn"] == len(doc.propositions)
    assert counts["propositions"]["recall"] == 0
    assert counts["propositions"]["tp"] == counts["propositions"]["fp"] == 0
    assert counts["propositions"]["precision"] is None
    ontology = load_ontology()
    assert counts["tags"]["fn"] == sum(len({tag.iri for t in p.tags
        if MATCHER_POLICY.classify_tag(tag := ontology.resolve(t.label, t.branch), ontology) == "meaning"})
        for p in doc.propositions)
    assert counts["tags"]["recall"] == 0
    assert result.status == "complete" and result.scores["readiness"] == "ready"
    assert not result.adjudication
    assert store.load(result.run_id) == result
    calls = len(codex.calls), len(claude.calls)
    assert await execute(setup_run, codex=codex, claude=claude) == result
    assert (len(codex.calls), len(claude.calls)) == calls


@pytest.mark.asyncio
async def test_new_source_omission_still_requires_gold_addition_adjudication(setup_run):
    doc = setup_run[0].documents[0]
    result = await execute(setup_run, **{
        provider: OmissionJudge(provider, doc, new=True) for provider in ("codex", "claude")})
    assert result.status == "adjudication"
    additions = [a for a in result.adjudication if "proposed-addition" in a["reasons"]]
    assert {a["provider"] for a in additions} == {"codex", "claude"}
    assert all(a["judgment"]["omission"]["span"] == {"start": 0, "end": len(doc.source.text)}
               for a in additions)
    assert result.scores["readiness"] == "incomplete"


@pytest.mark.asyncio
async def test_disagreement_about_existing_gold_omission_requires_adjudication(setup_run):
    doc = setup_run[0].documents[0]
    next(iter(setup_run[2].paths.values())).write_text('{"units": []}')
    result = await execute(setup_run, codex=OmissionJudge("codex", doc))
    assert result.status == "adjudication"
    assert any("omission-difference" in a["reasons"] and a["codex"]["omission"]
               and a["claude"]["omission"] is None for a in result.adjudication)
    assert not any("proposed-addition" in a["reasons"] for a in result.adjudication)
    assert result.scores["micro"]["propositions"]["fn"] == len(doc.propositions)
    assert result.scores["micro"]["propositions"]["recall"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("policy_case,expected", [
    ("exact", "complete"), ("nfc", "complete"), ("equivalent", "complete"),
    ("different-text", "adjudication"), ("different-kind", "adjudication"),
    ("different", "adjudication"), ("uncertain", "adjudication"),
])
async def test_prediction_omissions_follow_u2_matching_policy(setup_run, policy_case, expected):
    from folio_insights.measurement.matching import EquivalenceEdge, freeze_equivalences

    suite, pins, extractor, _, _, _ = setup_run
    doc = suite.documents[0]
    prop = doc.propositions[0]
    if policy_case == "nfc":
        prop = prop.model_copy(update={"text": "Café contract rule."})
        doc = doc.model_copy(update={"propositions": (prop, *doc.propositions[1:])})
        suite = suite.model_copy(update={"documents": (doc,)})
        setup_run = (suite, pins.model_copy(update={
            "gold_sha256": content_digest(suite.model_dump(mode="json"))}), *setup_run[2:])
    path = next(iter(extractor.paths.values()))
    data = json.loads(path.read_text())
    unit = data["units"][0]
    if policy_case in {"different-text", "equivalent"}:
        unit["text"] = "An independently reviewed paraphrase of the rule."
    if policy_case == "different-kind":
        unit["proposition_kind"] = "fact"
    if policy_case == "nfc":
        unit["text"] = unicodedata.normalize("NFD", prop.text)
    path.write_text(json.dumps(data))
    equivalences = None
    if policy_case in {"equivalent", "different", "uncertain"}:
        extractor.sha256
        row = await extractor.extract(doc.source)
        edge = EquivalenceEdge(source_id=row.source_id, prediction_id=unit["id"],
                               gold_id=prop.item_id, verdict=policy_case,
                               author="reviewer", reason="Authored atomic equivalence assessment.")
        equivalences = freeze_equivalences(suite, (row,), (edge,))

    class PredictionOmissionJudge(FakeJudge):
        def judge(self, packet, **kwargs):
            result = super().judge(packet, **kwargs)
            return result.model_copy(update={"judgments": tuple(
                j.model_copy(update={"omission": ProposedOmission(source_id=i.source_id, span=i.span)})
                if i.kind == "prediction" and i.proposition_id == prop.item_id else j
                for i, j in zip(packet.items, result.judgments, strict=True))})

    result = await execute(setup_run, equivalences=equivalences, **{
        provider: PredictionOmissionJudge(provider) for provider in ("codex", "claude")})
    assert result.status == expected
    assert bool(result.adjudication) == (expected == "adjudication")


@pytest.mark.asyncio
@pytest.mark.parametrize("ambiguous", [False, True])
async def test_source_omission_requires_unique_atomic_gold_match(setup_run, ambiguous):
    suite, pins, extractor, _, _, _ = setup_run
    doc = suite.documents[0]
    prop = doc.propositions[0]
    prop = prop.model_copy(update={"text": prop.span.source_slice(doc.source.text)})
    props = (prop, *doc.propositions[1:])
    if ambiguous:
        props = (*props, prop.model_copy(update={"item_id": "ambiguous-rule", "kind": "fact"}))
    doc = doc.model_copy(update={"propositions": props})
    suite = suite.model_copy(update={"documents": (doc,)})
    setup_run = (suite, pins.model_copy(update={
        "gold_sha256": content_digest(suite.model_dump(mode="json"))}), *setup_run[2:])
    next(iter(extractor.paths.values())).write_text('{"units": []}')

    class SourceOmissionJudge(FakeJudge):
        def judge(self, packet, **kwargs):
            result = super().judge(packet, **kwargs)
            return result.model_copy(update={"judgments": tuple(
                j.model_copy(update={"omission": ProposedOmission(
                    source_id=i.source_id, span=JudgeSpan(**prop.span.model_dump()))})
                if i.kind == "omission" else j
                for i, j in zip(packet.items, result.judgments, strict=True))})

    result = await execute(setup_run, **{
        provider: SourceOmissionJudge(provider) for provider in ("codex", "claude")})
    assert result.status == ("adjudication" if ambiguous else "complete")
    assert bool(result.adjudication) == ambiguous
    assert result.scores["micro"]["propositions"]["fn"] == len(props)
    assert result.scores["micro"]["propositions"]["recall"] == (None if ambiguous else 0)


@pytest.mark.asyncio
async def test_blank_source_omission_requires_adjudication_instead_of_crashing(setup_run):
    doc = setup_run[0].documents[0]
    start = doc.source.text.index(" ")

    class BlankOmissionJudge(FakeJudge):
        def judge(self, packet, **kwargs):
            result = super().judge(packet, **kwargs)
            return result.model_copy(update={"judgments": tuple(
                j.model_copy(update={"omission": ProposedOmission(
                    source_id=i.source_id, span=JudgeSpan(start=start, end=start + 1))})
                if i.kind == "omission" else j
                for i, j in zip(packet.items, result.judgments, strict=True))})

    result = await execute(setup_run, **{
        provider: BlankOmissionJudge(provider) for provider in ("codex", "claude")})
    assert result.status == "adjudication"
    assert result.scores["readiness"] == "incomplete"
    assert any("proposed-addition" in a["reasons"] for a in result.adjudication)


@pytest.mark.asyncio
async def test_disagreements_block_ready_scores_without_erasing_judgments(setup_run):
    result = await execute(setup_run, claude=FakeJudge("claude", uncertain=True))
    assert result.status == "adjudication"
    assert result.adjudication
    assert result.scores["readiness"] == "incomplete"
    assert all(a["codex"] and a["claude"] for a in result.adjudication)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["gold", "prediction", "tag"])
@pytest.mark.parametrize("verdicts", [("wrong", "wrong"), ("wrong", "correct"), ("correct", "wrong")])
async def test_negative_judgments_contradicting_accepted_items_block_readiness(setup_run, kind, verdicts):
    class NegativeJudge(FakeJudge):
        def judge(self, packet, **kwargs):
            result = super().judge(packet, **kwargs)
            return result.model_copy(update={"judgments": tuple(
                judgment.model_copy(update={"verdict": verdicts[self.provider == "claude"]})
                if item.kind == kind else judgment
                for item, judgment in zip(packet.items, result.judgments, strict=True))})

    codex, claude = NegativeJudge("codex"), NegativeJudge("claude")
    result = await execute(setup_run, codex=codex, claude=claude)
    assert result.status == "adjudication"
    pending = {item["item_id"]: item for item in result.adjudication}
    for provider, judge, verdict in zip(("codex", "claude"), (codex, claude), verdicts, strict=True):
        if verdict == "wrong":
            for item in (item for packet in judge.calls for item in packet.items if item.kind == kind):
                assert "contradicts-accepted" in pending[item.item_id]["reasons"]
                assert pending[item.item_id][provider]["verdict"] == "wrong"
    assert result.scores["readiness"] == "incomplete"
    for row in [result.scores["micro"], *result.scores["sources"].values(), *result.scores["genres"].values()]:
        assert row["target_met"] is None
        assert row["propositions"]["precision"] is None
        assert row["tags"]["precision"] is None
    assert setup_run[3].load(result.run_id) == result
    # Retrying retains the evidence and does not let agreement erase a challenge.
    assert await execute(setup_run) == result


@pytest.mark.asyncio
async def test_cancelled_retry_of_completed_run_does_not_write_or_change_scores(setup_run, monkeypatch):
    codex, claude = FakeJudge("codex"), FakeJudge("claude")
    result = await execute(setup_run, codex=codex, claude=claude)
    calls = len(codex.calls), len(claude.calls)
    store = setup_run[3]
    writes = []
    save = store.save

    def record_save(report):
        writes.append(report)
        return save(report)

    monkeypatch.setattr(store, "save", record_save)
    cancelled = threading.Event()
    cancelled.set()
    again = await execute(setup_run, codex=codex, claude=claude, cancelled=cancelled)
    assert again.status == "complete"
    assert again == result == store.load(result.run_id)
    assert (len(codex.calls), len(claude.calls)) == calls
    assert not writes


@pytest.mark.asyncio
async def test_cancelled_retry_refreshes_stale_ready_scores_and_contradicting_judgments(setup_run):
    codex = FakeJudge("codex")
    original = await execute(setup_run, codex=codex)
    item_id = next(item.item_id for packet in codex.calls for item in packet.items if item.kind == "gold")
    store = setup_run[3]
    attempt = next(result for result in store.results(original.run_id, provider="codex")
                   if any(j.item_id == item_id for j in result.judgments))
    changed = attempt.model_copy(update={"judgments": tuple(
        j.model_copy(update={"verdict": "wrong"}) if j.item_id == item_id else j
        for j in attempt.judgments)})
    # Reproduce a pre-fix complete checkpoint backed by negative judgments.
    store.record_result(original.model_copy(update={"stage": "codex"}), changed, keep_judgments=True)
    cancelled = threading.Event()
    cancelled.set()
    result = await execute(setup_run, cancelled=cancelled)
    assert result.status == "incomplete" and result.errors == {"run": "cancelled"}
    assert result.scores["micro"]["target_met"] is None
    assert result.scores["readiness"] == "incomplete"
    assert any(a["item_id"] == item_id and "contradicts-accepted" in a["reasons"]
               for a in result.adjudication)
    assert store.load(result.run_id) == result
    assert (await execute(setup_run)).status == "adjudication"


@pytest.mark.asyncio
async def test_gold_correction_requires_new_revision_and_preserves_original_run(setup_run):
    suite, pins, _, store, _, _ = setup_run
    original = await execute(setup_run)
    doc = suite.documents[0]
    rejected = doc.propositions[0].item_id
    corrected = suite.model_copy(update={"documents": (doc.model_copy(update={
        "propositions": tuple(p.model_copy(update={
            "links": tuple(link for link in p.links if link.target_id != rejected)})
            for p in doc.propositions if p.item_id != rejected)}),)})
    changed = list(setup_run)
    changed[0] = corrected
    changed[1] = pins.model_copy(update={"gold_sha256": content_digest(corrected.model_dump(mode="json"))})
    with pytest.raises(ValueError, match="new gold revision"):
        await execute(changed)
    corrected = corrected.model_copy(update={"gold_revision": suite.gold_revision + "-corrected"})
    changed[0] = corrected
    changed[1] = changed[1].model_copy(update={
        "gold_revision": corrected.gold_revision,
        "gold_sha256": content_digest(corrected.model_dump(mode="json"))})
    result = await execute(changed)
    assert result.status == "complete" and result.run_id != original.run_id
    assert result.scores["gold_revision"] == corrected.gold_revision
    assert result.scores["micro"]["propositions"]["fp"] == 1
    assert result.scores["micro"]["propositions"]["tp"] == len(doc.propositions) - 1
    assert result.scores["micro"]["target_met"] is False
    assert store.load(original.run_id) == original
    assert store.artifact(original.artifacts["gold"]) == suite.model_dump(mode="json")
    assert store.artifact(result.artifacts["gold"]) == corrected.model_dump(mode="json")


@pytest.mark.asyncio
async def test_unresolved_prediction_tag_stays_incomplete_instead_of_crashing(setup_run):
    path = next(iter(setup_run[2].paths.values()))
    data = json.loads(path.read_text())
    data["units"][0]["folio_tags"][0]["label"] = "Unresolved fixture concept"
    path.write_text(json.dumps(data))
    result = await execute(setup_run)
    assert result.status == "incomplete"
    assert result.scores["micro"]["target_met"] is None
    assert any("unresolved tag selections" in reason for reason in result.scores["reasons"])
    assert result.errors == {"codex": "unresolved-concept-selections"}
    assert not setup_run[3].judgments(result.run_id, "codex")
    retry = await execute(setup_run)
    assert retry.run_id == result.run_id and retry.status == "incomplete"
    assert retry.errors == result.errors


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
@pytest.mark.parametrize("stale_checkpoint", [False, True])
@pytest.mark.parametrize("error", ["timeout", None])
async def test_failed_final_batch_persisted_before_checkpoint_is_retried(
    setup_run, monkeypatch, stale_checkpoint, error,
):
    class FailedFinalJudge(FakeJudge):
        def judge(self, packet, **kwargs):
            result = super().judge(packet, **kwargs)
            if any(item.kind == "omission" for item in packet.items):
                return result.model_copy(update={"status": "incomplete", "error": error})
            return result

    store = setup_run[3]
    record_result = store.record_result

    def interrupt_after_failed_result(*args, **kwargs):
        persisted = record_result(*args, **kwargs)
        if args[1].status == "incomplete":
            raise InterruptedError
        return persisted

    monkeypatch.setattr(store, "record_result", interrupt_after_failed_result)
    judge = FailedFinalJudge("codex")
    first = await execute(setup_run, codex=judge)
    assert first.status == "incomplete"
    failed_ids = {item.item_id for item in judge.calls[-1].items}
    successful_ids = {item.item_id for packet in judge.calls[:-1] for item in packet.items}
    monkeypatch.setattr(store, "record_result", record_result)
    if stale_checkpoint:
        # Simulate an old split write, even one incorrectly marked complete.
        preceding = content_digest(store.results(first.run_id)[-2].model_dump(mode="json"))
        store.save(first.model_copy(update={
            "status": "complete", "errors": {}, "missing_item_ids": {"codex": ()},
            "artifacts": {**first.artifacts, "codex-last": preceding}}))
    retry = FailedFinalJudge("codex")
    second = await execute(setup_run, codex=retry)
    assert second.status == "incomplete", "a durable failed batch must never become complete"
    assert {item.item_id for packet in retry.calls for item in packet.items} == failed_ids
    assert not successful_ids.intersection(item.item_id for packet in retry.calls for item in packet.items)
    recovered = FakeJudge("codex")
    assert (await execute(setup_run, codex=recovered)).status == "complete"
    assert {item.item_id for packet in recovered.calls for item in packet.items} == failed_ids
    # Reusing an earlier receipt must still make it the newest attempt, even
    # after a successful retry of the same batch and another stale checkpoint.
    failed = next(result for result in store.results(first.run_id) if result.status == "incomplete")
    complete = store.load(first.run_id)
    store.record_result(complete.model_copy(update={"stage": "codex", "status": "incomplete"}),
                        failed, keep_judgments=True)
    store.save(complete)
    retry = FailedFinalJudge("codex")
    assert (await execute(setup_run, codex=retry)).status == "incomplete"
    assert {item.item_id for packet in retry.calls for item in packet.items} == failed_ids
    assert (await execute(setup_run)).status == "complete"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["codex", "claude"])
@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("boundary", [
    "before-persist", "after-persist", "after-checkpoint-write", "after-checkpoint",
])
async def test_batch_interruptions_are_atomic_and_successes_are_not_rejudged(
    setup_run, monkeypatch, provider, failed, boundary,
):
    store = setup_run[3]
    setup_run[5].batch_size = 1

    class InterruptJudge(FakeJudge):
        def judge(self, packet, **kwargs):
            result = super().judge(packet, **kwargs)
            if failed and len(self.calls) == 2:
                return result.model_copy(update={"status": "incomplete", "error": "timeout"})
            return result

    judge = InterruptJudge(provider)
    record_result, save_checkpoint = store.record_result, store._save
    target = None
    inside_target = False

    def interrupt_checkpoint(db, report):
        if inside_target and boundary == "after-persist":
            # The receipt, attempt and judgments have been inserted in this
            # transaction; interruption must roll all three back.
            raise InterruptedError
        save_checkpoint(db, report)
        if inside_target and boundary == "after-checkpoint-write":
            raise InterruptedError

    def interrupt_result(report, result, **kwargs):
        nonlocal target, inside_target
        inside_target = result.provider == provider and len(judge.calls) == 2
        if inside_target:
            target = result
            if boundary == "before-persist":
                raise InterruptedError
        try:
            persisted = record_result(report, result, **kwargs)
            if inside_target and boundary == "after-checkpoint":
                raise InterruptedError
            return persisted
        finally:
            inside_target = False

    monkeypatch.setattr(store, "_save", interrupt_checkpoint)
    monkeypatch.setattr(store, "record_result", interrupt_result)
    first = await execute(setup_run, **{provider: judge})
    assert first.status == "incomplete" and target is not None
    digest = content_digest(target.model_dump(mode="json"))
    with store._db() as db:
        artifact = db.execute("SELECT 1 FROM artifacts WHERE sha256=?", (digest,)).fetchone()
        attempt = db.execute("SELECT 1 FROM attempts WHERE sha256=?", (digest,)).fetchone()
    committed = boundary == "after-checkpoint"
    assert bool(artifact) == bool(attempt) == committed
    item_ids = {j.item_id for j in target.judgments}
    assert bool(item_ids & {j.item_id for j in store.judgments(first.run_id, provider)}) == committed
    if committed:
        assert first.artifacts[f"{provider}-last"] == digest
    monkeypatch.setattr(store, "record_result", record_result)
    monkeypatch.setattr(store, "_save", save_checkpoint)
    retry = FakeJudge(provider)
    second = await execute(setup_run, **{provider: retry})
    assert second.run_id == first.run_id and second.status == "complete"
    retried_ids = {item.item_id for packet in retry.calls for item in packet.items}
    assert bool(item_ids & retried_ids) == (failed or not committed)
    assert not {item.item_id for item in judge.calls[0].items} & retried_ids


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
async def test_changed_verdict_from_failed_batch_retry_retains_both_annotations(setup_run):
    first = await execute(setup_run, codex=FakeJudge("codex", partial=True, error="timeout", uncertain=True))
    history = await setup_run[4].history(run_id=first.run_id)
    assert len(history) == 1 and history[0].verdict == "uncertain"
    item_id = history[0].item_id
    second = await execute(setup_run)
    assert second.status == "complete"
    history = await setup_run[4].history(run_id=first.run_id)
    revisions = [a for a in history
                 if a.item_id == item_id and a.author_identity.startswith("codex/")]
    assert [a.verdict for a in revisions] == ["uncertain", "correct"]
    assert all(a.annotation_id in second.annotation_links.values() for a in revisions)
    assert len({a.idempotency_key for a in revisions}) == 2
    assert next(j for j in setup_run[3].judgments(first.run_id, "codex") if j.item_id == item_id).verdict == "correct"
    assert await execute(setup_run) == second
    assert await setup_run[4].history(run_id=first.run_id) == history


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
