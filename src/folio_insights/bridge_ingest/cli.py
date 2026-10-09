"""``folio-insights bridge-ingest`` and ``folio-insights bridge-status``."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import click

from folio_insights.governance.cli._state import corpus_root_option, resolve_corpus_root


@click.command("bridge-ingest")
@click.argument("record_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--corpus", "corpus", required=True, help="Target corpus name.")
@corpus_root_option
@click.option("--framework-id", default="us.case-law.unspecified", show_default=True,
              help="Envelope framework_id for every shard.")
@click.option("--extractor-did", default=None,
              help="first_extractor_did (default: $FOLIO_INSIGHTS_BRIDGE_EXTRACTOR_DID, "
                   "else did:web:folio-enrich.local).")
@click.option("--op-id", default=None, help="Explicit operation ID (default: derived).")
@click.option("--json", "as_json", is_flag=True, help="Print the report as JSON.")
def bridge_ingest_cmd(
    record_path: Path,
    corpus: str,
    corpus_root: Path | None,
    framework_id: str,
    extractor_did: str | None,
    op_id: str | None,
    as_json: bool,
) -> None:
    """Ingest a folio-enrich proposition export (JSON or NDJSON) as hypothesis shards."""
    from folio_insights.bridge_ingest.errors import BridgeIngestError
    from folio_insights.bridge_ingest.ingest import ingest_record
    from folio_insights.bridge_ingest.mapping import DEFAULT_EXTRACTOR_DID
    from folio_insights.storage.errors import StorageError

    did = extractor_did or os.environ.get("FOLIO_INSIGHTS_BRIDGE_EXTRACTOR_DID") or DEFAULT_EXTRACTOR_DID
    try:
        report = asyncio.run(
            ingest_record(
                record_path,
                corpus_root=resolve_corpus_root(corpus_root),
                corpus=corpus,
                framework_id=framework_id,
                extractor_did=did,
                op_id=op_id,
            )
        )
    except (BridgeIngestError, StorageError) as exc:
        click.echo(f"bridge-ingest refused: {type(exc).__name__}: {exc}", err=True)
        sys.exit(1)
    if as_json:
        click.echo(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
        return
    click.echo(
        f"corpus {report.corpus}: document {report.document_id}: "
        f"created {report.created}, existing {report.existing}, "
        f"skipped {report.skipped}, refused {report.refused}"
    )
    for refused in report.refused_shards:
        click.echo(f"  refused {refused.iri}: {refused.reason}")
    for skipped in report.skipped_propositions:
        click.echo(f"  skipped {skipped.proposition_id}: {skipped.reason}")
    if report.refused:
        sys.exit(2)


@click.command("bridge-status")
@click.argument("iris", nargs=-1, required=True)
@click.option("--corpus", "corpus", required=True, help="Corpus name.")
@corpus_root_option
def bridge_status_cmd(iris: tuple[str, ...], corpus: str, corpus_root: Path | None) -> None:
    """Print the bridge status (JSON) of one or more shard IRIs."""
    from folio_insights.bridge_ingest.status import normalize_iris, shard_status
    from folio_insights.storage import CorpusStorageContext
    from folio_insights.storage.journal import JOURNAL_FILENAME, committed_corpora

    try:
        wanted = normalize_iris(list(iris))
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="IRIS") from None
    root = resolve_corpus_root(corpus_root)
    if corpus not in committed_corpora(root / JOURNAL_FILENAME):
        click.echo(f"bridge-status: no corpus {corpus!r} in the storage root", err=True)
        sys.exit(1)

    async def run() -> list[dict]:
        ctx = await CorpusStorageContext.open(root, corpus)
        try:
            return [r.model_dump(mode="json") for r in await shard_status(ctx, wanted)]
        finally:
            await ctx.close()

    click.echo(json.dumps({"corpus": corpus, "results": asyncio.run(run())}, indent=2))


__all__ = ["bridge_ingest_cmd", "bridge_status_cmd"]
