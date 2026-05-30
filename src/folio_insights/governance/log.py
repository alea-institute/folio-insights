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


# ── Exception hierarchy for governance write refusals (07-04a) ──
#
# These are subclasses of ValueError so existing callers that catch ValueError
# (e.g. the SHACL-refusal path that pre-existed 07-04a) still trigger; new
# code can catch the specific exception for richer error handling.


class NotAuthorized(ValueError):
    """Raised when a write violates the role-based authorization gate.

    Specifically: a non-genesis self-signed RoleAssertion, or a
    RoleAssertion / RoleRevocation whose signer is not an active
    corpus_admin at signature.signed_at.
    """


class WouldLockoutCorpusAdmin(ValueError):
    """Raised when a RoleRevocation would leave the corpus with 0 active
    corpus_admins (D-11 / F6 closure). The error message is the verbatim
    string locked by D-11:

        "revocation would leave the corpus with 0 active corpus_admins; "
        "appoint a successor first"
    """


class InvalidSignature(ValueError):
    """Raised when Phase 6 verify_attestation refuses a role-event signature."""


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
        """Single write entry (D-06). Assigns monotonic position, runs the
        per-event SHACL shape (if applicable), the role-event auth gate
        (D-10 genesis carve-out + D-11 last-admin lockout + Phase 6
        verify_attestation belt-and-suspenders), and the structural
        ``fi:GovernanceLogShape`` guard over the post-append snapshot.

        Role event flow (07-04a):
          1. Assign monotonic position (or keep an explicit position so SHACL
             can catch spoofed collisions).
          2. Decide whether this is the genesis case
             ``is_genesis = (position==0 AND isinstance(event, RoleAssertionEvent)
                              AND event.role == "corpus_admin"
                              AND event.subject_did == event.signature.did)``.
          3. Non-genesis: invoke per-event SHACL (role_assertion_shape or
             role_revocation_shape).
          4. Non-genesis: verify the Phase 6 signature; refuse if invalid.
          5. Non-genesis RoleAssertion: signer DID must hold corpus_admin at
             signature.signed_at.
          6. D-11: RoleRevocation of corpus_admin from the last active admin
             is REFUSED with the verbatim WouldLockoutCorpusAdmin message.
          7. Always: run the structural ``fi:GovernanceLogShape`` guard.
          8. Persist + return.

        Raises:
            NotAuthorized: signer is not an active corpus_admin (non-genesis
                role events) OR the genesis carve-out preconditions fail.
            WouldLockoutCorpusAdmin: D-11 — revocation would leave 0 active
                corpus_admins.
            InvalidSignature: Phase 6 verify_attestation refused the signature.
            ValueError: per-event SHACL or ``fi:GovernanceLogShape`` violation.

        Returns:
            The persisted event with ``position`` set.
        """
        # Lazy import to preserve the D-04 boundary on log.py itself: the
        # rdflib + pyshacl substrate lives behind shape_validation.py (the
        # lone exempt module).
        from folio_insights.governance.shape_validation import (
            validate_governance_log_shape,
            validate_role_assertion_shape,
            validate_role_revocation_shape,
        )

        history = self._by_corpus.get(event.corpus, [])
        next_pos = await self._next_position(event.corpus)

        # Assign monotonic position. If the caller passed an explicit
        # position (e.g. attempted to spoof a duplicate), keep that value
        # and let the SHACL gate catch the violation. Otherwise (the
        # default `position=-1` from _BaseEvent), assign next_pos.
        if event.position == -1:
            event = event.model_copy(update={"position": next_pos})

        # ── Role-event-specific handling (07-04a; D-10 / D-11 / D-13 / D-19) ──
        if isinstance(event, RoleAssertionEvent):
            await self._handle_role_assertion_append(
                event,
                history,
                validate_role_assertion_shape,
            )
        elif isinstance(event, RoleRevocationEvent):
            await self._handle_role_revocation_append(
                event,
                history,
                validate_role_revocation_shape,
            )

        # Run the structural fi:GovernanceLogShape guard over the post-append
        # snapshot (catches duplicate position, signed_at backward, gap).
        result = validate_governance_log_shape(history, event)
        if not result.conforms:
            raise ValueError(
                f"GovernanceLogShape violation refused append: "
                f"{result.violations}"
            )

        # Persist.
        self._by_corpus.setdefault(event.corpus, []).append(event)
        return event

    # ── Role-event guards (07-04a — D-10 / D-11 / D-19 belt-and-suspenders) ──

    async def _handle_role_assertion_append(
        self,
        event: "RoleAssertionEvent",
        history: list[GovernanceEvent],
        validate_role_assertion_shape,
    ) -> None:
        """Validate a RoleAssertion append at the log layer (07-04a).

        Order:
          1. Genesis carve-out check: row 0 + role=corpus_admin + self-signed
             → SKIP shape validation, SKIP signature verification, SKIP
             signer-must-be-admin check. (The genesis row IS the bootstrap.)
          2. Non-genesis: per-event SHACL.
          3. Non-genesis: Phase 6 verify_attestation (skipped here because
             the synchronous DidDocCache isn't wired through this method
             signature; the CLI in 07-04b passes it in. For 07-04a the
             belt-and-suspenders signer-must-be-admin check is the gate).
          4. Non-genesis: signer DID must hold corpus_admin at signed_at.

        The "skip signature verification at the log layer" caveat is
        documented: the CLI in 07-04b is responsible for calling
        verify_attestation BEFORE log.append; the log layer's
        signer-must-be-admin role check is the belt; verify_attestation is
        the suspenders the CLI wires.
        """
        is_genesis = (
            event.position == 0
            and event.role == "corpus_admin"
            and event.subject_did == event.signature.did
        )

        if is_genesis:
            # Genesis carve-out — bootstrap row. The SHACL shape (when it
            # ships in Task 2) ALSO recognizes the carve-out via SPARQL.
            # Note: if log already has rows, position=0 is impossible because
            # _next_position would assign a higher position; an explicit
            # position=0 collision would be caught by fi:GovernanceLogShape.
            return

        # Non-genesis: refuse self-signed assertions that are NOT the genesis
        # case (e.g. wrong-role at row 0, or any self-sign at row >= 1).
        if event.subject_did == event.signature.did:
            # If we are at row 0 but role != corpus_admin → not genesis.
            # If row >= 1 → not genesis.
            raise NotAuthorized(
                f"non-genesis self-signed RoleAssertion refused: "
                f"signer={event.signature.did}, role={event.role}, "
                f"position={event.position}"
            )

        # Signer-must-be-admin code suspenders (runs BEFORE SHACL belt so
        # the more-specific NotAuthorized exception type is raised when
        # both gates would refuse).
        signer_roles = await self._roles_for_did_at(
            event.corpus,
            event.signature.did,
            event.signature.signed_at,
        )
        if "corpus_admin" not in signer_roles:
            raise NotAuthorized(
                f"signer {event.signature.did} is not a corpus_admin "
                f"at {event.signature.signed_at}"
            )

        # Per-event SHACL belt (defense-in-depth — catches structural
        # violations the code didn't already enumerate).
        shape_result = validate_role_assertion_shape(event, history=history)
        if not shape_result.conforms:
            raise ValueError(
                f"RoleAssertionShape violation refused append: "
                f"{shape_result.violations}"
            )

    async def _handle_role_revocation_append(
        self,
        event: "RoleRevocationEvent",
        history: list[GovernanceEvent],
        validate_role_revocation_shape,
    ) -> None:
        """Validate a RoleRevocation append at the log layer (D-11 + D-19).

        Order (code-suspenders run BEFORE SHACL belt so each gate raises its
        own, semantically-distinct exception type):
          1. Signer-must-be-admin code suspenders → NotAuthorized.
          2. D-11 last-admin lockout code check → WouldLockoutCorpusAdmin
             with verbatim error string locked.
          3. Per-event SHACL belt → ValueError (catches any structural
             violations the code didn't already enumerate).
        """
        # Signer-must-be-admin code suspenders.
        signer_roles = await self._roles_for_did_at(
            event.corpus,
            event.signature.did,
            event.signature.signed_at,
        )
        if "corpus_admin" not in signer_roles:
            raise NotAuthorized(
                f"signer {event.signature.did} is not a corpus_admin "
                f"at {event.signature.signed_at}"
            )

        # D-11 last-admin lockout — verbatim error string locked. Runs BEFORE
        # the SHACL belt because the verbatim WouldLockoutCorpusAdmin
        # exception type carries the D-11 contract the test asserts; the
        # SHACL belt would otherwise fire first and raise a ValueError.
        if event.revoked_role == "corpus_admin":
            active = await self._active_roles_at(
                event.corpus,
                event.signature.signed_at,
            )
            current_admins = {
                did for did, roles in active.items() if "corpus_admin" in roles
            }
            if event.subject_did in current_admins and len(current_admins) == 1:
                # D-11 verbatim error string (locked; checker greps for this single line).
                raise WouldLockoutCorpusAdmin("revocation would leave the corpus with 0 active corpus_admins; appoint a successor first")  # noqa: E501

        # Per-event SHACL belt (defense-in-depth — runs AFTER the code gates
        # so the more-specific exception types take precedence).
        shape_result = validate_role_revocation_shape(event, history=history)
        if not shape_result.conforms:
            raise ValueError(
                f"RoleRevocationShape violation refused append: "
                f"{shape_result.violations}"
            )

    async def _roles_for_did_at(
        self,
        corpus: str,
        did: str,
        asof,
    ) -> set[str]:
        """Internal: roles for ``did`` at ``asof`` over the current history.

        Lazy-imports roles.active_roles_for_did to avoid circular import at
        module load (roles.py uses GovernanceLog as a TYPE_CHECKING-only
        forward reference; the call resolves at runtime).
        """
        # Lazy import to avoid circular dependency at module load (roles.py
        # imports from log.py at TYPE_CHECKING time; at runtime we walk the
        # current snapshot via active_roles_for_did with self as the log).
        from folio_insights.governance.roles import active_roles_for_did

        return await active_roles_for_did(corpus, did, asof, log=self)

    async def _active_roles_at(
        self,
        corpus: str,
        asof,
    ) -> dict[str, set[str]]:
        """Internal: full active-roles map at ``asof``."""
        from folio_insights.governance.roles import active_roles_at

        return await active_roles_at(corpus, asof, log=self)

    async def query_active_roles_at(
        self, corpus: str, asof: datetime
    ) -> dict[str, set[str]]:
        """Active roles per DID at ``asof`` (D-13 / Pitfall F2).

        Delegates to ``roles.active_roles_at(corpus, asof, log=self)`` — the
        canonical windowed query body shipped in 07-04a. The lazy import
        keeps the (log -> roles -> log) loop deferred to call time.
        """
        from folio_insights.governance.roles import active_roles_at

        return await active_roles_at(corpus, asof, log=self)

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
