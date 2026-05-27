"""ContentEdit audit-log tests (CONTEXT D-04, D-05, D-08).

Covers ContentEdit frozen round-trip + extra-forbid regression + add_edit
append/capture-order semantics + D-07 × D-08 interaction (add_edit on a
frozen identity field raises ValidationError) + the forward-ref JSON
round-trip regression that guards Plan 02-02's ShardEnvelope.model_rebuild()
call (content_edits[0] must rehydrate as a real ContentEdit instance, not a
plain dict).

Phase 5 migration (D-04/D-05): ContentEdit gained dotted ``field_path``
(renamed from the flat Phase-2 key), a required ``rationale``, and a
``signature`` (AttestedSignature) slot. Every construction site below carries
the enriched shape; ``add_edit`` now takes ``rationale`` as its 5th argument.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from folio_insights.shards import (
    AttestedSignature,
    ContentEdit,
    SimpleAssertionShard,
    add_edit,
)

from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.shards


def test_content_edit_round_trip() -> None:
    """ContentEdit round-trips via model_dump_json / model_validate_json."""
    edit = ContentEdit(
        field_path="sense",
        old_value="old",
        new_value="new",
        edited_at=datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC),
        editor_did="did:key:zTest",
        rationale="clarify the intended sense",
        signature=AttestedSignature(),
    )
    rehydrated = ContentEdit.model_validate_json(edit.model_dump_json())
    assert rehydrated == edit


def test_content_edit_is_frozen() -> None:
    """D-08: ContentEdit model_config frozen=True — assignment raises."""
    edit = ContentEdit(
        field_path="sense",
        old_value="o",
        new_value="n",
        edited_at=datetime.now(UTC),
        editor_did="did:key:zTest",
        rationale="why",
        signature=AttestedSignature(),
    )
    with pytest.raises(ValidationError):
        edit.field_path = "elaborates"


def test_content_edit_rejects_extra_fields() -> None:
    """D-08: extra='forbid' on ContentEdit."""
    with pytest.raises(ValidationError):
        ContentEdit(
            field_path="sense",
            old_value="o",
            new_value="n",
            edited_at=datetime.now(UTC),
            editor_did="did:key:zTest",
            rationale="why",
            signature=AttestedSignature(),
            bogus_field="x",  # extra='forbid' rejects this
        )


def test_content_edit_requires_rationale() -> None:
    """D-04: rationale is required (no default) — omitting it raises."""
    with pytest.raises(ValidationError):
        ContentEdit(
            field_path="sense",
            old_value="o",
            new_value="n",
            edited_at=datetime.now(UTC),
            editor_did="did:key:zTest",
            signature=AttestedSignature(),
        )


def test_add_edit_appends_content_edit_record() -> None:
    """add_edit appends a ContentEdit with captured old_value + new values."""
    shard = _sample_shard(SimpleAssertionShard, sense="original_sense")
    assert shard.content_edits == []

    add_edit(shard, "sense", "revised_sense", "did:key:zEditor", "fix typo")

    assert len(shard.content_edits) == 1
    edit = shard.content_edits[0]
    assert edit.field_path == "sense"
    assert edit.old_value == "original_sense"
    assert edit.new_value == "revised_sense"
    assert edit.editor_did == "did:key:zEditor"
    assert edit.rationale == "fix typo"
    # D-05: the signature is an unsigned stub (signature=="") — clearly NOT verified.
    assert edit.signature.signature == ""
    assert edit.signature.action == "content_edit"
    assert edit.edited_at.tzinfo is not None
    assert edit.edited_at.utcoffset().total_seconds() == 0

    # Sanity: the shard field is updated too.
    assert shard.sense == "revised_sense"


def test_add_edit_captures_old_value_before_assignment() -> None:
    """Order-of-ops: old_value is captured BEFORE setattr."""
    shard = _sample_shard(SimpleAssertionShard, sense="first", reference="urn:old")
    add_edit(shard, "sense", "second", "did:key:zX", "edit 1")
    add_edit(shard, "sense", "third", "did:key:zX", "edit 2")
    assert [e.old_value for e in shard.content_edits] == ["first", "second"]
    assert [e.new_value for e in shard.content_edits] == ["second", "third"]
    assert shard.sense == "third"


def test_add_edit_on_frozen_field_raises() -> None:
    """D-07 × D-08: add_edit on a frozen identity field raises ValidationError."""
    shard = _sample_shard(SimpleAssertionShard)
    with pytest.raises(ValidationError, match="frozen"):
        add_edit(
            shard,
            "shard_iri",
            "urn:folio:shard/deadbeef00000000",
            "did:key:zX",
            "attempt to mutate identity",
        )


def test_content_edits_survive_json_round_trip() -> None:
    """ShardEnvelope.content_edits list of ContentEdit parses back correctly.

    Critical regression for Plan 02-02's ShardEnvelope.model_rebuild() call:
    after JSON dump/reparse, content_edits[0] must be a ContentEdit instance
    (not a dict or string). If the rebuild didn't happen, pydantic falls
    back to Any and content_edits[0] would be a dict.
    """
    shard = _sample_shard(SimpleAssertionShard, sense="a")
    add_edit(shard, "sense", "b", "did:key:zX", "round-trip edit")
    rehydrated = SimpleAssertionShard.model_validate_json(shard.model_dump_json())
    assert len(rehydrated.content_edits) == 1
    assert isinstance(rehydrated.content_edits[0], ContentEdit)
    assert rehydrated.content_edits[0].field_path == "sense"
