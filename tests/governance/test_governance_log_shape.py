"""SHACL fi:GovernanceLogShape positive + negative polarity tests (Phase 7 D-05).

The amended D-05 in-phase append-only gate has TWO halves:

  (a) `fi:GovernanceLogShape` SHACL refuses duplicate positions, signed_at
      moving backward with position, and gaps in the position sequence (the
      structural signature of a deletion under an append-only invariant).
  (b) The Protocol-level contract test (see
      ``tests/governance/test_governance_log_protocol_contract.py``) asserts
      no public mutation API exists on ``InMemoryGovernanceLog`` beyond
      ``append``.

This file owns part (a). Mirrors ``tests/revision/test_shacl_forward_only.py``
polarity-pair structure (the Phase 5 precedent). The TTL itself was modelled
on ``src/folio_insights/revision/content_edit_shape.ttl`` — both shapes use
the ``sh:sparql`` self-join polarity discipline (the SELECT matches the BAD
case so a non-empty result set yields ``conforms=False``).

Boundary: this test imports ``validate_governance_log_shape`` from
``governance/shape_validation.py`` — the LONE exempt module under
``governance/`` allowed to import rdflib/pyshacl (D-04). The events
themselves are stdlib + Pydantic only.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import ExtractEvent
from folio_insights.governance.shape_validation import (
    ValidationResult,
    validate_governance_log_shape,
)
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


def _sig(signed_at: datetime, did: str = "did:fi:alice") -> AttestedSignature:
    """Build a minimal AttestedSignature for embedding inside test events."""
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


def _event(position: int, signed_at: datetime, shard_iri: str = "fi:shard:s") -> ExtractEvent:
    """Build an ExtractEvent at the given position with the given signed_at."""
    return ExtractEvent(
        corpus="test-corpus",
        position=position,
        signature=_sig(signed_at),
        shard_iri=shard_iri,
    )


# ── Positive polarity ────────────────────────────────────────────────────


def test_monotonic_history_conforms() -> None:
    """A history of 3 events at positions 0,1,2 with strictly-increasing
    signed_at, plus a new event at position 3 → conforms=True (no violations).
    """
    history = [
        _event(0, datetime(2026, 1, 1, tzinfo=UTC), "fi:shard:a"),
        _event(1, datetime(2026, 1, 2, tzinfo=UTC), "fi:shard:b"),
        _event(2, datetime(2026, 1, 3, tzinfo=UTC), "fi:shard:c"),
    ]
    new_event = _event(3, datetime(2026, 1, 4, tzinfo=UTC), "fi:shard:d")
    result = validate_governance_log_shape(history, new_event)
    assert isinstance(result, ValidationResult)
    assert result.conforms is True, f"violations: {result.violations}"
    assert result.violations == []


def test_empty_history_with_genesis_conforms() -> None:
    """An empty history with a position-0 event also conforms (the genesis case)."""
    new_event = _event(0, datetime(2026, 1, 1, tzinfo=UTC), "fi:shard:a")
    result = validate_governance_log_shape([], new_event)
    assert result.conforms is True
    assert result.violations == []


# ── Negative polarity (3 cases mirroring the 3 SHACL constraints) ────────


def test_duplicate_position_rejected() -> None:
    """Two events at the same position → conforms=False (monotonic + gap-free
    violation; mirrors D-05 sh:message)."""
    history = [
        _event(0, datetime(2026, 1, 1, tzinfo=UTC), "fi:shard:a"),
        _event(1, datetime(2026, 1, 2, tzinfo=UTC), "fi:shard:b"),
    ]
    # New event at position 1 collides with the existing position-1 event.
    new_event = _event(1, datetime(2026, 1, 3, tzinfo=UTC), "fi:shard:c")
    result = validate_governance_log_shape(history, new_event)
    assert result.conforms is False
    assert len(result.violations) >= 1
    assert any(
        "monotonic" in v.lower() or "gap-free" in v.lower() or "append-only" in v.lower()
        for v in result.violations
    ), f"expected monotonic/gap-free/append-only message; got: {result.violations}"


def test_signed_at_goes_backward_rejected() -> None:
    """A later-positioned event with an earlier signed_at than a smaller
    position → conforms=False (back-dating violation)."""
    history = [
        _event(0, datetime(2026, 1, 1, tzinfo=UTC), "fi:shard:a"),
    ]
    # Position 1 but signed_at BEFORE position 0 → back-dating.
    new_event = _event(1, datetime(2025, 12, 31, tzinfo=UTC), "fi:shard:b")
    result = validate_governance_log_shape(history, new_event)
    assert result.conforms is False
    assert len(result.violations) >= 1
    assert any(
        "monotonically non-decreasing" in v.lower() or "signed" in v.lower()
        for v in result.violations
    ), f"expected signed_at monotonicity message; got: {result.violations}"


def test_position_gap_rejected() -> None:
    """A history with a gap (positions 0, 1) followed by a new event at
    position 3 (skipping 2) → conforms=False (gap = deletion signature)."""
    history = [
        _event(0, datetime(2026, 1, 1, tzinfo=UTC), "fi:shard:a"),
        _event(1, datetime(2026, 1, 2, tzinfo=UTC), "fi:shard:b"),
    ]
    # New event at position 3 (skipping 2) → gap.
    new_event = _event(3, datetime(2026, 1, 3, tzinfo=UTC), "fi:shard:c")
    result = validate_governance_log_shape(history, new_event)
    assert result.conforms is False
    assert len(result.violations) >= 1
    assert any(
        "gap" in v.lower() or "deletion" in v.lower() or "monotonic" in v.lower()
        for v in result.violations
    ), f"expected gap message; got: {result.violations}"
