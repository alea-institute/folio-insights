"""Competing writers serialize: unique, contiguous positions and authorization
checked against the committing transaction's state."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from folio_insights.governance.log import NotAuthorized, WouldLockoutCorpusAdmin
from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.journal import JOURNAL_FILENAME

from tests.storage.conftest import (
    at,
    genesis,
    new_identity,
    role_assertion,
    role_revocation,
    shard,
    start_proc,
)

pytestmark = pytest.mark.storage


def _journal_positions(root: Path, corpus: str) -> tuple[list[int], list[int]]:
    conn = sqlite3.connect(root / JOURNAL_FILENAME)
    try:
        positions = [
            r[0]
            for r in conn.execute(
                "SELECT position FROM journal WHERE corpus = ? ORDER BY position", (corpus,)
            )
        ]
        gov = [
            r[0]
            for r in conn.execute(
                "SELECT governance_position FROM journal WHERE corpus = ? AND "
                "kind = 'governance' ORDER BY governance_position",
                (corpus,),
            )
        ]
    finally:
        conn.close()
    return positions, gov


async def test_competing_processes_get_unique_contiguous_positions(
    storage_root: Path, admin
) -> None:
    setup = await CorpusStorageContext.open(storage_root, "corpus-a")
    await setup.governance.append(genesis("corpus-a", admin))
    await setup.close()

    workers, per_worker = 3, 3
    procs = [
        start_proc(
            "compete", str(storage_root), "corpus-a", admin.raw_private_hex(), str(w + 1),
            str(per_worker),
        )
        for w in range(workers)
    ]
    outputs = []
    for proc in procs:
        stdout, stderr = proc.communicate(timeout=25)
        assert proc.returncode == 0, stderr
        outputs.append(stdout.strip().splitlines()[-1])

    import json

    results = [json.loads(o) for o in outputs]
    gov_positions = sorted(p for r in results for p in r["positions"])
    assert gov_positions == list(range(1, workers * per_worker + 1))

    positions, gov = _journal_positions(storage_root, "corpus-a")
    total = 1 + 2 * workers * per_worker
    assert positions == list(range(total))
    assert gov == list(range(workers * per_worker + 1))

    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        status = await ctx.status()
        assert status.journal_head == status.projection_watermark == total - 1
        assert len([s async for s in ctx.shards.iter_shards()]) == workers * per_worker
        events = [e async for e in ctx.governance.iter_events("corpus-a")]
        assert [e.position for e in events] == list(range(workers * per_worker + 1))
    finally:
        await ctx.close()


async def test_concurrent_contexts_in_one_process_serialize(storage_root: Path, admin) -> None:
    contexts = [await CorpusStorageContext.open(storage_root, "corpus-a") for _ in range(4)]
    try:
        await contexts[0].governance.append(genesis("corpus-a", admin))

        async def _write(i: int, c: CorpusStorageContext) -> int:
            s = shard(100 + i)
            await c.shards.put(s.shard_iri, s)
            e = await c.governance.append(
                role_assertion("corpus-a", admin, new_identity().did, "reviewer", at(50))
            )
            return e.position

        positions = await asyncio.gather(*(_write(i, c) for i, c in enumerate(contexts)))
        assert sorted(positions) == [1, 2, 3, 4]
        journal, gov = _journal_positions(storage_root, "corpus-a")
        assert journal == list(range(9)) and gov == list(range(5))
    finally:
        for c in contexts:
            await c.close()


async def test_racing_mutual_revocations_leave_an_admin(storage_root: Path, admin) -> None:
    """Two admins revoke each other concurrently: authorization and the
    last-admin rule are evaluated inside the serialized transaction, so
    exactly one revocation commits and an admin always remains."""
    other = new_identity()
    a = await CorpusStorageContext.open(storage_root, "corpus-a")
    b = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        await a.governance.append(genesis("corpus-a", admin))
        await a.governance.append(role_assertion("corpus-a", admin, other.did, "corpus_admin", at(1)))
        results = await asyncio.gather(
            a.governance.append(role_revocation("corpus-a", admin, other.did, "corpus_admin", at(2))),
            b.governance.append(role_revocation("corpus-a", other, admin.did, "corpus_admin", at(2))),
            return_exceptions=True,
        )
        ok = [r for r in results if not isinstance(r, BaseException)]
        refused = [r for r in results if isinstance(r, BaseException)]
        assert len(ok) == 1 and len(refused) == 1
        assert isinstance(refused[0], (NotAuthorized, WouldLockoutCorpusAdmin))
        far = at(10_000)
        roles = await a.governance.query_active_roles_at("corpus-a", far)
        admins = [d for d, r in roles.items() if "corpus_admin" in r]
        assert len(admins) == 1
        assert await b.governance.latest_position("corpus-a") == 2
    finally:
        await a.close()
        await b.close()
