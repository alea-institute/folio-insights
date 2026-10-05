"""``folio-insights framework register|list|export`` (Phase 9 U2).

* ``register`` — a corpus admin registers a framework in a corpus, signed
  with the local keystore key (refused for any other role).
* ``list`` — the corpus registry (starter set + registrations) as JSON.
* ``export`` — the registry as a SKOS concept scheme (Turtle).

Every command opens one existing corpus storage context and never creates a
corpus.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from folio_insights.governance.cli._state import corpus_root_option, resolve_corpus_root
from folio_insights.identity.keys import KEY_PATH


def _open(corpus_root: Path | None, corpus: str):  # noqa: ANN202
    from folio_insights.storage import CorpusStorageContext
    from folio_insights.storage.journal import JOURNAL_FILENAME, committed_corpora

    root = resolve_corpus_root(corpus_root)
    if corpus not in committed_corpora(root / JOURNAL_FILENAME):
        click.echo(f"framework error: no corpus {corpus!r} under {root}", err=True)
        sys.exit(1)
    return CorpusStorageContext.open(root, corpus)


async def _registry(corpus_root: Path | None, corpus: str):  # noqa: ANN202
    from folio_insights.frameworks.registry import load_registry

    ctx = await _open(corpus_root, corpus)
    try:
        return await load_registry(ctx)
    finally:
        await ctx.close()


@click.group(name="framework")
def framework_group() -> None:
    """Framework records: register, list and export a corpus's frameworks."""


@framework_group.command(name="register")
@click.argument("framework_id")
@click.option("--label", required=True, help="Human-readable framework name.")
@click.option("--jurisdiction", required=True,
              help="Jurisdiction prefix of the ID (e.g. us.delaware).")
@click.option("--parent", default=None, help="Registered parent framework ID.")
@click.option("--corpus", required=True, help="Corpus whose registry receives it.")
@click.option("--key-path", type=click.Path(path_type=Path), default=KEY_PATH,
              show_default=True, help="Local ed25519 keystore JWK of a corpus admin.")
@corpus_root_option
def register_cmd(
    framework_id: str,
    label: str,
    jurisdiction: str,
    parent: str | None,
    corpus: str,
    key_path: Path,
    corpus_root: Path | None,
) -> None:
    """Register FRAMEWORK_ID in a corpus (corpus admins only; DID-signed)."""
    from pydantic import ValidationError

    from folio_insights.frameworks.registry import (
        FrameworkRegistrationRefused,
        register_framework,
        registration_summary,
    )
    from folio_insights.identity.cli import _derive_didkey_from_signing_key
    from folio_insights.identity.keys import load_signing_key
    from folio_insights.models.framework import Framework

    try:
        framework = Framework(
            id=framework_id, label=label, jurisdiction=jurisdiction, parent=parent
        )
    except ValidationError as exc:
        click.echo(f"invalid framework: {exc.errors()[0]['msg']}", err=True)
        sys.exit(2)
    try:
        sk = load_signing_key(key_path)
    except FileNotFoundError:
        click.echo(f"no signing key at {key_path}: run `folio-insights did generate` first.",
                   err=True)
        sys.exit(1)
    did = _derive_didkey_from_signing_key(sk)

    async def run() -> dict:
        ctx = await _open(corpus_root, corpus)
        try:
            registration = await register_framework(ctx, framework, signing_key=sk, did=did)
        finally:
            await ctx.close()
        return dict(registration_summary(registration))

    try:
        click.echo(json.dumps(asyncio.run(run()), indent=2))
    except FrameworkRegistrationRefused as exc:
        click.echo(f"registration refused: {exc}", err=True)
        sys.exit(1)
    except ValueError as exc:
        click.echo(f"registration refused: {exc}", err=True)
        sys.exit(1)


@framework_group.command(name="list")
@click.option("--corpus", required=True)
@corpus_root_option
def list_cmd(corpus: str, corpus_root: Path | None) -> None:
    """List the corpus registry (starter set plus registrations) as JSON."""
    registry = asyncio.run(_registry(corpus_root, corpus))
    click.echo(json.dumps([fw.model_dump(mode="json") for fw in registry.frameworks()], indent=2))


@framework_group.command(name="export")
@click.option("--corpus", required=True)
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write the SKOS Turtle here (default: stdout).")
@corpus_root_option
def export_cmd(corpus: str, out: Path | None, corpus_root: Path | None) -> None:
    """Export the corpus registry as a SKOS concept scheme (Turtle)."""
    turtle = asyncio.run(_registry(corpus_root, corpus)).to_skos_turtle()
    if out is None:
        click.echo(turtle, nl=False)
    else:
        out.write_text(turtle, encoding="utf-8")
        click.echo(str(out))


__all__ = ["framework_group"]
