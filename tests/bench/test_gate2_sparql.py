"""Gate 2 P95 SPARQL harness (QUALITY-01, D-05).

D-05 rule (CONTEXT.md):
  - P95 < 500ms hard target
  - P95 in [500ms, 800ms] — accept-with-SLO after 6-pass tuning
  - P95 > 800ms — pivot=fuseki verdict in DECISION.md

This test runs the 13 gold-query set in pytest-benchmark pedantic mode. The
warm-cache variant is the D-05 authoritative measurement (RESEARCH.md Gate 2
step 4). Results autosave to ``bench-results.json`` for Plan 08 DECISION.md
ingestion.

Run:

  # D-05 authoritative warm-cache measurement
  uv run pytest tests/bench/test_gate2_sparql.py::test_gate2_p95_warm \
    -m benchmark --benchmark-only \
    --benchmark-autosave \
    --benchmark-json=bench-results.json

  # Informational cold-cache variant (3 queries only; ~5-15 min wall-clock)
  uv run pytest tests/bench/test_gate2_sparql.py::test_gate2_p95_cold \
    -m benchmark --benchmark-only
"""
from __future__ import annotations

from pathlib import Path

import pytest

from folio_insights.bench.gate2_harness import (
    load_and_query,
    load_store_optimized,
    query_only,
)

QUERIES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "gold_queries"
GOLD_QUERIES = sorted(QUERIES_DIR.glob("q*.sparql"))

# D-05 thresholds (CONTEXT.md)
GATE2_HARD_TARGET_MS = 500
GATE2_SLO_CEILING_MS = 800

# pytest-benchmark rounds/warmup per RESEARCH.md §Gate 2 measurement (line 524).
# pedantic mode: rounds=20 measured, warmup_rounds=3 discarded, iterations=1
# per round (one function call timed per data point).
BENCH_ROUNDS = 20
BENCH_WARMUP = 3


def _p95_seconds(benchmark) -> float:
    """Compute P95 from the benchmark's sorted per-round data.

    pytest-benchmark 5.x Stats object does not expose a direct ``percentile``
    method; it exposes ``sorted_data`` (list of per-round wall-clock seconds)
    and the quartile aggregates (``q1``, ``median``, ``q3``, ``max``). For the
    P95 we index directly.
    """
    data = benchmark.stats.stats.sorted_data
    if not data:
        return 0.0
    # Nearest-rank percentile — standard for small-N pytest-benchmark runs.
    idx = min(len(data) - 1, int(0.95 * len(data)))
    return float(data[idx])


@pytest.fixture(scope="module")
def warm_store(bench_1m_corpus: Path):
    """Load + optimize once per module — warm-cache reuse (Gate 2 step 4).

    MODULE-scoped (not function) — a 1M bulk_load per query would explode the
    suite runtime. All 13 parametrizations share one loaded store so the
    measurement is query-time only, not ingest+query time.
    """
    return load_store_optimized(bench_1m_corpus)


@pytest.mark.benchmark(group="gate2-warm-p95")
@pytest.mark.parametrize("query_file", GOLD_QUERIES, ids=lambda p: p.stem)
def test_gate2_p95_warm(benchmark, warm_store, query_file: Path) -> None:
    """Warm-cache P95 — the authoritative Gate 2 measurement.

    Tuning steps applied (RESEARCH.md §Gate 2 lines 516-522):
      1. bulk_load via ``Store.bulk_load()`` (Plan 03's wrapper)
      2. ``Store.optimize()`` after load (Plan 03's wrapper)
      3. ``named_graphs=`` prune via ``GOLD_QUERY_NAMED_GRAPHS``
      4. Warm cache (this test — 3 warmup rounds, 20 measured rounds)
      5. SPARQL query-plan rewrites (baked into the .sparql files, Plan 00-03)
      6. RocksDB tuning (limited leverage — in-memory store for Phase 0)
    """
    benchmark.pedantic(
        query_only,
        args=(warm_store, query_file),
        rounds=BENCH_ROUNDS,
        warmup_rounds=BENCH_WARMUP,
        iterations=1,
    )

    p95_ms = _p95_seconds(benchmark) * 1000

    # D-05: >800ms = hard fail = pivot trigger. Must not be an xfail — Plan 08
    # needs a deterministic signal to write pivot=fuseki into DECISION.md.
    assert p95_ms < GATE2_SLO_CEILING_MS, (
        f"Gate 2 PIVOT TRIGGER — {query_file.name}: P95 {p95_ms:.1f}ms > "
        f"{GATE2_SLO_CEILING_MS}ms ceiling. Record in 00-DECISION.md per "
        f"D-05 (pivot=fuseki verdict required)."
    )

    if p95_ms >= GATE2_HARD_TARGET_MS:
        # Soft fail — accept-with-SLO range per D-05. xfail keeps the signal
        # visible in the test report without failing the suite.
        pytest.xfail(
            f"Gate 2 accept-with-SLO: {query_file.name} P95 {p95_ms:.1f}ms "
            f">= {GATE2_HARD_TARGET_MS}ms target; within "
            f"{GATE2_SLO_CEILING_MS}ms ceiling. Document SLO relaxation in "
            f"DECISION.md (D-05)."
        )


@pytest.mark.benchmark(group="gate2-cold-p95")
@pytest.mark.parametrize("query_file", GOLD_QUERIES[:3], ids=lambda p: p.stem)
def test_gate2_p95_cold(benchmark, bench_1m_corpus: Path, query_file: Path) -> None:
    """Cold-cache P95 — measures full bulk_load + optimize + query per round.

    NOT the D-05 authoritative measurement (D-05 is warm). This test exists
    to:
      (a) quantify the bulk_load cost (informs Phase 13 persistence decision),
      (b) confirm the harness works under worst-case,
      (c) provide a crossover datapoint for Gate 4 cold-page SSR comparison.

    Limited to the first 3 gold queries (T-00-25 mitigation): 20 rounds of
    cold-bulk-load over 13 queries would exceed 45 minutes wall-clock.
    """
    benchmark.pedantic(
        load_and_query,
        args=(bench_1m_corpus, query_file),
        rounds=5,
        warmup_rounds=0,  # cold = no warmup
        iterations=1,
    )
    # No assertion — purely informational. Plan 08 reads from
    # bench-results.json for the cold-vs-warm delta.
