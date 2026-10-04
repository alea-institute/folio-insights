"""Corpus storage for the governance + corpus CLI subgroups (Phase 13 U3).

Phase 7 shared one process-local ``InMemoryGovernanceLog`` singleton between
these commands, so nothing survived the process. Phase 13 replaces it: every
command opens ONE ``CorpusStorageContext`` for its corpus under the corpus
root and uses ``ctx.governance`` / ``ctx.shards`` for every read and write,
so separate CLI invocations see the same persistent state.

* Corpus root: ``--corpus-root``, else ``$FOLIO_INSIGHTS_CORPUS_ROOT``, else
  ``~/.folio-insights/corpora`` (created mode 0700). Never the repository's
  served ``output/`` directory.
* The context is always entered with ``async with corpus_storage(...)``: an
  unclosed aiosqlite connection keeps a worker thread alive and hangs
  interpreter exit.
* Signature verification on append uses ``cached_event_verifier`` over the
  SAME ``DidDocCache`` the command signs with, so a caller can pre-populate
  it for did:web / did:plc signers; did:key signers verify offline.
* Every CLI write passes an explicit operation ID (``new_op_id``); the
  storage default is not retry-safe.

D-04: this module imports the storage package, never the RDF/SQLite
libraries themselves; those stay behind ``folio_insights.storage``.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from folio_insights.identity.cache import DidDocCache
    from folio_insights.storage import CorpusStorageContext, StorageConfig

CORPUS_ROOT_ENV = "FOLIO_INSIGHTS_CORPUS_ROOT"


def default_corpus_root() -> Path:
    """``~/.folio-insights/corpora`` (resolved at call time)."""
    return Path.home() / ".folio-insights" / "corpora"


def resolve_corpus_root(value: Path | str | None) -> Path:
    """Explicit option, else the environment variable, else the default."""
    if value:
        return Path(value).expanduser()
    env = os.environ.get(CORPUS_ROOT_ENV)
    if env:
        return Path(env).expanduser()
    return default_corpus_root()


corpus_root_option = click.option(
    "--corpus-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help=(
        "Persistent corpus storage root (journal + RDF projection). Default: "
        f"${CORPUS_ROOT_ENV}, else ~/.folio-insights/corpora."
    ),
)


def cli_storage_config(cache: DidDocCache) -> StorageConfig:
    """Storage policy for CLI commands: the default PII gate and validators,
    with append-time signature checks resolved through ``cache``."""
    from folio_insights.storage import StorageConfig, cached_event_verifier

    return StorageConfig(event_verifier=cached_event_verifier(cache))


@asynccontextmanager
async def corpus_storage(
    root: Path | str | None, corpus: str, *, cache: DidDocCache
) -> AsyncIterator[CorpusStorageContext]:
    """Open the one storage context this command uses, and always close it."""
    from folio_insights.storage import CorpusStorageContext

    ctx = await CorpusStorageContext.open(
        resolve_corpus_root(root), corpus, config=cli_storage_config(cache)
    )
    try:
        yield ctx
    finally:
        await ctx.close()


def new_op_id(command: str) -> str:
    """A fresh explicit operation ID for one CLI write."""
    return f"cli:{command}:{uuid.uuid4().hex}"


def run_cli(coro: Coroutine[Any, Any, None]) -> None:
    """``asyncio.run`` with storage failures reported as a clean exit 1.

    A ``ProjectionRecoveryPending`` message names the committed operation ID
    and position, so the operator knows the write is durable.
    """
    from folio_insights.storage import StorageError

    try:
        asyncio.run(coro)
    except StorageError as exc:
        click.echo(f"storage error: {type(exc).__name__}: {exc}", err=True)
        sys.exit(1)


__all__ = [
    "CORPUS_ROOT_ENV",
    "cli_storage_config",
    "corpus_root_option",
    "corpus_storage",
    "default_corpus_root",
    "new_op_id",
    "resolve_corpus_root",
    "run_cli",
]
