"""Plan R14 / AE4: an enrich export ingested into a temp corpus is found by SPARQL.

Data-driven and parametrized over both committed records: the real folio-enrich
export of a public-domain opinion (``fixtures/enrich-propositions-record.json``)
and the synthetic one (``fixtures/synthetic-propositions-record.json``).
Everything asserted is derived from the file, so swapping in another export
needs no code change.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from folio_insights.bridge_ingest import ingest_record, load_record, shard_status
from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.projection import corpus_graph
from tests.bridge_ingest.conftest import E2E_RECORDS

CORPUS = "e2e-enrich"
FI = "https://folio-insights.aleainstitute.ai/vocab/"

records = pytest.mark.parametrize("record_path", E2E_RECORDS, ids=lambda p: p.stem)


def _expected(record_path: Path) -> tuple[set[str], dict[str, set[str]]]:
    record = load_record(record_path).record
    iris: set[str] = set()
    by_iri: dict[str, set[str]] = {}
    for p in record.propositions:
        if p.content_iri is None:
            continue
        iris.add(p.content_iri)
        by_iri.setdefault(p.content_iri, set()).add(p.id)
    return iris, by_iri


@records
async def test_enrich_record_round_trip(storage_root: Path, record_path: Path) -> None:
    expected, sources = _expected(record_path)
    assert len(expected) >= 1
    report = await ingest_record(
        record_path, corpus_root=storage_root, corpus=CORPUS,
        framework_id="us.case-law.unspecified", extractor_did="did:web:folio-enrich.local",
    )
    assert report.refused == 0, report.refused_shards
    assert report.manifest_refused == []
    assert set(report.created_iris) == expected

    ctx = await CorpusStorageContext.open(storage_root, CORPUS)
    try:
        rows = await ctx.query(
            f'SELECT ?s WHERE {{ GRAPH {corpus_graph(CORPUS)} '
            f'{{ ?s <{FI}shardType> "hypothesis" }} }}'
        )
        assert {row["s"].value for row in rows} == expected
        # The spec's GRAPH ?g form finds the same set.
        rows = await ctx.query(
            f'SELECT DISTINCT ?s WHERE {{ GRAPH ?g {{ ?s <{FI}shardType> "hypothesis" }} }}'
        )
        assert {row["s"].value for row in rows} == expected

        results = await shard_status(ctx, sorted(expected))
        for result in results:
            assert result.present
            assert result.shard_type == "hypothesis"
            assert result.epistemic_status == "hypothesis"
            assert result.contested is False
            assert {s.proposition_id for s in result.enrich_sources} == sources[result.iri]
    finally:
        await ctx.close()


@records
async def test_fixture_has_a_shared_span(record_path: Path) -> None:
    """Each fixture exercises R12 (≥5 propositions, at least one shared span)."""
    _, sources = _expected(record_path)
    assert sum(len(v) for v in sources.values()) >= 5
    assert any(len(v) >= 2 for v in sources.values())
