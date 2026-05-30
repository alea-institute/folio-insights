"""D-21 status-kind cross-check polarity tests (07-04b Task 1).

Per-status table:
  * ``authority_only`` → ≥1 cited shard must be a ConflictingAuthoritiesShard
    OR carry envelope ``epistemic_status == "authority_only"`` (closest match
    to the plan's ``AuthorityShard`` since Phase 2 ships no AuthorityShard
    subtype — see SUMMARY deviation note).
  * ``demonstrable`` → ≥1 cited shard must have ``epistemic_status`` in
    {demonstrable, per_se_nota_quoad_se, per_se_nota_quoad_nos, authority_only}.
  * ``per_se_nota_quoad_nos`` → no citation depth check (still requires the
    D-20 resolvability/non-self-citation, enforced upstream).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import PromotionEvent
from folio_insights.governance.promote import validate_promotion
from folio_insights.revision.store import InMemoryShardStore
from folio_insights.shards import (
    AuthorityPosition,
    ConflictingAuthoritiesShard,
    SimpleAssertionShard,
)
from folio_insights.shards.envelope import AttestedSignature
from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"


def _sig() -> AttestedSignature:
    return AttestedSignature(
        did=ALICE,
        action="promote",
        signed_at=datetime(2026, 1, 1, tzinfo=UTC),
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{ALICE}#key-1",
        did_doc_snapshot_at=datetime(2026, 1, 1, tzinfo=UTC),
        verified=None,
    )


async def _put_simple(
    store: InMemoryShardStore,
    iri: str,
    epistemic_status: str = "demonstrable",
) -> None:
    shard = _sample_shard(SimpleAssertionShard)
    shard = shard.model_copy(
        update={"shard_iri": iri, "epistemic_status": epistemic_status}
    )
    await store.put(iri, shard)


async def _put_conflicting_authorities(
    store: InMemoryShardStore, iri: str
) -> None:
    shard = _sample_shard(ConflictingAuthoritiesShard)
    shard = shard.model_copy(update={"shard_iri": iri})
    await store.put(iri, shard)


# ── POSITIVE: authority_only with ConflictingAuthoritiesShard cited ──


@pytest.mark.asyncio
async def test_authority_only_with_conflicting_authorities_cited_passes() -> None:
    store = InMemoryShardStore()
    await _put_conflicting_authorities(store, "fi:shard:auth")

    event = PromotionEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:promoted",
        new_status="authority_only",
        cited_iris=["fi:shard:auth"],
    )
    await validate_promotion(event, store=store)


# ── NEGATIVE: authority_only with SimpleAssertion cited ──


@pytest.mark.asyncio
async def test_authority_only_with_simple_assertion_cited_refused() -> None:
    store = InMemoryShardStore()
    await _put_simple(store, "fi:shard:simple", epistemic_status="hypothesis")

    event = PromotionEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:promoted",
        new_status="authority_only",
        cited_iris=["fi:shard:simple"],
    )
    with pytest.raises(ValueError) as exc_info:
        await validate_promotion(event, store=store)
    msg = str(exc_info.value).lower()
    assert "authority_only" in msg


# ── POSITIVE: demonstrable with demonstrable-status cited ──


@pytest.mark.asyncio
async def test_demonstrable_with_demonstrable_cited_passes() -> None:
    store = InMemoryShardStore()
    await _put_simple(store, "fi:shard:dem", epistemic_status="demonstrable")

    event = PromotionEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:promoted",
        new_status="demonstrable",
        cited_iris=["fi:shard:dem"],
    )
    await validate_promotion(event, store=store)


# ── NEGATIVE: demonstrable with hypothesis-status cited ──


@pytest.mark.asyncio
async def test_demonstrable_with_hypothesis_cited_refused() -> None:
    store = InMemoryShardStore()
    await _put_simple(store, "fi:shard:hyp", epistemic_status="hypothesis")

    event = PromotionEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:promoted",
        new_status="demonstrable",
        cited_iris=["fi:shard:hyp"],
    )
    with pytest.raises(ValueError) as exc_info:
        await validate_promotion(event, store=store)
    assert "demonstrable" in str(exc_info.value).lower()


# ── POSITIVE: per_se_nota_quoad_nos has no depth check ──


@pytest.mark.asyncio
async def test_per_se_nota_quoad_nos_no_depth_check() -> None:
    """Self-evident-to-us is axiomatic — cited shard's epistemic kind irrelevant."""
    store = InMemoryShardStore()
    # Cite a hypothesis-status shard — depth check would normally refuse, but
    # per_se_nota_quoad_nos bypasses depth checks (still respects D-20 resolvability).
    await _put_simple(store, "fi:shard:hyp", epistemic_status="hypothesis")

    event = PromotionEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:promoted",
        new_status="per_se_nota_quoad_nos",
        cited_iris=["fi:shard:hyp"],
    )
    await validate_promotion(event, store=store)
