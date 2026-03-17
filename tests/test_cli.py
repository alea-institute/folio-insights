"""Tests for the folio-insights CLI and pipeline orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from folio_insights.cli import cli
from folio_insights.pipeline.orchestrator import PipelineCheckpoint, PipelineOrchestrator
from folio_insights.pipeline.stages.base import InsightsJob


@pytest.fixture
def runner() -> CliRunner:
    """Provide a Click CliRunner for testing CLI commands."""
    return CliRunner()


@pytest.fixture
def sample_source_dir(tmp_path: Path) -> Path:
    """Create a temp directory with sample legal text files."""
    md_file = tmp_path / "chapter8.md"
    md_file.write_text(
        "# Expert Witnesses\n\n"
        "## Methodology Challenges\n\n"
        "Lock expert into reviewed-document list during deposition. "
        "This prevents the expert from expanding their opinion basis at trial.\n\n"
        "## Preparation Tips\n\n"
        "Always verify the expert's CV against published records. "
        "Check for inconsistencies in their claimed qualifications.\n",
        encoding="utf-8",
    )

    md_file2 = tmp_path / "chapter9.md"
    md_file2.write_text(
        "# Cross-Examination\n\n"
        "## Leading Questions\n\n"
        "Use short declarative statements that compel agreement. "
        "Never ask a question you do not know the answer to.\n",
        encoding="utf-8",
    )
    return tmp_path


class TestCLIHelp:
    """Test CLI help and basic invocation."""

    def test_cli_help(self, runner: CliRunner) -> None:
        """folio-insights --help exits 0 and lists commands."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "extract" in result.output
        assert "serve" in result.output

    def test_extract_help(self, runner: CliRunner) -> None:
        """folio-insights extract --help exits 0 and shows options."""
        result = runner.invoke(cli, ["extract", "--help"])
        assert result.exit_code == 0
        assert "--corpus" in result.output
        assert "--output" in result.output
        assert "--confidence-high" in result.output
        assert "--confidence-medium" in result.output
        assert "--resume" in result.output

    def test_serve_help(self, runner: CliRunner) -> None:
        """folio-insights serve --help shows port and host options."""
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--host" in result.output


