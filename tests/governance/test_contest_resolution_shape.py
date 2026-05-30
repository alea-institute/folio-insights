"""SHACL fi:ContestResolutionShape positive + negative polarity tests (07-05a Task 1).

Constraints:
  * ``fi:resolutionPath`` is one of {arbiter, distinguo, aporetic} (GOV-05 lock).
  * ``fi:shardIri`` non-empty xsd:string.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import ContestResolutionEvent
from folio_insights.governance.shape_validation import (
    ValidationResult,
    validate_contest_resolution_shape,
)
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"


def _sig() -> AttestedSignature:
    return AttestedSignature(
        did=ALICE,
        action="resolve_contest",
        signed_at=datetime(2026, 1, 1, tzinfo=UTC),
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{ALICE}#key-1",
        did_doc_snapshot_at=datetime(2026, 1, 1, tzinfo=UTC),
        verified=None,
    )


# ── POSITIVE (3 paths) ──


@pytest.mark.parametrize("path", ["arbiter", "distinguo", "aporetic"])
def test_valid_resolution_path_conforms(path: str) -> None:
    """Each of the 3 GOV-05 resolution paths conforms."""
    event = ContestResolutionEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:resolved",
        resolution_path=path,  # type: ignore[arg-type]
    )
    result = validate_contest_resolution_shape(event)
    assert isinstance(result, ValidationResult)
    assert result.conforms is True, f"violations: {result.violations}"


# ── NEGATIVE ──


def test_bogus_resolution_path_refused_by_shape() -> None:
    """A 4th resolution_path value (bypassing Pydantic) → conforms=False.

    The SHACL belt is the GOV-05 second line — adding a 4th value to the
    Literal would still fail this constraint until someone also rewrites the
    TTL ``sh:in`` clause (intentionally hard, requires an ADR).
    """
    event = ContestResolutionEvent.model_construct(
        corpus=CORPUS,
        position=-1,
        signature=_sig(),
        action="resolve_contest",
        shard_iri="fi:shard:resolved",
        resolution_path="majority",  # forbidden value
    )
    result = validate_contest_resolution_shape(event)
    assert result.conforms is False
    assert len(result.violations) >= 1
