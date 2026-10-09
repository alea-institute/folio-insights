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
