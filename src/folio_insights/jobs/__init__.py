"""Durable jobs (Phase 10 U2): a SQLite lease queue, an in-memory credential store and a worker.

* :mod:`.queue` -- :class:`JobQueue` protocol and its :class:`SQLiteJobQueue` implementation;
* :mod:`.secrets` -- process-local credential handles that never reach the queue;
* :mod:`.worker` -- :class:`JobWorker`, which leases, heartbeats, runs and settles jobs.
"""

from folio_insights.jobs.queue import (
    ACTIVE,
    ActiveJobExists,
    PAUSED,
    TERMINAL,
    Job,
    JobEvent,
    JobQueue,
    JobStatus,
    Lease,
    QueueError,
    SQLiteJobQueue,
    default_queue_path,
    new_owner_id,
)
from folio_insights.jobs.secrets import SecretStore, default_secret_store
from folio_insights.jobs.worker import (
    JobCancelled,
    JobHandler,
    JobRunContext,
    JobWorker,
    LeaseLost,
    PermanentJobError,
)

__all__ = [
    "ACTIVE",
    "ActiveJobExists",
    "PAUSED",
    "TERMINAL",
    "Job",
    "JobCancelled",
    "JobEvent",
    "JobHandler",
    "JobQueue",
    "JobRunContext",
    "JobStatus",
    "JobWorker",
    "Lease",
    "LeaseLost",
    "PermanentJobError",
    "QueueError",
    "SQLiteJobQueue",
    "SecretStore",
    "default_queue_path",
    "default_secret_store",
    "new_owner_id",
]
