"""Processing trigger and SSE stream endpoints.

POST /api/v1/corpus/{corpus_id}/process  -- Start background pipeline processing
GET  /api/v1/corpus/{corpus_id}/stream   -- SSE event stream for real-time progress
GET  /api/v1/corpus/{corpus_id}/job      -- Current job status (convenience)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from api.models.processing import ProcessingJob, ProcessingStatus
from api.services.job_manager import JobManager
from api.services.pipeline_runner import run_pipeline_with_progress

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["processing"])

# ---------------------------------------------------------------------------
# Singleton job manager (lazy-initialized)
# ---------------------------------------------------------------------------

_job_manager: JobManager | None = None


def _output_dir() -> Path:
    """Lazy import to avoid circular dependency with api.main."""
    from api.main import _output_dir

    return _output_dir


def get_job_manager() -> JobManager:
    """Return the module-level JobManager, creating it on first call."""
    global _job_manager
    if _job_manager is None:
        jobs_dir = _output_dir() / ".jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        _job_manager = JobManager(jobs_dir)
    return _job_manager


def reset_job_manager() -> None:
    """Reset the singleton (used by tests)."""
    global _job_manager
    _job_manager = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/corpus/{corpus_id}/process", status_code=202)
async def start_processing(corpus_id: str) -> dict:
    """Trigger pipeline processing for a corpus.

    Returns 202 Accepted with the job id. Processing runs in a
    background asyncio task. Connect to the SSE stream endpoint
    to follow progress in real time.
    """
    output = _output_dir()
    corpus_meta = output / corpus_id / "corpus-meta.json"
    if not corpus_meta.exists():
        raise HTTPException(status_code=404, detail=f"Corpus '{corpus_id}' not found")

    jm = get_job_manager()

    # Check for already-running job
    existing = await jm.load_by_corpus(corpus_id)
    if existing is not None and existing.status == ProcessingStatus.PROCESSING:
        raise HTTPException(status_code=409, detail="Processing already in progress")

    # Create new job
    now = _now_iso()
    job = ProcessingJob(
        corpus_id=corpus_id,
        status=ProcessingStatus.PENDING,
        created_at=now,
        updated_at=now,
    )
    await jm.save(job)

    # Launch background pipeline task
    source_dir = output / corpus_id / "sources"
    asyncio.create_task(
        run_pipeline_with_progress(corpus_id, source_dir, corpus_id, jm)
    )

    return {"job_id": str(job.id), "status": "pending"}


@router.get("/corpus/{corpus_id}/stream")
async def stream_progress(corpus_id: str):
    """SSE event stream for real-time processing progress.

    Emits events:
      - ``status``   -- when job status or stage changes
      - ``activity`` -- for each new activity log entry
      - ``complete`` -- when processing finishes (success or failure)
      - ``error``    -- if no job is found
    """
    return EventSourceResponse(event_generator(corpus_id))


async def event_generator(corpus_id: str):
    """Yield SSE events by polling the job file on disk."""
    jm = get_job_manager()
    last_status = None
    last_activity_count = 0

    while True:
        job = await jm.load_by_corpus(corpus_id)

        if job is None:
            yield {
                "event": "error",
                "data": json.dumps({"error": "No processing job found"}),
            }
            return

        # Emit status change
        if job.status != last_status:
            last_status = job.status
            yield {
                "event": "status",
                "data": json.dumps({
                    "job_id": str(job.id),
                    "status": job.status.value,
                    "stage": job.current_stage,
                    "progress": job.progress_pct,
                }),
            }

        # Emit new activity log entries
        if len(job.activity_log) > last_activity_count:
            for entry in job.activity_log[last_activity_count:]:
                yield {
                    "event": "activity",
                    "data": json.dumps({
                        "timestamp": entry.timestamp,
                        "stage": entry.stage,
                        "message": entry.message,
                    }),
                }
            last_activity_count = len(job.activity_log)

        # Terminal state: emit complete and exit
        if job.status in (ProcessingStatus.COMPLETED, ProcessingStatus.FAILED):
            yield {
                "event": "complete",
                "data": json.dumps({
                    "status": job.status.value,
                    "total_units": job.total_units,
                    "error": job.error,
                }),
            }
            return

        await asyncio.sleep(0.5)


@router.get("/corpus/{corpus_id}/job")
async def get_job(corpus_id: str) -> dict:
    """Return the current ProcessingJob for a corpus, or 404."""
    jm = get_job_manager()
    job = await jm.load_by_corpus(corpus_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"No processing job found for corpus '{corpus_id}'",
        )
    return job.model_dump()
