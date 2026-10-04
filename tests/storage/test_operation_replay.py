"""Operation-ID replay protection: retries return the committed result once."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from folio_insights.storage import CorpusStorageContext, OperationIdConflict

from tests.storage.conftest import at, genesis, new_identity, role_assertion, shard

pytestmark = pytest.mark.storage


async def test_governance_retry_returns_same_event(ctx: CorpusStorageContext, admin) -> None:
    first = await ctx.governance.append(genesis("corpus-a", admin), op_id="op-genesis")
    again = await ctx.governance.append(genesis("corpus-a", admin), op_id="op-genesis")
    assert again == first
    assert await ctx.governance.latest_position("corpus-a") == 0
    assert (await ctx.status()).journal_head == 0


async def test_identical_signed_event_is_not_duplicated_by_default(
    ctx: CorpusStorageContext, admin
) -> None:
    await ctx.governance.append(genesis("corpus-a", admin))
    event = role_assertion("corpus-a", admin, new_identity().did, "reviewer", at(1))
    first = await ctx.governance.append(event)
    second = await ctx.governance.append(event)
    assert first == second and first.position == 1
    assert await ctx.governance.latest_position("corpus-a") == 1


async def test_reused_operation_id_for_different_request_is_refused(
    ctx: CorpusStorageContext, admin
) -> None:
    await ctx.governance.append(genesis("corpus-a", admin))
    a = role_assertion("corpus-a", admin, new_identity().did, "reviewer", at(1))
    b = role_assertion("corpus-a", admin, new_identity().did, "reviewer", at(2))
    await ctx.governance.append(a, op_id="op-1")
    with pytest.raises(OperationIdConflict):
        await ctx.governance.append(b, op_id="op-1")
    assert await ctx.governance.latest_position("corpus-a") == 1


async def test_shard_put_retry_commits_once(ctx: CorpusStorageContext) -> None:
    s = shard(1)
    await ctx.shards.put(s.shard_iri, s, op_id="put-1")
    await ctx.shards.put(s.shard_iri, s, op_id="put-1")
    assert (await ctx.status()).journal_head == 0
    changed = shard(1, sense="different")
    with pytest.raises(OperationIdConflict):
        await ctx.shards.put(changed.shard_iri, changed, op_id="put-1")


async def test_reverting_put_is_a_new_revision(ctx: CorpusStorageContext) -> None:
    """Without an explicit op_id, A -> B -> A writes three revisions."""
    a, b = shard(1, sense="first"), shard(1, sense="second")
    for s in (a, b, a):
        await ctx.shards.put(s.shard_iri, s)
    assert (await ctx.status()).journal_head == 2
    assert (await ctx.shards.get(a.shard_iri)).sense == "first"


async def test_bulk_ingest_retry_commits_once(storage_root: Path) -> None:
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    records = [json.loads(shard(i).model_dump_json()) for i in range(3)]
    for record in records:
        del record["schema_version"]  # legacy v1 input
    try:
        first = await ctx.ingest_shards(records, op_id="ingest-1")
        again = await ctx.ingest_shards(records, op_id="ingest-1")
        assert [s.shard_iri for s in again] == [s.shard_iri for s in first]
        assert (await ctx.status()).journal_head == 2
        stored = await ctx.shards.get_record(first[0].shard_iri)
        assert stored is not None and stored.source_schema_version == 1
        assert json.loads(stored.original_bytes) == records[0]
    finally:
        await ctx.close()
