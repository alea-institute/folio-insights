"""Drain U4 (R13, KTD9; AE5) — the dependency-cycle guard.

The pure check over a committed ``DependencyGraph``, the in-transaction guard
in ``CorpusStorageContext`` (``shards.put``, ``ingest_shards``,
``bulk_load_shards`` on both the in-process and the process-pool path), the
``refuse_dependency_cycles`` switch for legacy corpora, and ``folio-insights
graph validate``. Synthetic shards and temporary storage roots only.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from folio_insights.revision.acyclicity import (
    EDGE_FIELDS,
    DependencyCycle,
    check_new_edges,
    find_new_cycle,
    record_out_edges,
    shard_out_edges,
)
from folio_insights.revision.dependency_graph import DependencyGraph, shard_edges
from folio_insights.shards import dump_shard_record
from folio_insights.storage import CorpusStorageContext, StorageConfig

from tests.storage.conftest import shard

pytestmark = pytest.mark.storage


def iri(n: int) -> str:
    return f"urn:folio:shard/{n:032x}"


A, B, C, D = iri(0xA), iri(0xB), iri(0xC), iri(0xD)


# ── the pure check ────────────────────────────────────────────────────────


def test_edge_fields_are_the_dependency_lists_plus_elaborates() -> None:
    assert EDGE_FIELDS == (
        "depends_on_precedents",
        "depends_on_definitions",
        "depends_on_shards",
        "depends_on_axioms",
        "elaborates",
    )
    s = shard(1, depends_on_axioms=[A], elaborates=[B, A], depends_on_shards=[C])
    assert shard_out_edges(s) == (C, A, B)
    assert record_out_edges(json.loads(dump_shard_record(s))) == (C, A, B)
    # A legacy record missing a field contributes nothing for it.
    assert record_out_edges({"depends_on_shards": [A], "elaborates": None}) == (A,)


def test_dependency_graph_includes_elaborates_only_when_asked() -> None:
    s = shard(1, depends_on_shards=[A], elaborates=[B])
    assert {e.dependency for e in shard_edges(s)} == {A}
    assert {(e.dependency, e.field) for e in shard_edges(s, include_elaborates=True)} == {
        (A, "depends_on_shards"), (B, "elaborates"),
    }
    assert DependencyGraph.from_shards([s]).dependencies(iri(1)) == [A]
    assert DependencyGraph.from_shards([s], include_elaborates=True).dependencies(iri(1)) == [A, B]


def test_ae5_pure_check_names_the_cycle() -> None:
    """AE5: A depends on B is committed; writing B that depends on A is
    refused and names ``A -> B -> A``."""
    committed = DependencyGraph.from_shards(
        [shard(0xA, depends_on_shards=[B])], include_elaborates=True
    )
    with pytest.raises(DependencyCycle) as info:
        check_new_edges(committed, [shard(0xB, depends_on_shards=[A])])
    assert info.value.cycle == [A, B, A]
    assert info.value.path == f"{A} -> {B} -> {A}"
    assert f"{A} -> {B} -> {A}" in str(info.value)


def test_acyclic_writes_pass() -> None:
    committed = DependencyGraph.from_shards(
        [shard(0xA), shard(0xB, depends_on_shards=[A])], include_elaborates=True
    )
    check_new_edges(committed, [shard(0xC, depends_on_shards=[A, B], elaborates=[B])])
    # A diamond is not a cycle.
    check_new_edges(committed, [shard(0xC, depends_on_shards=[A]), shard(0xD, elaborates=[A, iri(0xC)])])


def test_self_edge_is_refused() -> None:
    with pytest.raises(DependencyCycle) as info:
        check_new_edges(DependencyGraph(), [shard(0xA, depends_on_axioms=[A])])
    assert info.value.cycle == [A, A]
    with pytest.raises(DependencyCycle):
        check_new_edges(DependencyGraph(), [shard(0xA, elaborates=[A])])


def test_cycle_internal_to_the_batch_is_found() -> None:
    batch = [
        shard(0xA, depends_on_shards=[B]),
        shard(0xB, depends_on_definitions=[C]),
        shard(0xC, elaborates=[A]),
    ]
    cycle = find_new_cycle(DependencyGraph(), batch)
    assert cycle is not None and cycle[0] == cycle[-1] and len(cycle) == 4
    assert set(cycle) == {A, B, C}


def test_elaborates_edges_close_cycles() -> None:
    committed = DependencyGraph.from_shards(
        [shard(0xA, elaborates=[B]), shard(0xB)], include_elaborates=True
    )
    with pytest.raises(DependencyCycle) as info:
        check_new_edges(committed, [shard(0xB, depends_on_axioms=[A])])
    assert info.value.cycle == [A, B, A]


def test_cycle_through_a_long_committed_chain_names_the_shortest_path() -> None:
    chain = [shard(1)] + [shard(n, depends_on_shards=[iri(n - 1)]) for n in range(2, 200)]
    committed = DependencyGraph.from_shards(chain, include_elaborates=True)
    cycle = find_new_cycle(committed, [shard(1, depends_on_shards=[iri(199)])])
    assert cycle == [iri(n) for n in range(199, 0, -1)] + [iri(199)]


def test_last_revision_in_a_batch_wins() -> None:
    committed = DependencyGraph.from_shards(
        [shard(0xA, depends_on_shards=[B])], include_elaborates=True
    )
    # B first claims A (a cycle), then a later revision in the same batch drops it.
    check_new_edges(committed, [shard(0xB, depends_on_shards=[A]), shard(0xB)])


def test_unchanged_legacy_cycle_is_not_a_new_edge() -> None:
    legacy = DependencyGraph.from_shards(
        [shard(0xA, depends_on_shards=[B]), shard(0xB, depends_on_shards=[A])],
        include_elaborates=True,
    )
    # Re-writing B with the edges it already had closes nothing new.
    check_new_edges(legacy, [shard(0xB, depends_on_shards=[A], sense="revised")])
    # A legacy self-loop kept by a revision is not new either.
    looped = DependencyGraph.from_shards([shard(0xC, depends_on_shards=[C])])
    check_new_edges(looped, [shard(0xC, depends_on_shards=[C], sense="revised")])
    # ... but a NEW edge into the legacy cycle that closes another one is refused.
    with pytest.raises(DependencyCycle):
        check_new_edges(legacy, [shard(0xB, depends_on_shards=[A, C]), shard(0xC, elaborates=[B])])


# ── the storage guard ─────────────────────────────────────────────────────


async def _head(ctx: CorpusStorageContext) -> int:
    return (await ctx.status()).journal_head


async def test_ae5_put_is_refused_inside_the_transaction(tmp_path: Path) -> None:
    ctx = await CorpusStorageContext.open(tmp_path / "s", "corpus-a")
    try:
        await ctx.shards.put(A, shard(0xA, depends_on_shards=[B]), op_id="put-a")
        head = await _head(ctx)
        with pytest.raises(DependencyCycle) as info:
            await ctx.shards.put(B, shard(0xB, depends_on_shards=[A]), op_id="put-b")
        assert info.value.cycle == [A, B, A]
        assert str(info.value).endswith(f"{A} -> {B} -> {A}")
        assert await _head(ctx) == head and await ctx.shards.get(B) is None
        # The refusal is not a stuck state: an acyclic B commits.
        await ctx.shards.put(B, shard(0xB), op_id="put-b2")
        assert await ctx.shards.get(B) is not None
    finally:
        await ctx.close()


async def test_put_self_edge_and_elaborates_cycle_are_refused(tmp_path: Path) -> None:
    ctx = await CorpusStorageContext.open(tmp_path / "s", "corpus-a")
    try:
        with pytest.raises(DependencyCycle) as info:
            await ctx.shards.put(A, shard(0xA, elaborates=[A]))
        assert info.value.cycle == [A, A]
        await ctx.ingest_shards([shard(0xA, elaborates=[B]), shard(0xB)])
        # The committed elaborates edge is read from the journal (it is not
        # projected), so B -> A closes A -> B -> A.
        with pytest.raises(DependencyCycle) as info:
            await ctx.shards.put(B, shard(0xB, depends_on_precedents=[A]))
        assert info.value.cycle == [A, B, A]
    finally:
        await ctx.close()


async def test_batch_with_an_internal_cycle_is_refused_whole(tmp_path: Path) -> None:
    ctx = await CorpusStorageContext.open(tmp_path / "s", "corpus-a")
    try:
        await ctx.ingest_shards([shard(1)])
        head = await _head(ctx)
        batch = [
            shard(2),  # innocent records in the same batch are refused too
            shard(0xA, depends_on_shards=[B]),
            shard(0xB, elaborates=[C]),
            shard(0xC, depends_on_axioms=[A]),
        ]
        with pytest.raises(DependencyCycle):
            await ctx.ingest_shards(batch, op_id="cyclic-batch")
        assert await _head(ctx) == head
        assert [s.shard_iri async for s in ctx.shards.iter_shards()] == [iri(1)]
        # The same op_id is still free: nothing was committed under it.
        await ctx.ingest_shards(batch[:3], op_id="cyclic-batch")
        assert await _head(ctx) == head + 3
    finally:
        await ctx.close()


async def test_batch_closing_a_cycle_against_a_committed_chain(tmp_path: Path) -> None:
    ctx = await CorpusStorageContext.open(tmp_path / "s", "corpus-a")
    try:
        chain = [shard(1)] + [shard(n, depends_on_shards=[iri(n - 1)]) for n in range(2, 40)]
        await ctx.ingest_shards(chain)
        # Revising the root to rest on the tail closes the whole chain.
        with pytest.raises(DependencyCycle) as info:
            await ctx.ingest_shards([shard(50), shard(1, elaborates=[iri(39)])])
        assert info.value.cycle == [iri(n) for n in range(39, 0, -1)] + [iri(39)]
        # A dependent added on the tail is fine.
        await ctx.ingest_shards([shard(40, depends_on_shards=[iri(39)])])
    finally:
        await ctx.close()


async def test_large_pool_bulk_load_is_checked_from_payloads(tmp_path: Path) -> None:
    """The process-pool path returns bytes only; the guard reads edges from
    the payload JSON and refuses the whole bulk load."""
    n = 2600  # above PARALLEL_MIN_ITEMS
    records = [shard(k, depends_on_shards=[iri(k - 1)] if k else []) for k in range(n)]
    records[0] = shard(0, elaborates=[iri(n - 1)])
    ctx = await CorpusStorageContext.open(tmp_path / "s", "corpus-a")
    try:
        with pytest.raises(DependencyCycle) as info:
            await ctx.bulk_load_shards(records, op_id="bulk-cyclic")
        assert len(info.value.cycle) == n + 1
        assert await _head(ctx) == -1
        records[0] = shard(0)
        loaded = await ctx.bulk_load_shards(records, op_id="bulk-ok")
        assert loaded.records == n
    finally:
        await ctx.close()


async def test_guard_can_be_turned_off_for_legacy_loads_and_then_tolerates_them(
    tmp_path: Path,
) -> None:
    root = tmp_path / "s"
    off = await CorpusStorageContext.open(
        root, "corpus-a", config=StorageConfig(refuse_dependency_cycles=False)
    )
    try:
        await off.ingest_shards(
            [shard(0xA, depends_on_shards=[B]), shard(0xB, elaborates=[A])]
        )
    finally:
        await off.close()
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        # A revision that keeps the legacy edges is not refused...
        await ctx.shards.put(B, shard(0xB, elaborates=[A], sense="revised"), op_id="r1")
        # ...but one that adds a new cycle-closing edge is.
        with pytest.raises(DependencyCycle):
            await ctx.ingest_shards([shard(0xC, depends_on_shards=[B]), shard(0xA, depends_on_shards=[B, C])])
        graph = await DependencyGraph.from_store(ctx.shards, include_elaborates=True)
        assert graph.cycles() == [(A, B)]
        # Without elaborates the stored web is acyclic (A -> B only).
        assert (await DependencyGraph.from_store(ctx.shards)).is_acyclic()
    finally:
        await ctx.close()


async def test_retrying_a_committed_op_is_not_rechecked(tmp_path: Path) -> None:
    ctx = await CorpusStorageContext.open(tmp_path / "s", "corpus-a")
    try:
        batch = [shard(0xA, depends_on_shards=[B]), shard(0xB)]
        first = await ctx.ingest_shards(batch, op_id="op-1")
        assert await ctx.ingest_shards(batch, op_id="op-1") == first
    finally:
        await ctx.close()


# ── graph validate ────────────────────────────────────────────────────────


def _seed(root: Path, shards: list, *, guard: bool) -> None:
    async def run() -> None:
        ctx = await CorpusStorageContext.open(
            root, "corpus-a", config=StorageConfig(refuse_dependency_cycles=guard)
        )
        try:
            await ctx.ingest_shards(shards)
        finally:
            await ctx.close()

    asyncio.run(run())


def test_graph_validate_reports_stored_legacy_cycles(tmp_path: Path) -> None:
    from folio_insights.cli import cli

    root = tmp_path / "root"
    _seed(
        root,
        [shard(0xA, depends_on_shards=[B]), shard(0xB, elaborates=[A]), shard(0xC, depends_on_axioms=[C])],
        guard=False,
    )
    runner = CliRunner()
    out = runner.invoke(cli, ["graph", "validate", "corpus-a", "--corpus-root", str(root)])
    assert out.exit_code == 1, out.output
    assert f"cycle: {A} -> {B} -> {A}" in out.output
    assert f"cycle: {C} -> {C}" in out.output
    assert "2 cycle(s)" in out.output

    report = runner.invoke(
        cli, ["graph", "validate", "corpus-a", "--corpus-root", str(root), "--json"]
    )
    assert report.exit_code == 1
    data = json.loads(report.output)
    assert data["acyclic"] is False and data["cycles"] == [f"{A} -> {B} -> {A}", f"{C} -> {C}"]


def test_graph_validate_passes_an_acyclic_corpus_and_refuses_unknown(tmp_path: Path) -> None:
    from folio_insights.cli import cli

    root = tmp_path / "root"
    _seed(root, [shard(0xA), shard(0xB, elaborates=[A], depends_on_shards=[A])], guard=True)
    runner = CliRunner()
    out = runner.invoke(cli, ["graph", "validate", "corpus-a", "--corpus-root", str(root)])
    assert out.exit_code == 0, out.output
    assert "corpus-a: acyclic (2 nodes, 1 edges)" in out.output
    missing = runner.invoke(cli, ["graph", "validate", "nope", "--corpus-root", str(root)])
    assert missing.exit_code == 1 and "no corpus" in missing.output
