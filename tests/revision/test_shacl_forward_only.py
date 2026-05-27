"""SHACL forward-only guard — exit criterion 2 (CONTEXT D-07.2 / D-08b).

Tests the literal "SHACL guard": ``validate_content_edit_shape`` runs a REAL
pyshacl shape over the edit chain. Both polarities are asserted (RESEARCH
Pitfall 1, L365-369): an ORDERED chain conforms, a BACK-DATED chain does not.

Two-layer division (mirrored in the validator-confirmation test next door):
  * The Pydantic ``@model_validator`` (Plan 05-01) is the AUTHORITATIVE, always-on
    forward-only gate — it rejects a back-dated chain AT CONSTRUCTION. To exercise
    the SHACL guard's negative polarity we must therefore BYPASS that validator
    (``model_construct``), which is exactly the records-loaded-out-of-band case the
    defense-in-depth shape exists to catch.
  * The SHACL shape here is DEFENSE-IN-DEPTH over the same forward-only invariant.
  * The immutability half (D-08a) is NOT SHACL-enforceable (stateless over one
    snapshot, RESEARCH L115-124) — it is carried by ContentEdit frozen=True + the
    IMMUTABLE_FIELD_PATHS gate (Plan 02), not by this shape.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.revision.shape_validation import validate_content_edit_shape
from folio_insights.shards import SimpleAssertionShard

from tests.shards.conftest import _content_edit, _sample_shard

pytestmark = pytest.mark.shards


def _ordered_chain() -> SimpleAssertionShard:
    """A shard with a strictly-increasing edited_at chain (positive polarity)."""
    shard = _sample_shard(SimpleAssertionShard)
    shard.content_edits.append(
        _content_edit("sense", "s0", "s1", datetime(2026, 2, 1, 12, tzinfo=UTC))
    )
    shard.content_edits.append(
        _content_edit("sense", "s1", "s2", datetime(2026, 3, 1, 12, tzinfo=UTC))
    )
    shard.content_edits.append(
        _content_edit("sense", "s2", "s3", datetime(2026, 4, 1, 12, tzinfo=UTC))
    )
    return shard


def _back_dated_chain() -> SimpleAssertionShard:
    """A shard whose 3rd edit predates its predecessor (negative polarity).

    The Plan-01 @model_validator would reject this at construction, so build the
    object via ``model_construct`` to BYPASS the validator — the bypassed-record
    case the defense-in-depth SHACL guard exists to catch. We mint a valid shard
    first, then construct a copy whose content_edits carries the back-dated entry.
    """
    valid = _sample_shard(SimpleAssertionShard)
    edits = [
        _content_edit("sense", "s0", "s1", datetime(2026, 2, 1, 12, tzinfo=UTC)),
        _content_edit("sense", "s1", "s2", datetime(2026, 3, 1, 12, tzinfo=UTC)),
        # Back-dated: Jan precedes the Mar predecessor -> forward-only violation.
        _content_edit("sense", "s2", "s3", datetime(2026, 1, 1, 12, tzinfo=UTC)),
    ]
    data = valid.model_dump()
    data["content_edits"] = edits
    return SimpleAssertionShard.model_construct(**data)


def test_ordered_chain_conforms() -> None:
    """Positive polarity: a monotonic chain passes the SHACL guard (conforms=True)."""
    result = validate_content_edit_shape(_ordered_chain())
    assert result.conforms is True
    assert result.violations == []


def test_back_dated_chain_rejected() -> None:
    """Negative polarity (exit criterion 2): the SHACL guard rejects an edit to a
    past version — a back-dated insert makes conforms=False with a violation."""
    result = validate_content_edit_shape(_back_dated_chain())
    assert result.conforms is False
    assert len(result.violations) >= 1
    # The shape's sh:message names the forward-only violation.
    assert any("forward-only" in v.lower() for v in result.violations)


def test_empty_chain_conforms() -> None:
    """A shard with no edits trivially conforms (no adjacent pair to violate)."""
    result = validate_content_edit_shape(_sample_shard(SimpleAssertionShard))
    assert result.conforms is True
