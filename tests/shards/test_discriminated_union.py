"""Discriminated-union tests (SHARD-01 exit criterion 2; CONTEXT D-05 / D-06).

``TypeAdapter(Shard)`` dispatches on the ``shard_type`` tag; unknown tag
raises ``pydantic.ValidationError``. Each subtype's pinned Literal default
rejects foreign tags at direct-construction time.
"""
from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from folio_insights.shards import (
    Shard,
    SimpleAssertionShard,
)

from tests.shards.conftest import _SUBTYPE_TABLE, _sample_shard

pytestmark = pytest.mark.shards

_ADAPTER = TypeAdapter(Shard)


@pytest.mark.parametrize("tag,cls", _SUBTYPE_TABLE)
def test_adapter_dispatches_each_subtype(tag: str, cls: type) -> None:
    """TypeAdapter(Shard) returns the correct subtype class for each tag."""
    payload = _sample_shard(cls).model_dump()
    parsed = _ADAPTER.validate_python(payload)
    assert isinstance(parsed, cls)
    assert parsed.shard_type == tag


def test_invalid_shard_type_raises_validation_error() -> None:
    """D-05: unknown shard_type tag fails with a useful error message."""
    payload = _sample_shard(SimpleAssertionShard).model_dump()
    payload["shard_type"] = "nonsense"
    with pytest.raises(ValidationError) as exc_info:
        _ADAPTER.validate_python(payload)
    msg = str(exc_info.value)
    assert "shard_type" in msg
    # Either the bad tag or the word "discriminator" — phrasing varies across
    # Pydantic minor versions.
    assert "nonsense" in msg or "discriminator" in msg.lower()


def test_subtype_pinned_literal_rejects_foreign_tag() -> None:
    """D-06: each subtype's Literal default rejects any other tag at construction."""
    payload = _sample_shard(SimpleAssertionShard).model_dump()
    payload["shard_type"] = "gloss"  # wrong tag for SimpleAssertionShard
    with pytest.raises(ValidationError):
        SimpleAssertionShard.model_validate(payload)
