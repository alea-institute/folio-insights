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


@cli.command("export")
@click.argument("corpus_name")
@click.option(
    "--output", "-o",
    default="./output",
    show_default=True,
    type=click.Path(resolve_path=True),
    help="Output directory containing extraction results.",
)
@click.option(
    "--format", "-f", "formats",
    default="owl,ttl,jsonld,html,md",
    show_default=True,
    help="Comma-separated formats: owl,ttl,jsonld,html,md",
)
@click.option(
    "--approved-only/--all",
    default=True,
    show_default=True,
    help="Export only approved tasks (default: approved-only).",
)
@click.option(
    "--validate/--no-validate",
    default=True,
    show_default=True,
    help="Run SHACL validation after export.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Enable verbose (DEBUG) logging.",
)
def export(
    corpus_name: str,
    output: str,
    formats: str,
    approved_only: bool,
    validate: bool,
    verbose: bool,
) -> None:
    """Export approved tasks as OWL ontology and companion files.

    Reads review.db from the corpus output directory and exports the
    approved task hierarchy in the requested formats.

    Supported formats: owl (RDF/XML), ttl (Turtle), jsonld (JSON-LD),
    html (browsable site), md (Markdown outline).
    """
    _setup_logging(verbose)

    output_path = Path(output)
    corpus_dir = output_path / corpus_name
    db_path = corpus_dir / "review.db"

    if not db_path.exists():
        click.echo(
            f"Error: No review database found at {db_path}. "
            "Run 'folio-insights discover' first.",
            err=True,
        )
        sys.exit(1)

    # Load data from review.db using sync sqlite3
    import json as _json
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Load tasks
    if approved_only:
        task_rows = conn.execute(
            "SELECT * FROM task_decisions WHERE corpus_name = ? AND status = 'approved' "
            "ORDER BY canonical_order, label",
            (corpus_name,),
        ).fetchall()
    else:
        task_rows = conn.execute(
            "SELECT * FROM task_decisions WHERE corpus_name = ? "
            "ORDER BY canonical_order, label",
            (corpus_name,),
        ).fetchall()

    if not task_rows:
        click.echo("Error: No tasks found to export.", err=True)
        conn.close()
        sys.exit(1)

    tasks = [
        {
            "id": r["task_id"],
            "label": r["edited_label"] or r["label"],
            "folio_iri": r["folio_iri"],
            "parent_task_id": r["parent_task_id"],
            "is_procedural": bool(r["is_procedural"]),
            "canonical_order": r["canonical_order"],
            "is_manual": bool(r["is_manual"]),
            "status": r["status"],
        }
        for r in task_rows
    ]

    # Load unit links
    link_rows = conn.execute(
        "SELECT task_id, unit_id FROM task_unit_links WHERE corpus_name = ?",
        (corpus_name,),
    ).fetchall()

    task_unit_map: dict[str, list[str]] = {}
    for r in link_rows:
        task_unit_map.setdefault(r["task_id"], []).append(r["unit_id"])

    # Load extraction.json for unit details
    extraction_path = corpus_dir / "extraction.json"
    if extraction_path.exists():
        ext_data = _json.loads(extraction_path.read_text(encoding="utf-8"))
        all_units = {u["id"]: u for u in ext_data.get("units", [])}
    else:
        all_units = {}

    units_by_task: dict[str, list[dict]] = {}
    for tid, uids in task_unit_map.items():
        units_by_task[tid] = [all_units[uid] for uid in uids if uid in all_units]

    # Load contradictions
    contra_rows = conn.execute(
        "SELECT * FROM contradictions WHERE corpus_name = ?",
        (corpus_name,),
    ).fetchall()
    contradictions = [
        {
            "task_id": r["task_id"],
            "unit_id_a": r["unit_id_a"],
            "unit_id_b": r["unit_id_b"],
            "nli_score": r["nli_score"],
            "contradiction_type": r["contradiction_type"],
            "resolution": r["resolution"],
        }
        for r in contra_rows
    ]
    conn.close()

    metadata = {
        "corpus": corpus_name,
        "total_tasks": len(tasks),
        "total_units": sum(len(v) for v in units_by_task.values()),
    }

    # Parse formats
    format_list = [f.strip().lower() for f in formats.split(",") if f.strip()]

    click.echo(f"Exporting corpus: {corpus_name}")
    click.echo(f"Formats: {', '.join(format_list)}")
    click.echo(f"Tasks: {len(tasks)} ({'approved only' if approved_only else 'all'})")
    click.echo("")

    from folio_insights.services.task_exporter import TaskExporter

    exporter = TaskExporter()
    produced_files: list[str] = []

    # OWL and Turtle
    if "owl" in format_list or "ttl" in format_list:
        rdfxml, turtle, changelog = asyncio.run(
            exporter.export_owl(
                tasks, units_by_task, contradictions, metadata, db_path, corpus_dir
            )
        )
        if "owl" in format_list:
            produced_files.append(f"folio-insights.owl ({len(rdfxml)} bytes)")
        if "ttl" in format_list:
            produced_files.append(f"folio-insights.ttl ({len(turtle)} bytes)")
        if changelog:
            produced_files.append("CHANGELOG.md")

        # Validation
        if validate:
            from folio_insights.services.owl_serializer import OWLSerializer

            serializer = OWLSerializer()
            graph = serializer.build_graph(
                tasks, units_by_task,
                {t["id"]: t["folio_iri"] for t in tasks if t.get("folio_iri")},
                contradictions, metadata,
            )
            report_md = exporter.export_owl_validate(graph, corpus_dir)
            produced_files.append("validation-report.md")
            if "FAIL" in report_md:
                click.echo("Warning: SHACL validation has failures.", err=True)

    # JSON-LD
    if "jsonld" in format_list:
        asyncio.run(
            exporter.export_jsonld(tasks, units_by_task, db_path, corpus_dir)
        )
        produced_files.append("folio-insights.jsonld")

    # HTML browsable
    if "html" in format_list:
        html = exporter.export_browsable_html(
            tasks, units_by_task, contradictions, metadata
        )
        (corpus_dir / "browsable-index.html").write_text(html, encoding="utf-8")
        produced_files.append("browsable-index.html")

    # Markdown
    if "md" in format_list:
        md = exporter.export_markdown(tasks, units_by_task)
        (corpus_dir / "task-hierarchy.md").write_text(md, encoding="utf-8")
        produced_files.append("task-hierarchy.md")

    click.echo("--- Export Summary ---")
    for pf in produced_files:
        click.echo(f"  {pf}")
    click.echo(f"Output: {corpus_dir}/")


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
