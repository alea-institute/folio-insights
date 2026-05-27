"""get_shard_at reverse-replay across a 10-edit fixture (exit criterion 3, D-09).

Asserts the D-09 reconstruction contract: latest == current, extracted_at ==
as-extracted, ``t < extracted_at`` → None, unknown IRI → None, exact-``t`` ties
are KEPT (strict ``>`` undo), correct intermediate state at every recorded
checkpoint, and — critically — the stored shard is NEVER mutated by the call
(Pitfall 3, ``model_copy(deep=True)`` isolation).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from folio_insights.revision import get_field, get_shard_at

pytestmark = pytest.mark.shards


def _assert_state(shard, expected: dict) -> None:
    """Assert every recorded field equals the historical-state expectation."""
    for path, value in expected.items():
        assert get_field(shard, path) == value, f"{path}: {get_field(shard, path)!r} != {value!r}"


async def test_latest_equals_current(ten_edit_history) -> None:
    """get_shard_at(latest_edit_time) == current stored shard (no edits undone)."""
    h = ten_edit_history
    current = await h.store.get(h.shard_iri)
    at_latest = await get_shard_at(h.shard_iri, h.edit_times[-1], h.store)
    assert at_latest is not None
    assert at_latest.model_dump() == current.model_dump()
    assert len(at_latest.content_edits) == 10


async def test_extracted_at_is_as_extracted(ten_edit_history) -> None:
    """get_shard_at(extracted_at) undoes ALL content edits (as-extracted, §21.7)."""
    h = ten_edit_history
    at_extract = await get_shard_at(h.shard_iri, h.extracted_at, h.store)
    assert at_extract is not None
    # All 10 edits undone -> original field values, chain trimmed to empty.
    _assert_state(at_extract, h.checkpoints[1].expected)  # checkpoints[1] is extracted_at
    assert at_extract.content_edits == []


async def test_before_extracted_at_is_none(ten_edit_history) -> None:
    """t strictly before extracted_at -> None (the shard didn't exist yet)."""
    h = ten_edit_history
    before = h.extracted_at - timedelta(days=1)
    assert await get_shard_at(h.shard_iri, before, h.store) is None


async def test_unknown_iri_is_none(ten_edit_history) -> None:
    """Unknown IRI -> None (the unambiguous D-09/A3 choice)."""
    h = ten_edit_history
    assert await get_shard_at("urn:folio:shard/notreal", h.edit_times[0], h.store) is None


async def test_exact_t_tie_keeps_edit(ten_edit_history) -> None:
    """An edit at exactly t is KEPT (strict > undo) — Pitfall 4 / D-09 ties."""
    h = ten_edit_history
    # checkpoints[2] is the exact-t tie on edit_times[4] (the 5th edit).
    cp = h.checkpoints[2]
    assert cp.t == h.edit_times[4]
    at_t = await get_shard_at(h.shard_iri, cp.t, h.store)
    assert at_t is not None
    _assert_state(at_t, cp.expected)
    # The 5th edit (edited_at == t) is included in the trimmed chain.
    assert len(at_t.content_edits) == 5
    assert at_t.content_edits[-1].edited_at == cp.t


async def test_all_checkpoints_exact(ten_edit_history) -> None:
    """get_shard_at(t_k) matches the independently-computed state at every t_k."""
    h = ten_edit_history
    for cp in h.checkpoints:
        recon = await get_shard_at(h.shard_iri, cp.t, h.store)
        assert recon is not None, cp.note
        _assert_state(recon, cp.expected)
        # Chain trimmed to edits with edited_at <= t.
        assert all(e.edited_at <= cp.t for e in recon.content_edits), cp.note


async def test_stored_shard_unmutated_after_call(ten_edit_history) -> None:
    """The stored shard is byte-identical (model_dump) before AND after the call."""
    h = ten_edit_history
    before = (await h.store.get(h.shard_iri)).model_dump()
    # Reconstruct at several points, including extracted_at (undoes everything).
    await get_shard_at(h.shard_iri, h.extracted_at, h.store)
    await get_shard_at(h.shard_iri, h.edit_times[3], h.store)
    await get_shard_at(h.shard_iri, h.edit_times[-1], h.store)
    after = (await h.store.get(h.shard_iri)).model_dump()
    assert before == after


async def test_reconstruction_is_repeatable(ten_edit_history) -> None:
    """Two reconstructions at the same t are identical (no hidden mutation)."""
    h = ten_edit_history
    t = h.edit_times[5]
    first = (await get_shard_at(h.shard_iri, t, h.store)).model_dump()
    second = (await get_shard_at(h.shard_iri, t, h.store)).model_dump()
    assert first == second


async def test_just_after_latest_equals_current(ten_edit_history) -> None:
    """A t strictly after the last edit still equals current (nothing to undo)."""
    h = ten_edit_history
    current = await h.store.get(h.shard_iri)
    later = h.edit_times[-1] + timedelta(days=30)
    at_later = await get_shard_at(h.shard_iri, later, h.store)
    assert at_later is not None
    assert at_later.model_dump() == current.model_dump()
