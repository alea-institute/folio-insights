"""SQLite lease queue: enqueue, idempotency, leases, retries, recovery, control (Phase 10 U2)."""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from folio_insights.jobs import (
    ActiveJobExists,
    JobStatus,
    QueueError,
    SQLiteJobQueue,
)
from folio_insights.llm import SecretKey


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
    return SQLiteJobQueue(tmp_path / "queue.sqlite3", clock=clock, retry_backoff_seconds=2.0)


def test_enqueue_and_read_back(queue) -> None:
    job, created = queue.enqueue("extract", corpus_id="c1", payload={"corpus_name": "c1"})
    assert created and job.status is JobStatus.QUEUED and job.attempts == 0
    assert queue.get(job.id) == job
    assert queue.latest_for("extract", "c1").id == job.id
    assert [e.message for e in queue.events(job.id)] == ["extract job queued"]


def test_duplicate_submit_returns_the_same_job(queue) -> None:
    first, created1 = queue.enqueue("extract", corpus_id="c1", idempotency_key="k-1")
    second, created2 = queue.enqueue("extract", corpus_id="c1", idempotency_key="k-1")
    assert created1 and not created2 and first.id == second.id
    assert len(queue.list_jobs()) == 1


def test_exclusive_enqueue_refuses_a_second_active_job(queue) -> None:
    queue.enqueue("extract", corpus_id="c1", exclusive=True)
    with pytest.raises(ActiveJobExists):
        queue.enqueue("extract", corpus_id="c1", exclusive=True)
    queue.enqueue("discover", corpus_id="c1", exclusive=True)  # other kind: fine
    queue.enqueue("extract", corpus_id="c2", exclusive=True)  # other corpus: fine


@pytest.mark.parametrize("payload", [
    {"api_key": "sk-test-FAKEKEY-x"},
    {"llm": {"provider": "openai", "key": "sk-test-FAKEKEY-x"}},
    {"headers": [{"authorization": "Bearer x"}]},
    {"client_secret": "x"},
])
def test_payload_refuses_credential_fields(queue, payload) -> None:
    with pytest.raises(QueueError):
        queue.enqueue("extract", corpus_id="c1", payload=payload)
    assert queue.list_jobs() == []


def test_payload_refuses_a_secret_key_object(queue) -> None:
    with pytest.raises(TypeError):
        queue.enqueue("extract", corpus_id="c1", payload={"llm": {"provider": SecretKey("x" * 20)}})


def test_lease_heartbeat_complete(queue, clock) -> None:
    job, _ = queue.enqueue("extract", corpus_id="c1")
    lease = queue.lease("w1", lease_seconds=30)
    assert lease is not None and lease.job.id == job.id and lease.job.attempts == 1
    assert queue.lease("w2") is None  # nothing else runnable
    clock.advance(20)
    assert queue.heartbeat(lease, lease_seconds=30)
    assert queue.update_progress(lease, stage="s1", progress_pct=50, message="Starting S1...")
    assert queue.complete(lease, {"total_units": 3})
    done = queue.get(job.id)
    assert done.status is JobStatus.SUCCEEDED and done.progress_pct == 100
    assert done.result == {"total_units": 3} and done.finished_at == clock.t
    assert not queue.heartbeat(lease)  # a settled lease cannot be renewed


def test_lease_filters_by_kind(queue) -> None:
    queue.enqueue("reason", corpus_id="c1")
    assert queue.lease("w1", kinds=["extract"]) is None
    assert queue.lease("w1", kinds=["reason"]) is not None


