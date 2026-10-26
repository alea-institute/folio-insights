"""U38: synthetic atomic extraction through the BYOK port, entirely offline."""
from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from folio_insights.config import Settings
from folio_insights.llm import use_context
from folio_insights.llm.port import set_default_port
from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span, finalize_document
from folio_insights.pipeline.orchestrator import PipelineCheckpoint, PipelineOrchestrator
from folio_insights.pipeline.stages.base import InsightsJob
from folio_insights.pipeline.stages.distiller import DistillerStage
from tests.llm.conftest import make_context, make_port
from tests.pipeline.test_unit_template_lineage import SchemaRouter

CONTRACT = (
    "A plaintiff must prove (1) the formation of a contract, "
    "(2) the plaintiff's performance, and (3) the defendant's breach."
)
DUTY = "(a) A business must notify affected residents of a security breach."
EXCEPTION = "(b) A business need not notify if law enforcement requests a delay in writing."


def job_for(*blocks, genre="opinions"):
    source = "\n\n".join(blocks)
    units, start = [], 0
    for index, block in enumerate(blocks):
        units.append(KnowledgeUnit(
            id=f"boundary-{index}", text=block, source_file="synthetic.txt",
            original_span=Span(start=start, end=start + len(block), source_file="synthetic.txt"),
            unit_type=KnowledgeType.ADVICE, anchor_score=0.12, anchor_verified=False,
        ))
        start += len(block) + 2
    return InsightsJob(
        corpus_name="synthetic", source_dir="/nonexistent", units=units,
        metadata={"ingested": {"synthetic.txt": {"text": source, "genre": genre}}},
    )


def proposition(local_id, text, *, kind="rule", supports=None, links=None, citations=None):
    return {"id": local_id, "text": text, "kind": kind,
            "support_ids": supports or ["b0"], "links": links or [],
            "citations": citations or []}


def contract_output():
    return [
        proposition("rule", "A plaintiff must prove formation, performance, and breach."),
        *[proposition(name, text, kind="element", links=[
            {"relation": "condition-of", "target_id": "rule"},
        ]) for name, text in [
            ("formation", "the formation of a contract"),
            ("performance", "the plaintiff's performance"),
            ("breach", "the defendant's breach"),
        ]],
    ]


@pytest.fixture
def offline_port():
    router = SchemaRouter({})
    set_default_port(make_port(router))
    try:
        with use_context(make_context("openai")) as ctx:
            yield router, ctx
    finally:
        set_default_port(None)


async def extract(job, payload, offline_port):
    router, _ = offline_port
    router.payloads["AtomicDistilledOutput"] = {"propositions": payload}
    return await DistillerStage(atomic_extraction=True).execute(job)


def assert_grounded(job):
    source = job.metadata["ingested"]["synthetic.txt"]["text"]
    assert finalize_document(job.units, source_text=source,
                             source_snapshot_id="synthetic.txt") == job.units
    for unit in job.units:
        assert unit.anchor_verified and unit.anchor_score == 1.0
        assert unit.source_snippet == source[unit.original_span.start:unit.original_span.end]
        assert unit.content_hash == hashlib.sha256(unit.text.encode()).hexdigest()
        assert unit.provenance.genre == job.metadata["ingested"]["synthetic.txt"]["genre"]


async def test_contract_rule_and_three_independently_grounded_conditions(offline_port):
    job = await extract(job_for(CONTRACT), contract_output(), offline_port)
    assert len(job.units) == 4
    rule, *elements = job.units
    assert [u.proposition_kind for u in job.units] == ["rule", "element", "element", "element"]
    assert all([(link.relation, link.target_id) for link in u.links] == [
        ("condition-of", rule.id),
    ] for u in elements)
    assert_grounded(job)
    router, ctx = offline_port
    assert len(router.requests) == 1
    assert "distiller.atomic" in ctx.templates_used
    assert all(u.lineage[-1].template_hash == ctx.templates_used["distiller.atomic"]
               for u in job.units)
    assert all("support_recall=" in u.lineage[-1].detail for u in job.units)


