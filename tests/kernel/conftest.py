"""Drain U3 kernel test fixtures: generated admins and disposable corpora.

Every signing identity is a freshly generated ed25519 ``did:key``; no
operator key is read. Corpora live under pytest temp directories. Synthetic
non-kernel shards come from ``tests/storage/conftest.shard``.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from folio_insights.kernel.seed import SeedReport, seed_kernel
from folio_insights.storage import CorpusStorageContext

from tests.storage.conftest import Identity, genesis, new_identity

CORPUS = "kernel-corpus"


async def bootstrap_corpus(root: Path, corpus: str, admin: Identity) -> None:
    """Create ``corpus`` with ``admin`` as its genesis corpus admin."""
    ctx = await CorpusStorageContext.open(root, corpus)
    try:
        await ctx.governance.append(genesis(corpus, admin))
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
