"""API job submission and control on the durable queue, with per-request keys (Phase 10 U2)."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from api import main as api_main
from api.main import app
from api.routes import discovery as discovery_mod
from api.routes import processing as processing_mod
from api.services.job_manager import get_runtime
from folio_insights.jobs import JobStatus

KEY = "AIzaTestFAKEKEYapijobs0123456789abcdef"


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FOLIO_INSIGHTS_QUEUE_DB", str(tmp_path / ".queue" / "jobs.sqlite3"))
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    api_main.configure(output_dir=tmp_path)
    processing_mod.reset_job_manager()
    discovery_mod.reset_discovery_job_manager()
    yield tmp_path
    get_runtime().secret_store.clear()
    processing_mod.reset_job_manager()


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _corpus(client: AsyncClient, name: str = "Synthetic Corpus") -> str:
    resp = await client.post("/api/v1/corpora", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


def _queue_bytes(tmp: Path) -> bytes:
    return b"".join(p.read_bytes() for p in (tmp / ".queue").glob("*") if p.is_file())


async def test_per_request_key_is_held_in_memory_only(client, isolated, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    corpus = await _corpus(client)
    resp = await client.post(f"/api/v1/corpus/{corpus}/process",
                             json={"llm_provider": "google", "llm_model": "gemini-2.5-flash-lite"},
                             headers={"X-LLM-API-Key": KEY})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "pending" and KEY not in json.dumps(body)

    runtime = get_runtime()
    job = runtime.queue.get(body["queue_job_id"])
    assert job.requires_credentials and job.credential_holder == runtime.owner
    assert job.payload["llm"] == {"provider": "google", "model": "gemini-2.5-flash-lite",
                                  "pin_provider": True}
    token = body["control_token"]
    assert token and len(token) >= 40
    assert token.encode() not in _queue_bytes(isolated)  # only its SHA-256 is stored
    held = runtime.secret_store.get(job.id)
    assert held is not None and held.get("google").reveal() == KEY
    assert held.providers() == ["google"]  # bound to the provider the request named
    # Never at rest, never in a response or a log line.
    assert KEY.encode() not in _queue_bytes(isolated) and b"FAKEKEY" not in _queue_bytes(isolated)
    status = await client.get(f"/api/v1/corpus/{corpus}/job")
    assert KEY not in status.text and "FAKEKEY" not in caplog.text


async def test_unknown_provider_is_rejected(client) -> None:
    corpus = await _corpus(client)
    resp = await client.post(f"/api/v1/corpus/{corpus}/process", json={"llm_provider": "nonesuch"},
                             headers={"X-LLM-API-Key": KEY})
    assert resp.status_code == 422


async def test_duplicate_submit_returns_the_same_job(client) -> None:
    corpus = await _corpus(client)
    headers = {"X-LLM-API-Key": KEY, "Idempotency-Key": "submit-1"}
    first = await client.post(f"/api/v1/corpus/{corpus}/process", headers=headers)
    second = await client.post(f"/api/v1/corpus/{corpus}/process", headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert second.json()["duplicate"] is True
    # A different submission while that job is active is refused.
    third = await client.post(f"/api/v1/corpus/{corpus}/process", headers={"X-LLM-API-Key": KEY})
    assert third.status_code == 409
    assert len(get_runtime().secret_store) == 1  # the refused request's key was dropped


async def test_keyless_job_waits_then_takes_a_key(client, isolated) -> None:
    corpus = await _corpus(client)
    first = await client.post(f"/api/v1/corpus/{corpus}/process")
    assert first.json()["status"] == "needs_credentials"
    token = first.json()["control_token"]
    # Without the job's control token nobody can attach a key to it.
    anon = await client.post(f"/api/v1/corpus/{corpus}/job/credentials",
                             headers={"X-LLM-API-Key": KEY})
    assert anon.status_code == 403
    # Supplying the key to the waiting job (dedicated endpoint).
    resp = await client.post(f"/api/v1/corpus/{corpus}/job/credentials",
                             headers={"X-LLM-API-Key": KEY, "X-Job-Control-Token": token})
    assert resp.status_code == 200 and resp.json()["status"] == "pending"
    job = get_runtime().queue.get(first.json()["queue_job_id"])
    assert job.status is JobStatus.QUEUED and job.credential_holder == get_runtime().owner
    assert KEY.encode() not in _queue_bytes(isolated)
    # A second re-supply is refused: the job no longer waits.
    again = await client.post(f"/api/v1/corpus/{corpus}/job/credentials",
                              headers={"X-LLM-API-Key": KEY, "X-Job-Control-Token": token})
    assert again.status_code == 409


async def test_resubmitting_with_a_key_cannot_hijack_the_waiting_job(client) -> None:
    """Review P1-1: an anonymous resubmission never attaches a key to someone's waiting job."""
    corpus = await _corpus(client)
    first = await client.post(f"/api/v1/corpus/{corpus}/process")
    second = await client.post(f"/api/v1/corpus/{corpus}/process", headers={"X-LLM-API-Key": KEY})
    assert second.status_code == 409
    job = get_runtime().queue.get(first.json()["queue_job_id"])
    assert job.status is JobStatus.NEEDS_CREDENTIALS and len(get_runtime().secret_store) == 0