@pytest.mark.parametrize("reverse_boundaries", [False, True])
async def test_exception_links_to_duty_across_subdivisions(reverse_boundaries, offline_port):
    input_job = job_for(DUTY, EXCEPTION, genre="statutes-regulations")
    if reverse_boundaries:
        input_job.units.reverse()  # Refinement may append long paragraphs after short ones.
    payload = [
        proposition("duty", DUTY, supports=["b1" if reverse_boundaries else "b0"]),
        proposition("exception", EXCEPTION, kind="exception",
                    supports=["b0" if reverse_boundaries else "b1"], links=[
            {"relation": "exception-to", "target_id": "duty"},
        ]),
    ]
    job = await extract(input_job, payload, offline_port)
    assert len(job.units) == 2
    assert job.units[1].links[0].target_id == job.units[0].id
    assert job.units[1].links[0].relation == "exception-to"
    assert_grounded(job)
    prompt = offline_port[0].requests[0]["messages"][-1]["content"]
    assert DUTY in prompt and EXCEPTION in prompt
    assert prompt.index(DUTY) < prompt.index(EXCEPTION)


@pytest.mark.parametrize("endpoint", ["missing", "ambiguous", "self"])
async def test_unresolved_endpoints_are_diagnostics_without_fictitious_links(endpoint, offline_port):
    payload = [proposition("duty", DUTY)]
    if endpoint == "ambiguous":
        payload.append(proposition("duty", DUTY))
    payload.append(proposition("exception", EXCEPTION, kind="exception", supports=["b1"], links=[
        {"relation": "exception-to", "target_id": "exception" if endpoint == "self" else
         "absent" if endpoint == "missing" else "duty"},
    ]))
    job = await extract(job_for(DUTY, EXCEPTION), payload, offline_port)
    assert not job.units[-1].links
    assert any(d["reason"] == f"{endpoint}_endpoint"
               for d in job.metadata["atomic_extraction"]["diagnostics"])
    assert_grounded(job)


async def test_repeated_text_unicode_and_newlines_keep_occurrences(offline_port):
    block = "A café must give written notice.\nThe café may request a delay."
    job = job_for(block, block)
    # Legacy boundary anchoring may point both identical inputs at the first occurrence.
    job.units[1].original_span = job.units[0].original_span.model_copy()
    payload = [proposition(f"p{i}", "A café must give written notice.", supports=[f"b{i}"])
               for i in range(2)]
    job = await extract(job, payload, offline_port)
    assert len(job.units) == 2
    assert [u.original_span.start for u in job.units] == [0, len(block) + 2]
    assert_grounded(job)


async def test_short_elements_do_not_inherit_the_distiller_length_floor(offline_port):
    source = "A claimant must prove each element: (1) offer; (2) assent."
    payload = [proposition("rule", "A claimant must prove each element."),
               proposition("offer", "offer", kind="element"),
               proposition("assent", "assent", kind="element")]
    job = await extract(job_for(source), payload, offline_port)
    assert [u.text for u in job.units][1:] == ["offer", "assent"]
    assert_grounded(job)


async def test_complete_rule_support_can_span_boundary_size_chunks(offline_port):
    first = "A claimant must prove formation of a contract and " + "performance " * 55
    second = "and the defendant's breach of that contract."
    job = await extract(job_for(first, second), [proposition(
        "rule", "A claimant must prove formation, performance, and breach of a contract.",
        supports=["b0", "b1"],
    )], offline_port)
    assert len(job.units) == 1
    assert job.units[0].original_span.start == 0
    assert job.units[0].original_span.end == len(first) + 2 + len(second)
    assert_grounded(job)


async def test_fabricated_specifics_and_unsupported_claims_are_rejected(offline_port):
    payload = [proposition("supported", DUTY),
               proposition("specifics", "A business must notify under Rule 99 within 14 days."),
               proposition("unrelated", "A pilot may land a glider on the runway."),
               proposition("bad-support", DUTY, supports=["absent"])]
    job = await extract(job_for(DUTY), payload, offline_port)
    assert [u.text for u in job.units] == [DUTY]
    reasons = {d["reason"] for d in job.metadata["atomic_extraction"]["diagnostics"]}
    assert {"unsupported_specifics", "claim_unsupported", "missing_support"} <= reasons
    assert_grounded(job)


async def test_external_citation_stays_explicitly_unresolved(offline_port):
    source = "A party must give notice as required by Rule 42."
    job = await extract(job_for(source), [proposition("p", source, citations=["Rule 42"])],
                        offline_port)
    assert not job.units[0].links
    assert job.units[0].unresolved_citations[0].citation == "Rule 42"


