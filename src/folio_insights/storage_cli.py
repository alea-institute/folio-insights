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
* ``storage validate CORPUS``           — full Phase 11 SHACL validation;
  records the result (``full_shacl`` pass/fail) and exits 1 on Violations.

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


def _open_existing(corpus_root: Path | None, corpus: str):  # noqa: ANN202
    """Open a corpus that already has committed rows; never create one."""
    from folio_insights.storage import CorpusStorageContext, StorageConfig
    from folio_insights.storage.journal import JOURNAL_FILENAME, committed_corpora

    root = resolve_corpus_root(corpus_root)
    if corpus not in committed_corpora(root / JOURNAL_FILENAME):
        click.echo(f"storage error: no corpus {corpus!r} under {root}", err=True)
        sys.exit(1)
    # The CLI entry point is __main__-guarded, so the process pool is safe here.
    return CorpusStorageContext.open(root, corpus, config=StorageConfig(process_pool=True))


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
@click.option("--tbox-profile", type=click.Choice(["EL", "DL"]), default=None,
              help="TBox profile (default EL): an axiom outside OWL 2 EL refuses the export.")
@click.option("--expressive", is_flag=True,
              help="Export the TBox as OWL 2 DL (adds the expressive layer; "
                   "non-EL axioms become a warning). Same as --tbox-profile DL.")
@corpus_root_option
def export_cmd(
    corpus_name: str,
    out: Path,
    formats: tuple[str, ...],
    construct_query: str | None,
    construct_file: Path | None,
    allow_partial: bool,
    require_named_graphs: bool,
    tbox_profile: str | None,
    expressive: bool,
    corpus_root: Path | None,
) -> None:
    """Export CORPUS_NAME in the Phase 13 formats (verified round trips)."""
    from folio_insights.storage.exports import ALL_FORMATS, export_corpus

    if expressive and tbox_profile == "EL":
        raise click.UsageError("--expressive conflicts with --tbox-profile EL")

    if construct_file is not None:
        construct_query = construct_file.read_text(encoding="utf-8")

    async def run() -> None:
        ctx = await _open_existing(corpus_root, corpus_name)
        try:
            result = await export_corpus(
                ctx,
                out,
                list(formats) or list(ALL_FORMATS),
                construct_query=construct_query,
                allow_partial=allow_partial,
                require_named_graphs=require_named_graphs,
                tbox_profile=tbox_profile,  # type: ignore[arg-type]
                expressive=expressive,
            )
        finally:
            await ctx.close()
        profile = result.manifest["tbox_profile"]
        for warning in profile["warnings"]:
            click.echo(f"warning: {warning}", err=True)
            for violation in profile["el_violations"]:
                click.echo(f"  - {violation['constraint']}: {violation['triples'][0]}", err=True)
        click.echo(json.dumps({
            "destination": str(result.destination),
            "tbox_profile": profile["profile"],
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
@click.option("--use-snapshot-projection", is_flag=True,
              help="Copy the snapshot's projection (after per-file digest checks) instead "
                   "of rebuilding it from the journal (the default).")
def restore_cmd(snapshot: Path, to: Path, use_snapshot_projection: bool) -> None:
    """Restore SNAPSHOT into a new storage root, checked before it appears.

    The projection is rebuilt from the restored journal unless
    --use-snapshot-projection is given. The snapshot manifest is not signed:
    keep snapshots where only the operator can write.
    """
    from folio_insights.storage.backup import restore_storage

    result = _run(restore_storage(snapshot, to, rebuild_projection=not use_snapshot_projection,
                                  process_pool=True))
    click.echo(json.dumps({"restored": str(result.path), "corpora": result.corpora,
                           "projection": result.projection}, indent=2))


@storage_group.command(name="status")
@click.argument("corpus_name")
@corpus_root_option
def status_cmd(corpus_name: str, corpus_root: Path | None) -> None:
    """Journal head, projection watermark and the Phase 11 SHACL status."""
    async def run() -> None:
        ctx = await _open_existing(corpus_root, corpus_name)
        try:
            status = await ctx.status()
        finally:
            await ctx.close()
        click.echo(json.dumps(status.__dict__, indent=2, default=str))

    _run(run())


@storage_group.command(name="validate")
@click.argument("corpus_name")
@click.option("--engine", type=click.Choice(["compiled", "pyshacl"]), default="compiled",
              show_default=True,
              help="Local-tier engine: the compiled write-path engine or the pyshacl reference.")
@click.option("--max-results", type=int, default=50, show_default=True,
              help="How many Violation results to print (all are counted).")
@corpus_root_option
def validate_cmd(corpus_name: str, engine: str, max_results: int, corpus_root: Path | None) -> None:
    """Validate every shard and governance event against the full SHACL suite.

    Records the result so `storage status` reports full_shacl pass or fail.
    Exits 1 when any Violation is found (Warnings are counted, never fatal).
    """
    async def run() -> bool:
        ctx = await _open_existing(corpus_root, corpus_name)
        try:
            result = await ctx.validate_corpus(engine=engine, parallel=True)
        finally:
            await ctx.close()
        out = result.as_dict()
        out["results"] = out["results"][: max(0, max_results)]
        click.echo(json.dumps(out, indent=2, default=str))
        return result.conforms

    if not _run(run()):
        sys.exit(1)


__all__ = ["storage_group"]
