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


def _llm_options(func):
    """``--llm-provider`` / ``--llm-model``: the run-wide route for every LLM task.

    Per-task ``LLM_{TASK}_PROVIDER`` / ``LLM_{TASK}_MODEL`` environment overrides still win.
    """
    from folio_insights.llm.providers import supported_providers

    func = click.option(
        "--llm-model",
        default=None,
        help="Model for every LLM task (default: settings, or the provider's default model).",
    )(func)
    func = click.option(
        "--max-spend-usd",
        default=None,
        type=float,
        help="Spend cap in USD (default $FOLIO_INSIGHTS_LLM_MAX_SPEND_USD), CUMULATIVE across runs "
        "of this corpus and --spend-window: what earlier runs spent counts against it. A request "
        "that could exceed it is never sent; the run stops, resumable from its checkpoint.",
    )(func)
    func = click.option(
        "--spend-window",
        default="default",
        show_default=True,
        help="Name of the cumulative spend budget for this corpus; pass a new name to start a "
        "fresh budget.",
    )(func)
    func = click.option(
        "--llm-provider",
        default=None,
        type=click.Choice(supported_providers(), case_sensitive=False),
        help="LLM provider for every LLM task (default: FOLIO_INSIGHTS_LLM_PROVIDER).",
    )(func)
    return func


def _install_cli_llm_context(
    provider: str | None, model: str | None, max_spend_usd: float | None = None,
    corpus: str = "", spend_window: str = "default",
):
    """Use the invoking user's own keys (their environment) for this CLI command.

    Only CLI commands that run LLM work on the user's behalf call this, and the context lives
    only as long as the command (``click`` closes it as a resource). ``serve`` never does: the API
    process takes keys per request and must not hold an ambient one (R2).
    """
    import os

    from folio_insights.jobs.queue import default_queue_path
    from folio_insights.llm import Credentials, LLMRunContext, use_context
    from folio_insights.llm.cost import SPEND_CAP_ENV, CostMeter
    from folio_insights.llm.usage import UsageLedger

    # A stable run id per (corpus, spend window): the meter seeds itself from the ledger, so the
    # cap is cumulative across CLI runs of the corpus (a resume after the cap keeps counting).
    run_id = f"cli:{corpus or 'default'}:{spend_window or 'default'}"
    cap = max_spend_usd if max_spend_usd is not None else (os.environ.get(SPEND_CAP_ENV) or None)
    ctx = LLMRunContext(
        credentials=Credentials.from_env(),
        provider=provider.lower() if provider else None,
        model=model or None,
        run_id=run_id,
        meter=CostMeter(run_id=run_id, ledger=UsageLedger(default_queue_path()), cap_usd=cap,
                        corpus_id=corpus),
    )
    click.get_current_context().with_resource(use_context(ctx))
    return ctx


def _echo_llm_usage(ctx) -> None:
    summary = ctx.usage_summary()
    if not summary["calls"]:
        return
    click.echo("--- LLM Usage ---")
    for row in summary["by_task"]:
        click.echo(
            f"{row['task']:<18} {row['provider']}/{row['model']}: {row['calls']} call(s), "
            f"{row['input_tokens']} in / {row['output_tokens']} out tokens"
            + (f", {row['errors']} failed" if row["errors"] else "")
        )
    cost = summary.get("cost")
    if cost:
        cap = f" (cap ${cost['cap_usd']})" if cost.get("cap_usd") else ""
        click.echo(f"Cost: ${cost['spent_usd']}{cap}, price table {cost['price_table_version']}, "
                   f"run {ctx.run_id}"
                   + (f"; {cost['unpriced_calls']} unpriced call(s)" if cost["unpriced_calls"] else ""))


async def _closing(llm_ctx, coro):
    """Await ``coro``, then close the SDK clients the run built (they hold the user's key)."""
    try:
        return await coro
    finally:
        await llm_ctx.aclose()


