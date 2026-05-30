"""GovernanceLog Protocol contract test — D-05 part (b) (Phase 7 D-04/D-06).

The amended D-05 in-phase append-only gate has TWO halves:

  (a) ``fi:GovernanceLogShape`` SHACL refuses duplicate positions / signed_at
      moving backward with position / position gaps (covered by
      ``tests/governance/test_governance_log_shape.py``).
  (b) THIS TEST asserts that ``InMemoryGovernanceLog`` has no public mutation
      API beyond ``append`` — i.e. no ``update`` / ``remove`` / ``truncate``
      / ``drop`` / ``delete`` / ``pop`` / ``clear`` / ``set_at`` / ``replace``
      methods, even as private-shadow-public-method "convenience" leakage.

Together, (a) + (b) close D-05's amended in-phase bar. The persistent SQLite
``BEFORE UPDATE/DELETE → RAISE FAIL`` trigger TRAVELS FORWARD to Phase 13 —
it is NOT in this plan.

Also asserts the Protocol's structural shape: the 5 expected methods are
all ``async def`` (asyncio coroutines), and ``InMemoryGovernanceLog``
structurally matches ``GovernanceLog`` via ``runtime_checkable`` (D-04 seam).

Boundary: this test imports from ``governance/log.py`` (D-04 — stdlib +
Pydantic only — and ``shape_validation.py`` via lazy import inside
``append``). It does NOT import rdflib / pyshacl directly.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from folio_insights.governance.log import GovernanceLog, InMemoryGovernanceLog

pytestmark = pytest.mark.governance


# ── D-05 part (b): no public mutation API beyond `append` ─────────────────


FORBIDDEN_METHOD_NAMES = {
    "update", "remove", "truncate", "drop", "delete", "pop",
    "clear", "set_at", "replace",
}


def test_no_public_mutator_beyond_append() -> None:
    """D-05 part (b): the ONLY public mutator on InMemoryGovernanceLog is
    ``append``. The Protocol contract test enforces that no
    "convenience" mutation methods sneak in (an audit-log foundation
    invariant — T-7-03).
    """
    public_names = [n for n in dir(InMemoryGovernanceLog) if not n.startswith("_")]
    leaked = set(public_names) & FORBIDDEN_METHOD_NAMES
    assert leaked == set(), (
        f"InMemoryGovernanceLog exposes forbidden public mutator(s): {leaked}. "
        f"D-05 part (b) — only `append` may mutate. Move to a `_`-prefixed "
        f"internal helper or remove."
    )


def test_public_surface_matches_protocol() -> None:
    """The InMemoryGovernanceLog public surface IS EXACTLY the Protocol's
    5 methods. Any leak (e.g. a `_helper` accidentally not-underscored) is
    a contract drift.
    """
    expected = {
        "append",
        "query_active_roles_at",
        "get_by_position",
        "iter_events",
        "latest_position",
    }
    public_names = set(n for n in dir(InMemoryGovernanceLog) if not n.startswith("_"))
    assert public_names <= expected, (
        f"InMemoryGovernanceLog has public methods outside the Protocol "
        f"surface: {public_names - expected}. Move to `_`-prefixed internal."
    )


# ── Protocol structural shape: all 5 methods are async coroutines ─────────


@pytest.mark.parametrize("method_name", [
    "append",
    "query_active_roles_at",
    "get_by_position",
    "iter_events",
    "latest_position",
])
def test_protocol_method_is_async(method_name: str) -> None:
    """Every Protocol method is ``async def`` (D-04 — Phase 13 async backend
    slots in without signature churn)."""
    method = getattr(InMemoryGovernanceLog, method_name)
    # iter_events is async-generator-shaped; the others are plain coroutines.
    # Both satisfy iscoroutinefunction OR isasyncgenfunction.
    assert (
        inspect.iscoroutinefunction(method)
        or inspect.isasyncgenfunction(method)
    ), f"{method_name} must be async (def or generator)."


def test_inmemory_satisfies_protocol_runtime_checkable() -> None:
    """``InMemoryGovernanceLog`` structurally matches ``GovernanceLog`` —
    the D-04 seam guarantee (Phase 13's persistent backend ALSO has to
    pass this isinstance check at the same surface)."""
    log = InMemoryGovernanceLog()
    assert isinstance(log, GovernanceLog), (
        "InMemoryGovernanceLog does not structurally satisfy the "
        "GovernanceLog Protocol — the D-04 seam is broken."
    )


# ── Basic empty-log invariant (RESEARCH Pattern 2 docstring) ──────────────


def test_empty_log_latest_position_is_minus_one() -> None:
    """A fresh InMemoryGovernanceLog returns ``-1`` from
    ``latest_position(corpus)`` — the "next append is position 0
    (the genesis row)" invariant from RESEARCH Pattern 2.
    """
    log = InMemoryGovernanceLog()
    pos = asyncio.run(log.latest_position("c1"))
    assert pos == -1
