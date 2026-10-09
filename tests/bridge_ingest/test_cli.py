"""``folio-insights bridge-ingest`` / ``bridge-status`` through the root CLI."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from folio_insights.cli import cli
from tests.bridge_ingest.conftest import SYNTHETIC_RECORD, fixture_record_dict


def test_bridge_ingest_and_status(tmp_path: Path) -> None:
    root = tmp_path / "cli-root"
    runner = CliRunner()
    args = ["bridge-ingest", str(SYNTHETIC_RECORD), "--corpus", "cli-corpus",
            "--corpus-root", str(root), "--json"]
    first = runner.invoke(cli, args)
    assert first.exit_code == 0, first.output
    report = json.loads(first.output)
    expected = {
        p["content_iri"] for p in fixture_record_dict()["propositions"] if p.get("content_iri")
    }
    assert set(report["created_iris"]) == expected

    again = runner.invoke(cli, args[:-1])
    assert again.exit_code == 0, again.output
    assert f"created 0, existing {len(expected)}" in again.output

    iri = sorted(expected)[0]
    status = runner.invoke(
        cli, ["bridge-status", iri, "--corpus", "cli-corpus", "--corpus-root", str(root)]
    )
    assert status.exit_code == 0, status.output
    body = json.loads(status.output)
    assert body["results"][0]["present"] is True

    missing = runner.invoke(
        cli, ["bridge-status", iri, "--corpus", "nope", "--corpus-root", str(root)]
    )
    assert missing.exit_code == 1
    bad = runner.invoke(cli, ["bridge-status", "x", "--corpus", "cli-corpus", "--corpus-root", str(root)])
    assert bad.exit_code == 2


def test_bridge_ingest_refuses_bad_record(tmp_path: Path) -> None:
    data = fixture_record_dict()
    data["propositions"][0]["content_iri"] = "urn:folio:shard/" + "0" * 32
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = CliRunner().invoke(
        cli, ["bridge-ingest", str(path), "--corpus", "c", "--corpus-root", str(tmp_path / "r")]
    )
    assert result.exit_code == 1
    assert "ContentIriMismatch" in result.output
