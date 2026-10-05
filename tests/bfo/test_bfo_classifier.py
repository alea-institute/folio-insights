"""Phase 9 U7 (R10, KTD11) — rule-first BFO typing, coverage and reporting.

Synthetic inputs only (FOLIO branch IRIs and made-up tag IRIs); the LLM is a
fake, or the Phase 10 port with a fake task LLM.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from rdflib import OWL, RDF, RDFS, URIRef

from folio_insights.bfo.classifier import (
    BfoClassifier,
    BfoInput,
    BfoLLMChoice,
    BfoUnclassifiable,
    FolioTag,
    PortBfoLLM,
)
from folio_insights.bfo.report import (
    BfoRecord,
    build_report,
    corpus_report,
    record_assignment,
)
from folio_insights.bfo.spine import (
    BRANCH_BY_IRI,
    DEFAULT_CATEGORY_BY_SPEECH_ACT,
    FOLIO_BRANCH_SPINE,
)
from folio_insights.cli import cli
from folio_insights.shards import SimpleAssertionShard
from folio_insights.shards.envelope import ShardEnvelope
from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.projection import shard_triples
from folio_insights.vocab import FI_PREFIX, load_graph
from folio_insights.vocab._constants import BFO_CATEGORY_SPINE_CLASS

from tests.shards.conftest import _sample_shard
from tests.storage.conftest import shard


class FakeLLM:
    def __init__(self, category: str | None, confidence: float = 0.9) -> None:
        self.choice = BfoLLMChoice(category=category, confidence=confidence)  # type: ignore[arg-type]
        self.calls = 0

    def classify(self, item):  # noqa: ANN001, ANN201
        self.calls += 1
        return self.choice


_SYN = "https://folio.openlegalstandard.org/Rsyn"


class SyntheticFolio:
    """Synthetic FOLIO ancestry: leaf ``Rsyn<b>x<n>`` -> ``Rsynmid<b>`` -> the
    top-level branch ``b``. Inputs only ever carry leaf IRIs; the classifier
    has to climb to find the branch (review P2-9)."""

    def parents(self, iri: str):  # noqa: ANN201
        local = iri.removeprefix(_SYN)
        if local.startswith("mid"):
            return (FOLIO_BRANCH_SPINE[int(local[3:])].iri,)
        if "x" in local and local.split("x")[0].isdigit():
            return (f"{_SYN}mid{local.split('x')[0]}",)
        return ()


RESOLVER = SyntheticFolio()


def _leaf(branch, n: int = 0) -> str:  # noqa: ANN001
    return f"{_SYN}{FOLIO_BRANCH_SPINE.index(branch)}x{n}"


def _tag(branch, n: int = 0, *, verified: bool = True, **kw) -> FolioTag:  # noqa: ANN001, ANN003
    return FolioTag(iri=_leaf(branch, n), verified=verified, **kw)


# ── the table ─────────────────────────────────────────────────────────────


def test_table_covers_every_folio_top_level_branch() -> None:
    """Enumerates folio-python's top-level branches; each must be mapped."""
    from folio.graph import FOLIO_TYPE_IRIS

    expected = {f"https://folio.openlegalstandard.org/{local}" for local in FOLIO_TYPE_IRIS.values()}
    labels = {t.value for t in FOLIO_TYPE_IRIS}
    assert set(BRANCH_BY_IRI) == expected
    assert {b.label for b in FOLIO_BRANCH_SPINE} == labels
    assert len(FOLIO_BRANCH_SPINE) == len(FOLIO_TYPE_IRIS) == 24


def test_table_is_curated_against_the_spine() -> None:
    """Every branch's spine class is a spine class, and it sits under the class
    its envelope category projects to (so the finer typing never contradicts
    the projection)."""
    g = load_graph(include_bfo_mapping=True)
    for b in FOLIO_BRANCH_SPINE:
        assert (URIRef(b.spine_class), RDF.type, OWL.Class) in g, b.label
        projected = URIRef(BFO_CATEGORY_SPINE_CLASS[b.category])
        supers = set(g.transitive_objects(URIRef(b.spine_class), RDFS.subClassOf))
        assert projected in supers, (b.label, b.spine_class, projected)
        # and the spine class is aligned to BFO 2020 (directly or via a superclass)
        assert any((s, OWL.equivalentClass, None) in g for s in supers), b.label


def test_every_speech_act_has_a_documented_default() -> None:
    from typing import get_args

    acts = set(get_args(ShardEnvelope.model_fields["speech_act"].annotation))
    assert set(DEFAULT_CATEGORY_BY_SPEECH_ACT) == acts


# ── the classifier ────────────────────────────────────────────────────────


def test_rule_types_from_the_verified_tag_branch() -> None:
    event = next(b for b in FOLIO_BRANCH_SPINE if b.label == "Event")
    entity = next(b for b in FOLIO_BRANCH_SPINE if b.label == "Legal Entity")
    llm = FakeLLM("occurrent_process")
    result = BfoClassifier(llm=llm, resolver=RESOLVER).classify(BfoInput(
        speech_act="holding",
        folio_tags=(_tag(entity, 1, verified=False), _tag(event, 2, confidence=0.8),
                    _tag(entity, 3, confidence=0.6)),
    ))
    assert (result.category, result.source, result.branch) == ("occurrent_event", "rule", event.iri)
    assert result.spine_class == FI_PREFIX + "Process"
    assert any("unverified" in e for e in result.evidence)
    assert any("span categories" in e for e in result.evidence)
    assert llm.calls == 0


