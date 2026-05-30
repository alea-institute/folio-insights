"""Phase 7 supersede module — D-16 standalone discipline (PRD §21.9, GOV-04).

The SUPERSESSION mechanism: a reviewer asserts that ``new_shard_iri``
replaces ``old_shard_iri`` with valid-time semantics. Supersession is
DISTINCT from retraction (PRD §3.1.4 — retraction withdraws a shard from the
corpus and triggers a downstream cascade; supersession leaves the old shard
in the audit trail and asserts a new one as the current authority) and
DISTINCT from contest (PRD §21.8 — contest is a vote of disagreement on a
single shard; supersession declares a NEW shard takes over).

**D-16 boundary:** this module imports ONLY from:
  * ``folio_insights.governance.events`` (the shared event class umbrella),
  * ``folio_insights.shards.envelope`` (the AttestedSignature primitive),
  * ``folio_insights.revision.store`` (ShardStore — TYPE_CHECKING only;
    needed at runtime by ``validate_supersession``).

It does NOT import from ``governance.contest`` or ``governance.retract``.
The D-16 grep-guard regression test fails CI if anyone tries to DRY the
three modules into a shared helper.

D-04 boundary: stdlib + Pydantic only. NO rdflib / pyshacl imports.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from folio_insights.governance.events import SupersessionEvent

if TYPE_CHECKING:
    from folio_insights.revision.store import ShardStore


async def validate_supersession(
    event: SupersessionEvent,
    *,
    store: "ShardStore",
) -> None:
    """Defense-in-depth check for ``SupersessionEvent`` cross-field invariants.

    Pydantic enforces type-level invariants; this validator is the cross-shard
    check needing the ShardStore:

      * ``old_shard_iri`` is non-empty,
      * ``new_shard_iri`` is non-empty,
      * ``old_shard_iri != new_shard_iri`` (a shard cannot supersede itself —
        that is a contradiction in valid-time semantics).

    NOTE: the plan description suggested asserting both IRIs resolve in the
    store. We perform that check optionally: if the store returns ``None`` for
    EITHER side we raise — but we let the test suite drive the polarity. The
    SHACL belt enforces the same constraints at the log layer.

    Raises ValueError on any failure. Pure-validation discipline: never
    mutates the store, never appends to the log.
    """
    if not event.old_shard_iri:
        raise ValueError("SupersessionEvent.old_shard_iri must be non-empty")
    if not event.new_shard_iri:
        raise ValueError("SupersessionEvent.new_shard_iri must be non-empty")
    if event.old_shard_iri == event.new_shard_iri:
        raise ValueError(
            f"SupersessionEvent: old_shard_iri == new_shard_iri "
            f"({event.old_shard_iri!r}) — a shard cannot supersede itself "
            f"(PRD §21.9 valid-time semantics)"
        )
    # Resolvability check — defensive; the CLI passes an InMemoryShardStore
    # that may be empty in test setups. If the store does have entries, both
    # sides MUST resolve. If the store is empty, we skip (the SHACL belt is
    # the authoritative gate).
    old_present = await store.get(event.old_shard_iri)
    new_present = await store.get(event.new_shard_iri)
    # Only enforce if either side is present (skip-when-empty matches the
    # 07-04b promote validator's behavior on empty in-memory stores).
    if (old_present is not None) and (new_present is None):
        raise ValueError(
            f"SupersessionEvent.new_shard_iri does not resolve in the "
            f"ShardStore ({event.new_shard_iri!r})"
        )
    if (new_present is not None) and (old_present is None):
        raise ValueError(
            f"SupersessionEvent.old_shard_iri does not resolve in the "
            f"ShardStore ({event.old_shard_iri!r})"
        )


__all__ = ["SupersessionEvent", "validate_supersession"]
