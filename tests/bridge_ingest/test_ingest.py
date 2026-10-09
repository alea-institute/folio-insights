"""ingest_record: storage gates, idempotency, manifest dedupe, refusals."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from folio_insights.bridge_ingest import ContentIriMismatch, ingest_record
from folio_insights.bridge_ingest.manifest import manifest_path, read_manifest
from folio_insights.shards.minting import mint_shard_iri
from folio_insights.storage import CorpusStorageContext
from tests.bridge_ingest.conftest import CORPUS, SOURCE_URI, make_record, proposition

SPAN_A = "A carrier may limit liability only with a fair opportunity to choose."
SPAN_B = "We find that the cargo was damaged in transit."


def _record(**kw):
    return make_record(
        proposition("p1", SPAN_A, "Judicial Legal Conclusion"),
        proposition("p2", SPAN_A, "cited-authority proposition"),
        proposition("p3", SPAN_B, "Judicial Finding of Fact"),
        proposition("p4", None, "policy proposition"),
        **kw,
    )


async def _ingest(root: Path, record, **kw):
    return await ingest_record(
        record, corpus_root=root, corpus=CORPUS, framework_id="us.case-law.unspecified",
        extractor_did="did:web:folio-enrich.local", **kw,
    )


async def test_ingest_then_reingest_is_idempotent(storage_root: Path) -> None:
    first = await _ingest(storage_root, _record())
    iris = {mint_shard_iri(SOURCE_URI, SPAN_A)[0], mint_shard_iri(SOURCE_URI, SPAN_B)[0]}
    assert (first.created, first.existing, first.skipped, first.refused) == (2, 0, 1, 0)
    assert set(first.created_iris) == iris
    assert first.op_id and first.op_id.startswith("bridge-ingest:")
    assert first.manifest_lines_added == 3

    second = await _ingest(storage_root, _record())
    assert (second.created, second.existing, second.refused) == (0, 2, 0)
    assert set(second.existing_iris) == iris
    assert second.manifest_lines_added == 0

    ctx = await CorpusStorageContext.open(storage_root, CORPUS)
    try:
        for iri in iris:
            shard = await ctx.shards.get(iri)
            assert shard is not None and shard.epistemic_status == "hypothesis"
        rows = await ctx.query(
            "SELECT (COUNT(*) AS ?n) WHERE { ?s <https://folio-insights.aleainstitute.ai/vocab/journalPosition> ?p }"
        )
        assert int(rows[0]["n"].value) == 2  # no second revision was written
    finally:
        await ctx.close()


async def test_manifest_dedupes_and_accumulates_sources(storage_root: Path) -> None:
    await _ingest(storage_root, _record())
    await _ingest(storage_root, _record())
    other = make_record(
        proposition("q1", SPAN_A, "Legal Proposition", role="plaintiff"), document_id="doc-2",
    )
    report = await _ingest(storage_root, other)
    assert (report.created, report.existing) == (0, 1)
    lines = [json.loads(x) for x in manifest_path(storage_root).read_text().splitlines()]
    keys = [(x["iri"], x["document_id"], x["proposition_id"]) for x in lines]
    assert len(keys) == len(set(keys)) == 4
    by_iri = read_manifest(storage_root, CORPUS)
    iri_a = mint_shard_iri(SOURCE_URI, SPAN_A)[0]
    assert {x["proposition_id"] for x in by_iri[iri_a]} == {"p1", "p2", "q1"}
    assert read_manifest(storage_root, "another-corpus") == {}


async def test_pii_refusal_surfaces_as_refused(storage_root: Path) -> None:
    pii = "The clerk may be reached at 612-555-0199 for filings."
    record = make_record(
        proposition("p1", SPAN_A),
        proposition("p2", pii, "Factual Statement", role="party"),
    )
    report = await _ingest(storage_root, record)
    pii_iri = mint_shard_iri(SOURCE_URI, pii)[0]
    assert report.created == 1 and report.refused == 1
    assert report.refused_shards[0].iri == pii_iri
    assert "PiiRejected" in report.refused_shards[0].reason
    assert "612-555-0199" not in report.model_dump_json()
    # The refused IRI never reaches the manifest; the landed one does.
    assert pii_iri not in read_manifest(storage_root, CORPUS)
    # Retrying refuses it again and keeps the landed shard as existing.
    again = await _ingest(storage_root, record)
    assert (again.created, again.existing, again.refused) == (0, 1, 1)


async def test_single_refused_shard(storage_root: Path) -> None:
    record = make_record(proposition("p1", "Call 612-555-0199 now.", role="party"))
    report = await _ingest(storage_root, record)
    assert (report.created, report.refused) == (0, 1)


async def test_shacl_refusal_surfaces_as_refused(storage_root: Path) -> None:
    from folio_insights.storage import ShaclViolation, StorageConfig

    target = mint_shard_iri(SOURCE_URI, SPAN_B)[0]

    def refuse_one(shard) -> None:
        if shard.shard_iri == target:
            raise ShaclViolation(shard.shard_iri, [{"component": "test", "message": "refused"}])

    # The shard hook runs on every write after the PII gate and the SHACL suite;
    # raising the suite's own refusal type stands in for a SHACL Violation.
    report = await _ingest(
        storage_root, _record(), storage_config=StorageConfig(shard_validator=refuse_one)
    )
    assert report.created == 1 and report.refused == 1
    assert report.refused_shards[0].iri == target
    assert "ShaclViolation" in report.refused_shards[0].reason


async def test_non_refusal_errors_propagate(storage_root: Path) -> None:
    from folio_insights.storage import StorageConfig

    def boom(shard) -> None:
        raise RuntimeError("storage hook failure")

    with pytest.raises(RuntimeError, match="storage hook failure"):
        await _ingest(storage_root, _record(), storage_config=StorageConfig(shard_validator=boom))


async def test_record_refusal_writes_nothing(storage_root: Path) -> None:
    record = _record()
    bad = record.propositions[0].model_copy(update={"content_iri": "urn:folio:shard/" + "f" * 32})
    tampered = record.model_copy(update={"propositions": [bad, *record.propositions[1:]]})
    with pytest.raises(ContentIriMismatch):
        await _ingest(storage_root, tampered)
    assert not manifest_path(storage_root).exists()
    assert not storage_root.exists()  # refused before storage was opened


async def test_ingest_from_path_and_ndjson(storage_root: Path, tmp_path: Path) -> None:
    record = _record()
    data = record.model_dump(mode="json")
    props = data.pop("propositions")
    nd = tmp_path / "record.ndjson"
    nd.write_text(
        "\n".join(
            [json.dumps({"record_type": "proposition_document", **data})]
            + [json.dumps({"record_type": "proposition", **p}) for p in props]
        ),
        encoding="utf-8",
    )
    report = await _ingest(storage_root, nd)
    assert report.created == 2
    js = tmp_path / "record.json"
    js.write_text(record.model_dump_json(), encoding="utf-8")
    assert (await _ingest(storage_root, js)).existing == 2


# ── review fixes: manifest PII gate, lock, races ─────────────────────────────

SSN = "123-45-6789"


async def test_manifest_pii_gate_and_citation_text(storage_root: Path) -> None:
    from folio_propositions import CitationEdge

    edge = CitationEdge(
        edge_type="cites", authority_individual_id="authority:x",
        authority_text=f"Smith (SSN {SSN})",
    )
    clean = make_record(proposition("p1", SPAN_A, citation_edges=[edge]))
    report = await _ingest(storage_root, clean)
    assert report.created == 1 and report.manifest_lines_added == 1
    (line,) = [json.loads(x) for x in manifest_path(storage_root).read_text().splitlines()]
    assert line["citation_edges"] == [{"edge_type": "cites", "authority_individual_id": "authority:x"}]

    tainted = make_record(proposition("p2", SPAN_B), document_id=f"doc {SSN}")
    report = await _ingest(storage_root, tainted)
    assert report.created == 1  # the shard itself is clean and lands
    assert report.manifest_lines_added == 0
    assert [(r.field_path, r.pattern) for r in report.manifest_refused] == [("document_id", "ssn")]
    # Nothing SSN-shaped reaches the disk (the report only echoes the caller's
    # own document_id back to the caller).
    assert SSN not in manifest_path(storage_root).read_text()
    assert "Smith" not in manifest_path(storage_root).read_text()


async def test_manifest_lock_held_raises_busy(storage_root: Path, monkeypatch) -> None:
    import fcntl
    import os

    from folio_insights.bridge_ingest import manifest as manifest_module
    from folio_insights.bridge_ingest.manifest import ManifestBusy

    monkeypatch.setattr(manifest_module, "LOCK_TIMEOUT_S", 0.1)
    lock = manifest_path(storage_root).parent / manifest_module.LOCK_FILENAME
    lock.parent.mkdir(parents=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        with pytest.raises(ManifestBusy):
            await _ingest(storage_root, _record())
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    # Shards landed before the manifest step; a re-push appends the provenance.
    again = await _ingest(storage_root, _record())
    assert (again.created, again.existing, again.manifest_lines_added) == (0, 2, 3)


async def test_interleaved_writer_of_another_record(storage_root: Path, monkeypatch) -> None:
    """Record B shares SPAN_A with record A, which lands between B's existence
    check and B's write (simulated by hiding A's shard from B's first check).
    B's shard for SPAN_A has another extracted_at, so the write trips the
    frozen-identity check; it must end as existing, with B's provenance."""
    from folio_insights.storage.shards import PersistentShardStore

    a = make_record(proposition("a1", SPAN_A), metadata={"exported_at": "2026-01-01T00:00:00Z"})
    await _ingest(storage_root, a)
    iri_a = mint_shard_iri(SOURCE_URI, SPAN_A)[0]

    real = PersistentShardStore.get_record
    hidden = {iri_a: 1}

    async def racing_get_record(self, shard_iri):
        if hidden.get(shard_iri, 0) > 0:
            hidden[shard_iri] -= 1
            return None
        return await real(self, shard_iri)

    monkeypatch.setattr(PersistentShardStore, "get_record", racing_get_record)
    for doc, props in (
        ("doc-b1", [proposition("b1", SPAN_A, "Legal Proposition", role="plaintiff")]),
        ("doc-b2", [proposition("b2", SPAN_A, "Legal Proposition", role="plaintiff"),
                    proposition("b3", SPAN_B, "Judicial Finding of Fact")]),
    ):
        hidden[iri_a] = 1
        b = make_record(*props, document_id=doc, metadata={"exported_at": "2026-02-02T00:00:00Z"})
        report = await _ingest(storage_root, b)
        assert report.refused == 0, report.refused_shards
        assert iri_a in report.existing_iris
        assert {x["document_id"] for x in read_manifest(storage_root, CORPUS)[iri_a]} >= {doc}


