"""``folio-insights query count`` (Phase 9 U5): world-assumption-aware counts.

A closure contract is passed on the command line (``--scope`` with
``--closed-class`` / ``--closed-property``); membership is read from the
corpus's ``fi:closedUnder`` triples. Without both halves the answer is open.
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

import click

from folio_insights.governance.cli._state import corpus_root_option, resolve_corpus_root


@click.group(name="query")
def query_group() -> None:
    """Corpus queries with explicit world assumptions."""


@query_group.group(name="count")
def count_group() -> None:
    """Count queries; every result states its world assumption."""


def _scope_options(fn):  # noqa: ANN001, ANN202
    for opt in (
        click.option("--closed-property", "closed_properties", multiple=True,
                     help="Property IRI that is complete inside --scope."),
        click.option("--closed-class", "closed_classes", multiple=True,
                     help="Class IRI that is complete inside --scope."),
        click.option("--scope", "scope", default=None,
                     help="Closed-world scope IRI (the closure contract)."),
        click.option("--corpus", required=True),
        corpus_root_option,
    ):
        fn = opt(fn)
    return fn


def _run(corpus: str, corpus_root: Path | None, scope: str | None,
         classes: tuple[str, ...], props: tuple[str, ...], call) -> None:  # noqa: ANN001
    from folio_insights.query.closed_world import (
        ClosedWorldQuery,
        ClosedWorldScope,
        InvalidIri,
    )
    from folio_insights.storage import CorpusStorageContext
    from folio_insights.storage.journal import JOURNAL_FILENAME, committed_corpora

    root = resolve_corpus_root(corpus_root)
    if corpus not in committed_corpora(root / JOURNAL_FILENAME):
        click.echo(f"query error: no corpus {corpus!r} under {root}", err=True)
        sys.exit(1)

    async def run() -> dict:
        ctx = await CorpusStorageContext.open(root, corpus)
        try:
            scopes = [ClosedWorldScope(scope, frozenset(classes), frozenset(props))] if scope else []
            return asdict(await call(ClosedWorldQuery(ctx, scopes)))
        finally:
            await ctx.close()

    try:
        click.echo(json.dumps(asyncio.run(run()), indent=2))
    except InvalidIri as exc:
        click.echo(f"query error: {exc}", err=True)
        sys.exit(2)


@count_group.command(name="related")
@click.option("--subject", required=True, help="Subject IRI (e.g. a contract).")
@click.option("--property", "prop", required=True, help="Property IRI (e.g. has party).")
@_scope_options
def related_cmd(subject, prop, closed_properties, closed_classes, scope, corpus, corpus_root):  # noqa: ANN001, ANN201
    """Count objects related to SUBJECT by PROPERTY (closed only under fi:closedUnder)."""
    _run(corpus, corpus_root, scope, closed_classes, closed_properties,
         lambda q: q.count_related(subject, prop))


@count_group.command(name="lacking")
@click.option("--class", "cls", required=True, help="Class IRI.")
@click.option("--property", "prop", required=True, help="Property IRI the instances lack.")
@_scope_options
def lacking_cmd(cls, prop, closed_properties, closed_classes, scope, corpus, corpus_root):  # noqa: ANN001, ANN201
    """Count instances of CLASS with no PROPERTY (negation only inside --scope)."""
    if not scope:
        raise click.UsageError("--scope is required for 'lacking'")
    _run(corpus, corpus_root, scope, closed_classes, closed_properties,
         lambda q: q.count_lacking(cls, prop, scope))


__all__ = ["query_group"]
