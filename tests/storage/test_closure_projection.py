"""Persisted closure and coherent count snapshots over synthetic corpus records."""
from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from click.testing import CliRunner
from pyoxigraph import NamedNode, RdfFormat, parse

from folio_insights.closure.declarations import submit_declaration
from folio_insights.closure.projection import SnapshotRunner
from folio_insights.identity import sign_attestation, verify_attestation
from folio_insights.identity.cache import InMemoryDidDocCache
from folio_insights.query.cli import query_group
from folio_insights.query.closed_world import CLOSED_UNDER, ClosedWorldQuery, ClosedWorldScope
from folio_insights.revision.content_edit import canonical_content_hash
from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.backup import restore_storage, snapshot_storage
from folio_insights.storage.errors import ProjectionRecoveryFailed, ProjectionRecoveryPending, StorageClosed
from folio_insights.storage.exports import (
    ExportFormat, build_export_dataset, canonical_quads, export_corpus, read_neo4j,
)
from folio_insights.storage.projection import PROJECTION_DIRNAME, ProjectionHandle, closure_graph
from folio_insights.store.pyoxigraph_store import ServiceClauseBlocked
from tests.query.test_closure_declarations import declaration, seeded
from tests.storage.conftest import at, new_identity, role_assertion, shard

FI = "https://folio-insights.aleainstitute.ai/vocab/"
SCOPE = ClosedWorldScope("urn:test:stored-scope", frozenset({FI + "Shard"}),
                         frozenset({FI + "dependsOnShard"}))
MEMBERS = [shard(1).shard_iri, shard(2).shard_iri]


async def membership(ctx):
    rows = await ctx.query(f"SELECT ?s WHERE {{ ?s <{CLOSED_UNDER}> <{SCOPE.scope_iri}> }}")
    return {row["s"].value for row in rows}


async def test_declare_reopen_rebuild_and_unchanged_signed_bytes(tmp_path):
    ctx, admin = await seeded(tmp_path)
    try:
        signed_shard = shard(1)
        signed_shard.signatures.append(sign_attestation(
            canonical_content_hash(signed_shard), admin.sk, admin.did, "extract",
            signing_key_id=admin.key_id, did_doc_snapshot_at=None, now=datetime.now(UTC),
        ))
        await ctx.shards.put(signed_shard.shard_iri, signed_shard)
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
        assert await verify_attestation(after.shard, after.shard.signatures[0], cache=InMemoryDidDocCache())
    finally:
        await ctx.close()
    async with await CorpusStorageContext.open(tmp_path, "corpus-a") as reopened:
        assert await membership(reopened) == set(signed.members)
        assert (await ClosedWorldQuery(reopened).count_lacking(
            FI + "Shard", FI + "dependsOnShard", SCOPE.scope_iri)).count == 2


async def test_ledger_only_change_reaches_an_already_open_context(tmp_path):
    writer, admin = await seeded(tmp_path)
    async with writer, await CorpusStorageContext.open(tmp_path, writer.corpus) as reader:
        assert await membership(reader) == set()
        head = await reader.journal_head()
        await submit_declaration(writer, await declaration(writer, admin, scope=SCOPE))
        assert await reader.journal_head() == head
        assert await membership(reader) == {MEMBERS[0]}
        assert (await ClosedWorldQuery(reader).count_related(
            MEMBERS[0], FI + "dependsOnShard")).world_assumption == "closed"


@pytest.mark.parametrize("advance", ["member", "unrelated", "governance"])
async def test_any_main_journal_advance_requires_a_fresh_declaration(tmp_path, advance):
    ctx, admin = await seeded(tmp_path)
    async with ctx:
        await submit_declaration(ctx, await declaration(ctx, admin, scope=SCOPE, members=MEMBERS))
        if advance == "governance":
            await ctx.governance.append(role_assertion(
                ctx.corpus, admin, new_identity().did, "reviewer", at(1)))
        else:
            changed = shard(1, sense="revised synthetic member") if advance == "member" else shard(3)
            await ctx.shards.put(changed.shard_iri, changed)
        assert await membership(ctx) == set()
        q = ClosedWorldQuery(ctx, [SCOPE])
        assert (await q.count_related(MEMBERS[0], FI + "dependsOnShard")).world_assumption == "open"
        await submit_declaration(ctx, await declaration(
            ctx, admin, op_id="fresh-closure", scope=SCOPE, members=MEMBERS))
        assert await membership(ctx) == set(MEMBERS)
        assert (await q.count_related(MEMBERS[0], FI + "dependsOnShard")).world_assumption == "closed"


