"""JobWorker in-process: the real extraction handler over synthetic stages (Phase 10 U2).

``PipelineOrchestrator._build_stages`` is monkeypatched (restored after each test) so the real
``run_extraction_job`` handler and the real checkpoint path run three synthetic stages.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest

from folio_insights.jobs import JobStatus, JobWorker, PermanentJobError, SecretStore, SQLiteJobQueue
from folio_insights.llm import Credentials, LLMPort, set_default_port
from tests.jobs import fake_stages

FAKE_KEY = "AIzaTestFAKEKEYworker0123456789abcdef"

_VALID = {
    "id": "synthetic", "object": "chat.completion", "created": 1, "model": "gemini-2.5-flash-lite",
    "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None, "tool_calls": [{
            "id": "call_0", "type": "function", "function": {
                "name": "DistilledOutput",
                "arguments": json.dumps({"distilled_text": "Synthetic distilled insight."})}}]}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from folio_insights.pipeline.orchestrator import PipelineOrchestrator

    monkeypatch.setattr(PipelineOrchestrator, "_build_stages", lambda self: fake_stages.fake_stages())
    log = tmp_path / "stages.log"
    release = tmp_path / "release"
    monkeypatch.setenv("FAKE_PIPELINE_LOG", str(log))
    monkeypatch.setenv("FAKE_PIPELINE_RELEASE", str(release))
    monkeypatch.delenv("FAKE_LLM_KEY", raising=False)
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "LLM_DISTILLER_PROVIDER", "LLM_DISTILLER_MODEL"):
        monkeypatch.delenv(name, raising=False)
    queue = SQLiteJobQueue(tmp_path / "queue.sqlite3", retry_backoff_seconds=0.0)
    output = tmp_path / "output"
    (output / "synthetic" / "sources").mkdir(parents=True)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("authorization") != f"Bearer {FAKE_KEY}":
            return httpx.Response(400, json=[{"error": {"message": "API key not valid."}}])
        return httpx.Response(200, json=_VALID)

    set_default_port(LLMPort(
        http_client_factory=lambda _s: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_wait_seconds=0))
    yield {"tmp": tmp_path, "log": log, "release": release, "queue": queue, "output": output,
           "requests": requests}
    set_default_port(None)


def _payload(output: Path, provider: str = "google") -> dict:
    return {"corpus_name": "synthetic", "output_dir": str(output),
            "source_dir": str(output / "synthetic" / "sources"), "llm": {"provider": provider}}


def _worker(queue, store=None, **kw) -> JobWorker:
    from api.services.pipeline_runner import run_extraction_job

    return JobWorker(queue, {"extract": run_extraction_job},
                     secret_store=store if store is not None else SecretStore(),
                     lease_seconds=kw.pop("lease_seconds", 5.0), poll_interval=0.05, **kw)


def _lines(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


async def test_worker_runs_the_extraction_handler_end_to_end(env) -> None:
    env["release"].touch()
    job, _ = env["queue"].enqueue("extract", corpus_id="synthetic", payload=_payload(env["output"]))
    await _worker(env["queue"]).run(until_idle=True)

    done = env["queue"].get(job.id)
    assert done.status is JobStatus.SUCCEEDED, done.error
    assert done.result["total_units"] == 3
    assert "llm_usage" in done.result
    messages = [e.message for e in env["queue"].events(job.id)]
    assert "Starting fake_ingest..." in messages and "Completed fake_slow (3 units)" in messages
    assert (env["output"] / "synthetic" / "extraction.json").exists()
    # Job-scoped checkpoints are removed once the job succeeded.
    assert not (env["output"] / "synthetic" / "checkpoints" / "jobs" / job.id).exists()


async def test_cancel_takes_effect_at_the_next_stage_boundary(env) -> None:
    job, _ = env["queue"].enqueue("extract", corpus_id="synthetic", payload=_payload(env["output"]))
    task = asyncio.create_task(_worker(env["queue"]).run(until_idle=True))
    for _ in range(200):
        if "fake_slow:start" in _lines(env["log"]):
            break
        await asyncio.sleep(0.02)
    flagged = env["queue"].request_cancel(job.id)
    assert flagged.status is JobStatus.RUNNING  # not killed mid-stage
    env["release"].touch()
    await asyncio.wait_for(task, 20)
    done = env["queue"].get(job.id)
    assert done.status is JobStatus.CANCELLED
    assert "fake_slow:done" in _lines(env["log"])  # the running stage finished...
    assert not (env["output"] / "synthetic" / "extraction.json").exists()  # ...nothing after it


async def test_a_worker_without_the_key_handle_parks_the_job(env) -> None:
    worker = _worker(env["queue"])
    job, _ = env["queue"].enqueue("extract", corpus_id="synthetic", payload=_payload(env["output"]),
                                  requires_credentials=True, credential_holder=worker.owner)
    await worker.run(until_idle=True)
    parked = env["queue"].get(job.id)
    assert parked.status is JobStatus.NEEDS_CREDENTIALS
    assert _lines(env["log"]) == []  # nothing ran on an ambient key


async def test_missing_key_halts_before_checkpoint_then_resupply_resumes(env, monkeypatch, caplog) -> None:
    """A provider that needs a key, and no key: the run halts (no degraded checkpoint), the job
    waits as needs_credentials, and after the key is re-supplied it resumes from the last
    completed stage and the provider receives the user's key."""
    caplog.set_level(logging.DEBUG)
    env["release"].touch()
    monkeypatch.setenv("FAKE_LLM_KEY", "1")  # the fake_llm stage calls the port
    store = SecretStore()
    worker = _worker(env["queue"], store)
    job, _ = env["queue"].enqueue("extract", corpus_id="synthetic", payload=_payload(env["output"]))
    await worker.run(until_idle=True)

    parked = env["queue"].get(job.id)
    assert parked.status is JobStatus.NEEDS_CREDENTIALS
    assert "google" in parked.error
    assert env["requests"] == []  # no request went out without a key
    ckpts = env["output"] / "synthetic" / "checkpoints" / "jobs" / job.id
    assert (ckpts / "fake_ingest.json").exists() and not (ckpts / "fake_llm.json").exists()

    store.put(job.id, Credentials.single("google", FAKE_KEY))
    env["queue"].resupply_credentials(job.id, holder=worker.owner)
    await worker.run(until_idle=True)

    done = env["queue"].get(job.id)
    assert done.status is JobStatus.SUCCEEDED, done.error
    lines = _lines(env["log"])
    assert lines.count("fake_ingest") == 1  # resumed from its checkpoint, not re-run
    assert "fake_llm:ok" in lines
    assert [r.headers["authorization"] for r in env["requests"]] == [f"Bearer {FAKE_KEY}"]
    assert done.result["llm_usage"]["calls"] == 1
    assert job.id not in store  # the handle is dropped once the job settles

    # The key is nowhere at rest: queue database (and WAL), outputs, checkpoints, logs.
    blobs = [p.read_bytes() for p in env["tmp"].rglob("*") if p.is_file()]
    assert all(FAKE_KEY.encode() not in b and b"FAKEKEY" not in b for b in blobs)
    assert "FAKEKEY" not in caplog.text


