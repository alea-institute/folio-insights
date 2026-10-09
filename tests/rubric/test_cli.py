"""``folio-insights rubric score`` / ``rubric gold`` (R7, R8)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from folio_insights.cli import cli

from tests.rubric.conftest import GOLD_DIR, ORACLE_PATH, SOURCE, SOURCE_FILE, build_corpus, judged_all

CASE = GOLD_DIR / "ep001_generative_unanchored"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_rubric_is_registered(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["rubric", "--help"])
    assert result.exit_code == 0
    assert "score" in result.output and "gold" in result.output


def test_score_unit_run_json(runner: CliRunner) -> None:
    result = runner.invoke(cli, [
        "rubric", "score", str(CASE / "extraction.json"), "--sources", str(CASE / "source"),
        "--oracle", str(ORACLE_PATH), "--json",
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["artifact"]["kind"] == "unit_run"
    assert data["publishable"] is False
    by_id = {c["id"]: c for c in data["criteria"]}
    assert by_id["RUB-EXTRACT-05"]["gate"] == "fail"
    assert by_id["RUB-EXTRACT-10"]["status"] == "not_scored"
    assert len(data["not_scored"]) == 11


def test_score_directory_text_and_strict(runner: CliRunner) -> None:
    args = ["rubric", "score", str(CASE), "--sources", str(CASE / "source")]
    text = runner.invoke(cli, args)
    assert text.exit_code == 0, text.output
    assert "RUB-EXTRACT-05" in text.output and "publishable: false" in text.output
    strict = runner.invoke(cli, [*args, "--strict"])
    assert strict.exit_code == 3


def test_score_run_option_overrides_target(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["rubric", "score", "label-only", "--run",
                                 str(CASE / "extraction.json"), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["artifact"]["kind"] == "unit_run"


def test_score_shard_corpus_publishable(runner: CliRunner, tmp_path: Path) -> None:
    import asyncio

    root = tmp_path / "storage"
    shards = asyncio.run(build_corpus(root))
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / SOURCE_FILE).write_text(SOURCE, encoding="utf-8")
    judged = tmp_path / "judged.json"
    judged.write_text(json.dumps(judged_all(3, unit_ids=[s.shard_iri for s in shards])),
                      encoding="utf-8")
    args = ["rubric", "score", "rubric-corpus", "--corpus-root", str(root),
            "--sources", str(sources), "--oracle", str(ORACLE_PATH)]
    unjudged = runner.invoke(cli, [*args, "--json"])
    assert unjudged.exit_code == 0, unjudged.output
    assert json.loads(unjudged.output)["publishable"] is False
    result = runner.invoke(cli, [*args, "--judged", str(judged), "--json", "--strict"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["artifact"]["kind"] == "shard_corpus"
    assert data["publishable"] is True and data["not_scored"] == []


@pytest.mark.parametrize("extra, message", [
    (["--oracle", "/nonexistent/oracle.json"], "oracle file not found"),
    (["--judged", "/nonexistent/judged.json"], "judged-scores file not found"),
])
def test_score_bad_inputs_exit_one(runner: CliRunner, extra: list[str], message: str) -> None:
    result = runner.invoke(cli, ["rubric", "score", str(CASE), *extra])
    assert result.exit_code == 1
    assert message in result.output


def test_score_unknown_corpus_exits_one(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(cli, ["rubric", "score", "no-such-corpus",
                                 "--corpus-root", str(tmp_path / "root")])
    assert result.exit_code == 1
    assert "no corpus 'no-such-corpus'" in result.output


def test_gold_command_passes_on_committed_set(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["rubric", "gold"])
    assert result.exit_code == 0, result.output
    assert "0 drift finding(s)" in result.output
    assert "mapping-gold  agreement 0/1 = 0.0" in result.output
    as_json = runner.invoke(cli, ["rubric", "gold", "--json"])
    assert as_json.exit_code == 0 and json.loads(as_json.output)["ok"] is True


def test_gold_command_exits_nonzero_on_drift(runner: CliRunner, tmp_path: Path) -> None:
    gold = tmp_path / "gold"
    shutil.copytree(GOLD_DIR, gold)
    path = gold / "dedup_not_held" / "expected.json"
    expected = json.loads(path.read_text(encoding="utf-8"))
    expected["publishable"] = True
    path.write_text(json.dumps(expected), encoding="utf-8")
    result = runner.invoke(cli, ["rubric", "gold", "--gold-dir", str(gold)])
    assert result.exit_code == 1
    assert "DRIFT dedup_not_held" in result.output


def test_gold_command_missing_dir_exits_one(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(cli, ["rubric", "gold", "--gold-dir", str(tmp_path / "absent")])
    assert result.exit_code == 1 and "not found" in result.output
