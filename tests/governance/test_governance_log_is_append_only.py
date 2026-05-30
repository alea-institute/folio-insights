"""SHACL-level append-only refusal end-to-end test — D-05 part (a) (Phase 7).

End-to-end variant of ``test_governance_log_shape.py``: rather than calling
``validate_governance_log_shape`` directly, this test drives
``InMemoryGovernanceLog.append`` and verifies the validator is wired into the
single write seam (D-06). A tampered history (one with a position-0 event
whose ``position`` value was hand-edited via ``model_copy``) is then passed
to the validator separately to prove SHACL refuses it — the kind of bypass
a future caller might attempt before the SQLite trigger ships in Phase 13.

Two-layer division (mirrored from Phase 5 forward-only):

  * The Pydantic ``_BaseEvent.position`` default = -1 + ``append()`` assigns
    monotonic positions is the AUTHORITATIVE structural guarantee.
  * The SHACL guard in ``validate_governance_log_shape`` is DEFENSE-IN-DEPTH
    — catches records loaded out-of-band (e.g. a tamper of `_by_corpus`
    directly via reflection, which the Protocol contract test enforces is
    impossible via the public surface).

Boundary: this test imports ``InMemoryGovernanceLog`` from
``governance/log.py`` and ``validate_governance_log_shape`` from
``governance/shape_validation.py`` (the lone D-04 exempt module).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import ExtractEvent
from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.governance.shape_validation import validate_governance_log_shape
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


def _sig(signed_at: datetime, did: str = "did:fi:alice") -> AttestedSignature:
    return AttestedSignature(
        did=did,
        action="extract",
        signed_at=signed_at,
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{did}#key-1",
        did_doc_snapshot_at=signed_at,
        verified=None,
    )


def _event(signed_at: datetime, shard_iri: str = "fi:shard:s") -> ExtractEvent:
    return ExtractEvent(
        corpus="test-corpus",
        signature=_sig(signed_at),
        shard_iri=shard_iri,
    )


def test_append_assigns_monotonic_positions() -> None:
    """Two appends produce positions 0 and 1 — the structural guarantee
    that drives the SHACL invariant from the only legitimate write path."""
    log = InMemoryGovernanceLog()
    e1 = asyncio.run(
        log.append(_event(datetime(2026, 1, 1, tzinfo=UTC), "fi:shard:a"))
    )
    e2 = asyncio.run(
        log.append(_event(datetime(2026, 1, 2, tzinfo=UTC), "fi:shard:b"))
    )
    assert e1.position == 0
    assert e2.position == 1
    # And latest_position now reports 1.
    assert asyncio.run(log.latest_position("test-corpus")) == 1


def test_shacl_rejects_tampered_history_with_duplicate_position() -> None:
    """A history with TWO events at the same position fails the SHACL guard.

    The Protocol contract test in
    ``test_governance_log_protocol_contract.py`` already proves there is no
    public mutator that could produce such a state through legitimate
    means. This test proves that EVEN IF a tampered state arose (e.g. via
    reflection / a future buggy backend), the SHACL guard refuses it —
    the defense-in-depth half.
    """
    tampered_history = [
        ExtractEvent(
            corpus="test-corpus",
            position=0,
            signature=_sig(datetime(2026, 1, 1, tzinfo=UTC)),
            shard_iri="fi:shard:a",
        ),
        ExtractEvent(
            corpus="test-corpus",
            position=0,  # ← DUPLICATE position
            signature=_sig(datetime(2026, 1, 2, tzinfo=UTC)),
            shard_iri="fi:shard:b",
        ),
    ]
    pending = ExtractEvent(
        corpus="test-corpus",
        position=1,
        signature=_sig(datetime(2026, 1, 3, tzinfo=UTC)),
        shard_iri="fi:shard:c",
    )
    result = validate_governance_log_shape(tampered_history, pending)
    assert result.conforms is False
    assert len(result.violations) >= 1


def test_append_refuses_event_that_violates_log_shape() -> None:
    """``append`` re-runs the SHACL gate on every write. An attacker who
    crafts an event with an explicit ``position`` that would create a
    duplicate is refused at the seam (D-06 single write entry)."""
    log = InMemoryGovernanceLog()
    # First append: legitimate.
    asyncio.run(log.append(_event(datetime(2026, 1, 1, tzinfo=UTC), "fi:shard:a")))
    # Second event: explicitly carry position=0 (collides with the first).
    duplicate = ExtractEvent(
        corpus="test-corpus",
        position=0,  # ← explicit collision; bypasses the default -1
        signature=_sig(datetime(2026, 1, 2, tzinfo=UTC)),
        shard_iri="fi:shard:b",
    )
    with pytest.raises(ValueError, match="GovernanceLogShape"):
        asyncio.run(log.append(duplicate))
