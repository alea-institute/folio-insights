"""Signed closure declaration and world-assumption-aware count commands.

Stored declarations supply the contract. Optional class/property flags restrict it;
they cannot establish closure on their own or broaden the stored declaration.
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


@query_group.command(name="declare")
@click.option("--corpus", required=True)
@corpus_root_option
@click.option("--declaration", "declaration_path", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Corpus-admin signed closure declaration JSON.")
@click.option("--op-id", help="Must equal the operation ID in the signed artifact.")
def declare_cmd(corpus: str, corpus_root: Path | None,
                declaration_path: Path, op_id: str | None) -> None:
    """Persist an explicit signed closure contract; no key is loaded or created."""
    from pydantic import ValidationError

    from folio_insights.closure.declarations import ClosureDeclaration, submit_declaration
    from folio_insights.storage import CorpusStorageContext
    from folio_insights.storage.errors import ProjectionRecoveryPending
    from folio_insights.storage.journal import JOURNAL_FILENAME, committed_corpora

    try:
        declaration = ClosureDeclaration.model_validate_json(
            declaration_path.read_text(encoding="utf-8")
        )
    except (ValidationError, OSError):
        raise click.ClickException("invalid or unreadable closure declaration artifact") from None
    if declaration.corpus != corpus or (op_id is not None and op_id != declaration.op_id):
        raise click.ClickException("selected corpus or operation ID does not match the signed artifact")
    root = resolve_corpus_root(corpus_root)
    if corpus not in committed_corpora(root / JOURNAL_FILENAME):
        raise click.ClickException("the selected corpus does not exist")

    async def run() -> dict:
        async with await CorpusStorageContext.open(root, corpus) as ctx:
            entry = await submit_declaration(ctx, declaration, op_id=op_id)
            return {"status": "committed", "op_id": entry.op_id, "ledger_position": entry.position}

    try:
        click.echo(json.dumps(asyncio.run(run()), indent=2))
    except ProjectionRecoveryPending:
        raise click.ClickException(
            "declaration committed; projection recovery pending. Reopen and retry the same artifact"
        ) from None
    except ValueError as exc:
        raise click.ClickException(f"closure declaration refused: {exc}") from None


@query_group.group(name="count")
def count_group() -> None:
    """Count queries; every result states its world assumption."""


def _scope_options(fn):  # noqa: ANN001, ANN202
    for opt in (
        click.option("--closed-property", "closed_properties", multiple=True,
                     help="Restrict --scope to this stored closed property."),
        click.option("--closed-class", "closed_classes", multiple=True,
                     help="Restrict --scope to this stored closed class."),
        click.option("--scope", "scope", default=None,
                     help="Restrict the query to this persisted closure scope IRI."),
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
    if (classes or props) and not scope:
        raise click.UsageError("--scope is required with closure restrictions")
    if corpus not in committed_corpora(root / JOURNAL_FILENAME):
        click.echo(f"query error: no corpus {corpus!r} under {root}", err=True)
        sys.exit(1)

    async def run() -> dict:
        ctx = await CorpusStorageContext.open(root, corpus)
        try:
            restriction = ClosedWorldScope(scope, frozenset(classes), frozenset(props)) if scope else None
            snapshot = await ctx.closed_world_snapshot()
            scopes = [ClosedWorldScope(
                stored.scope_iri,
                stored.closed_classes & restriction.closed_classes if classes else stored.closed_classes,
                stored.closed_properties & restriction.closed_properties if props else stored.closed_properties,
            ) for stored in snapshot.scopes if restriction is None or stored.scope_iri == restriction.scope_iri]
            return asdict(await call(ClosedWorldQuery(snapshot.runner, scopes)))
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