async def test_concurrent_first_push_to_fresh_root(storage_root: Path) -> None:
    """Concurrent first opens of a brand-new journal race on the WAL pragma;
    ingest retries the open, so both pushes succeed."""
    import asyncio

    reports = await asyncio.gather(*(_ingest(storage_root, _record()) for _ in range(3)))
    assert all(r.refused == 0 for r in reports)
    assert sum(r.created for r in reports) == 2
    assert all(set(r.created_iris) | set(r.existing_iris) == set(reports[0].created_iris)
               | set(reports[0].existing_iris) for r in reports)


async def test_concurrent_ingest_of_same_record(storage_root: Path) -> None:
    import asyncio

    from tests.bridge_ingest.conftest import SYNTHETIC_RECORD

    # Create the storage root first: concurrent FIRST opens of a brand-new
    # journal race inside storage (see I1 report); this test is about pushes.
    await (await CorpusStorageContext.open(storage_root, CORPUS)).close()
    all_iris: set[str] = set()
    for record in (SYNTHETIC_RECORD, _record(metadata={})):  # with and without a timestamp
        reports = await asyncio.gather(_ingest(storage_root, record), _ingest(storage_root, record))
        iris = set(reports[0].created_iris) | set(reports[0].existing_iris)
        for report in reports:
            assert report.refused == 0, report.refused_shards
            assert set(report.created_iris) | set(report.existing_iris) == iris
        all_iris |= iris

    ctx = await CorpusStorageContext.open(storage_root, CORPUS)
    try:
        rows = await ctx.query(
            "SELECT ?s ?p WHERE { ?s <https://folio-insights.aleainstitute.ai/vocab/journalPosition> ?p }"
        )
        shard_rows = [r async for r in ctx.shards.iter_shards()]
    finally:
        await ctx.close()
    assert {r["s"].value for r in rows} == all_iris
    assert len(shard_rows) == len(all_iris)
    # One journal revision per IRI: no concurrent push wrote a second one.
    positions = {r["s"].value: int(r["p"].value) for r in rows}
    assert len(set(positions.values())) == len(all_iris)
