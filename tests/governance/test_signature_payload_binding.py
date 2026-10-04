"""Governance signed-payload v2: signed_at, signer DID and DID-doc snapshot are
bound into ``signature_payload`` (Phase 13 review P1-1). Synthetic keys only."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.governance.cli._signing import sign_and_verify_event
from folio_insights.governance.events import SIGNATURE_PAYLOAD_FORMAT, RoleAssertionEvent
from folio_insights.identity import did_key_from_public
from folio_insights.identity.cache import InMemoryDidDocCache
from folio_insights.shards import AttestedSignature
from folio_insights.storage import verify_event_signature_offline

T0 = datetime(2026, 6, 1, 12, tzinfo=UTC)


def _event(**sig: object) -> RoleAssertionEvent:
    fields = {"did": "did:key:zA", "action": "role_assertion", "signed_at": T0}
    fields.update(sig)
    return RoleAssertionEvent(
        corpus="c",
        signature=AttestedSignature(**fields),  # type: ignore[arg-type]
        subject_did="did:key:zB",
        role="reviewer",
    )


def test_format_marker_is_v2() -> None:
    assert SIGNATURE_PAYLOAD_FORMAT.endswith("/v2")


@pytest.mark.parametrize(
    "change",
    [
        {"signed_at": T0 + timedelta(seconds=1)},
        {"did": "did:key:zOther"},
        {"did_doc_snapshot_at": T0},
    ],
)
def test_bound_signature_fields_change_the_payload(change: dict) -> None:
    assert _event(**change).signature_payload() != _event().signature_payload()


def test_unbound_fields_do_not_change_the_payload() -> None:
    base = _event().signature_payload()
    assert _event(signature="xyz", over_content_hash="0" * 64).signature_payload() == base
    assert _event().model_copy(update={"position": 7}).signature_payload() == base


async def test_cli_helper_signs_the_bound_payload() -> None:
    sk = Ed25519PrivateKey.generate()
    did = did_key_from_public(
        sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
    )
    key_id = f"{did}#{did.removeprefix('did:key:')}"
    # A stale caller placeholder (wrong signed_at) must not leak into the payload.
    event = _event(did=did, signed_at=T0 - timedelta(days=1))
    sig = await sign_and_verify_event(
        event,
        signing_key=sk,
        did=did,
        action="role_assertion",
        signing_key_id=key_id,
        did_doc_snapshot_at=None,
        now=T0,
        cache=InMemoryDidDocCache(),
    )
    signed = event.model_copy(update={"signature": sig})
    assert sig.over_content_hash == signed.signature_payload().decode("utf-8")
    assert await verify_event_signature_offline(signed)
    moved = signed.model_copy(
        update={"signature": sig.model_copy(update={"signed_at": T0 + timedelta(seconds=1)})}
    )
    assert not await verify_event_signature_offline(moved)
