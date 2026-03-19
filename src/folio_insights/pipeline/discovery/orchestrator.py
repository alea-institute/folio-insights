"""Task discovery pipeline orchestrator: chains all 6 stages with checkpointing.

Reads Phase 1 extraction output and discovers advocacy tasks organized
in a hierarchical tree. Supports checkpoint-based resume for interrupted
runs. Loads previously approved task decisions from SQLite so reviewer
edits survive re-runs. Computes a diff between new results and existing
approved decisions for the frontend DiffView.

Stages (in order):
  1. HeadingAnalysisStage
  2. FolioMappingStage
  3. ContentClusteringStage
  4. HierarchyConstructionStage
  5. CrossSourceMergingStage
  6. ContradictionDetectionStage
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from folio_insights.config import Settings
from folio_insights.models.knowledge_unit import KnowledgeUnit
from folio_insights.models.task import (
    DiscoveredTask,
    DiscoveryJob,
    TaskHierarchy,
)
from folio_insights.pipeline.discovery.stages.base import DiscoveryStage

logger = logging.getLogger(__name__)


class DiscoveryCheckpoint:
    """Checkpoint management for task discovery pipeline stages.

    Same pattern as PipelineCheckpoint but typed for DiscoveryJob.
    Uses Pydantic model_dump/model_validate for serialization.
    """

    @staticmethod
    def save(stage_name: str, job: DiscoveryJob, output_dir: Path) -> Path:
        """Serialize discovery checkpoint to disk."""
        checkpoint_dir = Path(output_dir) / "discovery_checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_dir / f"{stage_name}.json"

        data = {
            "stage": stage_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_count": len(job.task_candidates),
            "job": job.model_dump(),
        }

        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(
            "Saved discovery checkpoint: %s (%d candidates)",
            stage_name,
            len(job.task_candidates),
        )
        return checkpoint_path

    @staticmethod
    def load(stage_name: str, output_dir: Path) -> DiscoveryJob | None:
        """Load a discovery checkpoint if it exists."""
        checkpoint_path = (
            Path(output_dir) / "discovery_checkpoints" / f"{stage_name}.json"
        )
        if not checkpoint_path.exists():
            return None

        try:
            with open(checkpoint_path, encoding="utf-8") as f:
                data = json.load(f)
            return DiscoveryJob(**data["job"])
        except Exception:
            logger.warning(
                "Failed to load discovery checkpoint %s; will re-run stage",
                checkpoint_path,
                exc_info=True,
            )
            return None

    @staticmethod
    def has_checkpoint(stage_name: str, output_dir: Path) -> bool:
        """Check whether a discovery checkpoint file exists for a stage."""
        checkpoint_path = (
            Path(output_dir) / "discovery_checkpoints" / f"{stage_name}.json"
        )
        return checkpoint_path.exists()

    @staticmethod
    def invalidate(stage_name: str, output_dir: Path) -> None:
        """Delete a discovery checkpoint file if it exists."""
        checkpoint_path = (
            Path(output_dir) / "discovery_checkpoints" / f"{stage_name}.json"
        )
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            logger.info("Invalidated discovery checkpoint: %s", stage_name)


class TaskDiscoveryOrchestrator:
    """Orchestrate the 6-stage task discovery pipeline.

    Reads Phase 1 extraction output and discovers advocacy tasks
    organized in a hierarchical tree. Supports checkpoint-based
    resume for interrupted runs. Loads previously approved task
    decisions from SQLite so reviewer edits survive re-runs.
    """

    def __init__(
        self,
        settings: Settings,
        db_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self._db_path = db_path  # Path to SQLite DB; None = no decision persistence
        self._stages: list[DiscoveryStage] = self._build_stages()

    def _build_stages(self) -> list[DiscoveryStage]:
        """Instantiate all 6 discovery stages in execution order."""
        from folio_insights.pipeline.discovery.stages.heading_analysis import (
            HeadingAnalysisStage,
        )
        from folio_insights.pipeline.discovery.stages.folio_mapping import (
            FolioMappingStage,
        )
        from folio_insights.pipeline.discovery.stages.content_clustering import (
            ContentClusteringStage,
        )
        from folio_insights.pipeline.discovery.stages.hierarchy_construction import (
            HierarchyConstructionStage,
        )
        from folio_insights.pipeline.discovery.stages.cross_source_merging import (
            CrossSourceMergingStage,
        )
        from folio_insights.pipeline.discovery.stages.contradiction_detection import (
            ContradictionDetectionStage,
        )

        return [
            HeadingAnalysisStage(),
            FolioMappingStage(),
            ContentClusteringStage(),
            HierarchyConstructionStage(),
            CrossSourceMergingStage(),
            ContradictionDetectionStage(),
        ]

    async def _load_approved_decisions(
        self, corpus_name: str
    ) -> list[DiscoveredTask]:
        """Load previously approved task_decisions from SQLite.

        Returns a list of DiscoveredTask objects reconstructed from the
        task_decisions table where status='approved' or status='edited'.
        These are injected into the DiscoveryJob so that subsequent
        pipeline stages treat them as locked (not overwritten).

        If db_path is None or the table doesn't exist yet (first run),
        returns an empty list.
        """
        if self._db_path is None or not self._db_path.exists():
            return []

        import aiosqlite

        approved: list[DiscoveredTask] = []
        try:
            async with aiosqlite.connect(str(self._db_path)) as db:
                db.row_factory = aiosqlite.Row
                try:
                    async with db.execute(
                        "SELECT * FROM task_decisions "
                        "WHERE corpus_name = ? AND status IN ('approved', 'edited')",
                        (corpus_name,),
                    ) as cursor:
                        async for row in cursor:
                            task = DiscoveredTask(
                                id=row["task_id"],
                                label=(
                                    row["edited_label"]
                                    if row["edited_label"]
                                    else row["label"]
                                ),
                                folio_iri=row["folio_iri"],
                                parent_task_id=row["parent_task_id"],
                                is_procedural=bool(row["is_procedural"]),
                                canonical_order=row["canonical_order"],
                                is_manual=bool(row["is_manual"]),
                                review_status=row["status"],
                            )
                            approved.append(task)
                except Exception:
                    # Table may not exist on first run -- return empty
                    logger.debug(
                        "task_decisions table not found; first run",
                        exc_info=True,
                    )
        except Exception:
            logger.warning(
                "Failed to connect to SQLite for approved decisions",
                exc_info=True,
            )

        if approved:
            logger.info(
                "Loaded %d approved task decisions for corpus '%s'",
                len(approved),
                corpus_name,
            )
        return approved

    async def run(
        self,
        corpus_name: str,
        resume: bool = True,
    ) -> DiscoveryJob:
        """Load Phase 1 extraction output and run all 6 discovery stages.

        Before running stages, loads approved task_decisions from SQLite
        (if any exist) and injects them into the DiscoveryJob. Stages
        must treat these as locked -- they are not re-discovered or overwritten.

        After all stages complete, computes a diff between new discovery results
        and the previously approved state for the frontend DiffView.

        Args:
            corpus_name: Name of the corpus to discover tasks in.
            resume: Whether to resume from checkpoints if available.

        Returns:
            The completed DiscoveryJob with task hierarchy and contradictions.
        """
        corpus_dir = self.settings.output_dir / corpus_name
        extraction_path = corpus_dir / "extraction.json"

        # 1. Load Phase 1 extraction output
        if not extraction_path.exists():
            raise FileNotFoundError(
                f"No extraction output found at {extraction_path}. "
                "Run 'folio-insights extract' first."
            )

        data = json.loads(extraction_path.read_text(encoding="utf-8"))
        units = [KnowledgeUnit(**u) for u in data.get("units", [])]

        # 2. DECISION PERSISTENCE: Load approved decisions from SQLite
        approved_tasks = await self._load_approved_decisions(corpus_name)
        pre_run_task_ids = {t.id for t in approved_tasks}
        pre_run_tasks = {t.id: t for t in approved_tasks}

        # 3. Create DiscoveryJob, injecting approved tasks as locked
        job = DiscoveryJob(
            corpus_name=corpus_name,
            source_dir=corpus_dir / "sources",
            knowledge_units=units,
            discovered_tasks=list(approved_tasks),  # Pre-populate
            metadata={
                "locked_task_ids": list(pre_run_task_ids),
            },
        )

        logger.info(
            "Starting discovery for corpus '%s': %d units, %d locked tasks",
            corpus_name,
            len(units),
            len(approved_tasks),
        )
        pipeline_start = time.monotonic()

        # 4. Iterate stages with checkpoint-based resume
        for stage in self._stages:
            stage_name = stage.name

            # Check for existing checkpoint
            if resume and DiscoveryCheckpoint.has_checkpoint(
                stage_name, corpus_dir
            ):
                restored = DiscoveryCheckpoint.load(stage_name, corpus_dir)
                if restored is not None:
                    job = restored
                    logger.info(
                        "Resumed discovery from checkpoint: %s", stage_name
                    )
                    continue

            # Execute stage
            stage_start = time.monotonic()
            try:
                job = await stage.execute(job)
            except Exception:
                logger.exception("Discovery stage '%s' failed", stage_name)
                raise

            stage_duration = time.monotonic() - stage_start
            logger.info(
                "Discovery stage '%s' completed in %.1fs",
                stage_name,
                stage_duration,
            )

            # Save checkpoint
            DiscoveryCheckpoint.save(stage_name, job, corpus_dir)

        # 5. DIFF COMPUTATION: Compare new results against approved state
        diff = self._compute_diff(job, pre_run_tasks)

        # 6. Write output files
        pipeline_duration = time.monotonic() - pipeline_start
        self._write_output(job, corpus_dir, diff)

        task_count = len(
            job.task_hierarchy.tasks if job.task_hierarchy else []
        )
        contradiction_count = len(job.contradictions)
        orphan_count = len(job.orphan_unit_ids)

        logger.info(
            "Discovery complete for '%s': %d tasks, %d contradictions, "
            "%d orphans, %d diff entries (%.1fs)",
            corpus_name,
            task_count,
            contradiction_count,
            orphan_count,
            len(diff),
            pipeline_duration,
        )

        return job

    def _compute_diff(
        self,
        job: DiscoveryJob,
        pre_run_tasks: dict[str, DiscoveredTask],
    ) -> list[dict]:
        """Compare new discovery results against previously approved state.

        Returns a list of diff entries for the frontend DiffView component:
        [
            {"type": "added", "id": "...", "description": "New task: ..."},
            {"type": "removed", "id": "...", "description": "Task removed: ..."},
            {"type": "changed", "id": "...", "description": "Label changed: ..."},
        ]

        Comparison logic:
        - For each task in current results:
          - If task.id not in pre_run_tasks: type="added"
          - If task.id in pre_run_tasks but fields changed: type="changed"
        - For each task_id in pre_run_tasks:
          - If task_id not in current results: type="removed"
        - Unit link changes: compare task_unit_links counts per task
        """
        current_tasks = {
            t.id: t
            for t in (job.task_hierarchy.tasks if job.task_hierarchy else [])
        }
        diff: list[dict] = []

        # Added tasks
        for tid, task in current_tasks.items():
            if tid not in pre_run_tasks:
                diff.append({
                    "type": "added",
                    "id": tid,
                    "description": f"New task: {task.label}",
                })

        # Removed tasks
        for tid, old_task in pre_run_tasks.items():
            if tid not in current_tasks:
                diff.append({
                    "type": "removed",
                    "id": tid,
                    "description": f"Task removed: {old_task.label}",
                })

        # Changed tasks
        for tid in current_tasks.keys() & pre_run_tasks.keys():
            new_t = current_tasks[tid]
            old_t = pre_run_tasks[tid]
            if new_t.label != old_t.label:
                diff.append({
                    "type": "changed",
                    "id": tid,
                    "description": (
                        f"Label changed: '{old_t.label}' -> '{new_t.label}'"
                    ),
                })
            if new_t.parent_task_id != old_t.parent_task_id:
                diff.append({
                    "type": "changed",
                    "id": tid,
                    "description": f"Parent changed for: {new_t.label}",
                })
            if new_t.folio_iri != old_t.folio_iri:
                diff.append({
                    "type": "changed",
                    "id": tid,
                    "description": (
                        f"FOLIO mapping changed for: {new_t.label}"
                    ),
                })

        # Unit link changes
        if job.task_hierarchy:
            for tid in current_tasks.keys() & pre_run_tasks.keys():
                new_unit_count = len(
                    job.task_hierarchy.task_unit_links.get(tid, [])
                )
                # Old tasks don't track unit counts, so only flag if > 0
                if new_unit_count > 0 and tid in pre_run_tasks:
                    old_t = pre_run_tasks[tid]
                    # If the old task had metadata with unit info, compare
                    old_unit_ids = old_t.metadata.get("knowledge_unit_ids", [])
                    if old_unit_ids:
                        added = new_unit_count - len(old_unit_ids)
                        if added > 0:
                            diff.append({
                                "type": "changed",
                                "id": tid,
                                "description": (
                                    f"{added} units added to: "
                                    f"{current_tasks[tid].label}"
                                ),
                            })
                        elif added < 0:
                            diff.append({
                                "type": "changed",
                                "id": tid,
                                "description": (
                                    f"{-added} units removed from: "
                                    f"{current_tasks[tid].label}"
                                ),
                            })

        return diff

    def _write_output(
        self,
        job: DiscoveryJob,
        corpus_dir: Path,
        diff: list[dict],
    ) -> None:
        """Write discovery output files.

        Files produced:
          - discovery.json: Full DiscoveryJob dump
          - task_tree.json: Simplified tree for the viewer
          - discovery_diff.json: Diff entries for DiffView
        """
        corpus_dir.mkdir(parents=True, exist_ok=True)

        # 1. discovery.json -- full dump
        discovery_path = corpus_dir / "discovery.json"
        discovery_data = job.model_dump()
        with open(discovery_path, "w", encoding="utf-8") as f:
            json.dump(discovery_data, f, indent=2, default=str)
        logger.info("Wrote discovery output: %s", discovery_path)

        # 2. task_tree.json -- simplified tree for viewer
        task_tree_path = corpus_dir / "task_tree.json"
        tree_nodes = self._build_tree_json(job)
        with open(task_tree_path, "w", encoding="utf-8") as f:
            json.dump(tree_nodes, f, indent=2)
        logger.info("Wrote task tree: %s", task_tree_path)

        # 3. discovery_diff.json -- diff for DiffView
        diff_path = corpus_dir / "discovery_diff.json"
        with open(diff_path, "w", encoding="utf-8") as f:
            json.dump(diff, f, indent=2)
        logger.info("Wrote discovery diff: %s", diff_path)

    @staticmethod
    def _build_tree_json(job: DiscoveryJob) -> list[dict]:
        """Build a simplified tree structure for the viewer.

        Each node has: id, parent_id, label, folio_iri, unit_count,
        review_status, has_contradictions, has_orphans, is_procedural,
        canonical_order, depth, is_jurisdiction_sensitive.
        """
        if job.task_hierarchy is None:
            return []

        nodes: list[dict] = []
        for task in job.task_hierarchy.tasks:
            unit_count = len(
                job.task_hierarchy.task_unit_links.get(task.id, [])
            )
            nodes.append({
                "id": task.id,
                "parent_id": task.parent_task_id,
                "label": task.label,
                "folio_iri": task.folio_iri,
                "folio_label": task.folio_label,
                "unit_count": unit_count,
                "review_status": task.review_status,
                "has_contradictions": task.has_contradictions,
                "has_orphans": task.has_orphans,
                "is_procedural": task.is_procedural,
                "is_jurisdiction_sensitive": task.is_jurisdiction_sensitive,
                "canonical_order": task.canonical_order,
                "depth": task.depth,
                "confidence": task.confidence,
            })

        return nodes
