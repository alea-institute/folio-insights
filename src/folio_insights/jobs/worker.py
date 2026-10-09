"""The queue consumer: lease, heartbeat, run, settle (KTD6, R7).

A :class:`JobWorker` drains a :class:`~folio_insights.jobs.queue.JobQueue`. For each leased job
it:

1. looks up the job's in-memory credential handle when the job needs one (missing ->
   ``needs_credentials``, never an ambient key);
2. keeps the lease alive from a heartbeat *thread*, so a stage that blocks the event loop with
   CPU work cannot let the lease lapse while the process is healthy;
3. installs an :class:`~folio_insights.llm.LLMRunContext` (credentials, the job's provider/model,
   its cost meter) and runs the kind's handler;
4. settles the job: succeeded, retried, failed, cancelled at a stage boundary, or paused
   (``needs_credentials`` / ``budget_exhausted``).

Handlers report stage progress through :meth:`JobRunContext.report`, which is also where a
cancellation request or a lost lease stops the run, always at a stage boundary.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import threading
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from folio_insights.jobs.queue import Job, JobQueue, JobStatus, Lease, new_owner_id
from folio_insights.jobs.secrets import SecretStore, default_secret_store
from folio_insights.llm import (
    BudgetExhaustedError,
    Credentials,
    LLMModelNotFoundError,
    LLMRunContext,
    MissingCredentialsError,
    UnpricedModelError,
    use_context,
)
from folio_insights.llm.credentials import scrub

logger = logging.getLogger(__name__)


PAUSED_TTL_ENV = "FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS"
DEFAULT_PAUSED_TTL_SECONDS = 86400.0


def parse_paused_ttl(value: object) -> float:
    """Validate a paused-job TTL (seconds). Zero or negative means "never expire".

    Raises ``ValueError`` for anything unparsable or non-finite (``nan``, ``inf``): a typo must
    not silently turn the sweep off or make it expire everything.
    """
    if isinstance(value, bool):
        raise ValueError("paused-job TTL must be a number of seconds")
    try:
        ttl = float(str(value).strip()) if isinstance(value, str) else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"paused-job TTL must be a number of seconds, got {value!r}") from None
    if not math.isfinite(ttl):
        raise ValueError(f"paused-job TTL must be finite, got {value!r}")
    return ttl


def paused_ttl_from_env() -> float:
    """The configured paused-job TTL, read the same way the API reads it.

    When pydantic-settings is importable this is ``Settings().job_paused_ttl_seconds``: the
    process environment (``$FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS``), else the ``.env`` file,
    else one day, with the same validation. So a TTL configured only in ``.env`` applies to a
    standalone worker exactly as to the API's embedded one; two sweepers with different TTLs
    would otherwise let the shorter one win. The lean worker image has no pydantic, so there
    only the process environment is read (stdlib only), defaulting to one day.

    Raises ``ValueError`` for an invalid value from either source.
    """
    try:
        from folio_insights.config import Settings
    except ImportError:  # the lean worker image
        raw = (os.environ.get(PAUSED_TTL_ENV) or "").strip()
        return parse_paused_ttl(raw) if raw else DEFAULT_PAUSED_TTL_SECONDS
    # A fresh Settings (not the cached get_settings()) so a worker constructed later in a
    # long-lived process sees the configuration as it is now.
    return Settings().job_paused_ttl_seconds


class JobCancelled(Exception):
    """Raised at a stage boundary when the job's cancellation was requested."""


class LeaseLost(Exception):
    """Raised at a stage boundary when this worker no longer owns the job's lease."""


class PermanentJobError(Exception):
    """A failure retrying cannot fix (bad payload, failed integrity canary, failure ratio)."""


class StageFailureRatioError(RuntimeError):
    """Placeholder replaced below by the pipeline's class when it is importable."""


try:  # the lean worker image has no pydantic, so the pipeline package may not import
    from folio_insights.pipeline.stages.base import (  # type: ignore[no-redef]
        StageFailureRatioError,
    )
except ImportError:  # pragma: no cover - exercised by the lean-image test
    pass


