"""Batch CLI entry point for folio-insights.

Provides the `folio-insights extract <directory>` command that runs
the full extraction pipeline and `folio-insights discover <corpus>`
that runs the 6-stage task discovery pipeline.

Uses Click for argument parsing per CONTEXT.md decision.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click

logger = logging.getLogger("folio_insights")


def _setup_logging(verbose: bool) -> None:
    """Configure logging level and format."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.version_option(package_name="folio-insights")
def cli() -> None:
    """folio-insights: Extract structured advocacy knowledge from legal texts."""


@cli.command("extract")
@click.argument(
    "source_dir",
    type=click.Path(exists=False, file_okay=False, resolve_path=True),
)
@click.option(
    "--corpus", "-c",
    default="default",
    show_default=True,
    help="Corpus name for grouping extraction results.",
)
@click.option(
    "--output", "-o",
    default="./output",
    show_default=True,
    type=click.Path(resolve_path=True),
    help="Output directory for JSON results.",
)
@click.option(
    "--confidence-high",
    default=0.8,
    show_default=True,
    type=float,
    help="High confidence threshold for auto-approve.",
)
@click.option(
    "--confidence-medium",
    default=0.5,
    show_default=True,
    type=float,
    help="Medium confidence threshold boundary.",
)
@click.option(
    "--resume/--no-resume",
    default=True,
    show_default=True,
    help="Resume from last checkpoint.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Enable verbose (DEBUG) logging.",
)
def extract(
    source_dir: str,
    corpus: str,
    output: str,
    confidence_high: float,
    confidence_medium: float,
    resume: bool,
    verbose: bool,
) -> None:
    """Extract knowledge units from source files in SOURCE_DIR.

    Runs the full pipeline: ingestion -> structure parsing -> boundary
    detection -> distillation -> classification -> FOLIO tagging ->
    deduplication -> JSON output.

    Output is written to {output}/{corpus}/ as extraction.json,
    review.json, and proposed_classes.json.
    """
    _setup_logging(verbose)

    source_path = Path(source_dir)
    if not source_path.exists():
        click.echo(f"Error: Source directory not found: {source_dir}", err=True)
        sys.exit(1)

    if not source_path.is_dir():
        click.echo(f"Error: Not a directory: {source_dir}", err=True)
        sys.exit(1)

    # Check for files in source directory
    files = list(source_path.iterdir())
    if not files:
        click.echo(f"Error: Source directory is empty: {source_dir}", err=True)
        sys.exit(1)

    # Build settings from CLI options
    from folio_insights.config import Settings

    settings = Settings(
        output_dir=Path(output),
        corpus_name=corpus,
        confidence_high=confidence_high,
        confidence_medium=confidence_medium,
    )

    # Create and run pipeline
    from folio_insights.pipeline.orchestrator import PipelineOrchestrator

    orchestrator = PipelineOrchestrator(settings)

    click.echo(f"Extracting from: {source_dir}")
    click.echo(f"Corpus: {corpus}")
    click.echo(f"Output: {output}/{corpus}/")
    click.echo("")

    try:
        job = asyncio.run(
            orchestrator.run(source_path, corpus_name=corpus, resume=resume)
        )
    except Exception as exc:
        click.echo(f"Error: Pipeline failed: {exc}", err=True)
        logger.debug("Pipeline error details", exc_info=True)
        sys.exit(1)

    # Print summary
    from folio_insights.quality.confidence_gate import ConfidenceGate

    gate = ConfidenceGate(
        high_threshold=confidence_high,
        medium_threshold=confidence_medium,
    )
    gated = gate.gate_units(job.units)

    click.echo("--- Extraction Summary ---")
    click.echo(f"Files processed:  {len(job.documents)}")
    click.echo(f"Units extracted:  {len(job.units)}")
    click.echo(f"  High confidence:   {len(gated['high'])}")
    click.echo(f"  Medium confidence: {len(gated['medium'])}")
    click.echo(f"  Low confidence:    {len(gated['low'])}")
    click.echo(f"Output: {output}/{corpus}/extraction.json")


