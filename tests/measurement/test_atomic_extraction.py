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


@pytest.mark.parametrize("emissions", [2, 3])
async def test_repeated_statements_in_one_block_keep_offsets_and_links(emissions, offline_port):
    claim = "A party must give written notice."
    source = claim + "\n\n" + claim
    payload = [proposition(f"p{i}", claim, links=[{
        "relation": "condition-of", "target_id": "p1" if i != 1 else "p0",
    }]) for i in range(emissions)]
    job = await extract(job_for(source), payload, offline_port)
    diagnostics = job.metadata["atomic_extraction"]["diagnostics"]
    if emissions == 3:
        assert any(d["reason"] == "surplus_occurrence" and d["local_id"] == "p2"
                   for d in diagnostics)
    else:
        assert diagnostics == []
    assert [(u.original_span.start, u.original_span.end) for u in job.units] == [
        (0, len(claim)), (len(claim) + 2, len(source)),
    ]
    first, second = job.units
    assert first.id != second.id
    assert [link.target_id for link in first.links] == [second.id]
    assert [link.target_id for link in second.links] == [first.id]
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


def echo_blocks(offline_port, monkeypatch, *, oversized=None, link_targets=None):
    """Answer the actual port request, with optional provider-size rejection."""
    import httpx

    router, _ = offline_port
    original_handler = router.handler
    groups = []

    def handler(request):
        body = json.loads(request.content)
        prompt = body["messages"][-1]["content"]
        blocks = json.loads(prompt.split("Source blocks (JSON):\n", 1)[1])
        groups.append(blocks)
        if oversized == "context" and len(blocks) > 2:
            router.requests.append(body)
            return httpx.Response(400, json={"error": {
                "message": "maximum context length exceeded", "type": "invalid_request_error",
                "code": "context_length_exceeded",
            }})
        router.payloads["AtomicDistilledOutput"] = {"propositions": [
            proposition(block["id"] + "-claim", block["text"], supports=[block["id"]],
                        links=(link_targets or {}).get(block["id"], []))
            for block in blocks
        ]}
        response = original_handler(request)
        if oversized == "output" and len(blocks) > 2:
            reply = response.json()
            reply["choices"][0]["finish_reason"] = "length"
            return httpx.Response(200, json=reply)
        return response

    monkeypatch.setattr(router, "handler", handler)
    return groups


async def test_long_document_uses_bounded_overlapping_groups_without_loss(
    offline_port, monkeypatch,
):
    groups = echo_blocks(offline_port, monkeypatch)
    blocks = [f"The business must give written notice to resident number {i} before the hearing."
              for i in range(30)]
    stage = DistillerStage(atomic_extraction=True, input_token_budget=6500,
                          output_token_budget=4000)
    job = await stage.execute(job_for(*blocks))
    assert len(groups) > 1
    assert any(set(b["id"] for b in left) & set(b["id"] for b in right)
               for left, right in zip(groups, groups[1:]))
    assert [u.text for u in job.units] == blocks
    assert len({u.id for u in job.units}) == len(blocks)
    for request in offline_port[0].requests:
        # Same byte-per-token upper bound used by the repo's cost estimator, plus framing.
        prompt_bytes = sum(len(m["content"].encode()) for m in request["messages"])
        schema_bytes = len(json.dumps(request["tools"][0]["function"]["parameters"]).encode())
        assert prompt_bytes + schema_bytes + 1024 <= 6500
        assert request.get("max_completion_tokens", request.get("max_tokens")) == 4000
    assert_grounded(job)


async def test_cross_group_links_resolve_at_document_scope(offline_port, monkeypatch):
    groups = echo_blocks(offline_port, monkeypatch, link_targets={"b11": [
        {"relation": "exception-to", "target_id": "b0-claim"},
        {"relation": "condition-of", "target_id": "unseen-claim"},
    ]})
    blocks = [f"The business must notify resident number {i} before the hearing."
              for i in range(12)]
    job = await DistillerStage(atomic_extraction=True, input_token_budget=6500,
                              output_token_budget=3000).execute(job_for(*blocks))
    assert not any({"b0", "b11"} <= {b["id"] for b in group} for group in groups)
    assert [(link.relation, link.target_id) for link in job.units[-1].links] == [
        ("exception-to", job.units[0].id),
    ]
    assert any(d["reason"] == "missing_endpoint" and d["target_id"] == "unseen-claim"
               for d in job.metadata["atomic_extraction"]["diagnostics"])
    assert_grounded(job)


@pytest.mark.parametrize("oversized", ["context", "output"])
async def test_oversized_requests_split_before_retry(oversized, offline_port, monkeypatch):
    groups = echo_blocks(offline_port, monkeypatch, oversized=oversized)
    blocks = [f"The business must give resident number {i} written notice before the hearing."
              for i in range(6)]
    job = await DistillerStage(atomic_extraction=True).execute(job_for(*blocks))
    assert len(groups[0]) > 2
    failed_groups = [tuple(b["id"] for b in g) for g in groups if len(g) > 2]
    assert len(failed_groups) == len(set(failed_groups))
    assert [u.text for u in job.units] == blocks
    assert any(d["reason"] == "oversized_group_split"
               for d in job.metadata["atomic_extraction"]["diagnostics"])
    assert_grounded(job)


