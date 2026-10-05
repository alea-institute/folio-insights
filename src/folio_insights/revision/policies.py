"""Retraction cascade policies (Phase 9 U3, KTD6/KTD7; PRD §8 P3).

``CascadePolicy`` is its own type, separate from the shard-level
``ReconciliationStrategy`` (the eight sic-et-non strategies of a
``ConflictingAuthoritiesShard``). A policy is chosen per retraction — the
PRD's ``retract --policy`` — and is never read off a shard. The Phase 7
classifier used to look for ``reconciliation_strategy == "prefer_latest"`` on
the dependent, a value the eight-value literal can never hold, so the
re-derive outcome was unreachable; the policy now arrives explicitly.

Reach (Decision Sheet folio-insights-2026-10-05-0814-p9-build-and-calls q4,
"Transitive; deeper levels flagged only"): direct dependents of a retracted
shard get the policy outcome (``auto_rederive`` or ``aporetic``), while
dependents two or more hops away are flagged ``review_needed`` and never
changed automatically.

Stdlib + Pydantic only.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, get_args

CascadePolicy = Literal[
    "prefer_latest",
    "prefer_authority",
    "prefer_most_specific_jurisdiction",
]
CASCADE_POLICIES: tuple[str, ...] = get_args(CascadePolicy)
DEFAULT_CASCADE_POLICY: CascadePolicy = "prefer_latest"

CascadeBucket = Literal["auto_rederive", "aporetic", "review_needed"]

# Epistemic statuses that count as attested authority for ``prefer_authority``.
ATTESTED_STATUSES: frozenset[str] = frozenset(
    {"per_se_nota_quoad_se", "per_se_nota_quoad_nos", "demonstrable", "authority_only"}
)

# Statuses that already need a human (the D-18 review markers).
_REVIEW_STATUSES: frozenset[str] = frozenset({"contested", "aporetic"})


def check_policy(policy: str) -> CascadePolicy:
    """Return ``policy`` if it is a ``CascadePolicy``, else raise ``ValueError``."""
    if policy not in CASCADE_POLICIES:
        raise ValueError(
            f"unknown cascade policy {policy!r}; expected one of {list(CASCADE_POLICIES)}"
        )
    return policy  # type: ignore[return-value]


def framework_at_least_as_specific(candidate: str | None, base: str | None) -> bool:
    """True when ``candidate`` is ``base`` or a sub-framework of it.

    Framework IDs are dotted paths from jurisdiction to body
    (``us.federal.fre`` is inside ``us.federal``), so specificity is the
    segment prefix relation.
    """
    if not candidate or not base:
        return False
    return candidate == base or candidate.startswith(base + ".")


def classify_dependent(dep_attrs: Mapping[str, Any], *, policy: CascadePolicy) -> CascadeBucket:
    """Classify one DIRECT dependent of a retracted shard under ``policy``.

    1. ``review_needed`` wins on any human-judgment marker on the dependent:
       a contested or aporetic status, unresolved contest votes, or a
       ``reconciliation_strategy`` (a ``ConflictingAuthoritiesShard`` already
       records a human reconciliation that a re-derivation must not override).
    2. With no successor for the retracted shard, the dependent reads
       ``aporetic`` under every policy.
    3. With a successor:
       * ``prefer_latest`` — re-derive against the latest (the successor);
       * ``prefer_authority`` — re-derive only when the successor carries an
         attested status, else ``review_needed``;
       * ``prefer_most_specific_jurisdiction`` — re-derive only when the
         successor's framework is the dependent's framework or a sub-framework
         of it, else ``review_needed``.

    ``dep_attrs`` keys (missing keys take the safe defaults):
    ``supersession_available``, ``reconciliation_strategy``,
    ``epistemic_status``, ``unresolved_contest_count``,
    ``successor_epistemic_status``, ``successor_framework_id``,
    ``dependent_framework_id``.
    """
    check_policy(policy)
    status = dep_attrs.get("epistemic_status")
    votes = int(dep_attrs.get("unresolved_contest_count", 0) or 0)
    if status in _REVIEW_STATUSES or votes > 0:
        return "review_needed"
    if dep_attrs.get("reconciliation_strategy") is not None:
        return "review_needed"
    if not dep_attrs.get("supersession_available", False):
        return "aporetic"
    if policy == "prefer_latest":
        return "auto_rederive"
    if policy == "prefer_authority":
        return (
            "auto_rederive"
            if dep_attrs.get("successor_epistemic_status") in ATTESTED_STATUSES
            else "review_needed"
        )
    # prefer_most_specific_jurisdiction
    return (
        "auto_rederive"
        if framework_at_least_as_specific(
            dep_attrs.get("successor_framework_id"), dep_attrs.get("dependent_framework_id")
        )
        else "review_needed"
    )


def classify_at_depth(
    depth: int, dep_attrs: Mapping[str, Any], *, policy: CascadePolicy
) -> CascadeBucket:
    """Graded reach: depth 1 gets the policy outcome; deeper is flag-only."""
    if depth < 1:
        raise ValueError(f"dependent depth must be >= 1, got {depth}")
    if depth == 1:
        return classify_dependent(dep_attrs, policy=policy)
    return "review_needed"


__all__ = [
    "ATTESTED_STATUSES",
    "CASCADE_POLICIES",
    "CascadeBucket",
    "CascadePolicy",
    "DEFAULT_CASCADE_POLICY",
    "check_policy",
    "classify_at_depth",
    "classify_dependent",
    "framework_at_least_as_specific",
]
