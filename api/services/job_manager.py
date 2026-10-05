"""API job state on the durable queue (Phase 10 U2), plus the legacy JSON-file store.

Processing and discovery jobs used to be ``asyncio.create_task`` coroutines whose state lived in
one JSON file per corpus (``<output>/.jobs/<corpus>.json``); a restart orphaned them mid-run.
They now live in the SQLite queue (:mod:`folio_insights.jobs`). This module keeps the API's view
of a job, :class:`~api.models.processing.ProcessingJob`, as a projection of the queue row and
its event log, so the SSE stream and ``GET .../job`` read queue state.

* :class:`QueueJobView` -- what the routes call ``get_job_manager()`` / ``load_by_corpus``;
* :class:`JobRuntime` -- this API process's queue, credential store and embedded worker;
* :class:`JobManager` -- the legacy JSON-file store, kept read-only for the explicit one-time
  import (:func:`import_legacy_jobs`, CLI ``folio-insights jobs import-legacy``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.models.processing import ActivityEntry, ProcessingJob, ProcessingStatus
from folio_insights.jobs import (
    Job,
    JobStatus,
    JobWorker,
    SecretStore,
    SQLiteJobQueue,
    default_secret_store,
    new_owner_id,
)
from folio_insights.jobs.legacy import import_legacy_jobs  # noqa: F401 - re-exported

logger = logging.getLogger(__name__)

EXTRACT_KIND = "extract"
DISCOVER_KIND = "discover"

_QUEUE_TO_API: dict[JobStatus, ProcessingStatus] = {
    JobStatus.QUEUED: ProcessingStatus.PENDING,
    JobStatus.RUNNING: ProcessingStatus.PROCESSING,
    JobStatus.SUCCEEDED: ProcessingStatus.COMPLETED,
    JobStatus.FAILED: ProcessingStatus.FAILED,
    JobStatus.CANCELLED: ProcessingStatus.CANCELLED,
    JobStatus.NEEDS_CREDENTIALS: ProcessingStatus.NEEDS_CREDENTIALS,
    JobStatus.BUDGET_EXHAUSTED: ProcessingStatus.BUDGET_EXHAUSTED,
}
_API_TO_QUEUE: dict[ProcessingStatus, JobStatus] = {v: k for k, v in _QUEUE_TO_API.items()}


def _iso(ts: float | None) -> str:
    return datetime.fromtimestamp(ts or 0.0, tz=timezone.utc).isoformat()


def _ts(iso: str | None) -> float:
    if not iso:
        return datetime.now(timezone.utc).timestamp()
    try:
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return datetime.now(timezone.utc).timestamp()


def _uuid_for(job_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(job_id)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"folio-insights-job:{job_id}")


def to_processing_job(queue: SQLiteJobQueue, job: Job, corpus_key: str) -> ProcessingJob:
    """Project a queue row and its event log onto the API's ``ProcessingJob`` shape."""
    activity = [
        ActivityEntry(timestamp=_iso(ev.ts), stage=ev.stage, message=ev.message)
        for ev in queue.events(job.id)
        if ev.stage != "queue"  # queue bookkeeping stays out of the user-facing activity log
    ]
    result = job.result or {}
    return ProcessingJob(
        id=_uuid_for(job.id),
        corpus_id=corpus_key,
        status=_QUEUE_TO_API[job.status],
        current_stage=job.current_stage,
        progress_pct=job.progress_pct,
        total_units=int(result.get("total_units", 0) or 0),
        activity_log=activity,
        error=job.error if job.status is not JobStatus.SUCCEEDED else None,
        created_at=_iso(job.created_at),
        updated_at=_iso(job.updated_at),
    )


