"""Temporary RED test for Task 2 (forward-only @model_validator, D-07.1/D-08b).

Deleted after GREEN — durable coverage lives in
test_content_edit_audit_append_only.py.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from folio_insights.shards import AttestedSignature, ContentEdit
from folio_insights.shards.subtypes import SimpleAssertionShard

from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.shards


def _edit(field_path: str, edited_at: datetime) -> ContentEdit:
    return ContentEdit(
        field_path=field_path,
        old_value="o",
        new_value="n",
        edited_at=edited_at,
        editor_did="did:key:zX",
        rationale="r",
        signature=AttestedSignature(),
    )


def test_monotonic_chain_validates() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    edits = [_edit("sense", base + timedelta(days=i)) for i in range(3)]
    shard = _sample_shard(SimpleAssertionShard, content_edits=edits)
    assert len(shard.content_edits) == 3


def test_equal_timestamps_allowed() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    edits = [_edit("sense", base), _edit("reference", base)]
    shard = _sample_shard(SimpleAssertionShard, content_edits=edits)
    assert len(shard.content_edits) == 2


def test_back_dated_chain_rejected() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    edits = [_edit("sense", base + timedelta(days=2)), _edit("reference", base)]
    with pytest.raises(ValueError, match="D-08b"):
        _sample_shard(SimpleAssertionShard, content_edits=edits)


def test_empty_and_single_validate() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    s0 = _sample_shard(SimpleAssertionShard, content_edits=[])
    s1 = _sample_shard(SimpleAssertionShard, content_edits=[_edit("sense", base)])
    assert s0.content_edits == []
    assert len(s1.content_edits) == 1
