"""Phase 7 active-roles query — windowed by event time <= asof (D-13 / Pitfall F2).

Walks the governance log and returns the active role map at a point in time.
The windowing discipline is the structural analog of
``identity/cache.py::DidDocCache.get((did, signed_at))`` — every governance
query that depends on "what roles held at time T" goes through this function
rather than reaching into the log directly, which closes the F2 pitfall for
role queries (key rotation does NOT retroactively invalidate a role
assertion).

D-13 active-roles semantics:

  * Walk all events in the corpus's log in position order.
  * For each event whose *event time* is ``<= asof``:
      - If RoleAssertionEvent: add (subject_did -> role) to the active set.
      - If RoleRevocationEvent: remove (subject_did -> revoked_role).
  * Events whose time is after ``asof`` are NOT YET visible and are ignored.
  * Re-assertion after revocation is supported via set semantics: revoke
    at t1 followed by re-assert at t2 means active at t2.

Event time (R17 / KTD12, ``governance/clock.py``): the time an event took
effect is the server's commit time wherever a server clock exists. The
persistent log (``storage/governance.py``) supplies each row's journal
``committed_at``; an in-memory snapshot built from that history carries the
same times. Only an in-memory log populated without a server clock — a test /
offline structure — falls back to the signer-claimed
``signature.signed_at``. A caller may also pass ``event_time`` explicitly.

How a log supplies its times: a log may implement the private async iterator
``_iter_timed_events(corpus)`` yielding ``(event, time)`` pairs from one
consistent read. Logs that implement only the public ``GovernanceLog``
Protocol are windowed by ``signed_at``.

D-04 boundary: stdlib + Pydantic only. No rdflib / pyshacl / aiosqlite imports
here. The dep-leak guard at ``tests/governance/test_dep_leak_guard.py``
enforces this on the full ``governance/`` tree (except ``shape_validation.py``).
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from datetime import datetime
from typing import TYPE_CHECKING

from folio_insights.governance.clock import EventTime, signed_at_time
from folio_insights.governance.events import (
    GovernanceEvent,
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
    "roles_from_timed_events",
    "timed_events",
]


if TYPE_CHECKING:
    from folio_insights.governance.log import GovernanceLog


async def timed_events(
    corpus: str,
    *,
    log: "GovernanceLog",
    event_time: EventTime | None = None,
) -> AsyncIterator[tuple[GovernanceEvent, datetime | None]]:
    """Yield ``(event, time)`` for every event of ``corpus`` in position order.

    ``event_time`` wins when given. Otherwise the log's own
    ``_iter_timed_events`` supplies the times (server commit time for the
    persistent log and for snapshots built from its history), and a log
    without one is windowed by ``signature.signed_at``.
    """
    if event_time is None:
        hook = getattr(log, "_iter_timed_events", None)
        if hook is not None:
            async for pair in hook(corpus):
                yield pair
            return
        event_time = signed_at_time
    async for event in log.iter_events(corpus):
        yield event, event_time(event)


def roles_from_timed_events(
    pairs: Iterable[tuple[GovernanceEvent, datetime | None]],
    asof: datetime | None,
) -> dict[str, set[str]]:
    """Fold role assertions minus revocations over ``pairs`` (position order).

    Pure: the shared body of ``active_roles_at`` and the SHACL role-context
    graph. Events with no time are skipped (an unsigned / untimed event cannot
    window in or out). ``asof=None`` includes every timed event.
    """
    active: dict[str, set[str]] = {}
    for event, at in pairs:
        if at is None:
            continue
        if asof is not None and at > asof:
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


async def active_roles_at(
    corpus: str,
    asof: datetime,
    *,
    log: "GovernanceLog",
    event_time: EventTime | None = None,
) -> dict[str, set[str]]:
    """Return active roles per DID at ``asof`` for the given corpus.

    Applies assertions minus revocations over the corpus log, windowed by
    each event's time ``<= asof`` (see the module docstring for where the
    time comes from: server commit time for persistent storage, ``signed_at``
    only for an in-memory log with no server clock, or ``event_time`` when
    the caller passes one). Returns a dict mapping each DID with at least
    one active role to its set of active role names.

    DIDs with no active roles are NOT included in the returned dict (callers
    should treat absence as "no active role"). This makes "did Bob hold role
    X at asof?" check pleasant: ``X in result.get(bob, set())``.

    Boundary discipline: events with no time (an unsigned stub whose
    ``signed_at`` is ``None`` in an in-memory log) are NOT included.
    """
    pairs = [pair async for pair in timed_events(corpus, log=log, event_time=event_time)]
    return roles_from_timed_events(pairs, asof)


async def active_roles_for_did(
    corpus: str,
    did: str,
    asof: datetime,
    *,
    log: "GovernanceLog",
    event_time: EventTime | None = None,
) -> set[str]:
    """Convenience wrapper: return the set of active roles for one DID.

    Returns an empty set if the DID has no active roles at ``asof`` (rather
    than raising). Mirrors the dict-get-default pattern callers would write
    anyway around ``active_roles_at``.
    """
    all_roles = await active_roles_at(corpus, asof, log=log, event_time=event_time)
    return all_roles.get(did, set())
