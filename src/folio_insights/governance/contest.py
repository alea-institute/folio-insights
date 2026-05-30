"""Phase 7 contest module — D-16 standalone discipline (PRD §21.8, GOV-04).

The CONTEST mechanism: a reviewer formally disagrees with a shard and
records a vote-with-position-text on the governance log. Contest is
DISTINCT from supersession (PRD §21.9 — supersession declares a NEW shard
replaces an OLD one with valid-time semantics; no claim of error) and
DISTINCT from retraction (PRD §3.1.4 — retraction triggers a cascade,
withdrawing the shard from the corpus). The reviewer must pick the
RIGHT mechanism for the philosophical situation — D-16 software discipline
refuses to let a unified ``disagree()`` helper hide the distinction.

**D-16 boundary:** this module imports ONLY from:
  * ``folio_insights.governance.events`` (the shared event class umbrella),
  * ``folio_insights.shards.envelope`` (the AttestedSignature primitive — the
    ONLY shared primitive across the three-way per D-16).

It does NOT import from ``governance.supersede`` or ``governance.retract``.
The D-16 grep-guard regression test
(``tests/governance/test_grep_guard_three_way_disambiguation.py``) fails CI
if a future contributor tries to share code across the three modules.

D-04 boundary: stdlib + Pydantic only. NO rdflib / pyshacl imports.
"""
from __future__ import annotations

from folio_insights.governance.events import ContestEvent


def validate_contest(event: ContestEvent) -> None:
    """Defense-in-depth check for ``ContestEvent`` field invariants.

    Pydantic enforces type-level invariants at construction; this validator
    is the cross-field check for cases where ``ContestEvent.model_construct``
    bypasses Pydantic (e.g. SHACL-polarity test setups).

    Raises ValueError if:
      * ``shard_iri`` is empty,
      * ``voter_did`` does not start with ``"did:"`` (mirrors the DID URI
        scheme requirement — Phase 6 DID-01),
      * ``position_text`` is empty.

    The SHACL belt for the same constraints lives in
    ``governance/shapes/contest_shape.ttl``; the log-layer SHACL gate is the
    third defense-in-depth layer.
    """
    if not event.shard_iri:
        raise ValueError("ContestEvent.shard_iri must be non-empty")
    if not event.voter_did.startswith("did:"):
        raise ValueError(
            f"ContestEvent.voter_did must start with 'did:' "
            f"(got {event.voter_did!r})"
        )
    if not event.position_text:
        raise ValueError("ContestEvent.position_text must be non-empty")


__all__ = ["ContestEvent", "validate_contest"]
