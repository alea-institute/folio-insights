"""Pipeline execution wrapper with progress callbacks updating ProcessingJob.

Iterates through PipelineOrchestrator stages individually, updating
the ProcessingJob between each stage so the SSE stream can report
real-time progress to the browser.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from api.models.processing import ActivityEntry, ProcessingStatus
from api.services.job_manager import JobManager
from folio_insights.config import get_settings
from folio_insights.pipeline.orchestrator import PipelineOrchestrator
from folio_insights.pipeline.stages.base import InsightsJob

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_pipeline_with_progress(
    corpus_id: str,
    source_dir: Path,
    corpus_name: str,
    job_manager: JobManager,
) -> None:
    """Run the full extraction pipeline with per-stage progress updates.

    This function is designed to be launched via ``asyncio.create_task()``
    from the processing trigger endpoint. It:

    1. Creates a ``ProcessingJob`` (or loads the existing pending one).
    2. Instantiates a ``PipelineOrchestrator`` and iterates its stages.
    3. After each stage, updates the job with progress and activity entries.
    4. On success, writes output and marks the job COMPLETED.
    5. On failure, captures the exception and marks the job FAILED.
    """
    job = await job_manager.load_by_corpus(corpus_id)
    if job is None:
        logger.error("No job found for corpus %s; aborting pipeline", corpus_id)
        return

    settings = get_settings()
    orchestrator = PipelineOrchestrator(settings)
    stages = orchestrator._stages
    total_stages = len(stages)

    # Create the InsightsJob that flows through the pipeline stages
    insights_job = InsightsJob(corpus_name=corpus_name, source_dir=source_dir)

    try:
        job.status = ProcessingStatus.PROCESSING
        await job_manager.save(job)

        for i, stage in enumerate(stages):
            display = _STAGE_DISPLAY.get(stage.name, stage.name)

            # Pre-stage update
            job.current_stage = stage.name
            job.progress_pct = int((i / total_stages) * 100)
            job.activity_log.append(
                ActivityEntry(
                    timestamp=_now_iso(),
                    stage=stage.name,
                    message=f"Starting {display}...",
                )
            )
            await job_manager.save(job)

            # Execute stage
            insights_job = await stage.execute(insights_job)

            # Post-stage update
            unit_count = len(insights_job.units)
            doc_count = len(insights_job.documents)
            if stage.name == "ingestion":
                detail = f"{doc_count} documents ingested"
            else:
                detail = f"{unit_count} units"

            job.activity_log.append(
                ActivityEntry(
                    timestamp=_now_iso(),
                    stage=stage.name,
                    message=f"Completed {display} ({detail})",
                )
            )
            await job_manager.save(job)

        # Post-pipeline: write output files (confidence gate + output formatter)
        output_dir = settings.output_dir
        corpus_dir = output_dir / corpus_name
        await orchestrator._write_output(insights_job, corpus_name, corpus_dir)

        # Mark complete
        job.status = ProcessingStatus.COMPLETED
        job.progress_pct = 100
        job.total_units = len(insights_job.units)
        job.activity_log.append(
            ActivityEntry(
                timestamp=_now_iso(),
                stage="pipeline",
                message=f"Pipeline complete: {job.total_units} units extracted",
            )
        )
        await job_manager.save(job)

        logger.info(
            "Pipeline complete for corpus %s: %d units",
            corpus_id,
            job.total_units,
        )

    except Exception as exc:
        logger.exception("Pipeline failed for corpus %s", corpus_id)
        job.status = ProcessingStatus.FAILED
        job.error = str(exc)
        job.activity_log.append(
            ActivityEntry(
                timestamp=_now_iso(),
                stage=job.current_stage or "unknown",
                message=f"Pipeline failed: {exc}",
            )
        )
        await job_manager.save(job)