@cli.command("discover")
@click.argument("corpus_name")
@click.option(
    "--output", "-o",
    default="./output",
    show_default=True,
    type=click.Path(resolve_path=True),
    help="Output directory containing extraction results.",
)
@click.option(
    "--cluster-threshold",
    default=0.5,
    show_default=True,
    type=float,
    help="Distance threshold for content clustering (lower = more clusters).",
)
@click.option(
    "--contradiction-threshold",
    default=0.7,
    show_default=True,
    type=float,
    help="NLI score threshold for contradiction LLM follow-up.",
)
@click.option(
    "--resume/--no-resume",
    default=True,
    show_default=True,
    help="Resume from last checkpoint.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Enable verbose (DEBUG) logging.",
)
def discover(
    corpus_name: str,
    output: str,
    cluster_threshold: float,
    contradiction_threshold: float,
    resume: bool,
    verbose: bool,
) -> None:
    """Discover advocacy tasks from extracted knowledge units in CORPUS_NAME.

    Reads extraction.json from the corpus output directory and runs
    the 6-stage task discovery pipeline: heading analysis, FOLIO mapping,
    content clustering, hierarchy construction, cross-source merging,
    and contradiction detection.

    Output is written to {output}/{corpus_name}/discovery.json and task_tree.json.
    """
    _setup_logging(verbose)

    output_path = Path(output)
    extraction_path = output_path / corpus_name / "extraction.json"

    if not extraction_path.exists():
        click.echo(
            f"Error: No extraction output found at {extraction_path}. "
            "Run 'folio-insights extract' first.",
            err=True,
        )
        sys.exit(1)

    # Build settings from CLI options
    from folio_insights.config import Settings

    settings = Settings(
        output_dir=output_path,
        corpus_name=corpus_name,
    )

    # Create and run discovery pipeline
    from folio_insights.pipeline.discovery.orchestrator import (
        TaskDiscoveryOrchestrator,
    )

    # Check for review database (optional -- enables decision persistence)
    db_path = output_path / corpus_name / "review.db"
    orchestrator = TaskDiscoveryOrchestrator(
        settings,
        db_path=db_path if db_path.exists() else None,
    )

    click.echo(f"Discovering tasks for corpus: {corpus_name}")
    click.echo(f"Source: {extraction_path}")
    click.echo(f"Cluster threshold: {cluster_threshold}")
    click.echo(f"Contradiction threshold: {contradiction_threshold}")
    click.echo("")

    try:
        job = asyncio.run(
            orchestrator.run(corpus_name, resume=resume)
        )
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"Error: Discovery pipeline failed: {exc}", err=True)
        logger.debug("Discovery error details", exc_info=True)
        sys.exit(1)

    # Print summary
    task_count = len(job.task_hierarchy.tasks) if job.task_hierarchy else 0
    contradiction_count = len(job.contradictions)
    orphan_count = len(job.orphan_unit_ids)

    click.echo("--- Discovery Summary ---")
    click.echo(f"Tasks discovered:    {task_count}")
    click.echo(f"Contradictions found: {contradiction_count}")
    click.echo(f"Orphan units:        {orphan_count}")
    click.echo(f"Output: {output}/{corpus_name}/discovery.json")
    click.echo(f"Tree:   {output}/{corpus_name}/task_tree.json")


@cli.command("serve")
@click.option(
    "--port", "-p",
    default=8742,
    show_default=True,
    type=int,
    help="Port for the review viewer server.",
)
@click.option(
    "--host", "-h",
    default="127.0.0.1",
    show_default=True,
    help="Host address for the review viewer server.",
)
def serve(port: int, host: str) -> None:
    """Start the FastAPI review viewer server.

    (Placeholder -- full implementation in Plan 01-04.)
    """
    click.echo(f"Review viewer server placeholder. Will start on {host}:{port}")
    click.echo("Full implementation coming in Plan 01-04.")


def main() -> None:
    """Entry point for the folio-insights CLI."""
    cli()
