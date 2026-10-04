"""U4: nightly TTL dump job with a local Git commit (disposable repository),
the dump-to-RDF restore, and the ``folio-insights storage`` CLI."""
from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from pyoxigraph import Store

from folio_insights.cli import cli
from folio_insights.storage import CorpusStorageContext, PiiRejected
from folio_insights.storage.dump import (
    DUMP_AUTHOR_EMAIL,
    DumpError,
    corpus_dirname,
    restore_ttl_dump,
    run_ttl_dump,
)
from folio_insights.storage.exports import build_export_dataset, canonical_quads
from folio_insights.storage.projection import TBOX_GRAPH

from tests.storage.conftest import genesis, new_identity, shard

pytestmark = pytest.mark.storage

PII_TEXT = "synthetic ssn 123-45-6789"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


async def _populate(root: Path) -> None:
    admin = new_identity()
    for corpus, numbers in (("corpus-a", range(1, 6)), ("corpus b/2", range(10, 13))):
        ctx = await CorpusStorageContext.open(root, corpus)
        try:
            await ctx.governance.append(genesis(corpus, admin))
            await ctx.ingest_shards([shard(n) for n in numbers])
            with pytest.raises(PiiRejected):
                await ctx.ingest_shards([shard(90, sense=PII_TEXT)])
        finally:
            await ctx.close()


async def test_dump_writes_ttl_and_a_visible_local_commit(tmp_path: Path) -> None:
    root, repo = tmp_path / "storage", tmp_path / "dump-repo"
    await _populate(root)
    first = await run_ttl_dump(root, repo, init=True,
                               now=datetime(2026, 10, 3, 2, 0, tzinfo=UTC))
    assert first.changed and first.commit
    assert first.corpora == {"corpus b/2": 3, "corpus-a": 5}
    log = git(repo, "log", "--format=%H|%ae|%s")
    assert log == f"{first.commit}|{DUMP_AUTHOR_EMAIL}|dump: 2 corpora at 2026-10-03T02:00:00Z"
    tracked = set(git(repo, "ls-files").splitlines())
    assert tracked == {
        "tbox.ttl",
        *(f"corpora/{corpus_dirname(c)}/{name}"
          for c in ("corpus-a", "corpus b/2")
          for name in ("abox.ttl", "governance.ttl", "manifest.json")),
    }
    assert git(repo, "status", "--porcelain") == ""

    # Deterministic: an unchanged corpus produces no new commit.
    again = await run_ttl_dump(root, repo)
    assert (again.changed, again.commit) == (False, None)
    assert len(git(repo, "log", "--format=%H").splitlines()) == 1

    ctx = await CorpusStorageContext.open(root, "corpus-a")
    await ctx.ingest_shards([shard(6)])
    await ctx.close()
    third = await run_ttl_dump(root, repo)
    assert third.changed and third.corpora["corpus-a"] == 6
    changed = git(repo, "show", "--name-only", "--format=", third.commit).splitlines()
    assert sorted(changed) == [
        "corpora/corpus-a/abox.ttl", "corpora/corpus-a/manifest.json"
    ]

    # Nothing refused reaches the dump repository, in any revision.
    history = git(repo, "log", "-p", "--all")
    assert PII_TEXT not in history and shard(90).shard_iri not in history


async def test_dump_restores_into_a_new_rdf_store(tmp_path: Path) -> None:
    root, repo = tmp_path / "storage", tmp_path / "dump-repo"
    await _populate(root)
    await run_ttl_dump(root, repo, init=True)
    loaded = restore_ttl_dump(repo, tmp_path / "rdf")
    with pytest.raises(DumpError, match="already exists"):
        restore_ttl_dump(repo, tmp_path / "rdf")
    store = Store(str(tmp_path / "rdf"))
    try:
        for corpus in ("corpus-a", "corpus b/2"):
            ctx = await CorpusStorageContext.open(root, corpus)
            try:
                dataset = await build_export_dataset(ctx)
            finally:
                await ctx.close()
            for graph in (dataset.abox, dataset.governance, TBOX_GRAPH):
                expected = dataset.graph(graph)
                got = list(store.quads_for_pattern(None, None, None, graph))
                assert canonical_quads(got) == canonical_quads(expected), graph
                assert loaded[graph.value] == len(expected)
    finally:
        del store


async def test_dump_repository_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    await _populate(root)
    with pytest.raises(DumpError, match="does not exist"):
        await run_ttl_dump(root, tmp_path / "missing")
    outer = tmp_path / "outer"
    outer.mkdir()
    git(outer, "init", "--quiet")
    (outer / "inner").mkdir()
    with pytest.raises(DumpError, match="its own work tree"):
        await run_ttl_dump(root, outer / "inner", init=True)
    with pytest.raises(DumpError, match="overlap"):
        await run_ttl_dump(root, root / "dumps", init=True)
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(DumpError, match="not a Git repository"):
        await run_ttl_dump(root, plain)
    with pytest.raises(DumpError, match="no journaled corpus"):
        await run_ttl_dump(root, tmp_path / "r", init=True, corpora=["nope"])


def test_storage_cli_end_to_end(tmp_path: Path) -> None:
    import asyncio

    root = tmp_path / "storage"
    asyncio.run(_populate(root))
    runner = CliRunner()
    base = ["--corpus-root", str(root)]

    out = runner.invoke(cli, ["storage", "dump", "--repo", str(tmp_path / "repo"), "--init",
                              *base])
    assert out.exit_code == 0, out.output
    dumped = json.loads(out.output)
    assert dumped["changed"] and dumped["commit"] == git(tmp_path / "repo", "rev-parse", "HEAD")

    out = runner.invoke(cli, ["storage", "export", "corpus-a", "--out", str(tmp_path / "x"),
                              *base])
    assert out.exit_code == 0, out.output
    assert set(json.loads(out.output)["formats"]) == {
        "combined.ttl", "abox", "tbox.ttl", "governance.ttl", "jsonld", "nquads", "neo4j"
    }
    out = runner.invoke(cli, ["storage", "export", "corpus-a", "--out", str(tmp_path / "y"),
                              "--format", "combined.ttl", "--require-named-graphs", *base])
    assert out.exit_code == 1 and "ExportRefused" in out.output

    out = runner.invoke(cli, ["storage", "snapshot", "--out", str(tmp_path / "snap"), *base])
    assert out.exit_code == 0, out.output
    out = runner.invoke(cli, ["storage", "restore", str(tmp_path / "snap"), "--to",
                              str(tmp_path / "restored")])
    assert out.exit_code == 0, out.output
    assert json.loads(out.output)["corpora"] == {"corpus b/2": 3, "corpus-a": 5}
    out = runner.invoke(cli, ["storage", "restore", str(tmp_path / "snap"), "--to",
                              str(tmp_path / "restored")])
    assert out.exit_code == 1 and "RestoreRefused" in out.output

    out = runner.invoke(cli, ["storage", "status", "corpus-a", "--corpus-root",
                              str(tmp_path / "restored")])
    assert out.exit_code == 0, out.output
    status = json.loads(out.output)
    assert status["journal_head"] == status["projection_watermark"] == 5
    assert status["full_shacl"] == "deferred-to-phase-11"
