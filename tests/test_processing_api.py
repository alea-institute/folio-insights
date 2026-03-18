"""Integration tests for processing trigger and SSE stream endpoints."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api import main as api_main
from api.main import app
from api.models.processing import (
    ActivityEntry,
    ProcessingJob,
    ProcessingStatus,
)
from api.routes import processing as processing_mod
from api.services.job_manager import JobManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def configure_tmp_output(tmp_path: Path):
    """Point the API at a temporary directory for each test."""
    api_main.configure(output_dir=tmp_path)
    processing_mod.reset_job_manager()
    yield tmp_path


@pytest.fixture()
async def client():
    """Async HTTPX test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_corpus(client: AsyncClient, name: str = "Test Corpus") -> str:
    """Helper to create a corpus and return its id."""
    resp = await client.post("/api/v1/corpora", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Tests: Processing trigger
# ---------------------------------------------------------------------------


async def test_trigger_processing(client: AsyncClient, configure_tmp_output: Path):
    """POST /api/v1/corpus/{id}/process returns 202 with a job_id."""
    corpus_id = await _create_corpus(client)

    with patch(
        "api.routes.processing.run_pipeline_with_progress",
        new_callable=AsyncMock,
    ):
        resp = await client.post(f"/api/v1/corpus/{corpus_id}/process")

    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "pending"


async def test_trigger_nonexistent_corpus(client: AsyncClient):
    """POST /api/v1/corpus/{id}/process returns 404 for unknown corpus."""
    resp = await client.post("/api/v1/corpus/does-not-exist/process")
    assert resp.status_code == 404


async def test_trigger_duplicate_processing(
    client: AsyncClient, configure_tmp_output: Path
):
    """POST twice while processing returns 409 on second call."""
    corpus_id = await _create_corpus(client)

    # Write a PROCESSING job directly to disk so the second POST sees it
    jm = processing_mod.get_job_manager()
    job = ProcessingJob(
        corpus_id=corpus_id,
        status=ProcessingStatus.PROCESSING,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    await jm.save(job)

    resp = await client.post(f"/api/v1/corpus/{corpus_id}/process")
    assert resp.status_code == 409
    assert "already in progress" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: SSE stream (unit-test the generator directly)
# ---------------------------------------------------------------------------


async def test_sse_generator_no_job(configure_tmp_output: Path):
    """Event generator yields error when no job exists."""
    events = []
    async for ev in processing_mod.event_generator("nonexistent"):
        events.append(ev)

    assert len(events) == 1
    assert events[0]["event"] == "error"
    assert "No processing job found" in events[0]["data"]


async def test_sse_generator_completed_job(configure_tmp_output: Path):
    """Event generator yields status + complete for an already-finished job."""
    jm = processing_mod.get_job_manager()
    job = ProcessingJob(
        corpus_id="test-corpus",
        status=ProcessingStatus.COMPLETED,
        progress_pct=100,
        total_units=42,
        activity_log=[
            ActivityEntry(
                timestamp=_now_iso(),
                stage="pipeline",
                message="Pipeline complete: 42 units extracted",
            ),
        ],
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    await jm.save(job)

    events = []
    async for ev in processing_mod.event_generator("test-corpus"):
        events.append(ev)

    event_types = [e["event"] for e in events]
    assert "status" in event_types
    assert "activity" in event_types
    assert "complete" in event_types

    # Verify complete event data
    complete_ev = next(e for e in events if e["event"] == "complete")
    complete_data = json.loads(complete_ev["data"])
    assert complete_data["status"] == "completed"
    assert complete_data["total_units"] == 42
    assert complete_data["error"] is None


async def test_sse_generator_failed_job(configure_tmp_output: Path):
    """Event generator yields error details for a failed job."""
    jm = processing_mod.get_job_manager()
    job = ProcessingJob(
        corpus_id="test-corpus",
        status=ProcessingStatus.FAILED,
        error="Something went wrong",
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    await jm.save(job)

    events = []
    async for ev in processing_mod.event_generator("test-corpus"):
        events.append(ev)

    complete_ev = next(e for e in events if e["event"] == "complete")
    complete_data = json.loads(complete_ev["data"])
    assert complete_data["status"] == "failed"
    assert complete_data["error"] == "Something went wrong"


async def test_sse_generator_progressive_updates(configure_tmp_output: Path):
    """Event generator picks up new activity entries as job progresses."""
    jm = processing_mod.get_job_manager()

    # Start with a PROCESSING job with one activity entry
    job = ProcessingJob(
        corpus_id="test-corpus",
        status=ProcessingStatus.PROCESSING,
        current_stage="ingestion",
        progress_pct=14,
        activity_log=[
            ActivityEntry(
                timestamp=_now_iso(),
                stage="ingestion",
                message="Starting Ingestion...",
            ),
        ],
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    await jm.save(job)

    # Collect events from the generator, but update the job mid-stream
    events = []
    call_count = 0
    original_load = jm.load_by_corpus

    async def _patched_load(corpus_id: str):
        nonlocal call_count
        call_count += 1

        if call_count == 2:
            # Second poll: mark as completed with more activity
            j = await original_load(corpus_id)
            j.status = ProcessingStatus.COMPLETED
            j.progress_pct = 100
            j.total_units = 10
            j.activity_log.append(
                ActivityEntry(
                    timestamp=_now_iso(),
                    stage="pipeline",
                    message="Pipeline complete: 10 units extracted",
                )
            )
            await jm.save(j)

        return await original_load(corpus_id)

    with patch.object(jm, "load_by_corpus", side_effect=_patched_load):
        async for ev in processing_mod.event_generator("test-corpus"):
            events.append(ev)

    event_types = [e["event"] for e in events]
    assert "status" in event_types
    assert "activity" in event_types
    assert "complete" in event_types

    # Should have at least 2 activity events (initial + final)
    activity_events = [e for e in events if e["event"] == "activity"]
    assert len(activity_events) >= 2


# ---------------------------------------------------------------------------
# Tests: SSE HTTP endpoint
# ---------------------------------------------------------------------------


async def test_sse_stream_endpoint_content_type(
    client: AsyncClient, configure_tmp_output: Path
):
    """GET /api/v1/corpus/{id}/stream returns text/event-stream content type."""
    # Create a completed job so the stream terminates quickly
    corpus_id = await _create_corpus(client)
    jm = processing_mod.get_job_manager()
    job = ProcessingJob(
        corpus_id=corpus_id,
        status=ProcessingStatus.COMPLETED,
        progress_pct=100,
        total_units=5,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    await jm.save(job)

    async with client.stream("GET", f"/api/v1/corpus/{corpus_id}/stream") as resp:
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type


# ---------------------------------------------------------------------------
# Tests: Job status endpoint
# ---------------------------------------------------------------------------


async def test_get_job_status(client: AsyncClient, configure_tmp_output: Path):
    """GET /api/v1/corpus/{id}/job returns current job state."""
    corpus_id = await _create_corpus(client)
    jm = processing_mod.get_job_manager()
    job = ProcessingJob(
        corpus_id=corpus_id,
        status=ProcessingStatus.PROCESSING,
        current_stage="ingestion",
        progress_pct=28,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    await jm.save(job)

    resp = await client.get(f"/api/v1/corpus/{corpus_id}/job")
    assert resp.status_code == 200
    data = resp.json()
    assert data["corpus_id"] == corpus_id
    assert data["status"] == "processing"
    assert data["current_stage"] == "ingestion"
    assert data["progress_pct"] == 28


async def test_get_job_not_found(client: AsyncClient):
    """GET /api/v1/corpus/{id}/job returns 404 when no job exists."""
    await _create_corpus(client, name="Empty Corpus")
    resp = await client.get("/api/v1/corpus/empty-corpus/job")
    assert resp.status_code == 404
