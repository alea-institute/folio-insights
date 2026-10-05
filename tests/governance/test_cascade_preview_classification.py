"""D-18 cascade-preview classifier table test (07-05b Task 1; Phase 9 U3 revision).

The classifier (``classify_dependent``) maps a DIRECT dependent's attributes
plus the retraction's cascade policy onto one of three buckets. Phase 9
(KTD6) passes the policy explicitly — ``CascadePolicy`` is its own type —
instead of reading ``reconciliation_strategy == "prefer_latest"`` off the
dependent, a value the eight-value ``ReconciliationStrategy`` literal can
never hold (so ``auto_rederive`` used to be unreachable).

  * ``review_needed``  — wins on any human-judgment marker:
                            * ``epistemic_status in {contested, aporetic}``,
                            * ``unresolved_contest_count > 0``,
                            * a recorded ``reconciliation_strategy``;
                         or a successor the policy rejects.
  * ``aporetic``       — no successor to re-derive on.
  * ``auto_rederive``  — the policy accepts the successor (``prefer_latest``
                         always; ``prefer_authority`` when the successor is
                         attested; ``prefer_most_specific_jurisdiction`` when
                         its framework is as specific as the dependent's).

Adding a 4th bucket requires an ADR + a synchronous edit to (a) this
table, (b) ``revision/policies.py``, (c) the ``CascadePreview`` Pydantic
model (the bucket lists), and (d) the rich.table columns in
``cli/retract.py``.
"""
from __future__ import annotations

import pytest

from folio_insights.governance.retract import classify_dependent
from folio_insights.revision.policies import (
    CASCADE_POLICIES,
    classify_at_depth,
    framework_at_least_as_specific,
)
from folio_insights.shards.subtypes import ReconciliationStrategy

pytestmark = pytest.mark.governance


# (supersession_available, policy, strategy, status, votes, successor_status,
#  successor_framework, dependent_framework) -> expected bucket
_TABLE: list[tuple[bool, str, str | None, str | None, int, str | None, str | None, str | None, str]] = [
    # 1. prefer_latest + successor: the canonical re-derive case.
    (True, "prefer_latest", None, "authority_only", 0, "authority_only", None, None, "auto_rederive"),
    # 2. prefer_latest, no successor -> aporetic.
    (False, "prefer_latest", None, "authority_only", 0, None, None, None, "aporetic"),
    # 3. contested status wins over an otherwise re-derivable case.
    (True, "prefer_latest", None, "contested", 0, "authority_only", None, None, "review_needed"),
    # 4. aporetic status routes to review.
    (False, "prefer_latest", None, "aporetic", 0, None, None, None, "review_needed"),
    # 5. unresolved contest votes win.
    (True, "prefer_latest", None, "authority_only", 1, "authority_only", None, None, "review_needed"),
    # 6. a recorded sic-et-non reconciliation is human judgment -> review.
    (True, "prefer_latest", "sense_distinction", "authority_only", 0, "authority_only", None, None, "review_needed"),
    (False, "prefer_authority", "unreconciled", "authority_only", 0, None, None, None, "review_needed"),
    # 7. hypothesis dependent, no successor -> aporetic.
    (False, "prefer_latest", None, "hypothesis", 0, None, None, None, "aporetic"),
    # 8. prefer_authority: attested successor re-derives; a hypothesis successor needs review.
    (True, "prefer_authority", None, "demonstrable", 0, "demonstrable", None, None, "auto_rederive"),
    (True, "prefer_authority", None, "demonstrable", 0, "hypothesis", None, None, "review_needed"),
    (False, "prefer_authority", None, "demonstrable", 0, None, None, None, "aporetic"),
    # 9. prefer_most_specific_jurisdiction: same or narrower framework re-derives.
    (True, "prefer_most_specific_jurisdiction", None, "authority_only", 0, "authority_only",
     "us.federal.fre", "us.federal.fre", "auto_rederive"),
    (True, "prefer_most_specific_jurisdiction", None, "authority_only", 0, "authority_only",
     "us.federal.fre", "us.federal", "auto_rederive"),
    (True, "prefer_most_specific_jurisdiction", None, "authority_only", 0, "authority_only",
     "us.common_law", "us.federal.fre", "review_needed"),
    (False, "prefer_most_specific_jurisdiction", None, "authority_only", 0, None,
     None, "us.federal.fre", "aporetic"),
]


@pytest.mark.parametrize(
    "succ, policy, strategy, status, votes, succ_status, succ_fw, dep_fw, expected",
    _TABLE,
    ids=[f"row{i + 1}" for i in range(len(_TABLE))],
)
def test_classify_dependent_truth_table(
    succ: bool,
    policy: str,
    strategy: str | None,
    status: str | None,
    votes: int,
    succ_status: str | None,
    succ_fw: str | None,
    dep_fw: str | None,
    expected: str,
) -> None:
    attrs = {
        "supersession_available": succ,
        "reconciliation_strategy": strategy,
        "epistemic_status": status,
        "unresolved_contest_count": votes,
        "successor_epistemic_status": succ_status,
        "successor_framework_id": succ_fw,
        "dependent_framework_id": dep_fw,
    }
    assert classify_dependent(attrs, policy=policy) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("policy", CASCADE_POLICIES)
def test_classify_dependent_defaults_match_safe_aporetic(policy: str) -> None:
    """Empty / missing attrs never auto-rederive."""
    assert classify_dependent({}, policy=policy) == "aporetic"  # type: ignore[arg-type]


def test_policy_is_required_and_validated() -> None:
    with pytest.raises(TypeError):
        classify_dependent({})  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="unknown cascade policy"):
        classify_dependent({}, policy="sense_distinction")  # type: ignore[arg-type]


def test_cascade_policy_is_separate_from_reconciliation_strategy() -> None:
    from typing import get_args

    assert not set(CASCADE_POLICIES) & set(get_args(ReconciliationStrategy))


@pytest.mark.parametrize("depth", [2, 3, 7])
def test_deeper_dependents_are_flagged_only(depth: int) -> None:
    attrs = {"supersession_available": True, "epistemic_status": "authority_only"}
    assert classify_at_depth(1, attrs, policy="prefer_latest") == "auto_rederive"
    assert classify_at_depth(depth, attrs, policy="prefer_latest") == "review_needed"
    with pytest.raises(ValueError):
        classify_at_depth(0, attrs, policy="prefer_latest")


def test_framework_specificity_is_the_segment_prefix() -> None:
    assert framework_at_least_as_specific("us.federal.fre", "us.federal")
    assert framework_at_least_as_specific("us.federal", "us.federal")
    assert not framework_at_least_as_specific("us.federalx", "us.federal")
    assert not framework_at_least_as_specific("us.federal", "us.federal.fre")
    assert not framework_at_least_as_specific(None, "us.federal")
