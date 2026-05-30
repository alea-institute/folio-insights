"""Hypothesis property: active_roles_at is stable under same-asof-window reordering.

D-13 active-roles semantics: a chronological walk over assertions minus
revocations windowed by ``signature.signed_at <= asof``. Set semantics imply
the result depends ONLY on which (did, role) pairs are active at the asof
boundary — NOT on the insertion order within the asof window.

Property statement (max_examples=200):

  For any sequence S of (did, role, assert-or-revoke, signed_at) tuples drawn
  from a small fixed pool, the active-roles map computed at a fixed asof equals
  the map computed over any permutation of S that preserves the (signed_at)
  ordering relation needed by the chronological walk. We approximate "same
  asof window" by using a SINGLE asof timestamp and tuples whose signed_at all
  fall BEFORE the asof, with mutation order shuffled within randomly-tied
  timestamps. The map is stable.

Budget note: 200 examples — small enough to fit the 30s pytest-timeout (each
example builds a fresh InMemoryGovernanceLog + iterates active_roles_at), large
enough for the Hypothesis shrinker to find any insertion-order-sensitive bug.
Mirrors the 07-03 property-test deviation rationale (the per-example cost is
the bottleneck under pyshacl; here the per-example cost is asof-walk only).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from folio_insights.governance.events import (
    RoleAssertionEvent,
    RoleRevocationEvent,
)
from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.governance.roles import active_roles_at
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "p"
T0 = datetime(2026, 1, 1, tzinfo=UTC)
ASOF = T0 + timedelta(days=365)  # all events fall before this asof

# Small pools to keep state space tractable.
_DIDS = ["did:fi:a", "did:fi:b", "did:fi:c"]
_ROLES = ["extractor", "reviewer", "arbiter"]


def _sig(did: str, action: str, signed_at: datetime) -> AttestedSignature:
    return AttestedSignature(
        did=did,
        action=action,  # type: ignore[arg-type]
        signed_at=signed_at,
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{did}#key-1",
        did_doc_snapshot_at=signed_at,
        verified=None,
    )


# A descriptor: (subject_did, role, op, day_offset) where op in {assert, revoke}.
_descriptor = st.tuples(
    st.sampled_from(_DIDS),
    st.sampled_from(_ROLES),
    st.sampled_from(["assert", "revoke"]),
    st.integers(min_value=0, max_value=10),
)


def _build_log(descriptors) -> InMemoryGovernanceLog:
    """Build a fresh InMemoryGovernanceLog with one event per descriptor.

    We sort by day_offset to keep the chronological walk well-defined (the
    log enforces monotonic signed_at via the SHACL gate). Within the same
    day_offset the descriptor order is what we shuffle in the test to prove
    stability.
    """
    log = InMemoryGovernanceLog()
    # Sort by day so the SHACL signed_at-non-decreasing constraint holds.
    sorted_d = sorted(descriptors, key=lambda d: d[3])
    for subject_did, role, op, day_off in sorted_d:
        signed_at = T0 + timedelta(days=day_off)
        if op == "assert":
            event = RoleAssertionEvent(
                corpus=CORPUS,
                signature=_sig(subject_did, "role_assertion", signed_at),
                subject_did=subject_did,
                role=role,  # type: ignore[arg-type]
            )
        else:
            event = RoleRevocationEvent(
                corpus=CORPUS,
                signature=_sig(subject_did, "role_revocation", signed_at),
                subject_did=subject_did,
                revoked_role=role,  # type: ignore[arg-type]
            )
        # Bypass log.append role-event guards: write directly into the
        # internal list. We're testing the active_roles_at semantics, not the
        # log's authorization guards. (The log's _by_corpus is implementation
        # detail used only for this property test setup.)
        # Assign the next position so the snapshot is well-formed.
        next_pos = len(log._by_corpus.get(CORPUS, []))
        positioned = event.model_copy(update={"position": next_pos})
        log._by_corpus.setdefault(CORPUS, []).append(positioned)
    return log


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(descriptors=st.lists(_descriptor, min_size=0, max_size=10))
def test_active_roles_at_is_order_stable_within_same_day(descriptors) -> None:
    """active_roles_at returns the same dict regardless of within-day ordering.

    Concretely: build a log with the descriptors sorted-by-day, then build a
    REVERSE-within-day log. Both should yield the same active-roles map at
    asof (any chronologically-equivalent ordering gives the same set).
    """
    log_forward = _build_log(descriptors)
    # Same descriptors, reverse-ordered within tied days.
    sorted_descriptors = sorted(descriptors, key=lambda d: d[3])
    descriptors_reordered = list(reversed(sorted_descriptors))
    log_reordered = _build_log(descriptors_reordered)

    map_forward = asyncio.run(active_roles_at(CORPUS, ASOF, log=log_forward))
    map_reordered = asyncio.run(active_roles_at(CORPUS, ASOF, log=log_reordered))

    # For each DID with active roles, the final set must match — regardless
    # of insertion order within tied days. (Strictly: this property holds
    # when the chronological walk produces the same FINAL set; we encode
    # that by sorting by day and asserting the maps match.)
    # Note: within the SAME day a revoke-then-assert vs assert-then-revoke
    # are NOT order-equivalent. We assert the weaker (sufficient) form:
    # the SET of (did, role) pairs at asof, computed via sorted-by-day
    # walks, is the same regardless of within-day reordering when the
    # within-day descriptors do not mutate the same (did, role) pair.
    # If they do (revoke + assert same pair same day), the test deliberately
    # accepts either outcome — both are valid windowed reads. We capture this
    # by asserting equality of the COMPUTED MAPS rather than re-deriving the
    # ground truth; the chronological walk is deterministic per ordering.
    # The property therefore tests: "same descriptors, same walk algorithm,
    # same final state — independent of reverse ordering noise within day
    # groups that don't conflict on the same (did, role) pair."
    same_day_groups: dict[int, list] = {}
    for d in descriptors:
        same_day_groups.setdefault(d[3], []).append((d[0], d[1]))
    conflicting_pair = False
    for day, pairs in same_day_groups.items():
        # If a (did, role) appears more than once on the same day with both
        # assert + revoke, ordering matters; skip the equality assertion.
        from collections import Counter

        counts = Counter(pairs)
        if any(c > 1 for c in counts.values()):
            conflicting_pair = True
            break
    if not conflicting_pair:
        assert map_forward == map_reordered
