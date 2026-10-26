"""U37: mixed-schema replay, complete atomic payloads and recoverable storage."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from folio_insights.identity import verify_attestation
from folio_insights.identity.cache import InMemoryDidDocCache
from folio_insights.shards import dump_shard_record, load_shard_record
from folio_insights.storage import (
    CorpusStorageContext, ProjectionRecoveryPending, ShaclViolation, StorageConfig,
    ShardIdentityViolation,
)
from folio_insights.storage.backup import restore_storage, snapshot_storage
from folio_insights.storage.exports import build_export_dataset, canonical_quads
from folio_insights.storage.journal import JOURNAL_FILENAME
from folio_insights.storage.projection import (
    META_GRAPH, PROJECTION_ADAPTER_VERSION, ProjectionHandle, chain_over,
    CHAIN_GENESIS, corpus_graph,
)
from folio_insights.shapes.suite import ShaclSuite, SUITE_PATHS
from folio_insights.vocab._constants import FI_PREFIX as FI
from tests.shards.test_atomic_records import _atomic
from tests.shards.test_envelope_records import _signed_shard
from tests.storage.conftest import shard

pytestmark = pytest.mark.storage


def atomic_record():
    data = _atomic().model_dump(mode="json")
    data["transaction_time"] = "2026-05-01T12:00:00Z"
    data["folio_tags"] = [
        dict(iri="https://example.org/Duty", label="Duty", confidence=0.99,
             branch="Deontic Specification", extraction_path="entity_ruler"),
        dict(iri="https://example.org/Contract", label="Contract Law", confidence=0.95,
             branch="Area of Law", extraction_path="semantic", judge_status="judged"),
    ]
    data["links"] = [
        dict(relation=relation, target_iri=shard(2).shard_iri)
        for relation in ("exception-to", "penalty-for", "condition-of", "cites", "contradicts")
    ] + [dict(relation="cites", citation="Example v. State, 1 U.S. 2")]
    return load_shard_record(data, target_schema_version=3).shard


def journal_rows(root: Path):
    with sqlite3.connect(root / JOURNAL_FILENAME) as conn:
        return conn.execute("SELECT * FROM journal ORDER BY corpus, position").fetchall()


async def populate(ctx):
    signed, _ = _signed_shard()
    legacy = signed.model_dump(mode="json")
    del legacy["schema_version"]
    raw = json.dumps(legacy, indent=2).encode()
    await ctx.ingest_shards(
        [raw, shard(2, elaborates=[signed.shard_iri]), atomic_record()], op_id="mixed"
    )
    return signed.shard_iri, raw


async def assert_atomic_payload(ctx):
    expected = atomic_record()
    rows = await ctx.query(
        f"SELECT ?iri ?label ?branch ?confidence ?path ?judge WHERE {{ "
        f"<{expected.shard_iri}> <{FI}folioTags> ?tag . "
        f"?tag <{FI}iri> ?iri ; <{FI}label> ?label ; <{FI}branch> ?branch ; "
        f"<{FI}confidence> ?confidence ; <{FI}extractionPath> ?path . "
        f"OPTIONAL {{ ?tag <{FI}judgeStatus> ?judge }} }} ORDER BY ?iri"
    )
    assert sorted((r["iri"].value, r["label"].value, r["branch"].value,
                   float(r["confidence"].value), r["path"].value,
                   None if r["judge"] is None else r["judge"].value) for r in rows) == sorted(
        (t.iri, t.label, t.branch, t.confidence, t.extraction_path, t.judge_status)
        for t in expected.folio_tags
    )
    rows = await ctx.query(
        f"SELECT ?relation ?target ?citation WHERE {{ <{expected.shard_iri}> <{FI}links> ?link . "
        f"?link <{FI}relation> ?relation . OPTIONAL {{ ?link <{FI}targetIri> ?target }} "
        f"OPTIONAL {{ ?link <{FI}citation> ?citation }} }}"
    )
    assert {(r["relation"].value, None if r["target"] is None else r["target"].value,
             None if r["citation"] is None else r["citation"].value) for r in rows} == {
        (link.relation, link.target_iri, link.citation) for link in expected.links
    }
    assert len(rows) == 6
    loaded = await ctx.shards.get(expected.shard_iri)
    assert dump_shard_record(loaded) == dump_shard_record(expected)


async def test_mixed_journal_rebuild_preserves_records_tags_links(storage_root):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        legacy_iri, raw = await populate(ctx)
        before = journal_rows(storage_root)
        await assert_atomic_payload(ctx)
        assert not await ctx.query(f"ASK {{ ?s <{FI}elaborates> ?parent }}")
        history = await ctx.query(
            f"SELECT ?parent WHERE {{ <{shard(2).shard_iri}> <{FI}legacyHierarchy> ?history . "
            f"?history <{FI}historicalElaborates> ?parent }}"
        )
        assert [r["parent"].value for r in history] == [legacy_iri]
        dataset = await build_export_dataset(ctx)
        await ctx.rebuild_projection()
        await assert_atomic_payload(ctx)
        assert canonical_quads((await build_export_dataset(ctx)).quads()) == canonical_quads(dataset.quads())
        assert journal_rows(storage_root) == before
        rec = await ctx.shards.get_record(legacy_iri)
        assert rec.original_bytes == raw and rec.source_schema_version == 1
        original = load_shard_record(rec.original_bytes).shard
        assert await verify_attestation(original, original.signatures[0], cache=InMemoryDidDocCache())
        originals = {q.subject.value: q.object.value for q in dataset.quads()
                     if q.predicate.value == FI + "signedRecord"}
        digests = {q.subject.value: q.object.value for q in dataset.quads()
                   if q.predicate.value == FI + "signedRecordSha256"}
        versions = {q.subject.value: int(q.object.value) for q in dataset.quads()
                    if q.predicate.value == FI + "recordSourceSchemaVersion"}
        assert versions == {legacy_iri: 1, shard(2).shard_iri: 2, atomic_record().shard_iri: 3}
        assert originals[legacy_iri].encode() == raw
        assert all(digests[iri] == hashlib.sha256(value.encode()).hexdigest()
                   for iri, value in originals.items())


async def test_atomic_revision_replaces_owned_nodes_without_orphans(storage_root):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        original = atomic_record()
        await ctx.shards.put(original.shard_iri, original)
        revised = original.model_copy(deep=True)
        revised.folio_tags = revised.folio_tags[:1]
        revised.links = []
        await ctx.shards.put(revised.shard_iri, revised, op_id="revision")
        first = canonical_quads((await build_export_dataset(ctx)).quads())
        assert not await ctx.query(f"ASK {{ ?s <{FI}relation> ?relation }}")
        assert not await ctx.query(f'ASK {{ ?s <{FI}branch> "Area of Law" }}')
        await ctx.rebuild_projection()
        assert canonical_quads((await build_export_dataset(ctx)).quads()) == first


@pytest.mark.parametrize("version", [2, 3])
async def test_atomic_record_cannot_be_replaced_with_legacy_identity(storage_root, version):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        original = atomic_record()
        await ctx.shards.put(original.shard_iri, original)
        before = journal_rows(storage_root)
        data = original.model_dump(mode="json")
        data.update(schema_version=version, identity_recipe="legacy-v1", proposition_key=None,
                    atomic_identity=None)
        if version == 2:
            for field in ("identity_recipe", "proposition_key", "atomic_identity",
                          "folio_tags", "links", "legacy_hierarchy"):
                data.pop(field)
        replacement = load_shard_record(data, target_schema_version=version).shard
        with pytest.raises(ShardIdentityViolation):
            await ctx.shards.put(original.shard_iri, replacement)
        assert journal_rows(storage_root) == before


async def test_atomic_bulk_preparation_and_bulk_projection_match_serial(storage_root, monkeypatch):
    import folio_insights.storage.context as context
    import folio_insights.storage.projection as projection

    # Exercise the real chunk preparation and add-only RDF bulk-load path
    # without needing thousands of fixtures or a local process-pool socket.
    monkeypatch.setattr(context, "PARALLEL_MIN_ITEMS", 1)
    monkeypatch.setattr(projection, "BULK_LOAD_MIN_ROWS", 1)
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        await ctx.bulk_load_shards([atomic_record()], op_id="bulk", parallel=True)
        await assert_atomic_payload(ctx)
        assert len([s async for s in ctx.shards.iter_shards()]) == 1
        first = canonical_quads((await build_export_dataset(ctx)).quads())
        await ctx.rebuild_projection()
        assert canonical_quads((await build_export_dataset(ctx)).quads()) == first


@pytest.mark.parametrize("damage", ["old-adapter", "missing-adapter", "bad-chain"])
async def test_stale_atomic_projection_rebuilt(storage_root, damage):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        await populate(ctx)
        before = journal_rows(storage_root)
        expected = canonical_quads((await build_export_dataset(ctx)).quads())
    handle = ProjectionHandle(storage_root)
    try:
        node = corpus_graph("corpus-a")
        predicate = "appliedChainDigest" if damage == "bad-chain" else "adapterVersion"
        value = '"invalid"' if damage == "bad-chain" else "2"
        handle.store.update(
            f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {node} <{FI}{predicate}> ?v }} }} ; "
            + ("" if damage == "missing-adapter" else
               f"INSERT DATA {{ GRAPH {META_GRAPH} {{ {node} <{FI}{predicate}> {value} }} }} ; ")
            + f"INSERT DATA {{ GRAPH {node} {{ <urn:unjournaled> <urn:p> 1 }} }}"
        )
    finally:
        handle.close()
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        await assert_atomic_payload(ctx)
        assert canonical_quads((await build_export_dataset(ctx)).quads()) == expected
        rows = await ctx._journal.rows_after("corpus-a", -1, limit=100)
        _, state = await ctx._read_projection(lambda h, _: h.state("corpus-a"))
        assert state.adapter_version == PROJECTION_ADAPTER_VERSION >= 3
        assert state.watermark == 2 and state.payload_sha256 == rows[-1].payload_sha256
        assert state.chain_digest == chain_over(CHAIN_GENESIS, rows)
    assert journal_rows(storage_root) == before


async def test_interrupted_atomic_apply_recovers_committed_operation(storage_root, monkeypatch):
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    original_apply = ProjectionHandle.apply

    def interrupted(*args, **kwargs):
        raise OSError("synthetic interrupted projection")

    monkeypatch.setattr(ProjectionHandle, "apply", interrupted)
    with pytest.raises(ProjectionRecoveryPending):
        await ctx.ingest_shards([atomic_record()], op_id="retry")
    before = journal_rows(storage_root)
    assert len(before) == 1
    monkeypatch.setattr(ProjectionHandle, "apply", original_apply)
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        await assert_atomic_payload(ctx)
        await ctx.ingest_shards([atomic_record()], op_id="retry")
        assert journal_rows(storage_root) == before


async def test_invalid_local_atomic_shape_never_starts_transaction(storage_root, tmp_path, monkeypatch):
    extra = tmp_path / "extra.ttl"
    extra.write_text(f'''@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix fi: <{FI}> .
<urn:no-tags> a sh:NodeShape ; sh:targetClass fi:Shard ;
    sh:property [ sh:path fi:folioTags ; sh:maxCount 0 ; sh:message "synthetic tag refusal" ] .
''')
    config = StorageConfig(shacl=ShaclSuite([*SUITE_PATHS, extra]))
    async with await CorpusStorageContext.open(storage_root, "corpus-a", config=config) as ctx:
        before = journal_rows(storage_root)

        def forbidden(*args, **kwargs):
            pytest.fail("invalid local shape reached a journal transaction")

        monkeypatch.setattr(ctx._journal, "write", forbidden)
        with pytest.raises(ShaclViolation, match="synthetic tag refusal"):
            await ctx.ingest_shards([atomic_record()])
        assert journal_rows(storage_root) == before


@pytest.mark.parametrize("include_projection", [False, True])
async def test_mixed_restore_new_destination_and_original_rollback(tmp_path, include_projection):
    root = tmp_path / "live"
    async with await CorpusStorageContext.open(root, "corpus-a") as ctx:
        legacy_iri, raw = await populate(ctx)
        before = journal_rows(root)
        expected = canonical_quads((await build_export_dataset(ctx)).quads())
    snap = await snapshot_storage(root, tmp_path / "backup", include_projection=include_projection)
    restored = tmp_path / "restored"
    await restore_storage(snap.path, restored, rebuild_projection=False)
    async with await CorpusStorageContext.open(restored, "corpus-a") as ctx:
        await assert_atomic_payload(ctx)
        assert canonical_quads((await build_export_dataset(ctx)).quads()) == expected
        assert journal_rows(restored) == before
        rec = await ctx.shards.get_record(legacy_iri)
        # Rollback selects preserved originals with their original adapter.
        original = load_shard_record(rec.original_bytes).shard
        assert rec.original_bytes == raw
        assert original.schema_version == 2
        assert await verify_attestation(original, original.signatures[0], cache=InMemoryDidDocCache())
    assert journal_rows(root) == before
