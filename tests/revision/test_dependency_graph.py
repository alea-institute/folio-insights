"""Phase 9 U3 (R6, KTD7) — the explicit dependency web.

Transitive reach with hop depth, cycle findings, one bulk adjacency read from
the persistent store, and the 10K-shard construction benchmark (< 5 s).
Synthetic shards only.
"""
from __future__ import annotations

import os
import platform
import time
from pathlib import Path

import pytest

from folio_insights.revision.dependency_graph import DependencyEdge, DependencyGraph
from folio_insights.revision.store import InMemoryShardStore
from folio_insights.storage import CorpusStorageContext

from tests.storage.conftest import shard


def iri(n: int) -> str:
    return f"urn:folio:shard/{n:032x}"


def chain_shards() -> list:
    """1 <- 2 <- 3 <- 4 (each depends on the previous), 5 depends on 1 and 3."""
    return [
        shard(1),
        shard(2, depends_on_shards=[iri(1)]),
        shard(3, depends_on_precedents=[iri(2)]),
        shard(4, depends_on_definitions=[iri(3)]),
        shard(5, depends_on_axioms=[iri(1)], depends_on_shards=[iri(3)]),
    ]


def test_transitive_dependents_carry_minimum_depth() -> None:
    graph = DependencyGraph.from_shards(chain_shards())
    assert graph.dependents(iri(1)) == [iri(2), iri(5)]
    assert graph.transitive_dependents(iri(1)) == {iri(2): 1, iri(5): 1, iri(3): 2, iri(4): 3}
    assert graph.transitive_dependencies(iri(4)) == {iri(3): 1, iri(2): 2, iri(1): 3}
    assert graph.node_count == 5 and graph.edge_count == 5
    assert graph.is_acyclic()


def test_planted_three_cycle_is_reported_not_raised() -> None:
    shards = [
        shard(1, depends_on_shards=[iri(3)]),
        shard(2, depends_on_shards=[iri(1)]),
        shard(3, depends_on_shards=[iri(2)]),
        shard(4, depends_on_shards=[iri(1)]),
    ]
    graph = DependencyGraph.from_shards(shards)
    assert graph.cycles() == [(iri(1), iri(3), iri(2))]
    assert not graph.is_acyclic()
    # the walk terminates and still reports every dependent once
    assert graph.transitive_dependents(iri(1)) == {iri(2): 1, iri(4): 1, iri(3): 2}


def test_self_reference_and_duplicate_edges_are_ignored() -> None:
    graph = DependencyGraph(
        [("a", "a"), ("b", "a"), DependencyEdge("b", "a", "depends_on_shards")], nodes=["c"]
    )
    assert graph.edge_count == 1 and graph.cycles() == [] and "c" in graph


async def test_persistent_bulk_read_matches_in_memory(tmp_path: Path) -> None:
    shards = chain_shards()
    memory = InMemoryShardStore("corpus-a")
    for s in shards:
        await memory.put(s.shard_iri, s)
    ctx = await CorpusStorageContext.open(tmp_path / "storage", "corpus-a")
    try:
        await ctx.ingest_shards(shards)
        nodes, edges = await ctx.shards.dependency_edges()
        assert nodes == sorted(iri(n) for n in range(1, 6))
        assert {(e.dependent, e.dependency, e.field) for e in edges} >= {
            (iri(2), iri(1), "depends_on_shards"),
            (iri(3), iri(2), "depends_on_precedents"),
            (iri(4), iri(3), "depends_on_definitions"),
            (iri(5), iri(1), "depends_on_axioms"),
        }
        persistent = await DependencyGraph.from_store(ctx.shards)
    finally:
        await ctx.close()
    in_memory = await DependencyGraph.from_store(memory)
    for n in range(1, 6):
        assert persistent.transitive_dependents(iri(n)) == in_memory.transitive_dependents(iri(n))


def _synthetic_dag(n: int) -> list:
    """``n`` shards; shard k depends on k//2 and k-1 (a deep, wide DAG)."""
    out = []
    for k in range(1, n + 1):
        deps = sorted({iri(k // 2), iri(k - 1)} - {iri(0), iri(k)}) if k > 1 else []
        out.append(shard(k, depends_on_shards=deps))
    return out


def _hardware() -> str:
    model = platform.processor() or platform.system()
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return f"{platform.machine()} {model} cpus={os.cpu_count()}"


def test_10k_shard_dag_builds_under_five_seconds() -> None:
    shards = _synthetic_dag(10_000)
    start = time.perf_counter()
    graph = DependencyGraph.from_shards(shards)
    reach = graph.transitive_dependents(iri(1))
    cycles = graph.cycles()
    elapsed = time.perf_counter() - start
    print(f"U3 DAG benchmark (in-memory): 10000 shards, {graph.edge_count} edges, "
          f"{elapsed:.3f}s on {_hardware()}")
    assert graph.node_count == 10_000 and len(reach) == 9_999 and cycles == []
    assert elapsed < 5.0


@pytest.mark.timeout(300)
async def test_10k_shard_dag_from_persistent_store_under_five_seconds(tmp_path: Path) -> None:
    """The bulk adjacency read + construction over a real 10K-shard corpus."""
    ctx = await CorpusStorageContext.open(tmp_path / "storage", "corpus-a")
    try:
        await ctx.bulk_load_shards(_synthetic_dag(10_000))
        start = time.perf_counter()
        graph = await DependencyGraph.from_store(ctx.shards)
        reach = graph.transitive_dependents(iri(1))
        cycles = graph.cycles()
        elapsed = time.perf_counter() - start
    finally:
        await ctx.close()
    print(f"U3 DAG benchmark (persistent): 10000 shards, {graph.edge_count} edges, "
          f"{elapsed:.3f}s on {_hardware()}")
    assert graph.node_count == 10_000 and len(reach) == 9_999 and cycles == []
    assert elapsed < 5.0
