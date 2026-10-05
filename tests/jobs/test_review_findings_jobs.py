"""Regression tests for the Phase 10 U1-U3 review findings on the jobs side (2026-10-05)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from folio_insights.jobs import JobStatus, JobWorker, SecretStore, SQLiteJobQueue
from folio_insights.llm import Credentials


@pytest.fixture()
def queue(tmp_path) -> SQLiteJobQueue:
    return SQLiteJobQueue(tmp_path / "q.sqlite3", retry_backoff_seconds=0)


async def test_p2_11_an_infinite_cap_fails_the_job_instead_of_wedging_it(queue) -> None:
    from folio_insights.llm.cost import job_meter_factory

    async def handler(ctx):
        return {"ok": 1}

    job, _ = queue.enqueue("extract", corpus_id="c",
                           payload={"llm": {"provider": "ollama", "max_spend_usd": float("inf")}})
    worker = JobWorker(queue, {"extract": handler}, meter_factory=job_meter_factory,
                       secret_store=SecretStore(), lease_seconds=30, poll_interval=0.01)
    await worker.run(until_idle=True)
    done = queue.get(job.id)
    assert done.status is JobStatus.FAILED and done.lease_owner is None
    assert "finite" in done.error


def test_p2_10_a_pause_gives_the_attempt_back(queue) -> None:
    job, _ = queue.enqueue("extract", corpus_id="c", max_attempts=1, requires_credentials=True,
                           credential_holder="w")
    for _ in range(3):  # three pause/resupply cycles never exhaust a one-attempt budget
        lease = queue.lease("w")
        assert lease is not None
        queue.pause(lease, JobStatus.NEEDS_CREDENTIALS, "key needed")
        assert queue.get(job.id).attempts == 0
        queue.resupply_credentials(job.id, holder="w")
    lease = queue.lease("w")
    assert queue.complete(lease, {"ok": 1})


def test_p2_10_budget_pause_drops_the_key_holder(queue) -> None:
    job, _ = queue.enqueue("extract", corpus_id="c", requires_credentials=True,
                           credential_holder="w")
    queue.pause(queue.lease("w"), JobStatus.BUDGET_EXHAUSTED, "cap")
    assert queue.get(job.id).credential_holder is None
    assert queue.resume(job.id).status is JobStatus.NEEDS_CREDENTIALS


async def test_p2_5_a_lost_lease_drops_the_key(queue) -> None:
    from folio_insights.jobs import LeaseLost

    async def handler(ctx):
        raise LeaseLost("synthetic")

    store = SecretStore()
    worker = JobWorker(queue, {"extract": handler}, secret_store=store, poll_interval=0.01)
    job, _ = queue.enqueue("extract", corpus_id="c", requires_credentials=True,
                           credential_holder=worker.owner)
    store.put(job.id, Credentials.single("openai", "sk-proj-FAKEKEY-lease-0000000000"))
    await worker.run(until_idle=True)
    assert job.id not in store


def test_p2_14_legacy_import_never_overwrites_a_live_job(tmp_path, queue) -> None:
    from folio_insights.jobs.legacy import import_legacy_jobs

    live, _ = queue.enqueue("extract", corpus_id="alpha", payload={"corpus_name": "alpha"},
                            job_id="11111111111141118111111111111111")
    jobs_dir = tmp_path / ".jobs"
    jobs_dir.mkdir()
    (jobs_dir / "alpha.json").write_text(json.dumps({
        "id": "11111111-1111-4111-8111-111111111111", "corpus_id": "alpha", "status": "failed",
        "created_at": "not-a-date", "updated_at": None}))
    (jobs_dir / "beta.json").write_text(json.dumps({
        "id": "22222222-2222-4222-8222-222222222222", "corpus_id": "beta", "status": "completed",
        "created_at": "garbage", "updated_at": "also garbage"}))
    rows = import_legacy_jobs(jobs_dir, queue)
    assert rows[0]["outcome"].startswith("skipped") and "live job" in rows[0]["outcome"]
    assert queue.get(live.id) == live  # untouched
    beta = queue.latest_for("extract", "beta")
    assert beta.created_at == 0.0 and beta.updated_at == 0.0  # malformed timestamps -> epoch


async def test_p2_12_lineage_reaches_extraction_json_and_survives_resume(tmp_path, monkeypatch) -> None:
    from folio_insights.config import Settings
    from folio_insights.llm import LLMRunContext, use_context
    from folio_insights.llm.context import current_context
    from folio_insights.pipeline.orchestrator import PipelineOrchestrator
    from folio_insights.pipeline.stages.base import InsightsPipelineStage
    from folio_insights.services.bridge import folio_bridge

    monkeypatch.setattr(folio_bridge, "verify_deterministic_bridge", lambda: object)

    class _UsesTemplate(InsightsPipelineStage):
        name = "folio_tagger"  # also triggers the B5 canary

        async def execute(self, job):
            current_context().templates_used["distiller.distill"] = "h-distill"
            return job

    class _Boom(InsightsPipelineStage):
        name = "deduplicator"
        fail = True

        async def execute(self, job):
            if _Boom.fail:
                raise RuntimeError("crash after the first stage")
            return job

    settings = Settings(output_dir=tmp_path)
    with use_context(LLMRunContext()), pytest.raises(RuntimeError):
        await PipelineOrchestrator(settings, stages=[_UsesTemplate(), _Boom()]).run(
            tmp_path, corpus_name="c")
    _Boom.fail = False

    class _Skip(InsightsPipelineStage):  # must not run: resumed from its checkpoint
        name = "folio_tagger"

        async def execute(self, job):
            raise AssertionError("re-ran a checkpointed stage")

    with use_context(LLMRunContext()):
        await PipelineOrchestrator(settings, stages=[_Skip(), _Boom()]).run(tmp_path, corpus_name="c")
    summary = json.loads((tmp_path / "c" / "extraction.json").read_text())["summary"]
    assert summary["llm"]["templates"] == {"distiller.distill": "h-distill"}
    assert summary["b5_canary"] == {"status": "ok"}


def test_p2_13_cli_cap_is_cumulative_per_corpus(tmp_path, monkeypatch) -> None:
    from click.testing import CliRunner

    from folio_insights.cli import cli
    from folio_insights.llm.usage import Usage, UsageLedger, UsageRecord
    from folio_insights.pipeline.orchestrator import PipelineOrchestrator

    monkeypatch.setenv("FOLIO_INSIGHTS_QUEUE_DB", str(tmp_path / "q.sqlite3"))
    UsageLedger(tmp_path / "q.sqlite3").record(
        UsageRecord(task="distiller", template_id="t", template_hash="h",
                    usage=Usage("google", "gemini-2.5-flash-lite", 10, 1)),
        run_id="cli:c:default", cost=Decimal("1.00"), price_table_version="2026-10-05")
    seen: dict = {}

    async def fake_run(self, source_dir, corpus_name=None, resume=True, **kw):
        from folio_insights.llm.context import current_context
        from folio_insights.pipeline.stages.base import InsightsJob

        meter = current_context().meter
        seen.update(spent=meter.spent, cap=meter.cap, run_id=current_context().run_id)
        return InsightsJob(corpus_name=corpus_name, source_dir=source_dir)

    monkeypatch.setattr(PipelineOrchestrator, "run", fake_run)
    src = tmp_path / "src"
    src.mkdir()
    (src / "s.md").write_text("# S\n\nSynthetic.\n")
    result = CliRunner().invoke(cli, ["extract", str(src), "--corpus", "c", "--output",
                                      str(tmp_path / "out"), "--max-spend-usd", "2.5"])
    assert result.exit_code == 0, result.output
    assert seen == {"spent": Decimal("1.00"), "cap": Decimal("2.5"), "run_id": "cli:c:default"}
    result = CliRunner().invoke(cli, ["extract", str(src), "--corpus", "c", "--output",
                                      str(tmp_path / "out"), "--spend-window", "q4"])
    assert seen["spent"] == 0 and seen["run_id"] == "cli:c:q4"


def test_control_token_is_hashed_and_checked_in_constant_time(queue) -> None:
    job, _ = queue.enqueue("extract", corpus_id="c", control_token="tok-123")
    assert queue.verify_control(job.id, "tok-123")
    assert not queue.verify_control(job.id, "tok-124")
    assert not queue.verify_control(job.id, None)
    other, _ = queue.enqueue("extract", corpus_id="d")
    assert not queue.verify_control(other.id, "")  # no token: never controllable
    assert b"tok-123" not in Path(queue.path).read_bytes()
