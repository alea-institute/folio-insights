"""One-time import of the pre-queue JSON job files (Phase 10 U2).

Before the durable queue, the API kept one ``ProcessingJob`` JSON file per corpus in
``<output>/.jobs/`` (``<corpus>.json`` for extraction, ``<corpus>_discovery.json`` for
discovery). :func:`import_legacy_jobs` copies them into the queue as display-only records so job
history survives the cutover. It is explicit (CLI ``folio-insights jobs import-legacy``), never
automatic, and idempotent (each file's job id is its idempotency key).

A legacy job that was ``pending`` or ``processing`` had been orphaned by the very restart the
queue now survives; it has no payload to resume from, so it imports as ``failed`` with that
reason.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from folio_insights.jobs.queue import JobStatus, QueueError, SQLiteJobQueue

_STATUS = {
    "pending": JobStatus.FAILED,
    "processing": JobStatus.FAILED,
    "completed": JobStatus.SUCCEEDED,
    "failed": JobStatus.FAILED,
    "cancelled": JobStatus.CANCELLED,
}
ORPHANED = "orphaned: the process running this job stopped before the durable queue existed"


def _ts(iso: str | None) -> float:
    """A legacy timestamp, or 0.0 (the epoch) when it is missing or malformed."""
    try:
        return datetime.fromisoformat(iso).timestamp() if iso else 0.0
    except (TypeError, ValueError):
        return 0.0


def import_legacy_jobs(jobs_dir: Path, queue: SQLiteJobQueue) -> list[dict[str, str]]:
    """Import every ``*.json`` job file in ``jobs_dir``. Returns one outcome row per file."""
    out: list[dict[str, str]] = []
    for path in sorted(Path(jobs_dir).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            job_id = str(data["id"]).replace("-", "")
            corpus_key = str(data["corpus_id"])
            legacy_status = str(data.get("status", "failed"))
        except (OSError, ValueError, KeyError) as exc:
            out.append({"file": path.name, "outcome": f"skipped ({type(exc).__name__})"})
            continue
        if corpus_key.endswith("_discovery"):
            kind, corpus = "discover", corpus_key[: -len("_discovery")]
        else:
            kind, corpus = "extract", corpus_key
        status = _STATUS.get(legacy_status, JobStatus.FAILED)
        error = data.get("error")
        if legacy_status in ("pending", "processing"):
            error = ORPHANED
        try:
            queue.import_snapshot(
                job_id=job_id,
                kind=kind,
                corpus_id=corpus,
                status=status,
                created_at=_ts(data.get("created_at")),
                updated_at=_ts(data.get("updated_at")),
                current_stage=data.get("current_stage"),
                progress_pct=int(data.get("progress_pct") or 0),
                result={"total_units": int(data.get("total_units") or 0)},
                error=error,
                events=[
                    (_ts(a.get("timestamp")), str(a.get("stage", "")), str(a.get("message", "")))
                    for a in data.get("activity_log") or []
                ],
                idempotency_key=f"legacy:{job_id}",
            )
        except QueueError as exc:
            out.append({"file": path.name, "outcome": f"skipped ({exc})"})
            continue
        out.append({"file": path.name, "outcome": f"imported as {kind}/{status.value}"})
    return out
