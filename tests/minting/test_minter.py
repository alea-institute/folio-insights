"""Drain U8 (R1-R5, AE1, AE2, KTD1, KTD3): the gated shard minter end to end.

A fake provider (the real port, SDK and instructor stack over a recorded
transport) drives every LLM call; corpora, keys and texts are synthetic.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from folio_insights.governance.events import ExtractEvent
from folio_insights.llm.templates import DISTILL, MINT_FIELDS, combined_prompt_hash
from folio_insights.minting import MintRefused, mark_local_only, mint_run
from folio_insights.minting.mapper import PREDICATE_BY_UNIT_TYPE, source_uri_for
from folio_insights.models.knowledge_unit import KnowledgeType
from folio_insights.shards import SimpleAssertionShard, mint_shard_iri
from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.context import verify_event_signature_offline

from tests.minting.conftest import (
    CORPUS,
    DAUBERT,
    FABRICATED,
    HEADING,
    LEAK_MARKER,
    MODEL,
    RUN_CORPUS,
    SENTENCES,
    SOURCE,
    SOURCE_FILE,
    FakeProvider,
    default_fields,
    governed_corpus,
    lineage,
    llm_tag,
    ruler_tag,
    scan_for,
    unit,
    write_run,
)


async def _mint(tmp: Path, run: Path, src: Path, provider: FakeProvider | None, **kw):
    kw.setdefault("source_visibility", "public")
    kw.setdefault("framework_id", "us.federal.fre")
    return await mint_run(
        kw.pop("root", tmp / "storage"), kw.pop("corpus", CORPUS), run, sources_dir=src,
        llm=provider.port() if provider else None,
        llm_context=provider.context() if provider else None, **kw,
    )


async def _shards(root: Path, corpus: str = CORPUS) -> list[SimpleAssertionShard]:
    ctx = await CorpusStorageContext.open(root, corpus)
    try:
        return [s async for s in ctx.shards.iter_shards()]
    finally:
        await ctx.close()


async def _extract_events(root: Path, corpus: str = CORPUS) -> list[ExtractEvent]:
    ctx = await CorpusStorageContext.open(root, corpus)
    try:
        return [e async for e in ctx.governance.iter_events(corpus)
                if isinstance(e, ExtractEvent)]
    finally:
        await ctx.close()


async def _head(root: Path, corpus: str = CORPUS) -> int:
    ctx = await CorpusStorageContext.open(root, corpus)
    try:
        return await ctx.journal_head()
    finally:
        await ctx.close()


# ── AE1: invention cannot be minted ──────────────────────────────────────


async def test_ae1_fabricated_heading_and_unjudged_units_are_refused_distinctly(
    tmp_path: Path, provider: FakeProvider, oracle
) -> None:
    from folio_insights.services.anchoring import resolve_anchor

    assert round(resolve_anchor(FABRICATED, SOURCE).score, 2) == 0.62
    units = [
        # Fluent distilled text, a snippet that is NOT in the source (0.62).
        unit("fabricated", SENTENCES[0], text="Lead the witness on redirect so the jury "
             "hears agreement twice.", snippet=FABRICATED, anchor_score=0.62,
             anchor_verified=False),
        unit("heading", HEADING),
        unit("unjudged", SENTENCES[1], tags=[llm_tag(judge_status="unjudged")],
             events=lineage(concept=True)),
    ]
    run, src = write_run(tmp_path, units)
    gov = await governed_corpus(tmp_path / "storage")
    report = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                         oracle=oracle)

    codes = {u.unit_id: u.code for u in report.units}
    assert codes == {"fabricated": "anchor_unverified", "heading": "not_substantive",
                     "unjudged": "iri_unjudged"}
    assert len(set(codes.values())) == 3
    assert report.minted == []
    assert provider.requests == []  # refused before any model call
    assert await _shards(gov.root) == []
    assert report.counts()["refused_by_code"] == {
        "anchor_unverified": 1, "iri_unjudged": 1, "not_substantive": 1}


# ── the happy path ───────────────────────────────────────────────────────


async def test_eligible_unit_mints_a_valid_hypothesis_shard_from_the_verified_slice(
    tmp_path: Path, provider: FakeProvider, oracle
) -> None:
    text = "Use only leading questions on cross so the witness can only agree."
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0], text=text)])
    gov = await governed_corpus(tmp_path / "storage")
    report = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                         oracle=oracle)

    assert [u.status for u in report.units] == ["minted"], report.as_dict()["units"]
    (shard,) = await _shards(gov.root)
    assert isinstance(shard, SimpleAssertionShard)
    SimpleAssertionShard.model_validate(shard.model_dump())  # envelope validation

    # KTD1: identity is the verified source slice, never the distilled text.
    start = SOURCE.index(SENTENCES[0])
    assert shard.source_span == SOURCE[start:start + len(SENTENCES[0])]
    assert shard.source_span != text and text not in shard.source_span
    source_uri = source_uri_for(RUN_CORPUS, SOURCE_FILE)
    assert shard.source_uri == source_uri == f"urn:folio:source:{RUN_CORPUS}:{SOURCE_FILE}"
    assert (shard.shard_iri, shard.provenance_hash) == mint_shard_iri(source_uri, shard.source_span)
    assert report.units[0].shard_iri == shard.shard_iri

    # The documented triple and fields.
    assert shard.triple.subject == DAUBERT
    assert shard.triple.predicate == PREDICATE_BY_UNIT_TYPE[KnowledgeType.ADVICE]
    assert shard.triple.object == text
    assert shard.epistemic_status == "hypothesis"
    assert shard.verification_method == "extractor_assertion"
    assert shard.framework_id == "us.federal.fre"
    assert shard.bfo_category == "occurrent_process"  # Daubert Motion Practice: Service
    assert shard.speech_act == "practitioner_advice" and shard.layer == "L2_composed"
    assert shard.sense == default_fields()["sense"]["value"]
    assert shard.extractor_model == f"openai:{MODEL}"
    assert shard.first_extractor_did == gov.extractor.did
    assert shard.confidence == pytest.approx(0.7)  # min gate confidence (predication_mode)
    assert shard.extraction_prompt_hash == combined_prompt_hash([DISTILL.hash, MINT_FIELDS.hash])
    assert [s.action for s in shard.signatures] == ["extract"]
    assert shard.depends_on_axioms == [] and shard.depends_on_shards == []

    # SHACL: the local tier passed at write time; the full suite has no Violation.
    ctx = await CorpusStorageContext.open(gov.root, CORPUS)
    try:
        validation = await ctx.validate_corpus()
    finally:
        await ctx.close()
    assert validation.violations == 0

    # One structured call, with the mint.fields template and the span in the prompt.
    (request,) = provider.requests
    body = json.loads(request.content)
    assert body["tools"][0]["function"]["name"] == "MintFieldsOutput"
    prompt = "\n".join(m["content"] for m in body["messages"])
    assert SENTENCES[0] in prompt and "Use ONLY the verified source passage" in prompt

    # Report: cost from the LLM context, a deterministic rubric section, never publishable.
    data = report.as_dict()
    assert data["publishable"] is False and data["rubric"]["publishable"] is False
    assert data["rubric"]["computed"] is True and data["rubric"]["artifact"]["units"] == 1
    criteria = {c["id"]: c for c in data["rubric"]["criteria"]}
    # The anchor re-verifies exactly; the subject IRI is a real FOLIO concept (the triple's
    # module-namespace predicate is a relation, not a concept tag, and is not checked).
    assert criteria["RUB-EXTRACT-05"]["score"] == 3 and criteria["RUB-EXTRACT-05"]["gate"] == "pass"
    assert criteria["RUB-EXTRACT-03"]["score"] == 3
    assert criteria["RUB-EXTRACT-10"]["gate"] == "pass"
    assert "RUB-EXTRACT-01" in data["rubric"]["not_scored"]
    assert data["cost"]["templates"] == {MINT_FIELDS.id: MINT_FIELDS.hash}
    assert data["counts"]["by_status"] == {"minted": 1}


async def test_framework_guard_refuses_an_unregistered_framework(
    tmp_path: Path, provider: FakeProvider, oracle
) -> None:
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0])])
    gov = await governed_corpus(tmp_path / "storage")
    report = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                         oracle=oracle, framework_id="us.texas.civil_practice")
    assert report.units[0].code == "framework_unconfident"
    assert provider.requests == []


async def test_v1_framework_ids_migrate_with_a_warning(
    tmp_path: Path, provider: FakeProvider, oracle
) -> None:
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0])])
    gov = await governed_corpus(tmp_path / "storage")
    report = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                         oracle=oracle, framework_id="us.federal.fre.2024")
    assert report.units[0].status == "minted"
    (shard,) = await _shards(gov.root)
    assert shard.framework_id == "us.federal.fre"
    assert any("year suffix" in w for w in report.as_dict()["framework_migration_warnings"])


# ── AE2: idempotency, determinism, ExtractEvents ─────────────────────────


async def test_ae2_second_run_writes_nothing_and_keeps_one_extract_event_per_shard(
    tmp_path: Path, provider: FakeProvider, oracle
) -> None:
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0]), unit("u2", SENTENCES[2])])
    gov = await governed_corpus(tmp_path / "storage")
    first = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                        oracle=oracle)
    assert [u.status for u in first.units] == ["minted", "minted"]
    head = await _head(gov.root)
    calls = len(provider.requests)

    second = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                         oracle=oracle)
    assert [u.status for u in second.units] == ["already_present", "already_present"]
    assert [u.shard_iri for u in second.units] == [u.shard_iri for u in first.units]
    assert [u.extract_event for u in second.units] == ["existing", "existing"]
    assert await _head(gov.root) == head  # no new journal rows
    assert len(provider.requests) == calls  # no new model calls

    events = await _extract_events(gov.root)
    assert sorted(e.shard_iri for e in events) == sorted(u.shard_iri for u in first.units)
    for event in events:
        assert event.extractor_model == f"openai:{MODEL}"
        assert event.signature.did == gov.extractor.did
        assert await verify_event_signature_offline(event)


async def test_identical_inputs_give_identical_iris_and_prompt_hashes(
    tmp_path: Path, oracle
) -> None:
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0]), unit("u2", SENTENCES[1])])
    results = []
    for name in ("a", "b"):
        provider = FakeProvider()
        gov = await governed_corpus(tmp_path / name)
        report = await _mint(tmp_path, run, src, provider, root=gov.root,
                             signing_key=gov.extractor.sk, oracle=oracle)
        shards = sorted(await _shards(gov.root), key=lambda s: s.shard_iri)
        results.append([(s.shard_iri, s.provenance_hash, s.extraction_prompt_hash)
                        for s in shards])
        assert report.run_id.startswith("run-")
    assert results[0] == results[1] and len(results[0]) == 2


async def test_unsigned_run_writes_unsigned_shards_and_skips_extract_events(
    tmp_path: Path, provider: FakeProvider, oracle
) -> None:
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0])])
    report = await _mint(tmp_path, run, src, provider, oracle=oracle,
                         extractor_did="did:key:z6MkSyntheticExtractorOnly")
    assert report.units[0].status == "minted"
    assert report.units[0].extract_event == "unsigned: skipped"
    assert any("no signing key" in n for n in report.notes)
    (shard,) = await _shards(tmp_path / "storage")
    assert shard.signatures == []
    assert await _extract_events(tmp_path / "storage") == []


async def test_signer_without_the_extractor_role_is_refused_before_any_call(
    tmp_path: Path, provider: FakeProvider
) -> None:
    from tests.storage.conftest import new_identity

    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0])])
    gov = await governed_corpus(tmp_path / "storage")
    with pytest.raises(MintRefused) as info:
        await _mint(tmp_path, run, src, provider, signing_key=new_identity().sk)
    assert info.value.code == "extractor_unauthorized"
    assert provider.requests == [] and await _shards(gov.root) == []


# ── R5: source visibility ────────────────────────────────────────────────


async def test_non_public_source_into_a_public_corpus_is_refused_before_any_llm_call(
    tmp_path: Path, provider: FakeProvider, oracle
) -> None:
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0])])
    root = tmp_path / "storage"
    with pytest.raises(MintRefused) as info:
        await _mint(tmp_path, run, src, provider, source_visibility="non-public",
                    extractor_did="did:key:z6MkSyntheticExtractorOnly", oracle=oracle)
    assert info.value.code == "source_visibility"
    assert provider.requests == []  # the transport saw nothing
    assert not root.exists()  # the corpus was not even opened

    mark_local_only(root, CORPUS)
    report = await _mint(tmp_path, run, src, provider, source_visibility="non-public",
                         extractor_did="did:key:z6MkSyntheticExtractorOnly", oracle=oracle)
    assert report.units[0].status == "minted"
    assert report.as_dict()["run"]["source_visibility"] == "non-public"


# ── fail-closed field inference ──────────────────────────────────────────


async def test_low_confidence_field_refuses_the_unit(tmp_path: Path, oracle) -> None:
    provider = FakeProvider(fields=lambda _b: default_fields(
        sense={"value": "Leading questions might help.", "confidence": 0.31}))
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0])])
    gov = await governed_corpus(tmp_path / "storage")
    report = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                         oracle=oracle)
    outcome = report.units[0]
    assert (outcome.status, outcome.code) == ("refused", "field_low_confidence:sense")
    assert len(provider.requests) == 1
    assert await _shards(gov.root) == []


async def test_custom_floor_applies_per_field(tmp_path: Path, provider: FakeProvider,
                                              oracle) -> None:
    from folio_insights.minting.fields import FieldFloors

    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0])])
    gov = await governed_corpus(tmp_path / "storage")
    report = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                         oracle=oracle, field_floors=FieldFloors(per_field={"layer": 0.9}))
    assert report.units[0].code == "field_low_confidence:layer"


async def test_no_llm_refuses_every_eligible_unit(tmp_path: Path, oracle) -> None:
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0]), unit("u2", SENTENCES[1])])
    gov = await governed_corpus(tmp_path / "storage")
    report = await _mint(tmp_path, run, src, None, signing_key=gov.extractor.sk, oracle=oracle)
    assert {u.code for u in report.units} == {"field_inference_unavailable"}
    assert await _shards(gov.root) == []


async def test_missing_credentials_halt_the_run_without_defaulting(tmp_path: Path,
                                                                   oracle) -> None:
    from folio_insights.llm import LLMRunContext

    provider = FakeProvider()
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0]), unit("u2", SENTENCES[1])])
    gov = await governed_corpus(tmp_path / "storage")
    report = await mint_run(
        gov.root, CORPUS, run, sources_dir=src, llm=provider.port(),
        llm_context=LLMRunContext(provider="openai", model=MODEL),  # no key
        source_visibility="public", signing_key=gov.extractor.sk, framework_id="us.federal.fre",
        oracle=oracle,
    )
    assert {u.code for u in report.units} == {"field_inference_unavailable"}
    assert provider.requests == []


async def test_bfo_unclassifiable_without_a_typing_source(tmp_path: Path,
                                                          provider: FakeProvider) -> None:
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0])])
    gov = await governed_corpus(tmp_path / "storage")
    # No oracle (no FOLIO ancestry) and no LLM fallback: strict BFO refuses.
    report = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                         llm_fallbacks=False)
    assert report.units[0].code == "bfo_unclassifiable"


# ── credentials never leak ───────────────────────────────────────────────


async def test_no_synthetic_key_appears_in_shards_events_report_or_journal(
    tmp_path: Path, provider: FakeProvider, oracle
) -> None:
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0])])
    gov = await governed_corpus(tmp_path / "storage")
    report = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                         oracle=oracle)
    assert report.units[0].status == "minted"
    raw = gov.extractor.sk.private_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    needles = [
        LEAK_MARKER.encode(),
        raw, raw.hex().encode(),
        base64.urlsafe_b64encode(raw).rstrip(b"="),  # the JWK "d" form
    ]
    assert scan_for(gov.root, needles) == []
    text = json.dumps(report.as_dict()).encode()
    assert not any(n in text for n in needles)
    assert SENTENCES[0].encode() not in text  # no source text in the report either


# ── dependencies on the axiom kernel (U3) ────────────────────────────────


async def test_unit_depending_on_a_kernel_maxim_keeps_the_edge(
    tmp_path: Path, provider: FakeProvider, oracle
) -> None:
    from folio_insights.kernel.catalog import load_catalog
    from folio_insights.kernel.seed import seed_kernel
    from folio_insights.kernel.traversal import derived_from_kernel

    k6 = load_catalog().by_citation("VI 5.12.6").shard_iri
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0], cross_references=[k6, "dup-1"])])
    gov = await governed_corpus(tmp_path / "storage")
    await seed_kernel(gov.root, CORPUS, signing_key=gov.admin.sk, collections=("liber_sextus",))
    report = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                         oracle=oracle)
    assert report.units[0].status == "minted", report.as_dict()["units"]
    iri = report.units[0].shard_iri
    ctx = await CorpusStorageContext.open(gov.root, CORPUS)
    try:
        shard = await ctx.shards.get(iri)
        assert shard.depends_on_axioms == [k6] and shard.depends_on_shards == []
        derivations = await derived_from_kernel(ctx, iri)
    finally:
        await ctx.close()
    assert [d.kernel_iri for d in derivations] == [k6]
    assert derivations[0].path == (iri, k6)


async def test_unresolvable_shard_dependency_refuses_the_unit(
    tmp_path: Path, provider: FakeProvider, oracle
) -> None:
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0],
                                         cross_references=["urn:folio:shard/" + "a" * 32])])
    gov = await governed_corpus(tmp_path / "storage")
    report = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                         oracle=oracle)
    assert report.units[0].code == "dependency_unresolved"
    assert provider.requests == []


# ── run-level behaviour ──────────────────────────────────────────────────


async def test_dry_run_calls_nothing_and_writes_nothing(
    tmp_path: Path, provider: FakeProvider
) -> None:
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0]), unit("h", HEADING)])
    root = tmp_path / "storage"
    report = await _mint(tmp_path, run, src, provider, dry_run=True,
                         extractor_did="did:key:z6MkSyntheticExtractorOnly")
    assert [u.status for u in report.units] == ["eligible", "refused"]
    expected, _ = mint_shard_iri(source_uri_for(RUN_CORPUS, SOURCE_FILE), SENTENCES[0])
    assert report.units[0].shard_iri == expected
    assert provider.requests == [] and not root.exists()


async def test_duplicate_units_in_one_run_mint_once(
    tmp_path: Path, provider: FakeProvider, oracle
) -> None:
    run, src = write_run(tmp_path, [
        unit("u1", SENTENCES[0]),
        unit("u2", SENTENCES[0], text="Lead on cross-examination so the witness can "
                                      "only agree with you."),
    ])
    gov = await governed_corpus(tmp_path / "storage")
    report = await _mint(tmp_path, run, src, provider, signing_key=gov.extractor.sk,
                         oracle=oracle)
    assert [u.status for u in report.units] == ["minted", "refused"]
    assert report.units[1].code == "duplicate_in_run"
    assert len(await _shards(gov.root)) == 1


async def test_unsupported_unit_type_and_pre_b9_runs_are_refused(
    tmp_path: Path, provider: FakeProvider
) -> None:
    run, src = write_run(tmp_path, [
        unit("cite", SENTENCES[0], unit_type="citation"),
        unit("b9", SENTENCES[1], tags=[llm_tag()], events=lineage(concept=True)),
        unit("ruler", SENTENCES[2], tags=[ruler_tag()]),
    ], b9=False)
    report = await _mint(tmp_path, run, src, provider, dry_run=True,
                         extractor_did="did:key:z6MkSyntheticExtractorOnly")
    by = {u.unit_id: u for u in report.units}
    assert by["cite"].code == "unit_type_unsupported"
    assert by["b9"].code == "iri_unverified"
    assert by["ruler"].status == "eligible"  # a ruler IRI needs no B9 evidence
