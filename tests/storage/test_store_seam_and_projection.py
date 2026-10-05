"""Typed corpus-scoped ShardStore seam (both backends) and the RDF projection."""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from folio_insights.revision import InMemoryShardStore, edit_shard_content, get_shard_at
from folio_insights.revision.store import DEPENDENCY_FIELDS, ShardStore
from folio_insights.storage import (
    FULL_SHACL_STATES,
    CorpusStorageContext,
    ShardIdentityViolation,
    StorageConfig,
)
from folio_insights.storage.projection import DEPENDENCY_PREDICATES, corpus_graph
from folio_insights.store.pyoxigraph_store import ServiceClauseBlocked

from tests.storage.conftest import shard

pytestmark = pytest.mark.storage

FI = "https://folio-insights.aleainstitute.ai/vocab/"


@pytest_asyncio.fixture(params=["memory", "persistent"])
async def any_store(request, storage_root: Path) -> AsyncIterator[ShardStore]:
    if request.param == "memory":
        yield InMemoryShardStore(corpus="corpus-a")
        return
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        yield ctx.shards
    finally:
        await ctx.close()


async def test_typed_seam_on_both_backends(any_store: ShardStore) -> None:
    assert isinstance(any_store, ShardStore)
    assert any_store.corpus == "corpus-a"
    base = shard(1)
    deps = [
        shard(2, depends_on_shards=[base.shard_iri]),
        shard(3, depends_on_precedents=[base.shard_iri]),
        shard(4, depends_on_axioms=["urn:x:unrelated"]),
        shard(5, depends_on_definitions=[base.shard_iri], depends_on_axioms=[base.shard_iri]),
    ]
    for s in [deps[2], base, *deps]:
        await any_store.put(s.shard_iri, s)
    listed = [s.shard_iri async for s in any_store.iter_shards()]
    assert listed == sorted({base.shard_iri, *(d.shard_iri for d in deps)})
    got = [s.shard_iri for s in await any_store.dependents_of(base.shard_iri)]
    assert got == sorted([deps[0].shard_iri, deps[1].shard_iri, deps[3].shard_iri])
    assert await any_store.dependents_of("urn:folio:shard/none") == []

    # A revision that drops the dependency removes it from the answer.
    revised = shard(2)
    await any_store.put(revised.shard_iri, revised)
    got = [s.shard_iri for s in await any_store.dependents_of(base.shard_iri)]
    assert deps[0].shard_iri not in got


async def test_revision_history_works_on_persistent_store(ctx: CorpusStorageContext) -> None:
    s = shard(1)
    await ctx.shards.put(s.shard_iri, s)
    await edit_shard_content(s.shard_iri, "sense", "v2", "did:key:zEditor", "r", None, ctx.shards)
    await edit_shard_content(s.shard_iri, "reference", "urn:x:v3", "did:key:zEditor", "r", None, ctx.shards)
    current = await ctx.shards.get(s.shard_iri)
    assert (current.sense, current.reference) == ("v2", "urn:x:v3")
    original = await get_shard_at(s.shard_iri, s.extracted_at, ctx.shards)
    assert (original.sense, original.reference) == (s.sense, s.reference)


async def test_frozen_identity_and_append_only_lists_hold_across_revisions(
    ctx: CorpusStorageContext,
) -> None:
    s = shard(1)
    await ctx.shards.put(s.shard_iri, s)
    await edit_shard_content(s.shard_iri, "sense", "v2", "did:key:zEditor", "r", None, ctx.shards)
    with pytest.raises(ShardIdentityViolation, match="source_span"):
        await ctx.shards.put(s.shard_iri, shard(1, source_span="different span"))
    with pytest.raises(ShardIdentityViolation, match="content_edits"):
        await ctx.shards.put(s.shard_iri, shard(1))  # drops the recorded edit
    with pytest.raises(ShardIdentityViolation, match="does not match"):
        await ctx.shards.put("urn:folio:shard/other", s)
    assert (await ctx.status()).journal_head == 1


async def test_projection_carries_schema_version_and_named_graphs(
    ctx: CorpusStorageContext,
) -> None:
    s = shard(1, depends_on_shards=["urn:x:dep"])
    await ctx.shards.put(s.shard_iri, s)
    rows = await ctx.query(
        f"SELECT ?g ?v WHERE {{ GRAPH ?g {{ <{s.shard_iri}> <{FI}schemaVersion> ?v }} }}"
    )
    assert [(r["g"].value, int(r["v"].value)) for r in rows] == [
        (corpus_graph("corpus-a").value, 2)
    ]
    assert await ctx.query(f"ASK {{ <{s.shard_iri}> <{FI}dependsOnShard> <urn:x:dep> }}")
    assert set(DEPENDENCY_PREDICATES) == set(DEPENDENCY_FIELDS)


async def test_bad_queries_refuse_without_closing_context(ctx: CorpusStorageContext) -> None:
    with pytest.raises(ServiceClauseBlocked):
        await ctx.query("SELECT * WHERE { SERVICE <http://169.254.169.254/> { ?s ?p ?o } }")
    with pytest.raises(SyntaxError):
        await ctx.query("SELECT WHERE {")
    assert not ctx.closed
    assert (await ctx.status()).full_shacl in FULL_SHACL_STATES


async def test_phase11_validator_hook_runs_before_append(storage_root: Path) -> None:
    seen: list[str] = []

    def _refuse_hypotheticals(s) -> None:  # noqa: ANN001
        seen.append(s.shard_iri)
        if s.sense.startswith("refuse"):
            raise ValueError("synthetic shape violation")

    ctx = await CorpusStorageContext.open(
        storage_root, "corpus-a", config=StorageConfig(shard_validator=_refuse_hypotheticals)
    )
    try:
        ok, bad = shard(1), shard(2, sense="refuse me")
        await ctx.shards.put(ok.shard_iri, ok)
        with pytest.raises(ValueError, match="synthetic shape violation"):
            await ctx.shards.put(bad.shard_iri, bad)
        assert seen == [ok.shard_iri, bad.shard_iri]
        assert (await ctx.status()).journal_head == 0
    finally:
        await ctx.close()


async def test_stale_adapter_version_rebuilds_from_journal(storage_root: Path) -> None:
    from folio_insights.storage.projection import META_GRAPH, ProjectionHandle

    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    s = shard(1)
    await ctx.shards.put(s.shard_iri, s)
    expected = await ctx.query("SELECT ?p ?o WHERE { ?s ?p ?o } ORDER BY ?p ?o")
    await ctx.close()

    handle = ProjectionHandle(storage_root)
    try:
        node = corpus_graph("corpus-a")
        handle._wrapper.store.update(
            f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {node} <{FI}adapterVersion> ?v }} }} ;\n"
            f"INSERT DATA {{ GRAPH {META_GRAPH} {{ {node} <{FI}adapterVersion> 0 }} }} ;\n"
            f"INSERT DATA {{ GRAPH {node} {{ <urn:x:stale> <urn:x:p> 1 }} }}"
        )
        assert handle.state("corpus-a").adapter_version == 0
    finally:
        handle.close()

    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        assert await ctx.query("SELECT ?p ?o WHERE { ?s ?p ?o } ORDER BY ?p ?o") == expected
    finally:
        await ctx.close()
    handle = ProjectionHandle(storage_root)
    try:
        assert handle.state("corpus-a").adapter_version == 1
    finally:
        handle.close()
