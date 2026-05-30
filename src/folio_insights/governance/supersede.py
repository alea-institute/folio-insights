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


class ShardNotFound(ValueError):
    """Raised when a SupersessionEvent references shard IRIs that the
    ShardStore cannot resolve (WR-04 closure).

    Subclasses ValueError so existing handlers catching ValueError
    (e.g. the CLI's ``except ValueError as exc`` branch) still
    trigger; new callers can catch the specific type for richer
    diagnostics.
    """


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

    WR-02 contract: this validator MUST NOT read ``event.signature`` or
    any of its sub-fields. The CLI flow runs validators BEFORE the real
    signature is computed; the event passed in carries a placeholder
    signature whose ``over_content_hash`` is the sentinel ``"0" * 64``.
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
    # that may be empty in test setups. If the store has entries we require
    # both sides to resolve.
    #
    # WR-04 fix: previously, when BOTH sides were absent (an empty store),
    # this validator silently passed — leaving the false-success path open
    # (the CLI would proceed to sign + append a SupersessionEvent referencing
    # two unresolvable IRIs). Now we refuse with ShardNotFound regardless of
    # the store's emptiness state: a supersession claim that neither side
    # exists for is unprovable in EVERY state of the world, not just non-
    # empty stores. The SHACL belt at the log layer remains the third
    # defense-in-depth layer, but this is now a hard refusal at the library
    # validator (matches the discipline validate_promotion uses with its
    # D-20 cite-resolvable guard).
    old_present = await store.get(event.old_shard_iri)
    new_present = await store.get(event.new_shard_iri)
    if (old_present is None) and (new_present is None):
        raise ShardNotFound(
            f"SupersessionEvent: neither old_shard_iri "
            f"({event.old_shard_iri!r}) nor new_shard_iri "
            f"({event.new_shard_iri!r}) resolve in the ShardStore — a "
            f"supersession claim is unprovable when neither side exists. "
            f"Did you mean to seed the store first?"
        )
    if (old_present is not None) and (new_present is None):
        raise ShardNotFound(
            f"SupersessionEvent.new_shard_iri does not resolve in the "
            f"ShardStore ({event.new_shard_iri!r})"
        )
    if (new_present is not None) and (old_present is None):
        raise ShardNotFound(
            f"SupersessionEvent.old_shard_iri does not resolve in the "
            f"ShardStore ({event.old_shard_iri!r})"
        )


__all__ = ["ShardNotFound", "SupersessionEvent", "validate_supersession"]
