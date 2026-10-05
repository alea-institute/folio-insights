"""``folio-insights bfo report`` (Phase 9 U7): a corpus's BFO distribution."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from folio_insights.governance.cli._state import corpus_root_option, resolve_corpus_root


@click.group(name="bfo")
def bfo_group() -> None:
    """BFO typing: coverage and distribution reports."""


@bfo_group.command(name="report")
@click.option("--corpus", required=True)
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write the JSON report here (default: stdout).")
@corpus_root_option
def report_cmd(corpus: str, out: Path | None, corpus_root: Path | None) -> None:
    """Per-source distribution over the four BFO categories, with the share of
    documented defaults (coverage excludes defaults)."""
    from folio_insights.bfo.report import corpus_report
    from folio_insights.storage import CorpusStorageContext
    from folio_insights.storage.journal import JOURNAL_FILENAME, committed_corpora

    root = resolve_corpus_root(corpus_root)
    if corpus not in committed_corpora(root / JOURNAL_FILENAME):
        click.echo(f"bfo error: no corpus {corpus!r} under {root}", err=True)
        sys.exit(1)

    async def run() -> dict:
        ctx = await CorpusStorageContext.open(root, corpus)
        try:
            return (await corpus_report(ctx)).as_dict()
        finally:
            await ctx.close()

    text = json.dumps(asyncio.run(run()), indent=2)
    if out is None:
        click.echo(text)
    else:
        out.write_text(text + "\n", encoding="utf-8")
        click.echo(str(out))


__all__ = ["bfo_group"]
