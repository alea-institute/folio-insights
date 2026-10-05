"""Processing trigger, SSE stream and job control endpoints (durable queue, Phase 10 U2).

POST /api/v1/corpus/{corpus_id}/process              -- Enqueue an extraction job
GET  /api/v1/corpus/{corpus_id}/stream               -- SSE progress, read from queue state
GET  /api/v1/corpus/{corpus_id}/job                  -- Current job status
POST /api/v1/corpus/{corpus_id}/job/cancel           -- Cancel (at the next stage boundary)
POST /api/v1/corpus/{corpus_id}/job/credentials      -- Re-supply the API key to a paused job
POST /api/v1/corpus/{corpus_id}/job/resume           -- Resume a budget-exhausted job

Bring your own key: the caller's LLM API key travels in the ``X-LLM-API-Key`` header of the
request that needs it, is held in this process's memory for the job, and is never stored in the
queue, logs, checkpoints or outputs. The server never uses an ambient key.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.models.processing import STREAM_END_STATUSES
from api.services.job_manager import (
    EXTRACT_KIND,
    QueueJobView,
    SubmitConflict,
    get_queue,
    reset_runtime,
    resupply_credentials,
    submit_job,
    to_processing_job,
)
from folio_insights.jobs import JobStatus, QueueError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["processing"])


class LLMJobOptions(BaseModel):
    """Optional per-job LLM choices. The key itself goes in the ``X-LLM-API-Key`` header."""

    llm_provider: str | None = Field(default=None, description="openai | anthropic | google | ollama")
    llm_model: str | None = None
    max_spend_usd: float | None = Field(default=None, gt=0)


class ResumeRequest(BaseModel):
    max_spend_usd: float | None = Field(default=None, gt=0)


# ---------------------------------------------------------------------------
# Job view (reads the durable queue)
# ---------------------------------------------------------------------------

_job_manager: QueueJobView | None = None


def _output_dir() -> Path:
    """Lazy import to avoid circular dependency with api.main."""
    from api.main import _output_dir

    return _output_dir


def get_job_manager() -> QueueJobView:
    """The extraction-job view over the durable queue, created on first call."""
    global _job_manager
    if _job_manager is None:
        _job_manager = QueueJobView(get_queue(), EXTRACT_KIND)
    return _job_manager


def reset_job_manager() -> None:
    """Reset the singleton and the process job runtime (used by tests).

    The next call re-opens the queue at ``default_queue_path()`` (``$FOLIO_INSIGHTS_QUEUE_DB``).
    """
    global _job_manager
    _job_manager = None
    reset_runtime()


def llm_payload(options: LLMJobOptions | None) -> dict:
    """Validate the per-job LLM choices into a (secret-free) payload fragment."""
    from folio_insights.llm import LLMError
    from folio_insights.llm.providers import get_provider_spec

    if options is None:
        return {}
    out: dict = {}
    if options.llm_provider:
        try:
            out["provider"] = get_provider_spec(options.llm_provider).name
        except LLMError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    if options.llm_model:
        out["model"] = options.llm_model
    if options.max_spend_usd is not None:
        out["max_spend_usd"] = options.max_spend_usd
    return out


def submit_or_http_error(view: QueueJobView, **kwargs) -> dict:
    try:
        job, created = submit_job(view, **kwargs)
    except SubmitConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Processing already in progress (job {exc.job.id} is {exc.job.status.value})",
        ) from None
    view_job = to_processing_job(view.queue, job, kwargs["corpus_id"])
    return {"job_id": str(view_job.id), "queue_job_id": job.id,
            "status": view_job.status.value, "duplicate": not created}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/corpus/{corpus_id}/process", status_code=202)
async def start_processing(
    corpus_id: str,
    force: bool = False,
    options: LLMJobOptions | None = None,
    x_llm_api_key: str | None = Header(default=None, alias="X-LLM-API-Key"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    """Enqueue pipeline processing for a corpus.

    Returns 202 Accepted with the job id. A worker runs the job from the durable queue; follow it
    on the SSE stream endpoint. Without an ``X-LLM-API-Key`` (for a provider that needs one) the
    job waits as ``needs_credentials``.

    Args:
        force: If True, clear the corpus registry so all files are
               re-ingested and re-processed from scratch.
    """
    output = _output_dir()
    corpus_meta = output / corpus_id / "corpus-meta.json"
    if not corpus_meta.exists():
        raise HTTPException(status_code=404, detail=f"Corpus '{corpus_id}' not found")

    view = get_job_manager()
    latest = await asyncio.to_thread(view.latest, corpus_id)
    if force and (latest is None or not latest.is_active):
        registry_path = output / corpus_id / f"corpus-{corpus_id}.json"
        if registry_path.exists():
            registry_path.unlink()
            logger.info("Cleared corpus registry for force re-processing: %s", corpus_id)

    payload = {
        "corpus_name": corpus_id,
        "output_dir": str(output.resolve()),
        "source_dir": str((output / corpus_id / "sources").resolve()),
        "llm": llm_payload(options),
    }
    return await asyncio.to_thread(
        submit_or_http_error, view, corpus_id=corpus_id, payload=payload,
        api_key=x_llm_api_key, idempotency_key=idempotency_key,
    )


@router.get("/corpus/{corpus_id}/stream")
async def stream_progress(corpus_id: str):
    """SSE event stream for real-time processing progress (read from the queue).

    Emits events:
      - ``status``   -- when job status or stage changes
      - ``activity`` -- for each new activity log entry
      - ``complete`` -- when the job ends or pauses (completed, failed, cancelled,
                        needs_credentials, budget_exhausted)
      - ``error``    -- if no job is found
    """
    return EventSourceResponse(event_generator(corpus_id))


async def event_generator(corpus_id: str):
    """Yield SSE events by polling the job's queue state."""
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

        # Terminal or paused state: emit complete and exit
        if job.status in STREAM_END_STATUSES:
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


