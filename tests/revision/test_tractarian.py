"""Drain U4 (R12, KTD8) — Tractarian path identifiers.

Paths derive from each shard's primary parent (``elaborates[0]``, else
``depends_on_axioms[0]``, else root) and from first commit order, so new
shards append and existing paths never renumber. Synthetic shards and
temporary storage roots only.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from folio_insights.revision.tractarian import TractarianFinding, TractarianIndex
from folio_insights.storage import CorpusStorageContext, StorageConfig

from tests.storage.conftest import shard


def iri(n: int) -> str:
    return f"urn:folio:shard/{n:032x}"


def index(*specs: tuple) -> TractarianIndex:
    """``(n, position, overrides)`` triples -> an index."""
    return TractarianIndex([(shard(n, **over), pos) for n, pos, over in specs])


def paths(ix: TractarianIndex) -> dict[str, str]:
    return {node.iri: node.path for node in ix.nodes()}


def test_roots_number_in_commit_order_not_iri_order() -> None:
    ix = index((3, 0, {}), (1, 5, {}), (2, 9, {}))
    assert ix.path_of(iri(3)) == "1"
    assert ix.path_of(iri(1)) == "2"
    assert ix.path_of(iri(2)) == "3"
    assert ix.children() == ["1", "2", "3"]
    assert ix.findings == ()


def test_children_nest_under_elaborates_then_axioms() -> None:
    ix = index(
        (1, 0, {}),                                     # 1
        (2, 1, {"elaborates": [iri(1)]}),               # 1.1
        (3, 2, {"depends_on_axioms": [iri(1)]}),        # 1.2 (axiom fallback)
        (4, 3, {"elaborates": [iri(2)]}),               # 1.1.1
        (5, 4, {}),                                     # 2
        (6, 5, {"elaborates": [iri(5)], "depends_on_axioms": [iri(1)]}),  # 2.1
    )
    assert paths(ix) == {
        iri(1): "1", iri(2): "1.1", iri(4): "1.1.1", iri(3): "1.2", iri(5): "2", iri(6): "2.1",
    }
    assert [n.path for n in ix.nodes()] == ["1", "1.1", "1.1.1", "1.2", "2", "2.1"]
    assert ix.children("1") == ["1.1", "1.2"] and ix.children("1.1") == ["1.1.1"]
    assert ix.children("9.9") == [] and ix.children("1.1.1") == []
    assert ix.iri_of("1.1.1") == iri(4) and ix.iri_of("7") is None
    assert ix.node(iri(3)).parent_field == "depends_on_axioms"  # type: ignore[union-attr]
    assert ix.node(iri(6)).parent_field == "elaborates"  # type: ignore[union-attr]
    assert ix.node(iri(4)).depth == 3  # type: ignore[union-attr]


def test_a_later_sibling_appends_without_renumbering() -> None:
    base = [
        (1, 0, {}), (2, 1, {"elaborates": [iri(1)]}), (3, 2, {}),
        (4, 3, {"elaborates": [iri(1)]}), (5, 4, {"elaborates": [iri(2)]}),
    ]
    before = paths(index(*base))
    after = paths(index(*base, (6, 10, {"elaborates": [iri(1)]}), (7, 11, {}), (8, 12, {"elaborates": [iri(2)]})))
    assert {k: after[k] for k in before} == before
    assert after[iri(6)] == "1.3" and after[iri(7)] == "3" and after[iri(8)] == "1.1.2"


def test_two_elaborates_parents_use_the_first_and_report_the_rest() -> None:
    ix = index(
        (1, 0, {}), (2, 1, {}),
        (3, 2, {"elaborates": [iri(2), iri(1), iri(1)]}),
    )
    assert ix.path_of(iri(3)) == "2.1"
    assert ix.findings == (TractarianFinding("extra_parent", iri(3), iri(1), "elaborates"),)
    assert "elaborates[0]" in ix.findings[0].detail


def test_dangling_parents_fall_back_and_are_reported() -> None:
    ghost, kernel_ext = iri(0xDEAD), "urn:example:external-axiom"
    ix = index(
        (1, 0, {}),
        (2, 1, {"elaborates": [ghost], "depends_on_axioms": [iri(1)]}),  # falls to axiom
        (3, 2, {"depends_on_axioms": [kernel_ext]}),                    # root
    )
    assert ix.path_of(iri(2)) == "1.1" and ix.path_of(iri(3)) == "2"
    kinds = {(f.kind, f.iri, f.target, f.field) for f in ix.findings}
    assert kinds == {
        ("dangling_parent", iri(2), ghost, "elaborates"),
        ("dangling_parent", iri(3), kernel_ext, "depends_on_axioms"),
    }


def test_legacy_parent_cycle_is_cut_at_its_first_committed_member() -> None:
    ix = index(
        (1, 7, {"elaborates": [iri(2)]}),
        (2, 3, {"elaborates": [iri(1)]}),
        (3, 9, {"elaborates": [iri(3)]}),  # self-elaboration
    )
    assert ix.path_of(iri(2)) == "1" and ix.path_of(iri(1)) == "1.1" and ix.path_of(iri(3)) == "2"
    assert {(f.kind, f.iri) for f in ix.findings} == {
        ("parent_cycle", iri(2)), ("parent_cycle", iri(3)),
    }


def test_tree_is_nested_json_and_deep_chains_do_not_recurse() -> None:
    ix = index((1, 0, {}), (2, 1, {"elaborates": [iri(1)]}), (3, 2, {}))
    assert ix.tree() == [
        {"path": "1", "iri": iri(1), "parent_field": None, "children": [
            {"path": "1.1", "iri": iri(2), "parent_field": "elaborates", "children": []},
        ]},
        {"path": "2", "iri": iri(3), "parent_field": None, "children": []},
    ]
    depth = 3000
    chain = TractarianIndex(
        [(shard(1), 0)]
        + [(shard(n, elaborates=[iri(n - 1)]), n) for n in range(2, depth + 1)]
    )
    assert chain.path_of(iri(depth)) == ".".join(["1"] * depth)
    json.dumps(chain.tree())  # nested, but built without recursion


def test_duplicate_entries_are_refused() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        index((1, 0, {}), (1, 1, {}))


def test_ae4_shape_path_sits_under_the_kernel_shard() -> None:
    """AE4 (path half): a shard that elaborates a hypothesis which depends on
    a kernel shard sits two levels under that kernel shard's path."""
    kernel, hypothesis, leaf = iri(0x100), iri(0x200), iri(0x300)
    ix = TractarianIndex([
        (shard(0x100, epistemic_status="authority_only"), 0),
        (shard(0x200, depends_on_axioms=[kernel]), 1),
        (shard(0x300, elaborates=[hypothesis]), 2),
    ])
    assert ix.path_of(kernel) == "1"
    assert ix.path_of(hypothesis) == "1.1"
    assert ix.path_of(leaf) == "1.1.1"


