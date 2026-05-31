"""Phase 8 Plan 08-02: Pydantic belt of D-04 two-belt vocab-pin enforcement.

Asserts that ``ShardEnvelope.vocab_version``:
  1. Defaults to the module constant ``VOCAB_VERSION`` via ``default_factory``.
  2. Accepts an explicit matching value and round-trips through ``model_dump()``.
  3. Refuses any value not equal to ``VOCAB_VERSION`` (the Pydantic belt).
  4. Refuses an empty string.

D-03: ``field_validator`` is the first such validator in the codebase; the
existing ``@model_validator(mode='after')`` precedent at
``shards/envelope.py:313`` and ``shards/subtypes.py:105`` was considered
but D-03 calls for ``field_validator`` verbatim.

The SHACL counterpart (``fi:VocabPinShape`` in ``vocab/shapes.ttl``) is
covered by Plan 08-01; this file covers the Pydantic belt only.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from folio_insights.shards import SimpleAssertionShard

# Import the module constant the validator pins against. Plan 08-01 is the
# canonical producer; this test asserts whichever value the source-of-truth
# constant currently carries.
try:
    from folio_insights.vocab import VOCAB_VERSION  # type: ignore
except ImportError:  # pragma: no cover — Plan 08-01 ordering fallback
    from folio_insights.shards.envelope import VOCAB_VERSION  # type: ignore


# Re-use the shards conftest fixture-builder so we get a valid envelope
# without per-test ceremony.
from tests.shards.conftest import _sample_shard  # noqa: E402


def test_default_factory_pins_vocab_version() -> None:
    """D-03: no explicit value → default_factory yields VOCAB_VERSION."""
    shard = _sample_shard(SimpleAssertionShard)
    assert shard.vocab_version == VOCAB_VERSION


def test_explicit_matching_value_accepted_and_round_trips() -> None:
    """D-03: explicit value == VOCAB_VERSION succeeds; round-trips through model_dump."""
    shard = _sample_shard(SimpleAssertionShard, vocab_version=VOCAB_VERSION)
    assert shard.vocab_version == VOCAB_VERSION

    dumped = shard.model_dump()
    assert dumped["vocab_version"] == VOCAB_VERSION

    # Round-trip back through construction.
    rebuilt = SimpleAssertionShard(**dumped)
    assert rebuilt.vocab_version == VOCAB_VERSION


def test_mismatched_value_raises_validation_error() -> None:
    """D-03 / D-04: any value != VOCAB_VERSION raises ValidationError with a
    diagnostic message naming vocab_version, the offending value, and Phase 8.
    """
    bad_value = "2026.04.0"
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(SimpleAssertionShard, vocab_version=bad_value)

    err_text = str(exc_info.value)
    assert "vocab_version" in err_text
    assert bad_value in err_text
    # The message must cite Phase 8 (or the VOCAB_VERSION constant by name)
    # so a downstream operator can locate the policy decision.
    assert "Phase 8" in err_text or "VOCAB_VERSION" in err_text


def test_empty_string_raises_validation_error() -> None:
    """D-03: vocab_version="" is a mismatched value; validator must refuse."""
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(SimpleAssertionShard, vocab_version="")

    err_text = str(exc_info.value)
    assert "vocab_version" in err_text


def test_module_constant_is_2026_05_0() -> None:
    """Sanity gate: Phase 8 ships VOCAB_VERSION = '2026.05.0' (D-02)."""
    assert VOCAB_VERSION == "2026.05.0"
