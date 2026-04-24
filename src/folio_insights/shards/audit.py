"""Phase 2 ContentEdit audit sub-model + minimal add_edit helper (CONTEXT D-08)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from folio_insights.shards.envelope import ShardEnvelope

# D-08 design:
#
# * ContentEdit is frozen end-to-end (audit records are immutable once written).
# * add_edit() appends a ContentEdit to shard.content_edits AND assigns
#   setattr(shard, field_name, new_value) — this is the "mutable-with-audit"
#   pattern for non-identity fields.
# * Attempted assignment on a frozen field (the 6 identity fields per D-07)
#   raises pydantic.ValidationError with type="frozen_field" — which is
#   the correct behavior: identity fields never change, edits must create a
#   new shard via the supersedes-chain.
#
# Phase 5 will:
#
# * Add @model_validator forward-only gate (edited_at >= shard.transaction_time).
# * Wire the SHACL shape for the append-only invariant.
# * Add validate_content_edit_shape() defense-in-depth (mirrors distinguo).
# * Harden add_edit to transactional semantics (rollback the append on setattr
#   failure).
#
# Phase 6 will:
#
# * Add DID signature capture (AttestedSignature over the ContentEdit's
#   canonical hash).
#
# Phase 2 ships the shape + helper only. This module is pure-Pydantic + stdlib
# — no storage-layer libraries are pulled in at Phase 2 (RDF mapping + SHACL
# gates are Phase 11 / Phase 13 scope).


class ContentEdit(BaseModel):
    """One audit entry in a Shard's ``content_edits`` chain (D-08).

    Audit records themselves are frozen (``model_config`` frozen=True +
    extra=forbid) — the chain as a whole is append-only (Phase 2 ships the
    append-only helper; Phase 5 adds the forward-only SHACL gate).
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_name: str
    old_value: Any
    new_value: Any
    edited_at: datetime
    editor_did: str


def add_edit(shard: ShardEnvelope, field_name: str, new_value: Any, editor_did: str) -> None:
    """Append a ContentEdit audit record AND assign the new value in place.

    Behavior:

    1. Capture ``old_value`` via ``getattr(shard, field_name)`` BEFORE assignment.
    2. Construct ``ContentEdit(field_name, old_value, new_value,
       edited_at=now(UTC), editor_did)``.
    3. Append to ``shard.content_edits``.
    4. ``setattr(shard, field_name, new_value)`` — raises ValidationError with
       ``type="frozen_field"`` if ``field_name`` is in the D-07 frozen set.

    Phase 2 minimal behavior. Phase 5 will:

    * Enforce ``edited_at`` monotonicity (no edits-to-past).
    * Validate ``field_name`` is a known envelope field (not free-form string).
    * Run SHACL shape check before committing the edit.
    * Make the append+setattr sequence transactional (rollback the append if
      setattr raises on a frozen field).
    """
    old_value = getattr(shard, field_name)
    shard.content_edits.append(
        ContentEdit(
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            edited_at=datetime.now(UTC),
            editor_did=editor_did,
        )
    )
    setattr(shard, field_name, new_value)


__all__ = ["ContentEdit", "add_edit"]


# Resolve ShardEnvelope.content_edits forward-ref from Plan 02-01's envelope.py.
# ShardEnvelope was declared with ``list["ContentEdit"] = Field(default_factory=list)``
# as a string forward-ref (to avoid a circular import at package load time).
# Now that ContentEdit exists in this module's namespace, Pydantic can rebuild
# the model and validate list items against the real class.
ShardEnvelope.model_rebuild()
