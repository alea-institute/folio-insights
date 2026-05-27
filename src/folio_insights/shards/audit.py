"""Phase 5 ContentEdit audit sub-model + sync add_edit wrapper (CONTEXT D-04, D-05, D-08).

Phase 2 (D-08) shipped the frozen ``ContentEdit`` record + ``add_edit()``
append-with-audit helper. Phase 5 enriches the record to the full PRD §6.4
shape and migrates the helper:

* D-04: the flat Phase-2 field key becomes dotted ``field_path`` (e.g.
  ``"triple.object"``, ``"sense"``) so re-parenting an editable ``triple.object``
  is auditable while the
  identity parts (``triple.subject``/``.predicate``) stay locked by the Plan 02
  ``IMMUTABLE_FIELD_PATHS`` gate.
* D-04: a required ``rationale`` records the governance/audit "why" on every edit.
* D-05: a ``signature`` slot reuses the existing ``AttestedSignature`` stub
  (``envelope.py``). Phase 5 ships an empty/unsigned placeholder; the real
  ed25519 / JCS signing lands in Phase 6 (DID Substrate), filled in by Plan 02's
  ``edit_shard_content`` write path without touching this record's shape.

Phase 5 ALSO delivers (in sibling files, NOT here — the dep-leak guard keeps
``shards/`` RDF-free):

* The authoritative forward-only/append-only ``@model_validator`` on
  ``ShardEnvelope`` (``envelope.py``) — rejects non-monotonic ``edited_at``
  (D-07.1 / D-08b). The immutability half (D-08a — no mutation/deletion of past
  entries) is carried structurally by ``ContentEdit`` ``frozen=True`` + the
  ``IMMUTABLE_FIELD_PATHS`` gate (a stateless validator cannot see deletions).
* The async store-backed ``edit_shard_content`` write path, reverse-replay
  ``get_shard_at``, and the pyshacl ``validate_content_edit_shape`` defense-in-depth
  shape — all in the new ``revision/`` package (Plan 02 / Plan 03), so the
  ``shards/`` package stays free of rdflib/pyshacl/pyoxigraph (D-07 boundary).

Phase 6 will:

* Fill ``sign_attestation`` with real ed25519 + JCS canonicalization (the
  ``signature`` slot here is the seam).

This module is pure-Pydantic + stdlib — no storage-layer or RDF libraries are
imported (``tests/shards/test_dep_leak_guard.py`` enforces this). Importing
``AttestedSignature`` from ``envelope.py`` is fine — it is pure Pydantic.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from folio_insights.shards.envelope import AttestedSignature, ShardEnvelope


class ContentEdit(BaseModel):
    """One audit entry in a Shard's ``content_edits`` chain (D-04, D-05, D-08).

    Audit records are frozen (``frozen=True`` + ``extra="forbid"``) — an
    individual entry can never be mutated in place, and the chain as a whole is
    append-only (the forward-only ``@model_validator`` on ``ShardEnvelope`` is
    the authoritative monotonicity gate; the ``IMMUTABLE_FIELD_PATHS`` gate
    blocks replacing/reordering the list).

    Fields (PRD §6.4 shape):

    * ``field_path`` — dotted path to the edited field (D-04). ``"sense"`` for a
      top-level field, ``"triple.object"`` for a nested submodel leaf.
    * ``old_value`` / ``new_value`` — the values before/after the edit.
    * ``edited_at`` — tz-aware UTC timestamp; monotonicity across the chain is
      enforced on ``ShardEnvelope`` (D-07.1 / D-08b).
    * ``editor_did`` — who *claims* to have made the edit. NOT verified in
      Phase 5 (DID verification is Phase 6 — V4 partial, a documented gap).
    * ``rationale`` — required governance/audit "why" (D-04, no default).
    * ``signature`` — an ``AttestedSignature`` slot (D-05). Phase 5 ships an
      empty/unsigned stub (``signature=""``); Phase 6 fills real ed25519.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_path: str
    old_value: Any
    new_value: Any
    edited_at: datetime
    editor_did: str
    rationale: str
    signature: AttestedSignature


def add_edit(
    shard: ShardEnvelope,
    field_path: str,
    new_value: Any,
    editor_did: str,
    rationale: str,
) -> None:
    """Append a ContentEdit audit record AND assign the new value in place.

    A thin SYNC convenience wrapper (RESEARCH Open Question 2) over the proven
    capture -> append -> assign sequence. The async, store-backed full path with
    the ``IMMUTABLE_FIELD_PATHS`` gate, real content hashing, and post-edit
    re-validation is ``revision.edit_shard_content`` (Plan 02). ``add_edit``
    preserves the Phase 2 ``test_audit_log.py`` semantics on the migrated
    (``field_path`` + required ``rationale``/``signature``) shape.

    Behavior:

    1. Capture ``old_value`` via ``getattr(shard, field_path)`` BEFORE assignment
       (the load-bearing capture-before-assign order — D-04 migration preserves
       ``test_add_edit_captures_old_value_before_assignment``).
    2. Construct ``ContentEdit(field_path, old_value, new_value,
       edited_at=now(UTC), editor_did, rationale, signature=<stub>)`` where the
       signature is an empty/unsigned ``AttestedSignature`` placeholder
       (``action="content_edit"``, ``signature=""`` — D-05; real signing is the
       Plan 02 / Phase 6 seam).
    3. Append to ``shard.content_edits``.
    4. ``setattr(shard, field_path, new_value)`` — raises ``ValidationError`` with
       ``type="frozen_field"`` if ``field_path`` is one of the 6 D-07 frozen
       identity fields.

    Note: ``add_edit`` is a flat-attribute helper (top-level fields only). Dotted
    nested paths like ``triple.object`` are the ``revision.set_field`` /
    ``edit_shard_content`` path (Plan 02).
    """
    old_value = getattr(shard, field_path)
    shard.content_edits.append(
        ContentEdit(
            field_path=field_path,
            old_value=old_value,
            new_value=new_value,
            edited_at=datetime.now(UTC),
            editor_did=editor_did,
            rationale=rationale,
            signature=AttestedSignature(
                did=editor_did,
                action="content_edit",
                over_content_hash="",
                signature="",
                signed_at=datetime.now(UTC),
            ),
        )
    )
    # WR-01: roll the append back if assignment fails, so a failed edit (e.g.
    # ``field_path`` is one of the 6 frozen identity fields → ValidationError)
    # leaves NO phantom ContentEdit in the chain. Without this, the audit log
    # would carry an entry describing an assignment that never happened.
    try:
        setattr(shard, field_path, new_value)
    except Exception:
        shard.content_edits.pop()
        raise


__all__ = ["ContentEdit", "add_edit"]


# Resolve ShardEnvelope.content_edits forward-ref from Plan 02-01's envelope.py.
# ShardEnvelope was declared with ``list["ContentEdit"] = Field(default_factory=list)``
# as a string forward-ref (to avoid a circular import at package load time).
# Now that ContentEdit exists in this module's namespace, Pydantic can rebuild
# the model and validate list items against the real class.
ShardEnvelope.model_rebuild()
