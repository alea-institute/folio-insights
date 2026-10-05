"""Phase 9 U3 (R6, KTD6/KTD7) — the three revision kinds as derived state.

Retraction (policy outcome for direct dependents, flag-only deeper),
supersession (both shards queryable; query_as_of picks the right one per
window), contest (resolved by arbiter distinguo with the signed log intact)
and the no-mutation rule (journal payload bytes never change). Generated
identities, synthetic shards, disposable roots.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from folio_insights.governance.events import (
    ContestEvent,
    ContestResolutionEvent,
    PromotionEvent,
    SupersessionEvent,
)
from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.governance.retract import (
    PreviewStale,
    build_cascade_preview,
    commit_cascade,
)
from folio_insights.revision.effective_state import (
    as_of_graph,
    derive_effective_states,
    effective_states,
)
from folio_insights.revision.hypothesis import ExtractionHypothesis, group_hypotheses
from folio_insights.revision.store import InMemoryShardStore
from folio_insights.shards import HypothesisShard
from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.context import verify_event_signature_offline
from folio_insights.temporal import query_as_of
from folio_insights.temporal.as_of import FI

from tests.shards.conftest import _sample_shard
from tests.storage.conftest import _unsigned, at, genesis, new_identity, shard, sign_event


def iri(n: int) -> str:
    return f"urn:folio:shard/{n:032x}"


def web(*, with_successor: bool) -> list:
    """1 is retracted; 2 and 3 depend on 1; 4 depends on 2; 5 depends on 4.
    9 is 1's successor when ``with_successor``."""
    out = [
        shard(1, superseded_by=iri(9) if with_successor else None),
        shard(2, depends_on_shards=[iri(1)]),
        shard(3, depends_on_precedents=[iri(1)]),
        shard(4, depends_on_shards=[iri(2)]),
        shard(5, depends_on_definitions=[iri(4)]),
    ]
    if with_successor:
        out.append(shard(9, supersedes=iri(1)))
    return out


async def _memory_store(shards) -> InMemoryShardStore:
    store = InMemoryShardStore("corpus-a")
    for s in shards:
        await store.put(s.shard_iri, s)
    return store


# ── retraction ────────────────────────────────────────────────────────────


async def test_prefer_latest_with_successor_rederives_direct_dependents() -> None:
    store = await _memory_store(web(with_successor=True))
    preview = await build_cascade_preview(
        iri(1), "corpus-a", store=store, log=InMemoryGovernanceLog(), policy="prefer_latest"
    )
    assert preview.policy == "prefer_latest"
    assert preview.auto_rederive == [iri(2), iri(3)]
    assert preview.aporetic == []
    assert preview.review_needed == [iri(4), iri(5)]  # deeper: flagged only
    assert preview.depths == {iri(2): 1, iri(3): 1, iri(4): 2, iri(5): 3}
    assert preview.cycles == []


async def test_prefer_latest_without_successor_reads_aporetic() -> None:
    store = await _memory_store(web(with_successor=False))
    preview = await build_cascade_preview(
        iri(1), "corpus-a", store=store, log=InMemoryGovernanceLog()
    )
    assert preview.aporetic == [iri(2), iri(3)]
    assert preview.auto_rederive == []
    assert preview.review_needed == [iri(4), iri(5)]


async def test_policy_is_bound_into_the_preview_and_its_hash() -> None:
    store = await _memory_store(web(with_successor=True))
    log = InMemoryGovernanceLog()
    latest = await build_cascade_preview(iri(1), "corpus-a", store=store, log=log, op_id="x")
    authority = await build_cascade_preview(
        iri(1), "corpus-a", store=store, log=log, op_id="x", policy="prefer_authority"
    )
    assert latest.underlying_state_hash != authority.underlying_state_hash
    with pytest.raises(ValueError, match="unknown cascade policy"):
        await build_cascade_preview(iri(1), "corpus-a", store=store, log=log, policy="nope")  # type: ignore[arg-type]


async def test_cycle_touching_the_cascade_is_a_finding() -> None:
    shards = [
        shard(1, depends_on_shards=[iri(3)]),
        shard(2, depends_on_shards=[iri(1)]),
        shard(3, depends_on_shards=[iri(2)]),
    ]
    store = await _memory_store(shards)
    preview = await build_cascade_preview(
        iri(1), "corpus-a", store=store, log=InMemoryGovernanceLog()
    )
    assert preview.cycles == [[iri(1), iri(3), iri(2)]]
    assert preview.depths == {iri(2): 1, iri(3): 2}