# ---------------------------------------------------------------------------
# Job control (shared helpers; discovery reuses them with its own view)
# ---------------------------------------------------------------------------


def _latest_or_404(view: QueueJobView, corpus_key: str):
    job = view.latest(corpus_key)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job found for '{corpus_key}'")
    return job


def cancel_latest(view: QueueJobView, corpus_key: str) -> dict:
    job = _latest_or_404(view, corpus_key)
    job = view.queue.request_cancel(job.id)
    return to_processing_job(view.queue, job, corpus_key).model_dump(mode="json")


def resupply_latest(view: QueueJobView, corpus_key: str, api_key: str | None) -> dict:
    if not api_key:
        raise HTTPException(status_code=422, detail="X-LLM-API-Key header is required")
    job = _latest_or_404(view, corpus_key)
    if job.status is not JobStatus.NEEDS_CREDENTIALS:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, not waiting for a key")
    try:
        job = resupply_credentials(job, api_key)
    except QueueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return to_processing_job(view.queue, job, corpus_key).model_dump(mode="json")


def resume_latest(view: QueueJobView, corpus_key: str, body: ResumeRequest | None) -> dict:
    job = _latest_or_404(view, corpus_key)
    if job.status is not JobStatus.BUDGET_EXHAUSTED:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, not budget_exhausted")
    try:
        if body is not None and body.max_spend_usd is not None:
            llm = dict(job.payload.get("llm") or {})
            llm["max_spend_usd"] = body.max_spend_usd
            view.queue.update_payload(job.id, {"llm": llm})
        job = view.queue.resume(job.id)
    except QueueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return to_processing_job(view.queue, job, corpus_key).model_dump(mode="json")


@router.post("/corpus/{corpus_id}/job/cancel")
async def cancel_job(corpus_id: str) -> dict:
    """Cancel the corpus's extraction job: now if waiting, else at the next stage boundary."""
    return await asyncio.to_thread(cancel_latest, get_job_manager(), corpus_id)


@router.post("/corpus/{corpus_id}/job/credentials")
async def resupply_job_credentials(
    corpus_id: str,
    x_llm_api_key: str | None = Header(default=None, alias="X-LLM-API-Key"),
) -> dict:
    """Re-supply the LLM API key to a job paused as ``needs_credentials``."""
    return await asyncio.to_thread(resupply_latest, get_job_manager(), corpus_id, x_llm_api_key)


@router.post("/corpus/{corpus_id}/job/resume")
async def resume_job(corpus_id: str, body: ResumeRequest | None = None) -> dict:
    """Resume a ``budget_exhausted`` job, optionally with a higher ``max_spend_usd``."""
    return await asyncio.to_thread(resume_latest, get_job_manager(), corpus_id, body)