def test_branch_comes_from_ancestry_not_the_caller() -> None:
    """Review P2-9: tags are unverified by default and carry no caller branch."""
    from pydantic import ValidationError

    gov = next(b for b in FOLIO_BRANCH_SPINE if b.label == "Governmental Body")
    assert FolioTag(iri=_leaf(gov)).verified is False
    with pytest.raises(ValidationError):
        FolioTag(iri=_leaf(gov), verified=True, branch="Event")  # type: ignore[call-arg]
    unverified = BfoClassifier(resolver=RESOLVER).classify(
        BfoInput(speech_act="holding", folio_tags=(FolioTag(iri=_leaf(gov)),)))
    assert unverified.source == "default"
    typed = BfoClassifier(resolver=RESOLVER).classify(
        BfoInput(speech_act="holding", folio_tags=(_tag(gov),)))
    assert (typed.category, typed.source, typed.branch) == ("continuant_independent", "rule", gov.iri)
    # without ancestry a leaf cannot be typed; a top-level branch IRI types itself
    no_resolver = BfoClassifier().classify(BfoInput(speech_act="holding", folio_tags=(_tag(gov),)))
    assert no_resolver.source == "default"
    itself = BfoClassifier().classify(BfoInput(
        speech_act="holding", folio_tags=(FolioTag(iri=gov.iri, verified=True),)))
    assert itself.source == "rule"


def test_tag_with_conflicting_ancestry_is_ambiguous() -> None:
    from folio_insights.bfo.spine import ParentMapResolver

    event = next(b for b in FOLIO_BRANCH_SPINE if b.label == "Event")
    entity = next(b for b in FOLIO_BRANCH_SPINE if b.label == "Legal Entity")
    resolver = ParentMapResolver({"urn:x:both": (event.iri, entity.iri)})
    result = BfoClassifier(resolver=resolver).classify(BfoInput(
        speech_act="holding", folio_tags=(FolioTag(iri="urn:x:both", verified=True),)))
    assert result.source == "default" and any("ambiguous" in e for e in result.evidence)


def test_llm_fallback_then_default_in_permissive_mode() -> None:
    item = BfoInput(speech_act="practitioner_advice", subject="synthetic subject")
    llm_result = BfoClassifier(llm=FakeLLM("continuant_independent", 0.9)).classify(item)
    assert (llm_result.category, llm_result.source) == ("continuant_independent", "llm")
    low = BfoClassifier(llm=FakeLLM("continuant_independent", 0.3)).classify(item)
    assert low.source == "default" and low.is_default and low.bfo_assignment == "default"
    assert low.category == DEFAULT_CATEGORY_BY_SPEECH_ACT["practitioner_advice"]
    assert any("below threshold" in e for e in low.evidence)


def test_strict_mode_refuses_an_untypeable_shard() -> None:
    item = BfoInput(speech_act="holding",
                    folio_tags=(FolioTag(iri="urn:x:no-ancestry", verified=True),))
    with pytest.raises(BfoUnclassifiable):
        BfoClassifier(mode="strict", llm=FakeLLM(None)).classify(item)
    permissive = BfoClassifier(mode="permissive", llm=FakeLLM(None)).classify(item)
    assert permissive.source == "default"


def test_port_adapter_constrains_the_llm_to_four_categories() -> None:
    from pydantic import ValidationError

    from folio_insights.llm.schemas import BfoCategoryChoice
    from folio_insights.llm.templates import BFO_CLASSIFY, template_for_task

    with pytest.raises(ValidationError):
        BfoCategoryChoice(category="fi:Role", confidence=0.9)  # type: ignore[arg-type]
    seen = {}

    class FakeTaskLLM:
        def structured_model_sync(self, prompt, schema, *, template):  # noqa: ANN001, ANN201
            seen.update(schema=schema, template=template, prompt=prompt)
            return BfoCategoryChoice(category="occurrent_process", confidence=0.8)

    choice = PortBfoLLM(FakeTaskLLM()).classify(BfoInput(speech_act="holding", subject="x"))
    assert choice.category == "occurrent_process"
    assert seen["schema"] is BfoCategoryChoice and seen["template"] is BFO_CLASSIFY
    assert template_for_task("bfo_classifier") is BFO_CLASSIFY


def _benchmark_inputs(per_branch: int = 40, untyped: int = 40) -> list[tuple[str, BfoInput]]:
    """Every FOLIO top-level branch represented by LEAF tags two levels below
    it (the branch is never given), a share of unverified noise tags, plus
    subjects with no tags."""
    out = []
    for b_index, branch in enumerate(FOLIO_BRANCH_SPINE):
        for i in range(per_branch):
            noise = FolioTag(iri=_leaf(FOLIO_BRANCH_SPINE[(b_index + 1) % 24], i), confidence=1.0)
            out.append((f"urn:x:source/{b_index % 5}", BfoInput(
                speech_act="holding", folio_tags=(noise, _tag(branch, i, confidence=0.8)))))
    for i in range(untyped):
        out.append((f"urn:x:source/{i % 5}", BfoInput(speech_act="dictum", subject=f"s{i}")))
    return out


