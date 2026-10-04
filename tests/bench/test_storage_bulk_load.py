"""Phase 13 exit criterion 1: bulk load >= 200K triples/sec at 1M triples.

The load goes through the authoritative path, ``CorpusStorageContext
.bulk_load_shards`` (PII gate, U17 adapter validation, one journal
transaction, then the projection catch-up), not a bare ``Store.bulk_load``
of ``fixtures/bench.nq``: that file is RDF, not shard records, and loading
it into the projection would bypass the journal the projection is derived
from.

Fixture: 43,479 synthetic shards (deterministic, generated in-process; no
book or production content) projecting to 1,000,017 ABox triples. Each run
loads into a fresh storage root in the same process; the first run includes
process-pool start-up. Pass criterion: the median of three runs. Every run's
number is printed and, with ``FOLIO_INSIGHTS_BULK_BENCH_OUT`` set, written
as JSON so the plan can record it verbatim.

Marked ``slow`` (excluded from the quick suite). Run:
    pytest tests/bench/test_storage_bulk_load.py -m slow -s
"""
from __future__ import annotations

import json
import os
import platform
import statistics
import time
from pathlib import Path

import pytest

from folio_insights.storage import CorpusStorageContext

from tests.storage.conftest import shard

pytestmark = [pytest.mark.slow, pytest.mark.storage]

SHARDS = 43_479
TARGET_TRIPLES_PER_SEC = 200_000
RUNS = 3


def _hardware() -> dict[str, object]:
    cpu = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
        mem_kb = next(
            int(line.split()[1])
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemTotal")
        )
    except (OSError, StopIteration, ValueError):
        mem_kb = 0
    import pyoxigraph

    return {
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "mem_gib": round(mem_kb / 1024 / 1024, 1),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "pyoxigraph": pyoxigraph.__version__,
    }


@pytest.mark.timeout(600)
async def test_bulk_load_meets_200k_triples_per_second(tmp_path: Path) -> None:
    records = [shard(n) for n in range(SHARDS)]
    runs: list[dict[str, float]] = []
    triples = 0
    for run in range(RUNS):
        ctx = await CorpusStorageContext.open(tmp_path / f"run-{run}", "bench")
        try:
            started = time.perf_counter()
            result = await ctx.bulk_load_shards(records, op_id=f"bench-{run}")
            elapsed = time.perf_counter() - started
            assert result.records == SHARDS
            rows = await ctx.query(
                "SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }"
            )
            triples = int(rows[0]["n"].value)
            started = time.perf_counter()
            await ctx.rebuild_projection()
            rebuild = time.perf_counter() - started
        finally:
            await ctx.close()
        runs.append({
            "seconds": round(elapsed, 3),
            "triples_per_sec": round(triples / elapsed),
            # rebuild_projection = drop the corpus graphs (pyoxigraph deletes
            # are transactional, ~15 us/quad) + replay; recorded, not gated.
            "rebuild_seconds": round(rebuild, 3),
            "rebuild_triples_per_sec": round(triples / rebuild),
        })
    median = statistics.median(r["triples_per_sec"] for r in runs)
    report = {
        "fixture": {"shards": SHARDS, "projected_triples": triples},
        "path": "CorpusStorageContext.bulk_load_shards (journal + projection)",
        "runs": runs,
        "median_triples_per_sec": median,
        "target": TARGET_TRIPLES_PER_SEC,
        "hardware": _hardware(),
    }
    print(json.dumps(report, indent=2))
    out = os.environ.get("FOLIO_INSIGHTS_BULK_BENCH_OUT")
    if out:
        Path(out).write_text(json.dumps(report, indent=2) + "\n")
    assert triples == 1_000_017
    assert median >= TARGET_TRIPLES_PER_SEC, report
