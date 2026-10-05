"""In-memory credential handles for queued jobs (KTD3).

The API takes a user's key per request and hands the job a handle that lives only here, in the
memory of the process whose worker runs the job. It is never serialized: not to the queue
table, not to logs, not to checkpoints. If that process restarts, the handle is gone and the
job pauses as ``needs_credentials`` until the user supplies the key again; the server never
falls back to an ambient key.
"""

from __future__ import annotations

import threading
from typing import Any

from folio_insights.llm.credentials import Credentials


class SecretStore:
    """Process-local ``job_id -> Credentials`` map. Unpicklable; redacted repr."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_job: dict[str, Credentials] = {}

    def put(self, job_id: str, credentials: Credentials) -> None:
        if not isinstance(credentials, Credentials):
            raise TypeError("SecretStore holds Credentials handles only")
        with self._lock:
            self._by_job[job_id] = credentials

    def get(self, job_id: str) -> Credentials | None:
        with self._lock:
            return self._by_job.get(job_id)

    def swap(self, job_id: str, credentials: Credentials) -> Credentials | None:
        """Install ``credentials`` for the job; return the handle it replaced (or None)."""
        if not isinstance(credentials, Credentials):
            raise TypeError("SecretStore holds Credentials handles only")
        with self._lock:
            previous = self._by_job.get(job_id)
            self._by_job[job_id] = credentials
            return previous

    def restore_if(self, job_id: str, expected: Credentials, previous: Credentials | None) -> None:
        """Undo a :meth:`swap` only if the job still holds ``expected`` (our own handle)."""
        with self._lock:
            if self._by_job.get(job_id) is not expected:
                return
            if previous is None:
                self._by_job.pop(job_id, None)
            else:
                self._by_job[job_id] = previous

    def discard_if(self, job_id: str, expected: Credentials) -> None:
        """Drop the job's handle only if it is ``expected`` (never someone else's)."""
        with self._lock:
            if self._by_job.get(job_id) is expected:
                self._by_job.pop(job_id, None)

    def discard(self, job_id: str) -> None:
        with self._lock:
            self._by_job.pop(job_id, None)

    def clear(self) -> None:
        with self._lock:
            self._by_job.clear()

    def __contains__(self, job_id: object) -> bool:
        with self._lock:
            return job_id in self._by_job

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_job)

    def __repr__(self) -> str:
        return f"SecretStore(jobs={len(self)})"

    def __reduce__(self) -> Any:
        raise TypeError("SecretStore cannot be pickled or serialized")


_DEFAULT: SecretStore | None = None
_DEFAULT_LOCK = threading.Lock()


def default_secret_store() -> SecretStore:
    """This process's store (shared by the API routes and the embedded worker)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = SecretStore()
        return _DEFAULT