async def test_cancel_endpoint(client) -> None:
    corpus = await _corpus(client)
    sub = await client.post(f"/api/v1/corpus/{corpus}/process", headers={"X-LLM-API-Key": KEY})
    anon = await client.post(f"/api/v1/corpus/{corpus}/job/cancel")
    wrong = await client.post(f"/api/v1/corpus/{corpus}/job/cancel",
                              headers={"X-Job-Control-Token": "not-the-token"})
    assert anon.status_code == wrong.status_code == 403
    resp = await client.post(f"/api/v1/corpus/{corpus}/job/cancel",
                             headers={"X-Job-Control-Token": sub.json()["control_token"]})
    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
    assert len(get_runtime().secret_store) == 0  # the cancelled job's key is dropped
    # A cancelled job no longer blocks a new submission.
    again = await client.post(f"/api/v1/corpus/{corpus}/process", headers={"X-LLM-API-Key": KEY})
    assert again.status_code == 202


async def test_resume_needs_the_control_token_and_a_fresh_key(client, monkeypatch) -> None:
    """Review P1-1: an anonymous caller cannot resume a capped job, and resuming past a cap
    needs a key again (the old one was dropped), so whoever resumes pays."""
    from folio_insights.jobs import JobWorker

    corpus = await _corpus(client)
    sub = await client.post(f"/api/v1/corpus/{corpus}/process",
                            json={"llm_provider": "google", "max_spend_usd": 0.5},
                            headers={"X-LLM-API-Key": KEY})
    token = sub.json()["control_token"]
    runtime = get_runtime()

    async def capped(ctx):
        from folio_insights.llm import BudgetExhaustedError

        raise BudgetExhaustedError("spend cap $0.5 reached")

    worker = JobWorker(runtime.queue, {"extract": capped}, owner=runtime.owner,
                       secret_store=runtime.secret_store, poll_interval=0.01)
    await worker.run(until_idle=True)
    job = runtime.queue.get(sub.json()["queue_job_id"])
    assert job.status is JobStatus.BUDGET_EXHAUSTED and job.attempts == 0  # pause != failure
    assert runtime.secret_store.get(job.id) is None  # the key left memory at the cap

    anon = await client.post(f"/api/v1/corpus/{corpus}/job/resume", json={"max_spend_usd": 1e6})
    assert anon.status_code == 403
    assert runtime.queue.get(job.id).payload["llm"]["max_spend_usd"] == 0.5
    inf = await client.post(f"/api/v1/corpus/{corpus}/job/resume",
                            content='{"max_spend_usd": Infinity}',
                            headers={"X-Job-Control-Token": token,
                                     "content-type": "application/json"})
    assert inf.status_code == 422

    resumed = await client.post(f"/api/v1/corpus/{corpus}/job/resume", json={"max_spend_usd": 2.0},
                                headers={"X-Job-Control-Token": token})
    assert resumed.status_code == 200 and resumed.json()["status"] == "needs_credentials"
    rekeyed = await client.post(f"/api/v1/corpus/{corpus}/job/credentials",
                                headers={"X-Job-Control-Token": token, "X-LLM-API-Key": KEY})
    assert rekeyed.status_code == 200 and rekeyed.json()["status"] == "pending"
    assert runtime.queue.get(job.id).payload["llm"]["max_spend_usd"] == 2.0


async def test_sse_reads_queue_state_and_closes_on_a_paused_job(client) -> None:
    corpus = await _corpus(client)
    await client.post(f"/api/v1/corpus/{corpus}/process")  # needs_credentials
    events = [ev async for ev in processing_mod.event_generator(corpus)]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "status" and kinds[-1] == "complete"
    complete = json.loads(events[-1]["data"])
    assert complete["status"] == "needs_credentials" and "API key" in complete["error"]


async def test_discovery_uses_its_own_queue_kind(client, isolated) -> None:
    corpus = await _corpus(client)
    (isolated / corpus / "extraction.json").write_text(json.dumps({"units": []}))
    p = await client.post(f"/api/v1/corpus/{corpus}/process", headers={"X-LLM-API-Key": KEY})
    d = await client.post(f"/api/v1/corpus/{corpus}/discover", headers={"X-LLM-API-Key": KEY})
    assert p.status_code == d.status_code == 202
    queue = get_runtime().queue
    assert queue.get(d.json()["queue_job_id"]).kind == "discover"
    job = await client.get(f"/api/v1/corpus/{corpus}/discover/job")
    assert job.json()["corpus_id"] == f"{corpus}_discovery"
    anon = await client.post(f"/api/v1/corpus/{corpus}/discover/job/cancel")
    assert anon.status_code == 403
    cancel = await client.post(f"/api/v1/corpus/{corpus}/discover/job/cancel",
                               headers={"X-Job-Control-Token": d.json()["control_token"]})
    assert cancel.json()["status"] == "cancelled"


