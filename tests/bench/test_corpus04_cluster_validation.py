"""CORPUS-04 measures the real validator with local synthetic inputs only."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from folio_insights.bench.corpus04 import CORPORA, cluster_validation, run_corpus04
from folio_insights.storage import CorpusStorageContext
from folio_insights.validation.coverage import TaskNode

from tests.validation.conftest import FakeNli, FakeReasoner, folio, type_triple, vshard

pytestmark = pytest.mark.storage


def records(*, contradiction: bool = False):
    return [
        vshard(1, source_uri="urn:x:benchmark", reference=folio("Synthetic"),
               sense="The synthetic rule is applicable.", speech_act="holding"),
        vshard(2, source_uri="urn:x:benchmark", reference=folio("Synthetic"),
               sense=("The synthetic rule is not applicable." if contradiction
                      else "A second synthetic rule applies."), speech_act="holding"),
    ]


def inputs(**overrides):
    values = {
        "tasks": [TaskNode("task", "Synthetic task", folio("Synthetic"))],
        "reasoner": None,
        "nli": FakeNli(),
    }
    values.update(overrides)
    return values


async def test_actual_validator_reports_fallback_coverage_and_does_not_write(tmp_path: Path):
    ctx = await CorpusStorageContext.open(tmp_path, "benchmark")
    try:
        await ctx.ingest_shards(records())
        head = await ctx.journal_head()
        ledger = await ctx.proposals.entries()
        options = inputs()
        result = await cluster_validation(ctx, **options)
        assert result["status"] == "pass", result
        assert result["shards"] == 2
        assert result["clusters"] > 0
        assert result["checked_clusters"] == result["clusters"]
        assert result["cluster_modes"] == {"nli_fallback": result["clusters"]}
        assert result["checkers"] == {
            "hermit": "disabled", "nli": "available", "coverage": "ran", "crossref": "ran",
        }
        assert result["task_leaves"] == result["mapped_task_leaves"] == 1
        assert result["findings"] == result["warnings"] == 0
        assert result["validate_seconds"] >= 0
        assert result["applied"] is False
        assert options["nli"].scored
        assert await ctx.journal_head() == head
        assert await ctx.proposals.entries() == ledger
    finally:
        await ctx.close()


async def test_actual_contradiction_fails_without_source_text(tmp_path: Path):
    ctx = await CorpusStorageContext.open(tmp_path, "benchmark")
    try:
        await ctx.ingest_shards(records(contradiction=True))
        result = await cluster_validation(ctx, **inputs())
        assert result["status"] == "fail"
        assert result["by_kind"] == {"contradiction": 1}
        assert result["findings"] == result["warnings"] == 1
        serialized = json.dumps(result)
        assert "The synthetic rule" not in serialized
        assert "urn:x:benchmark" not in serialized
        assert "proposals" not in result
    finally:
        await ctx.close()


@pytest.mark.parametrize(("options", "reason"), [
    ({"tasks": None}, "task_tree_missing"),
    ({"tasks": []}, "task_tree_empty"),
    ({"tasks": [TaskNode("task", "Unmapped synthetic task")]}, "task_leaves_unmapped"),
    ({"nli": None}, "unchecked_clusters"),
    ({"min_size": 3}, "no_eligible_clusters"),
    ({"consistency": False}, "unchecked_clusters"),
    ({"coverage": False}, "coverage_not_run"),
    ({"crossref": False}, "crossref_not_run"),
])
async def test_unexecuted_required_checks_never_pass(tmp_path: Path, options, reason):
    ctx = await CorpusStorageContext.open(tmp_path, "benchmark")
    try:
        await ctx.ingest_shards(records())
        result = await cluster_validation(ctx, **inputs(**options))
        assert result["status"] == "incomplete", result
        assert reason in result["reasons"]
    finally:
        await ctx.close()


async def test_empty_input_never_passes(tmp_path: Path):
    ctx = await CorpusStorageContext.open(tmp_path, "benchmark")
    try:
        result = await cluster_validation(ctx, **inputs(tasks=[]))
        assert result["status"] == "incomplete"
        assert "empty_input" in result["reasons"]
        assert result["shards"] == result["clusters"] == 0
    finally:
        await ctx.close()


async def test_formal_inputs_reach_actual_validator(tmp_path: Path):
    ctx = await CorpusStorageContext.open(tmp_path, "benchmark")
    try:
        formal = records()
        formal[0] = formal[0].model_copy(update={"triple": type_triple("urn:x:entity", folio("A"))})
        formal[1] = formal[1].model_copy(update={"triple": type_triple("urn:x:entity", folio("B"))})
        await ctx.ingest_shards(formal)
        reasoner = FakeReasoner()
        result = await cluster_validation(ctx, **inputs(
            reasoner=reasoner, disjoint_seeds=[(folio("A"), folio("B"))],
        ))
        assert result["status"] == "fail"
        assert result["by_kind"] == {"contradiction": 1}
        assert result["cluster_modes"] == {"formal+textual": result["clusters"]}
        assert reasoner.calls > 0
    finally:
        await ctx.close()


class FailingNli:
    def contradiction_probabilities(self, pairs):
        raise RuntimeError("private source excerpt must never enter the benchmark")


async def test_backend_failure_is_sanitized_and_incomplete(tmp_path: Path):
    ctx = await CorpusStorageContext.open(tmp_path, "benchmark")
    try:
        await ctx.ingest_shards(records())
        result = await cluster_validation(ctx, **inputs(nli=FailingNli()))
        assert result["status"] == "incomplete"
        assert result["checkers"]["nli"] == "failed"
        assert "private source excerpt" not in json.dumps(result)
    finally:
        await ctx.close()


def write_sources(directory: Path, names=CORPORA):
    directory.mkdir()
    for name in names:
        (directory / f"{name}.jsonl").write_text("".join(
            json.dumps(record.model_dump(mode="json")) + "\n" for record in records()
        ))


async def test_all_file_sources_can_meet_harness_but_are_synthetic_test_evidence(tmp_path: Path):
    sources = tmp_path / "sources"
    write_sources(sources)
    report = await run_corpus04(tmp_path / "root", corpora_dir=sources,
                                cluster_inputs={name: inputs() for name in CORPORA})
    assert report["corpus_04"] == "met"
    assert report["unmet_reasons"] == []
    assert all(c["cluster_validation"]["status"] == "pass" for c in report["corpora"])
    assert all(c["shacl"]["full_shacl"] == "pass" for c in report["corpora"])
    # This exercises the file-input branch only; these fixtures prove no real-world acceptance.


async def test_clean_standins_still_cannot_satisfy_corpus04(tmp_path: Path, monkeypatch):
    from folio_insights.bench import corpus04

    monkeypatch.delenv(corpus04.ENV_DIR, raising=False)
    monkeypatch.setattr(corpus04, "synthetic_standin", lambda *args: [
        record.model_dump(mode="json") for record in records()
    ])
    report = await run_corpus04(tmp_path / "root",
                                cluster_inputs={name: inputs() for name in CORPORA})
    assert report["corpus_04"] == "unmet"
    assert all(c["cluster_validation"]["status"] == "pass" for c in report["corpora"])
    assert len(report["unmet_reasons"]) == 3
    assert all("synthetic stand-in" in reason for reason in report["unmet_reasons"])


async def test_mixed_file_and_standin_inputs_stay_unmet(tmp_path: Path, monkeypatch):
    from folio_insights.bench import corpus04

    sources = tmp_path / "sources"
    write_sources(sources, names=("fre",))
    monkeypatch.setattr(corpus04, "synthetic_standin", lambda *args: [
        record.model_dump(mode="json") for record in records()
    ])
    report = await run_corpus04(tmp_path / "root", corpora_dir=sources,
                                cluster_inputs={name: inputs() for name in CORPORA})
    assert report["corpus_04"] == "unmet"
    assert len(report["unmet_reasons"]) == 2
    assert all(c["cluster_validation"]["status"] == "pass" for c in report["corpora"])


async def test_validator_exception_is_sanitized_closes_context_and_continues(tmp_path: Path, monkeypatch):
    from folio_insights.validation import validator

    sources = tmp_path / "sources"
    write_sources(sources)
    original = validator.validate_corpus
    failed_contexts = []

    async def failing_first(ctx, **kwargs):
        if ctx.corpus == CORPORA[0]:
            failed_contexts.append(ctx)
            raise RuntimeError("private exception payload")
        return await original(ctx, **kwargs)

    monkeypatch.setattr(validator, "validate_corpus", failing_first)
    report = await run_corpus04(tmp_path / "root", corpora_dir=sources,
                                cluster_inputs={name: inputs() for name in CORPORA})
    first, *rest = report["corpora"]
    assert first["cluster_validation"]["status"] == "error"
    assert first["cluster_validation"]["reason"] == "cluster_validator_execution_failed"
    assert "private exception payload" not in json.dumps(report)
    assert all(c["cluster_validation"]["status"] == "pass" for c in rest)
    assert report["corpus_04"] == "unmet"
    assert failed_contexts[0].closed
    ctx = await CorpusStorageContext.open(tmp_path / "root", CORPORA[0])
    await ctx.close()
