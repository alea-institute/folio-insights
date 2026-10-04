"""Regression tests for the Phase 13 storage review findings.

One test (or parametrized group) per finding: replayed governance events,
uncommitted rows reaching the projection, PII in validation errors, ``*_hash``
keys skipping the PII gate, ``INSERT OR REPLACE`` around the immutability
triggers, bulk replay matching other operations, explicit-op_id retry after a
later revision, and a failed COMMIT leaving the transaction open. All data is
synthetic.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

import folio_insights.storage.context as context_module
from folio_insights.governance.log import InvalidSignature
from folio_insights.shards import AttestedSignature
from folio_insights.storage import (
    CorpusStorageContext,
    GovernanceEventReplayed,
    PiiRejected,
    ShardIdentityViolation,
    ShardRecordInvalid,
)
from folio_insights.storage.journal import JOURNAL_FILENAME
from folio_insights.storage.projection import fi

from tests.storage.conftest import (
    at,
    genesis,
    new_identity,
    role_assertion,
    role_revocation,
    shard,
)

pytestmark = pytest.mark.storage

CORPUS = "corpus-a"
SSN = "123-45-6789"
PHONE = "212-555-0142"


# ── P1-1: replayed governance event ───────────────────────────────────────


async def test_same_signer_revoke_regrant_revoke_cycle_succeeds(
    ctx: CorpusStorageContext, admin
) -> None:
    """With signed_at bound into the signed payload, a repeat by the same
    admin is a distinct signed event, not a replay."""
    subject = new_identity()
    await ctx.governance.append(genesis(CORPUS, admin))
    await ctx.governance.append(role_assertion(CORPUS, admin, subject.did, "reviewer", at(1)))
    await ctx.governance.append(role_revocation(CORPUS, admin, subject.did, "reviewer", at(2)))
    regrant = await ctx.governance.append(
        role_assertion(CORPUS, admin, subject.did, "reviewer", at(3))
    )
    assert (await ctx.governance.query_active_roles_at(CORPUS, at(3))).get(subject.did) == {
        "reviewer"
    }
    final = await ctx.governance.append(
        role_revocation(CORPUS, admin, subject.did, "reviewer", at(4))
    )
    assert (regrant.position, final.position) == (3, 4)
    assert subject.did not in await ctx.governance.query_active_roles_at(CORPUS, at(10))


async def test_replay_with_moved_signed_at_fails_verification(
    ctx: CorpusStorageContext, admin
) -> None:
    subject = new_identity()
    await ctx.governance.append(genesis(CORPUS, admin))
    await ctx.governance.append(
        role_assertion(CORPUS, admin, subject.did, "corpus_admin", at(1))
    )
    revocation = role_revocation(CORPUS, admin, subject.did, "corpus_admin", at(2))
    await ctx.governance.append(revocation)
    await ctx.governance.append(
        role_assertion(CORPUS, admin, subject.did, "corpus_admin", at(3))
    )
    head = await ctx.governance.latest_position(CORPUS)

    replay = revocation.model_copy(
        update={"signature": revocation.signature.model_copy(update={"signed_at": at(4)})}
    )
    assert replay.signature_payload() != revocation.signature_payload()
    with pytest.raises(InvalidSignature):
        await ctx.governance.append(replay)

    assert await ctx.governance.latest_position(CORPUS) == head
    roles = await ctx.governance.query_active_roles_at(CORPUS, at(10))
    assert roles.get(subject.did) == {"corpus_admin"}


async def test_verbatim_replay_under_fresh_op_id_is_refused(
    ctx: CorpusStorageContext, admin
) -> None:
    await ctx.governance.append(genesis(CORPUS, admin))
    event = role_assertion(CORPUS, admin, new_identity().did, "reviewer", at(1))
    first = await ctx.governance.append(event, op_id="x1")
    assert await ctx.governance.append(event, op_id="x1") == first  # retry still works
    with pytest.raises(GovernanceEventReplayed):
        await ctx.governance.append(event, op_id="x2")
    assert await ctx.governance.latest_position(CORPUS) == first.position


# ── P1-2: uncommitted rows reach the projection ───────────────────────────


async def test_open_write_transaction_is_never_projected(
    ctx: CorpusStorageContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate_hit, release = asyncio.Event(), asyncio.Event()
    original = context_module.JournalTransaction.append_many
    refused_iri = shard(2).shard_iri

    async def held_append(self, pendings):  # type: ignore[no-untyped-def]
        rows = await original(self, pendings)  # appended inside the open transaction
        if any(p.subject == refused_iri for p in pendings):
            gate_hit.set()
            await release.wait()
            raise ShardIdentityViolation("synthetic refusal of record 2")
        return rows

    monkeypatch.setattr(context_module.JournalTransaction, "append_many", held_append)

    async def writer() -> None:
        with pytest.raises(ShardIdentityViolation):
            await ctx.ingest_shards([shard(1), shard(2)])

    task = asyncio.create_task(writer())
    await gate_hit.wait()
    during = await ctx.status()  # both records are appended but not committed
    release.set()
    await task
    assert (during.journal_head, during.projection_watermark) == (-1, -1)

    monkeypatch.setattr(context_module.JournalTransaction, "append_many", original)
    third = shard(3)
    await ctx.shards.put(third.shard_iri, third)
    rows = await ctx.query(f"SELECT ?s WHERE {{ ?s {fi('journalPosition')} ?p }}")
    assert [r["s"].value for r in rows] == [third.shard_iri]


async def test_projection_past_committed_head_is_rebuilt(ctx: CorpusStorageContext) -> None:
    """A watermark ahead of the journal head (the state P1-2 left behind) is a
    rebuild trigger, not a 'nothing to do'."""
    first = shard(1)
    await ctx.shards.put(first.shard_iri, first)
    ctx._confirmed = 5  # simulate a projection that applied rows never committed
    status = await ctx.status()
    assert (status.journal_head, status.projection_watermark) == (0, 0)


# ── P2-1: PII leaks into validation error messages ────────────────────────


async def test_pii_in_invalid_field_is_refused_before_validation(
    ctx: CorpusStorageContext,
) -> None:
    record = json.loads(shard(1).model_dump_json())
    with pytest.raises(PiiRejected) as info:
        await ctx.ingest_shards([dict(record, confidence=SSN)])
    assert SSN not in str(info.value)


async def test_validation_error_omits_input_values_and_keys(
    ctx: CorpusStorageContext,
) -> None:
    record = json.loads(shard(1).model_dump_json())
    for bad in (
        dict(record, **{f"note_{PHONE}": "x"}),
        dict(record, confidence="not-a-number 2125550142"),
    ):
        with pytest.raises(ShardRecordInvalid) as info:
            await ctx.ingest_shards([bad])
        message = str(info.value)
        assert PHONE not in message and "2125550142" not in message
        assert info.value.__cause__ is None and info.value.__suppress_context__
    assert (await ctx.status()).journal_head == -1


# ── P2-2: ``*_hash`` keys skip the PII gate ───────────────────────────────


async def test_hash_key_holding_free_text_is_scanned(ctx: CorpusStorageContext) -> None:
    record = json.loads(shard(1).model_dump_json())
    with pytest.raises(PiiRejected):
        await ctx.ingest_shards([dict(record, provenance_hash=f"SSN {SSN}")])
    digest = "0" * 63 + "1"
    stored = await ctx.ingest_shards([dict(record, provenance_hash=digest)])
    assert stored[0].provenance_hash == digest


# ── P2-3: INSERT OR REPLACE around the immutability triggers ──────────────


@pytest.mark.parametrize(
    "statement",
    [
        # same op_id, next position: REPLACE would delete position 0
        "INSERT OR REPLACE INTO journal SELECT corpus, 1, op_id, request_sha256, kind, "
        "'urn:evil', governance_position, record_schema_version, source_schema_version, "
        "payload, original_bytes, payload_sha256, committed_at FROM journal WHERE position = 0",
        # same position
        "INSERT OR REPLACE INTO journal SELECT corpus, 0, 'other-op', request_sha256, kind, "
        "'urn:evil', governance_position, record_schema_version, source_schema_version, "
        "payload, original_bytes, payload_sha256, committed_at FROM journal WHERE position = 0",
        # same governance_position
        "INSERT OR REPLACE INTO journal SELECT corpus, 2, 'other-op', request_sha256, kind, "
        "'urn:evil', governance_position, record_schema_version, source_schema_version, "
        "payload, original_bytes, payload_sha256, committed_at FROM journal WHERE position = 1",
        "INSERT OR REPLACE INTO storage_meta VALUES ('journal_schema_version', '1')",
        "REPLACE INTO storage_meta VALUES ('journal_schema_version', '2')",
    ],
)
async def test_insert_or_replace_cannot_rewrite_committed_rows(
    storage_root: Path, admin, statement: str
) -> None:
    ctx = await CorpusStorageContext.open(storage_root, CORPUS)
    try:
        first = shard(1)
        await ctx.shards.put(first.shard_iri, first, op_id="op-A")
        await ctx.governance.append(genesis(CORPUS, admin))
    finally:
        await ctx.close()
    conn = sqlite3.connect(storage_root / JOURNAL_FILENAME)
    try:
        before = (
            conn.execute("SELECT * FROM journal ORDER BY position").fetchall(),
            conn.execute("SELECT * FROM storage_meta").fetchall(),
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(statement)
        conn.rollback()
        after = (
            conn.execute("SELECT * FROM journal ORDER BY position").fetchall(),
            conn.execute("SELECT * FROM storage_meta").fetchall(),
        )
        assert after == before
    finally:
        conn.close()
    reopened = await CorpusStorageContext.open(storage_root, CORPUS)  # triggers stay valid
    await reopened.close()


# ── P2-4: bulk replay matches other operations ────────────────────────────


async def test_bulk_retry_returns_only_its_own_rows(ctx: CorpusStorageContext) -> None:
    s1, s2, s3 = shard(1), shard(2), shard(3)
    await ctx.ingest_shards([s1], op_id="Batch")
    await ctx.ingest_shards([s2], op_id="batch")
    await ctx.ingest_shards([s3], op_id="Batch#0")
    again = await ctx.ingest_shards([s1], op_id="Batch")
    assert [s.shard_iri for s in again] == [s1.shard_iri]
    assert (await ctx.status()).journal_head == 2


# ── P2-5: explicit op_id retry after a later revision ─────────────────────


async def test_explicit_op_id_retry_after_later_revision_returns_result(
    ctx: CorpusStorageContext,
) -> None:
    base = shard(5)
    await ctx.shards.put(base.shard_iri, base, op_id="p1")
    sig = AttestedSignature(
        did="did:key:zSynthetic",
        action="promote",
        signed_at=at(1),
        signature="AA",
        over_content_hash="00",
        signing_key_id="did:key:zSynthetic#zSynthetic",
    )
    signed = base.model_copy(update={"signatures": [sig]})
    await ctx.shards.put(base.shard_iri, signed, op_id="p2")
    await ctx.shards.put(base.shard_iri, base, op_id="p1")  # retry: no raise
    assert (await ctx.status()).journal_head == 1
    current = await ctx.shards.get(base.shard_iri)
    assert current is not None and len(current.signatures) == 1


# ── Nit: a failed COMMIT must not leave the transaction open ──────────────


async def test_failed_commit_rolls_back(
    ctx: CorpusStorageContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = ctx._journal.conn
    real_execute = conn.execute
    failed = False

    def execute(sql: str, *args):  # type: ignore[no-untyped-def]
        nonlocal failed
        if sql == "COMMIT" and not failed:
            failed = True

            async def boom():  # type: ignore[no-untyped-def]
                raise sqlite3.OperationalError("synthetic commit failure")

            return boom()
        return real_execute(sql, *args)

    monkeypatch.setattr(conn, "execute", execute)
    first = shard(1)
    with pytest.raises(sqlite3.OperationalError, match="synthetic commit failure"):
        await ctx.shards.put(first.shard_iri, first)
    assert not conn.in_transaction
    assert (await ctx.status()).journal_head == -1
    await ctx.shards.put(first.shard_iri, first)  # the connection is usable again
    assert (await ctx.status()).journal_head == 0
