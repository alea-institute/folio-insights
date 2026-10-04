"""U4: the eight Phase 13 export formats, their capability refusals and the
signed-record round trip (synthetic data, generated identities)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pyoxigraph import DefaultGraph, Literal, NamedNode, Quad, RdfFormat, Triple, parse

import folio_insights.storage.exports as exports
from folio_insights.governance.events import GovernanceEvent
from folio_insights.identity import sign_attestation, verify_attestation
from folio_insights.identity.cache import InMemoryDidDocCache
from folio_insights.revision.content_edit import canonical_content_hash
from folio_insights.shards import load_shard_record
from folio_insights.storage import (
    CorpusStorageContext,
    PiiRejected,
    verify_event_signature_offline,
)
from folio_insights.storage.exports import (
    ALL_FORMATS,
    CAPABILITIES,
    ExportDataset,
    ExportFormat,
    ExportLossDetected,
    ExportRefused,
    abox_filename,
    build_export_dataset,
    canonical_quads,
    check_capabilities,
    export_corpus,
    read_neo4j,
)
from folio_insights.storage.journal import JOURNAL_FILENAME
from folio_insights.storage.projection import TBOX_GRAPH, corpus_graph, governance_graph

from tests.storage.conftest import genesis, new_identity, role_assertion, at, shard

pytestmark = pytest.mark.storage

FI = "https://folio-insights.aleainstitute.ai/vocab/"
CORPUS = "corpus/a b"  # needs percent-encoding in IRIs and file names
CONSTRUCT_ALL_SHARDS = (
    f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ ?s a <{FI}Shard> ; ?p ?o }}"
)
PII = {
    "ssn": "synthetic ssn 123-45-6789",
    "phone": "call (212) 555-0142 today",
    "aba": "routing 011000015 here",
}


def _signed_shard(n: int, signer) -> object:  # noqa: ANN001
    s = shard(n)
    s.signatures.append(
        sign_attestation(
            canonical_content_hash(s),
            signer.sk,
            signer.did,
            "extract",
            signing_key_id=signer.key_id,
            did_doc_snapshot_at=None,
            now=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
    )
    return s


@pytest.fixture
async def populated(tmp_path: Path):  # noqa: ANN201
    admin, signer = new_identity(), new_identity()
    root = tmp_path / "storage"
    ctx = await CorpusStorageContext.open(root, CORPUS)
    other = await CorpusStorageContext.open(root, "corpus-b")
    await ctx.governance.append(genesis(CORPUS, admin))
    await ctx.governance.append(role_assertion(CORPUS, admin, signer.did, "reviewer", at(1)))
    await ctx.ingest_shards([_signed_shard(n, signer) for n in range(1, 6)])
    revised = shard(2, sense="revised synthetic sense")
    revised.signatures.extend((await ctx.shards.get(shard(2).shard_iri)).signatures)
    await ctx.shards.put(revised.shard_iri, revised)
    await other.ingest_shards([shard(99)])
    # Refused inputs: never journaled, so never exported or dumped.
    for field, text in (("sense", PII["ssn"]), ("source_span", PII["phone"]),
                        ("reference", PII["aba"])):
        with pytest.raises(PiiRejected):
            await ctx.ingest_shards([shard(50, **{field: text})])
    try:
        yield ctx, signer, tmp_path
    finally:
        await ctx.close()
        await other.close()


async def test_all_formats_round_trip(populated) -> None:  # noqa: ANN001
    ctx, _, tmp = populated
    dest = tmp / "export"
    result = await export_corpus(
        ctx, dest, list(ExportFormat), construct_query=CONSTRUCT_ALL_SHARDS
    )
    dataset = await build_export_dataset(ctx)
    abox, gov = corpus_graph(CORPUS), governance_graph(CORPUS)
    quads = dataset.quads()
    assert {q.graph_name for q in quads} == {abox, gov, TBOX_GRAPH}

    def triples(qs):  # noqa: ANN001, ANN202
        return [Quad(q.subject, q.predicate, q.object, DefaultGraph()) for q in qs]

    def ttl(rel: str) -> list[Quad]:
        return list(parse(path=str(dest / rel), format=RdfFormat.TURTLE))

    # Independent re-parse of every format (the exporter also checks itself).
    assert canonical_quads(parse(path=str(dest / "dataset.nq"), format=RdfFormat.N_QUADS)) == (
        canonical_quads(quads)
    )
    assert canonical_quads(
        parse(path=str(dest / "dataset.jsonld"), format=RdfFormat.JSON_LD)
    ) == canonical_quads(quads)
    assert canonical_quads(read_neo4j(dest)) == canonical_quads(quads)
    assert canonical_quads(triples(ttl("combined.ttl"))) == canonical_quads(triples(quads))
    assert canonical_quads(triples(ttl(abox_filename(CORPUS)))) == canonical_quads(
        triples(dataset.graph(abox))
    )
    assert canonical_quads(triples(ttl("governance.ttl"))) == canonical_quads(
        triples(dataset.graph(gov))
    )
    assert canonical_quads(triples(ttl("tbox.ttl"))) == canonical_quads(
        triples(dataset.graph(TBOX_GRAPH))
    )
    construct = triples(ttl("construct.ttl"))
    assert {str(q.subject) for q in construct} == {
        f"<{s.shard_iri}>" for s in (shard(n) for n in range(1, 6))
    }

    manifest = json.loads((dest / "manifest.json").read_text())
    assert manifest == json.loads(json.dumps(result.manifest))
    assert set(manifest["formats"]) == {f.value for f in ExportFormat}
    assert manifest["graphs"] == {"abox": abox.value, "governance": gov.value,
                                  "tbox": TBOX_GRAPH.value}
    assert manifest["formats"]["abox"]["files"][0]["graph"] == abox.value
    assert manifest["full_shacl"] == "deferred-to-phase-11"
    # Corpus isolation: nothing of corpus-b in any file.
    for path in dest.rglob("*"):
        if path.is_file():
            assert shard(99).shard_iri not in path.read_text(encoding="utf-8")


async def test_signed_records_survive_every_format(populated) -> None:  # noqa: ANN001
    ctx, signer, tmp = populated
    dest = tmp / "export"
    await export_corpus(ctx, dest)
    stored = await ctx.shards.get_record(shard(3).shard_iri)
    assert stored is not None
    sources = {
        "nquads": list(parse(path=str(dest / "dataset.nq"), format=RdfFormat.N_QUADS)),
        "jsonld": list(parse(path=str(dest / "dataset.jsonld"), format=RdfFormat.JSON_LD)),
        "neo4j": read_neo4j(dest),
        "abox": list(parse(path=str(dest / abox_filename(CORPUS)), format=RdfFormat.TURTLE)),
    }
    cache = InMemoryDidDocCache()
    for name, quads in sources.items():
        records = {
            q.subject.value: q.object.value
            for q in quads
            if q.predicate == NamedNode(f"{FI}signedRecord")
        }
        assert set(records) == {shard(n).shard_iri for n in range(1, 6)}, name
        raw = records[shard(3).shard_iri].encode("utf-8")
        assert raw == stored.original_bytes, name
        reloaded = load_shard_record(raw).shard
        assert reloaded == stored.shard, name
        assert reloaded.signatures[0].did == signer.did
        assert await verify_attestation(reloaded, reloaded.signatures[0], cache=cache), name
        # The revised shard carries its original signature but no longer verifies
        # under it: the export keeps the evidence, it does not launder it.
        revised = load_shard_record(records[shard(2).shard_iri].encode("utf-8")).shard
        assert revised.sense == "revised synthetic sense"
        assert not await verify_attestation(revised, revised.signatures[0], cache=cache)

    events = [
        q.object.value
        for q in parse(path=str(dest / "governance.ttl"), format=RdfFormat.TURTLE)
        if q.predicate == NamedNode(f"{FI}signedEvent")
    ]
    assert len(events) == 2
    from pydantic import TypeAdapter

    adapter = TypeAdapter(GovernanceEvent)
    for text in events:
        assert await verify_event_signature_offline(adapter.validate_json(text))


async def test_named_graph_requirement_refuses_graphless_formats(populated) -> None:  # noqa: ANN001
    ctx, _, tmp = populated
    for fmt in (ExportFormat.COMBINED_TTL, ExportFormat.SPARQL_CONSTRUCT):
        with pytest.raises(ExportRefused, match="cannot carry named graphs"):
            await export_corpus(
                ctx, tmp / f"refused-{fmt.name}", [fmt],
                construct_query=CONSTRUCT_ALL_SHARDS, require_named_graphs=True,
            )
        assert not (tmp / f"refused-{fmt.name}").exists()
    ok = await export_corpus(
        ctx, tmp / "graphs", [f for f in ALL_FORMATS if CAPABILITIES[f].named_graphs != "none"],
        require_named_graphs=True,
    )
    assert "combined.ttl" not in ok.manifest["formats"]


def test_triple_terms_are_refused_by_formats_that_cannot_carry_them() -> None:
    s = NamedNode("urn:x:s")
    term = Triple(s, NamedNode("urn:x:p"), Literal("o"))
    dataset = ExportDataset(corpus="c", watermark=0, watermark_payload_sha256=None, graphs={
        "urn:g": [Quad(s, NamedNode(f"{FI}reifies"), term, NamedNode("urn:g"))]
    })
    for fmt in (ExportFormat.JSON_LD, ExportFormat.NEO4J_CSV):
        with pytest.raises(ExportRefused, match="triple terms"):
            check_capabilities([fmt], dataset, require_named_graphs=False)
    check_capabilities([ExportFormat.N_QUADS, ExportFormat.COMBINED_TTL], dataset,
                       require_named_graphs=False)


async def test_partial_construct_is_refused_unless_acknowledged(populated) -> None:  # noqa: ANN001
    ctx, _, tmp = populated
    query = f"CONSTRUCT {{ ?s <{FI}sense> ?o }} WHERE {{ ?s <{FI}sense> ?o }}"
    with pytest.raises(ExportRefused, match="identity/signature"):
        await export_corpus(ctx, tmp / "partial", [ExportFormat.SPARQL_CONSTRUCT],
                            construct_query=query)
    assert not (tmp / "partial").exists()
    events = (
        f"CONSTRUCT {{ ?e <{FI}action> ?a }} WHERE {{ ?e a <{FI}GovernanceEvent> ; "
        f"<{FI}action> ?a }}"
    )
    with pytest.raises(ExportRefused, match="event"):
        await export_corpus(ctx, tmp / "partial-ev", [ExportFormat.SPARQL_CONSTRUCT],
                            construct_query=events)
    result = await export_corpus(
        ctx, tmp / "partial", [ExportFormat.SPARQL_CONSTRUCT],
        construct_query=query, allow_partial=True,
    )
    assert result.manifest["partial"] is True
    with pytest.raises(ExportRefused, match="construct_query"):
        await export_corpus(ctx, tmp / "noquery", [ExportFormat.SPARQL_CONSTRUCT])


async def test_lossy_serialization_is_detected_and_removed(
    populated, monkeypatch: pytest.MonkeyPatch  # noqa: ANN001
) -> None:
    ctx, _, tmp = populated
    real = exports.serialize

    def dropping(items, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        items = list(items)
        return real(items[1:], *args, **kwargs)  # silently drops one (ground) statement

    for fmt in (ExportFormat.N_QUADS, ExportFormat.JSON_LD, ExportFormat.COMBINED_TTL,
                ExportFormat.ABOX_TTL):
        monkeypatch.setattr(exports, "serialize", dropping)
        dest = tmp / f"lossy-{fmt.name}"
        with pytest.raises(ExportLossDetected, match="1 quad"):
            await export_corpus(ctx, dest, [fmt])
        assert not dest.exists()
        monkeypatch.setattr(exports, "serialize", real)

    # Into an existing empty directory: only what this call wrote is removed.
    dest = tmp / "existing"
    dest.mkdir()
    monkeypatch.setattr(exports, "serialize", dropping)
    with pytest.raises(ExportLossDetected):
        await export_corpus(ctx, dest, [ExportFormat.N_QUADS])
    assert dest.is_dir() and not any(dest.iterdir())


async def test_destination_boundaries(populated, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    ctx, _, tmp = populated
    with pytest.raises(ExportRefused, match="storage root"):
        await export_corpus(ctx, ctx.root / "exports")
    served = tmp / "served"
    monkeypatch.setattr(exports, "_served_output_dir", lambda: served.resolve())
    with pytest.raises(ExportRefused, match="served output"):
        await export_corpus(ctx, served / "corpus")
    full = tmp / "full"
    full.mkdir()
    (full / "keep.txt").write_text("not ours")
    with pytest.raises(ExportRefused, match="not empty"):
        await export_corpus(ctx, full)
    assert (full / "keep.txt").read_text() == "not ours"


async def test_refused_pii_reaches_no_export_and_no_journal(populated) -> None:  # noqa: ANN001
    ctx, _, tmp = populated
    dest = tmp / "export"
    await export_corpus(ctx, dest, list(ExportFormat), construct_query=CONSTRUCT_ALL_SHARDS)
    blobs = [p.read_bytes() for p in dest.rglob("*") if p.is_file()]
    blobs += [p.read_bytes() for p in ctx.root.glob(f"{JOURNAL_FILENAME}*")]
    for text in PII.values():
        needle = text.encode("utf-8")
        assert not any(needle in blob for blob in blobs), text
    assert not any(shard(50).shard_iri.encode() in blob for blob in blobs)
