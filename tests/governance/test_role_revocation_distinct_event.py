"""RoleRevocationEvent is a structurally distinct Pydantic class (D-13 / F6).

D-13 closes F6 ("role revocation cannot be a flag on RoleAssertion") by making
``RoleRevocationEvent`` a separate class in the ``GovernanceEvent`` discriminated
union — different ``action`` Literal pin, different field set
(``revoked_role`` vs ``role``). The discriminator dispatches via
``pydantic.TypeAdapter``.
"""
from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from folio_insights.governance.events import (
    GovernanceEvent,
    RoleAssertionEvent,
    RoleRevocationEvent,
)

pytestmark = pytest.mark.governance


_ADAPTER = TypeAdapter(GovernanceEvent)


def test_role_revocation_event_is_distinct_class_from_role_assertion(
    attested_signature_factory,
) -> None:
    """D-13: RoleRevocationEvent and RoleAssertionEvent are different classes."""
    assert_event = RoleAssertionEvent(
        corpus="c1",
        signature=attested_signature_factory(action="role_assertion"),
        subject_did="did:fi:bob",
        role="reviewer",
    )
    rev_event = RoleRevocationEvent(
        corpus="c1",
        signature=attested_signature_factory(action="role_revocation"),
        subject_did="did:fi:bob",
        revoked_role="reviewer",
    )
    assert type(rev_event) is not type(assert_event)
    # Structural distinctness: different field NAMES on each side.
    assert hasattr(assert_event, "role")
    assert hasattr(rev_event, "revoked_role")
    assert not hasattr(assert_event, "revoked_role")
    assert not hasattr(rev_event, "role")


def test_discriminated_union_dispatches_role_revocation(
    attested_signature_factory,
) -> None:
    """D-06: TypeAdapter dispatches ``action='role_revocation'`` → RoleRevocationEvent."""
    payload = {
        "action": "role_revocation",
        "corpus": "c1",
        "signature": attested_signature_factory(action="role_revocation").model_dump(),
        "subject_did": "did:fi:bob",
        "revoked_role": "reviewer",
    }
    parsed = _ADAPTER.validate_python(payload)
    assert isinstance(parsed, RoleRevocationEvent)
    assert not isinstance(parsed, RoleAssertionEvent)
    assert parsed.revoked_role == "reviewer"


def test_discriminated_union_dispatches_role_assertion(
    attested_signature_factory,
) -> None:
    """D-06: TypeAdapter dispatches ``action='role_assertion'`` → RoleAssertionEvent."""
    payload = {
        "action": "role_assertion",
        "corpus": "c1",
        "signature": attested_signature_factory(action="role_assertion").model_dump(),
        "subject_did": "did:fi:bob",
        "role": "reviewer",
    }
    parsed = _ADAPTER.validate_python(payload)
    assert isinstance(parsed, RoleAssertionEvent)
    assert not isinstance(parsed, RoleRevocationEvent)
    assert parsed.role == "reviewer"


def test_discriminated_union_unknown_action_raises(attested_signature_factory) -> None:
    """D-06: unknown ``action`` tag fails with a discriminator error."""
    payload = {
        "action": "nonsense_action",
        "corpus": "c1",
        "signature": attested_signature_factory(action="role_assertion").model_dump(),
        "subject_did": "did:fi:bob",
        "role": "reviewer",
    }
    with pytest.raises(ValidationError) as exc_info:
        _ADAPTER.validate_python(payload)
    msg = str(exc_info.value)
    assert "action" in msg or "discriminator" in msg.lower()


def test_extra_fields_forbidden_on_event(attested_signature_factory) -> None:
    """ConfigDict(extra='forbid') propagates to event classes."""
    payload = {
        "action": "role_revocation",
        "corpus": "c1",
        "signature": attested_signature_factory(action="role_revocation").model_dump(),
        "subject_did": "did:fi:bob",
        "revoked_role": "reviewer",
        "unknown_field": "boom",
    }
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(payload)


def test_role_revocation_round_trip_through_union(
    attested_signature_factory,
) -> None:
    """Round-trip: dump → validate_json → equal instance through discriminator."""
    original = RoleRevocationEvent(
        corpus="c1",
        signature=attested_signature_factory(action="role_revocation"),
        subject_did="did:fi:bob",
        revoked_role="arbiter",
    )
    payload_json = original.model_dump_json()
    parsed = _ADAPTER.validate_json(payload_json)
    assert isinstance(parsed, RoleRevocationEvent)
    assert parsed.subject_did == original.subject_did
    assert parsed.revoked_role == original.revoked_role
    assert parsed.corpus == original.corpus