class QueueJobView:
    """The per-kind API view over the queue (replaces the JSON-file ``JobManager``).

    ``corpus_suffix`` keeps the discovery routes' historical key (``<corpus>_discovery``).
    """

    def __init__(self, queue: SQLiteJobQueue, kind: str, *, corpus_suffix: str = "") -> None:
        self.queue = queue
        self.kind = kind
        self.corpus_suffix = corpus_suffix

    def _base(self, corpus_key: str) -> str:
        if self.corpus_suffix and corpus_key.endswith(self.corpus_suffix):
            return corpus_key[: -len(self.corpus_suffix)]
        return corpus_key

    def latest(self, corpus_key: str) -> Job | None:
        return self.queue.latest_for(self.kind, self._base(corpus_key))

    async def load_by_corpus(self, corpus_key: str) -> ProcessingJob | None:
        """The latest job for a corpus, as the API reports it (reads queue state)."""

        def _load() -> ProcessingJob | None:
            job = self.latest(corpus_key)
            return None if job is None else to_processing_job(self.queue, job, corpus_key)

        return await asyncio.to_thread(_load)

    async def save(self, job: ProcessingJob) -> None:
        """Record a ``ProcessingJob`` snapshot (the legacy import path; tests seed state with it).

        Snapshots are display records: they carry no payload, so no worker can run one.
        """

        def _save() -> None:
            self.queue.import_snapshot(
                job_id=job.id.hex,
                kind=self.kind,
                corpus_id=self._base(job.corpus_id),
                status=_API_TO_QUEUE[job.status],
                created_at=_ts(job.created_at),
                updated_at=_ts(job.updated_at),
                current_stage=job.current_stage,
                progress_pct=job.progress_pct,
                result={"total_units": job.total_units},
                error=job.error,
                events=[(_ts(a.timestamp), a.stage, a.message) for a in job.activity_log],
                idempotency_key=f"snapshot:{job.id.hex}",
            )

        await asyncio.to_thread(_save)


# ---------------------------------------------------------------------------
# Process runtime: one queue, one credential store, one embedded worker
# ---------------------------------------------------------------------------


class JobRuntime:
    """This API process's queue, in-memory credential store and embedded worker identity."""

    def __init__(
        self,
        queue: SQLiteJobQueue,
        *,
        secret_store: SecretStore | None = None,
        owner: str | None = None,
    ) -> None:
        self.queue = queue
        self.secret_store = secret_store if secret_store is not None else default_secret_store()
        self.owner = owner or new_owner_id("api")
        self.worker: JobWorker | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None

    def build_worker(self, **kwargs: Any) -> JobWorker:
        from api.services.discovery_runner import run_discovery_job
        from api.services.pipeline_runner import run_extraction_job

        handlers = {EXTRACT_KIND: run_extraction_job, DISCOVER_KIND: run_discovery_job}
        kwargs.setdefault("lease_seconds", float(os.environ.get("FOLIO_INSIGHTS_JOB_LEASE_SECONDS", 120)))
        self.worker = JobWorker(
            self.queue, handlers, owner=self.owner, secret_store=self.secret_store, **kwargs
        )
        return self.worker

    def start(self) -> None:
        """Start the embedded worker on the running loop (the API lifespan calls this)."""
        if self._task is not None:
            return
        worker = self.worker or self.build_worker()
        self.queue.worker_heartbeat(self.owner)
        self._stop = asyncio.Event()
        self._task = asyncio.get_running_loop().create_task(worker.run(self._stop))

    async def stop(self) -> None:
        if self._task is None or self._stop is None:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=10)
        except asyncio.TimeoutError:
            self._task.cancel()
        self._task = None


_runtime: JobRuntime | None = None


def get_runtime() -> JobRuntime:
    """The process runtime, created on first use against ``default_queue_path()``."""
    global _runtime
    if _runtime is None:
        _runtime = JobRuntime(SQLiteJobQueue())
    return _runtime


def reset_runtime(runtime: JobRuntime | None = None) -> None:
    """Swap or drop the process runtime (tests; the next ``get_runtime`` rebuilds it)."""
    global _runtime
    _runtime = runtime


def get_queue() -> SQLiteJobQueue:
    return get_runtime().queue


# ---------------------------------------------------------------------------
# Legacy JSON-file store (read for the one-time import only)
# ---------------------------------------------------------------------------


class JobManager:
    """Persist ProcessingJob instances as JSON files on disk (pre-queue, legacy).

    Each corpus gets a single job file at ``{jobs_dir}/{corpus_id}.json``. Kept so
    :func:`import_legacy_jobs` can read existing files; new state goes to the queue.
    """

    def __init__(self, jobs_dir: Path) -> None:
        self.jobs_dir = Path(jobs_dir)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def _job_path(self, corpus_id: str) -> Path:
        return self.jobs_dir / f"{corpus_id}.json"

    async def save(self, job: ProcessingJob) -> None:
        """Atomically persist *job* to disk (temp file + ``os.replace``)."""
        job.updated_at = datetime.now(timezone.utc).isoformat()
        path = self._job_path(job.corpus_id)
        data = json.dumps(job.model_dump(), default=str, indent=2)

        def _write() -> None:
            fd, tmp_path = tempfile.mkstemp(dir=str(self.jobs_dir), suffix=".tmp")
            try:
                with open(fd, "w") as f:
                    f.write(data)
                os.replace(tmp_path, str(path))
            except BaseException:
                Path(tmp_path).unlink(missing_ok=True)
                raise

        await asyncio.to_thread(_write)

    async def load_by_corpus(self, corpus_id: str) -> ProcessingJob | None:
        """Load the ProcessingJob for *corpus_id*, or ``None`` if absent."""
        path = self._job_path(corpus_id)
        if not path.exists():
            return None
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return ProcessingJob.model_validate_json(text)

    async def delete(self, corpus_id: str) -> None:
        """Remove the job file for *corpus_id* if it exists."""
        path = self._job_path(corpus_id)
        if path.exists():
            path.unlink()


