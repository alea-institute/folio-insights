"""``--llm-provider`` / ``--llm-model`` on ``extract`` and ``discover`` (Phase 10 U1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from folio_insights.cli import cli
from folio_insights.llm import current_context, resolve_route
from tests.llm.conftest import FAKE_KEYS, LEAK_MARKER


@pytest.fixture()
def captured(monkeypatch):
    seen: dict = {}

    def _snapshot() -> None:
        ctx = current_context()
        seen["provider"], seen["model"] = ctx.provider, ctx.model
        seen["key"] = ctx.credentials.get("anthropic")
        seen["cap"] = ctx.meter.cap if ctx.meter is not None else "no meter"
        seen["routes"] = {t: resolve_route(t) for t in ("distiller", "concept", "contradiction")}

    async def fake_extract_run(self, source_dir, corpus_name=None, resume=True, **kw):
        _snapshot()
        from folio_insights.pipeline.stages.base import InsightsJob

        return InsightsJob(corpus_name=corpus_name or "c", source_dir=source_dir)

    async def fake_discover_run(self, corpus_name, resume=True, **kw):
        _snapshot()
        from folio_insights.models.task import DiscoveryJob

        return DiscoveryJob(corpus_name=corpus_name, source_dir=Path("."))

    from folio_insights.pipeline.discovery.orchestrator import TaskDiscoveryOrchestrator
    from folio_insights.pipeline.orchestrator import PipelineOrchestrator

    monkeypatch.setattr(PipelineOrchestrator, "run", fake_extract_run)
    monkeypatch.setattr(TaskDiscoveryOrchestrator, "run", fake_discover_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEYS["anthropic"])
    return seen


def test_extract_flags_reach_every_task_and_env_override_wins(tmp_path, captured, monkeypatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "synthetic.md").write_text("# Synthetic\n\nObject before the answer.\n")
    monkeypatch.setenv("LLM_CONCEPT_PROVIDER", "openai")
    monkeypatch.setenv("LLM_CONCEPT_MODEL", "gpt-4.1-nano")
    result = CliRunner().invoke(cli, [
        "extract", str(src), "--corpus", "c", "--output", str(tmp_path / "out"),
        "--llm-provider", "anthropic", "--llm-model", "claude-sonnet-4-5"])
    assert result.exit_code == 0, result.output
    assert captured["provider"] == "anthropic" and captured["model"] == "claude-sonnet-4-5"
    assert captured["routes"]["distiller"].provider == "anthropic"
    assert captured["routes"]["contradiction"].model == "claude-sonnet-4-5"
    assert (captured["routes"]["concept"].provider, captured["routes"]["concept"].model) == (
        "openai", "gpt-4.1-nano")
    # The CLI used the invoking user's own key, and printed none of it.
    assert captured["key"] is not None and LEAK_MARKER not in result.output
    # The context lived only for the command.
    assert current_context().provider is None and not current_context().credentials


def test_discover_accepts_the_same_flags(tmp_path, captured) -> None:
    corpus = tmp_path / "out" / "c"
    corpus.mkdir(parents=True)
    (corpus / "extraction.json").write_text(json.dumps({"units": []}))
    result = CliRunner().invoke(cli, [
        "discover", "c", "--output", str(tmp_path / "out"), "--llm-provider", "google",
        "--llm-model", "gemini-2.5-pro"])
    assert result.exit_code == 0, result.output
    assert captured["routes"]["distiller"].model == "gemini-2.5-pro"


def test_unknown_provider_flag_is_rejected(tmp_path) -> None:
    result = CliRunner().invoke(cli, ["extract", str(tmp_path), "--llm-provider", "nonesuch"])
    assert result.exit_code != 0 and "nonesuch" in result.output


def test_max_spend_flag_sets_the_run_cap(tmp_path, captured, monkeypatch) -> None:
    from decimal import Decimal

    monkeypatch.setenv("FOLIO_INSIGHTS_QUEUE_DB", str(tmp_path / "q.sqlite3"))
    src = tmp_path / "src"
    src.mkdir()
    (src / "synthetic.md").write_text("# Synthetic\n\nObject before the answer.\n")
    result = CliRunner().invoke(cli, ["extract", str(src), "--corpus", "c", "--output",
                                      str(tmp_path / "out"), "--max-spend-usd", "2.5"])
    assert result.exit_code == 0, result.output
    assert captured["cap"] == Decimal("2.5")
    assert not (tmp_path / "q.sqlite3").exists()  # no LLM call, no ledger write
