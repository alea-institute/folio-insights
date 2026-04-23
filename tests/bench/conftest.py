"""Shared fixtures for folio-insights Phase 0 bench tests.

Scope: Gate 1-5 measurement harness. Fixtures are session-scoped where
1M-triple load is expensive; per-test fixtures for determinism helpers.

Pitfall 7 discipline: single `random.Random(seed)` instance; never
module-level `random.choice()`; never a NumPy RNG.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
BENCH_CORPUS = FIXTURES / "bench.nq"


@pytest.fixture(scope="session")
def bench_1m_corpus() -> Path:
    """D-14 pytest fixture — deterministic 1M-triple corpus (committed artifact).

    Generated via `folio-insights bench gen --seed 42 --target 1000000` (Plan 00-02).
    If missing, skip the test with actionable instructions.
    """
    if not BENCH_CORPUS.exists():
        pytest.skip(
            f"Missing {BENCH_CORPUS}. Run: "
            "uv run folio-insights bench gen --seed 42 --target 1000000 "
            "--out fixtures/bench.nq"
        )
    return BENCH_CORPUS


@pytest.fixture(scope="session")
def bench_store(bench_1m_corpus: Path):
    """pyoxigraph.Store pre-loaded + optimized (Gate 2 tuning steps 1-2 from
    RESEARCH.md Gate-Tuning Playbook Gate 2).

    session-scoped: bulk_load at 1M is expensive; reuse across all Gate 2
    assertions in a single pytest run.
    """
    from pyoxigraph import RdfFormat, Store

    store = Store(path=None)  # in-memory for tests (RocksDB temp for Phase 13)
    with open(bench_1m_corpus, "rb") as f:
        store.bulk_load(f, format=RdfFormat.N_QUADS)
    store.optimize()  # RocksDB compaction + index merge
    return store


@pytest.fixture
def seeded_rng() -> random.Random:
    """Per-test seeded RNG (D-15 determinism per Pitfall 7).

    Always an explicit Random(seed) instance. Never use module-level
    random.choice() or a NumPy RNG in tests or the generator.
    """
    return random.Random(42)