# ---------------------------------------------------------------------------
# Submission and control (shared by the processing and discovery routes)
# ---------------------------------------------------------------------------


class SubmitConflict(Exception):
    """A job of this kind is already active for the corpus."""

    def __init__(self, job: Job) -> None:
        super().__init__(job.status.value)
        self.job = job


def _route_provider(provider: str | None) -> Any:
    from folio_insights.llm.port import resolve_route
    from folio_insights.llm.providers import get_provider_spec

    from folio_insights.llm import LLMRunContext

    route = resolve_route("distiller", context=LLMRunContext(provider=provider))
    return get_provider_spec(route.provider)


def submit_job(
    view: QueueJobView,
    *,
    corpus_id: str,
    payload: dict[str, Any],
    api_key: str | None,
    idempotency_key: str | None,
) -> tuple[Job, bool]:
    """Enqueue an API job with a per-request key (BYOK, KTD3). Returns ``(job, created)``.

    * The key goes into this process's in-memory credential store under the new job's id
      *before* the row exists, and the row names this process's worker as the holder, so no
      other worker can lease a job whose key it does not have.
    * A provider that needs a key but got none enqueues the job as ``needs_credentials``.
    * Repeating a submission with the same ``Idempotency-Key`` returns the same job.
    * Submitting with a key while the corpus's job waits for one re-supplies it to that job.
    * Any other submission while a job is active raises :class:`SubmitConflict` (409).
    """
    from folio_insights.jobs import ActiveJobExists
    from folio_insights.llm import Credentials

    runtime = get_runtime()
    queue = runtime.queue
    llm = payload.get("llm") or {}
    spec = _route_provider(llm.get("provider"))
    idem = f"{view.kind}:{corpus_id}:{idempotency_key}" if idempotency_key else None

    if idem is not None:
        with queue.connect() as conn:
            row = conn.execute("SELECT id FROM jobs WHERE idempotency_key = ?", (idem,)).fetchone()
        if row is not None:
            existing = queue.get(row["id"])
            assert existing is not None
            return existing, False

    latest = view.latest(corpus_id)
    if latest is not None and latest.status is JobStatus.NEEDS_CREDENTIALS and api_key:
        return resupply_credentials(latest, api_key, provider=spec.name), False

    job_id = uuid.uuid4().hex
    holder: str | None = None
    status = JobStatus.QUEUED
    requires = False
    if api_key:
        runtime.secret_store.put(job_id, Credentials.single(spec.name, api_key))
        holder, requires = runtime.owner, True
    elif spec.requires_key:
        status, requires = JobStatus.NEEDS_CREDENTIALS, True
    try:
        job, created = queue.enqueue(
            view.kind,
            corpus_id=corpus_id,
            payload=payload,
            idempotency_key=idem,
            requires_credentials=requires,
            credential_holder=holder,
            job_id=job_id,
            status=status,
            exclusive=True,
        )
    except ActiveJobExists as exc:
        runtime.secret_store.discard(job_id)
        raise SubmitConflict(exc.job) from None
    if job.id != job_id:
        runtime.secret_store.discard(job_id)
    return job, created


def resupply_credentials(job: Job, api_key: str, *, provider: str | None = None) -> Job:
    """Give a ``needs_credentials`` job a fresh in-memory key held by this process's worker."""
    from folio_insights.llm import Credentials

    runtime = get_runtime()
    name = provider or _route_provider((job.payload.get("llm") or {}).get("provider")).name
    runtime.secret_store.put(job.id, Credentials.single(name, api_key))
    try:
        return runtime.queue.resupply_credentials(job.id, holder=runtime.owner)
    except Exception:
        runtime.secret_store.discard(job.id)
        raise