async def test_committed_retraction_derives_state_and_keeps_journal_bytes(
    tmp_path: Path,
) -> None:
    admin = new_identity()
    ctx = await CorpusStorageContext.open(tmp_path / "storage", "corpus-a")
    try:
        await ctx.governance.append(genesis("corpus-a", admin))
        await ctx.ingest_shards(web(with_successor=True))
        before = _journal_payloads(ctx.journal_path)
        head = await ctx.journal_head()
        preview = await build_cascade_preview(
            iri(1), "corpus-a", store=ctx.shards, log=ctx.governance,
            state_position=head, policy="prefer_latest",
        )
        assert preview.auto_rederive == [iri(2), iri(3)]
        event = await commit_cascade(
            preview, store=ctx.shards, log=ctx.governance, signing_key=admin.sk, did=admin.did
        )
        assert event.action == "retract"

        states = await effective_states(ctx.shards, ctx.governance, policy=preview.policy)
        assert states[iri(1)].status == "retracted"
        assert [states[iri(n)].status for n in (2, 3)] == ["auto_rederive", "auto_rederive"]
        assert (states[iri(4)].status, states[iri(4)].depth) == ("review_needed", 2)
        assert (states[iri(5)].status, states[iri(5)].depth) == ("review_needed", 3)
        assert states[iri(9)].status == "current"
        assert states[iri(2)].cause == iri(1)

        # history is intact: every shard is still stored, unchanged
        after = _journal_payloads(ctx.journal_path)
        shard_rows = {k: v for k, v in after.items() if v[0] == "shard"}
        assert all(before[k] == v for k, v in shard_rows.items())
        assert len(after) == len(before) + 1  # only the retraction event appended
        assert (await ctx.shards.get(iri(1))) is not None
    finally:
        await ctx.close()


async def test_commit_refuses_when_the_policy_outcome_changed() -> None:
    store = await _memory_store(web(with_successor=False))
    log = InMemoryGovernanceLog()
    preview = await build_cascade_preview(iri(1), "corpus-a", store=store, log=log)
    await store.put(iri(9), shard(9, supersedes=iri(1)))
    await store.put(iri(1), shard(1, superseded_by=iri(9)))  # a successor appeared
    admin = new_identity()
    with pytest.raises(PreviewStale):
        await commit_cascade(preview, store=store, log=log, signing_key=admin.sk, did=admin.did)


# ── supersession ──────────────────────────────────────────────────────────


async def test_supersession_keeps_both_queryable_and_as_of_picks_the_window(
    tmp_path: Path,
) -> None:
    admin = new_identity()
    t_old, t_new = datetime(2000, 12, 1, tzinfo=UTC), datetime(2023, 12, 1, tzinfo=UTC)
    old = shard(11, valid_time_start=t_old, sense="rule as of 2000", reference="fre:rule702")
    new = shard(12, valid_time_start=t_new, sense="rule as of 2023",
                reference="fre:rule702", supersedes=iri(11))
    ctx = await CorpusStorageContext.open(tmp_path / "storage", "corpus-a")
    try:
        await ctx.governance.append(genesis("corpus-a", admin))
        await ctx.ingest_shards([old, new])
        event = SupersessionEvent(
            corpus="corpus-a",
            signature=_unsigned(admin.did, "supersede", at(10)),
            old_shard_iri=iri(11),
            new_shard_iri=iri(12),
        )
        await ctx.governance.append(sign_event(event, admin, at(10)))
        states = await effective_states(ctx.shards, ctx.governance)
        assert states[iri(11)].status == "superseded"
        assert states[iri(11)].superseded_by == iri(12)
        assert states[iri(11)].valid_time_end == t_new  # aligned to the successor's start
        assert states[iri(12)].status == "current"
        # both stay queryable, unchanged
        assert (await ctx.shards.get(iri(11))).valid_time_end is None
        rows = await ctx.query(
            "SELECT ?s WHERE { ?s <https://folio-insights.aleainstitute.ai/vocab/reference> "
            '"fre:rule702" } ORDER BY ?s'
        )
        assert [r["s"].value for r in rows] == [iri(11), iri(12)]
        stored = [s async for s in ctx.shards.iter_shards()]
    finally:
        await ctx.close()
    graph = as_of_graph(stored, states)
    assert query_as_of(graph, FI.sense, datetime(2010, 1, 1, tzinfo=UTC)) == [
        (pytest.importorskip("rdflib").URIRef(iri(11)),
         pytest.importorskip("rdflib").Literal("rule as of 2000"))
    ]
    later = query_as_of(graph, FI.sense, datetime(2024, 6, 1, tzinfo=UTC))
    assert [str(s) for s, _ in later] == [iri(12)]
    assert query_as_of(graph, FI.sense, datetime(1990, 1, 1, tzinfo=UTC)) == []


