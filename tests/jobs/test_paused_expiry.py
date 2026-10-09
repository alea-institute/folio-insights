"""Expiry for abandoned paused jobs (R18, KTD13, AE7)."""

from __future__ import annotations

import asyncio
import math
import threading

import pytest
from click.testing import CliRunner

from folio_insights.jobs import ActiveJobExists, JobStatus, JobWorker, SecretStore, SQLiteJobQueue
from folio_insights.jobs.worker import parse_paused_ttl, paused_ttl_from_env
from folio_insights.llm import Credentials

TTL = 3600.0


class Clock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def queue(tmp_path, clock) -> SQLiteJobQueue:
    return SQLiteJobQueue(tmp_path / "queue.sqlite3", clock=clock)


def _paused(queue: SQLiteJobQueue, corpus: str, status: JobStatus) -> str:
    """Drive a job through the real lease -> pause path."""
    queue.enqueue("extract", corpus_id=corpus, requires_credentials=False)
    lease = queue.lease("w1", kinds=["extract"])
    assert lease is not None
    assert queue.pause(lease, status, "synthetic pause")
    return lease.job.id


@pytest.mark.parametrize("status", [JobStatus.NEEDS_CREDENTIALS, JobStatus.BUDGET_EXHAUSTED])
def test_ae7_expired_paused_job_is_cancelled_and_corpus_unblocked(queue, clock, status) -> None:
    job_id = _paused(queue, "c1", status)
    with pytest.raises(ActiveJobExists):  # the bug: a lost token blocks the corpus
        queue.enqueue("extract", corpus_id="c1", exclusive=True)

    clock.advance(TTL + 1)
    assert queue.expire_paused(ttl_seconds=TTL) == [job_id]

    job = queue.get(job_id)
    assert job.status is JobStatus.CANCELLED and job.is_terminal
    assert job.error.startswith("expired")
    assert job.credential_holder is None and job.finished_at == clock.t
    assert any(e.message.startswith("expired") for e in queue.events(job_id))
    fresh, created = queue.enqueue("extract", corpus_id="c1", exclusive=True)
    assert created and fresh.id != job_id


def test_paused_job_younger_than_ttl_is_untouched(queue, clock) -> None:
    job_id = _paused(queue, "c1", JobStatus.NEEDS_CREDENTIALS)
    clock.advance(TTL - 1)
    assert queue.expire_paused(ttl_seconds=TTL) == []
    assert queue.get(job_id).status is JobStatus.NEEDS_CREDENTIALS


def test_running_and_queued_jobs_are_never_expired(queue, clock) -> None:
    queued, _ = queue.enqueue("extract", corpus_id="q")
    running, _ = queue.enqueue("extract", corpus_id="r")
    lease = queue.lease("w1", kinds=["extract"], lease_seconds=10 * TTL)
    leased_id = lease.job.id
    clock.advance(5 * TTL)
    assert queue.expire_paused(ttl_seconds=TTL) == []
    assert queue.get(leased_id).status is JobStatus.RUNNING
    other = queued.id if leased_id != queued.id else running.id
    assert queue.get(other).status is JobStatus.QUEUED


def test_only_paused_are_expired_in_a_mixed_queue(queue, clock) -> None:
    paused = _paused(queue, "p", JobStatus.BUDGET_EXHAUSTED)
    queued, _ = queue.enqueue("extract", corpus_id="q")
    clock.advance(2 * TTL)
    assert queue.expire_paused(ttl_seconds=TTL) == [paused]
    assert queue.get(queued.id).status is JobStatus.QUEUED


