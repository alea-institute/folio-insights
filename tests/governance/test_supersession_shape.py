"""SHACL fi:SupersessionShape positive + negative polarity tests (07-05a Task 1).

Constraints:
  * ``fi:oldShardIri`` non-empty xsd:string.
  * ``fi:newShardIri`` non-empty xsd:string.
  * old != new (sh:sparql self-join refusal).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import SupersessionEvent
from folio_insights.governance.shape_validation import (
    ValidationResult,
    validate_supersession_shape,
)
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance


CORPUS = "c1"
ALICE = "did:fi:alice"


def _sig() -> AttestedSignature:
    return AttestedSignature(
        did=ALICE,
        action="supersede",
        signed_at=datetime(2026, 1, 1, tzinfo=UTC),
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{ALICE}#key-1",
        did_doc_snapshot_at=datetime(2026, 1, 1, tzinfo=UTC),
        verified=None,
    )


# ── POSITIVE ──


def test_valid_supersession_conforms() -> None:
    """old != new, both non-empty → conforms=True."""
    event = SupersessionEvent(
        corpus=CORPUS,
        signature=_sig(),
        old_shard_iri="fi:shard:old",
        new_shard_iri="fi:shard:new",
    )
    result = validate_supersession_shape(event)
    assert isinstance(result, ValidationResult)
    assert result.conforms is True, f"violations: {result.violations}"


# ── NEGATIVE ──


def test_same_old_and_new_refused_by_shape() -> None:
    """A supersession where old == new is a contradiction (a shard cannot
    supersede itself) → conforms=False via the sh:sparql self-join constraint."""
    event = SupersessionEvent.model_construct(
        corpus=CORPUS,
        position=-1,
        signature=_sig(),
        action="supersede",
        old_shard_iri="fi:shard:same",
        new_shard_iri="fi:shard:same",
    )
    result = validate_supersession_shape(event)
    assert result.conforms is False
    assert len(result.violations) >= 1


def test_empty_new_shard_iri_refused_by_shape() -> None:
    """Empty new_shard_iri triggers the sh:minLength constraint."""
    event = SupersessionEvent.model_construct(
        corpus=CORPUS,
        position=-1,
        signature=_sig(),
        action="supersede",
        old_shard_iri="fi:shard:old",
        new_shard_iri="",
    )
    result = validate_supersession_shape(event)
    assert result.conforms is False
    assert len(result.violations) >= 1