async def test_short_substantive_input_is_never_silently_deleted(offline_port):
    text = "Give prompt notice."
    job = await extract(job_for(text), [proposition("notice", text, kind="advice")], offline_port)
    assert [u.text for u in job.units] == [text]
    assert job.units[0].source_snippet == text
    assert (job.units[0].original_span.start, job.units[0].original_span.end) == (0, len(text))
    assert_grounded(job)


async def test_short_outcome_survives_while_headings_are_rejected(offline_port):
    source = "The court considered the motion. Motion denied.\nII. Background\nFacts"
    payload = [proposition("outcome", "Motion denied.", kind="outcome"),
               proposition("section", "II. Background", kind="fact"),
               proposition("heading", "Facts", kind="fact")]
    job = await extract(job_for(source), payload, offline_port)
    assert [(u.text, u.proposition_kind) for u in job.units] == [("Motion denied.", "outcome")]
    assert_grounded(job)


def test_atomic_budget_environment_reaches_default_pipeline(monkeypatch):
    monkeypatch.setenv("FOLIO_INSIGHTS_ATOMIC_INPUT_TOKEN_BUDGET", "9000")
    monkeypatch.setenv("FOLIO_INSIGHTS_ATOMIC_OUTPUT_TOKEN_BUDGET", "5000")
    stage = next(s for s in PipelineOrchestrator(
        Settings(_env_file=None, atomic_extraction=True),
    ).stages if s.name == "distiller")
    assert stage.input_token_budget == 9000
    assert stage.output_token_budget == 5000
    # An invalid atomic budget cannot change the default-off path.
    monkeypatch.setenv("FOLIO_INSIGHTS_ATOMIC_OUTPUT_TOKEN_BUDGET", "0")
    assert DistillerStage().atomic_extraction is False
    with pytest.raises(ValidationError):
        DistillerStage(atomic_extraction=True)


@pytest.mark.parametrize("retry", [False, True])
async def test_single_long_boundary_is_bounded_without_losing_sentences(
    retry, offline_port, monkeypatch,
):
    import httpx

    router, _ = offline_port
    original_handler = router.handler
    sentences = [f"The business must notify resident number {i} in writing." for i in range(40)]
    seen = []

    def handler(request):
        body = json.loads(request.content)
        prompt = body["messages"][0]["content"]
        blocks = json.loads(prompt.split("Source blocks (JSON):\n", 1)[1])
        seen.append(tuple((b["id"], b["text"]) for b in blocks))
        if retry and sum(len(b["text"]) for b in blocks) > 300:
            router.requests.append(body)
            return httpx.Response(413, json={"error": {
                "message": "request too large", "type": "invalid_request_error",
            }})
        payload = []
        for i, sentence in enumerate(sentences):
            support = next((b for b in blocks if sentence in b["text"]), None)
            if support:
                payload.append(proposition(f"sentence-{i}", sentence, supports=[support["id"]]))
        router.payloads["AtomicDistilledOutput"] = {"propositions": payload}
        return original_handler(request)

    monkeypatch.setattr(router, "handler", handler)
    job = await DistillerStage(atomic_extraction=True, input_token_budget=6500,
                              output_token_budget=4000).execute(job_for(" ".join(sentences)))
    assert len(seen) > 1
    assert len(seen) == len(set(seen))
    assert [u.text for u in job.units] == sentences
    assert_grounded(job)


@pytest.mark.parametrize("retry", [False, True])
async def test_long_sentences_stay_complete_through_recursive_splits(
    retry, offline_port, monkeypatch,
):
    import httpx

    router, _ = offline_port
    original_handler = router.handler
    sentences = [
        f"The business must notify resident number {i} in writing before the hearing "
        "and provide the complete record of its decision together with instructions "
        "for requesting review within the prescribed period."
        for i in range(20)
    ]
    seen, successful = [], []

    def handler(request):
        body = json.loads(request.content)
        blocks = json.loads(body["messages"][0]["content"].split("Source blocks (JSON):\n", 1)[1])
        seen.append(blocks)
        if retry and sum(len(b["text"]) for b in blocks) > 250:
            router.requests.append(body)
            return httpx.Response(413, json={"error": {
                "message": "request too large", "type": "invalid_request_error",
            }})
        successful.append(blocks)
        router.payloads["AtomicDistilledOutput"] = {"propositions": [
            proposition(f"sentence-{i}", sentence, supports=[block["id"]])
            for i, sentence in enumerate(sentences)
            for block in blocks if sentence in block["text"]
        ]}
        return original_handler(request)

    monkeypatch.setattr(router, "handler", handler)
    job = await DistillerStage(atomic_extraction=True, input_token_budget=6500,
                              output_token_budget=4000).execute(job_for(" ".join(sentences)))
    assert len(seen) > 1
    assert all(any(sentence in block["text"] for group in successful for block in group)
               for sentence in sentences)
    assert [u.text for u in job.units] == sentences
    if retry:
        assert any(d["reason"] == "oversized_group_split"
                   for d in job.metadata["atomic_extraction"]["diagnostics"])
    assert_grounded(job)


