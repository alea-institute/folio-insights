"""Phase 5 revision/ shared fixtures (CONTEXT D-02, D-09; 05-PATTERNS L168-182).

Provides:
  * ``store`` — a fresh ``InMemoryShardStore`` per test (D-02 in-memory seam).
  * ``sample_shard`` — a ``SimpleAssertionShard`` built via the existing
    ``tests/shards/conftest.py::_sample_shard`` builder (reused, not re-derived).
  * ``stored_shard`` — ``sample_shard`` already ``put`` into ``store`` (async),
    plus its IRI, for round-trip edit-path tests.
  * ``ten_edit_history`` — a 10-edit ``SimpleAssertionShard`` with strictly
    increasing monthly ``edited_at`` on mutable fields, the store it lives in,
    and a recorded list of ``(t_k, expected_snapshot)`` checkpoints + an
    exact-``t`` boundary tie (Task 2 — get_shard_at exit criterion 3).

The ``tests/shards`` builders (``_sample_shard``, ``_content_edit``) are imported
directly so the enriched ``ContentEdit`` ceremony (rationale/signature) is not
re-derived here (05-PATTERNS "reuse the existing builder").
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio

from folio_insights.revision import InMemoryShardStore, get_field
from folio_insights.shards import ShardEnvelope, SimpleAssertionShard

# Reuse the Phase 2/3 shards builders rather than re-deriving the 30-field
# envelope or the enriched-ContentEdit signature/rationale ceremony.
from tests.shards.conftest import _content_edit, _sample_shard


@pytest.fixture
def store() -> InMemoryShardStore:
    """A fresh in-memory store per test (D-02)."""
    return InMemoryShardStore()


@pytest.fixture
def sample_shard() -> SimpleAssertionShard:
    """A valid SimpleAssertionShard with empty content_edits (reuses _sample_shard)."""
    return _sample_shard(SimpleAssertionShard)


@pytest_asyncio.fixture
async def stored_shard(
    store: InMemoryShardStore, sample_shard: SimpleAssertionShard
) -> tuple[str, SimpleAssertionShard]:
    """``sample_shard`` put into ``store``; returns (shard_iri, shard)."""
    await store.put(sample_shard.shard_iri, sample_shard)
    return sample_shard.shard_iri, sample_shard


# ── 10-edit history fixture (Task 2 — exit criterion 3) ──────────────────────

# The 4 mutable fields the fixture edits, cycled across the 10 edits. All are
# declared-mutable on ShardEnvelope (not in IMMUTABLE_FIELD_PATHS): "sense" and
# "reference" are top-level strings, "triple.object" is a mutable submodel leaf
# (re-parenting, D-04), "confidence" is a float in [0, 1].
_MUTABLE_FIELDS = ["sense", "reference", "triple.object", "confidence"]


@dataclass
class Checkpoint:
    """A historical snapshot: ``get_shard_at(iri, t)`` must equal these field values."""

    t: datetime
    expected: dict[str, Any]  # field_path -> expected value at time t
    note: str = ""


@dataclass
class TenEditHistory:
    """The 10-edit fixture bundle Task 2's get_shard_at test consumes."""

    shard_iri: str
    store: InMemoryShardStore
    extracted_at: datetime
    edit_times: list[datetime]
    checkpoints: list[Checkpoint]


def _month(n: int) -> datetime:
    """A strictly-increasing UTC timestamp: the (n)th month after extraction."""
    # extracted_at is 2026-01-01; edits land on the 1st of months 2..11.
    month = 1 + n  # n in 1..10 -> months 2..11
    return datetime(2026, month, 1, 12, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def ten_edit_history(store: InMemoryShardStore) -> TenEditHistory:
    """Build a SimpleAssertionShard + 10 strictly-monotonic edits, recording the
    intermediate state at chosen ``t_k`` for exact ``get_shard_at`` assertions.

    Construction order (each edit captures old_value BEFORE the new value is set,
    matching ``edit_shard_content``), so the stored shard's ``content_edits`` chain
    is genuine reverse-replay input. The expected snapshots are computed forward
    here (the "known intermediate states") so the test asserts an independently
    derived truth, not the implementation's own output.
    """
    extracted_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    shard = _sample_shard(
        SimpleAssertionShard,
        extracted_at=extracted_at,
        sense="sense-v0",
        reference="urn:folio:concept/ref-v0",
        confidence=0.50,
    )
    # triple.object starts at "o" (the _sample_shard default).

    # Forward-apply 10 edits, recording each edit and the running field state.
    edit_times: list[datetime] = []
    running: dict[str, Any] = {
        "sense": "sense-v0",
        "reference": "urn:folio:concept/ref-v0",
        "triple.object": "o",
        "confidence": 0.50,
    }
    # state_after[k] = field-state dict AFTER the k-th edit (k in 1..10);
    # state_after[0] = as-extracted state.
    state_after: list[dict[str, Any]] = [dict(running)]

    for i in range(1, 11):
        field = _MUTABLE_FIELDS[(i - 1) % len(_MUTABLE_FIELDS)]
        edited_at = _month(i)
        old_value = get_field(shard, field)
        if field == "confidence":
            new_value: Any = round(0.50 + i * 0.04, 2)  # 0.54, 0.58, ... <= 1.0
        elif field == "triple.object":
            new_value = f"object-v{i}"
        elif field == "sense":
            new_value = f"sense-v{i}"
        else:  # reference
            new_value = f"urn:folio:concept/ref-v{i}"

        shard.content_edits.append(
            _content_edit(field, old_value, new_value, edited_at)
        )
        # Apply the new value via dotted set so triple.object nests correctly.
        if "." in field:
            parent, leaf = field.split(".", 1)
            setattr(getattr(shard, parent), leaf, new_value)
        else:
            setattr(shard, field, new_value)

        edit_times.append(edited_at)
        running[field] = new_value
        state_after.append(dict(running))

    await store.put(shard.shard_iri, shard)

    # Checkpoints the get_shard_at test asserts exactly:
    checkpoints = [
        Checkpoint(t=edit_times[-1], expected=state_after[10], note="latest == current"),
        Checkpoint(t=extracted_at, expected=state_after[0], note="extracted_at == as-extracted"),
        # Exactly on the 5th edit's timestamp: that edit IS included (strict >),
        # so the state equals state_after[5].
        Checkpoint(t=edit_times[4], expected=state_after[5], note="exact-t tie keeps the edit"),
        # Just before the 6th edit (but after the 5th): state_after[5].
        Checkpoint(
            t=edit_times[5].replace(day=15) if edit_times[5].day == 1 else edit_times[5],
            expected=state_after[5],
            note="between edit 5 and 6",
        ),
        # Between edit 7 and edit 8.
        Checkpoint(
            t=datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC),
            expected=state_after[7],
            note="mid-window (after edit 7, before edit 8)",
        ),
    ]

    return TenEditHistory(
        shard_iri=shard.shard_iri,
        store=store,
        extracted_at=extracted_at,
        edit_times=edit_times,
        checkpoints=checkpoints,
    )
