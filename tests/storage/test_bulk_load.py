"""U4 bulk-load path: add-only catch-up through ``Store.bulk_load``, the
process-parallel per-record checks, and their equivalence with the
transactional, in-process path."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import folio_insights.storage._parallel as parallel
import folio_insights.storage.projection as projection
from folio_insights.shards import dump_shard_record
from folio_insights.storage import (
    CorpusStorageContext,
    PiiRejected,
    ProjectionRecoveryFailed,
    ProjectionRecoveryPending,
)
from folio_insights.storage.journal import JOURNAL_FILENAME

from tests.storage.conftest import shard

pytestmark = pytest.mark.storage

_ALL = "SELECT ?g ?s ?p ?o WHERE { GRAPH ?g { ?s ?p ?o } }"
N = 2600  # above BULK_LOAD_MIN_ROWS and PARALLEL_MIN_ITEMS, below a second chunk


def _quads(rows: list[dict]) -> list[tuple[str, ...]]:
    return sorted(tuple(str(r[k]) for k in ("g", "s", "p", "o")) for r in rows)


async def _load(root: Path, records: list, **kwargs) -> list[tuple[str, ...]]:
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        await ctx.bulk_load_shards(records, **kwargs)
        return _quads(await ctx.query(_ALL))
    finally:
        await ctx.close()


class _BulkLoadSpy:
    """Counts ``bulk_load`` calls on a projection store. Module-level and
    closure-free, so dropping the handle frees the RocksDB store (and its
    lock) by reference counting, exactly as without the spy."""

    def __init__(self, store, seen: dict[str, int]) -> None:  # noqa: ANN001
        self._store = store
        self._seen = seen

    def __getattr__(self, name: str):  # noqa: ANN204
        return getattr(self._store, name)

    def bulk_load(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        self._seen["bulk_load"] += 1
        return self._store.bulk_load(*args, **kwargs)


@pytest.fixture(scope="module")
def records() -> list:
    return [
        shard(n, depends_on_shards=[shard(n - 1).shard_iri] if n % 7 == 0 and n else [])
        for n in range(N)
    ]


async def test_bulk_path_matches_transactional_and_rebuild(
    tmp_path: Path, records: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    bulk = await _load(tmp_path / "bulk", records)
    # 27 base triples per shard (adapter v2 adds fi:framework, fi:speechAct,
    # fi:bfoCategory, fi:subjectBfoClass), plus one dependsOnShard per 7th.
    assert len(bulk) == N * 27 + (N - 1) // 7

    # Same records with the bulk path disabled: one transactional update path.
    monkeypatch.setattr(projection, "BULK_LOAD_MIN_ROWS", 10**9)
    monkeypatch.setattr(parallel, "PARALLEL_MIN_ITEMS", 10**9)
    serial = await _load(tmp_path / "serial", records)
    assert serial == bulk

    # A rebuild from the journal reproduces the bulk-loaded projection.
    monkeypatch.undo()
    ctx = await CorpusStorageContext.open(tmp_path / "bulk", "corpus-a")
    try:
        assert await ctx.rebuild_projection() == N - 1
        assert _quads(await ctx.query(_ALL)) == bulk
        # Dependency edges answered from the bulk-loaded projection.
        deps = await ctx.shards.dependents_of(shard(6).shard_iri)
        assert [d.shard_iri for d in deps] == [shard(7).shard_iri]
    finally:
        await ctx.close()


async def test_bulk_load_uses_bulk_store_path_and_pool(
    tmp_path: Path, records: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, int] = {"bulk_load": 0, "pool_chunks": 0}
    real_map = parallel.map_chunks

    def counting_map(fn, items, *args, **kwargs):  # noqa: ANN001, ANN202
        seen["pool_chunks"] += len(items)
        return real_map(fn, items, *args, **kwargs)

    monkeypatch.setattr(parallel, "map_chunks", counting_map)
    import folio_insights.storage.context as context_module

    monkeypatch.setattr(context_module, "map_chunks", counting_map)
    real_handle_init = projection.ProjectionHandle.__init__

    def init(self, root):  # noqa: ANN001, ANN202
        real_handle_init(self, root)
        self._wrapper._store = _BulkLoadSpy(self._wrapper._store, seen)

    monkeypatch.setattr(projection.ProjectionHandle, "__init__", init)
    ctx = await CorpusStorageContext.open(tmp_path, "corpus-a")
    try:
        result = await ctx.bulk_load_shards(records, op_id="bulk-1")
        assert (result.records, result.first_position, result.last_position) == (N, 0, N - 1)
        assert result.op_id == "bulk-1"
        # Retrying the operation ID commits nothing new.
        again = await ctx.bulk_load_shards(records, op_id="bulk-1")
        assert again == result
        assert (await ctx.status()).journal_head == N - 1
    finally:
        await ctx.close()
    assert seen["bulk_load"] == 1
    assert seen["pool_chunks"] >= 2 * N  # prepare (twice: retry) and render


async def test_crash_between_bulk_load_and_watermark_recovers(
    tmp_path: Path, records: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = await _load(tmp_path / "clean", records)

    real_update = projection._watermark_update

    def failing_watermark(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise OSError("synthetic crash after bulk_load, before the watermark")

    monkeypatch.setattr(projection, "_watermark_update", failing_watermark)
    ctx = await CorpusStorageContext.open(tmp_path / "crash", "corpus-a")
    with pytest.raises(ProjectionRecoveryPending):
        await ctx.bulk_load_shards(records, op_id="bulk-crash")
    assert ctx.closed
    with pytest.raises(ProjectionRecoveryFailed):
        await CorpusStorageContext.open(tmp_path / "crash", "corpus-a")

    monkeypatch.setattr(projection, "_watermark_update", real_update)
    ctx = await CorpusStorageContext.open(tmp_path / "crash", "corpus-a")
    try:
        # Quads past the old watermark are replayed idempotently, not doubled.
        assert _quads(await ctx.query(_ALL)) == expected
        retried = await ctx.bulk_load_shards(records, op_id="bulk-crash")
        assert retried.last_position == N - 1
    finally:
        await ctx.close()


async def test_revisions_inside_a_large_batch_use_the_transactional_path(
    tmp_path: Path,
) -> None:
    first = [shard(n) for n in range(N)]
    revised = [shard(n, sense=f"revised sense {n}") for n in range(0, N, 2)]
    ctx = await CorpusStorageContext.open(tmp_path, "corpus-a")
    try:
        await ctx.bulk_load_shards(first)
        await ctx.bulk_load_shards(revised + [shard(N + 1)])
        senses = await ctx.query(
            "SELECT ?s ?v WHERE { ?s <https://folio-insights.aleainstitute.ai/vocab/sense> ?v }"
        )
        by_subject = {r["s"].value: r["v"].value for r in senses}
        assert len(by_subject) == N + 1  # one sense per subject: old quads replaced
        assert by_subject[shard(0).shard_iri] == "revised sense 0"
        assert by_subject[shard(1).shard_iri] == "synthetic sense 1"
        rebuilt_before = _quads(await ctx.query(_ALL))
        await ctx.rebuild_projection()
        assert _quads(await ctx.query(_ALL)) == rebuilt_before
    finally:
        await ctx.close()


async def test_parallel_prepare_raises_the_first_refusal_in_input_order(
    tmp_path: Path,
) -> None:
    raws = [json.loads(dump_shard_record(shard(n))) for n in range(N)]
    raws[2400]["sense"] = "call 212-555-0142 now"  # later chunk
    raws[1500]["source_span"] = "ssn 123-45-6789"  # earlier chunk: reported
    ctx = await CorpusStorageContext.open(tmp_path, "corpus-a")
    try:
        with pytest.raises(PiiRejected) as info:
            await ctx.bulk_load_shards(raws)
        assert (info.value.field_path, info.value.pattern_name) == ("source_span", "ssn")
        assert "123-45-6789" not in str(info.value)
        status = await ctx.status()
        assert (status.journal_head, status.projection_watermark) == (-1, -1)
    finally:
        await ctx.close()


async def test_pool_unavailable_falls_back_in_process(
    tmp_path: Path, records: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = await _load(tmp_path / "pool", records)
    monkeypatch.setattr(parallel, "_get_pool", lambda: None)
    assert await _load(tmp_path / "nopool", records) == expected


def test_pii_refusal_pickles_without_its_message() -> None:
    import pickle

    err = pickle.loads(pickle.dumps(PiiRejected("a.b", "ssn")))
    assert (err.field_path, err.pattern_name) == ("a.b", "ssn")


async def test_current_version_rows_store_null_original_bytes(storage_root: Path) -> None:
    legacy = json.loads(dump_shard_record(shard(2)))
    del legacy["schema_version"]  # legacy v1 input: original bytes differ
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        await ctx.ingest_shards([shard(1), legacy])
        current = await ctx.shards.get_record(shard(1).shard_iri)
        migrated = await ctx.shards.get_record(shard(2).shard_iri)
        assert current is not None and migrated is not None
        assert current.original_bytes == current.payload
        assert json.loads(migrated.original_bytes) == legacy
        assert migrated.original_bytes != migrated.payload
    finally:
        await ctx.close()
    with sqlite3.connect(storage_root / JOURNAL_FILENAME) as conn:
        nulls = conn.execute(
            "SELECT position, original_bytes IS NULL FROM journal ORDER BY position"
        ).fetchall()
    assert nulls == [(0, 1), (1, 0)]


async def test_quadratic_replace_guard_is_migrated(storage_root: Path) -> None:
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    await ctx.close()
    with sqlite3.connect(storage_root / JOURNAL_FILENAME) as conn:
        conn.execute("DROP TRIGGER journal_refuse_replace_v2")
        conn.execute(
            "CREATE TRIGGER journal_refuse_replace BEFORE INSERT ON journal "
            "WHEN 0 BEGIN SELECT 1; END"
        )
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    await ctx.close()
    with sqlite3.connect(storage_root / JOURNAL_FILENAME) as conn:
        names = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        }
        plan = " ".join(
            str(r)
            for r in conn.execute(
                "EXPLAIN QUERY PLAN SELECT 1 FROM journal WHERE corpus = 'x' AND op_id = 'y'"
            )
        )
    assert "journal_refuse_replace_v2" in names and "journal_refuse_replace" not in names
    assert "USING" in plan and "INDEX" in plan
