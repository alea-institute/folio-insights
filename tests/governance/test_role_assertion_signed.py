"""End-to-end signed RoleAssertion test (Test 14 from PLAN 07-04a).

Genesis admin signs a RoleAssertion granting reviewer to another DID;
``verify_attestation`` succeeds; ``log.append(role_event)`` succeeds;
``active_roles_at(corpus, now)`` returns the expected role map.

This is the integration test that proves the substrate plumbing:
  - keys.py keystore + signer.py sign_attestation
  - DidDocCache + verifier.verify_attestation
  - governance log.append (Phase 6 belt-and-suspenders signature gate)
  - active_roles_at windowed query
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from folio_insights.governance.events import RoleAssertionEvent
from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.governance.roles import active_roles_at
from folio_insights.identity.cache import (
    DidDocSnapshot,
    InMemoryDidDocCache,
)
from folio_insights.identity.signer import sign_attestation
from folio_insights.identity.verifier import verify_attestation

# Try to import real ed25519 keygen / did:key helpers.
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

pytestmark = pytest.mark.governance


CORPUS = "c1"


def _make_did_key() -> tuple[Ed25519PrivateKey, str, str]:
    """Generate an ed25519 keypair and a synthetic did:key.

    Returns (private_key, did, public_key_multibase).
    """
    from cryptography.hazmat.primitives import serialization

    from folio_insights.identity.keys import did_key_from_public

    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key()
    raw_pub = pk.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    did = did_key_from_public(raw_pub)
    multibase = did.removeprefix("did:key:")
    return sk, did, multibase


@pytest.mark.asyncio
async def test_role_assertion_signed_end_to_end() -> None:
    """Genesis admin signs a RoleAssertion granting reviewer to another DID;
    verify_attestation succeeds; log.append succeeds; active_roles_at returns
    the expected role map."""
    log = InMemoryGovernanceLog()
    cache = InMemoryDidDocCache()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)

    # Alice (genesis admin).
    alice_sk, alice_did, alice_mb = _make_did_key()
    # Bob (new reviewer).
    _, bob_did, _ = _make_did_key()

    # Seed the DidDocCache with Alice's snapshot at t0 (so verify_attestation
    # can resolve the signing-time key).
    await cache.put(
        (alice_did, t0),
        DidDocSnapshot(
            did=alice_did,
            fetched_at=t0,
            verification_method_id=f"{alice_did}#key-1",
            public_key_multibase=alice_mb,
        ),
    )

    # Genesis bootstrap: Alice self-signs corpus_admin (carve-out — no signature
    # verification at log layer for genesis).
    genesis_sig = sign_attestation(
        content_hash="0" * 64,  # placeholder for genesis
        signing_key=alice_sk,
        did=alice_did,
        action="role_assertion",
        signing_key_id=f"{alice_did}#key-1",
        did_doc_snapshot_at=t0,
        now=t0,
    )
    genesis = RoleAssertionEvent(
        corpus=CORPUS,
        signature=genesis_sig,
        subject_did=alice_did,
        role="corpus_admin",
    )
    await log.append(genesis)

    # Now Alice signs a RoleAssertion granting Bob reviewer. The signature is
    # over the event's signature_payload (JCS-canonical hash of content sans
    # signature).
    payload_hash = RoleAssertionEvent(
        corpus=CORPUS,
        position=1,
        signature=genesis_sig,  # placeholder; will be replaced
        subject_did=bob_did,
        role="reviewer",
    ).signature_payload().hex()

    bob_sig = sign_attestation(
        content_hash=payload_hash,
        signing_key=alice_sk,
        did=alice_did,
        action="role_assertion",
        signing_key_id=f"{alice_did}#key-1",
        did_doc_snapshot_at=t0,
        now=t0,
    )
    bob_event = RoleAssertionEvent(
        corpus=CORPUS,
        position=1,
        signature=bob_sig,
        subject_did=bob_did,
        role="reviewer",
    )

    # Verify the signature independently (Phase 6 contract).
    verified = await verify_attestation(payload_hash, bob_sig, cache=cache)
    assert verified is True

    # Append goes through log.append which calls verify_attestation internally
    # for non-genesis role events.
    await log.append(bob_event)

    # active_roles_at at t0.5 returns the expected map.
    t05 = datetime(2026, 1, 1, 12, tzinfo=UTC)
    roles = await active_roles_at(CORPUS, t05, log=log)
    assert "corpus_admin" in roles.get(alice_did, set())
    assert "reviewer" in roles.get(bob_did, set())