def test_two_workers_never_lease_one_job(tmp_path) -> None:
    """Concurrency: many threads racing over many jobs; every job is leased exactly once."""
    queue = SQLiteJobQueue(tmp_path / "race.sqlite3")
    for i in range(40):
        queue.enqueue("extract", corpus_id=f"c{i}")
    leased: list[str] = []
    lock = threading.Lock()

    def drain(owner: str) -> None:
        q = SQLiteJobQueue(tmp_path / "race.sqlite3")
        while (lease := q.lease(owner)) is not None:
            with lock:
                leased.append(lease.job.id)

    threads = [threading.Thread(target=drain, args=(f"w{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(leased) == 40 and len(set(leased)) == 40


def test_failure_retries_with_backoff_then_fails(queue, clock) -> None:
    job, _ = queue.enqueue("extract", corpus_id="c1", max_attempts=2)
    lease = queue.lease("w1")
    after = queue.fail(lease, "boom")
    assert after.status is JobStatus.QUEUED and after.available_at == clock.t + 2.0
    assert queue.lease("w1") is None  # backing off
    clock.advance(2.0)
    lease = queue.lease("w1")
    assert lease.job.attempts == 2
    final = queue.fail(lease, "boom again")
    assert final.status is JobStatus.FAILED and final.error == "boom again"


def test_permanent_failure_skips_retries(queue) -> None:
    queue.enqueue("extract", corpus_id="c1", max_attempts=5)
    lease = queue.lease("w1")
    assert queue.fail(lease, "bad payload", retry=False).status is JobStatus.FAILED


def test_expired_lease_is_reclaimed_and_resumable(queue, clock) -> None:
    job, _ = queue.enqueue("extract", corpus_id="c1")
    lease = queue.lease("w1", lease_seconds=10)
    clock.advance(11)
    assert queue.reclaim_expired() == [job.id]
    assert queue.get(job.id).status is JobStatus.QUEUED
    # The dead worker's late writes are refused: its lease token is void.
    assert not queue.heartbeat(lease)
    assert not queue.complete(lease, {})
    relet = queue.lease("w2")
    assert relet.job.id == job.id and relet.job.attempts == 2


def test_reclaim_parks_credential_jobs_as_needs_credentials(queue, clock) -> None:
    job, _ = queue.enqueue("extract", corpus_id="c1", requires_credentials=True,
                           credential_holder="w1")
    assert queue.lease("w2") is None  # only the key holder may lease it
    queue.lease("w1", lease_seconds=10)
    clock.advance(11)
    queue.reclaim_expired()
    parked = queue.get(job.id)
    assert parked.status is JobStatus.NEEDS_CREDENTIALS and parked.credential_holder is None
    resupplied = queue.resupply_credentials(job.id, holder="w3")
    assert resupplied.status is JobStatus.QUEUED and resupplied.credential_holder == "w3"
    assert queue.lease("w3").job.id == job.id


def test_queued_credential_job_with_a_dead_holder_is_parked(queue, clock) -> None:
    queue.worker_heartbeat("api-1")
    job, _ = queue.enqueue("extract", corpus_id="c1", requires_credentials=True,
                           credential_holder="api-1")
    clock.advance(queue.worker_ttl_seconds + 1)  # api-1 stopped heart-beating
    queue.reclaim_expired()
    assert queue.get(job.id).status is JobStatus.NEEDS_CREDENTIALS


def test_crash_loop_exhausts_attempts(queue, clock) -> None:
    job, _ = queue.enqueue("extract", corpus_id="c1", max_attempts=1)
    queue.lease("w1", lease_seconds=5)
    clock.advance(6)
    queue.reclaim_expired()
    assert queue.get(job.id).status is JobStatus.FAILED


def test_cancel_queued_is_immediate_and_running_is_flagged(queue) -> None:
    waiting, _ = queue.enqueue("extract", corpus_id="c1")
    assert queue.request_cancel(waiting.id).status is JobStatus.CANCELLED
    running, _ = queue.enqueue("extract", corpus_id="c2")
    lease = queue.lease("w1")
    flagged = queue.request_cancel(running.id)
    assert flagged.status is JobStatus.RUNNING and flagged.cancel_requested
    assert queue.is_cancel_requested(running.id)
    assert queue.mark_cancelled(lease, "cancellation requested")
    assert queue.get(running.id).status is JobStatus.CANCELLED


def test_budget_exhausted_pause_and_resume(queue) -> None:
    job, _ = queue.enqueue("extract", corpus_id="c1", payload={"llm": {"max_spend_usd": 1.0}})
    lease = queue.lease("w1")
    assert queue.pause(lease, JobStatus.BUDGET_EXHAUSTED, "cap reached")
    assert queue.get(job.id).status is JobStatus.BUDGET_EXHAUSTED
    queue.update_payload(job.id, {"llm": {"max_spend_usd": 5.0}})
    resumed = queue.resume(job.id)
    assert resumed.status is JobStatus.QUEUED and resumed.payload["llm"]["max_spend_usd"] == 5.0
    with pytest.raises(QueueError):
        queue.resume(job.id)


def test_needs_credentials_enqueue_and_illegal_transitions(queue) -> None:
    job, _ = queue.enqueue("extract", corpus_id="c1", requires_credentials=True,
                           status=JobStatus.NEEDS_CREDENTIALS)
    assert queue.lease("w1") is None
    with pytest.raises(QueueError):
        queue.enqueue("extract", corpus_id="c2", status=JobStatus.RUNNING)
    with pytest.raises(QueueError):
        queue.resume(job.id)


def test_queue_file_is_private_and_holds_no_secret_columns(queue) -> None:
    import stat

    assert stat.S_IMODE(queue.path.stat().st_mode) == 0o600
    with sqlite3.connect(queue.path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert not {c for c in cols if "key" in c and c != "idempotency_key"}


def test_events_are_ordered(queue) -> None:
    job, _ = queue.enqueue("extract", corpus_id="c1")
    lease = queue.lease("w1")
    for i in range(3):
        queue.update_progress(lease, stage=f"s{i}", message=f"m{i}")
    msgs = [e.message for e in queue.events(job.id)]
    assert msgs[-3:] == ["m0", "m1", "m2"]
    assert [e.seq for e in queue.events(job.id)] == list(range(1, len(msgs) + 1))
    assert json.dumps([e.message for e in queue.events(job.id, after_seq=len(msgs) - 1)]) == '["m2"]'


def test_legacy_import_is_idempotent_and_never_runnable(tmp_path, queue) -> None:
    from folio_insights.jobs.legacy import ORPHANED, import_legacy_jobs

    jobs_dir = tmp_path / ".jobs"
    jobs_dir.mkdir()
    base = {"created_at": "2026-10-01T00:00:00+00:00", "updated_at": "2026-10-01T00:05:00+00:00",
            "activity_log": [{"timestamp": "2026-10-01T00:01:00+00:00", "stage": "ingestion",
                              "message": "Starting Ingestion..."}]}
    (jobs_dir / "alpha.json").write_text(json.dumps({
        **base, "id": "11111111-1111-4111-8111-111111111111", "corpus_id": "alpha",
        "status": "processing", "current_stage": "ingestion"}))
    (jobs_dir / "alpha_discovery.json").write_text(json.dumps({
        **base, "id": "22222222-2222-4222-8222-222222222222", "corpus_id": "alpha_discovery",
        "status": "completed", "total_units": 4}))
    (jobs_dir / "broken.json").write_text("{not json")

    rows = import_legacy_jobs(jobs_dir, queue)
    assert [r["outcome"] for r in rows] == [
        "imported as extract/failed", "imported as discover/succeeded", "skipped (JSONDecodeError)"]
    orphan = queue.latest_for("extract", "alpha")
    assert orphan.status is JobStatus.FAILED and orphan.error == ORPHANED
    assert [e.message for e in queue.events(orphan.id)] == ["Starting Ingestion..."]
    assert queue.latest_for("discover", "alpha").result == {"total_units": 4}
    import_legacy_jobs(jobs_dir, queue)  # idempotent
    assert len(queue.list_jobs()) == 2
    assert queue.lease("w1") is None  # imported records are never runnable