def test_supersession_without_successor_start_uses_the_event_time() -> None:
    admin = new_identity()
    old, new = shard(21), shard(22, supersedes=iri(21))
    event = SupersessionEvent(
        corpus="corpus-a", position=3, signature=_unsigned(admin.did, "supersede", at(5)),
        old_shard_iri=iri(21), new_shard_iri=iri(22),
    )
    states = derive_effective_states([old, new], [event])
    assert states[iri(21)].valid_time_end == at(5) and states[iri(21)].events == (3,)


# ── contest ───────────────────────────────────────────────────────────────


async def test_contest_of_promoted_shard_resolves_by_arbiter_distinguo(tmp_path: Path) -> None:
    admin, voter = new_identity(), new_identity()
    hypothesis = _sample_shard(
        HypothesisShard, shard_iri=iri(31), epistemic_status="hypothesis",
        depends_on_precedents=[iri(32)],
    )
    ctx = await CorpusStorageContext.open(tmp_path / "storage", "corpus-a")
    try:
        await ctx.governance.append(genesis("corpus-a", admin))
        await ctx.ingest_shards([hypothesis, shard(32)])
        promote = PromotionEvent(
            corpus="corpus-a", signature=_unsigned(admin.did, "promote", at(1)),
            shard_iri=iri(31), new_status="demonstrable", cited_iris=[iri(32)],
        )
        await ctx.governance.append(sign_event(promote, admin, at(1)))
        contest = ContestEvent(
            corpus="corpus-a", signature=_unsigned(admin.did, "contest", at(2)),
            shard_iri=iri(31), voter_did=voter.did, position_text="synthetic objection",
        )
        await ctx.governance.append(sign_event(contest, admin, at(2)))
        mid = await effective_states(ctx.shards, ctx.governance)
        assert mid[iri(31)].status == "contested"

        resolve = ContestResolutionEvent(
            corpus="corpus-a", signature=_unsigned(admin.did, "resolve_contest", at(3)),
            shard_iri=iri(31), resolution_path="distinguo",
        )
        await ctx.governance.append(sign_event(resolve, admin, at(3)))
        final = await effective_states(ctx.shards, ctx.governance)
        assert final[iri(31)].status == "resolved"
        assert final[iri(31)].contest_resolution == "distinguo"

        events = [e async for e in ctx.governance.iter_events("corpus-a")]
        assert [e.action for e in events] == [
            "role_assertion", "promote", "contest", "resolve_contest"
        ]
        assert [e.position for e in events] == [0, 1, 2, 3]
        assert all([await verify_event_signature_offline(e) for e in events])
        assert final[iri(31)].events == (2, 3)
    finally:
        await ctx.close()


def test_aporetic_resolution_reads_aporetic() -> None:
    did = new_identity().did
    events = [
        ContestEvent(corpus="c", position=0, signature=_unsigned(did, "contest", at(1)),
                     shard_iri=iri(41), voter_did=did, position_text="x"),
        ContestResolutionEvent(corpus="c", position=1,
                               signature=_unsigned(did, "resolve_contest", at(2)),
                               shard_iri=iri(41), resolution_path="aporetic"),
    ]
    assert derive_effective_states([shard(41)], events)[iri(41)].status == "aporetic"


# ── ExtractionHypothesis ──────────────────────────────────────────────────


def test_extraction_hypothesis_holds_competing_readings_of_one_span() -> None:
    a = _sample_shard(HypothesisShard, sense="reading A", source_span="span 7")
    b = _sample_shard(HypothesisShard, sense="reading B", source_span="span 7")
    group = ExtractionHypothesis.of([b, a, a])
    assert group.competing and len(group.candidates) == 2
    assert group.content_hashes == tuple(sorted(group.content_hashes))
    assert group.candidate(group.content_hashes[0]) in (a, b)
    other = _sample_shard(HypothesisShard, source_span="span 8")
    with pytest.raises(ValueError):
        ExtractionHypothesis.of([a, other])
    with pytest.raises(TypeError):
        ExtractionHypothesis.of([shard(1)])  # type: ignore[list-item]
    groups = group_hypotheses([a, b, other, shard(1)])
    assert [len(g.candidates) for g in groups] == [2, 1]
    assert [len(g.candidates) for g in group_hypotheses([a, b, other], competing_only=True)] == [2]


def _journal_payloads(path: Path) -> dict[tuple[str, int], tuple[str, bytes, bytes | None]]:
    with sqlite3.connect(path) as conn:
        return {
            (corpus, pos): (kind, payload, original)
            for corpus, pos, kind, payload, original in conn.execute(
                "SELECT corpus, position, kind, payload, original_bytes FROM journal"
            )
        }