def test_two_workers_sweeping_concurrently_are_idempotent(tmp_path, clock) -> None:
    path = tmp_path / "queue.sqlite3"
    ids = []
    q0 = SQLiteJobQueue(path, clock=clock)
    for i in range(5):
        ids.append(_paused(q0, f"c{i}", JobStatus.NEEDS_CREDENTIALS))
    clock.advance(TTL + 1)
    results: list[list[str]] = []
    barrier = threading.Barrier(4)

    def sweep() -> None:
        q = SQLiteJobQueue(path, clock=clock)
        barrier.wait()
        results.append(q.expire_paused(ttl_seconds=TTL))

    threads = [threading.Thread(target=sweep) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    flat = [i for r in results for i in r]
    assert sorted(flat) == sorted(ids)  # every job expired exactly once
    assert all(q0.get(i).status is JobStatus.CANCELLED for i in ids)
    assert q0.expire_paused(ttl_seconds=TTL) == []
    assert sum(1 for e in q0.events(ids[0]) if e.message.startswith("expired")) == 1


@pytest.mark.parametrize("ttl", [0, -5, math.nan, math.inf])
def test_disabled_when_ttl_non_positive_or_non_finite(queue, clock, ttl) -> None:
    job_id = _paused(queue, "c1", JobStatus.NEEDS_CREDENTIALS)
    clock.advance(10 * TTL)
    assert queue.expire_paused(ttl_seconds=ttl) == []
    assert queue.get(job_id).status is JobStatus.NEEDS_CREDENTIALS


def test_explicit_now_is_honoured(queue, clock) -> None:
    job_id = _paused(queue, "c1", JobStatus.NEEDS_CREDENTIALS)
    assert queue.expire_paused(ttl_seconds=TTL, now=clock.t + TTL + 1) == [job_id]


def test_ttl_parsing_rejects_non_finite_and_garbage(monkeypatch) -> None:
    assert parse_paused_ttl("90") == 90.0 and parse_paused_ttl(-1) == -1.0
    for bad in ("nan", "inf", "-inf", "soon", None, True):
        with pytest.raises(ValueError):
            parse_paused_ttl(bad)
    monkeypatch.delenv("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS", raising=False)
    assert paused_ttl_from_env() == 86400.0
    monkeypatch.setenv("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS", "120")
    assert paused_ttl_from_env() == 120.0
    monkeypatch.setenv("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS", "nan")
    with pytest.raises(ValueError):
        paused_ttl_from_env()


def test_settings_field_default_env_and_rejection(monkeypatch) -> None:
    from pydantic import ValidationError

    from folio_insights.config import Settings

    monkeypatch.delenv("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS", raising=False)
    assert Settings(_env_file=None).job_paused_ttl_seconds == 86400.0
    monkeypatch.setenv("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS", "0")
    assert Settings(_env_file=None).job_paused_ttl_seconds == 0.0
    monkeypatch.setenv("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS", "inf")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_worker_poll_expires_job_and_drops_in_memory_secret(queue, clock) -> None:
    store = SecretStore()
    job_id = _paused(queue, "c1", JobStatus.NEEDS_CREDENTIALS)
    store.put(job_id, Credentials.single("gemini", "synthetic-key-0123456789"))
    worker = JobWorker(queue, {}, secret_store=store, paused_ttl_seconds=TTL)
    asyncio.run(worker.run_once())
    assert queue.get(job_id).status is JobStatus.NEEDS_CREDENTIALS and job_id in store

    clock.advance(TTL + 1)
    asyncio.run(worker.run_once())
    assert queue.get(job_id).status is JobStatus.CANCELLED
    assert job_id not in store


def test_worker_with_disabled_ttl_never_expires(queue, clock) -> None:
    job_id = _paused(queue, "c1", JobStatus.NEEDS_CREDENTIALS)
    clock.advance(100 * TTL)
    worker = JobWorker(queue, {}, secret_store=SecretStore(), paused_ttl_seconds=0)
    asyncio.run(worker.run_once())
    assert queue.get(job_id).status is JobStatus.NEEDS_CREDENTIALS


def test_worker_reads_ttl_from_env_by_default(queue, monkeypatch) -> None:
    monkeypatch.setenv("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS", "42")
    assert JobWorker(queue, {}, secret_store=SecretStore()).paused_ttl_seconds == 42.0


def test_worker_survives_a_failing_sweep(queue, clock, monkeypatch) -> None:
    def boom(**_kw):
        raise RuntimeError("db locked")

    monkeypatch.setattr(queue, "expire_paused", boom)
    worker = JobWorker(queue, {}, secret_store=SecretStore(), paused_ttl_seconds=TTL)
    assert asyncio.run(worker.expire_paused()) == []


def test_cli_expire_and_list_show_reason(tmp_path, clock, monkeypatch) -> None:
    from folio_insights.cli import cli

    db = tmp_path / "cli.sqlite3"
    q = SQLiteJobQueue(db, clock=clock)
    job_id = _paused(q, "c1", JobStatus.NEEDS_CREDENTIALS)
    runner = CliRunner()
    # The CLI queue uses the wall clock; age the row directly instead.
    import sqlite3

    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE jobs SET updated_at = 1.0 WHERE id = ?", (job_id,))

    res = runner.invoke(cli, ["jobs", "list", "--db", str(db)])
    assert res.exit_code == 0 and "reason=" in res.output and "synthetic pause" in res.output
    res = runner.invoke(cli, ["jobs", "expire", "--db", str(db), "--ttl", "0"])
    assert res.exit_code == 0 and "disabled" in res.output
    assert SQLiteJobQueue(db).get(job_id).status is JobStatus.NEEDS_CREDENTIALS
    res = runner.invoke(cli, ["jobs", "expire", "--db", str(db), "--ttl", "nan"])
    assert res.exit_code != 0
    res = runner.invoke(cli, ["jobs", "expire", "--db", str(db), "--ttl", "60"])
    assert res.exit_code == 0 and f"{job_id}: expired" in res.output and "1 job(s)" in res.output
    res = runner.invoke(cli, ["jobs", "list", "--db", str(db)])
    assert "cancelled" in res.output and "reason=expired" in res.output


def test_standalone_worker_reads_a_dotenv_ttl_like_the_api(queue, tmp_path, monkeypatch) -> None:
    """A TTL set only in ``.env`` applies to the standalone worker exactly as to the API's
    Settings (both sweepers must agree, or the shortest TTL wins)."""
    from folio_insights.config import Settings

    monkeypatch.delenv("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS=0\n", encoding="utf-8")
    assert Settings().job_paused_ttl_seconds == 0.0  # what the API's get_settings() reads
    assert paused_ttl_from_env() == 0.0
    assert JobWorker(queue, {}, secret_store=SecretStore()).paused_ttl_seconds == 0.0
    # The process environment still wins over .env, as in Settings.
    monkeypatch.setenv("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS", "300")
    assert paused_ttl_from_env() == 300.0 == Settings().job_paused_ttl_seconds
    # An invalid .env value is refused, never silently defaulted.
    monkeypatch.delenv("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS")
    (tmp_path / ".env").write_text("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS=nan\n", encoding="utf-8")
    with pytest.raises(ValueError):
        paused_ttl_from_env()


def test_lean_image_without_pydantic_settings_reads_the_environment(tmp_path, monkeypatch) -> None:
    """With no pydantic-settings (the lean worker image) only the process environment counts."""
    import sys

    monkeypatch.setitem(sys.modules, "folio_insights.config", None)  # import -> ImportError
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS=0\n", encoding="utf-8")
    monkeypatch.delenv("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS", raising=False)
    assert paused_ttl_from_env() == 86400.0
    monkeypatch.setenv("FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS", "7")
    assert paused_ttl_from_env() == 7.0
