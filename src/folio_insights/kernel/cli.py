"""``folio-insights kernel list|seed|chain`` (drain U3, R9-R11).

* ``list`` — the packaged kernel catalog (verified maxims with citation, IRI
  and provenance), as text or JSON. Needs no corpus.
* ``seed`` — write the kernel into an existing corpus, signed by a corpus
  admin's key (``--signing-key``): registers the two collection frameworks if
  the corpus lacks them, then ingests every missing maxim. Idempotent.
* ``chain`` — export a shard's derivation chain to the kernel as JSON or
  Turtle.

Corpus storage resolves like the other corpus CLIs (``--corpus-root``, alias
``--root``; else ``$FOLIO_INSIGHTS_CORPUS_ROOT``; else
``~/.folio-insights/corpora``), and no command creates a corpus.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from folio_insights.governance.cli._state import CORPUS_ROOT_ENV, resolve_corpus_root

kernel_root_option = click.option(
    "--corpus-root",
    "--root",
    "corpus_root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help=(
        "Persistent corpus storage root (journal + RDF projection). Default: "
        f"${CORPUS_ROOT_ENV}, else ~/.folio-insights/corpora."
    ),
)


def _existing_root(corpus_root: Path | None, corpus: str) -> Path:
    from folio_insights.storage.journal import JOURNAL_FILENAME, committed_corpora

    root = resolve_corpus_root(corpus_root)
    if corpus not in committed_corpora(root / JOURNAL_FILENAME):
        click.echo(f"kernel error: no corpus {corpus!r} under {root}", err=True)
        sys.exit(1)
    return root


def _emit(text: str, out: Path | None) -> None:
    if out is None:
        click.echo(text, nl=not text.endswith("\n"))
    else:
        out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        click.echo(str(out))


@click.group(name="kernel")
def kernel_group() -> None:
    """Axiom kernel: the packaged regulae iuris, seeding and derivation chains."""


@kernel_group.command(name="list")
@click.option("--collection", type=click.Choice(["liber_sextus", "digest"]), default=None,
              help="Only this collection.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON (maxims, counts, exclusions).")
def list_cmd(collection: str | None, as_json: bool) -> None:
    """List the verified kernel maxims (citation, shard IRI, provenance)."""
    from folio_insights.kernel.catalog import load_catalog

    catalog = load_catalog()
    maxims = catalog.collection(collection) if collection else catalog.maxims
    excluded = [e for e in catalog.excluded if collection in (None, e.collection)]
    if as_json:
        counts = catalog.counts()
        payload = {
            "counts": {k: v for k, v in counts.items() if collection in (None, k)},
            "maxims": [m.as_dict() for m in maxims],
            "excluded": [
                {"collection": e.collection, "number": e.number, "citation": e.citation,
                 "reason": e.reason}
                for e in excluded
            ],
        }
        click.echo(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
        return
    for m in maxims:
        flag = "" if m.provenance.cross_checked else "  [single source]"
        click.echo(f"{m.citation}\t{m.shard_iri}\t{m.latin}{flag}")
    single = sum(1 for m in maxims if not m.provenance.cross_checked)
    click.echo(f"{len(maxims)} verified maxims ({single} single-source, "
               f"{len(excluded)} excluded)", err=True)


@kernel_group.command(name="seed")
@click.argument("corpus")
@click.option("--signing-key", "signing_key_path", required=True,
              type=click.Path(dir_okay=False, path_type=Path),
              help="Ed25519 JWK keyfile of a corpus admin (mode 0600).")
@click.option("--collection", "collections", multiple=True,
              type=click.Choice(["liber_sextus", "digest"]),
              help="Seed only this collection (repeatable; default: both).")
@kernel_root_option
def seed_cmd(
    corpus: str, signing_key_path: Path, collections: tuple[str, ...], corpus_root: Path | None
) -> None:
    """Seed the kernel into CORPUS (idempotent; corpus admins only)."""
    from folio_insights.frameworks.registry import FrameworkRegistrationRefused
    from folio_insights.identity.keys import load_signing_key
    from folio_insights.kernel.seed import KernelSeedError, seed_kernel

    root = _existing_root(corpus_root, corpus)
    try:
        signing_key = load_signing_key(signing_key_path)
    except FileNotFoundError:
        click.echo(f"kernel error: no signing key at {signing_key_path}", err=True)
        sys.exit(1)
    except PermissionError as exc:
        click.echo(f"kernel error: {exc}", err=True)
        sys.exit(1)
    try:
        report = asyncio.run(seed_kernel(
            root, corpus, signing_key=signing_key,
            collections=collections or ("liber_sextus", "digest"),
        ))
    except (FrameworkRegistrationRefused, KernelSeedError) as exc:
        click.echo(f"seed refused: {exc}", err=True)
        sys.exit(1)
    click.echo(json.dumps(report.as_dict(), indent=2, sort_keys=True))


@kernel_group.command(name="chain")
@click.argument("corpus")
@click.argument("iri")
@click.option("--format", "fmt", type=click.Choice(["json", "ttl"]), default="json",
              show_default=True)
@click.option("--max-depth", type=click.IntRange(min=0), default=32, show_default=True,
              help="Maximum number of derivation hops to walk.")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write the export here (default: stdout).")
@kernel_root_option
def chain_cmd(
    corpus: str, iri: str, fmt: str, max_depth: int, out: Path | None, corpus_root: Path | None
) -> None:
    """Export IRI's derivation chain to the kernel (JSON or Turtle)."""
    from folio_insights.kernel.export import chain_to_json, chain_to_turtle
    from folio_insights.kernel.traversal import UnknownShard, derivation_tree
    from folio_insights.storage import CorpusStorageContext

    root = _existing_root(corpus_root, corpus)

    async def run():  # noqa: ANN202
        ctx = await CorpusStorageContext.open(root, corpus)
        try:
            return await derivation_tree(ctx, iri, max_depth=max_depth)
        finally:
            await ctx.close()

    try:
        tree = asyncio.run(run())
    except UnknownShard as exc:
        click.echo(f"kernel error: {exc}", err=True)
        sys.exit(1)
    _emit(chain_to_json(tree) if fmt == "json" else chain_to_turtle(tree), out)


__all__ = ["kernel_group"]
