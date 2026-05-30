"""SignedAction Literal must expose exactly 13 values (D-13 extends 12 → 13).

Phase 6's ``shards/envelope.py`` ships a 12-value ``SignedAction`` Literal;
Plan 07-01 extends it by exactly one — ``"role_revocation"`` — appended as the
final value. Position is load-bearing (D-13 stability — downstream
serialization formats can rely on the final-position pin), so we assert the
last entry too.

D-13 closure depends on this Literal carrying a discrete ``role_revocation``
token so that the ``GovernanceEvent`` discriminated union can dispatch it to a
distinct ``RoleRevocationEvent`` class (NOT a flag on ``RoleAssertionEvent``).
"""
from __future__ import annotations

from typing import get_args

import pytest

from folio_insights.shards.envelope import SignedAction

pytestmark = pytest.mark.governance


def test_signed_action_literal_has_exactly_13_values() -> None:
    """D-13: Phase 6's 12-value Literal extended by exactly one (12 → 13)."""
    values = get_args(SignedAction)
    assert len(values) == 13, (
        f"SignedAction must carry exactly 13 values (12 Phase 6 + role_revocation); "
        f"got {len(values)}: {values}"
    )


def test_signed_action_literal_contains_role_revocation() -> None:
    """D-13: ``role_revocation`` is present in the Literal vocabulary."""
    values = get_args(SignedAction)
    assert "role_revocation" in values, (
        f"SignedAction must contain 'role_revocation' (D-13); got {values}"
    )


def test_signed_action_literal_role_revocation_is_last() -> None:
    """D-13: ``role_revocation`` is appended as the final value (positional pin).

    Append-at-end keeps Phase 6's positional ordering stable for any downstream
    serialization that relies on Literal value order.
    """
    values = get_args(SignedAction)
    assert values[-1] == "role_revocation", (
        f"role_revocation must be the final SignedAction value; got values={values}"
    )


def test_signed_action_literal_preserves_phase_6_values() -> None:
    """Regression guard: every Phase 6 value still appears in the Literal."""
    values = get_args(SignedAction)
    phase_6 = {
        "extract", "promote", "demote", "contest", "supersede", "retract",
        "distinguo", "role_assertion",
        "content_edit", "reparent", "reconcile", "resolve_contest",
    }
    missing = phase_6 - set(values)
    assert not missing, f"Phase 6 SignedAction values dropped: {missing}"
