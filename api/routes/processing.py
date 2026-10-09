"""Processing trigger, SSE stream and job control endpoints (durable queue, Phase 10 U2).

POST /api/v1/corpus/{corpus_id}/process              -- Enqueue an extraction job
GET  /api/v1/corpus/{corpus_id}/stream               -- SSE progress, read from queue state
GET  /api/v1/corpus/{corpus_id}/job                  -- Current job status
POST /api/v1/corpus/{corpus_id}/job/cancel           -- Cancel (at the next stage boundary)
POST /api/v1/corpus/{corpus_id}/job/credentials      -- Re-supply the API key to a paused job
POST /api/v1/corpus/{corpus_id}/job/resume           -- Resume a budget-exhausted job

Security posture (Phase 10 review, 2026-10-05):

* **Bring your own key.** The caller's LLM API key travels in the ``X-LLM-API-Key`` header of
  the request that needs it, is held only in this process's memory for that job, and is never
  stored in the queue, logs, checkpoints or outputs. The server never uses an ambient key. The
  key is bound to the provider the request named (else the settings default) and the job is
  pinned to it, so the key is never sent to another provider or host.
* **Job control tokens.** Submitting and controlling a job are writes, so they need an operator
  token (``api/auth.py``, drain plan U5); read routes stay open, as deployed. Controlling a job
  needs more: cancel, resume and key re-supply act on a job that may be spending someone's
  key, so they also require the job's control token
  (``X-Job-Control-Token``). It is returned once, in the 202 response of the submission that
  created the job; only its SHA-256 is stored and it is compared in constant time. Without it
  the control routes answer 403.
* **Who pays past a cap.** A job that hits its spend cap drops its key from memory; resuming it
  requires a key again (``X-LLM-API-Key`` on ``/job/resume`` or ``/job/credentials``), so
  whoever raises the cap pays for what follows.
* **Keyless providers.** Ollama runs on the server's own hardware without a per-user key, so
  API jobs may use it only when the operator sets ``FOLIO_INSIGHTS_API_ALLOW_KEYLESS_PROVIDERS``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, model_validator
from sse_starlette.sse import EventSourceResponse

from api.auth import WRITE_GUARD
from api.models.processing import STREAM_END_STATUSES
from api.services.job_manager import (
    EXTRACT_KIND,
    QueueJobView,
    SubmitConflict,
    SubmitRefused,
    get_queue,
    get_runtime,
    reset_runtime,
    resupply_credentials,
    submit_job_controlled,
    to_processing_job,
)
from folio_insights.jobs import JobStatus, QueueError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["processing"], dependencies=WRITE_GUARD)


def _finite_cap(data: Any) -> Any:
    """Reject a non-finite cap before field validation, in a JSON-safe form.

    JSON ``Infinity`` parses to ``float('inf')``; letting the field reject it would echo ``inf``
    in the 422 body, which is not valid JSON.
    """
    if isinstance(data, dict):
        cap = data.get("max_spend_usd")
        if isinstance(cap, float) and not math.isfinite(cap):
            return {**data, "max_spend_usd": "non-finite"}
    return data


class LLMJobOptions(BaseModel):
    """Optional per-job LLM choices. The key itself goes in the ``X-LLM-API-Key`` header."""

    llm_provider: str | None = Field(default=None, description="openai | anthropic | google | ollama")
    llm_model: str | None = None
    max_spend_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    _finite = model_validator(mode="before")(_finite_cap)


class ResumeRequest(BaseModel):
    max_spend_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    _finite = model_validator(mode="before")(_finite_cap)


CONTROL_TOKEN_HEADER = "X-Job-Control-Token"


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
        job, created, control_token = submit_job_controlled(view, **kwargs)
    except SubmitRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except SubmitConflict as exc:
        detail = exc.reason or (
            f"Processing already in progress (job {exc.job.id} is {exc.job.status.value})")
        raise HTTPException(status_code=409, detail=detail) from None
    view_job = to_processing_job(view.queue, job, kwargs["corpus_id"])
    return {"job_id": str(view_job.id), "queue_job_id": job.id,
            "status": view_job.status.value, "duplicate": not created,
            # Returned once, on creation; needed to cancel, resume or re-key the job.
            "control_token": control_token}


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
    if force and latest is not None and latest.is_active:
        # force means "re-ingest everything", which must not race a job still using the corpus.
        raise HTTPException(
            status_code=409,
            detail=f"force cannot apply while job {latest.id} is {latest.status.value}; "
                   "cancel it first",
        )
    if force:
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


def _controlled_job(view: QueueJobView, corpus_key: str, control_token: str | None):
    """The latest job, if the caller holds its control token; else 403 (never says why)."""
    job = _latest_or_404(view, corpus_key)
    if not view.queue.verify_control(job.id, control_token):
        raise HTTPException(status_code=403, detail=f"{CONTROL_TOKEN_HEADER} missing or invalid")
    return job


def cancel_latest(view: QueueJobView, corpus_key: str, control_token: str | None = None) -> dict:
    job = _controlled_job(view, corpus_key, control_token)
    job = view.queue.request_cancel(job.id)
    if job.is_terminal:
        get_runtime().secret_store.discard(job.id)
    return to_processing_job(view.queue, job, corpus_key).model_dump(mode="json")


def resupply_latest(view: QueueJobView, corpus_key: str, api_key: str | None,
                    control_token: str | None = None) -> dict:
    job = _controlled_job(view, corpus_key, control_token)
    if not api_key:
        raise HTTPException(status_code=422, detail="X-LLM-API-Key header is required")
    if job.status is not JobStatus.NEEDS_CREDENTIALS:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, not waiting for a key")
    try:
        job = resupply_credentials(job, api_key)
    except QueueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return to_processing_job(view.queue, job, corpus_key).model_dump(mode="json")


def resume_latest(view: QueueJobView, corpus_key: str, body: ResumeRequest | None,
                  control_token: str | None = None, api_key: str | None = None) -> dict:
    job = _controlled_job(view, corpus_key, control_token)
    if job.status is not JobStatus.BUDGET_EXHAUSTED:
        raise HTTPException(status_code=409, detail=f"Job is {job.status.value}, not budget_exhausted")
    try:
        if body is not None and body.max_spend_usd is not None:
            llm = dict(job.payload.get("llm") or {})
            llm["max_spend_usd"] = body.max_spend_usd
            view.queue.update_payload(job.id, {"llm": llm})
        job = view.queue.resume(job.id)
        if job.status is JobStatus.NEEDS_CREDENTIALS and api_key:
            job = resupply_credentials(job, api_key)
    except QueueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return to_processing_job(view.queue, job, corpus_key).model_dump(mode="json")


@router.post("/corpus/{corpus_id}/job/cancel")
async def cancel_job(
    corpus_id: str,
    x_job_control_token: str | None = Header(default=None, alias=CONTROL_TOKEN_HEADER),
) -> dict:
    """Cancel the corpus's extraction job: now if waiting, else at the next stage boundary."""
    return await asyncio.to_thread(cancel_latest, get_job_manager(), corpus_id, x_job_control_token)


