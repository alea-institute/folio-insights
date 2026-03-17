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

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from folio_insights.config import Settings
from folio_insights.models.corpus import CorpusManifest
from folio_insights.pipeline.stages.base import (
    InsightsJob,
    InsightsPipelineStage,
)

logger = logging.getLogger(__name__)


class PipelineCheckpoint:
    """Checkpoint management for pipeline stages."""

    @staticmethod
    def save(stage_name: str, job: InsightsJob, output_dir: Path) -> Path:
        """Serialize checkpoint to disk.

        Args:
            stage_name: Name of the completed stage.
            job: The current job state after stage execution.
            output_dir: Corpus output directory.

        Returns:
            Path to the saved checkpoint file.
        """
        checkpoint_dir = Path(output_dir) / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_dir / f"{stage_name}.json"

        data = {
            "stage": stage_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "unit_count": len(job.units),
            "job": job.model_dump(),
        }

        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info("Saved checkpoint: %s (%d units)", stage_name, len(job.units))
        return checkpoint_path

    @staticmethod
    def load(stage_name: str, output_dir: Path) -> InsightsJob | None:
        """Load a checkpoint if it exists.

        Args:
            stage_name: Name of the stage to load checkpoint for.
            output_dir: Corpus output directory.

        Returns:
            An InsightsJob restored from checkpoint, or None if no checkpoint.
        """
        checkpoint_path = Path(output_dir) / "checkpoints" / f"{stage_name}.json"
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
    def has_checkpoint(stage_name: str, output_dir: Path) -> bool:
        """Check whether a checkpoint file exists for a stage."""
        checkpoint_path = Path(output_dir) / "checkpoints" / f"{stage_name}.json"
        return checkpoint_path.exists()

    @staticmethod
    def invalidate(stage_name: str, output_dir: Path) -> None:
        """Delete a checkpoint file if it exists."""
        checkpoint_path = Path(output_dir) / "checkpoints" / f"{stage_name}.json"
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            logger.info("Invalidated checkpoint: %s", stage_name)


class PipelineOrchestrator:
    """Orchestrate the full knowledge extraction pipeline.

    Chains all 7 stages in order with checkpoint-based resume support.
    After all stages complete, runs confidence gating and output formatting.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._stages: list[InsightsPipelineStage] = self._build_stages()

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
            IngestionStage(),
            StructureParserStage(),
            BoundaryDetectionStage(),
            DistillerStage(),
            KnowledgeClassifierStage(),
            FolioTaggerStage(),
            DeduplicatorStage(),
        ]

    async def run(
        self,
        source_dir: Path,
        corpus_name: str | None = None,
        resume: bool = True,
    ) -> InsightsJob:
        """Execute the full extraction pipeline.

        Args:
            source_dir: Directory containing source files to process.
            corpus_name: Name of the corpus (default from settings).
            resume: Whether to resume from checkpoints if available.

        Returns:
            The completed InsightsJob with all extracted knowledge units.
        """
        corpus_name = corpus_name or self.settings.corpus_name
        corpus_dir = self.settings.output_dir / corpus_name

        # Create initial job
        job = InsightsJob(
            corpus_name=corpus_name,
            source_dir=source_dir,
        )

        logger.info(
            "Starting pipeline for corpus '%s' from %s", corpus_name, source_dir
        )
        pipeline_start = time.monotonic()

        # Execute each stage in order
        for stage in self._stages:
            stage_name = stage.name

            # Check for existing checkpoint
            if resume and PipelineCheckpoint.has_checkpoint(stage_name, corpus_dir):
                restored = PipelineCheckpoint.load(stage_name, corpus_dir)
                if restored is not None:
                    job = restored
                    logger.info(
                        "Resumed from checkpoint: %s (%d units)",
                        stage_name,
                        len(job.units),
                    )
                    continue

            # Execute stage
            stage_start = time.monotonic()
            try:
                job = await stage.execute(job)
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

            # Save checkpoint
            PipelineCheckpoint.save(stage_name, job, corpus_dir)

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
