"""Phase 9 U0 / KTD3 — the adapter-version bump rebuilds projections cleanly.

A projection written by adapter version 1 (framework as a literal only, no
speech act or BFO class) must be rebuilt from the journal when a version-2
context opens it: framework links become IRIs, the new terms appear, and the
journal — payload bytes, original bytes and signatures — is untouched.
Disposable roots, generated identities, synthetic shards only.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.projection import (
    META_GRAPH,
    PROJECTION_ADAPTER_VERSION,
    ProjectionHandle,
    corpus_graph,
)
from folio_insights.vocab._constants import FI_PREFIX, FRAMEWORK_NS

from tests.storage.conftest import genesis, shard

FI = FI_PREFIX


def _journal_rows(path: Path) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT corpus, position, kind, subject, payload, original_bytes, payload_sha256 "
            "FROM journal ORDER BY corpus, position"
        ).fetchall()


def _downgrade_to_v1(root: Path, corpus: str) -> None:
    """Make the stored projection look like adapter version 1 wrote it."""
    handle = ProjectionHandle(root)
    try:
        node = corpus_graph(corpus)
        handle._wrapper.store.update(
            f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {node} <{FI}adapterVersion> ?v }} }} ;\n"
            f"INSERT DATA {{ GRAPH {META_GRAPH} {{ {node} <{FI}adapterVersion> 1 }} }} ;\n"
            f"DELETE WHERE {{ GRAPH {node} {{ ?s <{FI}framework> ?f }} }} ;\n"
            f"DELETE WHERE {{ GRAPH {node} {{ ?s <{FI}speechAct> ?a }} }} ;\n"
            f"DELETE WHERE {{ GRAPH {node} {{ ?s <{FI}bfoCategory> ?b }} }} ;\n"
            f"DELETE WHERE {{ GRAPH {node} {{ ?s <{FI}subjectBfoClass> ?c }} }}"
        )
        assert handle.state(corpus).adapter_version == 1
    finally:
        handle.close()


async def test_version_bump_rebuilds_with_framework_iris(storage_root: Path, admin) -> None:
    assert PROJECTION_ADAPTER_VERSION >= 2
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        await ctx.ingest_shards(
            [
                shard(1, framework_id="us.federal.fre", bfo_category="occurrent_event"),
                shard(2, framework_id="us.ucc", depends_on_shards=[f"urn:folio:shard/{1:032x}"]),
            ]
        )
        await ctx.governance.append(genesis("corpus-a", admin))
        journal = ctx.journal_path
    finally:
        await ctx.close()
    before = _journal_rows(journal)

    _downgrade_to_v1(storage_root, "corpus-a")

    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        rows = await ctx.query(
            f"SELECT ?s ?f WHERE {{ ?s <{FI}framework> ?f }} ORDER BY ?s"
        )
        assert [(r["s"].value, r["f"].value) for r in rows] == [
            (f"urn:folio:shard/{1:032x}", FRAMEWORK_NS + "us.federal.fre"),
            (f"urn:folio:shard/{2:032x}", FRAMEWORK_NS + "us.ucc"),
        ]
        assert all(type(r["f"]).__name__ == "NamedNode" for r in rows)
        spine = await ctx.query(
            f"SELECT ?c WHERE {{ <urn:folio:shard/{1:032x}> <{FI}subjectBfoClass> ?c }}"
        )
        assert [r["c"].value for r in spine] == [FI + "Process"]
        # the dependency web and governance survive the rebuild
        deps = await ctx.shards.dependents_of(f"urn:folio:shard/{1:032x}")
        assert [d.shard_iri for d in deps] == [f"urn:folio:shard/{2:032x}"]
        events = [e async for e in ctx.governance.iter_events("corpus-a")]
        assert [e.action for e in events] == ["role_assertion"]
    finally:
        await ctx.close()

    handle = ProjectionHandle(storage_root)
    try:
        assert handle.state("corpus-a").adapter_version == PROJECTION_ADAPTER_VERSION
    finally:
        handle.close()
    # Journal bytes (payload, original bytes, digests, signatures inside) unchanged.
    assert _journal_rows(journal) == before


async def test_explicit_rebuild_leaves_journal_and_signatures_unchanged(
    storage_root: Path, admin
) -> None:
    from folio_insights.storage.context import verify_event_signature_offline

    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        await ctx.ingest_shards([shard(n) for n in range(1, 4)])
        await ctx.governance.append(genesis("corpus-a", admin))
        before = _journal_rows(ctx.journal_path)
        first = await ctx.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o } ORDER BY ?s ?p ?o")
        await ctx.rebuild_projection()
        assert await ctx.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o } ORDER BY ?s ?p ?o") == first
        assert _journal_rows(ctx.journal_path) == before
        events = [e async for e in ctx.governance.iter_events("corpus-a")]
        assert events and all([await verify_event_signature_offline(e) for e in events])
    finally:
        await ctx.close()
