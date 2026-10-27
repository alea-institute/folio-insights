"""Persisted closure and coherent count snapshots over synthetic corpus records."""
from __future__ import annotations

import pytest

from folio_insights.closure.declarations import submit_declaration
from folio_insights.query.closed_world import CLOSED_UNDER, ClosedWorldQuery, ClosedWorldScope
from folio_insights.storage import CorpusStorageContext
from tests.query.test_closure_declarations import declaration, seeded
from tests.storage.conftest import shard

FI = "https://folio-insights.aleainstitute.ai/vocab/"
SCOPE = ClosedWorldScope("urn:test:stored-scope", frozenset({FI + "Shard"}),
                         frozenset({FI + "dependsOnShard"}))


async def membership(ctx):
    rows = await ctx.query(f"SELECT ?s WHERE {{ ?s <{CLOSED_UNDER}> <{SCOPE.scope_iri}> }}")
    return {row["s"].value for row in rows}


async def test_declare_reopen_rebuild_and_unchanged_signed_bytes(tmp_path):
    ctx, admin = await seeded(tmp_path)
    try:
        q = ClosedWorldQuery(ctx)
        assert (await q.count_related(shard(1).shard_iri, FI + "dependsOnShard")).world_assumption == "open"
        before = await ctx.shards.get_record(shard(1).shard_iri)
        signed = await declaration(ctx, admin, scope=SCOPE,
                                   members=[shard(1).shard_iri, shard(2).shard_iri])
        await submit_declaration(ctx, signed)
        assert await membership(ctx) == set(signed.members)
        related = await q.count_related(shard(1).shard_iri, FI + "dependsOnShard")
        assert (related.world_assumption, related.count) == ("closed", 0)
        lacking = await q.count_lacking(FI + "Shard", FI + "dependsOnShard", SCOPE.scope_iri)
        assert (lacking.world_assumption, lacking.count, lacking.total_instances) == ("closed", 2, 2)
        await ctx.rebuild_projection()
        assert await membership(ctx) == set(signed.members)
        after = await ctx.shards.get_record(shard(1).shard_iri)
        assert (after.payload, after.original_bytes) == (before.payload, before.original_bytes)
    finally:
        await ctx.close()
    async with await CorpusStorageContext.open(tmp_path, "corpus-a") as reopened:
        assert await membership(reopened) == set(signed.members)
        assert (await ClosedWorldQuery(reopened).count_lacking(
            FI + "Shard", FI + "dependsOnShard", SCOPE.scope_iri)).count == 2
