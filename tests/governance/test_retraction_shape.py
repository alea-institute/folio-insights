"""SHACL fi:RetractionShape positive + negative polarity tests (07-05b Task 1).

Constraints (per ``governance/shapes/retraction_shape.ttl``):
  * ``fi:shardIri``             — sh:minLength 1 (non-empty).
  * ``fi:cascadePreviewHash``   — sh:minLength 1 + xsd:string (commits the
                                  preview the operator confirmed — D-17).

The Pydantic ``RetractionEvent.cascade_preview_hash: str`` is the first
gate; the SHACL belt at the log layer is the third (governance/retract.py
``validate_retraction`` is the second).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import RetractionEvent
from folio_insights.governance.shape_validation import (
    ValidationResult,
    validate_retraction_shape,
)
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance

CORPUS = "c1"
ALICE = "did:fi:alice"


def _sig() -> AttestedSignature:
    return AttestedSignature(
        did=ALICE,
        action="retract",
        signed_at=datetime(2026, 1, 1, tzinfo=UTC),
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{ALICE}#key-1",
        did_doc_snapshot_at=datetime(2026, 1, 1, tzinfo=UTC),
        verified=None,
    )


# ── POSITIVE ──


def test_valid_retraction_conforms() -> None:
    """A well-formed retraction event conforms.

    cascade_preview_hash is a 64-hex-character SHA-256 hex string in
    production; the SHACL shape requires only non-empty xsd:string.
    """
    event = RetractionEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:to-retract",
        cascade_preview_hash="a" * 64,
    )
    result = validate_retraction_shape(event)
    assert isinstance(result, ValidationResult)
    assert result.conforms is True, f"violations: {result.violations}"


# ── NEGATIVE ──


def test_empty_cascade_preview_hash_refused_by_shape() -> None:
    """Empty cascade_preview_hash triggers the SHACL belt (sh:minLength 1)."""
    event = RetractionEvent.model_construct(
        corpus=CORPUS,
        position=-1,
        signature=_sig(),
        action="retract",
        shard_iri="fi:shard:to-retract",
        cascade_preview_hash="",
    )
    result = validate_retraction_shape(event)
    assert result.conforms is False
    assert len(result.violations) >= 1, (
        "empty cascade_preview_hash MUST yield at least one SHACL violation"
    )


def test_empty_shard_iri_refused_by_shape() -> None:
    """Empty shard_iri triggers the SHACL belt (sh:minLength 1)."""
    event = RetractionEvent.model_construct(
        corpus=CORPUS,
        position=-1,
        signature=_sig(),
        action="retract",
        shard_iri="",
        cascade_preview_hash="a" * 64,
    )
    result = validate_retraction_shape(event)
    assert result.conforms is False
    assert len(result.violations) >= 1
