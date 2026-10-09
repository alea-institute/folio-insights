"""``folio-insights graph`` — the dependency web and Tractarian paths (drain U4).

* ``graph validate CORPUS [--json]`` — every cycle stored in the corpus's
  dependency web (the four ``depends_on_*`` lists plus ``elaborates``), as
  ``A -> B -> A``; exits 1 when any exists. New writes cannot add one while
  ``StorageConfig.refuse_dependency_cycles`` is on (the default), so a
  finding here is a legacy cycle written before the guard or with it off.
* ``graph path CORPUS IRI`` — the shard's Tractarian path and IRI; exits 1
  when the IRI is not a shard of the corpus.
* ``graph tree CORPUS [--json]`` — every shard's path beside its IRI in path
  order (``--json``: the nested tree plus its findings).

Paths are display identifiers derived from the journal (``revision/
tractarian.py``); the content-hash URN stays the shard's identity. Like the
``storage`` group this module lives outside the storage package and imports
it only when a command runs; it reads a corpus that already has committed
rows under ``--corpus-root`` (else ``$FOLIO_INSIGHTS_CORPUS_ROOT``, else
``~/.folio-insights/corpora``) and never creates one or writes to it.
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

import click

from folio_insights.governance.cli._state import corpus_root_option, resolve_corpus_root

if TYPE_CHECKING:
    from folio_insights.storage import CorpusStorageContext

T = TypeVar("T")


def _with_corpus(
    corpus_root: Path | None,
    corpus: str,
    read: Callable[[CorpusStorageContext], Awaitable[T]],
) -> T:
    """Open an existing corpus, run ``read``, always close; storage failures
    exit 1 with a one-line message (never a traceback)."""
    from folio_insights.storage import CorpusStorageContext, StorageError
    from folio_insights.storage.journal import JOURNAL_FILENAME, committed_corpora

    root = resolve_corpus_root(corpus_root)
    if corpus not in committed_corpora(root / JOURNAL_FILENAME):
        click.echo(f"graph error: no corpus {corpus!r} under {root}", err=True)
        sys.exit(1)

    async def run() -> T:
        ctx = await CorpusStorageContext.open(root, corpus)
        try:
            return await read(ctx)
        finally:
            await ctx.close()

    try:
        return asyncio.run(run())
    except StorageError as exc:
        click.echo(f"graph error: {type(exc).__name__}: {exc}", err=True)
        sys.exit(1)


@click.group(name="graph")
def graph_group() -> None:
    """Dependency-web checks and Tractarian path identifiers."""


@graph_group.command(name="validate")
@click.argument("corpus_name")
@corpus_root_option
@click.option("--json", "as_json", is_flag=True, help="Print a JSON report.")
def validate_cmd(corpus_name: str, corpus_root: Path | None, as_json: bool) -> None:
    """Report every stored dependency cycle (elaborates included); exit 1 if any."""
    from folio_insights.revision.dependency_graph import DependencyGraph

    async def read(ctx: CorpusStorageContext) -> DependencyGraph:
        return await DependencyGraph.from_store(ctx.shards, include_elaborates=True)

    graph = _with_corpus(corpus_root, corpus_name, read)
    cycles = [[*cycle, cycle[0]] for cycle in graph.cycles()]
    if as_json:
        click.echo(json.dumps({
            "corpus": corpus_name,
            "nodes": graph.node_count,
            "edges": graph.edge_count,
            "acyclic": not cycles,
            "cycles": [" -> ".join(c) for c in cycles],
        }, indent=2))
    else:
        for cycle in cycles:
            click.echo(f"cycle: {' -> '.join(cycle)}")
        verdict = "acyclic" if not cycles else f"{len(cycles)} cycle(s)"
        click.echo(
            f"{corpus_name}: {verdict} ({graph.node_count} nodes, {graph.edge_count} edges)"
        )
    if cycles:
        sys.exit(1)


@graph_group.command(name="path")
@click.argument("corpus_name")
@click.argument("iri")
@corpus_root_option
def path_cmd(corpus_name: str, iri: str, corpus_root: Path | None) -> None:
    """Print IRI's Tractarian path beside the IRI."""
    from folio_insights.revision.tractarian import TractarianIndex

    index = _with_corpus(corpus_root, corpus_name, TractarianIndex.from_context)
    path = index.path_of(iri)
    if path is None:
        click.echo(f"graph error: {iri!r} is not a shard of corpus {corpus_name!r}", err=True)
        sys.exit(1)
    click.echo(f"{path}\t{iri}")


@graph_group.command(name="tree")
@click.argument("corpus_name")
@corpus_root_option
@click.option("--json", "as_json", is_flag=True, help="Print the nested tree as JSON.")
def tree_cmd(corpus_name: str, corpus_root: Path | None, as_json: bool) -> None:
    """Print every shard's Tractarian path beside its IRI, in path order."""
    from folio_insights.revision.tractarian import TractarianIndex

    index = _with_corpus(corpus_root, corpus_name, TractarianIndex.from_context)
    if as_json:
        click.echo(json.dumps({
            "corpus": corpus_name,
            "shards": len(index),
            "tree": index.tree(),
            "findings": [f.as_dict() for f in index.findings],
        }, indent=2))
        return
    for node in index.nodes():
        click.echo(f"{'  ' * (node.depth - 1)}{node.path}\t{node.iri}")
    for finding in index.findings:
        click.echo(f"finding: {finding.kind}: {finding.detail}", err=True)


__all__ = ["graph_group"]