@dataclass
class JobRunContext:
    """What a handler gets: the job, its credentials and a stage-boundary reporter."""

    job: Job
    lease: Lease
    queue: JobQueue
    owner: str
    credentials: Credentials
    llm: LLMRunContext
    lease_lost: threading.Event = field(default_factory=threading.Event)

    @property
    def payload(self) -> dict[str, Any]:
        return self.job.payload

    def checkpoint(self) -> None:
        """Stop here if the lease was lost or cancellation was requested."""
        if self.lease_lost.is_set():
            raise LeaseLost(f"lease on job {self.job.id} was lost")
        if self.queue.is_cancel_requested(self.job.id):
            raise JobCancelled("cancellation requested")

    def report(self, *, stage: str | None = None, progress_pct: int | None = None,
               message: str | None = None, check: bool = True) -> None:
        """Record progress (visible to SSE), then honour cancel / lease loss when ``check``."""
        if not self.queue.update_progress(self.lease, stage=stage, progress_pct=progress_pct,
                                          message=message):
            self.lease_lost.set()
        if check:
            self.checkpoint()


JobHandler = Callable[[JobRunContext], Awaitable[dict[str, Any] | None]]
MeterFactory = Callable[[Job, JobQueue], Any]


class _Heartbeat(threading.Thread):
    """Extends one lease (and the worker's presence) until stopped or the lease is lost."""

    def __init__(self, queue: JobQueue, lease: Lease, owner: str, lease_seconds: float,
                 lost: threading.Event) -> None:
        super().__init__(name=f"lease-heartbeat-{lease.job.id[:8]}", daemon=True)
        self._queue, self._lease, self._owner = queue, lease, owner
        self._lease_seconds = lease_seconds
        self._lost = lost
        self._stop_event = threading.Event()

    def run(self) -> None:
        interval = max(0.05, self._lease_seconds / 3.0)
        while not self._stop_event.wait(interval):
            try:
                if not self._queue.heartbeat(self._lease, lease_seconds=self._lease_seconds):
                    self._lost.set()
                    return
                self._queue.worker_heartbeat(self._owner)
            except Exception:  # noqa: BLE001 - a transient DB error must not kill the run
                logger.warning("lease heartbeat failed for job %s", self._lease.job.id,
                               exc_info=True)

    def stop(self) -> None:
        self._stop_event.set()