async def test_citation_keeps_complete_support_when_claim_matches_a_shorter_sentence(offline_port):
    claim = "A party must give written notice."
    source = claim + " This duty is established by Rule 42."
    job = await extract(job_for(source), [proposition("p", claim, citations=["Rule 42"])],
                        offline_port)
    assert job.units[0].source_snippet == source
    assert job.units[0].unresolved_citations[0].citation == "Rule 42"


async def test_atomic_children_and_links_survive_real_pipeline_and_checkpoints(
    tmp_path, monkeypatch, offline_port,
):
    from folio_insights.pipeline.stages.deduplicator import DeduplicatorStage
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage
    from folio_insights.services.bridge.ingestion_bridge import IngestionBridge

    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "contract.txt").write_text(CONTRACT, encoding="utf-8")
    monkeypatch.setattr(IngestionBridge, "__init__", lambda self: None)
    monkeypatch.setattr(IngestionBridge, "detect_and_ingest",
                        lambda self, path: (path.read_text(encoding="utf-8"), []))
    monkeypatch.setattr(DeduplicatorStage, "_encode_units", lambda self, units: None)
    monkeypatch.setattr(PipelineOrchestrator, "_run_b5_canary", lambda self: None)

    async def offline_tags(self, job):
        return job

    monkeypatch.setattr(FolioTaggerStage, "execute", offline_tags)
    router, _ = offline_port
    router.payloads.update({
        "AtomicDistilledOutput": {"propositions": contract_output()},
        "ClassificationOutput": {"unit_type": "procedural_rule", "confidence": 0.8},
        "NoveltyOutput": {"score": 0.3},
    })
    settings = Settings(_env_file=None, atomic_extraction=True, output_dir=tmp_path / "output")
    orch = PipelineOrchestrator(settings)
    job = await orch.run(sources, "atomic", resume=False)
    assert len(job.units) == 4
    saved = json.loads((settings.output_dir / "atomic" / "extraction.json").read_text())
    assert saved["total_units"] == 4
    assert {u["id"] for u in saved["units"]} == {u.id for u in job.units}
    for unit in job.units:
        assert unit.is_grounded(CONTRACT, source_snapshot_id=unit.source_file)
    assert sum(len(u["links"]) for u in saved["units"]) == 3
    requests = len(router.requests)
    resumed = await orch.run(sources, "atomic")
    assert [u.model_dump() for u in resumed.units] == [u.model_dump() for u in job.units]
    assert len(router.requests) == requests


async def test_default_off_keeps_legacy_distillation_and_schema(offline_port):
    router, _ = offline_port
    router.payloads["DistilledOutput"] = {"distilled_text": "Give notice promptly."}
    job = job_for(DUTY)
    original = job.units[0]
    await DistillerStage().execute(job)
    assert job.units == [original] and original.text == "Give notice promptly."
    assert original.provenance is None and not original.links
    assert "atomic_extraction" not in job.metadata
    assert router.requests[0]["tools"][0]["function"]["name"] == "DistilledOutput"


def test_configuration_defaults_off_and_reaches_orchestrator(monkeypatch):
    assert Settings(_env_file=None).atomic_extraction is False
    monkeypatch.setenv("FOLIO_INSIGHTS_ATOMIC_EXTRACTION", "true")
    settings = Settings(_env_file=None)
    assert settings.atomic_extraction is True
    stage = next(s for s in PipelineOrchestrator(settings).stages if s.name == "distiller")
    assert stage.atomic_extraction is True


async def test_atomic_run_refuses_legacy_distiller_checkpoint(tmp_path, offline_port):
    settings = Settings(_env_file=None, output_dir=tmp_path, atomic_extraction=True)
    PipelineCheckpoint.save("distiller", job_for(DUTY), tmp_path / "synthetic")
    orch = PipelineOrchestrator(settings, stages=[DistillerStage(atomic_extraction=True)])
    with pytest.raises(ValueError, match="atomic_extraction.*checkpoint"):
        await orch.run(tmp_path, "synthetic")


@pytest.mark.parametrize("extra", [{"iri": "urn:invented"}, {"start": 0}, {"anchor_score": 1}])
def test_model_cannot_supply_identifiers_offsets_or_verification(extra):
    from folio_insights.llm.schemas import AtomicDistilledOutput

    with pytest.raises(ValidationError):
        AtomicDistilledOutput.model_validate({"propositions": [
            {**proposition("p", DUTY), **extra},
        ]})
