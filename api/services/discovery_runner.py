"""Discovery job handler for the durable queue (Phase 10 U2).

``POST /corpus/{id}/discover`` enqueues a ``discover`` job; a worker leases it and calls
:func:`run_discovery_job`, which runs ``TaskDiscoveryOrchestrator.run`` -- the CLI's
checkpointed path, including the diff and the ``review.db`` persistence -- with a job-scoped
checkpoint directory and stage-boundary progress, instead of the API's former private stage loop.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from api.services.pipeline_runner import job_checkpoint_dir, stage_reporter
from folio_insights.config import get_settings
from folio_insights.jobs import JobRunContext, PermanentJobError

logger = logging.getLogger(__name__)

# Human-readable display names for discovery stages
_DISCOVERY_STAGE_DISPLAY: dict[str, str] = {
    "heading_analysis": "Heading Analysis",
    "folio_mapping": "FOLIO Mapping",
    "content_clustering": "Content Clustering",
    "hierarchy_construction": "Hierarchy Construction",
    "cross_source_merging": "Cross-Source Merging",
    "contradiction_detection": "Contradiction Detection",
}


def _discovery_detail(stage_name: str, job: Any) -> str:
    if stage_name == "hierarchy_construction":
        return f"{len(job.discovered_tasks)} tasks discovered"
    if stage_name == "contradiction_detection":
        return f"{len(job.contradictions)} contradictions found"
    return f"{len(job.task_candidates)} candidates"


async def run_discovery_job(ctx: JobRunContext) -> dict[str, Any]:
    """Queue handler for ``discover`` jobs."""
    from folio_insights.pipeline.discovery.orchestrator import TaskDiscoveryOrchestrator

    payload = ctx.payload
    try:
        corpus_name = str(payload["corpus_name"])
        output_dir = Path(payload["output_dir"])
    except KeyError as exc:
        raise PermanentJobError(f"discover job payload lacks {exc}") from None
    corpus_dir = output_dir / corpus_name
    if not (corpus_dir / "extraction.json").exists():
        raise PermanentJobError(
            f"No extraction output for corpus {corpus_name!r}. Run extraction pipeline first."
        )
    checkpoints = job_checkpoint_dir(corpus_dir, ctx.job.id, discovery=True)

    settings = get_settings().model_copy(update={"output_dir": output_dir, "corpus_name": corpus_name})
    orchestrator = TaskDiscoveryOrchestrator(settings, db_path=corpus_dir / "review.db")
    ctx.report(stage="discovery", progress_pct=0, message="Discovery started")

    pipeline_job = await orchestrator.run(
        corpus_name,
        resume=True,
        checkpoint_dir=checkpoints,
        progress=stage_reporter(ctx, _DISCOVERY_STAGE_DISPLAY, _discovery_detail),
    )

    final_task_count = len(
        pipeline_job.task_hierarchy.tasks if pipeline_job.task_hierarchy else []
    )
    ctx.report(stage="discovery", progress_pct=100,
               message=f"Discovery complete: {final_task_count} tasks discovered", check=False)
    shutil.rmtree(checkpoints, ignore_errors=True)
    return {"total_units": final_task_count, "corpus_name": corpus_name}


async def _persist_discovery_to_sqlite(
    db_path: Path,
    corpus_name: str,
    pipeline_job,
) -> None:
    """Persist discovered tasks, unit links and contradictions to ``review.db``.

    Delegates to the library's ``persist_discovery`` so the API and the CLI write
    identical rows.
    """
    from folio_insights.persistence import persist_discovery

    await persist_discovery(db_path, corpus_name, pipeline_job)
