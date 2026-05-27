"""Authoritative forward-only Pydantic validator confirmation (CONTEXT D-07.1).

Independently confirms that the Plan-01 ``@model_validator`` on ``ShardEnvelope``
is the AUTHORITATIVE forward-only gate (D-07.1) — distinct from the SHACL guard
(``test_shacl_forward_only.py``) which is DEFENSE-IN-DEPTH over the same invariant.

Two-layer division (the reason this test exists separately from the SHACL one):
  * Pydantic ``@model_validator`` = authoritative, always-on; rejects a
    non-monotonic chain at construction (here: via ``model_validate``).
  * pyshacl ``validate_content_edit_shape`` = defense-in-depth, catches records
    that bypassed the validator (``model_construct``).
  * The immutability half (D-08a — no mutation/deletion of a past entry) is
    carried structurally by ContentEdit frozen=True + the IMMUTABLE_FIELD_PATHS
    gate (Plan 02); a stateless validator cannot see a deletion (RESEARCH L115-124).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from folio_insights.shards import SimpleAssertionShard

from tests.shards.conftest import _content_edit, _sample_shard

pytestmark = pytest.mark.shards


def test_ordered_chain_validates() -> None:
    """An ordered (strictly-increasing edited_at) chain passes the validator."""
    shard = _sample_shard(SimpleAssertionShard)
    shard.content_edits.append(
        _content_edit("sense", "s0", "s1", datetime(2026, 2, 1, 12, tzinfo=UTC))
    )
    shard.content_edits.append(
        _content_edit("sense", "s1", "s2", datetime(2026, 3, 1, 12, tzinfo=UTC))
    )
    # Re-validate through the authoritative gate (model_validate re-runs it).
    revalidated = SimpleAssertionShard.model_validate(shard.model_dump())
    assert len(revalidated.content_edits) == 2


def test_non_monotonic_chain_rejected_by_validator() -> None:
    """The authoritative Pydantic validator rejects a back-dated chain (D-07.1).

    Build the dict payload, then ``model_validate`` it — the @model_validator
    fires and raises (forward-only, D-08b)."""
    shard = _sample_shard(SimpleAssertionShard)
    payload = shard.model_dump()
    payload["content_edits"] = [
        _content_edit("sense", "s0", "s1", datetime(2026, 3, 1, 12, tzinfo=UTC)).model_dump(),
        # Back-dated: Feb precedes the Mar predecessor.
        _content_edit("sense", "s1", "s2", datetime(2026, 2, 1, 12, tzinfo=UTC)).model_dump(),
    ]
    with pytest.raises((ValidationError, ValueError)):
        SimpleAssertionShard.model_validate(payload)
