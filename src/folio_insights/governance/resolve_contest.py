"""Phase 7 contest-resolution module — D-16 standalone discipline (PRD §3.1.3, GOV-05).

The CONTEST RESOLUTION mechanism: governance resolves a previously-contested
shard via EXACTLY ONE of three paths:

  * ``arbiter``   — an arbiter role signs a decision (PRD §3.1.3 row arbiter).
  * ``distinguo`` — the dispute is resolved by sense-forking (the contested
    interpretations are formally distinguished; cf. polysemy Phase 1).
  * ``aporetic``  — the dispute is acknowledged as UNRESOLVABLE on the present
    record; the shard remains contested-but-aporetic (PRD §3.1.3 acceptance
    of irreducible difficulty; cf. classical aporia).

**GOV-05 explicit-rejection lock:** NO majority-vote resolution path exists.
The Literal in ``ContestResolutionEvent.resolution_path`` has EXACTLY 3
values. The SHACL ``fi:ContestResolutionShape`` has ``sh:in`` with EXACTLY 3
values. Adding a 4th value requires an ADR.

**D-16 boundary:** this module imports ONLY from:
  * ``folio_insights.governance.events`` (the shared event class umbrella),
  * ``folio_insights.shards.envelope`` (the AttestedSignature primitive),
  * ``folio_insights.governance.log`` (GovernanceLog — TYPE_CHECKING only;
    needed at runtime by ``validate_contest_resolution`` to look up prior
    contests).

It does NOT import from ``governance.contest`` or ``governance.supersede``
or ``governance.retract``. The D-16 grep-guard regression test fails CI if
anyone DRY's the three modules.

D-04 boundary: stdlib + Pydantic only. NO rdflib / pyshacl imports.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from folio_insights.governance.events import (
    ContestResolutionEvent,
    ContestResolutionPath,
)

if TYPE_CHECKING:
    from folio_insights.governance.log import GovernanceLog


# GOV-05 explicit-rejection lock — frozen set of the 3 allowed paths.
_GOV_05_PATHS: frozenset[str] = frozenset(get_args(ContestResolutionPath))


async def validate_contest_resolution(
    event: ContestResolutionEvent,
    *,
    log: "GovernanceLog",
) -> None:
    """Defense-in-depth check for ``ContestResolutionEvent`` invariants.

    Pydantic enforces the resolution_path Literal at construction; this
    validator additionally enforces:

      * The cited shard has a prior ContestEvent in the log (a resolution
        cannot precede a contest — that is a sequence error).
      * The resolution_path is one of the GOV-05 3-value set (defense-in-depth
        — Pydantic enforces but this catches ``model_construct`` bypasses).

    Raises ValueError on failure. Pure-validation discipline: never mutates
    the log, never appends.

    WR-02 contract: this validator MUST NOT read ``event.signature`` or
    any of its sub-fields. The CLI flow runs this validator BEFORE the
    real signature is computed; the event passed in carries a placeholder
    signature whose ``over_content_hash`` is the sentinel ``"0" * 64``.
    """
    if event.resolution_path not in _GOV_05_PATHS:
        raise ValueError(
            f"GOV-05 violation: resolution_path={event.resolution_path!r} is "
            f"not one of {sorted(_GOV_05_PATHS)}. Adding a 4th value requires "
            f"an ADR (the Literal + SHACL sh:in + this check all lock the set)."
        )
    # The cited shard must have been contested in this corpus.
    from folio_insights.governance.events import ContestEvent

    found_contest = False
    async for prior in log.iter_events(event.corpus):
        if isinstance(prior, ContestEvent) and prior.shard_iri == event.shard_iri:
            found_contest = True
            break
    if not found_contest:
        raise ValueError(
            f"ContestResolutionEvent.shard_iri {event.shard_iri!r}: no prior "
            f"ContestEvent for this shard in corpus {event.corpus!r} — a "
            f"resolution cannot precede a contest."
        )


__all__ = [
    "ContestResolutionEvent",
    "ContestResolutionPath",
    "validate_contest_resolution",
]
