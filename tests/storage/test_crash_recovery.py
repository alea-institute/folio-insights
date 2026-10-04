"""Crash after journal commit but before projection update: recovery replays
exactly the committed state and watermark."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from folio_insights.storage import (
    CorpusStorageContext,
    ProjectionRecoveryFailed,
    ProjectionRecoveryPending,
    StorageClosed,
)
from folio_insights.storage.projection import ProjectionHandle

from tests.storage.conftest import (
    at,
    genesis,
    new_identity,
    role_assertion,
    shard,
    start_proc,
)

pytestmark = pytest.mark.storage

_ALL_QUADS = "SELECT ?s ?p ?o WHERE { ?s ?p ?o } ORDER BY ?s ?p ?o"


async def _quads(ctx: CorpusStorageContext) -> list[tuple[str, str, str]]:
    rows = await ctx.query(_ALL_QUADS)
    return [(str(r["s"]), str(r["p"]), str(r["o"])) for r in rows]


async def test_projection_failure_after_commit_is_pending_then_recovers(
    storage_root: Path, admin, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    await ctx.governance.append(genesis("corpus-a", admin))
    s = shard(1)
    await ctx.shards.put(s.shard_iri, s)
    before = await _quads(ctx)

    def _boom(self, corpus, rows):  # noqa: ANN001
        raise OSError("synthetic projection failure")

    monkeypatch.setattr(ProjectionHandle, "apply", _boom)
    event = role_assertion("corpus-a", admin, new_identity().did, "reviewer", at(1))
    with pytest.raises(ProjectionRecoveryPending) as info:
        await ctx.governance.append(event, op_id="op-pending")
    assert info.value.op_id == "op-pending" and info.value.position == 2
    # The failing context closed itself instead of serving a mixed revision.
    assert ctx.closed
    with pytest.raises(StorageClosed):
        await ctx.shards.get(s.shard_iri)

    # While recovery cannot finish, opening (and so any query) refuses.
    with pytest.raises(ProjectionRecoveryFailed):
        await CorpusStorageContext.open(storage_root, "corpus-a")

    monkeypatch.undo()
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        status = await ctx.status()
        assert status.journal_head == status.projection_watermark == 2
        # Retrying the operation ID returns the committed event; nothing new.
        retried = await ctx.governance.append(event, op_id="op-pending")
        assert retried.position == 1
        assert (await ctx.status()).journal_head == 2
        after = await _quads(ctx)
        assert set(before) < set(after)
        # Recovery reconstructs exactly what a clean rebuild produces.
        assert await ctx.rebuild_projection() == 2
        assert await _quads(ctx) == after
    finally:
        await ctx.close()


async def test_process_killed_between_commit_and_projection(storage_root: Path, admin) -> None:
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    await ctx.governance.append(genesis("corpus-a", admin))
    await ctx.close()

    proc = start_proc("crash", str(storage_root), "corpus-a", admin.raw_private_hex())
    stdout, stderr = proc.communicate(timeout=25)
    assert proc.returncode == 17, stderr
    crashed = json.loads(stdout.strip().splitlines()[-1])
    assert crashed == {"committed": 1, "op_id": "crash-op"}

    # The projection still trails the journal on disk.
    from folio_insights.storage.projection import ProjectionHandle as Handle

    handle = Handle(storage_root)
    try:
        assert handle.state("corpus-a").watermark == 0
    finally:
        handle.close()

    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        status = await ctx.status()
        assert status.journal_head == status.projection_watermark == 1
        events = [e async for e in ctx.governance.iter_events("corpus-a")]
        assert [e.position for e in events] == [0, 1]
        rows = await ctx.query(
            "SELECT ?a WHERE { GRAPH ?g { ?e <https://folio-insights.aleainstitute.ai/vocab/logPosition> 1 ; "
            "<https://folio-insights.aleainstitute.ai/vocab/action> ?a } }"
        )
        assert [r["a"].value for r in rows] == ["role_assertion"]
        recovered = await _quads(ctx)
        await ctx.rebuild_projection()
        assert await _quads(ctx) == recovered
    finally:
        await ctx.close()
