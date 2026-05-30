"""Hypothesis property test: ``InMemoryGovernanceLog.append`` assigns
monotonic 0..N-1 positions over random event sequences (Phase 7 D-06).

Contract: for any sequence of 1 ≤ N ≤ 100 valid (non-role) events appended
in order, the resulting events carry positions ``[0, 1, ..., N-1]`` and
``latest_position`` reports ``N-1``. This proves the D-06 single-write-entry
discipline: position assignment is monotonic, gap-free, and starts at 0.

Mirrors ``tests/identity/test_canonical_jcs_properties.py`` Hypothesis
decoration: ``@settings(max_examples=1000, deadline=None)``. Role events
are EXCLUDED from the strategy because plan 07-03 stubs
``RoleAssertionEvent`` / ``RoleRevocationEvent`` to raise
``NotImplementedError`` (07-04 owns role-event validation).

Budget: 1000 examples, deadline disabled. Hypothesis health-checks are
suppressed because the SHACL gate runs per-append (each example walks the
pyshacl validator over a growing graph; the per-example cost grows
quadratically with N, but 100 events × 1000 examples stays well within
the 30s pytest-timeout default in pyproject.toml).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from folio_insights.governance.events import ExtractEvent
from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


# ── Event-construction strategy ──────────────────────────────────────────


@st.composite
def extract_events_with_increasing_signed_at(draw, *, n: int) -> list[ExtractEvent]:
    """Build ``n`` ExtractEvents whose ``signature.signed_at`` is strictly
    increasing (one-second step per event from a random base).

    Each event carries:
      * a random corpus string from a small pool (so we mostly test the
        single-corpus path but occasionally exercise multi-corpus
        independence);
      * a random shard_iri suffix;
      * a random DID suffix;
      * a strictly-increasing signed_at (required by the SHACL gate to
        avoid back-dating refusal — orthogonal to the position
        monotonicity we're testing).

    We use a SINGLE corpus per generated batch so the position assignment
    invariant is testable as a single sequence. Multi-corpus independence
    is tested elsewhere.
    """
    corpus = draw(st.sampled_from(["alpha", "beta", "gamma"]))
    base_did = draw(st.text(
        alphabet=st.characters(min_codepoint=0x41, max_codepoint=0x7A),
        min_size=3,
        max_size=8,
    ))
    # Base time is a fixed anchor so the test is reproducible across CI.
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    events = []
    for i in range(n):
        did = f"did:fi:{base_did}{i}"
        sig = AttestedSignature(
            did=did,
            action="extract",
            signed_at=base + timedelta(seconds=i),
            signature="",
            over_content_hash="0" * 64,
            signing_key_id=f"{did}#key-1",
            did_doc_snapshot_at=base + timedelta(seconds=i),
            verified=None,
        )
        events.append(
            ExtractEvent(
                corpus=corpus,
                signature=sig,
                shard_iri=f"fi:shard:{corpus}:{i}",
            )
        )
    return events


# ── Property: positions are 0..N-1, gap-free, in order ────────────────────


@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(n=st.integers(min_value=1, max_value=100), data=st.data())
def test_append_assigns_monotonic_positions_property(n: int, data) -> None:
    """For random sequences of 1 ≤ N ≤ 100 ExtractEvents appended in order,
    the persisted positions are exactly ``[0, 1, ..., N-1]`` and
    ``latest_position`` is ``N-1``.
    """
    events = data.draw(extract_events_with_increasing_signed_at(n=n))
    assert len(events) == n
    corpus = events[0].corpus

    async def _run() -> None:
        log = InMemoryGovernanceLog()
        for i, ev in enumerate(events):
            persisted = await log.append(ev)
            assert persisted.position == i, (
                f"event {i}: append assigned position={persisted.position}, "
                f"expected {i}"
            )
        # After all appends, latest_position reports N-1.
        latest = await log.latest_position(corpus)
        assert latest == n - 1, (
            f"latest_position={latest}, expected {n - 1}"
        )
        # And iter_events yields them in position order.
        collected = []
        async for ev in log.iter_events(corpus):
            collected.append(ev)
        assert [e.position for e in collected] == list(range(n))

    asyncio.run(_run())
