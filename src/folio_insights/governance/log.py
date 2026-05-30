"""Phase 7 GovernanceLog seam — append-only event log per corpus (CONTEXT D-04, D-05, D-06).

The append-only governance log per PRD §3.1.5. D-04 keeps that signature honest
with a thin ``GovernanceLog`` Protocol over an in-memory dict; Phase 13 swaps a
persistent aiosqlite-backed store + the ``BEFORE UPDATE/DELETE → RAISE FAIL``
trigger in behind the *same* async interface without touching any caller
(D-05 — the path is ``async def`` so Phase 13 storage slots in without
signature churn).

Analog: ``revision/store.py::ShardStore`` (in-memory-dict + thin async Protocol)
and ``identity/cache.py::DidDocCache`` (windowed-by-time async query pattern).

Boundary (D-04): this module is stdlib + Pydantic ONLY — NO ``aiosqlite`` /
``rdflib`` / ``pyoxigraph`` / ``oxrdflib`` imports here (the
``tests/governance/test_dep_leak_guard.py`` boundary). Phase 13 is the place
that fills the persistent backend; in Phase 7 the dict IS the store. The
SHACL validator is reached via a LAZY import of
``folio_insights.governance.shape_validation`` from inside ``append()`` — the
shape_validation module is the lone exempt file allowed to pull rdflib +
pyshacl (mirrors revision/shape_validation.py).

D-05 amended in-phase append-only gate (TWO halves):

  (a) ``fi:GovernanceLogShape`` SHACL refuses duplicate positions / signed_at
      moving backward with position / position gaps. Wired here:
      ``append()`` calls ``validate_governance_log_shape(history, pending)``
      and raises ``ValueError`` if ``conforms=False``.
  (b) THIS MODULE EXPOSES NO PUBLIC MUTATOR BEYOND ``append``. The Protocol
      contract test
      (``tests/governance/test_governance_log_protocol_contract.py``)
      enforces the absence of update / remove / truncate / drop / delete /
      pop / clear / set_at / replace methods. Internal helpers (e.g.
      ``_assign_position``) are ``_``-prefixed.

D-05 forward-travel (NOT in this plan): the persistent SQLite ``BEFORE
UPDATE/DELETE → RAISE FAIL`` trigger lands in Phase 13. The Phase 7 dict +
the Protocol surface + the SHACL guard are the substrate Phase 13 swaps
behind. The trigger is the third defense-in-depth layer that arrives THEN.

D-06: ``append(event: GovernanceEvent)`` is the SINGLE WRITE ENTRY. It is
the only public mutator and the only place that assigns ``position``. It
returns the persisted event (with ``position`` set).

D-10 genesis carve-out + signature verification + D-11 last-admin lockout
refusal are STUBBED in this plan — RoleAssertionEvent / RoleRevocationEvent
appended → ``NotImplementedError`` mentioning 07-04. The substrate (Protocol
shape, monotonic position, SHACL gate) is final here.

D-07 on-disk layout (forward-travel, NOT in this plan): Phase 13 will land
``<corpus>/governance.ttl`` + ``<corpus>/.governance.sqlite`` behind this
Protocol. The on-disk layout is documented here so future readers find the
trail.
"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator, Protocol, runtime_checkable

from folio_insights.governance.events import (
    GovernanceEvent,
    RoleAssertionEvent,
    RoleRevocationEvent,
)


@runtime_checkable
class GovernanceLog(Protocol):
    """Append-only governance log seam (D-04). Phase 13 swaps aiosqlite behind it.

    The 5-method async surface every backend (in-memory now; aiosqlite in
    Phase 13) MUST satisfy. ``runtime_checkable`` allows the Protocol
    contract test to verify any backend structurally without a nominal
    inheritance relationship.

    Methods:

      * ``append(event)`` — single write entry (D-06). Validates the SHACL
        ``fi:GovernanceLogShape`` invariant over the post-append snapshot;
        assigns monotonic position; returns the persisted event.
      * ``query_active_roles_at(corpus, asof)`` — active roles per DID at
        ``asof`` (assertions minus revocations, windowed by
        ``signature.signed_at <= asof``). D-13 / Pitfall F2.
      * ``get_by_position(corpus, position)`` — random-access read by
        log position.
      * ``iter_events(corpus)`` — async iterator over all events for a
        corpus in position order.
      * ``latest_position(corpus)`` — the highest assigned position, or
        ``-1`` if the log is empty (so the next append is position 0 — the
        genesis row).
    """

    async def append(self, event: GovernanceEvent) -> GovernanceEvent: ...

    async def query_active_roles_at(
        self, corpus: str, asof: datetime
    ) -> dict[str, set[str]]: ...

    async def get_by_position(
        self, corpus: str, position: int
    ) -> GovernanceEvent | None: ...

    def iter_events(self, corpus: str) -> AsyncIterator[GovernanceEvent]: ...

    async def latest_position(self, corpus: str) -> int: ...


class InMemoryGovernanceLog:
    """Process-local in-memory ``GovernanceLog`` (D-04). Reset per construction.

    Stdlib + Pydantic only — the dict IS the seam Phase 13 replaces with a
    persistent aiosqlite-backed store behind the identical async interface.

    Per-corpus event list: ``_by_corpus[corpus] = [event0, event1, ...]``
    where the list index equals the event's ``position`` field. The
    structural invariant (list index == event.position) is enforced by
    ``append()`` (positions are assigned monotonically from 0).

    Public surface (D-05 part b): ``append``, ``query_active_roles_at``,
    ``get_by_position``, ``iter_events``, ``latest_position`` — and NOTHING
    ELSE. The Protocol contract test in
    ``tests/governance/test_governance_log_protocol_contract.py`` enforces.
    Internal helpers are ``_``-prefixed.
    """

    def __init__(self) -> None:
        self._by_corpus: dict[str, list[GovernanceEvent]] = {}

    async def append(self, event: GovernanceEvent) -> GovernanceEvent:
        """Single write entry (D-06). Assigns monotonic position and runs
        the SHACL ``fi:GovernanceLogShape`` guard over the post-append
        snapshot.

        Role-event handling (RoleAssertionEvent / RoleRevocationEvent) is
        DEFERRED to plan 07-04 — this method raises
        ``NotImplementedError`` on those event types so the substrate
        boundary is honest about what does and does not work yet (no
        silent "passed" on a role write that the next wave will actually
        validate against the role-event SHACL + last-admin lockout).

        Raises:
            NotImplementedError: if ``event`` is a role event (07-04 owns).
            ValueError: if the SHACL guard refuses the post-append snapshot
                (e.g. duplicate position, signed_at backward, gap). The
                error message contains the SHACL violation list.

        Returns:
            The persisted event with ``position`` set.
        """
        # 07-04 carve-out (D-10 genesis + D-11 last-admin lockout + signature
        # verification all land there). Role events refuse loudly here.
        if isinstance(event, (RoleAssertionEvent, RoleRevocationEvent)):
            raise NotImplementedError(
                "Role event validation lands in 07-04 (genesis carve-out + "
                "last-admin lockout + verify_attestation belt-and-suspenders)."
            )

        # Lazy import to preserve the D-04 boundary on log.py itself: the
        # rdflib + pyshacl substrate lives behind shape_validation.py (the
        # lone exempt module). A module-top import would still be inside the
        # governance/ package and pull pyshacl/rdflib at import time, which
        # is fine for the dep-leak guard (it scans source text, not runtime
        # imports) but the lazy import is cheap and matches the seam
        # discipline.
        from folio_insights.governance.shape_validation import (
            validate_governance_log_shape,
        )

        history = self._by_corpus.get(event.corpus, [])
        next_pos = await self._next_position(event.corpus)

        # Assign monotonic position. If the caller passed an explicit
        # position (e.g. attempted to spoof a duplicate), keep that value
        # and let the SHACL gate catch the violation. Otherwise (the
        # default `position=-1` from _BaseEvent), assign next_pos.
        if event.position == -1:
            event = event.model_copy(update={"position": next_pos})

        # Run the SHACL gate over the post-append snapshot.
        result = validate_governance_log_shape(history, event)
        if not result.conforms:
            raise ValueError(
                f"GovernanceLogShape violation refused append: "
                f"{result.violations}"
            )

        # Persist.
        self._by_corpus.setdefault(event.corpus, []).append(event)
        return event

    async def query_active_roles_at(
        self, corpus: str, asof: datetime
    ) -> dict[str, set[str]]:
        """Active roles per DID at ``asof`` (D-13 / Pitfall F2).

        STUB in this plan (07-03). The real body lands in 07-04 inside
        ``governance/roles.py`` (active_roles_at walks the log applying
        assertions minus revocations, windowed by
        ``signature.signed_at <= asof``).

        Raises:
            NotImplementedError: 07-04 owns the windowed query.
        """
        raise NotImplementedError(
            "Active-roles query body lands in 07-04 (roles.py)."
        )

    async def get_by_position(
        self, corpus: str, position: int
    ) -> GovernanceEvent | None:
        """Return the event at the given position, or ``None`` if absent.

        The structural invariant (list index == event.position) means we
        can index directly. Negative positions raise IndexError-style
        ``None`` (treated as "not present").
        """
        events = self._by_corpus.get(corpus, [])
        if position < 0 or position >= len(events):
            return None
        return events[position]

    async def iter_events(self, corpus: str) -> AsyncIterator[GovernanceEvent]:
        """Async iterator over all events for a corpus in position order."""
        for event in self._by_corpus.get(corpus, []):
            yield event

    async def latest_position(self, corpus: str) -> int:
        """Highest assigned position for the corpus, or ``-1`` if empty.

        The "next append is position 0" sentinel — the genesis row case.
        Callers compute ``await log.latest_position(corpus) + 1`` to
        anticipate the next position, but ``append()`` does this
        internally so callers normally don't have to.
        """
        return len(self._by_corpus.get(corpus, [])) - 1

    # ── Internal helpers (D-05 part b — `_`-prefixed) ────────────────────

    async def _next_position(self, corpus: str) -> int:
        """The next position to assign (``latest_position + 1``).

        Internal because it is a position-assignment primitive — exposing
        it publicly would leak a write-adjacent API beyond the single
        ``append`` entry (D-06 violation).
        """
        return len(self._by_corpus.get(corpus, []))


__all__ = ["GovernanceLog", "InMemoryGovernanceLog"]