@router.post("/corpus/{corpus_id}/job/credentials")
async def resupply_job_credentials(
    corpus_id: str,
    x_llm_api_key: str | None = Header(default=None, alias="X-LLM-API-Key"),
    x_job_control_token: str | None = Header(default=None, alias=CONTROL_TOKEN_HEADER),
) -> dict:
    """Re-supply the LLM API key to a job paused as ``needs_credentials``."""
    return await asyncio.to_thread(resupply_latest, get_job_manager(), corpus_id, x_llm_api_key,
                                   x_job_control_token)


@router.post("/corpus/{corpus_id}/job/resume")
async def resume_job(
    corpus_id: str,
    body: ResumeRequest | None = None,
    x_llm_api_key: str | None = Header(default=None, alias="X-LLM-API-Key"),
    x_job_control_token: str | None = Header(default=None, alias=CONTROL_TOKEN_HEADER),
) -> dict:
    """Resume a ``budget_exhausted`` job, optionally with a higher ``max_spend_usd``.

    The key was dropped at the cap, so the job resumes as ``needs_credentials`` unless this
    request carries ``X-LLM-API-Key`` (the resumer pays for what follows).
    """
    return await asyncio.to_thread(resume_latest, get_job_manager(), corpus_id, body,
                                   x_job_control_token, x_llm_api_key)