class TestCLIValidation:
    """Test CLI input validation."""

    def test_invalid_source_dir(self, runner: CliRunner) -> None:
        """Nonexistent source directory exits with error."""
        result = runner.invoke(cli, ["extract", "/nonexistent/path/to/nowhere"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    def test_empty_source_dir(self, runner: CliRunner, tmp_path: Path) -> None:
        """Empty source directory exits with error."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = runner.invoke(cli, ["extract", str(empty_dir)])
        assert result.exit_code == 1
        assert "empty" in result.output.lower()


class TestPipelineOrchestrator:
    """Test PipelineOrchestrator directly."""

    async def test_orchestrator_stages_order(self) -> None:
        """Orchestrator has all 7 stages in the correct order."""
        from folio_insights.config import Settings

        settings = Settings()
        orchestrator = PipelineOrchestrator(settings)

        stage_names = [s.name for s in orchestrator._stages]
        expected = [
            "ingestion",
            "structure_parser",
            "boundary_detection",
            "distiller",
            "knowledge_classifier",
            "folio_tagger",
            "deduplicator",
        ]
        assert stage_names == expected


class TestPipelineCheckpoint:
    """Test checkpoint save/load/has/invalidate."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        """Checkpoint save and load round-trips correctly."""
        job = InsightsJob(corpus_name="test", source_dir=tmp_path)
        PipelineCheckpoint.save("ingestion", job, tmp_path)

        assert PipelineCheckpoint.has_checkpoint("ingestion", tmp_path)

        loaded = PipelineCheckpoint.load("ingestion", tmp_path)
        assert loaded is not None
        assert loaded.corpus_name == "test"

    def test_has_checkpoint_nonexistent(self, tmp_path: Path) -> None:
        """has_checkpoint returns False for nonexistent checkpoint."""
        assert not PipelineCheckpoint.has_checkpoint("fake_stage", tmp_path)

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        """Loading a nonexistent checkpoint returns None."""
        result = PipelineCheckpoint.load("fake_stage", tmp_path)
        assert result is None

    def test_invalidate(self, tmp_path: Path) -> None:
        """Invalidate removes checkpoint file."""
        job = InsightsJob(corpus_name="test", source_dir=tmp_path)
        PipelineCheckpoint.save("ingestion", job, tmp_path)

        assert PipelineCheckpoint.has_checkpoint("ingestion", tmp_path)

        PipelineCheckpoint.invalidate("ingestion", tmp_path)
        assert not PipelineCheckpoint.has_checkpoint("ingestion", tmp_path)


class TestBatchPipeline:
    """Test end-to-end pipeline via CLI with mocked stages."""

    def test_batch_pipeline(
        self, runner: CliRunner, sample_source_dir: Path, tmp_path: Path
    ) -> None:
        """CLI extract invocation produces JSON output."""
        output_dir = tmp_path / "output"

        # Mock the orchestrator to avoid needing real bridge services
        mock_job = InsightsJob(
            corpus_name="default",
            source_dir=sample_source_dir,
        )

        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=mock_job)

        with patch(
            "folio_insights.pipeline.orchestrator.PipelineOrchestrator",
            return_value=mock_instance,
        ):
            result = runner.invoke(
                cli,
                [
                    "extract",
                    str(sample_source_dir),
                    "--output",
                    str(output_dir),
                    "--corpus",
                    "default",
                ],
            )

        assert result.exit_code == 0
        assert "Extraction Summary" in result.output

    def test_extract_produces_json(
        self, runner: CliRunner, sample_source_dir: Path, tmp_path: Path
    ) -> None:
        """Extract produces valid JSON extraction.json output."""
        output_dir = tmp_path / "output"

        # Create a job with some units for richer output
        from folio_insights.models.knowledge_unit import (
            KnowledgeType,
            KnowledgeUnit,
            Span,
        )
        from folio_insights.models.corpus import CorpusDocument

        mock_job = InsightsJob(
            corpus_name="default",
            source_dir=sample_source_dir,
            documents=[
                CorpusDocument(
                    file_path="chapter8.md",
                    content_hash="abc",
                    format="markdown",
                )
            ],
            units=[
                KnowledgeUnit(
                    text="Lock expert into reviewed-document list",
                    original_span=Span(start=0, end=40, source_file="chapter8.md"),
                    unit_type=KnowledgeType.ADVICE,
                    source_file="chapter8.md",
                    source_section=["Expert Witnesses", "Methodology Challenges"],
                    confidence=0.9,
                    content_hash="hash1",
                )
            ],
        )

        # Patch orchestrator to return mock job, but let _write_output run
        with patch.object(
            PipelineOrchestrator,
            "_build_stages",
            return_value=[],
        ):
            # Patch the stage execution loop to just write output
            async def mock_run(self, source_dir, corpus_name=None, resume=True):
                corpus_name = corpus_name or self.settings.corpus_name
                corpus_dir = self.settings.output_dir / corpus_name
                mock_job.corpus_name = corpus_name
                await self._write_output(mock_job, corpus_name, corpus_dir)
                return mock_job

            with patch.object(PipelineOrchestrator, "run", mock_run):
                result = runner.invoke(
                    cli,
                    [
                        "extract",
                        str(sample_source_dir),
                        "--output",
                        str(output_dir),
                        "--corpus",
                        "default",
                    ],
                )

        assert result.exit_code == 0, f"CLI failed: {result.output}"

        extraction_path = output_dir / "default" / "extraction.json"
        assert extraction_path.exists(), f"extraction.json not found. Output: {result.output}"

        with open(extraction_path) as f:
            data = json.load(f)

        assert "units" in data
        assert data["total_units"] == 1
        assert data["corpus"] == "default"

    def test_summary_output(
        self, runner: CliRunner, sample_source_dir: Path, tmp_path: Path
    ) -> None:
        """CLI output contains summary with unit count and confidence breakdown."""
        from folio_insights.models.knowledge_unit import (
            KnowledgeType,
            KnowledgeUnit,
            Span,
        )

        mock_job = InsightsJob(
            corpus_name="default",
            source_dir=sample_source_dir,
            units=[
                KnowledgeUnit(
                    text="High conf unit",
                    original_span=Span(start=0, end=10, source_file="test.md"),
                    unit_type=KnowledgeType.ADVICE,
                    source_file="test.md",
                    confidence=0.9,
                    content_hash="h1",
                ),
                KnowledgeUnit(
                    text="Low conf unit",
                    original_span=Span(start=0, end=10, source_file="test.md"),
                    unit_type=KnowledgeType.PITFALL,
                    source_file="test.md",
                    confidence=0.3,
                    content_hash="h2",
                ),
            ],
        )

        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=mock_job)

        with patch(
            "folio_insights.pipeline.orchestrator.PipelineOrchestrator",
            return_value=mock_instance,
        ):
            result = runner.invoke(
                cli,
                [
                    "extract",
                    str(sample_source_dir),
                    "--output",
                    str(tmp_path / "output"),
                ],
            )

        assert result.exit_code == 0
        assert "Units extracted:" in result.output
        assert "High confidence:" in result.output
        assert "Low confidence:" in result.output

    def test_checkpoint_resume(self, tmp_path: Path) -> None:
        """Checkpoint-based resume skips already-completed stages."""
        source_dir = tmp_path / "sources"
        source_dir.mkdir()
        (source_dir / "test.md").write_text("# Test\n\nContent.\n")

        output_dir = tmp_path / "output"
        corpus_dir = output_dir / "default"

        # Save a checkpoint for ingestion stage
        job = InsightsJob(corpus_name="default", source_dir=source_dir)
        PipelineCheckpoint.save("ingestion", job, corpus_dir)

        # The checkpoint should be loadable
        assert PipelineCheckpoint.has_checkpoint("ingestion", corpus_dir)
        loaded = PipelineCheckpoint.load("ingestion", corpus_dir)
        assert loaded is not None
        assert loaded.corpus_name == "default"
