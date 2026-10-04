"""``folio-insights storage`` operator commands (Phase 13 U4).

Lives outside the ``storage`` package so registering the group does not
import the storage package (journal, projection, process pool) at
``folio-insights --help`` time; each command imports what it needs.

* ``storage export CORPUS --out DIR``  — the eight Phase 13 export formats.
* ``storage dump --repo DIR``           — TTL dump + local Git commit (the
  nightly job's entry point; scheduling and pushing are not done here).
* ``storage snapshot --out DIR``        — journal + projection snapshot.
* ``storage restore SNAPSHOT --to DIR`` — restore into a NEW storage root.
* ``storage status CORPUS``             — journal head, watermark, SHACL status.

These are operator commands over a storage root on the local filesystem
(``--corpus-root``, else ``$FOLIO_INSIGHTS_CORPUS_ROOT``, else
``~/.folio-insights/corpora``). They do not sign anything and do not change
governance state; per-corpus access policy for exports arrives with Phase
13.5 (private corpora).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from folio_insights.governance.cli._state import corpus_root_option, resolve_corpus_root


def _run(coro):  # noqa: ANN001, ANN202
    from folio_insights.storage import OperationIdConflict, StorageError
    from folio_insights.storage.backup import RestoreRefused
    from folio_insights.storage.exports import ExportRefused

    try:
        return asyncio.run(coro)
    except (StorageError, OperationIdConflict, ExportRefused, RestoreRefused) as exc:
        click.echo(f"storage error: {type(exc).__name__}: {exc}", err=True)
        sys.exit(1)


@click.group(name="storage")
def storage_group() -> None:
    """Persistent storage operations: export, dump, snapshot, restore."""


@storage_group.command(name="export")
@click.argument("corpus_name")
@click.option("--out", "out", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="New (or empty) destination directory.")
@click.option("--format", "formats", multiple=True,
              type=click.Choice([
                  "combined.ttl", "abox", "tbox.ttl", "governance.ttl",
                  "jsonld", "construct", "nquads", "neo4j",
              ]),
              help="Formats to write (repeatable). Default: all but construct.")
@click.option("--construct-query", default=None, help="SPARQL CONSTRUCT for --format construct.")
@click.option("--construct-file", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="File holding the SPARQL CONSTRUCT query.")
@click.option("--allow-partial", is_flag=True,
              help="Accept a CONSTRUCT subset that drops identity/signature triples.")
@click.option("--require-named-graphs", is_flag=True,
              help="Refuse formats that cannot carry graph membership.")
@corpus_root_option
def export_cmd(
    corpus_name: str,
    out: Path,
    formats: tuple[str, ...],
    construct_query: str | None,
    construct_file: Path | None,
    allow_partial: bool,
    require_named_graphs: bool,
    corpus_root: Path | None,
) -> None:
    """Export CORPUS_NAME in the Phase 13 formats (verified round trips)."""
    from folio_insights.storage import CorpusStorageContext
    from folio_insights.storage.exports import ALL_FORMATS, export_corpus

    if construct_file is not None:
        construct_query = construct_file.read_text(encoding="utf-8")

    async def run() -> None:
        ctx = await CorpusStorageContext.open(resolve_corpus_root(corpus_root), corpus_name)
        try:
            result = await export_corpus(
                ctx,
                out,
                list(formats) or list(ALL_FORMATS),
                construct_query=construct_query,
                allow_partial=allow_partial,
                require_named_graphs=require_named_graphs,
            )
        finally:
            await ctx.close()
        click.echo(json.dumps({
            "destination": str(result.destination),
            "watermark": result.manifest["watermark"],
            "formats": {k: [f["path"] for f in v["files"]]
                        for k, v in result.manifest["formats"].items()},
        }, indent=2))

    _run(run())


@storage_group.command(name="dump")
@click.option("--repo", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Dedicated dump Git repository (its own work tree).")
@click.option("--corpus", "corpora", multiple=True, help="Corpus to dump (default: all).")
@click.option("--init", is_flag=True, help="Create / git-init the dump repository if needed.")
@corpus_root_option
def dump_cmd(repo: Path, corpora: tuple[str, ...], init: bool, corpus_root: Path | None) -> None:
    """Write a TTL dump of every corpus and commit it locally (nightly job).

    Scheduling (systemd timer / cron) and pushing the repository are left to
    the operator.
    """
    from folio_insights.storage.dump import run_ttl_dump

    result = _run(run_ttl_dump(resolve_corpus_root(corpus_root), repo,
                               corpora=list(corpora) or None, init=init))
    click.echo(json.dumps({
        "repo": str(result.repo),
        "corpora": result.corpora,
        "changed": result.changed,
        "commit": result.commit,
    }, indent=2))


@storage_group.command(name="snapshot")
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="New snapshot directory (must not exist).")
@click.option("--no-projection", is_flag=True,
              help="Journal only; a restore rebuilds the projection.")
@corpus_root_option
def snapshot_cmd(out: Path, no_projection: bool, corpus_root: Path | None) -> None:
    """Snapshot the storage root (journal backup + projection backup)."""
    from folio_insights.storage.backup import snapshot_storage

    result = _run(snapshot_storage(resolve_corpus_root(corpus_root), out,
                                   include_projection=not no_projection))
    click.echo(json.dumps({"snapshot": str(result.path),
                           "corpora": result.manifest["corpora"]}, indent=2))


@storage_group.command(name="restore")
@click.argument("snapshot", type=click.Path(file_okay=False, exists=True, path_type=Path))
@click.option("--to", "to", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="NEW storage root to restore into (must not exist).")
@click.option("--rebuild-projection", is_flag=True,
              help="Rebuild the projection from the journal instead of copying it.")
def restore_cmd(snapshot: Path, to: Path, rebuild_projection: bool) -> None:
    """Restore SNAPSHOT into a new storage root, verified before it appears."""
    from folio_insights.storage.backup import restore_storage

    result = _run(restore_storage(snapshot, to, rebuild_projection=rebuild_projection))
    click.echo(json.dumps({"restored": str(result.path), "corpora": result.corpora,
                           "projection": result.projection}, indent=2))


@storage_group.command(name="status")
@click.argument("corpus_name")
@corpus_root_option
def status_cmd(corpus_name: str, corpus_root: Path | None) -> None:
    """Journal head, projection watermark and the Phase 11 SHACL status."""
    from folio_insights.storage import CorpusStorageContext

    async def run() -> None:
        ctx = await CorpusStorageContext.open(resolve_corpus_root(corpus_root), corpus_name)
        try:
            status = await ctx.status()
        finally:
            await ctx.close()
        click.echo(json.dumps(status.__dict__, indent=2, default=str))

    _run(run())


__all__ = ["storage_group"]
