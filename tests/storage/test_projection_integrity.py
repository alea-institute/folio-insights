"""U4: watermark digest recovery, the shared TBox graph and named-graph
partitioning (Phase 13 exit criterion 2)."""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest
from pyoxigraph import BlankNode

from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.journal import JOURNAL_FILENAME
from folio_insights.storage.projection import (
    META_GRAPH,
    TBOX_GRAPH,
    ProjectionHandle,
    corpus_graph,
    governance_graph,
    tbox_quads,
)

from tests.storage.conftest import genesis, shard

pytestmark = pytest.mark.storage

FI = "https://folio-insights.aleainstitute.ai/vocab/"
_SUBJECTS = f"SELECT DISTINCT ?s WHERE {{ ?s a <{FI}Shard> }} ORDER BY ?s"


async def _subjects(ctx: CorpusStorageContext) -> list[str]:
    return [r["s"].value for r in await ctx.query(_SUBJECTS)]


def _copy_journal(src: Path, dst: Path) -> None:
    for old in dst.glob(f"{JOURNAL_FILENAME}*"):
        old.unlink()
    for path in src.glob(f"{JOURNAL_FILENAME}*"):
        shutil.copy2(path, dst / path.name)


async def test_same_length_journal_with_different_content_is_detected(tmp_path: Path) -> None:
    """The review nit: recovery used to compare positions only. A journal of the
    same length but different content now fails the watermark digest and the
    projection is rebuilt from it instead of serving the old quads."""
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    ctx_a = await CorpusStorageContext.open(root_a, "corpus-a")
    await ctx_a.ingest_shards([shard(n) for n in (1, 2, 3)])
    assert len(await _subjects(ctx_a)) == 3
    await ctx_a.close()
    ctx_b = await CorpusStorageContext.open(root_b, "corpus-a")
    await ctx_b.ingest_shards([shard(n) for n in (7, 8, 9)])
    expected = await _subjects(ctx_b)
    await ctx_b.close()

    _copy_journal(root_b, root_a)  # same positions 0..2, different rows
    handle = ProjectionHandle(root_a)
    try:
        stale = handle.state("corpus-a")
        assert stale.watermark == 2 and stale.payload_sha256 is not None
    finally:
        handle.close()

    ctx = await CorpusStorageContext.open(root_a, "corpus-a")
    try:
        assert await _subjects(ctx) == expected
        status = await ctx.status()
        assert status.journal_head == status.projection_watermark == 2
    finally:
        await ctx.close()
    with sqlite3.connect(root_a / JOURNAL_FILENAME) as conn:
        (row_sha,) = conn.execute(
            "SELECT payload_sha256 FROM journal WHERE corpus = 'corpus-a' AND position = 2"
        ).fetchone()
    handle = ProjectionHandle(root_a)
    try:
        assert handle.state("corpus-a").payload_sha256 == row_sha != stale.payload_sha256
    finally:
        handle.close()


async def test_projection_without_digest_is_rebuilt_once(storage_root: Path) -> None:
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    await ctx.ingest_shards([shard(1), shard(2)])
    expected = await ctx.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o } ORDER BY ?s ?p ?o")
    await ctx.close()

    handle = ProjectionHandle(storage_root)
    try:
        node = corpus_graph("corpus-a")
        handle.store.update(
            f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {node} <{FI}appliedPayloadSha256> ?h }} }} ;\n"
            f"INSERT DATA {{ GRAPH {node} {{ <urn:x:pre-u4> <urn:x:p> 1 }} }}"
        )
        assert handle.state("corpus-a").payload_sha256 is None
    finally:
        handle.close()

    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        got = await ctx.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o } ORDER BY ?s ?p ?o")
        assert got == expected  # the unjournaled quad is gone: rebuilt
    finally:
        await ctx.close()


