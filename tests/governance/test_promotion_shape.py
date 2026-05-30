"""SHACL fi:PromotionShape positive + negative polarity tests (07-04b Task 1).

The SHACL belt validates structural constraints D-20 cannot fully enforce in
Python alone:
  * ``fi:newStatus`` must be one of the 3-Literal set.
  * ``fi:citedIri`` must appear at least once (sh:minCount 1).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import PromotionEvent
from folio_insights.governance.shape_validation import (
    ValidationResult,
    validate_promotion_shape,
)
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"


def _sig() -> AttestedSignature:
    return AttestedSignature(
        did=ALICE,
        action="promote",
        signed_at=datetime(2026, 1, 1, tzinfo=UTC),
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{ALICE}#key-1",
        did_doc_snapshot_at=datetime(2026, 1, 1, tzinfo=UTC),
        verified=None,
    )


# ── POSITIVE ──


def test_valid_promotion_conforms() -> None:
    """A promotion with a non-empty cited_iris and a valid status → conforms=True."""
    event = PromotionEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:promoted",
        new_status="demonstrable",
        cited_iris=["fi:shard:cited"],
    )
    result = validate_promotion_shape(event)
    assert isinstance(result, ValidationResult)
    assert result.conforms is True, f"violations: {result.violations}"


# ── NEGATIVE: empty cited_iris (D-20 SHACL belt) ──


def test_empty_cited_iris_refused_by_shape() -> None:
    """SHACL sh:minCount 1 on fi:citedIri → conforms=False when empty.

    Pydantic refuses construction with ``cited_iris=[]`` (Field min_length=1);
    to exercise the SHACL belt we build the event WITH a single citation, then
    manipulate the materialized data graph indirectly by validating an event
    whose ``cited_iris`` we cannot legitimately empty. Instead we exercise the
    SHACL polarity for the NEW_STATUS constraint (next test) — the cited_iris
    SHACL belt is the second line; Pydantic is the first.

    This test verifies that the SHACL shape's sh:minCount on fi:citedIri is
    LOADED and active by checking via a constructed graph mismatch path.
    """
    # Build a valid promotion; then verify the shape rejects a deliberately-
    # mangled data graph. To exercise the cited_iris belt, we monkey-patch
    # the event's cited_iris after construction by going through model_copy
    # with an unsafe path — this is contrived but the cited_iris SHACL belt
    # is genuine defense-in-depth.
    event = PromotionEvent.model_construct(
        corpus=CORPUS,
        position=-1,
        signature=_sig(),
        action="promote",
        shard_iri="fi:shard:promoted",
        new_status="demonstrable",
        cited_iris=[],  # bypassing Pydantic validation via model_construct
    )
    result = validate_promotion_shape(event)
    assert result.conforms is False
    assert len(result.violations) >= 1


# ── NEGATIVE: invalid new_status (D-21 SHACL belt) ──


def test_invalid_new_status_refused_by_shape() -> None:
    """SHACL sh:in on fi:newStatus → conforms=False when status outside the 3-Literal set."""
    event = PromotionEvent.model_construct(
        corpus=CORPUS,
        position=-1,
        signature=_sig(),
        action="promote",
        shard_iri="fi:shard:promoted",
        new_status="bogus",  # outside the 3-Literal set
        cited_iris=["fi:shard:cited"],
    )
    result = validate_promotion_shape(event)
    assert result.conforms is False
    assert len(result.violations) >= 1
