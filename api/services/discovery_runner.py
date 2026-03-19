"""Discovery pipeline execution wrapper with progress callbacks.

Iterates through TaskDiscoveryOrchestrator stages individually, updating
the ProcessingJob between each stage so the SSE stream can report
real-time progress to the browser.

Follows the same pattern as pipeline_runner.py for extraction.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from api.models.processing import ActivityEntry, ProcessingJob, ProcessingStatus
from api.services.job_manager import JobManager

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_discovery_with_progress(
    corpus_id: str,
    corpus_name: str,
    job_manager: JobManager,
) -> None:
    """Run the 6-stage task discovery pipeline with per-stage progress updates.

    Same pattern as run_pipeline_with_progress: iterates orchestrator._stages
    individually, updating the job between each stage for SSE polling.

    After completion, persists discovered tasks to SQLite (insert into
    task_decisions, task_unit_links, contradictions tables).
    """
    job = await job_manager.load_by_corpus(f"{corpus_id}_discovery")
    if job is None:
        logger.error("No discovery job found for corpus %s; aborting", corpus_id)
        return

    from folio_insights.config import get_settings
    from folio_insights.models.knowledge_unit import KnowledgeUnit
    from folio_insights.models.task import DiscoveryJob as PipelineDiscoveryJob
    from folio_insights.pipeline.discovery.orchestrator import TaskDiscoveryOrchestrator

    settings = get_settings()
    corpus_dir = settings.output_dir / corpus_name
    extraction_path = corpus_dir / "extraction.json"

    try:
        job.status = ProcessingStatus.PROCESSING
        await job_manager.save(job)

        # Check extraction output exists
        if not extraction_path.exists():
            raise FileNotFoundError(
                f"No extraction output at {extraction_path}. "
                "Run extraction pipeline first."
            )

        # Load extraction data for unit count
        data = json.loads(extraction_path.read_text(encoding="utf-8"))
        units = data.get("units", [])

        # Check for SQLite DB for decision persistence
        db_path = corpus_dir / "review.db"
        orchestrator = TaskDiscoveryOrchestrator(
            settings,
            db_path=db_path if db_path.exists() else None,
        )
        stages = orchestrator._stages
        total_stages = len(stages)

        # Create the DiscoveryJob that flows through the pipeline stages
        ku_list = [KnowledgeUnit(**u) for u in units]

        # Load approved decisions
        approved_tasks = await orchestrator._load_approved_decisions(corpus_name)
        pre_run_task_ids = {t.id for t in approved_tasks}

        pipeline_job = PipelineDiscoveryJob(
            corpus_name=corpus_name,
            source_dir=corpus_dir / "sources",
            knowledge_units=ku_list,
            discovered_tasks=list(approved_tasks),
            metadata={
                "locked_task_ids": list(pre_run_task_ids),
            },
        )

        for i, stage in enumerate(stages):
            display = _DISCOVERY_STAGE_DISPLAY.get(stage.name, stage.name)

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
            pipeline_job = await stage.execute(pipeline_job)

            # Post-stage update
            task_count = len(pipeline_job.task_candidates)
            discovered_count = len(pipeline_job.discovered_tasks)
            if stage.name == "hierarchy_construction":
                detail = f"{discovered_count} tasks discovered"
            elif stage.name == "contradiction_detection":
                detail = f"{len(pipeline_job.contradictions)} contradictions found"
            else:
                detail = f"{task_count} candidates"

            job.activity_log.append(
                ActivityEntry(
                    timestamp=_now_iso(),
                    stage=stage.name,
                    message=f"Completed {display} ({detail})",
                )
            )
            await job_manager.save(job)

        # Write output files (discovery.json, task_tree.json, discovery_diff.json)
        pre_run_tasks = {t.id: t for t in approved_tasks}
        diff = orchestrator._compute_diff(pipeline_job, pre_run_tasks)
        orchestrator._write_output(pipeline_job, corpus_dir, diff)

        # Persist discovered tasks to SQLite
        await _persist_discovery_to_sqlite(
            corpus_dir / "review.db",
            corpus_name,
            pipeline_job,
        )

        # Count final tasks
        final_task_count = len(
            pipeline_job.task_hierarchy.tasks
            if pipeline_job.task_hierarchy
            else []
        )

        # Mark complete
        job.status = ProcessingStatus.COMPLETED
        job.progress_pct = 100
        job.total_units = final_task_count
        job.activity_log.append(
            ActivityEntry(
                timestamp=_now_iso(),
                stage="discovery",
                message=f"Discovery complete: {final_task_count} tasks discovered",
            )
        )
        await job_manager.save(job)

        logger.info(
            "Discovery complete for corpus %s: %d tasks",
            corpus_id,
            final_task_count,
        )

    except Exception as exc:
        logger.exception("Discovery failed for corpus %s", corpus_id)
        job.status = ProcessingStatus.FAILED
        job.error = str(exc)
        job.activity_log.append(
            ActivityEntry(
                timestamp=_now_iso(),
                stage=job.current_stage or "unknown",
                message=f"Discovery failed: {exc}",
            )
        )
        await job_manager.save(job)


async def _persist_discovery_to_sqlite(
    db_path: Path,
    corpus_name: str,
    pipeline_job,
) -> None:
    """Persist discovered tasks, unit links, and contradictions to SQLite.

    Creates the review.db if it doesn't exist. Inserts new rows or
    updates existing ones (via INSERT OR IGNORE / ON CONFLICT).
    """
    import aiosqlite

    from api.db.models import SCHEMA_SQL

    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(SCHEMA_SQL)

        if pipeline_job.task_hierarchy:
            # Insert task_decisions
            for task in pipeline_job.task_hierarchy.tasks:
                await db.execute(
                    """
                    INSERT INTO task_decisions
                        (task_id, corpus_name, folio_iri, label, parent_task_id,
                         is_procedural, canonical_order, is_manual)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        folio_iri = excluded.folio_iri,
                        label = excluded.label,
                        parent_task_id = excluded.parent_task_id,
                        is_procedural = excluded.is_procedural,
                        canonical_order = excluded.canonical_order,
                        updated_at = datetime('now')
                    """,
                    (
                        task.id,
                        corpus_name,
                        task.folio_iri,
                        task.label,
                        task.parent_task_id,
                        int(task.is_procedural),
                        task.canonical_order,
                        int(task.is_manual),
                    ),
                )

            # Insert task_unit_links
            for task_id, unit_ids in pipeline_job.task_hierarchy.task_unit_links.items():
                for uid in unit_ids:
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO task_unit_links
                            (task_id, unit_id, corpus_name)
                        VALUES (?, ?, ?)
                        """,
                        (task_id, uid, corpus_name),
                    )

        # Insert contradictions
        for c in pipeline_job.contradictions:
            await db.execute(
                """
                INSERT INTO contradictions
                    (task_id, unit_id_a, unit_id_b, corpus_name, nli_score,
                     contradiction_type)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(unit_id_a, unit_id_b, task_id) DO UPDATE SET
                    nli_score = excluded.nli_score,
                    contradiction_type = excluded.contradiction_type
                """,
                (
                    c.task_id,
                    c.unit_id_a,
                    c.unit_id_b,
                    corpus_name,
                    c.nli_score,
                    c.contradiction_type,
                ),
            )

        await db.commit()

    logger.info(
        "Persisted discovery results to SQLite for corpus '%s'",
        corpus_name,
    )
