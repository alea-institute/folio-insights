"""Hypothesis property tests for get_shard_at reverse-replay invariants (D-09).

Generates a random sequence of N edits to mutable fields with strictly-monotonic
timestamps, then asserts the D-09 invariants hold for arbitrary chains:

  * get_shard_at(latest)       == current      (no edits undone)
  * get_shard_at(extracted_at) == as-extracted (all edits undone, chain empty)
  * get_shard_at(t < extracted_at) is None
  * the stored shard is never mutated by the call

Matches Phase 2's minting-determinism rigor: ``@settings(max_examples=1000,
deadline=None)`` (tests/shards/test_minting_determinism.py L27).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from folio_insights.revision import InMemoryShardStore, get_field, get_shard_at
from folio_insights.shards import SimpleAssertionShard
from tests.shards.conftest import _content_edit, _sample_shard

pytestmark = pytest.mark.shards

_EXTRACTED_AT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
_MUTABLE_FIELDS = ["sense", "reference", "triple.object", "confidence"]


def _new_value(field: str, i: int) -> Any:
    if field == "confidence":
        # Keep within [0, 1]; deterministic per edit index.
        return round((i % 100) / 100.0, 2)
    if field == "triple.object":
        return f"object-{i}"
    if field == "sense":
        return f"sense-{i}"
    return f"urn:folio:concept/ref-{i}"


def _set(shard: SimpleAssertionShard, field: str, value: Any) -> None:
    if "." in field:
        parent, leaf = field.split(".", 1)
        setattr(getattr(shard, parent), leaf, value)
    else:
        setattr(shard, field, value)


def _build_history(field_seq: list[str]) -> tuple[str, InMemoryShardStore, dict[str, Any]]:
    """Build a shard + a monotonic edit chain from a random field sequence.

    Returns (shard_iri, store, as_extracted_state). Timestamps are strictly
    increasing (one day apart) so append order == chronological order, the
    invariant the forward-only validator guarantees. The store is populated
    synchronously (``InMemoryShardStore`` is a plain dict under the hood) so the
    builder stays loop-agnostic — the Hypothesis test owns the single event loop.
    """
    shard = _sample_shard(
        SimpleAssertionShard,
        extracted_at=_EXTRACTED_AT,
        sense="sense-init",
        reference="urn:folio:concept/ref-init",
        confidence=0.50,
    )
    as_extracted = {
        "sense": "sense-init",
        "reference": "urn:folio:concept/ref-init",
        "triple.object": "o",
        "confidence": 0.50,
    }
    for i, field in enumerate(field_seq, start=1):
        edited_at = _EXTRACTED_AT + timedelta(days=i)
        old_value = get_field(shard, field)
        new_value = _new_value(field, i)
        shard.content_edits.append(_content_edit(field, old_value, new_value, edited_at))
        _set(shard, field, new_value)

    store = InMemoryShardStore()
    store._d[shard.shard_iri] = shard  # sync populate (loop-agnostic builder)
    return shard.shard_iri, store, as_extracted


@settings(max_examples=1000, deadline=None)
@given(
    field_seq=st.lists(
        st.sampled_from(_MUTABLE_FIELDS), min_size=0, max_size=12
    )
)
def test_reverse_replay_invariants(field_seq: list[str]) -> None:
    """For an arbitrary monotonic edit chain, the D-09 invariants hold.

    The test function is sync (Hypothesis ``@given`` requires it) and owns a
    single fresh event loop for the async ``get_shard_at`` / ``store.get`` calls.
    """

    async def _run() -> None:
        shard_iri, store, as_extracted = _build_history(field_seq)
        current = await store.get(shard_iri)
        n = len(field_seq)

        # latest == current
        if n > 0:
            latest_t = _EXTRACTED_AT + timedelta(days=n)
            at_latest = await get_shard_at(shard_iri, latest_t, store)
            assert at_latest is not None
            assert at_latest.model_dump() == current.model_dump()

        # extracted_at == as-extracted (all edits undone, chain emptied)
        at_extract = await get_shard_at(shard_iri, _EXTRACTED_AT, store)
        assert at_extract is not None
        for path, value in as_extracted.items():
            assert get_field(at_extract, path) == value
        assert at_extract.content_edits == []

        # t < extracted_at -> None
        before = _EXTRACTED_AT - timedelta(seconds=1)
        assert await get_shard_at(shard_iri, before, store) is None

        # stored shard never mutated
        snapshot = current.model_dump()
        after = (await store.get(shard_iri)).model_dump()
        assert snapshot == after

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()
