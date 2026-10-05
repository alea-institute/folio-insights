"""CORPUS-04 harness (Phase 13 exit criterion 7, Phase 11 plan R10).

The three real benchmark corpora (v1 advocacy, FRE, Restatement of
Contracts) are not in the repository, so the harness runs on synthetic
stand-ins. Each stand-in loads and passes full SHACL, yet the report must
still read CORPUS-04 ``unmet``: a stand-in is not the real corpus, and the
Phase 9.P1 cluster validator is not built.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from folio_insights.bench.corpus04 import (
    CLUSTER_UNAVAILABLE,
    CORPORA,
    discover,
    run_corpus04,
    synthetic_standin,
)

pytestmark = pytest.mark.storage


def test_standins_are_deterministic_and_cover_every_subtype() -> None:
    a, b = synthetic_standin("fre", 60), synthetic_standin("fre", 60)
    assert a == b
    assert {r["shard_type"] for r in a} == {
        "simple_assertion", "disputed_proposition", "conflicting_authorities", "gloss", "hypothesis",
    }
    assert a[1]["supersedes"] == a[0]["shard_iri"] and a[0]["superseded_by"] == a[1]["shard_iri"]


async def test_harness_runs_on_standins_and_reports_corpus04_unmet(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("FOLIO_INSIGHTS_CORPUS04_DIR", raising=False)
    report = await run_corpus04(tmp_path / "root", standin_shards=120)
    assert [c["name"] for c in report["corpora"]] == list(CORPORA)
    for entry in report["corpora"]:
        assert entry["source"] == "synthetic" and entry["records"] == 120
        assert entry["shacl"]["full_shacl"] == "pass", entry
        assert entry["shacl"]["conforms"] and entry["shacl"]["violations"] == 0
        assert entry["cluster_validation"] == {"status": "unavailable", "reason": CLUSTER_UNAVAILABLE}
    assert report["corpus_04"] == "unmet"
    assert len(report["unmet_reasons"]) == 6  # stand-in + cluster, per corpus
    json.dumps(report)


async def test_a_real_corpus_file_is_used_but_cluster_step_keeps_it_unmet(tmp_path: Path) -> None:
    corpora = tmp_path / "corpora"
    corpora.mkdir()
    # A "real" file for one corpus (synthetic content standing in for the
    # operator-provided JSONL; the harness only cares about the format).
    with (corpora / "fre.jsonl").open("w") as handle:
        for record in synthetic_standin("fre-file", 40):
            handle.write(json.dumps(record) + "\n")
    sources = {s.name: s for s in discover(corpora)}
    assert sources["fre"].kind == "real" and len(sources["fre"].records) == 40
    assert sources["v1-advocacy"].kind == "synthetic"

    report = await run_corpus04(tmp_path / "root", corpora_dir=corpora, standin_shards=30)
    fre = next(c for c in report["corpora"] if c["name"] == "fre")
    assert fre["source"] == "real" and fre["shacl"]["full_shacl"] == "pass"
    assert report["corpus_04"] == "unmet"
    assert "fre: cluster validation unavailable" in report["unmet_reasons"]
    assert not any(r.startswith("fre: synthetic") for r in report["unmet_reasons"])
