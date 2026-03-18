"""Disk-based ProcessingJob persistence with atomic writes.

Stores each job as a JSON file keyed by corpus_id. Uses temp-file +
os.replace() to prevent SSE pollers from reading partial JSON.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from api.models.processing import ProcessingJob

logger = logging.getLogger(__name__)


class JobManager:
    """Persist ProcessingJob instances as JSON files on disk.

    Each corpus gets a single job file at ``{jobs_dir}/{corpus_id}.json``.
    Writes are atomic (temp file + rename) so concurrent readers never
    see partial data.
    """

    def __init__(self, jobs_dir: Path) -> None:
        self.jobs_dir = Path(jobs_dir)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def _job_path(self, corpus_id: str) -> Path:
        return self.jobs_dir / f"{corpus_id}.json"

    async def save(self, job: ProcessingJob) -> None:
        """Atomically persist *job* to disk.

        Writes to a temporary file first, then uses ``os.replace()``
        to swap it into place. This guarantees that readers (e.g. the
        SSE poller) always see complete, valid JSON.
        """
        from datetime import datetime, timezone

        job.updated_at = datetime.now(timezone.utc).isoformat()
        path = self._job_path(job.corpus_id)
        data = json.dumps(job.model_dump(), default=str, indent=2)

        def _write() -> None:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.jobs_dir), suffix=".tmp"
            )
            try:
                with open(fd, "w") as f:
                    f.write(data)
                os.replace(tmp_path, str(path))
            except BaseException:
                Path(tmp_path).unlink(missing_ok=True)
                raise

        await asyncio.to_thread(_write)
        logger.debug("Saved job for corpus %s", job.corpus_id)

    async def load_by_corpus(self, corpus_id: str) -> ProcessingJob | None:
        """Load the ProcessingJob for *corpus_id*, or ``None`` if absent."""
        path = self._job_path(corpus_id)
        if not path.exists():
            return None

        def _read() -> str:
            return path.read_text(encoding="utf-8")

        text = await asyncio.to_thread(_read)
        return ProcessingJob.model_validate_json(text)

    async def delete(self, corpus_id: str) -> None:
        """Remove the job file for *corpus_id* if it exists."""
        path = self._job_path(corpus_id)
        if path.exists():
            path.unlink()
            logger.debug("Deleted job for corpus %s", corpus_id)