async def test_permanent_errors_fail_without_retry_and_transient_ones_retry(env) -> None:
    calls: list[str] = []

    async def permanent(ctx):
        calls.append("p")
        raise PermanentJobError("bad payload")

    async def flaky(ctx):
        calls.append("f")
        if len([c for c in calls if c == "f"]) == 1:
            raise RuntimeError("transient")
        return {"ok": True}

    queue = env["queue"]
    p, _ = queue.enqueue("permanent", corpus_id="x", max_attempts=3)
    f, _ = queue.enqueue("flaky", corpus_id="y", max_attempts=3)
    worker = JobWorker(queue, {"permanent": permanent, "flaky": flaky}, secret_store=SecretStore(),
                       lease_seconds=5, poll_interval=0.05)
    await worker.run(until_idle=True)
    assert queue.get(p.id).status is JobStatus.FAILED and calls.count("p") == 1
    assert queue.get(f.id).status is JobStatus.SUCCEEDED and calls.count("f") == 2


async def test_heartbeat_keeps_a_blocked_loop_from_losing_its_lease(env) -> None:
    """A stage that blocks the event loop (CPU work) must not let the lease lapse."""
    import time

    async def blocking(ctx):
        time.sleep(1.2)  # 4x the lease below, with the loop blocked the whole time
        ctx.checkpoint()
        return {"ok": True}

    queue = env["queue"]
    job, _ = queue.enqueue("blocking", corpus_id="z")
    worker = JobWorker(queue, {"blocking": blocking}, secret_store=SecretStore(),
                       lease_seconds=0.3, poll_interval=0.05)
    await worker.run(until_idle=True)
    assert queue.get(job.id).status is JobStatus.SUCCEEDED
