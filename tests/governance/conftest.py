"""Shared fixtures for tests/governance (Phase 7, Wave 0).

Provides:
  * ``genesis_did`` — fixed did:key string used by tests as the genesis signer.
  * ``attested_signature_factory`` — factory callable returning a valid
    ``AttestedSignature`` instance for embedding inside test events. Mirrors the
    "factory fixture" idiom used by ``tests/identity/conftest.py``.
  * ``sample_role_assertion`` — factory building a ``RoleAssertionEvent``.

Kept stdlib + Pydantic-shaped only — no rdflib/aiosqlite/pyoxigraph imports
(D-04 boundary; ``tests/governance/test_dep_leak_guard.py`` enforces it on the
``src/folio_insights/governance/`` tree, but this conftest sets the same tone
for tests). The factories return fully-validated Pydantic instances so tests
don't have to repeat the ceremony.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable, Optional

import pytest

from folio_insights.shards.envelope import AttestedSignature


# A fixed did:key for tests (no real signing — these are unsigned stub
# signatures, honest about being unverified).
GENESIS_DID = "did:key:zGenesisFixtureSigner"


@pytest.fixture
def genesis_did() -> str:
    """The fixed did:key string used as the genesis signer for test events."""
    return GENESIS_DID


@pytest.fixture
def attested_signature_factory() -> Callable[..., AttestedSignature]:
    """Return a callable that builds a valid ``AttestedSignature``.

    Tests embed the result inside event payloads (every ``_BaseEvent``
    descendant carries ``signature: AttestedSignature``). The factory accepts
    overrides via kwargs; defaults produce a syntactically-valid (but
    cryptographically unsigned) signature whose ``verified`` slot is ``None``
    — honestly unverified, never reads as verified (T-06-03).
    """
    def _build(
        action: str = "role_assertion",
        did: str = GENESIS_DID,
        signed_at: Optional[datetime] = None,
        over_content_hash: str = "0" * 64,
    ) -> AttestedSignature:
        return AttestedSignature(
            did=did,
            action=action,  # type: ignore[arg-type]  # Literal-narrowed by caller
            signed_at=signed_at or datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC),
            signature="",
            over_content_hash=over_content_hash,
            signing_key_id=f"{did}#key-1",
            did_doc_snapshot_at=signed_at or datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC),
            verified=None,
        )

    return _build


@pytest.fixture
def sample_role_assertion(attested_signature_factory):
    """Return a callable building a ``RoleAssertionEvent`` test instance."""
    from folio_insights.governance.events import RoleAssertionEvent

    def _build(
        role: str = "reviewer",
        subject: str = "did:fi:bob",
        corpus: str = "test-corpus",
    ) -> RoleAssertionEvent:
        return RoleAssertionEvent(
            corpus=corpus,
            signature=attested_signature_factory(action="role_assertion"),
            subject_did=subject,
            role=role,  # type: ignore[arg-type]
        )

    return _build
