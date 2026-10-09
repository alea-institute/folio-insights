"""Durable job queue: a SQLite lease table behind a swappable protocol (KTD6, R7).

Jobs survive API and worker restarts because their state lives in a ``jobs`` table, not in an
``asyncio`` task. A worker *leases* a queued job for a bounded time and keeps the lease alive
with heartbeats; if the worker dies, the lease expires and :meth:`SQLiteJobQueue.reclaim_expired`
puts the job back in the queue so another worker resumes it from its stage checkpoint. Every
write runs under ``BEGIN IMMEDIATE`` in WAL mode (the same serialized-writer discipline the
Phase 13 store proved), so two workers can never lease the same job.

State machine::

    queued --lease--> running --complete--> succeeded
       ^                 |  \\--fail (retries left)--> queued (after back-off)
       |                 |   \\-fail (no retries)----> failed
       |                 |----cancel at a stage boundary--> cancelled
       |                 |----halt: no credential------> needs_credentials --resupply--> queued
       |                 |----halt: spend cap----------> budget_exhausted --resume----> queued
       \\--lease expired (worker crash)--/   (a credential job goes to needs_credentials:
                                              the dead worker's in-memory key is gone)

**No secrets in the queue (KTD3).** Payloads are JSON and are refused if they carry a field
that looks like a credential; a user's key lives only in the leasing worker's memory
(``folio_insights.jobs.secrets``). The queue records only *whether* a job needs one and which
live worker holds it.

The :class:`JobQueue` protocol is the escape hatch: an Arq/Redis implementation could replace
this one if multi-host scale ever needs it.
"""

from __future__ import annotations

import enum
import hashlib
import hmac
import json
import math
import os
import re
import socket
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

SCHEMA_VERSION = 1
QUEUE_DB_ENV = "FOLIO_INSIGHTS_QUEUE_DB"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_CREDENTIALS = "needs_credentials"
    BUDGET_EXHAUSTED = "budget_exhausted"


TERMINAL = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})
PAUSED = frozenset({JobStatus.NEEDS_CREDENTIALS, JobStatus.BUDGET_EXHAUSTED})
ACTIVE = frozenset({JobStatus.QUEUED, JobStatus.RUNNING}) | PAUSED


class QueueError(Exception):
    """A queue operation was refused (bad payload, illegal transition, unknown job)."""


class ActiveJobExists(QueueError):
    """An exclusive enqueue found an active job of the same kind for the same corpus."""

    def __init__(self, job: Job) -> None:
        super().__init__(f"{job.kind} job {job.id} for {job.corpus_id!r} is {job.status.value}")
        self.job = job


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    corpus_id: str
    status: JobStatus
    payload: dict[str, Any]
    idempotency_key: str | None
    attempts: int
    max_attempts: int
    requires_credentials: bool
    credential_holder: str | None
    cancel_requested: bool
    current_stage: str | None
    progress_pct: int
    result: dict[str, Any] | None
    error: str | None
    lease_owner: str | None
    lease_expires_at: float | None
    available_at: float
    created_at: float
    updated_at: float
    started_at: float | None
    finished_at: float | None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE


@dataclass(frozen=True)
class Lease:
    """Proof that one worker owns one running job until ``expires_at``."""

    job: Job
    owner: str
    token: str
    expires_at: float


@dataclass(frozen=True)
class JobEvent:
    job_id: str
    seq: int
    ts: float
    stage: str
    message: str


