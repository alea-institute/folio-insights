"""Unit tests for gate2_harness — stateless API contract (QUALITY-01 scaffold).

Runs against a tiny in-test N-Quads fixture so the quick suite does not need
the 235MB 1M-triple corpus. The Gate 2 bench harness
(tests/bench/test_gate2_sparql.py) exercises the same entrypoints against
fixtures/bench.nq.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pyoxigraph import NamedNode

from folio_insights.bench.gate2_harness import (
    GOLD_QUERY_NAMED_GRAPHS,
    load_and_query,
    load_store_optimized,
    query_only,
)


@pytest.fixture
def tiny_nquads(tmp_path: Path) -> Path:
    """Tiny N-Quads fixture — 6 quads across 3 named graphs.

    Mirrors the bench.nq graph layout (advocacy / fre / restatement) so the
    prune-table entries under test map to real graph IRIs.
    """
    path = tmp_path / "tiny.nq"
    path.write_text(
        "<http://a> <http://p> <http://o1> <https://folio-insights.aleainstitute.ai/corpus/advocacy> .\n"
        "<http://b> <http://p> <http://o2> <https://folio-insights.aleainstitute.ai/corpus/advocacy> .\n"
        "<http://c> <http://p> <http://o3> <https://folio-insights.aleainstitute.ai/corpus/fre> .\n"
        "<http://d> <http://p> <http://o4> <https://folio-insights.aleainstitute.ai/corpus/fre> .\n"
        "<http://e> <http://p> <http://o5> <https://folio-insights.aleainstitute.ai/corpus/restatement> .\n"
        "<http://f> <http://p> <http://o6> <https://folio-insights.aleainstitute.ai/corpus/restatement> .\n"
    )
    return path


@pytest.fixture
def tiny_query(tmp_path: Path) -> Path:
    """Query that returns all triples matching pattern across graphs."""
    path = tmp_path / "q_tiny.sparql"
    path.write_text("SELECT ?s WHERE { GRAPH ?g { ?s <http://p> ?o } }")
    return path


def test_load_store_optimized_returns_pyoxigraph_store(tiny_nquads: Path) -> None:
    store = load_store_optimized(tiny_nquads)
    rows = list(store.store.query("SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }"))
    count = int(rows[0][0].value)
    assert count == 6


def test_load_and_query_returns_rows(tiny_nquads: Path, tiny_query: Path) -> None:
    rows = load_and_query(tiny_nquads, tiny_query, named_graphs=None)
    assert len(rows) == 6


def test_named_graphs_pruning_reduces_rows(tiny_nquads: Path, tiny_query: Path) -> None:
    all_rows = load_and_query(tiny_nquads, tiny_query, named_graphs=None)
    advocacy_only = load_and_query(
        tiny_nquads,
        tiny_query,
        named_graphs=[NamedNode("https://folio-insights.aleainstitute.ai/corpus/advocacy")],
    )
    assert len(advocacy_only) < len(all_rows)
    assert len(advocacy_only) == 2


def test_repeated_calls_deterministic(tiny_nquads: Path, tiny_query: Path) -> None:
    a = load_and_query(tiny_nquads, tiny_query, named_graphs=None)
    b = load_and_query(tiny_nquads, tiny_query, named_graphs=None)
    assert len(a) == len(b)


def test_gold_query_named_graphs_covers_all_13_queries() -> None:
    """Plan 08 tuning log requires an explicit entry for every gold query."""
    queries_dir = Path("fixtures/gold_queries")
    gold_stems = {p.stem for p in queries_dir.glob("q*.sparql")}
    covered = set(GOLD_QUERY_NAMED_GRAPHS.keys())
    missing = gold_stems - covered
    assert not missing, f"Missing named_graphs entry for: {missing}"


def test_query_only_warm_path(tiny_nquads: Path, tiny_query: Path) -> None:
    store = load_store_optimized(tiny_nquads)
    rows = query_only(store, tiny_query, named_graphs=None)
    assert len(rows) == 6