class JobWorker:
    """Consumes jobs of the kinds it has handlers for."""

    def __init__(
        self,
        queue: JobQueue,
        handlers: Mapping[str, JobHandler],
        *,
        owner: str | None = None,
        secret_store: SecretStore | None = None,
        lease_seconds: float = 60.0,
        poll_interval: float = 1.0,
        meter_factory: MeterFactory | None = None,
        paused_ttl_seconds: float | None = None,
    ) -> None:
        self.queue = queue
        self.handlers = dict(handlers)
        self.owner = owner or new_owner_id()
        self.secret_store = secret_store if secret_store is not None else default_secret_store()
        self.lease_seconds = lease_seconds
        self.poll_interval = poll_interval
        self.meter_factory = meter_factory
        # ``None`` reads the environment (the lean standalone worker has no Settings); the
        # embedded runtime passes the validated Settings value. <= 0 disables the sweep.
        self.paused_ttl_seconds = (
            paused_ttl_from_env() if paused_ttl_seconds is None
            else parse_paused_ttl(paused_ttl_seconds)
        )

    def __repr__(self) -> str:
        return f"JobWorker(owner={self.owner!r}, kinds={sorted(self.handlers)!r})"

    @property
    def kinds(self) -> Sequence[str]:
        return sorted(self.handlers)

    # ---- loop ----------------------------------------------------------------------------------

    async def run_once(self) -> bool:
        """Recover expired leases, then lease and run at most one job. ``True`` if one ran."""
        await asyncio.to_thread(self.queue.worker_heartbeat, self.owner)
        await asyncio.to_thread(self.queue.reclaim_expired)
        await self.expire_paused()
        if not self.handlers:
            return False
        lease = await asyncio.to_thread(
            self.queue.lease, self.owner, kinds=self.kinds, lease_seconds=self.lease_seconds
        )
        if lease is None:
            return False
        await self.run_lease(lease)
        return True

    async def expire_paused(self) -> list[str]:
        """Cancel abandoned paused jobs (R18) and drop their in-memory key handles.

        Idempotent across workers; a failure here is logged and never stops the poll loop.
        """
        if self.paused_ttl_seconds <= 0:
            return []
        try:
            expired = await asyncio.to_thread(
                self.queue.expire_paused, ttl_seconds=self.paused_ttl_seconds
            )
        except Exception:  # noqa: BLE001 - housekeeping must not block leasing
            logger.warning("paused-job expiry sweep failed", exc_info=True)
            return []
        for job_id in expired:
            self.secret_store.discard(job_id)
            logger.info("job %s expired: paused longer than %gs", job_id, self.paused_ttl_seconds)
        return expired

    async def run(self, stop: asyncio.Event | None = None, *, until_idle: bool = False) -> None:
        stop = stop or asyncio.Event()
        logger.info("job worker %s started (kinds=%s)", self.owner, ",".join(self.kinds) or "-")
        while not stop.is_set():
            try:
                ran = await self.run_once()
            except Exception:  # noqa: BLE001 - keep consuming; the queue holds the state
                logger.exception("job worker loop error")
                ran = False
            if ran:
                continue
            if until_idle:
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass
        logger.info("job worker %s stopped", self.owner)

    # ---- one job -------------------------------------------------------------------------------

    async def run_lease(self, lease: Lease) -> None:
        job = lease.job
        handler = self.handlers.get(job.kind)
        if handler is None:  # pragma: no cover - lease() filters by kind
            await asyncio.to_thread(self.queue.fail, lease, f"no handler for kind {job.kind!r}",
                                    retry=False)
            return

        credentials = Credentials.empty()
        if job.requires_credentials:
            held = self.secret_store.get(job.id)
            if held is None:
                await asyncio.to_thread(
                    self.queue.pause, lease, JobStatus.NEEDS_CREDENTIALS,
                    "this worker does not hold the job's API key (restarted?); re-supply it",
                )
                return
            credentials = held

        llm_payload = job.payload.get("llm") or {}
        secrets = credentials.secrets()
        try:
            meter = self.meter_factory(job, self.queue) if self.meter_factory else None
        except ValueError as exc:  # e.g. a malformed or infinite spend cap
            self.secret_store.discard(job.id)
            await asyncio.to_thread(self.queue.fail, lease, _error_text(exc, secrets), retry=False)
            return
        llm_ctx = LLMRunContext(
            credentials=credentials,
            provider=llm_payload.get("provider"),
            model=llm_payload.get("model"),
            pin_provider=bool(llm_payload.get("pin_provider")),
            run_id=job.id,
            meter=meter,
        )
        lost = threading.Event()
        ctx = JobRunContext(job=job, lease=lease, queue=self.queue, owner=self.owner,
                            credentials=credentials, llm=llm_ctx, lease_lost=lost)
        beat = _Heartbeat(self.queue, lease, self.owner, self.lease_seconds, lost)
        beat.start()
        try:
            with use_context(llm_ctx):
                try:
                    result = await handler(ctx)
                finally:
                    await llm_ctx.aclose()  # SDK clients hold the revealed key
        except JobCancelled as exc:
            self.secret_store.discard(job.id)
            await asyncio.to_thread(self.queue.mark_cancelled, lease, str(exc))
        except LeaseLost:
            # Another worker owns the job now; a key handle here would only linger.
            self.secret_store.discard(job.id)
            logger.warning("job %s: lease lost; another worker owns it now", job.id)
        except MissingCredentialsError as exc:  # includes a rejected key (LLMAuthError)
            self.secret_store.discard(job.id)
            await asyncio.to_thread(self.queue.pause, lease, JobStatus.NEEDS_CREDENTIALS,
                                    scrub(str(exc), secrets))
        except (BudgetExhaustedError, UnpricedModelError) as exc:
            # Whoever resumes past the cap must supply (and pay with) a key again.
            self.secret_store.discard(job.id)
            await asyncio.to_thread(self.queue.pause, lease, JobStatus.BUDGET_EXHAUSTED,
                                    scrub(str(exc), secrets))
        except (PermanentJobError, LLMModelNotFoundError, StageFailureRatioError) as exc:
            self.secret_store.discard(job.id)
            await asyncio.to_thread(self.queue.fail, lease, _error_text(exc, secrets), retry=False)
        except Exception as exc:  # noqa: BLE001 - retried by the queue's attempt budget
            logger.warning("job %s attempt failed: %s", job.id, type(exc).__name__)
            settled = await asyncio.to_thread(self.queue.fail, lease, _error_text(exc, secrets),
                                              retry=True)
            if settled is not None and settled.is_terminal:
                self.secret_store.discard(job.id)
        else:
            body = dict(result or {})
            body.setdefault("llm_usage", llm_ctx.usage_summary())
            if lost.is_set() or not await asyncio.to_thread(self.queue.complete, lease, body):
                logger.warning("job %s finished after losing its lease; result discarded", job.id)
            self.secret_store.discard(job.id)
        finally:
            beat.stop()
            beat.join(timeout=5)


def _error_text(exc: BaseException, secrets: list[Any]) -> str:
    return scrub(f"{type(exc).__name__}: {exc}", secrets)[:1000]
