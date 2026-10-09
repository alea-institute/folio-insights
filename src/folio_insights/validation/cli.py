"""``folio-insights validate clusters`` (Phase 9 U1, R4): the cluster validator CLI.

A worker-tier entry point. The command reads one corpus (its current shards
and framework registry), optionally a discovery task tree, a TBox file,
disjointness seeds and a FOLIO ancestry map, and prints the cluster report as
JSON (default) or text. It never writes to the corpus: proposals are report
data only.

HermiT runs only where owlready2 and a Java runtime exist (the worker image);
elsewhere the report says the reasoner is unavailable and every cluster falls
back to the NLI screen. The heavy modules (``validation.validator``,
``validation.consistency``, the NLI model) load inside the command, so
registering this group in ``folio_insights.cli`` costs the web tier nothing.

Exit status: 0 when the run completes (CI runs it warn-only), 1 with
``--fail-on-findings`` when a ``warning`` finding exists, 2 when the corpus or
an input file cannot be read.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import click

from folio_insights.governance.cli._state import corpus_root_option, resolve_corpus_root
from folio_insights.validation.clusters import CLUSTER_AXES, DEFAULT_DOCTRINAL_DEPTH


def load_tbox_triples(path: Path) -> list[tuple[str, str, str]]:
    """IRI / blank-node triples of an RDF file (format from its extension).
    Literal-valued triples are dropped; the formal check never uses them."""
    from pyoxigraph import BlankNode, Literal, NamedNode, parse

    def term(node: Any) -> str | None:
        if isinstance(node, NamedNode):
            return node.value
        if isinstance(node, BlankNode):
            return f"_:{node.value}"
        if isinstance(node, Literal):
            return None
        return None

    out: list[tuple[str, str, str]] = []
    for item in parse(path=str(path)):
        s, p, o = term(item.subject), term(item.predicate), term(item.object)
        if s is not None and p is not None and o is not None:
            out.append((s, p, o))
    return out


def load_parent_map(path: Path) -> dict[str, list[str]]:
    """A FOLIO ancestry map ``{iri: [parent iri, ...]}`` from JSON."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v)
        for k, v in data.items()
    ):
        raise ValueError(f"{path}: expected a JSON object of IRI -> list of parent IRIs")
    return data


@click.group(name="validate")
def validate_group() -> None:
    """Validation over stored shards (cluster-level checks)."""


@validate_group.command(name="clusters")
@click.option("--corpus", required=True, help="Corpus to validate.")
@corpus_root_option
@click.option("--tasks", "tasks_path", type=click.Path(dir_okay=False, path_type=Path),
              default=None, help="Discovery task tree (task_tree.json or discovery.json) "
              "for the coverage check; without it coverage is skipped.")
@click.option("--folio-parents", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="JSON map of FOLIO IRI -> parent IRIs (doctrinal axis and coverage ancestry).")
@click.option("--doctrinal-depth", type=click.IntRange(min=0), default=DEFAULT_DOCTRINAL_DEPTH,
              show_default=True, help="Depth below the FOLIO roots of the shared ancestor.")
@click.option("--axis", "axes", type=click.Choice(CLUSTER_AXES), multiple=True,
              help="Cluster axes to build (repeatable; default: all four).")
@click.option("--min-size", type=click.IntRange(min=1), default=2, show_default=True)
@click.option("--tbox", "tbox_path", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="TBox RDF file (Turtle, N-Triples, RDF/XML ...) for the formal check.")
@click.option("--disjoint", "disjoint", type=(str, str), multiple=True,
              help="Two class IRIs asserted owl:disjointWith (repeatable).")
@click.option("--hermit/--no-hermit", default=True, show_default=True,
              help="Run HermiT where available (worker image).")
@click.option("--nli/--no-nli", default=True, show_default=True,
              help="Run the NLI textual screen (loads the cross-encoder model).")
@click.option("--nli-threshold", type=click.FloatRange(min=0.0, max=1.0, min_open=True),
              default=0.7, show_default=True)
@click.option("--allow-framework-pair", "allowed_pairs", type=(str, str), multiple=True,
              help="Two framework IDs that may cite each other (repeatable).")
@click.option("--coverage/--no-coverage", default=True, show_default=True)
@click.option("--crossref/--no-crossref", default=True, show_default=True)
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="json",
              show_default=True)
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write the report here (default: stdout).")
@click.option("--fail-on-findings", is_flag=True, default=False,
              help="Exit 1 when any warning-level finding exists (default: warn-only).")
def clusters_cmd(
    corpus: str,
    corpus_root: Path | None,
    tasks_path: Path | None,
    folio_parents: Path | None,
    doctrinal_depth: int,
    axes: tuple[str, ...],
    min_size: int,
    tbox_path: Path | None,
    disjoint: tuple[tuple[str, str], ...],
    hermit: bool,
    nli: bool,
    nli_threshold: float,
    allowed_pairs: tuple[tuple[str, str], ...],
    coverage: bool,
    crossref: bool,
    fmt: str,
    out: Path | None,
    fail_on_findings: bool,
) -> None:
    """Cluster-level validation of CORPUS: contradictions, coverage gaps and
    cross-framework citations, with proposed reconciliations (never applied)."""
    from folio_insights.bfo.spine import ParentMapResolver
    from folio_insights.storage import CorpusStorageContext
    from folio_insights.storage.journal import JOURNAL_FILENAME, committed_corpora
    from folio_insights.validation import nli as nli_module
    from folio_insights.validation.coverage import load_task_nodes
    from folio_insights.validation.validator import validate_corpus

    root = resolve_corpus_root(corpus_root)
    if corpus not in committed_corpora(root / JOURNAL_FILENAME):
        click.echo(f"validate error: no corpus {corpus!r} under {root}", err=True)
        sys.exit(2)
    try:
        tasks = load_task_nodes(tasks_path) if tasks_path is not None else None
        resolver = ParentMapResolver(load_parent_map(folio_parents)) if folio_parents else None
        tbox = load_tbox_triples(tbox_path) if tbox_path is not None else []
    except (OSError, ValueError) as exc:
        click.echo(f"validate error: {exc}", err=True)
        sys.exit(2)

    options: dict[str, Any] = {
        "folio_resolver": resolver,
        "doctrinal_depth": doctrinal_depth,
        "axes": axes or CLUSTER_AXES,
        "min_size": min_size,
        "reasoner": "auto" if hermit else None,
        "nli": nli_module.default_nli_scorer() if nli else None,
        "nli_threshold": nli_threshold,
        "tbox": tbox,
        "disjoint_seeds": list(disjoint),
        "coverage": coverage,
        "crossref": crossref,
        "allowed_framework_pairs": list(allowed_pairs),
    }

    async def run():
        ctx = await CorpusStorageContext.open(root, corpus)
        try:
            return await validate_corpus(ctx, tasks=tasks, **options)
        finally:
            await ctx.close()

    report = asyncio.run(run())
    text = report.to_json() + "\n" if fmt == "json" else report.render_text()
    if out is None:
        click.echo(text, nl=False)
    else:
        out.write_text(text, encoding="utf-8")
        click.echo(str(out))
    if fail_on_findings and any(f.severity == "warning" for f in report.findings):
        sys.exit(1)


__all__ = ["clusters_cmd", "load_parent_map", "load_tbox_triples", "validate_group"]
