"""D-18 cascade-preview classifier table test (07-05b Task 1).

The D-18 classifier (``classify_dependent``) maps a dependent's attribute
tuple ``(supersession_available, reconciliation_strategy, epistemic_status,
unresolved_contest_count)`` onto one of three buckets:

  * ``auto_rederive``  — ``reconciliation_strategy="prefer_latest"`` AND
                         ``supersession_available=True``.
  * ``review_needed``  — any of:
                            * ``epistemic_status in {contested, aporetic}``,
                            * ``unresolved_contest_count > 0``,
                            * ``reconciliation_strategy != prefer_latest``
                              (when a strategy IS set).
  * ``aporetic``       — fall-through (no supersession, no reviewer marker,
                         no contest votes, no non-prefer_latest strategy).

The heuristic is locked verbatim by D-18 (RESEARCH lines 1338-1353).
Adding a 4th bucket requires an ADR + a synchronous edit to (a) this
table, (b) the ``classify_dependent`` body, (c) the ``CascadePreview``
Pydantic model (the bucket lists), and (d) the human-verify rich.table
columns in ``cli/retract.py``.
"""
from __future__ import annotations

import pytest

from folio_insights.governance.retract import classify_dependent

pytestmark = pytest.mark.governance


# ── D-18 truth table (>=8 rows per plan acceptance) ────────────────────────
#
# Each row encodes (supersession_available, reconciliation_strategy,
# epistemic_status, unresolved_contest_count) -> expected_bucket.
#
# The `review_needed wins` precedence rule (status / votes / non-prefer_latest
# strategy override an otherwise-auto_rederive case) is exercised by rows 4-6.
_TABLE: list[tuple[bool, str | None, str | None, int, str]] = [
    # 1. The canonical auto_rederive case: prefer_latest + supersession.
    (True, "prefer_latest", "authority_only", 0, "auto_rederive"),
    # 2. prefer_latest but NO supersession available → fall-through to aporetic.
    (False, "prefer_latest", "authority_only", 0, "aporetic"),
    # 3. No strategy at all + no marker → aporetic.
    (False, None, "authority_only", 0, "aporetic"),
    # 4. epistemic_status=contested wins over otherwise auto_rederive case.
    (True, "prefer_latest", "contested", 0, "review_needed"),
    # 5. epistemic_status=aporetic also routes to review_needed.
    (False, None, "aporetic", 0, "review_needed"),
    # 6. unresolved_contest_count > 0 wins, even with prefer_latest + succ.
    (True, "prefer_latest", "authority_only", 1, "review_needed"),
    # 7. Non-prefer_latest strategy (e.g. sense_distinction) routes to review.
    (True, "sense_distinction", "authority_only", 0, "review_needed"),
    # 8. Strategy set to something other than prefer_latest, no succ → still review.
    (False, "unreconciled", "authority_only", 0, "review_needed"),
    # 9. Status hypothesis + no strategy + no succ + no votes → aporetic.
    (False, None, "hypothesis", 0, "aporetic"),
    # 10. Status demonstrable + no strategy + supersession_available → aporetic
    #     (no prefer_latest -> can't route to auto_rederive).
    (True, None, "demonstrable", 0, "aporetic"),
]


@pytest.mark.parametrize(
    "supersession_available, strategy, status, votes, expected",
    _TABLE,
    ids=[f"row{i + 1}" for i in range(len(_TABLE))],
)
def test_classify_dependent_truth_table(
    supersession_available: bool,
    strategy: str | None,
    status: str | None,
    votes: int,
    expected: str,
) -> None:
    """Exercise the D-18 classifier across the >=8 row truth table."""
    attrs = {
        "supersession_available": supersession_available,
        "reconciliation_strategy": strategy,
        "epistemic_status": status,
        "unresolved_contest_count": votes,
    }
    bucket = classify_dependent(attrs)
    assert bucket == expected, (
        f"D-18 classifier returned {bucket!r} for attrs={attrs}; "
        f"expected {expected!r}. The heuristic is locked verbatim by D-18 "
        "(RESEARCH lines 1338-1353)."
    )


def test_classify_dependent_defaults_match_safe_aporetic() -> None:
    """Empty / missing attrs route to the safe ``aporetic`` bucket.

    The cascade preview must NEVER auto-rederive on a missing-attribute
    edge case — the only way to land in ``auto_rederive`` is the explicit
    prefer_latest + supersession combination.
    """
    assert classify_dependent({}) == "aporetic"
