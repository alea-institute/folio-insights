"""GOV-05 explicit-rejection: no majority-vote resolution path (07-05a Task 1).

The 3 resolution paths are LOCKED at three layers:

  1. Pydantic ``ContestResolutionEvent.resolution_path`` is a 3-value Literal.
     A 4th value (``"majority"``) raises ``ValidationError`` at construction.

  2. SHACL ``fi:ContestResolutionShape`` has ``sh:in ("arbiter" "distinguo"
     "aporetic")`` on ``fi:resolutionPath`` — the SHACL belt refuses any
     non-3-Literal value materialized via ``model_construct`` (bypassing
     Pydantic).

  3. The Literal vocabulary itself is asserted via ``get_args()`` so a 5th
     value added to the Literal would still trip the structural check.

If anyone tries to add a 4th resolution path (e.g. ``"majority"``), at least
one of these 3 gates will fail. Future expansion requires an ADR.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import get_args

import pytest
from pydantic import ValidationError

from folio_insights.governance.resolve_contest import (
    ContestResolutionEvent,
    validate_contest_resolution,
)
from folio_insights.governance.shape_validation import (
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


# ── Test 1: Literal vocabulary structural check ──


def test_resolution_path_literal_has_exactly_three_values() -> None:
    """get_args() over the resolution_path Literal returns exactly the 3-value set.

    A change to ``ContestResolutionPath`` that adds (or removes) a value would
    flip this assertion. Adding ``"majority"`` is the canonical GOV-05
    regression this test catches.
    """
    rp_literal = ContestResolutionEvent.model_fields["resolution_path"].annotation
    assert set(get_args(rp_literal)) == {"arbiter", "distinguo", "aporetic"}


# ── Test 2: Pydantic refuses ``"majority"`` at construction ──


def test_majority_resolution_path_raises_pydantic_validation_error() -> None:
    """Constructing a ContestResolutionEvent with ``resolution_path="majority"``
    raises Pydantic ``ValidationError`` (the Literal narrowing is the first gate)."""
    with pytest.raises(ValidationError):
        ContestResolutionEvent(
            corpus=CORPUS,
            signature=_sig(),
            shard_iri="fi:shard:abc",
            resolution_path="majority",  # type: ignore[arg-type]
        )


# ── Test 3: SHACL belt refuses ``"majority"`` even if Pydantic is bypassed ──


def test_majority_resolution_path_refused_by_shacl_belt() -> None:
    """``validate_contest_resolution_shape`` on an event built via
    ``model_construct`` (bypassing Pydantic) returns ``conforms=False``.

    This is the defense-in-depth second line: even if a future change relaxes
    the Pydantic Literal, the SHACL ``sh:in`` constraint still refuses any
    non-3-Literal resolution_path.
    """
    event = ContestResolutionEvent.model_construct(
        corpus=CORPUS,
        position=-1,
        signature=_sig(),
        action="resolve_contest",
        shard_iri="fi:shard:abc",
        resolution_path="majority",  # bypassing Pydantic
    )
    result = validate_contest_resolution_shape(event)
    assert result.conforms is False
    assert len(result.violations) >= 1


# ── Test 4: validator function refuses an unresolvable shard_iri ──


def test_validator_refuses_contest_resolution_for_uncontested_shard() -> None:
    """``validate_contest_resolution`` refuses if the shard has no prior
    ContestEvent in the log history (you cannot resolve what was not contested)."""
    from folio_insights.governance.log import InMemoryGovernanceLog

    log = InMemoryGovernanceLog()
    # No prior contest — resolution should refuse.
    event = ContestResolutionEvent(
        corpus=CORPUS,
        signature=_sig(),
        shard_iri="fi:shard:never-contested",
        resolution_path="arbiter",
    )
    import asyncio

    with pytest.raises(ValueError, match="no prior ContestEvent"):
        asyncio.run(validate_contest_resolution(event, log=log))
