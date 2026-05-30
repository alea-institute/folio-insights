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


@pytest.fixture(autouse=True)
def _reset_governance_cli_singleton():
    """WR-01: reset the process-local ``GOVERNANCE_LOG`` singleton between
    tests.

    ``src/folio_insights/governance/cli/_state.py`` exposes a module-level
    ``GOVERNANCE_LOG: InMemoryGovernanceLog`` that the governance + corpus
    CLI subgroups share so a single ``corpus init`` is visible to
    subsequent ``governance`` invocations within one Python process.

    Pytest runs every test in the same Python process; without a reset
    fixture, events appended in one CLI test leak into the next. The
    leak is order-dependent (some tests deliberately pre-seed events;
    others assume a fresh empty log) and causes flaky cross-file
    failures.

    Strategy: re-bind ``_state.GOVERNANCE_LOG`` to a fresh
    ``InMemoryGovernanceLog()`` before each test. Re-binding (not just
    clearing the internal dict) ensures any test that previously
    captured a reference to the old singleton releases it; the new
    singleton is also picked up correctly by ``importlib.reload`` paths
    if any test uses them.

    Autouse + ``tests/governance/conftest.py`` scope: applies to every
    test under tests/governance/ (which includes CLI integration tests
    that exercise the singleton). Tests outside tests/governance/ that
    also touch the singleton (e.g. tests/corpus/test_corpus_init_*.py)
    are unaffected by this fixture; if cross-tree leakage shows up,
    Phase 13 can promote this fixture to tests/conftest.py.
    """
    from folio_insights.governance.cli import _state
    from folio_insights.governance.log import InMemoryGovernanceLog

    _state.GOVERNANCE_LOG = InMemoryGovernanceLog()
    yield
    _state.GOVERNANCE_LOG = InMemoryGovernanceLog()


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