async def test_replacement_removes_members_and_callers_cannot_broaden_contract(tmp_path):
    ctx, admin = await seeded(tmp_path)
    extra = FI + "dependsOnDefinition"
    broad = ClosedWorldScope(SCOPE.scope_iri, SCOPE.closed_classes,
                             SCOPE.closed_properties | {extra})
    async with ctx:
        old = await declaration(ctx, admin, scope=broad, members=MEMBERS)
        await submit_declaration(ctx, old)
        await submit_declaration(ctx, await declaration(
            ctx, admin, op_id="narrow", scope=SCOPE, members=[MEMBERS[1]]))
        await submit_declaration(ctx, old)  # exact historical retry must not restore anything
        assert await membership(ctx) == {MEMBERS[1]}
        q = ClosedWorldQuery(ctx, [broad])
        assert (await q.count_related(MEMBERS[0], FI + "dependsOnShard")).world_assumption == "open"
        assert (await q.count_related(MEMBERS[1], extra)).world_assumption == "open"
        assert (await q.count_related(MEMBERS[1], FI + "dependsOnShard")).world_assumption == "closed"
        lacking = await q.count_lacking(FI + "Shard", FI + "dependsOnShard", SCOPE.scope_iri)
        assert (lacking.count, lacking.total_instances) == (1, 1)
        restricted = ClosedWorldQuery(ctx, [ClosedWorldScope(
            SCOPE.scope_iri, SCOPE.closed_classes, frozenset({extra}))])
        assert (await restricted.count_related(MEMBERS[1], FI + "dependsOnShard")).world_assumption == "open"
        wrong_class = ClosedWorldQuery(ctx, [ClosedWorldScope(
            SCOPE.scope_iri, frozenset({FI + "Unknown"}), SCOPE.closed_properties)])
        assert (await wrong_class.count_lacking(
            FI + "Shard", FI + "dependsOnShard", SCOPE.scope_iri)).world_assumption == "open"


@pytest.mark.parametrize("include_projection", [False, True])
async def test_closure_survives_snapshot_restore(tmp_path, include_projection):
    root = tmp_path / "live"
    ctx, admin = await seeded(root)
    async with ctx:
        await submit_declaration(ctx, await declaration(ctx, admin, scope=SCOPE, members=MEMBERS))
    snap = await snapshot_storage(root, tmp_path / "snapshot", include_projection=include_projection)
    destination = tmp_path / "restored"
    await restore_storage(snap.path, destination, rebuild_projection=False)
    async with await CorpusStorageContext.open(destination, "corpus-a") as restored:
        assert await membership(restored) == set(MEMBERS)
        assert (await ClosedWorldQuery(restored).count_lacking(
            FI + "Shard", FI + "dependsOnShard", SCOPE.scope_iri)).count == 2


def install_projection_copy(source, destination):
    # Keep a backup even for disposable synthetic data: only the derived copy is replaced.
    (destination / PROJECTION_DIRNAME).rename(destination / "original-projection")
    shutil.copytree(source / PROJECTION_DIRNAME, destination / PROJECTION_DIRNAME)


@pytest.mark.parametrize("declared", [False, True])
async def test_older_snapshot_rejects_newer_projection_closure(tmp_path, declared):
    root = tmp_path / "live"
    ctx, admin = await seeded(root)
    async with ctx:
        if declared:
            await submit_declaration(ctx, await declaration(ctx, admin, scope=SCOPE, members=MEMBERS))
    snap = await snapshot_storage(root, tmp_path / "older", include_projection=False)
    async with await CorpusStorageContext.open(root, "corpus-a") as newer:
        await newer.ingest_shards([shard(3)])
        await submit_declaration(newer, await declaration(
            newer, admin, op_id="newer", scope=SCOPE, members=[MEMBERS[1]]))
        assert await membership(newer) == {MEMBERS[1]}
    destination = tmp_path / "restored"
    await restore_storage(snap.path, destination)
    install_projection_copy(root, destination)
    async with await CorpusStorageContext.open(destination, "corpus-a") as restored:
        assert await membership(restored) == (set(MEMBERS) if declared else set())
        assert await restored.shards.get(shard(3).shard_iri) is None