# ── from storage: first commit position, not latest revision ──────────────


async def test_from_context_orders_by_first_commit_and_survives_revisions(tmp_path: Path) -> None:
    ctx = await CorpusStorageContext.open(tmp_path / "s", "corpus-a")
    try:
        await ctx.ingest_shards([shard(9), shard(4, elaborates=[iri(9)])])
        await ctx.ingest_shards([shard(1)])
        await ctx.ingest_shards([shard(5, elaborates=[iri(9)])])
        before = paths(await TractarianIndex.from_context(ctx))
        assert before == {iri(9): "1", iri(4): "1.1", iri(5): "1.2", iri(1): "2"}
        # A later revision of the first root keeps its ordinal (first commit).
        await ctx.shards.put(iri(9), shard(9, sense="revised sense"), op_id="rev-9")
        await ctx.ingest_shards([shard(7, elaborates=[iri(4)])])
        after = paths(await TractarianIndex.from_context(ctx))
        assert {k: after[k] for k in before} == before and after[iri(7)] == "1.1.1"
        # A content edit that changes the primary parent moves that shard only.
        await ctx.shards.put(iri(5), shard(5, elaborates=[iri(1)]), op_id="move-5")
        moved = paths(await TractarianIndex.from_context(ctx))
        assert moved[iri(5)] == "2.1" and moved[iri(4)] == "1.1" and moved[iri(7)] == "1.1.1"
    finally:
        await ctx.close()


async def test_shards_in_commit_order_is_one_consistent_read(tmp_path: Path) -> None:
    ctx = await CorpusStorageContext.open(tmp_path / "s", "corpus-a")
    try:
        assert await ctx.shards_in_commit_order() == []
        await ctx.ingest_shards([shard(2), shard(1)])
        await ctx.shards.put(iri(2), shard(2, sense="v2"), op_id="r")
        order = await ctx.shards_in_commit_order()
        assert [(s.shard_iri, pos) for s, pos in order] == [(iri(2), 0), (iri(1), 1)]
        assert order[0][0].sense == "v2"  # the current revision, at its first position
    finally:
        await ctx.close()


# ── CLI ───────────────────────────────────────────────────────────────────


def _seed(root: Path) -> None:
    async def run() -> None:
        ctx = await CorpusStorageContext.open(
            root, "corpus-a", config=StorageConfig(refuse_dependency_cycles=True)
        )
        try:
            await ctx.ingest_shards([
                shard(1),
                shard(2, elaborates=[iri(1), iri(3)]),
                shard(3),
            ])
        finally:
            await ctx.close()

    asyncio.run(run())


def test_cli_path_and_tree(tmp_path: Path) -> None:
    from folio_insights.cli import cli

    root = tmp_path / "root"
    _seed(root)
    runner = CliRunner()
    base = ["--corpus-root", str(root)]

    out = runner.invoke(cli, ["graph", "path", "corpus-a", iri(2), *base])
    assert out.exit_code == 0, out.output
    assert out.output == f"1.1\t{iri(2)}\n"
    missing = runner.invoke(cli, ["graph", "path", "corpus-a", "urn:folio:shard/nope", *base])
    assert missing.exit_code == 1 and "not a shard" in missing.output

    tree = runner.invoke(cli, ["graph", "tree", "corpus-a", *base])
    assert tree.exit_code == 0, tree.output
    lines = tree.stdout.splitlines()
    assert lines == [f"1\t{iri(1)}", f"  1.1\t{iri(2)}", f"2\t{iri(3)}"]
    assert "finding: extra_parent" in tree.stderr

    as_json = runner.invoke(cli, ["graph", "tree", "corpus-a", "--json", *base])
    assert as_json.exit_code == 0, as_json.output
    data = json.loads(as_json.stdout)
    assert data["shards"] == 3
    assert [n["path"] for n in data["tree"]] == ["1", "2"]
    assert data["tree"][0]["children"][0] == {
        "path": "1.1", "iri": iri(2), "parent_field": "elaborates", "children": [],
    }
    assert data["findings"][0]["kind"] == "extra_parent"

    nope = runner.invoke(cli, ["graph", "tree", "nope", *base])
    assert nope.exit_code == 1 and "no corpus" in nope.output
