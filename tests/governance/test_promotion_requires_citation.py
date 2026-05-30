"""D-20 cite-resolvable promotion-validator polarity tests (07-04b Task 1).

``validate_promotion`` enforces:
  * each `cited_iris` IRI resolves in the ShardStore (no dangling citations);
  * none of `cited_iris` equals `event.shard_iri` (no self-citation).

Pydantic field-level ``Field(min_length=1)`` on ``cited_iris`` enforces the
"at least one citation" rule at construction time; D-20's CODE-LAYER second
gate is what this module exercises directly.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import PromotionEvent
from folio_insights.governance.promote import validate_promotion
from folio_insights.revision.store import InMemoryShardStore
from folio_insights.shards.envelope import AttestedSignature
from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"


def _sig(action: str = "promote") -> AttestedSignature:
    return AttestedSignature(
        did=ALICE,
        action=action,  # type: ignore[arg-type]
        signed_at=datetime(2026, 1, 1, tzinfo=UTC),
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{ALICE}#key-1",
        did_doc_snapshot_at=datetime(2026, 1, 1, tzinfo=UTC),
        verified=None,
    )


async def _put_authority(store: InMemoryShardStore, iri: str) -> None:
    """Seed an AuthorityShard-like cited shard (uses AuthorityShard subtype if
    present; otherwise falls back to the demonstrable-status envelope)."""
    from folio_insights.shards import SimpleAssertionShard

    shard = _sample_shard(SimpleAssertionShard)
    shard = shard.model_copy(
        update={"shard_iri": iri, "epistemic_status": "demonstrable"}
    )
    await store.put(iri, shard)


# ── POSITIVE ──


@pytest.mark.asyncio
async def test_resolvable_citation_passes() -> None:
    """PromotionEvent with a cited IRI that resolves in the store → no raise."""
    store = InMemoryShardStore()
    await _put_authority(store, "fi:shard:cited")

    event = PromotionEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:promoted",
        new_status="demonstrable",
        cited_iris=["fi:shard:cited"],
    )

    # No raise.
    await validate_promotion(event, store=store)


# ── NEGATIVE ──


def test_empty_cited_iris_refused_at_pydantic_level() -> None:
    """D-20: cited_iris=[] is refused by Pydantic Field(min_length=1)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PromotionEvent(
            corpus=CORPUS,
            signature=_sig(),
            shard_iri="fi:shard:promoted",
            new_status="demonstrable",
            cited_iris=[],
        )


@pytest.mark.asyncio
async def test_unresolvable_iri_refused() -> None:
    """D-20: any IRI not in the ShardStore raises ValueError mentioning 'unresolvable'."""
    store = InMemoryShardStore()
    # Store empty — citation cannot resolve.
    event = PromotionEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:promoted",
        new_status="demonstrable",
        cited_iris=["fi:shard:nonexistent"],
    )
    with pytest.raises(ValueError) as exc_info:
        await validate_promotion(event, store=store)
    msg = str(exc_info.value).lower()
    assert "unresolvable" in msg or "not in store" in msg, (
        f"expected diagnostic about unresolvable IRI; got: {exc_info.value}"
    )


@pytest.mark.asyncio
async def test_self_citation_refused() -> None:
    """D-20: cited_iris containing event.shard_iri raises ValueError mentioning 'self-citation'."""
    store = InMemoryShardStore()
    await _put_authority(store, "fi:shard:promoted")  # self-citation target exists in store

    event = PromotionEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:promoted",
        new_status="demonstrable",
        cited_iris=["fi:shard:promoted"],  # self-cite
    )
    with pytest.raises(ValueError) as exc_info:
        await validate_promotion(event, store=store)
    assert "self-citation" in str(exc_info.value).lower()
