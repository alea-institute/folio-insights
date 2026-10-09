"""Drain U3 kernel test fixtures: generated admins and disposable corpora.

Every signing identity is a freshly generated ed25519 ``did:key``; no
operator key is read. Governance events are signed at the real clock (R17:
``signed_at`` must be within ``SIGNING_SKEW`` of server time), never at a
time fixed when the module was imported. Corpora live under pytest temp directories. Synthetic
non-kernel shards come from ``tests/storage/conftest.shard``.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from folio_insights.kernel.seed import SeedReport, seed_kernel
from folio_insights.storage import CorpusStorageContext

from tests.storage.conftest import (  # noqa: F401  (fresh_signing_clock: autouse, R17)
    Identity,
    fresh_signing_clock,
    genesis,
    new_identity,
)

CORPUS = "kernel-corpus"


async def bootstrap_corpus(root: Path, corpus: str, admin: Identity) -> None:
    """Create ``corpus`` with ``admin`` as its genesis corpus admin."""
    ctx = await CorpusStorageContext.open(root, corpus)
    try:
        # Signed now (not at the import-time anchor): a module-scoped fixture can run
        # long after ``tests.storage.conftest`` was imported.
        await ctx.governance.append(
            genesis(corpus, admin, datetime.now(UTC).replace(microsecond=0))
        )
    finally:
        await ctx.close()


@dataclass(frozen=True)
class SeededCorpus:
    root: Path
    corpus: str
    admin: Identity
    first: SeedReport
    second: SeedReport


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> SeededCorpus:
    """One corpus seeded twice with the full kernel (shared per module)."""
    root = tmp_path_factory.mktemp("kernel") / "storage"
    admin = new_identity()

    async def run() -> tuple[SeedReport, SeedReport]:
        await bootstrap_corpus(root, CORPUS, admin)
        first = await seed_kernel(root, CORPUS, signing_key=admin.sk)
        second = await seed_kernel(root, CORPUS, signing_key=admin.sk)
        return first, second

    first, second = asyncio.run(run())
    return SeededCorpus(root, CORPUS, admin, first, second)