def test_queue_tables_have_no_credential_columns(isolated) -> None:
    get_runtime()
    with sqlite3.connect(isolated / ".queue" / "jobs.sqlite3") as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        cols = {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")] for t in tables}
    flat = [c for cs in cols.values() for c in cs]
    assert not [c for c in flat if ("key" in c and c != "idempotency_key") or "secret" in c]


async def test_key_is_bound_to_the_named_provider_and_the_job_is_pinned(client, monkeypatch) -> None:
    """Review P1-2: a per-task env override can never route a user's key elsewhere."""
    from folio_insights.llm import LLMRunContext
    from folio_insights.llm.port import resolve_route

    monkeypatch.setenv("LLM_DISTILLER_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_DISTILLER_MODEL", "claude-haiku-4-5")
    corpus = await _corpus(client)
    sub = await client.post(f"/api/v1/corpus/{corpus}/process", json={"llm_provider": "openai"},
                            headers={"X-LLM-API-Key": "sk-proj-FAKEKEY-pinned-000000000000"})
    job = get_runtime().queue.get(sub.json()["queue_job_id"])
    held = get_runtime().secret_store.get(job.id)
    assert held.providers() == ["openai"]
    llm = job.payload["llm"]
    ctx = LLMRunContext(credentials=held, provider=llm["provider"], pin_provider=llm["pin_provider"])
    for task in ("distiller", "classifier", "concept", "branch_judge", "boundary"):
        assert resolve_route(task, context=ctx).provider == "openai"


async def test_keyless_provider_needs_operator_opt_in(client, monkeypatch) -> None:
    """Review P2-15: Ollama jobs run on the server's hardware; they need an explicit opt-in."""
    monkeypatch.delenv("FOLIO_INSIGHTS_API_ALLOW_KEYLESS_PROVIDERS", raising=False)
    corpus = await _corpus(client)
    refused = await client.post(f"/api/v1/corpus/{corpus}/process", json={"llm_provider": "ollama"})
    assert refused.status_code == 403
    monkeypatch.setenv("FOLIO_INSIGHTS_API_ALLOW_KEYLESS_PROVIDERS", "1")
    allowed = await client.post(f"/api/v1/corpus/{corpus}/process", json={"llm_provider": "ollama"})
    assert allowed.status_code == 202 and allowed.json()["status"] == "pending"


async def test_idempotency_replay_with_a_different_payload_or_key_conflicts(client) -> None:
    corpus = await _corpus(client)
    h = {"X-LLM-API-Key": KEY, "Idempotency-Key": "k1"}
    first = await client.post(f"/api/v1/corpus/{corpus}/process", headers=h)
    same = await client.post(f"/api/v1/corpus/{corpus}/process", headers=h)
    assert same.status_code == 202 and same.json()["job_id"] == first.json()["job_id"]
    assert same.json()["control_token"] is None  # the token is only ever returned once
    other_key = await client.post(f"/api/v1/corpus/{corpus}/process",
                                  headers={**h, "X-LLM-API-Key": "AIzaTestFAKEKEYother000000000000"})
    other_body = await client.post(f"/api/v1/corpus/{corpus}/process", headers=h,
                                   json={"llm_model": "gemini-2.5-pro"})
    assert other_key.status_code == other_body.status_code == 409


async def test_force_while_a_job_is_active_is_an_explicit_conflict(client, isolated) -> None:
    corpus = await _corpus(client)
    registry = isolated / corpus / f"corpus-{corpus}.json"
    registry.write_text("{}")
    await client.post(f"/api/v1/corpus/{corpus}/process", headers={"X-LLM-API-Key": KEY})
    resp = await client.post(f"/api/v1/corpus/{corpus}/process?force=true",
                             headers={"X-LLM-API-Key": KEY})
    assert resp.status_code == 409 and "force" in resp.json()["detail"]
    assert registry.exists()  # nothing was cleared under the running job


async def test_concurrent_resupply_never_wipes_the_winners_key(client) -> None:
    """Review P2-7: a losing re-supply restores the store instead of dropping the key."""
    from api.services.job_manager import resupply_credentials
    from folio_insights.jobs import QueueError

    corpus = await _corpus(client)
    sub = await client.post(f"/api/v1/corpus/{corpus}/process")
    runtime = get_runtime()
    stale = runtime.queue.get(sub.json()["queue_job_id"])
    resupply_credentials(stale, "AIzaTestFAKEKEYfirst0000000000000000")
    with pytest.raises(QueueError):
        resupply_credentials(stale, "AIzaTestFAKEKEYsecond000000000000000")
    held = runtime.secret_store.get(stale.id)
    assert held is not None and held.get("google").reveal().startswith("AIzaTestFAKEKEYfirst")
