"""Closure admission, verified-prefix reuse and nightly RDF round trips."""
import hashlib
import json
from dataclasses import replace
from datetime import timedelta

import jcs
from pyoxigraph import Store

from folio_insights.closure import declarations
from folio_insights.closure.declarations import load_declarations, submit_declaration
from folio_insights.governance.clock import parse_committed_at
from folio_insights.query.closed_world import CLOSED_UNDER, ClosedWorldQuery, ClosedWorldScope
from folio_insights.storage import CorpusStorageContext
from folio_insights.storage import context as context_module
from folio_insights.storage.dump import restore_ttl_dump, run_ttl_dump
from folio_insights.storage.exports import build_export_dataset, canonical_quads
from folio_insights.storage.projection import closure_graph
from tests.query.test_closure_declarations import declaration, seeded
from tests.storage.conftest import shard

FI = "https://folio-insights.aleainstitute.ai/vocab/"
SCOPE = ClosedWorldScope("urn:test:review-scope", frozenset({FI + "Shard"}),
                         frozenset({FI + "dependsOnShard"}))


async def test_clock_rollback_cannot_commit_an_immediately_invalid_closure(tmp_path, monkeypatch):
    ctx, admin = await seeded(tmp_path)
    async with ctx:
        head = await ctx.journal_head()
        row = await ctx._journal.row_at(ctx.corpus, head)
        prefix_time = parse_committed_at(row.committed_at)
        rolled_back = prefix_time - timedelta(seconds=30)
        monkeypatch.setattr(context_module, "_server_now", lambda: rolled_back)
        signed = await declaration(ctx, admin, scope=SCOPE, signed_at=rolled_back)
        entry = await submit_declaration(ctx, signed)
        assert parse_committed_at(entry.committed_at) >= prefix_time
        assert (await load_declarations(ctx)).active == (signed,)
        assert await submit_declaration(ctx, signed) == entry


async def test_warm_reads_reuse_history_until_a_verified_prefix_changes(tmp_path, monkeypatch):
    ctx, admin = await seeded(tmp_path)
    async with ctx:
        await submit_declaration(ctx, await declaration(ctx, admin, scope=SCOPE))
        await ctx.ingest_shards([shard(3)])
        await submit_declaration(ctx, await declaration(ctx, admin, op_id="current", scope=SCOPE))
        calls = []
        original = declarations._members_at

        async def counted(context, head):
            calls.append(head)
            return await original(context, head)

        monkeypatch.setattr(declarations, "_members_at", counted)
        query = ClosedWorldQuery(ctx)
        for _ in range(2):
            assert (await query.count_related(shard(1).shard_iri, FI + "dependsOnShard")).is_complete
        assert calls == []
        await ctx.proposals.append("note", {"tag": "synthetic"}, op_id="new-ledger-row")
        assert (await query.count_related(shard(1).shard_iri, FI + "dependsOnShard")).is_complete
        assert calls
        calls.clear()
        await ctx.rebuild_projection()
        assert calls
        assert (await query.count_related(shard(1).shard_iri, FI + "dependsOnShard")).is_complete


async def test_cache_checks_same_height_ledger_content_and_corpus_isolation(tmp_path, monkeypatch):
    ctx, admin = await seeded(tmp_path)
    other, other_admin = await seeded(tmp_path, "corpus-b")
    async with ctx, other:
        original = await declaration(ctx, admin, scope=SCOPE)
        entry = await submit_declaration(ctx, original)
        await submit_declaration(other, await declaration(
            other, other_admin, scope=SCOPE, members=[shard(2).shard_iri],
        ))
        replacement = await declaration(ctx, admin, scope=SCOPE, op_id="replacement",
                                        members=[shard(2).shard_iri])
        payload = replacement.model_dump(mode="json")
        alternate = replace(entry, op_id=replacement.op_id, payload=payload,
                            payload_sha256=hashlib.sha256(jcs.canonicalize(payload)).hexdigest())

        async def alternate_entries(*args, **kwargs):
            return [alternate]

        query = ClosedWorldQuery(ctx)
        assert (await query.count_related(shard(1).shard_iri, FI + "dependsOnShard")).is_complete
        with monkeypatch.context() as patch:
            patch.setattr(ctx.proposals, "entries", alternate_entries)
            assert not (await query.count_related(shard(1).shard_iri, FI + "dependsOnShard")).is_complete
            assert (await query.count_related(shard(2).shard_iri, FI + "dependsOnShard")).is_complete
        assert (await query.count_related(shard(1).shard_iri, FI + "dependsOnShard")).is_complete
        assert not (await ClosedWorldQuery(other).count_related(
            shard(1).shard_iri, FI + "dependsOnShard",
        )).is_complete


async def test_nightly_dump_tracks_closure_replacement_and_invalidation(tmp_path):
    root, repo = tmp_path / "storage", tmp_path / "dump"
    ctx, admin = await seeded(root)
    async with ctx:
        await submit_declaration(ctx, await declaration(ctx, admin, scope=SCOPE))
        expected = (await build_export_dataset(ctx)).graph(closure_graph(ctx.corpus))
    await run_ttl_dump(root, repo, init=True)
    graph = closure_graph("corpus-a")

    def restored(name):
        destination = tmp_path / name
        counts = restore_ttl_dump(repo, destination)
        store = Store(str(destination))
        try:
            return counts, list(store.quads_for_pattern(None, None, None, graph))
        finally:
            del store

    counts, quads = restored("initial-rdf")
    assert canonical_quads(quads) == canonical_quads(expected)
    assert counts[graph.value] == 1
    async with await CorpusStorageContext.open(root, "corpus-a") as reopened:
        await submit_declaration(reopened, await declaration(
            reopened, admin, scope=SCOPE, op_id="replacement", members=[shard(2).shard_iri],
        ))
    assert (await run_ttl_dump(root, repo)).changed
    _, quads = restored("replacement-rdf")
    assert {(q.subject.value, q.predicate.value) for q in quads} == {
        (shard(2).shard_iri, CLOSED_UNDER),
    }
    async with await CorpusStorageContext.open(root, "corpus-a") as reopened:
        await reopened.ingest_shards([shard(3)])
    assert (await run_ttl_dump(root, repo)).changed
    counts, quads = restored("invalidated-rdf")
    assert counts[graph.value] == 0 and quads == []
    manifest = json.loads((repo / "corpora/corpus-a/manifest.json").read_text())
    assert any(e["graph"] == graph.value and e["statements"] == 0 for e in manifest["files"])
    assert not (await run_ttl_dump(root, repo)).changed