async def test_equal_height_different_ledger_prefix_replaces_old_membership(tmp_path):
    base = tmp_path / "base"
    ctx, admin = await seeded(base)
    await ctx.close()
    snap = await snapshot_storage(base, tmp_path / "base-snapshot", include_projection=False)
    roots = [tmp_path / "branch-a", tmp_path / "branch-b"]
    for index, root in enumerate(roots):
        await restore_storage(snap.path, root)
        async with await CorpusStorageContext.open(root, "corpus-a") as branch:
            await submit_declaration(branch, await declaration(
                branch, admin, op_id=f"branch-{index}", scope=SCOPE, members=[MEMBERS[index]]))
            assert await branch.proposals.head() == 0
    branch_snapshot = await snapshot_storage(roots[1], tmp_path / "branch-snapshot", include_projection=False)
    destination = tmp_path / "restored"
    await restore_storage(branch_snapshot.path, destination)
    install_projection_copy(roots[0], destination)
    async with await CorpusStorageContext.open(destination, "corpus-a") as restored:
        assert await membership(restored) == {MEMBERS[1]}
        q = ClosedWorldQuery(restored)
        assert (await q.count_related(MEMBERS[0], FI + "dependsOnShard")).world_assumption == "open"
        assert (await q.count_related(MEMBERS[1], FI + "dependsOnShard")).world_assumption == "closed"


async def test_failed_materialization_is_committed_and_recovers_once(tmp_path, monkeypatch):
    ctx, admin = await seeded(tmp_path)
    signed = await declaration(ctx, admin, scope=SCOPE, members=MEMBERS)
    original = ProjectionHandle.replace_closure

    def fail(self, corpus, triples, digest):
        if digest is not None:
            raise OSError("synthetic closure projection failure")
        return original(self, corpus, triples, digest)

    with monkeypatch.context() as patch:
        patch.setattr(ProjectionHandle, "replace_closure", fail)
        with pytest.raises(ProjectionRecoveryPending) as error:
            await submit_declaration(ctx, signed)
        assert (error.value.op_id, error.value.position) == (signed.op_id, 0)
        with pytest.raises(StorageClosed):
            await membership(ctx)
    async with await CorpusStorageContext.open(tmp_path, "corpus-a") as restored:
        assert await membership(restored) == set(MEMBERS)
        assert (await submit_declaration(restored, signed)).position == 0
        assert await restored.proposals.head() == 0


@pytest.mark.parametrize("damage", ["position", "payload_sha256"])
async def test_cached_projection_never_bypasses_ledger_prefix_verification(tmp_path, monkeypatch, damage):
    ctx, admin = await seeded(tmp_path)
    signed = await declaration(ctx, admin, scope=SCOPE, members=MEMBERS)
    entry = await submit_declaration(ctx, signed)
    assert await membership(ctx) == set(MEMBERS)

    async def corrupted_prefix():
        return [replace(entry, **{damage: 5 if damage == "position" else "0" * 64})]

    monkeypatch.setattr(ctx.proposals, "entries", corrupted_prefix)
    with pytest.raises(ProjectionRecoveryFailed):
        await membership(ctx)
    with pytest.raises(StorageClosed):
        await ClosedWorldQuery(ctx).count_related(MEMBERS[0], FI + "dependsOnShard")
    async with await CorpusStorageContext.open(tmp_path, "corpus-a") as restored:
        assert await membership(restored) == set(MEMBERS)


@pytest.mark.parametrize("operation", ["related", "lacking"])
@pytest.mark.parametrize("mutation", ["main", "narrow"])
async def test_counts_hold_one_snapshot_across_interleaved_writes(tmp_path, monkeypatch, operation, mutation):
    ctx, admin = await seeded(tmp_path)
    async with ctx, await CorpusStorageContext.open(tmp_path, ctx.corpus) as writer:
        await ctx.shards.put(MEMBERS[0], shard(1, depends_on_shards=[MEMBERS[1]]))
        await submit_declaration(ctx, await declaration(ctx, admin, scope=SCOPE, members=MEMBERS))
        original = SnapshotRunner.query
        changed = False

        async def interleave(self, sparql, **kwargs):
            nonlocal changed
            result = await original(self, sparql, **kwargs)
            if not changed:
                changed = True
                if mutation == "main":
                    await writer.shards.put(MEMBERS[0], shard(1))
                else:
                    narrow = ClosedWorldScope(SCOPE.scope_iri, SCOPE.closed_classes, frozenset())
                    await submit_declaration(writer, await declaration(
                        writer, admin, op_id="narrow-during-count", scope=narrow, members=[MEMBERS[1]]))
            return result

        monkeypatch.setattr(SnapshotRunner, "query", interleave)
        q = ClosedWorldQuery(ctx)
        if operation == "related":
            answer = await q.count_related(MEMBERS[0], FI + "dependsOnShard")
            assert (answer.world_assumption, answer.count, answer.items) == ("closed", 1, (MEMBERS[1],))
        else:
            answer = await q.count_lacking(FI + "Shard", FI + "dependsOnShard", SCOPE.scope_iri)
            assert (answer.world_assumption, answer.count, answer.total_instances,
                    answer.asserted_with_property) == ("closed", 1, 2, 1)
        assert changed
        assert (await q.count_related(MEMBERS[0], FI + "dependsOnShard")).world_assumption == "open"