def test_synthetic_benchmark_coverage_is_at_least_95_percent() -> None:
    """R10: >= 95% non-default on a benchmark with every branch represented.
    Untagged subjects go to the (fake) LLM; three in four get a confident answer."""
    answers = iter([("continuant_dependent", 0.9)] * 30 + [(None, 0.0)] * 10)

    class ScriptedLLM:
        def classify(self, item):  # noqa: ANN001, ANN201
            category, conf = next(answers)
            return BfoLLMChoice(category=category, confidence=conf)

    classifier = BfoClassifier(llm=ScriptedLLM(), resolver=RESOLVER)
    records = []
    for n, (source, item) in enumerate(_benchmark_inputs()):
        a = classifier.classify(item)
        if a.source == "rule":  # the noise tag never decides: it is unverified
            expected = FOLIO_BRANCH_SPINE[int(item.folio_tags[1].iri.removeprefix(_SYN).split("x")[0])]
            assert a.branch == expected.iri
        records.append(BfoRecord(f"urn:x:shard/{n}", source, a.category, a.source))
    report = build_report(records)
    assert report.total == 24 * 40 + 40
    assert report.coverage >= 0.95
    assert report.provenance_count("default") == 10
    assert set(report.as_dict()["categories"]) == set(BFO_CATEGORY_SPINE_CLASS)
    assert report.as_dict()["event_subcount"] == 40  # the Event branch


# ── projection and report over storage ────────────────────────────────────


@pytest.mark.parametrize("branch", FOLIO_BRANCH_SPINE, ids=lambda b: b.label)
def test_projection_asserts_the_mapped_spine_class(branch) -> None:  # noqa: ANN001
    assignment = BfoClassifier(resolver=RESOLVER).classify(
        BfoInput(speech_act="holding", folio_tags=(_tag(branch),)))
    assert assignment.source == "rule" and assignment.branch == branch.iri
    s = _sample_shard(SimpleAssertionShard, bfo_category=assignment.category)
    spine = [o.value for _s, p, o in shard_triples(s, journal_position=0)
             if p.value == FI_PREFIX + "subjectBfoClass"]
    assert spine == [BFO_CATEGORY_SPINE_CLASS[assignment.category]]


async def test_corpus_report_reads_shards_and_recorded_provenance(tmp_path: Path) -> None:
    ctx = await CorpusStorageContext.open(tmp_path / "storage", "corpus-a")
    try:
        classifier = BfoClassifier(resolver=RESOLVER)
        event = next(b for b in FOLIO_BRANCH_SPINE if b.label == "Event")
        typed = classifier.classify(BfoInput(speech_act="holding", folio_tags=(_tag(event),)))
        default = classifier.classify(BfoInput(speech_act="practitioner_advice"))
        shards = [
            shard(1, source_uri="urn:x:src/a", bfo_category=typed.category),
            shard(2, source_uri="urn:x:src/a", bfo_category=default.category),
            shard(3, source_uri="urn:x:src/b", bfo_category="continuant_independent"),
        ]
        await ctx.ingest_shards(shards)
        await record_assignment(ctx, shards[0].shard_iri, typed)
        await record_assignment(ctx, shards[0].shard_iri, typed)  # idempotent
        await record_assignment(ctx, shards[1].shard_iri, default)
        report = (await corpus_report(ctx)).as_dict()
    finally:
        await ctx.close()
    assert report["total"] == 3 and report["unrecorded"] == 1
    by_source = {s["source_uri"]: s for s in report["sources"]}
    a = by_source["urn:x:src/a"]
    assert a["provenance"] == {"rule": 1, "llm": 0, "default": 1, "unrecorded": 0}
    assert a["event_subcount"] == 1 and a["process_total"] == 2 and a["default_share"] == 0.5
    assert by_source["urn:x:src/b"]["categories"]["continuant_independent"] == 1


def test_bfo_report_cli(tmp_path: Path) -> None:
    root = tmp_path / "storage"

    async def seed() -> None:
        ctx = await CorpusStorageContext.open(root, "corpus-a")
        try:
            await ctx.ingest_shards([shard(1), shard(2, bfo_category="occurrent_event")])
        finally:
            await ctx.close()

    asyncio.run(seed())
    out = CliRunner().invoke(cli, ["bfo", "report", "--corpus", "corpus-a",
                                   "--corpus-root", str(root)])
    assert out.exit_code == 0, out.output
    data = json.loads(out.output)
    assert data["total"] == 2 and data["event_subcount"] == 1 and data["unrecorded"] == 2
    missing = CliRunner().invoke(cli, ["bfo", "report", "--corpus", "nope",
                                       "--corpus-root", str(root)])
    assert missing.exit_code == 1
