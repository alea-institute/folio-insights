"""Exit criterion 1 (REQ SHARD-09): ContentEdit chain is append-only + forward-only.

Asserts the two halves of D-08 against the migrated (D-04/D-05) ContentEdit shape
and the authoritative forward-only ``@model_validator`` on ShardEnvelope (D-07.1):

1. Append-then-revalidate: a new monotonic edit appends and the shard re-validates.
2. Immutability (D-08a): an existing ContentEdit entry is frozen — in-place
   mutation raises ValidationError.
3. Forward-only (D-08b): a back-dated append is rejected by ShardEnvelope
   re-validation (model_validate over the dumped state).
4. Append-only ordering: replacing content_edits with a non-monotonic (reordered)
   list is rejected on re-validation.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from folio_insights.shards import SimpleAssertionShard, add_edit

from tests.shards.conftest import _content_edit, _sample_shard

pytestmark = pytest.mark.shards


_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_append_then_revalidate_succeeds() -> None:
    """A new monotonic edit appends and the shard re-validates clean."""
    shard = _sample_shard(SimpleAssertionShard, sense="v0")
    add_edit(shard, "sense", "v1", "did:key:zX", "first edit")
    add_edit(shard, "sense", "v2", "did:key:zX", "second edit")

    # Re-validation over the dumped state succeeds (monotonic chain).
    revalidated = SimpleAssertionShard.model_validate(shard.model_dump())
    assert len(revalidated.content_edits) == 2
    assert [e.field_path for e in revalidated.content_edits] == ["sense", "sense"]


def test_existing_entry_is_immutable() -> None:
    """D-08a: an existing ContentEdit entry is frozen — mutation raises."""
    shard = _sample_shard(SimpleAssertionShard, sense="v0")
    add_edit(shard, "sense", "v1", "did:key:zX", "edit")
    entry = shard.content_edits[0]
    with pytest.raises(ValidationError):
        entry.new_value = "tampered"
    with pytest.raises(ValidationError):
        entry.edited_at = _T0 - timedelta(days=365)


def test_back_dated_append_rejected_on_revalidation() -> None:
    """D-08b: appending an edit earlier than the prior edit is rejected."""
    edits = [
        _content_edit("sense", "v0", "v1", _T0 + timedelta(days=2)),
        # back-dated: edited_at precedes its predecessor
        _content_edit("reference", "r0", "r1", _T0),
    ]
    shard = _sample_shard(SimpleAssertionShard)
    # Bypass the construction-time validator by mutating the list in place,
    # then re-validate the dumped snapshot (the integrity gate).
    shard.content_edits.extend(edits)
    with pytest.raises(ValueError, match="forward-only"):
        SimpleAssertionShard.model_validate(shard.model_dump())


def test_reordered_chain_rejected_on_revalidation() -> None:
    """Append-only ordering: a non-monotonic (reordered) list is rejected."""
    e_early = _content_edit("sense", "v0", "v1", _T0)
    e_late = _content_edit("reference", "r0", "r1", _T0 + timedelta(days=5))
    shard = _sample_shard(SimpleAssertionShard)
    # Construct in correct (monotonic) order first — this validates.
    shard.content_edits.extend([e_early, e_late])
    SimpleAssertionShard.model_validate(shard.model_dump())  # sanity: ordered is OK

    # Now reorder to a non-monotonic sequence and re-validate — rejected.
    shard.content_edits[:] = [e_late, e_early]
    with pytest.raises(ValueError, match="D-08b"):
        SimpleAssertionShard.model_validate(shard.model_dump())