async def test_same_scope_is_corpus_isolated_and_every_export_keeps_membership(tmp_path):
    root = tmp_path / "storage"
    first, admin_a = await seeded(root)
    second, admin_b = await seeded(root, "corpus-b")
    async with first, second:
        for ctx, admin, member in ((first, admin_a, MEMBERS[0]), (second, admin_b, MEMBERS[1])):
            await submit_declaration(ctx, await declaration(ctx, admin, scope=SCOPE, members=[member]))
            assert await membership(ctx) == {member}
            dataset = await build_export_dataset(ctx)
            closure = dataset.graph(closure_graph(ctx.corpus))
            assert {q.subject.value for q in closure} == {member}
            assert all(q.predicate == NamedNode(CLOSED_UNDER) for q in closure)
            destination = tmp_path / f"export-{ctx.corpus}"
            formats = [f for f in ExportFormat if f is not ExportFormat.SPARQL_CONSTRUCT]
            result = await export_corpus(ctx, destination, formats)
            assert result.manifest["graphs"]["closure"] == closure_graph(ctx.corpus).value
            for filename, fmt in (("dataset.nq", RdfFormat.N_QUADS),
                                  ("dataset.jsonld", RdfFormat.JSON_LD)):
                assert canonical_quads(parse(path=str(destination / filename), format=fmt)) == canonical_quads(dataset.quads())
            assert canonical_quads(read_neo4j(destination)) == canonical_quads(dataset.quads())
            for filename in ("combined.ttl", f"closure/{ctx.corpus}.ttl"):
                quads = list(parse(path=str(destination / filename), format=RdfFormat.TURTLE))
                assert {q.subject.value for q in quads if q.predicate == NamedNode(CLOSED_UNDER)} == {member}
            assert result.manifest["formats"]["abox"]["files"][1]["graph"] == closure_graph(ctx.corpus).value
        await first.rebuild_projection()
        assert await membership(first) == {MEMBERS[0]}
        assert await membership(second) == {MEMBERS[1]}
        assert await first.proposals.head() == await second.proposals.head() == 0


async def test_snapshot_runner_refuses_service(tmp_path):
    ctx, _admin = await seeded(tmp_path)
    async with ctx:
        snapshot = await ctx.closed_world_snapshot()
        with pytest.raises(ServiceClauseBlocked):
            await snapshot.runner.query("SELECT * WHERE { SERVICE <https://example.test/> { ?s ?p ?o } }")


def test_count_cli_uses_persisted_contract_and_restricts_selected_scope(tmp_path):
    async def prepare():
        ctx, admin = await seeded(tmp_path)
        async with ctx:
            await submit_declaration(ctx, await declaration(ctx, admin, scope=SCOPE, members=MEMBERS))

    asyncio.run(prepare())
    args = ["count", "related", "--corpus", "corpus-a", "--corpus-root", str(tmp_path),
            "--subject", MEMBERS[0], "--property", FI + "dependsOnShard"]
    runner = CliRunner()
    for extra, assumption in (([], "closed"), (["--scope", SCOPE.scope_iri], "closed"),
                              (["--scope", "urn:test:other"], "open"),
                              (["--scope", SCOPE.scope_iri, "--closed-property", FI + "unknown"], "open")):
        result = runner.invoke(query_group, args + extra)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["world_assumption"] == assumption
    result = runner.invoke(query_group, [
        "count", "lacking", "--corpus", "corpus-a", "--corpus-root", str(tmp_path),
        "--scope", SCOPE.scope_iri, "--class", FI + "Shard", "--property", FI + "dependsOnShard"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["count"] == 2
    restricted = runner.invoke(query_group, [
        "count", "lacking", "--corpus", "corpus-a", "--corpus-root", str(tmp_path),
        "--scope", SCOPE.scope_iri, "--class", FI + "Shard", "--property", FI + "dependsOnShard",
        "--closed-property", FI + "dependsOnShard"])
    assert restricted.exit_code == 0, restricted.output
    assert json.loads(restricted.output)["count"] == 2
    invalid = runner.invoke(query_group, args + ["--closed-property", FI + "dependsOnShard"])
    assert invalid.exit_code == 2
    assert "--scope is required" in invalid.output