def _echo_halt_hint(exc: BaseException) -> None:
    kind = getattr(exc, "kind", "")
    if kind == "budget_exhausted":
        click.echo("The spend cap stopped the run before a request that could exceed it. The cap "
                   "is cumulative for this corpus and --spend-window: re-run with a higher "
                   "--max-spend-usd (or a new --spend-window) to resume from the last completed "
                   "stage.", err=True)
    elif kind == "needs_credentials":
        click.echo("Set the provider's API key in your environment and re-run; completed "
                   "stages resume from their checkpoints.", err=True)


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
@_llm_options
def extract(
    source_dir: str,
    corpus: str,
    output: str,
    confidence_high: float,
    confidence_medium: float,
    resume: bool,
    verbose: bool,
    llm_provider: str | None,
    llm_model: str | None,
    max_spend_usd: float | None,
    spend_window: str,
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

    llm_ctx = _install_cli_llm_context(llm_provider, llm_model, max_spend_usd, corpus,
                                       spend_window)

    # Create and run pipeline
    from folio_insights.pipeline.orchestrator import PipelineOrchestrator

    orchestrator = PipelineOrchestrator(settings)

    click.echo(f"Extracting from: {source_dir}")
    click.echo(f"Corpus: {corpus}")
    click.echo(f"Output: {output}/{corpus}/")
    click.echo("")

    try:
        job = asyncio.run(_closing(
            llm_ctx, orchestrator.run(source_path, corpus_name=corpus, resume=resume)
        ))
    except Exception as exc:
        click.echo(f"Error: Pipeline failed: {exc}", err=True)
        _echo_halt_hint(exc)
        _echo_llm_usage(llm_ctx)
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
    _echo_llm_usage(llm_ctx)


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
@_llm_options
def discover(
    corpus_name: str,
    output: str,
    cluster_threshold: float,
    contradiction_threshold: float,
    resume: bool,
    verbose: bool,
    llm_provider: str | None,
    llm_model: str | None,
    max_spend_usd: float | None,
    spend_window: str,
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

    llm_ctx = _install_cli_llm_context(llm_provider, llm_model, max_spend_usd, corpus_name,
                                       spend_window)

    # Create and run discovery pipeline
    from folio_insights.pipeline.discovery.orchestrator import (
        TaskDiscoveryOrchestrator,
    )

    # review.db holds reviewer decisions. Always pass it: a missing database reads as "no
    # approved decisions yet", and discovery creates or refreshes it so `export` can read it.
    db_path = output_path / corpus_name / "review.db"
    orchestrator = TaskDiscoveryOrchestrator(settings, db_path=db_path)

    click.echo(f"Discovering tasks for corpus: {corpus_name}")
    click.echo(f"Source: {extraction_path}")
    click.echo(f"Cluster threshold: {cluster_threshold}")
    click.echo(f"Contradiction threshold: {contradiction_threshold}")
    click.echo("")

    try:
        job = asyncio.run(_closing(llm_ctx, orchestrator.run(corpus_name, resume=resume)))
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"Error: Discovery pipeline failed: {exc}", err=True)
        _echo_halt_hint(exc)
        _echo_llm_usage(llm_ctx)
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
    _echo_llm_usage(llm_ctx)


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
        # Tell "nothing discovered" apart from "nothing approved yet": a CLI-only run discovers
        # tasks as 'unreviewed', and export defaults to approved tasks only.
        if approved_only:
            total = conn.execute(
                "SELECT COUNT(*) FROM task_decisions WHERE corpus_name = ?",
                (corpus_name,),
            ).fetchone()[0]
            if total:
                click.echo(
                    f"Error: No approved tasks to export ({total} discovered but unreviewed). "
                    "Approve them in the reviewer UI, or re-run with '--all' to export "
                    "everything discovered.",
                    err=True,
                )
                conn.close()
                sys.exit(1)
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


@cli.command("verify-iris")
@click.option(
    "--db",
    "db_path",
    default=None,
    type=click.Path(),
    help="Path to the global shard IRI registry DB "
    "(defaults to the registry's standing path).",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Enable verbose (DEBUG) logging.",
)
def verify_iris(db_path: str | None, verbose: bool) -> None:
    """Re-hash every stored shard IRI and report any drift (D-06/D-07).

    The standing nightly guard against source drift or a hash-logic regression:
    re-mint each stored shard's IRI from its stored source_uri + source_span and
    compare to the stored body. Any mismatch is surfaced for human review with a
    non-zero exit -- this command NEVER auto-quarantines or mutates the registry.
    """
    _setup_logging(verbose)

    # Lazy imports: keep the registry + minting off `folio-insights --help`.
    import asyncio as _asyncio

    from folio_insights.shards.iri_registry import (
        DEFAULT_REGISTRY_PATH,
        ShardIRIRegistry,
    )
    from folio_insights.shards.minting import mint_shard_iri

    registry_path = Path(db_path) if db_path else DEFAULT_REGISTRY_PATH

    if not registry_path.exists():
        click.echo(
            f"Error: No shard IRI registry found at {registry_path}.",
            err=True,
        )
        sys.exit(1)

    registry = ShardIRIRegistry(registry_path)
    records = _asyncio.run(registry.all_records())

    if not records:
        # all_records() self-bootstraps an empty table on any path, so a
        # misdirected --db (or a genuinely empty registry) would otherwise report
        # "all 0 ... re-mint identically" and exit 0 — a silent pass that verifies
        # nothing. A drift guard with no records to check must fail loud, not green.
        click.echo(
            f"Error: shard IRI registry at {registry_path} contains no records "
            "to verify. Refusing to report success on an empty registry "
            "(check the --db path).",
            err=True,
        )
        sys.exit(1)

    mismatches: list[tuple[str, str, str]] = []  # (stored_iri, reminted_iri, source_uri)
    for rec in records:
        reminted_iri, _ = mint_shard_iri(rec["source_uri"], rec["source_span"])
        reminted_body = reminted_iri.removeprefix("urn:folio:shard/")
        if reminted_body != rec["iri_body"]:
            stored_iri = f"urn:folio:shard/{rec['iri_body']}"
            mismatches.append((stored_iri, reminted_iri, rec["source_uri"]))
            logger.error(
                "verify-iris MISMATCH: stored IRI %s re-mints to %s "
                "from source_uri=%r (source drift or hash-logic regression).",
                stored_iri,
                reminted_iri,
                rec["source_uri"],
            )

    if mismatches:
        click.echo(
            f"verify-iris: {len(mismatches)} of {len(records)} stored IRIs "
            "FAILED re-hash verification:",
            err=True,
        )
        for stored_iri, reminted_iri, source_uri in mismatches:
            click.echo(
                f"  MISMATCH stored={stored_iri} reminted={reminted_iri} "
                f"source_uri={source_uri}",
                err=True,
            )
        click.echo(
            "Surfaced for human review (no auto-quarantine).",
            err=True,
        )
        sys.exit(1)

    click.echo(
        f"verify-iris: all {len(records)} stored shard IRIs re-mint identically."
    )


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

    Launches the interactive review viewer on the specified host and port.
    The viewer provides task tree browsing, review workflows, and export dialogs.
    """
    click.echo(f"Starting review viewer on {host}:{port}")
    click.echo("Press Ctrl+C to stop.")

    from api.main import serve as _serve
    _serve(host=host, port=port)


# Register the Phase 0 bench subgroup on the root cli group (D-14).
# Import at module-bottom is intentional: avoids pulling pyoxigraph at
# `folio-insights --help` time for commands that don't need it.
from folio_insights.bench.cli import bench as _bench_group

cli.add_command(_bench_group)

# Register the Phase 1 polysemy subgroup (PRINCIPLE-06 CLI surface).
# Same module-bottom pattern as bench above.
from folio_insights.polysemy.cli import polysemy as _polysemy_group

cli.add_command(_polysemy_group)

# Register the Phase 6 did subgroup (DID-05 / DID-07 CLI surface).
# Same module-bottom pattern — keeps the crypto/atproto deps off the root
# `folio-insights --help` invocation for commands that don't need them.
from folio_insights.identity.cli import did_group as _did_group

cli.add_command(_did_group)

# Register the Phase 7 governance + corpus subgroups (D-15, D-19; CORPUS-05).
# Same module-bottom pattern — keeps the rdflib/pyshacl deps off the root
# `folio-insights --help` invocation for commands that don't need them.
from folio_insights.governance.cli import governance_group as _governance_group

cli.add_command(_governance_group)

from folio_insights.corpus.cli import corpus_group as _corpus_group

cli.add_command(_corpus_group)

# folio-enrich bridge (plan U4): bridge-ingest + bridge-status. Module-bottom
# pattern, like the groups above.
from folio_insights.bridge_ingest.cli import bridge_ingest_cmd as _bridge_ingest_cmd  # noqa: E402
from folio_insights.bridge_ingest.cli import bridge_status_cmd as _bridge_status_cmd  # noqa: E402

cli.add_command(_bridge_ingest_cmd)
cli.add_command(_bridge_status_cmd)

# Phase 10 U2: durable job queue inspection and the one-time legacy import.
@cli.group("jobs")
def jobs_group() -> None:
    """Durable job queue: list jobs, cancel one, import legacy JSON job files."""


def _open_queue(db: str | None):
    from folio_insights.jobs import SQLiteJobQueue

    return SQLiteJobQueue(db)


@jobs_group.command("list")
@click.option("--db", default=None, help="Queue database (default: $FOLIO_INSIGHTS_QUEUE_DB).")
@click.option("--limit", default=20, show_default=True, type=int)
def jobs_list(db: str | None, limit: int) -> None:
    """List recent jobs (newest first)."""
    queue = _open_queue(db)
    for job in queue.list_jobs(limit=limit):
        reason = f"  reason={' '.join(job.error.split())[:120]}" if job.error else ""
        click.echo(f"{job.id}  {job.kind:<9} {job.status.value:<18} {job.corpus_id}  "
                   f"attempts={job.attempts}/{job.max_attempts}  stage={job.current_stage or '-'}"
                   f"{reason}")


@jobs_group.command("cancel")
@click.argument("job_id")
@click.option("--db", default=None, help="Queue database (default: $FOLIO_INSIGHTS_QUEUE_DB).")
def jobs_cancel(job_id: str, db: str | None) -> None:
    """Cancel a job (immediately if waiting, else at its next stage boundary)."""
    job = _open_queue(db).request_cancel(job_id)
    click.echo(f"{job.id}: {job.status.value}"
               + (" (cancellation requested)" if job.cancel_requested and not job.is_terminal else ""))


@jobs_group.command("expire")
@click.option("--db", default=None, help="Queue database (default: $FOLIO_INSIGHTS_QUEUE_DB).")
@click.option("--ttl", "ttl", default=None, type=float,
              help="Expire paused jobs idle longer than this many seconds "
                   "(default: $FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS, else .env, else 86400).")
def jobs_expire(db: str | None, ttl: float | None) -> None:
    """Cancel abandoned paused jobs (needs_credentials / budget_exhausted) past the TTL.

    Frees a corpus whose paused job can no longer be resumed (lost control token). Running and
    queued jobs are never touched.
    """
    from folio_insights.jobs.worker import parse_paused_ttl, paused_ttl_from_env

    try:
        seconds = paused_ttl_from_env() if ttl is None else parse_paused_ttl(ttl)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    if seconds <= 0:
        click.echo("expiry disabled (ttl <= 0); nothing expired")
        return
    expired = _open_queue(db).expire_paused(ttl_seconds=seconds)
    for job_id in expired:
        click.echo(f"{job_id}: expired")
    click.echo(f"{len(expired)} job(s) expired (ttl={seconds:g}s)")


@jobs_group.command("import-legacy")
@click.option("--jobs-dir", required=True, type=click.Path(exists=True, file_okay=False),
              help="The pre-queue job directory (the API's <output>/.jobs).")
@click.option("--db", default=None, help="Queue database (default: $FOLIO_INSIGHTS_QUEUE_DB).")
def jobs_import_legacy(jobs_dir: str, db: str | None) -> None:
    """One-time import of legacy JSON job files into the queue (idempotent).

    Jobs that were pending or processing were orphaned by a restart and import as failed.
    """
    from folio_insights.jobs.legacy import import_legacy_jobs

    for row in import_legacy_jobs(Path(jobs_dir), _open_queue(db)):
        click.echo(f"{row['file']}: {row['outcome']}")


# Register the Phase 13 storage subgroup (export, dump, snapshot, restore).
# Same module-bottom pattern; the storage package loads only when one of
# its commands runs.
from folio_insights.storage_cli import storage_group as _storage_group  # noqa: E402

cli.add_command(_storage_group)

# Phase 9 U2: framework records (register / list / export).
from folio_insights.frameworks.cli import framework_group as _framework_group  # noqa: E402

cli.add_command(_framework_group)

# Phase 9 U7: BFO typing report.
from folio_insights.bfo.cli import bfo_group as _bfo_group  # noqa: E402

cli.add_command(_bfo_group)

# Phase 9 U5: closed-world-aware counts.
from folio_insights.query.cli import query_group as _query_group  # noqa: E402

cli.add_command(_query_group)

# Drain U3: axiom kernel (list / seed / chain).
from folio_insights.kernel.cli import kernel_group as _kernel_group  # noqa: E402

cli.add_command(_kernel_group)


def main() -> None:
    """Entry point for the folio-insights CLI."""
    cli()


# Drain U4: dependency-cycle validation and Tractarian paths.
from folio_insights.graph_cli import graph_group as _graph_group  # noqa: E402

cli.add_command(_graph_group)

# Drain plan U5: API operator tokens (``folio-insights api token-new``).
from folio_insights.api_cli import api_group as _api_group  # noqa: E402

cli.add_command(_api_group)

# Phase 10 U6: deterministic extraction-quality rubric (rubric score / rubric gold).
from folio_insights.rubric.cli import rubric_group as _rubric_group  # noqa: E402

cli.add_command(_rubric_group)

# Phase 9 U1: cluster validator (`folio-insights validate clusters`; worker tier).
from folio_insights.validation.cli import validate_group as _validate_group  # noqa: E402

cli.add_command(_validate_group)
