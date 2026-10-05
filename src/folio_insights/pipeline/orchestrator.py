"""Pipeline orchestrator: chains all extraction stages with checkpointing.

Executes the full extraction pipeline in order:
  1. IngestionStage
  2. StructureParserStage
  3. BoundaryDetectionStage
  4. DistillerStage
  5. KnowledgeClassifierStage
  6. FolioTaggerStage
  7. DeduplicatorStage

After all stages: runs ConfidenceGate and OutputFormatter to produce
JSON output files. Supports checkpoint-based resume so interrupted
runs can continue from the last completed stage.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import tempfile
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from folio_insights.config import Settings
from folio_insights.llm.context import current_context
from folio_insights.models.corpus import CorpusManifest
from folio_insights.pipeline.stages.base import (
    InsightsJob,
    InsightsPipelineStage,
)

logger = logging.getLogger(__name__)


def _checkpoint_dir(output_dir: Path, checkpoint_dir: Path | None) -> Path:
    return Path(checkpoint_dir) if checkpoint_dir is not None else Path(output_dir) / "checkpoints"


# ``progress(event, stage_name, index, total, job)``: event is "start", "done" or "resumed".
# It runs at every stage boundary and may raise to stop the run there (job cancellation).
StageProgress = Callable[[str, str, int, int, Any], Awaitable[None] | None]


async def notify_stage(progress: StageProgress | None, *args: Any) -> None:
    if progress is None:
        return
    outcome = progress(*args)
    if inspect.isawaitable(outcome):
        await outcome


class PipelineCheckpoint:
    """Checkpoint management for pipeline stages."""

    @staticmethod
    def save(
        stage_name: str,
        job: InsightsJob,
        output_dir: Path,
        checkpoint_dir: Path | None = None,
    ) -> Path:
        """Serialize checkpoint to disk.

        Args:
            stage_name: Name of the completed stage.
            job: The current job state after stage execution.
            output_dir: Corpus output directory.
            checkpoint_dir: Override for ``<output_dir>/checkpoints`` (job-scoped runs).

        Returns:
            Path to the saved checkpoint file.
        """
        checkpoint_dir = _checkpoint_dir(output_dir, checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_dir / f"{stage_name}.json"

        data = {
            "stage": stage_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "unit_count": len(job.units),
            "job": job.model_dump(),
        }

        # Atomic: a crash mid-write must never leave a truncated checkpoint that a resume would
        # half-trust (temp file in the same directory, fsync, then rename over).
        fd, tmp = tempfile.mkstemp(dir=checkpoint_dir, prefix=f".{stage_name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, checkpoint_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

        logger.info("Saved checkpoint: %s (%d units)", stage_name, len(job.units))
        return checkpoint_path

    @staticmethod
    def load(
        stage_name: str, output_dir: Path, checkpoint_dir: Path | None = None
    ) -> InsightsJob | None:
        """Load a checkpoint if it exists.

        Args:
            stage_name: Name of the stage to load checkpoint for.
            output_dir: Corpus output directory.
            checkpoint_dir: Override for ``<output_dir>/checkpoints``.

        Returns:
            An InsightsJob restored from checkpoint, or None if no checkpoint.
        """
        checkpoint_path = _checkpoint_dir(output_dir, checkpoint_dir) / f"{stage_name}.json"
        if not checkpoint_path.exists():
            return None

        try:
            with open(checkpoint_path, encoding="utf-8") as f:
                data = json.load(f)
            return InsightsJob(**data["job"])
        except Exception:
            logger.warning(
                "Failed to load checkpoint %s; will re-run stage",
                checkpoint_path,
                exc_info=True,
            )
            return None

    @staticmethod
    def has_checkpoint(
        stage_name: str, output_dir: Path, checkpoint_dir: Path | None = None
    ) -> bool:
        """Check whether a checkpoint file exists for a stage."""
        checkpoint_path = _checkpoint_dir(output_dir, checkpoint_dir) / f"{stage_name}.json"
        return checkpoint_path.exists()

    @staticmethod
    def invalidate(
        stage_name: str, output_dir: Path, checkpoint_dir: Path | None = None
    ) -> None:
        """Delete a checkpoint file if it exists."""
        checkpoint_path = _checkpoint_dir(output_dir, checkpoint_dir) / f"{stage_name}.json"
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            logger.info("Invalidated checkpoint: %s", stage_name)


class PipelineOrchestrator:
    """Orchestrate the full knowledge extraction pipeline.

    Chains all 7 stages in order with checkpoint-based resume support.
    After all stages complete, runs confidence gating and output formatting.
    """

    def __init__(
        self,
        settings: Settings,
        stages: list[InsightsPipelineStage] | None = None,
    ) -> None:
        self.settings = settings
        self._stages: list[InsightsPipelineStage] = (
            list(stages) if stages is not None else self._build_stages()
        )

    @property
    def stages(self) -> list[InsightsPipelineStage]:
        return list(self._stages)

    def _build_stages(self) -> list[InsightsPipelineStage]:
        """Instantiate all pipeline stages in execution order."""
        from folio_insights.pipeline.stages.boundary_detection import (
            BoundaryDetectionStage,
        )
        from folio_insights.pipeline.stages.deduplicator import DeduplicatorStage
        from folio_insights.pipeline.stages.distiller import DistillerStage
        from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage
        from folio_insights.pipeline.stages.ingestion import IngestionStage
        from folio_insights.pipeline.stages.knowledge_classifier import (
            KnowledgeClassifierStage,
        )
        from folio_insights.pipeline.stages.structure_parser import (
            StructureParserStage,
        )

        return [
            IngestionStage(self.settings),
            StructureParserStage(),
            BoundaryDetectionStage(),
            DistillerStage(),
            KnowledgeClassifierStage(),
            FolioTaggerStage(),
            DeduplicatorStage(),
        ]

    def _run_b5_canary(self) -> dict[str, str] | None:
        """Run ``verify_deterministic_bridge()`` at job start when the run includes FOLIO tagging.

        With ``require_deterministic_iri`` (the default) a failure aborts the run before any
        stage executes; otherwise the run continues degraded and the failure is recorded in the
        output metadata (``b5_canary``).
        """
        if not any(stage.name == "folio_tagger" for stage in self._stages):
            return None
        from folio_insights.services.bridge.folio_bridge import (
            BridgeIntegrityError,
            verify_deterministic_bridge,
        )

        try:
            verify_deterministic_bridge()
        except Exception as exc:  # noqa: BLE001 - any canary failure is an integrity failure
            reason = f"{type(exc).__name__}: {exc}"[:400]
            if self.settings.require_deterministic_iri:
                if isinstance(exc, BridgeIntegrityError):
                    raise
                raise BridgeIntegrityError(f"B5 startup canary failed: {reason}") from exc
            logger.error("B5 startup canary failed; running DEGRADED: %s", reason)
            return {"status": "failed", "reason": reason}
        return {"status": "ok"}

    async def run(
        self,
        source_dir: Path,
        corpus_name: str | None = None,
        resume: bool = True,
        *,
        checkpoint_dir: Path | None = None,
        progress: StageProgress | None = None,
    ) -> InsightsJob:
        """Execute the full extraction pipeline.

        Args:
            source_dir: Directory containing source files to process.
            corpus_name: Name of the corpus (default from settings).
            resume: Whether to resume from checkpoints if available.
            checkpoint_dir: Where stage checkpoints live (default ``<corpus>/checkpoints``).
                Queued jobs use a job-scoped directory so a retry resumes its own run.
            progress: Stage-boundary callback (see :data:`StageProgress`); the durable job
                worker uses it for SSE progress and to stop a cancelled job between stages.

        Returns:
            The completed InsightsJob with all extracted knowledge units.
        """
        corpus_name = corpus_name or self.settings.corpus_name
        output_root = self.settings.output_dir.resolve()
        corpus_dir = (output_root / corpus_name).resolve()
        if not corpus_dir.is_relative_to(output_root):
            raise ValueError("Corpus path is outside the output directory")

        # Create initial job
        job = InsightsJob(
            corpus_name=corpus_name,
            source_dir=source_dir,
        )

        logger.info(
            "Starting pipeline for corpus '%s' from %s", corpus_name, source_dir
        )
        pipeline_start = time.monotonic()

        # B5 startup canary (KTD7): prove the deterministic IRI path loads before any stage runs.
        canary = self._run_b5_canary()

        # Execute each stage in order
        total = len(self._stages)
        for index, stage in enumerate(self._stages):
            stage_name = stage.name

            # Check for existing checkpoint
            if resume and PipelineCheckpoint.has_checkpoint(stage_name, corpus_dir, checkpoint_dir):
                restored = PipelineCheckpoint.load(stage_name, corpus_dir, checkpoint_dir)
                if restored is not None:
                    job = restored
                    # Template identities of stages run before the resume stay in the record.
                    current_context().merge_templates(job.metadata.get("llm_templates"))
                    logger.info(
                        "Resumed from checkpoint: %s (%d units)",
                        stage_name,
                        len(job.units),
                    )
                    await notify_stage(progress, "resumed", stage_name, index, total, job)
                    continue

            await notify_stage(progress, "start", stage_name, index, total, job)

            # Execute stage
            stage_start = time.monotonic()
            try:
                job = await stage.execute(job)
                # A run-halting LLM condition (no credential, spend cap) is swallowed per call by
                # the stage's own error handling; it must still stop the run here, before the
                # degraded stage output is checkpointed, so a resume re-runs this stage.
                current_context().raise_if_halted()
            except Exception:
                logger.exception("Stage '%s' failed", stage_name)
                raise

            stage_duration = time.monotonic() - stage_start
            logger.info(
                "Stage '%s' completed in %.1fs (%d units)",
                stage_name,
                stage_duration,
                len(job.units),
            )

            # Save checkpoint (with the template identities used so far, for resumes)
            job.metadata["llm_templates"] = {
                **(job.metadata.get("llm_templates") or {}),
                **current_context().templates_used,
            }
            PipelineCheckpoint.save(stage_name, job, corpus_dir, checkpoint_dir)
            await notify_stage(progress, "done", stage_name, index, total, job)

        # LLM accounting for the run report: per-task calls/tokens and the template hashes the
        # run actually used (no prompts, no unit text, no credentials).
        current_context().merge_templates(job.metadata.get("llm_templates"))
        llm_summary = current_context().usage_summary()
        if llm_summary["calls"] or llm_summary["templates"]:
            job.metadata["llm"] = llm_summary
        if canary is not None:
            job.metadata["b5_canary"] = canary

        # Post-pipeline: confidence gating + output formatting
        pipeline_duration = time.monotonic() - pipeline_start
        await self._write_output(job, corpus_name, corpus_dir)

        logger.info(
            "Pipeline complete for '%s': %d units in %.1fs",
            corpus_name,
            len(job.units),
            pipeline_duration,
        )
        return job

    async def _write_output(
        self, job: InsightsJob, corpus_name: str, corpus_dir: Path
    ) -> None:
        """Run confidence gating and write all output files."""
        from folio_insights.quality.confidence_gate import ConfidenceGate
        from folio_insights.quality.output_formatter import OutputFormatter

        # Build corpus manifest from job data
        corpus = CorpusManifest(
            name=corpus_name,
            documents=job.documents,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        # Confidence gating
        gate = ConfidenceGate(
            high_threshold=self.settings.confidence_high,
            medium_threshold=self.settings.confidence_medium,
        )
        gated = gate.gate_units(job.units)

        # Format output
        formatter = OutputFormatter()
        units_json = formatter.format_units_json(job.units, corpus, job.metadata)
        review_json = formatter.format_review_report(gated)
        proposed_json = formatter.format_proposed_classes_report(job.units)

        # Write files
        formatter.write_output(
            self.settings.output_dir, corpus_name, units_json, review_json, proposed_json
        )

        # Save corpus registry
        from folio_insights.services.corpus_registry import CorpusRegistry

        registry = CorpusRegistry(corpus_name)
        registry._manifest = corpus
        registry.save(corpus_dir)
