"""Raw ledger rows cannot bypass closure admission or restore withdrawn authority."""
from dataclasses import replace
from datetime import timedelta

import pytest

from folio_insights.closure.declarations import (
    LEDGER_KIND, ClosureDeclarationRefused, load_declarations, submit_declaration,
)
from tests.query.test_closure_declarations import declaration, seeded
from folio_insights.governance.clock import parse_committed_at
from tests.storage.conftest import fresh_signing_clock, new_identity  # noqa: F401


async def test_raw_ledger_unknown_member_is_not_active(tmp_path):
    ctx, admin = await seeded(tmp_path)
    try:
        signed = await declaration(ctx, admin, members=["urn:test:absent"])
        await ctx.proposals.append(LEDGER_KIND, signed.model_dump(mode="json"), op_id=signed.op_id)
        loaded = await load_declarations(ctx)
        assert not loaded.active
        assert loaded.refused
    finally:
        await ctx.close()


async def test_raw_unauthorized_row_is_not_a_successful_retry(tmp_path):
    ctx, _admin = await seeded(tmp_path)
    try:
        signed = await declaration(ctx, new_identity())
        await ctx.proposals.append(LEDGER_KIND, signed.model_dump(mode="json"), op_id=signed.op_id)
        before = await ctx.proposals.entries()
        with pytest.raises(ClosureDeclarationRefused):
            await submit_declaration(ctx, signed)
        assert await ctx.proposals.entries() == before
    finally:
        await ctx.close()


async def test_captured_ledger_digest_and_signed_operation_are_checked(tmp_path):
    ctx, admin = await seeded(tmp_path)
    try:
        signed = await declaration(ctx, admin)
        entry = await submit_declaration(ctx, signed)
        with pytest.raises(ClosureDeclarationRefused, match="digest"):
            await load_declarations(ctx, entries=[replace(entry, payload_sha256="0" * 64)])
        loaded = await load_declarations(ctx, entries=[replace(entry, op_id="moved")])
        assert not loaded.active
        assert loaded.refused
    finally:
        await ctx.close()


async def test_unparseable_replacement_cannot_restore_previous_completeness(tmp_path):
    ctx, admin = await seeded(tmp_path)
    try:
        signed = await declaration(ctx, admin)
        await submit_declaration(ctx, signed)
        await ctx.proposals.append(LEDGER_KIND, {"invalid": "metadata"}, op_id="damaged")
        loaded = await load_declarations(ctx)
        assert not loaded.active and loaded.refused
        fresh = await declaration(ctx, admin, op_id="fresh-declaration")
        await submit_declaration(ctx, fresh)
        assert (await load_declarations(ctx)).active == (fresh,)
    finally:
        await ctx.close()


async def test_declaration_cannot_cover_a_prefix_committed_after_its_ledger_row(tmp_path):
    ctx, admin = await seeded(tmp_path)
    try:
        signed = await declaration(ctx, admin)
        entry = await submit_declaration(ctx, signed)
        main_row = await ctx._journal.row_at(ctx.corpus, signed.main_head)
        before_main = parse_committed_at(main_row.committed_at) - timedelta(microseconds=1)
        loaded = await load_declarations(ctx, entries=[replace(entry, committed_at=before_main.isoformat())])
        assert not loaded.active and loaded.refused
    finally:
        await ctx.close()
