"""Extraction job handler for the durable queue (Phase 10 U2).

The API no longer runs the pipeline in an untracked ``asyncio.create_task`` with its own private
stage loop. ``POST /corpus/{id}/process`` enqueues an ``extract`` job; a worker leases it and
calls :func:`run_extraction_job`, which runs ``PipelineOrchestrator.run`` -- the same
checkpoint-and-resume path the CLI uses -- with a job-scoped checkpoint directory, so a worker
that dies mid-stage is replaced by one that resumes from the last completed stage.

Stage progress and activity entries are written to the queue at every stage boundary (the SSE
stream reads them there), and a cancellation request takes effect at the next boundary.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from folio_insights.config import get_settings
from folio_insights.jobs import JobRunContext, PermanentJobError

logger = logging.getLogger(__name__)

# Human-readable display names for pipeline stages
_STAGE_DISPLAY: dict[str, str] = {
    "ingestion": "Ingestion",
    "structure_parser": "Structure Parsing",
    "boundary_detection": "Boundary Detection",
    "distiller": "Distillation",
    "knowledge_classifier": "Knowledge Classification",
    "folio_tagger": "FOLIO Tagging",
    "deduplicator": "Deduplication",
}


def _stage_detail(stage_name: str, job: Any) -> str:
    if stage_name == "ingestion":
        return f"{len(job.documents)} documents ingested"
    if stage_name == "structure_parser":
        structured = job.metadata.get("structured", {})
        elem_count = sum(len(v) for v in structured.values())
        return f"{elem_count} elements across {len(structured)} files"
    return f"{len(job.units)} units"


def stage_reporter(ctx: JobRunContext, display: dict[str, str], detail_fn: Any) -> Any:
    """A ``StageProgress`` callback writing progress + activity to the queue.

    It runs at every stage boundary and raises there when the job was cancelled or this worker
    lost its lease, so the run stops cleanly between stages.
    """

    def _progress(event: str, stage_name: str, index: int, total: int, job: Any) -> None:
        name = display.get(stage_name, stage_name)
        if event == "start":
            ctx.report(stage=stage_name, progress_pct=int(index / total * 100),
                       message=f"Starting {name}...")
        elif event == "done":
            ctx.report(stage=stage_name, progress_pct=int((index + 1) / total * 100),
                       message=f"Completed {name} ({detail_fn(stage_name, job)})")
        elif event == "resumed":
            ctx.report(stage=stage_name, progress_pct=int((index + 1) / total * 100),
                       message=f"Resumed {name} from checkpoint")

    return _progress


def job_checkpoint_dir(corpus_dir: Path, job_id: str, *, discovery: bool = False) -> Path:
    """Checkpoints for one queued job: its retries resume its own run, never another's."""
    base = "discovery_checkpoints" if discovery else "checkpoints"
    return corpus_dir / base / "jobs" / job_id


async def run_extraction_job(ctx: JobRunContext) -> dict[str, Any]:
    """Queue handler for ``extract`` jobs."""
    from folio_insights.pipeline.orchestrator import PipelineOrchestrator

    payload = ctx.payload
    try:
        corpus_name = str(payload["corpus_name"])
        output_dir = Path(payload["output_dir"])
    except KeyError as exc:
        raise PermanentJobError(f"extract job payload lacks {exc}") from None
    source_dir = Path(payload.get("source_dir") or output_dir / corpus_name / "sources")
    corpus_dir = output_dir / corpus_name
    checkpoints = job_checkpoint_dir(corpus_dir, ctx.job.id)

    settings = get_settings().model_copy(update={"output_dir": output_dir, "corpus_name": corpus_name})
    orchestrator = PipelineOrchestrator(settings)
    ctx.report(stage="pipeline", progress_pct=0,
               message="Pipeline started" if ctx.job.attempts <= 1
               else f"Pipeline resumed (attempt {ctx.job.attempts})")

    insights_job = await orchestrator.run(
        source_dir,
        corpus_name=corpus_name,
        resume=True,
        checkpoint_dir=checkpoints,
        progress=stage_reporter(ctx, _STAGE_DISPLAY, _stage_detail),
    )

    # Invalidate cached extraction data so subsequent API reads get fresh data.
    try:
        from api.main import load_extraction

        load_extraction(corpus_name)
    except Exception:  # noqa: BLE001 - the cache refreshes on next startup anyway
        logger.warning("could not refresh the extraction cache for %s", corpus_name, exc_info=True)

    total_units = len(insights_job.units)
    ctx.report(stage="pipeline", progress_pct=100,
               message=f"Pipeline complete: {total_units} units extracted", check=False)
    shutil.rmtree(checkpoints, ignore_errors=True)
    return {"total_units": total_units, "corpus_name": corpus_name}
