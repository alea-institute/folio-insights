"""Temporary RED test for Task 1 (ContentEdit enrichment, D-04/D-05).

Deleted after GREEN — the durable coverage lives in the migrated
test_audit_log.py + test_content_edit_audit_append_only.py.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from folio_insights.shards import AttestedSignature, ContentEdit, add_edit
from folio_insights.shards.subtypes import SimpleAssertionShard

from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.shards


def test_content_edit_carries_field_path_rationale_signature() -> None:
    edit = ContentEdit(
        field_path="sense",
        old_value="o",
        new_value="n",
        edited_at=datetime.now(UTC),
        editor_did="did:key:zX",
        rationale="why",
        signature=AttestedSignature(),
    )
    assert edit.field_path == "sense"
    assert edit.rationale == "why"


def test_content_edit_rationale_required() -> None:
    with pytest.raises(ValidationError):
        ContentEdit(
            field_path="sense",
            old_value="o",
            new_value="n",
            edited_at=datetime.now(UTC),
            editor_did="did:key:zX",
            signature=AttestedSignature(),
        )


def test_add_edit_takes_rationale_and_sets_field_path() -> None:
    shard = _sample_shard(SimpleAssertionShard, sense="orig")
    add_edit(shard, "sense", "new", "did:key:zX", rationale="r")
    assert len(shard.content_edits) == 1
    edit = shard.content_edits[0]
    assert edit.field_path == "sense"
    assert edit.old_value == "orig"
    assert shard.sense == "new"
