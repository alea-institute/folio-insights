"""Phase 11 exit criterion 4 / SHACL-03: per-shard incremental SHACL
validation P95 < 50 ms with a 1M-triple corpus loaded, shapes pre-compiled.

Setup: 43,479 synthetic shards (1,000,017 projected ABox triples, the bulk
benchmark's fixture) bulk-loaded with the suite on. Then 200 revisions, each
adding a supersession link so the corpus tier has real work. Per write, the
measured validation is exactly what a storage write runs:

* the local tier on the record (``check_shard_payload``);
* the corpus tier for that shard and its one-hop neighbours on the 1M
  projection (``ctx._corpus_tier``), including taking the projection lock.

The full ``shards.put`` latency (journal commit, projection catch-up,
validation, marker update) is recorded too but not gated. Marked ``slow``.

    pytest tests/bench/test_shacl_incremental.py -m slow -s
"""
from __future__ import annotations

import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from folio_insights.shards import dump_shard_record
from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.shacl_status import check_shard_payload
from tests.bench.test_storage_bulk_load import SHARDS, _hardware
from tests.storage.conftest import shard

pytestmark = [pytest.mark.slow, pytest.mark.storage]

TARGET_P95_MS = 50.0
SAMPLES = 200


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, round(0.95 * len(ordered)) - 1)]


@pytest.mark.timeout(600)
async def test_incremental_validation_p95_under_50ms_at_1m_triples(tmp_path: Path) -> None:
    ctx = await CorpusStorageContext.open(tmp_path / "root", "bench")
    try:
        started = time.perf_counter()
        await ctx.bulk_load_shards([shard(n) for n in range(SHARDS)], op_id="seed")
        load_s = time.perf_counter() - started
        rows = await ctx.query("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }")
        triples = int(rows[0]["n"].value)
        suite = ctx.config.shacl
        assert suite is not None

        validation_ms: list[float] = []
        local_ms: list[float] = []
        put_ms: list[float] = []
        for i in range(SAMPLES):
            n = 1000 + i
            revision = shard(
                n,
                supersedes=shard(20_000 + i).shard_iri,
                valid_time_start=datetime(2026, 1, 1, tzinfo=UTC),
            )
            payload = dump_shard_record(revision)
            t0 = time.perf_counter()
            check_shard_payload(payload, suite)
            t1 = time.perf_counter()
            await ctx._corpus_tier(suite, {revision.shard_iri})
            t2 = time.perf_counter()
            local_ms.append((t1 - t0) * 1e3)
            validation_ms.append((t2 - t0) * 1e3)
            t3 = time.perf_counter()
            await ctx.shards.put(revision.shard_iri, revision)
            put_ms.append((time.perf_counter() - t3) * 1e3)
        status = await ctx.status()
    finally:
        await ctx.close()

    report = {
        "fixture": {"shards": SHARDS, "projected_triples": triples, "load_seconds": round(load_s, 2)},
        "samples": SAMPLES,
        "validation_ms": {
            "p50": round(statistics.median(validation_ms), 3),
            "p95": round(_p95(validation_ms), 3),
            "max": round(max(validation_ms), 3),
        },
        "local_tier_ms": {"p50": round(statistics.median(local_ms), 3), "p95": round(_p95(local_ms), 3)},
        "put_ms_not_gated": {"p50": round(statistics.median(put_ms), 3), "p95": round(_p95(put_ms), 3)},
        "full_shacl_after": status.full_shacl,
        "target_p95_ms": TARGET_P95_MS,
        "hardware": _hardware(),
    }
    print(json.dumps(report, indent=2))
    out = os.environ.get("FOLIO_INSIGHTS_SHACL_BENCH_OUT")
    if out:
        Path(out).write_text(json.dumps(report, indent=2) + "\n")
    assert triples >= 1_000_000
    # Every revision supersedes a still-current shard: the corpus tier must say so.
    assert status.full_shacl == "fail"
    assert report["validation_ms"]["p95"] < TARGET_P95_MS, report
