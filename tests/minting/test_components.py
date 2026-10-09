"""Drain U8 components: eligibility checks, the mint.fields template, mapping rules, CLI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from click.testing import CliRunner

from folio_insights.llm.schemas import MintFieldsOutput
from folio_insights.llm.templates import (
    CONCEPT,
    DISTILL,
    MINT_FIELDS,
    combined_prompt_hash,
    get_template,
    template_for_task,
)
from folio_insights.minting.eligibility import (
    REFUSAL_CODES,
    Eligible,
    Refused,
    RunEvidence,
    evaluate,
)
from folio_insights.minting.fields import OracleBranchResolver
from folio_insights.minting.mapper import (
    extractor_model,
    prompt_hash,
    source_uri_for,
)
from folio_insights.models.knowledge_unit import KnowledgeUnit
from folio_insights.rubric.adapters import SourceResolver
from folio_insights.shards import ShardEnvelope

from tests.minting.conftest import (
    CORPUS,
    DAUBERT,
    FAKE_KEYS,
    MODEL,
    SENTENCES,
    SOURCE,
    FakeProvider,
    governed_corpus,
    lineage,
    unit,
    write_run,
)

B9 = RunEvidence(b9_verified=True, judge_enabled=True)


def _evaluate(tmp: Path, data: dict, *, run: RunEvidence = B9, seen: set | None = None):
    _, src = write_run(tmp, [data])
    return evaluate(KnowledgeUnit.model_validate(data), SourceResolver(src).resolve_path,
                    run=run, seen=seen)


# ── the template ─────────────────────────────────────────────────────────


def test_mint_fields_template_is_registered_with_the_envelope_enums() -> None:
    assert get_template("mint.fields.v1") is MINT_FIELDS
    assert template_for_task("mint_fields") is MINT_FIELDS
    assert MINT_FIELDS.version == "1" and MINT_FIELDS.output_schema is MintFieldsOutput
    for name in ("layer", "predication_mode", "fork", "speech_act"):
        schema_enum = MintFieldsOutput.model_fields[name].annotation.model_fields["value"].annotation
        assert get_args(schema_enum) == get_args(ShardEnvelope.model_fields[name].annotation)
    assert set(MintFieldsOutput.model_fields) == {
        "sense", "reference", "logical_form_imputed", "layer", "predication_mode", "fork",
        "speech_act"}
    # The hash covers identity, never unit text.
    assert MINT_FIELDS.hash == MINT_FIELDS.hash and len(MINT_FIELDS.hash) == 64
    rendered = MINT_FIELDS.messages(span="{x}", unit_text="t", unit_type="advice", section="s")
    assert "{x}" in rendered[1]["content"]  # a brace in source text is not re-formatted


def test_every_refusal_code_is_distinct() -> None:
    assert len(REFUSAL_CODES) == len(set(REFUSAL_CODES))


# ── eligibility ──────────────────────────────────────────────────────────


def test_snippet_route_returns_the_verified_slice_and_its_offsets(tmp_path: Path) -> None:
    # A loose span, but the snippet is verbatim source text: the slice is recovered.
    data = unit("u", SENTENCES[1], span=(0, 5), anchor_score=0.0, anchor_verified=False,
                snippet=SENTENCES[1])
    data.pop("anchor_score"), data.pop("anchor_verified")
    outcome = _evaluate(tmp_path, data)
    assert isinstance(outcome, Eligible), outcome
    start, end = outcome.span_offsets
    assert SOURCE[start:end] == outcome.verified_span == SENTENCES[1]
    assert outcome.method == "snippet" and outcome.match == 1.0


def test_stored_unverified_anchor_is_refused_even_when_span_and_snippet_agree(
    tmp_path: Path,
) -> None:
    outcome = _evaluate(tmp_path, unit("u", SENTENCES[0], anchor_score=0.62,
                                       anchor_verified=False))
    assert isinstance(outcome, Refused) and outcome.code == "anchor_unverified"


def test_missing_source_is_source_unavailable(tmp_path: Path) -> None:
    data = unit("u", SENTENCES[0])
    data["original_span"]["source_file"] = data["source_file"] = "sources/absent.txt"
    outcome = _evaluate(tmp_path, data)
    assert isinstance(outcome, Refused) and outcome.code == "source_unavailable"


def test_all_reasons_are_recorded_and_the_cheapest_is_primary(tmp_path: Path) -> None:
    events = [{"stage": "distiller", "action": "distill", "detail": "no template"}]
    data = unit("u", SENTENCES[0], tags=[{"iri": DAUBERT, "label": "x", "confidence": 0.9,
                                          "extraction_path": "semantic"}],
                events=events, anchor_score=0.4, anchor_verified=False)
    outcome = _evaluate(tmp_path, data)
    assert isinstance(outcome, Refused)
    codes = [r.code for r in outcome.reasons]
    assert codes == ["iri_unjudged", "no_prompt_identity", "anchor_unverified"]
    assert outcome.code == "iri_unjudged"


def test_llm_tags_without_a_concept_template_lack_prompt_identity(tmp_path: Path) -> None:
    tag = {"iri": DAUBERT, "label": "x", "confidence": 0.9, "extraction_path": "llm",
           "judge_status": "judged"}
    outcome = _evaluate(tmp_path, unit("u", SENTENCES[0], tags=[tag], events=lineage()))
    assert isinstance(outcome, Refused) and outcome.code == "no_prompt_identity"
    outcome = _evaluate(tmp_path, unit("u", SENTENCES[0], tags=[tag],
                                       events=lineage(concept=True)))
    assert isinstance(outcome, Eligible)


def test_metadata_units_and_unknown_paths_are_refused(tmp_path: Path) -> None:
    events = [*lineage(), {"stage": "folio_tagger", "action": "skip", "detail": "metadata"}]
    outcome = _evaluate(tmp_path, unit("u", SENTENCES[0], events=events))
    assert isinstance(outcome, Refused) and outcome.code == "metadata_unit"
    tag = {"iri": DAUBERT, "label": "x", "confidence": 0.9, "extraction_path": "manual"}
    outcome = _evaluate(tmp_path, unit("u", SENTENCES[0], tags=[tag]))
    assert isinstance(outcome, Refused) and outcome.code == "iri_unverified"
    outcome = _evaluate(tmp_path, unit("u", SENTENCES[0], tags=[]))
    assert isinstance(outcome, Refused) and outcome.code == "no_folio_concept"


def test_run_evidence_reads_the_tagger_summary() -> None:
    assert RunEvidence.from_extraction({}) == RunEvidence()
    ev = RunEvidence.from_extraction({"summary": {"folio_tagger": {
        "carried_iris_rejected": 2, "judge_enabled": True}}})
    assert ev == RunEvidence(b9_verified=True, judge_enabled=True)


# ── mapping rules ────────────────────────────────────────────────────────


def test_source_uri_is_stable_and_percent_encoded() -> None:
    assert source_uri_for("my corpus", "sources/ch 1.md") == \
        "urn:folio:source:my%20corpus:sources/ch%201.md"
    resolver_tail = source_uri_for("c", "sources/a.txt").rsplit(":", 1)[-1]
    assert resolver_tail == "sources/a.txt"
    with pytest.raises(ValueError):
        source_uri_for("", "a.txt")


def test_prompt_hash_is_the_flat_combined_hash_of_lineage_and_minter_templates() -> None:
    ku = KnowledgeUnit.model_validate(unit("u", SENTENCES[0], events=lineage(concept=True)))
    expected = combined_prompt_hash([DISTILL.hash, CONCEPT.hash, MINT_FIELDS.hash])
    assert prompt_hash(ku, [MINT_FIELDS.hash]) == expected
    assert prompt_hash(ku, [MINT_FIELDS.hash, MINT_FIELDS.hash]) == expected
    reordered = ku.model_copy(update={"lineage": list(reversed(ku.lineage))})
    assert prompt_hash(reordered, [MINT_FIELDS.hash]) == expected


def test_extractor_model_names_minter_and_lineage_routes() -> None:
    ku = KnowledgeUnit.model_validate(unit("u", SENTENCES[0]))
    summary = {"llm": {"by_task": [{"task": "distiller", "provider": "google",
                                    "model": "gemini-2.5-flash-lite"}]}}
    assert extractor_model(ku, {"openai:gpt-4.1-mini"}, summary) == \
        "google:gemini-2.5-flash-lite+openai:gpt-4.1-mini"
    assert extractor_model(ku, {"openai:gpt-4.1-mini"}, {}) == "openai:gpt-4.1-mini"


def test_oracle_branch_resolver_types_through_the_oracle(oracle) -> None:
    from folio_insights.bfo.spine import BRANCH_BY_LABEL, top_level_branches

    resolver = OracleBranchResolver(oracle)
    assert tuple(resolver.parents(DAUBERT)) == (BRANCH_BY_LABEL["service"].iri,)
    assert [b.category for b in top_level_branches(DAUBERT, resolver)] == ["occurrent_process"]
    assert tuple(resolver.parents("https://folio.openlegalstandard.org/UNKNOWN")) == ()


# ── the CLI ──────────────────────────────────────────────────────────────


async def test_cli_mints_signs_and_writes_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oracle
) -> None:
    import asyncio

    from folio_insights.cli import cli
    from folio_insights.identity.keys import generate_keypair
    from folio_insights.llm import set_default_port
    from folio_insights.storage import CorpusStorageContext

    from tests.storage.conftest import role_assertion

    root = tmp_path / "storage"
    gov = await governed_corpus(root)
    key_path = tmp_path / "keys" / "extractor.jwk"
    did = generate_keypair(key_path)
    ctx = await CorpusStorageContext.open(root, CORPUS)
    try:
        from datetime import UTC, datetime

        await ctx.governance.append(
            role_assertion(CORPUS, gov.admin, did, "extractor", datetime.now(UTC)))
    finally:
        await ctx.close()

    provider = FakeProvider()
    set_default_port(provider.port())
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEYS["openai"])
    run, src = write_run(tmp_path, [unit("u1", SENTENCES[0])])
    out = tmp_path / "report.json"
    oracle_path = Path(__file__).resolve().parents[1] / "rubric" / "fixtures" / "folio_oracle.json"
    args = ["mint", CORPUS, "--run", str(run), "--sources", str(src),
            "--source-visibility", "public", "--signing-key", str(key_path),
            "--llm-provider", "openai", "--llm-model", MODEL, "--framework", "us.federal.fre",
            "--oracle", str(oracle_path), "--report", str(out), "--corpus-root", str(root)]
    try:
        result = await asyncio.to_thread(CliRunner().invoke, cli, args)
    finally:
        set_default_port(None)
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text())
    assert report["counts"]["by_status"] == {"minted": 1}
    assert report["units"][0]["extract_event"] == "appended"
    assert report["run"]["extractor_did"] == did and report["publishable"] is False
    assert FAKE_KEYS["openai"] not in result.output + out.read_text()

    refused = await asyncio.to_thread(CliRunner().invoke, cli, [
        "mint", CORPUS, "--run", str(run), "--sources", str(src),
        "--source-visibility", "non-public", "--extractor-did", did,
        "--corpus-root", str(root)])
    assert refused.exit_code == 1 and "source_visibility" in refused.output

    marked = await asyncio.to_thread(CliRunner().invoke, cli, [
        "mint", "fresh-corpus", "--mark-local-only", "--corpus-root", str(root)])
    assert marked.exit_code == 0
    from folio_insights.minting import is_local_only

    assert is_local_only(root, "fresh-corpus") and not is_local_only(root, CORPUS)

    usage = await asyncio.to_thread(CliRunner().invoke, cli, ["mint", CORPUS])
    assert usage.exit_code == 2
