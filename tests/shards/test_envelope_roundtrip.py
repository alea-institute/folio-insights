"""Envelope round-trip + bitemporal + frozen-field regression tests.

Covers SHARD-01 exit criterion 1 (``Shard(**shard.model_dump()) == shard``
round-trips for every subtype), SHARD-10 (bitemporal round-trip), and
CONTEXT D-07 (6 frozen identity fields raise on assignment).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from folio_insights.shards import (
    ShardEnvelope,
    SimpleAssertionShard,
)

from tests.shards.conftest import _SUBTYPE_TABLE, _sample_shard

pytestmark = pytest.mark.shards


# ── SHARD-01 exit criterion 1: round-trip for every subtype ──


@pytest.mark.parametrize("tag,cls", _SUBTYPE_TABLE)
def test_shard_round_trip_model_dump(tag: str, cls: type[ShardEnvelope]) -> None:
    """SubtypeCls(**shard.model_dump()) == shard for all 5 subtypes (SHARD-01)."""
    original = _sample_shard(cls)
    dumped = original.model_dump()
    assert dumped["shard_type"] == tag
    reconstructed = cls(**dumped)
    assert reconstructed == original


@pytest.mark.parametrize("tag,cls", _SUBTYPE_TABLE)
def test_shard_round_trip_json(tag: str, cls: type[ShardEnvelope]) -> None:
    """JSON round-trip preserves all envelope fields + bitemporal triplet."""
    original = _sample_shard(cls)
    payload = original.model_dump_json()
    parsed = json.loads(payload)
    assert parsed["shard_type"] == tag
    reconstructed = cls.model_validate_json(payload)
    assert reconstructed == original


# ── SHARD-10: bitemporal round-trip (D-03, D-04, D-12) ──


def test_bitemporal_null_unbounded_round_trip() -> None:
    """D-03: valid_time_start=None, valid_time_end=None round-trip as JSON null."""
    shard = _sample_shard(
        SimpleAssertionShard,
        valid_time_start=None,
        valid_time_end=None,
    )
    parsed = json.loads(shard.model_dump_json())
    assert parsed["valid_time_start"] is None
    assert parsed["valid_time_end"] is None
    rehydrated = SimpleAssertionShard.model_validate_json(shard.model_dump_json())
    assert rehydrated.valid_time_start is None
    assert rehydrated.valid_time_end is None


def test_bitemporal_bounded_round_trip() -> None:
    """Non-null valid_time_start/end serialize as ISO-8601 strings (D-12)."""
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2030, 12, 31, tzinfo=UTC)
    shard = _sample_shard(
        SimpleAssertionShard,
        valid_time_start=start,
        valid_time_end=end,
    )
    parsed = json.loads(shard.model_dump_json())
    # Accept both `Z` suffix and `+00:00` tz-offset forms (Pydantic version variance).
    assert parsed["valid_time_start"].startswith("2025-01-01T00:00:00")
    assert parsed["valid_time_end"].startswith("2030-12-31T00:00:00")
    rehydrated = SimpleAssertionShard.model_validate_json(shard.model_dump_json())
    assert rehydrated.valid_time_start == start
    assert rehydrated.valid_time_end == end


def test_transaction_time_default_is_tz_aware_utc() -> None:
    """D-04: default_factory produces a tz-aware UTC datetime."""
    shard = _sample_shard(SimpleAssertionShard)
    assert shard.transaction_time.tzinfo is not None
    assert shard.transaction_time.utcoffset().total_seconds() == 0


def test_transaction_time_round_trip() -> None:
    """transaction_time serializes + reparses losslessly (D-12)."""
    shard = _sample_shard(SimpleAssertionShard)
    rehydrated = SimpleAssertionShard.model_validate_json(shard.model_dump_json())
    assert rehydrated.transaction_time == shard.transaction_time


# ── D-07: 6 frozen identity fields raise on assignment ──


@pytest.mark.parametrize("field_name", [
    "shard_iri", "provenance_hash", "source_uri",
    "source_span", "extracted_at", "first_extractor_did",
])
def test_identity_fields_are_frozen(field_name: str) -> None:
    # D-07 fields: "shard_iri", "provenance_hash", "source_uri", "source_span", "extracted_at", "first_extractor_did"
    """D-07 — each of the 6 frozen identity fields raises ValidationError on assignment."""
    shard = _sample_shard(SimpleAssertionShard)
    with pytest.raises(ValidationError, match="frozen"):
        setattr(shard, field_name, "whatever")


# ── extra="forbid" regression guard ──


def test_extra_field_rejected() -> None:
    """ConfigDict(extra='forbid'): unknown fields raise ValidationError."""
    payload = _sample_shard(SimpleAssertionShard).model_dump()
    payload["unknown_field"] = "nope"
    with pytest.raises(ValidationError):
        SimpleAssertionShard.model_validate(payload)
