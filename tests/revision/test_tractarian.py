"""Flat navigation replaces Tractarian paths; legacy metadata remains readable."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from folio_insights.revision.tractarian import TractarianIndex, TractarianRevision
from folio_insights.shards import dump_shard_record, load_shard_record
from folio_insights.storage import CorpusStorageContext
from tests.storage.conftest import shard


def iri(n: int) -> str:
    return f"urn:folio:shard/{n:032x}"


def test_flat_references_ignore_parent_cycles_and_axioms() -> None:
    shards = [shard(1, elaborates=[iri(2)]),
              shard(2, elaborates=[iri(1)], depends_on_axioms=[iri(3)]), shard(3)]
    index = TractarianIndex([(s, n) for n, s in enumerate(shards)])
    assert index.children() == [iri(1), iri(2), iri(3)]
    assert index.findings == ()
    assert index.path_of("missing") is index.iri_of("1.1") is None
    assert index.node("missing") is None
    assert index.children(iri(1)) == []
    assert all(n.path == n.iri and n.parent_iri is None and n.depth == 1
               for n in index.nodes())


def test_revisions_read_legacy_and_migrated_history_without_parent_navigation() -> None:
    original = shard(1, elaborates=[iri(2)])
    raw = dump_shard_record(original)
    migrated = load_shard_record(raw, target_schema_version=3).shard
    old = TractarianRevision.from_payload(0, iri(1), raw, "batch")
    new = TractarianRevision.from_payload(0, iri(1), dump_shard_record(migrated), "batch")
    assert old == new == TractarianRevision.of(migrated, 0, "batch")
    assert new.elaborates == (iri(2),)
    assert TractarianIndex([(migrated, 0)], [new]).path_of(iri(1)) == iri(1)


def test_duplicate_and_mismatched_history_are_refused() -> None:
    s = shard(1)
    with pytest.raises(ValueError, match="duplicate"):
        TractarianIndex([(s, 0), (s, 1)])
    with pytest.raises(ValueError, match="history does not match"):
        TractarianIndex([(s, 0)], [TractarianRevision.of(s, 1)])


async def test_context_references_survive_edits_and_late_arrivals(tmp_path: Path) -> None:
    ctx = await CorpusStorageContext.open(tmp_path / "s", "corpus-a")
    try:
        await ctx.ingest_shards([shard(2, elaborates=[iri(1)])])
        before = await TractarianIndex.from_context(ctx)
        await ctx.ingest_shards([shard(1)])
        await ctx.shards.put(iri(2), shard(2, elaborates=[iri(3)]), op_id="revision")
        after = await TractarianIndex.from_context(ctx)
        assert before.path_of(iri(2)) == after.path_of(iri(2)) == iri(2)
        assert after.children() == [iri(2), iri(1)]
        assert [(s.shard_iri, pos) for s, pos in await ctx.shards_in_commit_order()] == [
            (iri(2), 0), (iri(1), 1),
        ]
    finally:
        await ctx.close()


def test_cli_flat_path_and_tree(tmp_path: Path) -> None:
    from folio_insights.cli import cli

    root = tmp_path / "s"

    async def seed() -> None:
        ctx = await CorpusStorageContext.open(root, "corpus-a")
        try:
            await ctx.ingest_shards([shard(1), shard(2, elaborates=[iri(1)]), shard(3)])
        finally:
            await ctx.close()

    asyncio.run(seed())
    runner = CliRunner()
    base = ["--corpus-root", str(root)]
    result = runner.invoke(cli, ["graph", "path", "corpus-a", iri(2), *base])
    assert result.exit_code == 0 and result.output == f"{iri(2)}\t{iri(2)}\n"
    tree = runner.invoke(cli, ["graph", "tree", "corpus-a", "--json", *base])
    assert tree.exit_code == 0, tree.output
    body = json.loads(tree.output)
    assert body["shards"] == 3 and body["findings"] == []
    assert body["tree"] == [
        {"path": iri(n), "iri": iri(n), "parent_field": None, "children": []}
        for n in range(1, 4)
    ]
    text = runner.invoke(cli, ["graph", "tree", "corpus-a", *base])
    assert text.exit_code == 0
    assert text.output.splitlines() == [f"{iri(n)}\t{iri(n)}" for n in range(1, 4)]
    missing = runner.invoke(cli, ["graph", "path", "corpus-a", iri(99), *base])
    assert missing.exit_code == 1 and "not a shard" in missing.output
    missing = runner.invoke(cli, ["graph", "tree", "missing", *base])
    assert missing.exit_code == 1 and "no corpus" in missing.output