async def test_named_graph_partitioning_with_shared_tbox(tmp_path: Path, admin) -> None:
    root = tmp_path / "storage"
    a = await CorpusStorageContext.open(root, "corpus-a")
    b = await CorpusStorageContext.open(root, "corpus-b")
    try:
        await a.governance.append(genesis("corpus-a", admin))
        await a.ingest_shards([shard(1), shard(2)])
        await b.ingest_shards([shard(3)])

        graphs = "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } } ORDER BY ?g"
        with_tbox = {r["g"].value for r in await a.query(graphs, include_tbox=True)}
        assert with_tbox == {
            corpus_graph("corpus-a").value,
            governance_graph("corpus-a").value,
            TBOX_GRAPH.value,
        }
        assert {r["g"].value for r in await a.query(graphs)} == {
            corpus_graph("corpus-a").value,
            governance_graph("corpus-a").value,
        }
        assert {r["g"].value for r in await b.query(graphs, include_tbox=True)} == {
            corpus_graph("corpus-b").value,
            TBOX_GRAPH.value,
        }
        # Cross-graph query: an ABox shard type resolved against the TBox class.
        joined = await a.query(
            f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ "
            f"GRAPH <{corpus_graph('corpus-a').value}> {{ ?s a <{FI}Shard> }} "
            f"GRAPH <{TBOX_GRAPH.value}> {{ ?c ?p ?o }} }}",
            include_tbox=True,
        )
        assert int(joined[0]["n"].value) == 2
        # The TBox is one shared graph: identical quads from either corpus.
        tbox = f"SELECT ?s ?p ?o WHERE {{ GRAPH <{TBOX_GRAPH.value}> {{ ?s ?p ?o }} }}"
        rows_a = await a.query(tbox, include_tbox=True)
        rows_b = await b.query(tbox, include_tbox=True)
        assert len(rows_a) == len(rows_b) == len(tbox_quads())
    finally:
        await a.close()
        await b.close()


def test_tbox_blank_nodes_are_deterministic() -> None:
    first, second = tbox_quads(), tbox_quads()
    assert first == second
    labels = {
        term.value
        for q in first
        for term in (q.subject, q.object)
        if isinstance(term, BlankNode)
    }
    assert labels and all(label.startswith("tbox-") for label in labels)


async def test_tbox_reloads_when_vocab_digest_changes(storage_root: Path) -> None:
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    await ctx.close()
    handle = ProjectionHandle(storage_root)
    try:
        digest = handle.tbox_digest()
        assert digest is not None
        handle.store.update(
            f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ ?n <{FI}tboxDigest> ?d }} }} ;\n"
            f"INSERT DATA {{ GRAPH {META_GRAPH} {{ <urn:folio-insights:storage:projection#tbox> "
            f"<{FI}tboxDigest> \"stale\" }} }} ;\n"
            f"INSERT DATA {{ GRAPH <{TBOX_GRAPH.value}> {{ <urn:x:stale> <urn:x:p> 1 }} }}"
        )
    finally:
        handle.close()
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        stale = await ctx.query(
            f"ASK {{ GRAPH <{TBOX_GRAPH.value}> {{ <urn:x:stale> ?p ?o }} }}", include_tbox=True
        )
        assert stale is False
    finally:
        await ctx.close()
    handle = ProjectionHandle(storage_root)
    try:
        assert handle.tbox_digest() == digest
        assert len(handle.graph_quads(TBOX_GRAPH)) == len(tbox_quads())
    finally:
        handle.close()


async def test_rebuild_with_two_revisions_of_one_shard_in_a_batch(storage_root: Path) -> None:
    """A batch holding several revisions of one shard applies only the last
    one, with the same result as applying them one by one. The old per-row
    INSERT / DELETE WHERE / INSERT sequence inside one update failed on
    pyoxigraph 0.5.7 (RocksDB: "Not able to find the string ... in the string
    store") when rebuilding a restored projection; the end-to-end reproducer
    is ``test_snapshot_restore.py::test_snapshot_restore_matches_original``
    (``rebuild_projection=True``)."""
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        await ctx.shards.put(shard(1).shard_iri, shard(1))
        await ctx.shards.put(shard(1).shard_iri, shard(1, sense="second"))
        await ctx.shards.put(shard(1).shard_iri, shard(1, sense="third"))
        live = await ctx.query("SELECT ?p ?o WHERE { ?s ?p ?o }")
        assert await ctx.rebuild_projection() == 2
        rebuilt = await ctx.query("SELECT ?p ?o WHERE { ?s ?p ?o }")
        key = sorted((str(r["p"]), str(r["o"])) for r in live)
        assert sorted((str(r["p"]), str(r["o"])) for r in rebuilt) == key
        senses = [r["o"].value for r in rebuilt if r["p"].value == f"{FI}sense"]
        assert senses == ["third"]
    finally:
        await ctx.close()
