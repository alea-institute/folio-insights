"""Phase 7 active-roles query — windowed by signed_at <= asof (D-13 / Pitfall F2).

Walks the governance log and returns the active role map at a point in time.
The windowing discipline is the structural analog of
``identity/cache.py::DidDocCache.get((did, signed_at))`` — every governance
query that depends on "what roles held at signing time" goes through this
function rather than reaching into the log directly, which closes the F2
pitfall for role queries (key rotation does NOT retroactively invalidate
a role assertion).

D-13 active-roles semantics:

  * Walk all events in the corpus's log in position order.
  * For each event with ``signature.signed_at <= asof``:
      - If RoleAssertionEvent: add (subject_did -> role) to the active set.
      - If RoleRevocationEvent: remove (subject_did -> revoked_role).
  * Events with ``signed_at > asof`` are NOT YET visible and are ignored.
  * Re-assertion after revocation is supported via set semantics: revoke
    at t1 followed by re-assert at t2 means active at t2.

D-04 boundary: stdlib + Pydantic only. No rdflib / pyshacl / aiosqlite imports
here. The dep-leak guard at ``tests/governance/test_dep_leak_guard.py``
enforces this on the full ``governance/`` tree (except ``shape_validation.py``).
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from folio_insights.governance.events import (
    RoleAssertionEvent,
    RoleRevocationEvent,
)

# Re-export for convenience (callers can write
# ``from folio_insights.governance.roles import RoleAssertionEvent``).
__all__ = [
    "RoleAssertionEvent",
    "RoleRevocationEvent",
    "active_roles_at",
    "active_roles_for_did",
]


if TYPE_CHECKING:
    from folio_insights.governance.log import GovernanceLog


async def active_roles_at(
    corpus: str,
    asof: datetime,
    *,
    log: "GovernanceLog",
) -> dict[str, set[str]]:
    """Return active roles per DID at ``asof`` for the given corpus.

    Walks ``log.iter_events(corpus)`` and applies assertions minus revocations
    windowed by ``signature.signed_at <= asof``. Returns a dict mapping each
    DID with at least one active role to its set of active role names.

    DIDs with no active roles are NOT included in the returned dict (callers
    should treat absence as "no active role"). This makes "did Bob hold role
    X at asof?" check pleasant: ``X in result.get(bob, set())``.

    Boundary discipline: events whose ``signature.signed_at`` is ``None``
    (the Phase-5 honest-unsigned stub) are NOT included — an unsigned event
    cannot meaningfully window in or out of an asof query.
    """
    active: dict[str, set[str]] = {}
    async for event in log.iter_events(corpus):
        signed_at = event.signature.signed_at
        if signed_at is None:
            continue
        if signed_at > asof:
            continue
        if isinstance(event, RoleAssertionEvent):
            active.setdefault(event.subject_did, set()).add(event.role)
        elif isinstance(event, RoleRevocationEvent):
            roles = active.get(event.subject_did)
            if roles is not None:
                roles.discard(event.revoked_role)
                if not roles:
                    active.pop(event.subject_did, None)
        # All other event types are governance writes, not role mutations.
    return active


async def active_roles_for_did(
    corpus: str,
    did: str,
    asof: datetime,
    *,
    log: "GovernanceLog",
) -> set[str]:
    """Convenience wrapper: return the set of active roles for one DID.

    Returns an empty set if the DID has no active roles at ``asof`` (rather
    than raising). Mirrors the dict-get-default pattern callers would write
    anyway around ``active_roles_at``.
    """
    all_roles = await active_roles_at(corpus, asof, log=log)
    return all_roles.get(did, set())
