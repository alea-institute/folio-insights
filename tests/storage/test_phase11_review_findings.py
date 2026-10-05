"""Phase 11 review findings, storage side (each test failed before its fix).

* P1-1: a truncated failing list must never turn into ``full_shacl: pass``
  through an incremental write. Only ``validate_corpus`` clears it.
* P2-2: a post-commit marker failure never raises from a committed write.
  Status then reads ``unvalidated``.
* P2-5: retrying a committed explicit op_id replays it even when the suite
  would refuse the record. The suite judges new appends only.
* Nit: the full-validation Warning count is cleared, not left stale, after
  a later write.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from folio_insights.storage import ShaclViolation, context, shacl_status
from folio_insights.storage.shacl_status import MarkerStore
from tests.storage.conftest import open_ctx, shard

pytestmark = pytest.mark.storage

T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 6, 1, tzinfo=UTC)


def bad(n: int):  # noqa: ANN201
    return shard(n, valid_time_start=T2, valid_time_end=T1)


def good(n: int):  # noqa: ANN201
    return shard(n, valid_time_start=T1, valid_time_end=T2)


async def _legacy_corpus(root: Path, count: int) -> None:
    off = await open_ctx(root, shacl=None)
    try:
        await off.ingest_shards([bad(n) for n in range(count)])
    finally:
        await off.close()


@pytest.mark.parametrize("branch", ["complete", "focused"])
async def test_truncated_failing_list_never_reads_pass(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch, branch: str
) -> None:
    monkeypatch.setattr(shacl_status, "MAX_FAILING", 5)
    monkeypatch.setattr(context, "INCREMENTAL_FOCUS_LIMIT", 3 if branch == "complete" else 1000)
    await _legacy_corpus(storage_root, 12)
    ctx = await open_ctx(storage_root)
    try:
        result = await ctx.validate_corpus()
        assert result.violations == 12
        marker = MarkerStore(storage_root, "corpus-a").read()
        assert marker is not None and marker.failing_truncated and len(marker.failing) == 5
        listed = {e["focus"] for e in marker.failing}
        by_iri = {shard(n).shard_iri: n for n in range(12)}
        # Fix exactly the listed shards: 7 unlisted failures remain.
        await ctx.ingest_shards([good(by_iri[iri]) for iri in sorted(listed)])
        status = await ctx.status()
        assert status.full_shacl == "fail", status
        assert not (await ctx.validate_corpus()).conforms
        # Fix everything; only a full validation may clear truncation.
        await ctx.ingest_shards([good(n) for n in range(12)])
        assert (await ctx.status()).full_shacl == "fail"
        assert (await ctx.validate_corpus()).conforms
        assert (await ctx.status()).full_shacl == "pass"
    finally:
        await ctx.close()


async def test_post_commit_marker_failure_never_raises(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = await open_ctx(storage_root)
    try:
        await ctx.shards.put(shard(0).shard_iri, shard(0))

        def boom(self, fn):  # noqa: ANN001, ANN202
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(MarkerStore, "update", boom)
        await ctx.shards.put(shard(1).shard_iri, shard(1))  # committed: must not raise
        assert await ctx.shards.get(shard(1).shard_iri) is not None
        await ctx.ingest_shards([shard(2), shard(3)])
        monkeypatch.undo()
        status = await ctx.status()
        assert status.journal_head == 3
        assert status.full_shacl == "unvalidated"  # marker left behind, honestly
        assert (await ctx.validate_corpus()).conforms
        assert (await ctx.status()).full_shacl == "pass"
    finally:
        await ctx.close()


@pytest.mark.parametrize("path", ["put", "ingest", "bulk", "implicit_ingest"])
async def test_replaying_a_committed_op_skips_the_suite(storage_root: Path, path: str) -> None:
    records = [bad(n) for n in range(3)]
    off = await open_ctx(storage_root, shacl=None)
    try:
        if path == "put":
            await off.shards.put(records[0].shard_iri, records[0], op_id="op-1")
        elif path == "implicit_ingest":
            await off.ingest_shards(records)
        else:
            await off.ingest_shards(records, op_id="op-1")
    finally:
        await off.close()

    ctx = await open_ctx(storage_root)
    try:
        head = (await ctx.status()).journal_head
        if path == "put":
            await ctx.shards.put(records[0].shard_iri, records[0], op_id="op-1")
        elif path == "ingest":
            assert len(await ctx.ingest_shards(records, op_id="op-1")) == 3
        elif path == "bulk":
            assert (await ctx.bulk_load_shards(records, op_id="op-1")).records == 3
        else:
            assert len(await ctx.ingest_shards(records)) == 3
        assert (await ctx.status()).journal_head == head  # nothing new appended
        # A NEW operation with the same refused content is still refused.
        with pytest.raises(ShaclViolation):
            await ctx.shards.put(records[0].shard_iri, records[0], op_id="op-2")
        with pytest.raises(ShaclViolation):
            await ctx.ingest_shards([bad(9)])
    finally:
        await ctx.close()


async def test_warning_count_is_cleared_after_a_later_write(storage_root: Path) -> None:
    ctx = await open_ctx(storage_root)
    try:
        await ctx.shards.put(shard(1).shard_iri, shard(1))  # unsigned: a Warning
        result = await ctx.validate_corpus()
        assert (await ctx.status()).shacl_warnings == result.warnings >= 1
        await ctx.shards.put(shard(2).shard_iri, shard(2))
        status = await ctx.status()
        assert status.full_shacl == "pass" and status.shacl_warnings is None
    finally:
        await ctx.close()


async def test_concurrent_writes_through_one_context_stay_validated(storage_root: Path) -> None:
    """Marker steps of one context run in commit order (conc.py probe)."""
    import asyncio

    ctx = await open_ctx(storage_root)
    try:
        await ctx.shards.put(shard(0).shard_iri, shard(0))
        for _ in range(3):
            base = (await ctx.status()).journal_head + 1
            await asyncio.gather(
                *(ctx.shards.put(shard(n).shard_iri, shard(n)) for n in range(base, base + 6)),
                ctx.ingest_shards([shard(n) for n in range(base + 100, base + 104)]),
            )
            status = await ctx.status()
            assert (status.full_shacl, status.shacl_validated_through) == ("pass", status.journal_head)
        assert not ctx._unmarked
    finally:
        await ctx.close()
