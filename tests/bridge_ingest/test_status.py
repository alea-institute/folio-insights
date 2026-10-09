"""shard_status: present/absent, related and contesting shards, enrich sources."""
from __future__ import annotations

from pathlib import Path

import pytest

from folio_insights.bridge_ingest import ingest_record, shard_status
from folio_insights.shards import (
    AuthorityPosition,
    ConflictingAuthoritiesShard,
    DisputedPropositionShard,
    GlossShard,
    Objection,
    SimpleAssertionShard,
)
from folio_insights.shards.minting import mint_shard_iri
from folio_insights.storage import CorpusStorageContext
from tests.bridge_ingest.conftest import CORPUS, SOURCE_URI, make_record, proposition
from tests.shards.conftest import _sample_shard

SPAN = "A carrier may limit liability only with a fair opportunity to choose."
TARGET = mint_shard_iri(SOURCE_URI, SPAN)[0]
ABSENT = "urn:folio:shard/" + "e" * 32


def _other(cls, n: int, **overrides):
    iri, h = mint_shard_iri("urn:x:status-test", f"span {n}")
    return _sample_shard(cls, shard_iri=iri, provenance_hash=h, source_span=f"span {n}", **overrides)


async def test_status_relations(storage_root: Path) -> None:
    await ingest_record(
        make_record(proposition("p1", SPAN), proposition("p2", SPAN, "cited-authority proposition")),
        corpus_root=storage_root, corpus=CORPUS,
    )
    dependent = _other(SimpleAssertionShard, 1, depends_on_shards=[TARGET])
    elaborator = _other(SimpleAssertionShard, 2, elaborates=[TARGET])
    gloss = _other(GlossShard, 3, glosses=TARGET)
    conflict = _other(
        ConflictingAuthoritiesShard, 4,
        sic=[AuthorityPosition(authority_iri=TARGET, position="Holds.", jurisdiction="us", weight="binding")],
    )
    disputed = _other(
        DisputedPropositionShard, 5,
        objections=[Objection(cites=TARGET, argues="It seems not.", strength=0.4)],
    )
    contested = _other(SimpleAssertionShard, 6, contested=True)
    ctx = await CorpusStorageContext.open(storage_root, CORPUS)
    try:
        await ctx.ingest_shards([dependent, elaborator, gloss, conflict, disputed, contested])
        results = await shard_status(ctx, [ABSENT, TARGET, contested.shard_iri, TARGET])
    finally:
        await ctx.close()

    assert [r.iri for r in results] == [ABSENT, TARGET, contested.shard_iri]
    absent, target, flagged = results
    assert absent.present is False
    assert absent.shard_type is None and absent.contested is None
    assert absent.related == [] and absent.contesting == [] and absent.enrich_sources == []

    assert target.present and target.shard_type == "hypothesis"
    assert target.epistemic_status == "hypothesis" and target.contested is False
    related = {(r.iri, r.relation) for r in target.related}
    assert related == {
        (dependent.shard_iri, "depended_on_by"),
        (elaborator.shard_iri, "elaborated_by"),
        (gloss.shard_iri, "glossed_by"),
    }
    contesting = {(c.iri, c.relation) for c in target.contesting}
    assert contesting == {
        (conflict.shard_iri, "conflicting_authority"),
        (disputed.shard_iri, "objection"),
    }
    assert {s.proposition_id for s in target.enrich_sources} == {"p1", "p2"}
    assert flagged.present and flagged.contested is True


async def test_status_forward_relations(storage_root: Path) -> None:
    await ingest_record(make_record(proposition("p1", SPAN)), corpus_root=storage_root, corpus=CORPUS)
    dependent = _other(SimpleAssertionShard, 11, depends_on_shards=[TARGET], elaborates=[TARGET])
    ctx = await CorpusStorageContext.open(storage_root, CORPUS)
    try:
        await ctx.ingest_shards([dependent])
        (result,) = await shard_status(ctx, [dependent.shard_iri])
    finally:
        await ctx.close()
    assert {(r.iri, r.relation) for r in result.related} == {
        (TARGET, "depends_on"), (TARGET, "elaborates"),
    }


async def test_status_rejects_bad_iris(storage_root: Path) -> None:
    ctx = await CorpusStorageContext.open(storage_root, CORPUS)
    try:
        with pytest.raises(ValueError):
            await shard_status(ctx, ["urn:folio:shard/XYZ> } DROP ALL #"])
        assert await shard_status(ctx, []) == []
    finally:
        await ctx.close()


async def test_status_supersession(storage_root: Path) -> None:
    await ingest_record(make_record(proposition("p1", SPAN)), corpus_root=storage_root, corpus=CORPUS)
    successor = _other(SimpleAssertionShard, 21, supersedes=TARGET)
    ctx = await CorpusStorageContext.open(storage_root, CORPUS)
    try:
        await ctx.ingest_shards([successor])
        target, succ = await shard_status(ctx, [TARGET, successor.shard_iri])
    finally:
        await ctx.close()
    assert (successor.shard_iri, "superseded_by") in {(c.iri, c.relation) for c in target.contesting}
    assert succ.supersedes == TARGET
