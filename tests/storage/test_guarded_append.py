"""Phase 13 U3 storage seams used by the CLI.

* ``PersistentGovernanceLog.append(..., expected_head=)`` compares the corpus
  journal head inside the write transaction and appends nothing on a change.
* ``CorpusStorageContext.committed_governance_op`` finds a committed
  operation, so a retried saved operation returns its result.
* ``cached_event_verifier`` / ``cli_storage_config``: append-time signature
  checks resolve did:web signers from a pre-populated DID-document cache, and
  still fail closed without one.

Identities are generated per test; nothing reads operator credentials.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from folio_insights.governance.cli._state import cli_storage_config
from folio_insights.governance.events import RoleAssertionEvent
from folio_insights.governance.log import InvalidSignature
from folio_insights.identity.cache import DidDocSnapshot, InMemoryDidDocCache
from folio_insights.identity.signer import sign_attestation
from folio_insights.shards import AttestedSignature
from folio_insights.storage import (
    CorpusStorageContext,
    JournalStateChanged,
    OperationIdConflict,
)

from tests.storage.conftest import at, genesis, new_identity, role_assertion, shard

CORPUS = "corpus-a"


async def test_guarded_append_refuses_after_any_commit(ctx: CorpusStorageContext, admin) -> None:
    await ctx.governance.append(genesis(CORPUS, admin), op_id="g")
    head = await ctx.journal_head()

    # An unrelated shard write moves the journal head.
    s = shard(1)
    await ctx.shards.put(s.shard_iri, s, op_id="shard-1")

    event = role_assertion(CORPUS, admin, new_identity().did, "reviewer", at(5))
    with pytest.raises(JournalStateChanged) as info:
        await ctx.governance.append(event, op_id="guarded", expected_head=head)
    assert info.value.expected == head and info.value.actual == head + 1
    assert await ctx.journal_head() == head + 1
    assert await ctx.committed_governance_op("guarded") is None

    # Against the current head the same request commits, exactly once.
    committed = await ctx.governance.append(event, op_id="guarded", expected_head=head + 1)
    again = await ctx.governance.append(event, op_id="guarded", expected_head=head + 1)
    assert again == committed
    assert await ctx.journal_head() == head + 2
    assert await ctx.committed_governance_op("guarded") == committed


async def test_committed_governance_op_refuses_shard_op(ctx: CorpusStorageContext, admin) -> None:
    await ctx.governance.append(genesis(CORPUS, admin), op_id="g")
    s = shard(2)
    await ctx.shards.put(s.shard_iri, s, op_id="a-shard-write")
    with pytest.raises(OperationIdConflict):
        await ctx.committed_governance_op("a-shard-write")
    assert (await ctx.committed_governance_op("g")).position == 0  # type: ignore[union-attr]


async def test_signature_check_runs_before_guarded_commit(
    ctx: CorpusStorageContext, admin
) -> None:
    await ctx.governance.append(genesis(CORPUS, admin), op_id="g")
    head = await ctx.journal_head()
    event = role_assertion(CORPUS, admin, new_identity().did, "reviewer", at(5))
    tampered = event.model_copy(update={"subject_did": new_identity().did})
    with pytest.raises(InvalidSignature):
        await ctx.governance.append(tampered, op_id="bad", expected_head=head)
    assert await ctx.journal_head() == head
    assert await ctx.committed_governance_op("bad") is None


# ── did:web through a pre-populated cache ──────────────────────────────────

WEB_DID = "did:web:corpus-admin.example.test"
WEB_KEY_ID = f"{WEB_DID}#key-1"
SNAPSHOT_AT = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)


def _did_web_genesis() -> tuple[RoleAssertionEvent, str]:
    """A genesis row self-signed by a did:web admin backed by a generated key.

    Returns the event and the key's did:key multibase (for the cache entry).
    """
    key = new_identity()
    placeholder = AttestedSignature(
        did=WEB_DID,
        action="role_assertion",
        signed_at=at(0),
        signing_key_id=WEB_KEY_ID,
        did_doc_snapshot_at=SNAPSHOT_AT,
    )
    event = RoleAssertionEvent(
        corpus=CORPUS,
        position=0,
        signature=placeholder,
        subject_did=WEB_DID,
        role="corpus_admin",
    )
    sig = sign_attestation(
        event.signature_payload().decode("utf-8"),
        key.sk,
        WEB_DID,
        "role_assertion",
        signing_key_id=WEB_KEY_ID,
        did_doc_snapshot_at=SNAPSHOT_AT,
        now=at(0),
    )
    return event.model_copy(update={"signature": sig}), key.did.removeprefix("did:key:")


async def test_did_web_signer_fails_closed_without_cache(storage_root: Path) -> None:
    event, _ = _did_web_genesis()
    ctx = await CorpusStorageContext.open(storage_root, CORPUS)  # offline default
    try:
        with pytest.raises(InvalidSignature):
            await ctx.governance.append(event, op_id="web-genesis")
        assert await ctx.journal_head() == -1
    finally:
        await ctx.close()


async def test_did_web_signer_verifies_from_prepopulated_cli_cache(storage_root: Path) -> None:
    event, multibase = _did_web_genesis()
    cache = InMemoryDidDocCache()
    await cache.put(
        (WEB_DID, SNAPSHOT_AT),
        DidDocSnapshot(
            did=WEB_DID,
            fetched_at=SNAPSHOT_AT,
            verification_method_id=WEB_KEY_ID,
            public_key_multibase=multibase,
        ),
    )
    ctx = await CorpusStorageContext.open(
        storage_root, CORPUS, config=cli_storage_config(cache)
    )
    try:
        persisted = await ctx.governance.append(event, op_id="web-genesis")
        assert persisted.position == 0
    finally:
        await ctx.close()

    # An empty CLI cache still refuses a did:web signer (no network fallback).
    other_root = storage_root.parent / "other"
    ctx = await CorpusStorageContext.open(
        other_root, CORPUS, config=cli_storage_config(InMemoryDidDocCache())
    )
    try:
        with pytest.raises(InvalidSignature):
            await ctx.governance.append(event, op_id="web-genesis")
    finally:
        await ctx.close()


async def test_revoked_signer_refused_in_transaction(ctx: CorpusStorageContext, admin) -> None:
    """P2: every non-genesis event is re-authorized against the committed
    history inside the write transaction, not only role events."""
    from folio_insights.governance.events import ExtractEvent
    from folio_insights.governance.log import NotAuthorized

    from tests.storage.conftest import role_revocation, sign_event

    reviewer = new_identity()
    await ctx.governance.append(genesis(CORPUS, admin), op_id="g")
    await ctx.governance.append(
        role_assertion(CORPUS, admin, reviewer.did, "reviewer", at(1)), op_id="grant"
    )

    def extract(n: int) -> ExtractEvent:
        unsigned = ExtractEvent(
            corpus=CORPUS,
            signature=AttestedSignature(did=reviewer.did, action="extract", signed_at=at(100 * n)),
            shard_iri=shard(n).shard_iri,
        )
        return sign_event(unsigned, reviewer, at(100 * n))  # type: ignore[return-value]

    assert (await ctx.governance.append(extract(1), op_id="x1")).position == 2
    await ctx.governance.append(
        role_revocation(CORPUS, admin, reviewer.did, "reviewer", at(150)), op_id="revoke"
    )
    head = await ctx.journal_head()
    with pytest.raises(NotAuthorized):
        await ctx.governance.append(extract(2), op_id="x2")
    assert await ctx.journal_head() == head