class JobQueue(Protocol):
    """The queue contract the API, the worker and the CLI depend on."""

    def enqueue(
        self,
        kind: str,
        *,
        corpus_id: str = "",
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        requires_credentials: bool = False,
        credential_holder: str | None = None,
        max_attempts: int = 3,
        job_id: str | None = None,
        status: JobStatus = JobStatus.QUEUED,
        exclusive: bool = False,
    ) -> tuple[Job, bool]: ...

    def lease(self, owner: str, *, kinds: Sequence[str] | None = None,
              lease_seconds: float = 30.0) -> Lease | None: ...

    def heartbeat(self, lease: Lease, *, lease_seconds: float = 30.0) -> bool: ...

    def update_progress(self, lease: Lease, *, stage: str | None = None,
                        progress_pct: int | None = None, message: str | None = None) -> bool: ...

    def complete(self, lease: Lease, result: dict[str, Any] | None = None) -> bool: ...

    def fail(self, lease: Lease, error: str, *, retry: bool = True) -> Job | None: ...

    def pause(self, lease: Lease, status: JobStatus, reason: str) -> bool: ...

    def mark_cancelled(self, lease: Lease, reason: str = "cancelled") -> bool: ...

    def request_cancel(self, job_id: str) -> Job: ...

    def is_cancel_requested(self, job_id: str) -> bool: ...

    def resupply_credentials(self, job_id: str, *, holder: str) -> Job: ...

    def resume(self, job_id: str) -> Job: ...

    def reclaim_expired(self) -> list[str]: ...

    def expire_paused(self, *, ttl_seconds: float, now: float | None = None) -> list[str]: ...

    def get(self, job_id: str) -> Job | None: ...

    def latest_for(self, kind: str, corpus_id: str) -> Job | None: ...

    def events(self, job_id: str, after_seq: int = 0) -> list[JobEvent]: ...

    def add_event(self, job_id: str, stage: str, message: str) -> None: ...

    def worker_heartbeat(self, owner: str) -> None: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS queue_meta (
    name  TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id                   TEXT PRIMARY KEY,
    kind                 TEXT NOT NULL,
    corpus_id            TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL,
    payload              TEXT NOT NULL DEFAULT '{}',
    idempotency_key      TEXT UNIQUE,
    attempts             INTEGER NOT NULL DEFAULT 0,
    max_attempts         INTEGER NOT NULL DEFAULT 3,
    requires_credentials INTEGER NOT NULL DEFAULT 0,
    credential_holder    TEXT,
    cancel_requested     INTEGER NOT NULL DEFAULT 0,
    current_stage        TEXT,
    progress_pct         INTEGER NOT NULL DEFAULT 0,
    result               TEXT,
    error                TEXT,
    lease_owner          TEXT,
    lease_token          TEXT,
    lease_expires_at     REAL,
    available_at         REAL NOT NULL,
    created_at           REAL NOT NULL,
    updated_at           REAL NOT NULL,
    started_at           REAL,
    finished_at          REAL,
    control_token_sha256 TEXT
);
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs (status, available_at, created_at);
CREATE INDEX IF NOT EXISTS jobs_by_corpus ON jobs (kind, corpus_id, created_at);
CREATE TABLE IF NOT EXISTS job_events (
    job_id  TEXT NOT NULL,
    seq     INTEGER NOT NULL,
    ts      REAL NOT NULL,
    stage   TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    PRIMARY KEY (job_id, seq)
);
CREATE TABLE IF NOT EXISTS workers (
    owner        TEXT PRIMARY KEY,
    pid          INTEGER,
    host         TEXT,
    heartbeat_at REAL NOT NULL
);
"""

# A payload field whose NAME looks like a credential is refused outright: keys never enter the
# queue table, even by accident.
_SECRETISH = re.compile(
    r"(^|[_-])(api[_-]?key|apikey|key|secret|token|password|passwd|credentials?|authorization"
    r"|bearer)$",
    re.IGNORECASE,
)


def _check_payload(payload: Any, path: str = "payload") -> None:
    if isinstance(payload, dict):
        for k, v in payload.items():
            if _SECRETISH.search(str(k)):
                raise QueueError(f"{path}.{k}: credential-like fields may not be stored in the queue")
            _check_payload(v, f"{path}.{k}")
    elif isinstance(payload, (list, tuple)):
        for i, v in enumerate(payload):
            _check_payload(v, f"{path}[{i}]")


def default_queue_path() -> Path:
    """``$FOLIO_INSIGHTS_QUEUE_DB``, else ``<corpus storage root>/queue/jobs.sqlite3``."""
    env = (os.environ.get(QUEUE_DB_ENV) or "").strip()
    if env:
        return Path(env).expanduser()
    # Same resolution as ``governance.cli._state.resolve_corpus_root`` (kept import-free here:
    # the lean worker image has no click/pydantic; a test pins the two together).
    root = (os.environ.get("FOLIO_INSIGHTS_CORPUS_ROOT") or "").strip()
    base = Path(root).expanduser() if root else Path.home() / ".folio-insights" / "corpora"
    return base / "queue" / "jobs.sqlite3"


def new_owner_id(prefix: str = "worker") -> str:
    """A worker identity unique to this process start (a restart is a new worker)."""
    return f"{prefix}:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class SQLiteJobQueue:
    """The single-host durable queue. Safe across threads and processes."""

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        clock: Callable[[], float] = time.time,
        worker_ttl_seconds: float = 60.0,
        retry_backoff_seconds: float = 2.0,
    ) -> None:
        self.path = Path(path) if path is not None else default_queue_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self.worker_ttl_seconds = worker_ttl_seconds
        self.retry_backoff_seconds = retry_backoff_seconds
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
            if "control_token_sha256" not in cols:  # queues created before job control tokens
                conn.execute("ALTER TABLE jobs ADD COLUMN control_token_sha256 TEXT")
            conn.execute(
                "INSERT OR IGNORE INTO queue_meta (name, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:  # pragma: no cover - best effort on exotic filesystems
            pass

    def __repr__(self) -> str:
        return f"SQLiteJobQueue({str(self.path)!r})"

    # ---- connection helpers ------------------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """One serialized write transaction (``BEGIN IMMEDIATE``)."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def connect(self) -> Any:
        """A read/write connection context for co-located tables (the usage ledger)."""
        return self._connect()

    def write_transaction(self) -> Any:
        return self._write()

    def now(self) -> float:
        return self._clock()

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            kind=row["kind"],
            corpus_id=row["corpus_id"],
            status=JobStatus(row["status"]),
            payload=json.loads(row["payload"] or "{}"),
            idempotency_key=row["idempotency_key"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            requires_credentials=bool(row["requires_credentials"]),
            credential_holder=row["credential_holder"],
            cancel_requested=bool(row["cancel_requested"]),
            current_stage=row["current_stage"],
            progress_pct=row["progress_pct"],
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            available_at=row["available_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    @staticmethod
    def _get(conn: sqlite3.Connection, job_id: str) -> Job | None:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return SQLiteJobQueue._row_to_job(row) if row else None

    def _event(self, conn: sqlite3.Connection, job_id: str, stage: str, message: str) -> None:
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM job_events WHERE job_id = ?", (job_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO job_events (job_id, seq, ts, stage, message) VALUES (?, ?, ?, ?, ?)",
            (job_id, seq, self.now(), stage or "", message),
        )

    # ---- enqueue -------------------------------------------------------------------------------

    def enqueue(
        self,
        kind: str,
        *,
        corpus_id: str = "",
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        requires_credentials: bool = False,
        credential_holder: str | None = None,
        max_attempts: int = 3,
        job_id: str | None = None,
        status: JobStatus = JobStatus.QUEUED,
        exclusive: bool = False,
        control_token: str | None = None,
    ) -> tuple[Job, bool]:
        """Add a job; with an ``idempotency_key`` already present, return that job instead.

        ``control_token`` (optional) is the secret a caller must present to cancel, resume or
        re-key the job (:meth:`verify_control`). Only its SHA-256 is stored.

        ``exclusive`` refuses (:class:`ActiveJobExists`) when another job of the same kind is
        active for the same corpus; the check and the insert share one ``BEGIN IMMEDIATE``
        transaction, so two concurrent submissions cannot both pass it.

        Returns ``(job, created)``.
        """
        if status not in (JobStatus.QUEUED, JobStatus.NEEDS_CREDENTIALS):
            raise QueueError(f"a job cannot be enqueued as {status.value}")
        body = dict(payload or {})
        _check_payload(body)
        encoded = json.dumps(body, sort_keys=True)  # raises TypeError on a SecretKey
        job_id = job_id or uuid.uuid4().hex
        now = self.now()
        with self._write() as conn:
            if idempotency_key is not None:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
                ).fetchone()
                if row is not None:
                    return self._row_to_job(row), False
            if exclusive:
                active = conn.execute(
                    f"SELECT * FROM jobs WHERE kind = ? AND corpus_id = ? AND status IN "
                    f"({', '.join('?' for _ in ACTIVE)}) ORDER BY created_at DESC LIMIT 1",
                    (kind, corpus_id, *(s.value for s in ACTIVE)),
                ).fetchone()
                if active is not None:
                    raise ActiveJobExists(self._row_to_job(active))
            conn.execute(
                """INSERT INTO jobs (id, kind, corpus_id, status, payload, idempotency_key,
                       max_attempts, requires_credentials, credential_holder, available_at,
                       created_at, updated_at, control_token_sha256)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, kind, corpus_id, status.value, encoded, idempotency_key,
                 max(1, int(max_attempts)), int(requires_credentials), credential_holder,
                 now, now, now, _token_hash(control_token) if control_token else None),
            )
            self._event(conn, job_id, "queue", f"{kind} job queued")
            if status is JobStatus.NEEDS_CREDENTIALS:
                waiting = "waiting for an API key: none was supplied with the request"
                conn.execute("UPDATE jobs SET error = ? WHERE id = ?", (waiting, job_id))
                self._event(conn, job_id, "queue", waiting)
            job = self._get(conn, job_id)
        assert job is not None
        return job, True

    # ---- worker side ---------------------------------------------------------------------------

    def lease(
        self,
        owner: str,
        *,
        kinds: Sequence[str] | None = None,
        lease_seconds: float = 30.0,
    ) -> Lease | None:
        """Atomically claim the oldest runnable job, or return ``None``.

        A job that needs a credential is runnable only by the worker holding its in-memory key.
        """
        now = self.now()
        params: list[Any] = [JobStatus.QUEUED.value, now, owner]
        kind_sql = ""
        if kinds:
            kind_sql = f" AND kind IN ({', '.join('?' for _ in kinds)})"
            params.extend(kinds)
        token = uuid.uuid4().hex
        with self._write() as conn:
            row = conn.execute(
                "SELECT id FROM jobs WHERE status = ? AND available_at <= ?"
                " AND (requires_credentials = 0 OR credential_holder = ?)"
                f"{kind_sql} ORDER BY created_at, id LIMIT 1",
                params,
            ).fetchone()
            if row is None:
                return None
            expires = now + lease_seconds
            conn.execute(
                """UPDATE jobs SET status = ?, lease_owner = ?, lease_token = ?,
                       lease_expires_at = ?, attempts = attempts + 1,
                       started_at = COALESCE(started_at, ?), updated_at = ?
                   WHERE id = ? AND status = ?""",
                (JobStatus.RUNNING.value, owner, token, expires, now, now, row["id"],
                 JobStatus.QUEUED.value),
            )
            job = self._get(conn, row["id"])
            assert job is not None
            self._event(conn, job.id, "queue", f"leased by worker (attempt {job.attempts})")
        return Lease(job=job, owner=owner, token=token, expires_at=expires)

    def _owned(self, conn: sqlite3.Connection, lease: Lease) -> bool:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE id = ? AND lease_token = ? AND status = ?",
            (lease.job.id, lease.token, JobStatus.RUNNING.value),
        ).fetchone()
        return row is not None

    def heartbeat(self, lease: Lease, *, lease_seconds: float = 30.0) -> bool:
        """Extend the lease. ``False`` means the lease was lost (expired and reclaimed)."""
        now = self.now()
        with self._write() as conn:
            cur = conn.execute(
                "UPDATE jobs SET lease_expires_at = ?, updated_at = ?"
                " WHERE id = ? AND lease_token = ? AND status = ?",
                (now + lease_seconds, now, lease.job.id, lease.token, JobStatus.RUNNING.value),
            )
            return cur.rowcount == 1

    def update_progress(
        self,
        lease: Lease,
        *,
        stage: str | None = None,
        progress_pct: int | None = None,
        message: str | None = None,
    ) -> bool:
        now = self.now()
        with self._write() as conn:
            if not self._owned(conn, lease):
                return False
            sets, params = ["updated_at = ?"], [now]
            if stage is not None:
                sets.append("current_stage = ?")
                params.append(stage)
            if progress_pct is not None:
                sets.append("progress_pct = ?")
                params.append(max(0, min(100, int(progress_pct))))
            conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", (*params, lease.job.id))
            if message:
                self._event(conn, lease.job.id, stage or "", message)
            return True

    def _finish(
        self,
        lease: Lease,
        status: JobStatus,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        message: str | None = None,
        stage: str = "queue",
        extra_sets: str = "",
    ) -> bool:
        now = self.now()
        with self._write() as conn:
            if not self._owned(conn, lease):
                return False
            terminal = status in TERMINAL
            conn.execute(
                f"""UPDATE jobs SET status = ?, result = COALESCE(?, result), error = ?,
                        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                        updated_at = ?, finished_at = ?{extra_sets}
                    WHERE id = ?""",
                (status.value, json.dumps(result, sort_keys=True) if result is not None else None,
                 error, now, now if terminal else None, lease.job.id),
            )
            if message:
                self._event(conn, lease.job.id, stage, message)
            return True

    def complete(self, lease: Lease, result: dict[str, Any] | None = None) -> bool:
        body = dict(result or {})
        _check_payload(body, "result")
        return self._finish(lease, JobStatus.SUCCEEDED, result=body,
                            message="job succeeded", extra_sets=", progress_pct = 100")

    def fail(self, lease: Lease, error: str, *, retry: bool = True) -> Job | None:
        """Record a failure: back to the queue with back-off while retries remain, else failed."""
        now = self.now()
        with self._write() as conn:
            if not self._owned(conn, lease):
                return None
            job = self._get(conn, lease.job.id)
            assert job is not None
            if retry and job.attempts < job.max_attempts:
                delay = min(self.retry_backoff_seconds * (2 ** (job.attempts - 1)), 300.0)
                conn.execute(
                    """UPDATE jobs SET status = ?, error = ?, lease_owner = NULL,
                           lease_token = NULL, lease_expires_at = NULL, available_at = ?,
                           updated_at = ? WHERE id = ?""",
                    (JobStatus.QUEUED.value, error, now + delay, now, job.id),
                )
                self._event(conn, job.id, job.current_stage or "queue",
                            f"attempt {job.attempts} failed; retrying in {delay:.0f}s: {error}")
            else:
                conn.execute(
                    """UPDATE jobs SET status = ?, error = ?, lease_owner = NULL,
                           lease_token = NULL, lease_expires_at = NULL, updated_at = ?,
                           finished_at = ? WHERE id = ?""",
                    (JobStatus.FAILED.value, error, now, now, job.id),
                )
                self._event(conn, job.id, job.current_stage or "queue", f"job failed: {error}")
            return self._get(conn, job.id)

    def pause(self, lease: Lease, status: JobStatus, reason: str) -> bool:
        """Pause a running job. A pause is not a failure: it gives the lease's attempt back.

        Both pauses drop the credential holder: the worker discards the in-memory key, so
        whoever resumes the job must supply a key again (and pays for what follows).
        """
        if status not in PAUSED:
            raise QueueError(f"{status.value} is not a pause state")
        return self._finish(lease, status, error=reason, message=f"paused ({status.value}): {reason}",
                            extra_sets=", credential_holder = NULL, attempts = MAX(attempts - 1, 0)")

    def mark_cancelled(self, lease: Lease, reason: str = "cancelled") -> bool:
        return self._finish(lease, JobStatus.CANCELLED, error=reason,
                            message=f"job cancelled: {reason}")

    # ---- control plane -------------------------------------------------------------------------

    def request_cancel(self, job_id: str) -> Job:
        """Cancel now if the job is not running; otherwise flag it for the next stage boundary."""
        now = self.now()
        with self._write() as conn:
            job = self._get(conn, job_id)
            if job is None:
                raise QueueError(f"no job {job_id!r}")
            if job.status in TERMINAL:
                return job
            if job.status is JobStatus.RUNNING:
                conn.execute(
                    "UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE id = ?",
                    (now, job_id),
                )
                self._event(conn, job_id, job.current_stage or "queue",
                            "cancellation requested; stopping at the next stage boundary")
            else:
                conn.execute(
                    """UPDATE jobs SET status = ?, cancel_requested = 1, error = ?,
                           credential_holder = NULL, updated_at = ?, finished_at = ?
                       WHERE id = ?""",
                    (JobStatus.CANCELLED.value, "cancelled before it ran", now, now, job_id),
                )
                self._event(conn, job_id, "queue", "job cancelled")
            out = self._get(conn, job_id)
        assert out is not None
        return out

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return bool(row and row[0])

    def resupply_credentials(self, job_id: str, *, holder: str) -> Job:
        """A user re-supplied the key to worker ``holder``: ``needs_credentials`` -> ``queued``."""
        now = self.now()
        with self._write() as conn:
            job = self._get(conn, job_id)
            if job is None:
                raise QueueError(f"no job {job_id!r}")
            if job.status is not JobStatus.NEEDS_CREDENTIALS:
                raise QueueError(f"job is {job.status.value}, not waiting for credentials")
            conn.execute(
                """UPDATE jobs SET status = ?, credential_holder = ?, requires_credentials = 1,
                       error = NULL, available_at = ?, updated_at = ? WHERE id = ?""",
                (JobStatus.QUEUED.value, holder, now, now, job_id),
            )
            self._event(conn, job_id, "queue", "API key re-supplied; job queued")
            out = self._get(conn, job_id)
        assert out is not None
        return out

    def resume(self, job_id: str) -> Job:
        """Re-queue a ``budget_exhausted`` job (after the cap was raised)."""
        now = self.now()
        with self._write() as conn:
            job = self._get(conn, job_id)
            if job is None:
                raise QueueError(f"no job {job_id!r}")
            if job.status is not JobStatus.BUDGET_EXHAUSTED:
                raise QueueError(f"job is {job.status.value}, not budget_exhausted")
            new_status = (
                JobStatus.NEEDS_CREDENTIALS
                if job.requires_credentials and job.credential_holder is None
                else JobStatus.QUEUED
            )
            if new_status is JobStatus.NEEDS_CREDENTIALS:
                conn.execute("UPDATE jobs SET error = ? WHERE id = ?",
                             ("resumed: waiting for an API key", job_id))
            conn.execute(
                "UPDATE jobs SET status = ?, available_at = ?, updated_at = ?,"
                " error = CASE WHEN ? = 'queued' THEN NULL ELSE error END WHERE id = ?",
                (new_status.value, now, now, new_status.value, job_id),
            )
            self._event(conn, job_id, "queue", f"resumed after spend cap ({new_status.value})")
            out = self._get(conn, job_id)
        assert out is not None
        return out

    def update_payload(self, job_id: str, updates: dict[str, Any]) -> Job:
        """Merge non-secret fields into a paused or queued job's payload (e.g. a new spend cap)."""
        _check_payload(updates)
        with self._write() as conn:
            job = self._get(conn, job_id)
            if job is None:
                raise QueueError(f"no job {job_id!r}")
            if job.status in TERMINAL or job.status is JobStatus.RUNNING:
                raise QueueError(f"cannot change the payload of a {job.status.value} job")
            merged = {**job.payload, **updates}
            conn.execute("UPDATE jobs SET payload = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(merged, sort_keys=True), self.now(), job_id))
            out = self._get(conn, job_id)
        assert out is not None
        return out

    def reclaim_expired(self) -> list[str]:
        """Return expired leases to the queue (crash recovery). Returns the reclaimed job ids.

        * a job that still has attempts left and needs no credential -> ``queued`` (it resumes
          from its stage checkpoint on the next lease);
        * a job that needs a credential -> ``needs_credentials`` (its key lived only in the dead
          worker's memory);
        * a job out of attempts -> ``failed``.

        Also parks queued credential jobs whose holder stopped heart-beating.
        """
        now = self.now()
        reclaimed: list[str] = []
        with self._write() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? AND lease_expires_at IS NOT NULL"
                " AND lease_expires_at < ?",
                (JobStatus.RUNNING.value, now),
            ).fetchall()
            for row in rows:
                job = self._row_to_job(row)
                if job.attempts >= job.max_attempts:
                    status, msg = JobStatus.FAILED, (
                        f"lease expired after {job.attempts} attempt(s); giving up")
                elif job.requires_credentials:
                    status, msg = JobStatus.NEEDS_CREDENTIALS, (
                        "worker stopped; the API key was held only in its memory, "
                        "re-supply it to continue")
                else:
                    status, msg = JobStatus.QUEUED, "worker stopped; lease expired, job re-queued"
                conn.execute(
                    """UPDATE jobs SET status = ?, lease_owner = NULL, lease_token = NULL,
                           lease_expires_at = NULL, available_at = ?, updated_at = ?,
                           error = CASE WHEN ? = 'queued' THEN error ELSE ? END,
                           credential_holder = CASE WHEN ? = 'needs_credentials'
                                                    THEN NULL ELSE credential_holder END,
                           finished_at = CASE WHEN ? = 'failed' THEN ? ELSE finished_at END
                       WHERE id = ?""",
                    (status.value, now, now, status.value, msg, status.value, status.value, now,
                     job.id),
                )
                self._event(conn, job.id, job.current_stage or "queue", msg)
                reclaimed.append(job.id)

            stale = now - self.worker_ttl_seconds
            orphans = conn.execute(
                """SELECT id FROM jobs WHERE status = ? AND requires_credentials = 1
                       AND credential_holder IS NOT NULL
                       AND credential_holder NOT IN (
                           SELECT owner FROM workers WHERE heartbeat_at >= ?)
                       AND created_at < ?""",
                (JobStatus.QUEUED.value, stale, stale),
            ).fetchall()
            for row in orphans:
                conn.execute(
                    """UPDATE jobs SET status = ?, credential_holder = NULL, updated_at = ?,
                           error = ? WHERE id = ?""",
                    (JobStatus.NEEDS_CREDENTIALS.value, now,
                     "the worker holding the API key is gone; re-supply it to continue",
                     row["id"]),
                )
                self._event(conn, row["id"], "queue",
                            "credential holder gone; waiting for the API key")
                reclaimed.append(row["id"])
        return reclaimed

    def expire_paused(self, *, ttl_seconds: float, now: float | None = None) -> list[str]:
        """Cancel paused jobs nobody resumed within ``ttl_seconds`` (R18, KTD13).

        A ``needs_credentials`` / ``budget_exhausted`` job counts as active, so an exclusive
        enqueue for its corpus is refused for as long as it exists. If the control token was lost
        nothing can ever resume or cancel it, and the corpus would be blocked forever. This sweep
        moves such a job to ``cancelled`` (error ``expired: ...``), drops its credential holder
        and stamps ``finished_at``, so a new job can be enqueued.

        ``updated_at`` is the entry time: every path into a paused state (``pause``,
        ``reclaim_expired``, ``enqueue(status=NEEDS_CREDENTIALS)``, ``resume`` that lands back in
        ``needs_credentials``) writes it, and nothing touches a paused job afterwards except an
        operator action (``update_payload``), which fairly restarts the clock.

        Only paused jobs are considered; queued and running jobs are never expired here. One
        ``BEGIN IMMEDIATE`` transaction re-selects under the write lock, so two workers sweeping
        at once expire each job exactly once (the loser sees no row and returns ``[]``).
        A non-positive or non-finite ``ttl_seconds`` disables the sweep. Returns the expired ids.
        """
        if not isinstance(ttl_seconds, (int, float)) or not math.isfinite(ttl_seconds) \
                or ttl_seconds <= 0:
            return []
        stamp = self.now() if now is None else float(now)
        cutoff = stamp - float(ttl_seconds)
        paused = tuple(s.value for s in PAUSED)
        expired: list[str] = []
        with self._write() as conn:
            rows = conn.execute(
                f"SELECT * FROM jobs WHERE status IN ({', '.join('?' for _ in paused)})"
                " AND updated_at < ? ORDER BY updated_at",
                (*paused, cutoff),
            ).fetchall()
            for row in rows:
                job = self._row_to_job(row)
                reason = (f"expired: paused ({job.status.value}) for more than "
                          f"{ttl_seconds:g}s without being resumed")
                conn.execute(
                    """UPDATE jobs SET status = ?, cancel_requested = 1, error = ?,
                           credential_holder = NULL, lease_owner = NULL, lease_token = NULL,
                           lease_expires_at = NULL, updated_at = ?, finished_at = ?
                       WHERE id = ?""",
                    (JobStatus.CANCELLED.value, reason, stamp, stamp, job.id),
                )
                self._event(conn, job.id, job.current_stage or "queue", reason)
                expired.append(job.id)
        return expired

    def worker_heartbeat(self, owner: str) -> None:
        with self._write() as conn:
            conn.execute(
                """INSERT INTO workers (owner, pid, host, heartbeat_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(owner) DO UPDATE SET heartbeat_at = excluded.heartbeat_at""",
                (owner, os.getpid(), socket.gethostname(), self.now()),
            )

    # ---- reads ---------------------------------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._connect() as conn:
            return self._get(conn, job_id)

    def latest_for(self, kind: str, corpus_id: str) -> Job | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE kind = ? AND corpus_id = ?"
                " ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (kind, corpus_id),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, *, status: JobStatus | None = None, limit: int = 100) -> list[Job]:
        sql, params = "SELECT * FROM jobs", []
        if status is not None:
            sql += " WHERE status = ?"
            params.append(status.value)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return [self._row_to_job(r) for r in conn.execute(sql, params).fetchall()]

    def events(self, job_id: str, after_seq: int = 0) -> list[JobEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM job_events WHERE job_id = ? AND seq > ? ORDER BY seq",
                (job_id, after_seq),
            ).fetchall()
        return [JobEvent(r["job_id"], r["seq"], r["ts"], r["stage"], r["message"]) for r in rows]

    def add_event(self, job_id: str, stage: str, message: str) -> None:
        with self._write() as conn:
            self._event(conn, job_id, stage, message)

    # ---- legacy import -------------------------------------------------------------------------

    def import_snapshot(
        self,
        *,
        job_id: str,
        kind: str,
        corpus_id: str,
        status: JobStatus,
        created_at: float,
        updated_at: float,
        current_stage: str | None = None,
        progress_pct: int = 0,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        events: Sequence[tuple[float, str, str]] = (),
        idempotency_key: str | None = None,
    ) -> Job:
        """Upsert a display-only job record (the one-time JSON-file import, and test seeding).

        An imported record has no payload, so a worker that leased one could not run it; the
        importer therefore never imports a runnable state. It only ever upserts records it
        imported: a live job with the same id is left untouched (``QueueError``).
        """
        with self._write() as conn:
            existing_job = self._get(conn, job_id)
            if existing_job is not None and existing_job.payload != {"imported": True}:
                raise QueueError(f"job {job_id!r} is a live job; an import never overwrites it")
            conn.execute(
                """INSERT INTO jobs (id, kind, corpus_id, status, payload, idempotency_key,
                       current_stage, progress_pct, result, error, available_at, created_at,
                       updated_at, finished_at)
                   VALUES (?, ?, ?, ?, '{"imported": true}', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET status = excluded.status,
                       current_stage = excluded.current_stage,
                       progress_pct = excluded.progress_pct, result = excluded.result,
                       error = excluded.error, updated_at = excluded.updated_at,
                       finished_at = excluded.finished_at
                   WHERE jobs.payload = '{"imported": true}'""",
                (job_id, kind, corpus_id, status.value, idempotency_key, current_stage,
                 progress_pct, json.dumps(result) if result is not None else None, error,
                 created_at, created_at, updated_at,
                 updated_at if status in TERMINAL else None),
            )
            existing = conn.execute(
                "SELECT COUNT(*) FROM job_events WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
            for ts, stage, message in list(events)[existing:]:
                seq = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM job_events WHERE job_id = ?", (job_id,)
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO job_events (job_id, seq, ts, stage, message) VALUES (?, ?, ?, ?, ?)",
                    (job_id, seq, ts, stage, message),
                )
            out = self._get(conn, job_id)
        assert out is not None
        return out

    def verify_control(self, job_id: str, token: str | None) -> bool:
        """Constant-time check of a job's control token. A job without one is never controllable."""
        if not token:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT control_token_sha256 FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        stored = row["control_token_sha256"] if row else None
        if not stored:
            hmac.compare_digest(_token_hash(token), _token_hash(""))  # even out the timing
            return False
        return hmac.compare_digest(stored, _token_hash(token))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class QueueStats:
    """Counts by status (for ``folio-insights jobs list`` and health output)."""

    counts: dict[str, int] = field(default_factory=dict)


def queue_stats(queue: SQLiteJobQueue) -> QueueStats:
    with queue.connect() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
    return QueueStats(counts={r["status"]: r["n"] for r in rows})
