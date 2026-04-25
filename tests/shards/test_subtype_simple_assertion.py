"""Phase 03 SimpleAssertionShard (REQ SHARD-02; PRD §6.2.1 Example A.1).

Covers exit criterion 1 (A.1 round-trips) for the empty subtype that ships
no §6.2-specific fields (CONTEXT D-01).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from folio_insights.shards import (
    Shard,
    SimpleAssertionShard,
)

from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.shards

_FIXTURE = Path(__file__).parent / "fixtures" / "example_a1_simple_assertion.json"


def test_a1_fixture_round_trips() -> None:
    """PRD §6.2.1 Example A.1 round-trips via TypeAdapter(Shard) (SHARD-02 exit 1)."""
    payload = json.loads(_FIXTURE.read_text())
    parsed = TypeAdapter(Shard).validate_python(payload)
    assert isinstance(parsed, SimpleAssertionShard)
    assert parsed.shard_type == "simple_assertion"
    # Bidirectional round-trip via mode='json' so datetime → ISO string aligns
    # with the JSON fixture representation.
    redumped = parsed.model_dump(mode="json")
    assert redumped == payload


def test_simple_assertion_constructs_via_sample_shard() -> None:
    """SimpleAssertionShard requires no Phase 3 fields beyond envelope (D-01)."""
    shard = _sample_shard(SimpleAssertionShard)
    assert shard.shard_type == "simple_assertion"


def test_extra_field_rejected() -> None:
    """ConfigDict(extra='forbid') inherited from ShardEnvelope: unknown fields raise."""
    payload = _sample_shard(SimpleAssertionShard).model_dump()
    payload["unknown_field"] = "nope"
    with pytest.raises(ValidationError):
        SimpleAssertionShard.model_validate(payload)
