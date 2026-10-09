"""Phase 9 U1 (R4): the structured report and ``folio-insights validate clusters``."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from folio_insights.cli import cli
from folio_insights.shards import Triple
from folio_insights.storage import CorpusStorageContext
from folio_insights.validation.report import Finding, ValidationReport
from folio_insights.validation.validator import build_validator

from tests.validation.conftest import FakeNli, folio, iri, type_triple, vshard

ENFORCEABLE = "A gratuitous promise without consideration is enforceable."
UNENFORCEABLE = "A gratuitous promise without consideration is not enforceable."


def corpus_shards():
    return [
        vshard(1, source_uri="urn:x:source/a", sense=ENFORCEABLE,
               triple=Triple(subject=folio("Consideration"), predicate="urn:x:p", object="urn:x:o"),
               speech_act="practitioner_advice"),
        vshard(2, source_uri="urn:x:source/b", sense=UNENFORCEABLE,
               framework_id="us.restatement_2d.contracts"),
        vshard(3, source_uri="urn:x:source/b", framework_id="uk.england.common_law",
               depends_on_precedents=[iri(2)]),
    ]


def make_corpus(root: Path, shards) -> None:
    async def go() -> None:
        ctx = await CorpusStorageContext.open(root, "corpus-a")
        try:
            await ctx.ingest_shards(shards)
        finally:
            await ctx.close()

    asyncio.run(go())


def journal_head(root: Path) -> int:
    async def go() -> int:
        ctx = await CorpusStorageContext.open(root, "corpus-a")
        try:
            return await ctx.journal_head()
        finally:
            await ctx.close()

    return asyncio.run(go())


@pytest.fixture
def fake_nli(monkeypatch):
    import folio_insights.validation.nli as nli

    scorer = FakeNli()
    monkeypatch.setattr(nli, "default_nli_scorer", lambda: scorer)
    return scorer


def test_report_round_trips_and_never_claims_application(registry) -> None:
    report = build_validator(registry, reasoner=None, nli=FakeNli()).validate(corpus_shards(), corpus="c")
    data = json.loads(report.to_json())
    assert data["format"] == "folio-insights/cluster-validation/v1"
    assert data["applied"] is False
    assert data["summary"]["by_kind"] == {"contradiction": 1, "cross_framework_citation": 1}
    assert data["checkers"] == {"hermit": "disabled", "nli": "available",
                                "coverage": "skipped: no task tree supplied", "crossref": "ran"}
    data.pop("summary")
    assert ValidationReport.model_validate(data) == report
    with pytest.raises(ValueError):
        ValidationReport(applied=True)  # type: ignore[arg-type]
    text = report.render_text()
    assert "nothing was applied" in text and "contradiction (nli)" in text
    assert "cross_framework_citation (crossref)" in text and "1. " in text


def test_finding_order_is_stable(registry) -> None:
    a = build_validator(registry, reasoner=None, nli=FakeNli()).validate(corpus_shards())
    b = build_validator(registry, reasoner=None, nli=FakeNli()).validate(list(reversed(corpus_shards())))
    assert [f.id for f in a.findings] == [f.id for f in b.findings]
    assert all(isinstance(f, Finding) for f in a.findings)


def test_cli_reports_findings_without_writing(tmp_path: Path, fake_nli) -> None:
    root = tmp_path / "corpora"
    make_corpus(root, corpus_shards())
    head = journal_head(root)
    tasks = tmp_path / "task_tree.json"
    tasks.write_text(json.dumps([
        {"id": "t1", "parent_id": None, "label": "Argue consideration",
         "folio_iri": folio("Consideration")},
    ]))
    result = CliRunner().invoke(cli, [
        "validate", "clusters", "--corpus", "corpus-a", "--corpus-root", str(root),
        "--no-hermit", "--tasks", str(tasks),
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    kinds = data["summary"]["by_kind"]
    assert kinds == {"contradiction": 1, "coverage_gap": 1, "cross_framework_citation": 1}
    [gap] = [f for f in data["findings"] if f["kind"] == "coverage_gap"]
    assert gap["detail"]["non_authority_shards"] == [iri(1)]
    assert data["checkers"]["hermit"] == "disabled"
    assert all(c["mode"] in {"nli_fallback", "unchecked"} for c in data["clusters"])
    assert journal_head(root) == head  # proposals are never applied


def test_cli_text_out_file_and_fail_on_findings(tmp_path: Path, fake_nli) -> None:
    root = tmp_path / "corpora"
    make_corpus(root, corpus_shards())
    out = tmp_path / "report.txt"
    result = CliRunner().invoke(cli, [
        "validate", "clusters", "--corpus", "corpus-a", "--corpus-root", str(root),
        "--no-hermit", "--format", "text", "--out", str(out), "--fail-on-findings",
    ])
    assert result.exit_code == 1
    assert result.output.strip() == str(out)
    assert "Cluster validation — corpus corpus-a" in out.read_text()


def test_cli_formal_inputs_and_no_nli(tmp_path: Path, monkeypatch) -> None:
    """--tbox / --disjoint / --folio-parents parse; with no checker able to run a
    cluster reads unchecked (never consistent)."""
    root = tmp_path / "corpora"
    make_corpus(root, [vshard(1, triple=type_triple("urn:x:p/1", folio("A"))),
                       vshard(2, triple=type_triple("urn:x:p/1", folio("B")))])
    tbox = tmp_path / "tbox.ttl"
    tbox.write_text(f'<{folio("A")}> <http://www.w3.org/2000/01/rdf-schema#label> "A" ;'
                    f' <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{folio("Top")}> .\n')
    parents = tmp_path / "parents.json"
    parents.write_text(json.dumps({folio("A"): [folio("Top")], folio("B"): [folio("Top")]}))
    result = CliRunner().invoke(cli, [
        "validate", "clusters", "--corpus", "corpus-a", "--corpus-root", str(root),
        "--no-hermit", "--no-nli", "--tbox", str(tbox), "--disjoint", folio("A"), folio("B"),
        "--folio-parents", str(parents), "--doctrinal-depth", "0", "--axis", "doctrinal",
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [c["id"] for c in data["clusters"]] == [f"doctrinal:{folio('Top')}"]
    assert data["clusters"][0]["mode"] == "unchecked"
    assert data["clusters"][0]["formal_axiom_count"] == 2


def test_cli_refuses_a_missing_corpus_or_bad_input(tmp_path: Path) -> None:
    root = tmp_path / "corpora"
    missing = CliRunner().invoke(cli, ["validate", "clusters", "--corpus", "nope",
                                       "--corpus-root", str(root), "--no-nli"])
    assert missing.exit_code == 2 and "no corpus 'nope'" in missing.output
    make_corpus(root, corpus_shards())
    bad = tmp_path / "parents.json"
    bad.write_text(json.dumps({"x": "not a list"}))
    result = CliRunner().invoke(cli, ["validate", "clusters", "--corpus", "corpus-a",
                                      "--corpus-root", str(root), "--no-nli",
                                      "--folio-parents", str(bad)])
    assert result.exit_code == 2 and "list of parent IRIs" in result.output