async def test_indivisible_over_budget_sentence_is_sent_alone_with_diagnostic(
    offline_port, monkeypatch,
):
    groups = echo_blocks(offline_port, monkeypatch)
    sentence = "A party must provide " + "written notice and " * 100 + "a complete record."
    job = await DistillerStage(atomic_extraction=True, input_token_budget=6500,
                              output_token_budget=4000).execute(job_for(sentence))
    assert [[b["text"] for b in group] for group in groups] == [[sentence]]
    assert [u.text for u in job.units] == [sentence]
    assert any(d["reason"] == "oversized_sentence"
               for d in job.metadata["atomic_extraction"]["diagnostics"])
    assert_grounded(job)


@pytest.mark.parametrize("block_count", [1, 2])
def test_recursive_fallback_keeps_whole_sentence_overlap_until_singleton_leaves(block_count):
    from folio_insights.pipeline.stages.distiller import _AtomicBlock, _split_atomic_group

    sentences = [f"A party must notify resident number {i} in writing." for i in range(20)]
    size = len(sentences) // block_count
    job = job_for(*[" ".join(sentences[i:i + size]) for i in range(0, len(sentences), size)])
    source = job.metadata["ingested"]["synthetic.txt"]["text"]
    pending = [[_AtomicBlock(f"b{i}", parent, parent.original_span.start,
                             parent.original_span.end) for i, parent in enumerate(job.units)]]
    while pending:
        group = pending.pop()
        children = _split_atomic_group(group, source)
        if not children:
            assert len(group) == 1
            assert source[group[0].start:group[0].end].strip() in sentences
            continue
        covered = [{sentence for sentence in sentences
                    if any(sentence in source[b.start:b.end] for b in child)}
                   for child in children]
        if len(set.union(*covered)) > 2:
            assert set.intersection(*covered), "Fallback dropped all complete-sentence overlap"
        for child in children:
            assert sum(b.end - b.start for b in child) < sum(b.end - b.start for b in group)
            for block in child:
                text = source[block.start:block.end].strip()
                assert any(text.startswith(sentence) for sentence in sentences)
                assert any(text.endswith(sentence) for sentence in sentences)
        pending.extend(children)


async def test_same_span_nfc_duplicates_merge_links_and_citations(offline_port):
    import unicodedata

    source = "A café must give notice under Rule 42."
    payload = [proposition("first", source),
               proposition("second", unicodedata.normalize("NFD", source), citations=["Rule 42"],
                           links=[{"relation": "condition-of", "target_id": "duty"}]),
               proposition("duty", DUTY, supports=["b1"])]
    job = await extract(job_for(source, DUTY), payload, offline_port)
    assert len(job.units) == 2
    assert len(job.units[0].unresolved_citations) == 1
    assert job.units[0].links[0].target_id == job.units[1].id
    assert_grounded(job)


@pytest.mark.parametrize("local_rejected", [False, True])
async def test_cross_group_alias_never_overrides_ambiguous_or_rejected_endpoint(
    local_rejected, offline_port, monkeypatch,
):
    router, _ = offline_port
    original_handler = router.handler
    calls = []

    def handler(request):
        body = json.loads(request.content)
        blocks = json.loads(body["messages"][0]["content"].split("Source blocks (JSON):\n", 1)[1])
        calls.append(blocks)
        payload = []
        for block in blocks:
            id = block["id"]
            payload.append(proposition(id + "-claim", block["text"], supports=[id]))
            if id == "b0" or (id == "b3" and not local_rejected):
                payload.append(proposition("shared", block["text"], supports=[id]))
            if id == "b11":
                payload[-1]["links"] = [{"relation": "condition-of", "target_id": "shared"}]
                if local_rejected:
                    payload.append(proposition("shared", "A pilot may land a glider on a runway.",
                                               supports=[id]))
        router.payloads["AtomicDistilledOutput"] = {"propositions": payload}
        return original_handler(request)

    monkeypatch.setattr(router, "handler", handler)
    blocks = [f"The business must notify resident number {i} before the hearing."
              for i in range(12)]
    job = await DistillerStage(atomic_extraction=True, input_token_budget=6500,
                              output_token_budget=3000).execute(job_for(*blocks))
    assert len(calls) > 1
    assert not job.units[-1].links
    assert any(d["target_id"] == "shared" for d in
               job.metadata["atomic_extraction"]["diagnostics"] if "target_id" in d)
    assert_grounded(job)
