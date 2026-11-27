"""Signed closure declarations use generated identities and synthetic corpora."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from folio_insights.closure.declarations import (
    LEDGER_KIND, ClosureDeclarationRefused, capture_main_state, load_declarations,
    sign_declaration, submit_declaration, verify_declaration,
)
from folio_insights.query.closed_world import ClosedWorldScope
from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.errors import JournalStateChanged, OperationIdConflict
from tests.storage.conftest import (
    at, fresh_signing_clock, genesis, new_identity, role_assertion, role_revocation, shard,
)

SCOPE = ClosedWorldScope("urn:test:scope", frozenset({"urn:test:Class"}),
                         frozenset({"urn:test:property", "urn:test:withdrawn"}))


async def seeded(root, corpus="corpus-a"):
    admin = new_identity()
    ctx = await CorpusStorageContext.open(root, corpus)
    await ctx.governance.append(genesis(corpus, admin, at(0)))
    await ctx.ingest_shards([shard(1), shard(2)])
    return ctx, admin


async def declaration(ctx, admin, *, op_id="closure-one", scope=SCOPE, members=None, **kw):
    head, digest = await capture_main_state(ctx)
    return sign_declaration(
        ctx.corpus, scope, members=members if members is not None else [shard(1).shard_iri],
        main_head=head, main_digest=digest, op_id=op_id, signing_key=admin.sk,
        did=admin.did, **kw,
    )


async def test_persist_reopen_and_exact_retry(tmp_path):
    ctx, admin = await seeded(tmp_path)
    signed = await declaration(ctx, admin)
    assert verify_declaration(signed)
    entry = await submit_declaration(ctx, signed)
    assert entry.kind == LEDGER_KIND and entry.op_id == signed.op_id
    assert await submit_declaration(ctx, signed) == entry
    assert await ctx.proposals.head() == 0
    assert (await load_declarations(ctx)).active == (signed,)
    await ctx.close()
    ctx = await CorpusStorageContext.open(tmp_path, "corpus-a")
    try:
        assert (await load_declarations(ctx)).active == (signed,)
        assert await submit_declaration(ctx, signed) == entry
    finally:
        await ctx.close()


async def test_latest_scope_replaces_and_old_retry_never_restores(tmp_path):
    ctx, admin = await seeded(tmp_path)
    try:
        old = await declaration(ctx, admin, members=[shard(1).shard_iri, shard(2).shard_iri])
        old_entry = await submit_declaration(ctx, old)
        narrow = ClosedWorldScope(SCOPE.scope_iri, SCOPE.closed_classes,
                                  frozenset({"urn:test:property"}))
        new = await declaration(ctx, admin, op_id="closure-two", scope=narrow)
        await submit_declaration(ctx, new)
        assert (await load_declarations(ctx)).active == (new,)
        assert await submit_declaration(ctx, old) == old_entry
        assert (await load_declarations(ctx)).active == (new,)
        with pytest.raises(ClosureDeclarationRefused):
            await submit_declaration(ctx, old, op_id="closure-three")
        with pytest.raises(ClosureDeclarationRefused):
            await submit_declaration(ctx, old.model_copy(update={"op_id": "closure-three"}))
        conflict = await declaration(ctx, admin, op_id=old.op_id, scope=narrow)
        with pytest.raises(OperationIdConflict):
            await submit_declaration(ctx, conflict)
        assert await ctx.proposals.head() == 1
    finally:
        await ctx.close()


async def test_wrong_corpus_signer_signature_and_unknown_member_refuse(tmp_path):
    ctx, admin = await seeded(tmp_path)
    other = await CorpusStorageContext.open(tmp_path, "corpus-b")
    try:
        await other.ingest_shards([shard(3)])
        signed = await declaration(ctx, admin)
        stranger = await declaration(ctx, new_identity())
        for invalid in (signed.model_copy(update={"corpus": "corpus-b"}),
                        signed.model_copy(update={"signature": "invalid"}), stranger,
                        await declaration(ctx, admin, members=[shard(3).shard_iri]),
                        await declaration(ctx, admin, members=["urn:test:unknown"])):
            with pytest.raises(ClosureDeclarationRefused):
                await submit_declaration(ctx, invalid)
        assert await ctx.proposals.head() == -1
    finally:
        await ctx.close()
        await other.close()


async def test_revoked_admin_and_stale_signature_refuse(tmp_path):
    ctx, admin = await seeded(tmp_path)
    former = new_identity()
    try:
        await ctx.governance.append(role_assertion(ctx.corpus, admin, former.did,
                                                   "corpus_admin", at(1)))
        await ctx.governance.append(role_revocation(ctx.corpus, admin, former.did,
                                                    "corpus_admin", at(2)))
        for signed in (await declaration(ctx, former), await declaration(
            ctx, admin, signed_at=datetime.now(UTC) - timedelta(days=1))):
            with pytest.raises(ClosureDeclarationRefused):
                await submit_declaration(ctx, signed)
        assert await ctx.proposals.head() == -1
    finally:
        await ctx.close()


async def test_head_advance_between_validation_and_transaction_is_atomic(tmp_path, monkeypatch):
    ctx, admin = await seeded(tmp_path)
    try:
        signed = await declaration(ctx, admin)
        original = ctx.proposals._append_authorized

        async def advance_then_append(*args, **kwargs):
            await ctx.ingest_shards([shard(3)])
            return await original(*args, **kwargs)

        monkeypatch.setattr(ctx.proposals, "_append_authorized", advance_then_append)
        with pytest.raises(JournalStateChanged):
            await submit_declaration(ctx, signed)
        assert await ctx.proposals.head() == -1
    finally:
        await ctx.close()


async def test_changed_main_state_invalidates_until_redeclared(tmp_path):
    ctx, admin = await seeded(tmp_path)
    try:
        old = await declaration(ctx, admin)
        entry = await submit_declaration(ctx, old)
        await ctx.ingest_shards([shard(3)])
        assert (await load_declarations(ctx)).active == ()
        # An exact historical retry succeeds even after the corpus moves.
        assert await submit_declaration(ctx, old) == entry
        assert (await load_declarations(ctx)).active == ()
        fresh = await declaration(ctx, admin, op_id="closure-new")
        await submit_declaration(ctx, fresh)
        assert (await load_declarations(ctx)).active == (fresh,)
    finally:
        await ctx.close()


async def test_unsafe_iris_and_tampered_binding_refuse(tmp_path):
    ctx, admin = await seeded(tmp_path)
    try:
        with pytest.raises((ValueError, ValidationError)):
            await declaration(ctx, admin, members=['urn:test:x> . ?s ?p ?o'])
        signed = await declaration(ctx, admin)
        for field, value in (("members", (shard(2).shard_iri,)),
                             ("main_digest", "0" * 64), ("main_head", 1),
                             ("closed_properties", ("urn:test:other",)),
                             ("scope_iri", "urn:test:other")):
            altered = signed.model_copy(update={field: value})
            assert not verify_declaration(altered)
            with pytest.raises(ClosureDeclarationRefused):
                await submit_declaration(ctx, altered)
        assert await ctx.proposals.head() == -1
    finally:
        await ctx.close()
