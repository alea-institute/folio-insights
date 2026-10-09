"""Shards, revisions, governance events and active roles survive reopening,
including across separate OS processes."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from folio_insights.revision import edit_shard_content, get_shard_at
from folio_insights.storage import CorpusStorageContext

from tests.storage.conftest import (
    at,
    genesis,
    new_identity,
    role_assertion,
    role_revocation,
    run_proc,
    shard,
)

pytestmark = pytest.mark.storage

FAR = datetime(2100, 1, 1, tzinfo=UTC)


async def test_reopen_in_process_restores_everything(
    storage_root: Path, admin, monkeypatch: pytest.MonkeyPatch
) -> None:
    from folio_insights.storage import context as storage_context

    reviewer = new_identity()
    base = shard(1)
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    # Role windows are server commit times (R17), so pin the server clock to
    # the signing times to make the reviewer's window [at(1), at(2)) exact.
    for seconds, event in (
        (0, genesis("corpus-a", admin)),
        (1, role_assertion("corpus-a", admin, reviewer.did, "reviewer", at(1))),
        (2, role_revocation("corpus-a", admin, reviewer.did, "reviewer", at(2))),
    ):
        monkeypatch.setattr(storage_context, "_server_now", lambda s=seconds: at(s))
        await ctx.governance.append(event)
    monkeypatch.undo()
    await ctx.shards.put(base.shard_iri, base)
    await edit_shard_content(
        base.shard_iri, "sense", "synthetic revised", admin.did, "why", admin.sk, ctx.shards
    )
    before_status = await ctx.status()
    await ctx.close()

    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        assert await ctx.status() == before_status
        assert await ctx.governance.latest_position("corpus-a") == 2
        events = [e async for e in ctx.governance.iter_events("corpus-a")]
        assert [e.action for e in events] == ["role_assertion", "role_assertion", "role_revocation"]
        assert [e.position for e in events] == [0, 1, 2]
        assert await ctx.governance.query_active_roles_at("corpus-a", FAR) == {
            admin.did: {"corpus_admin"}
        }
        assert (await ctx.governance.query_active_roles_at("corpus-a", at(1)))[reviewer.did] == {
            "reviewer"
        }
        current = await ctx.shards.get(base.shard_iri)
        assert current is not None and current.sense == "synthetic revised"
        assert len(current.content_edits) == 1
        original = await get_shard_at(base.shard_iri, base.extracted_at, ctx.shards)
        assert original is not None and original.sense == base.sense
        record = await ctx.shards.get_record(base.shard_iri)
        assert record is not None and record.position == 4
        assert (await ctx.governance.get_by_position("corpus-a", 1)).subject_did == reviewer.did
        assert await ctx.governance.get_by_position("corpus-a", 9) is None
    finally:
        await ctx.close()


async def test_separate_processes_share_persistent_state(storage_root: Path, admin) -> None:
    written = run_proc("write", str(storage_root), "corpus-a", admin.raw_private_hex())
    assert written["positions"] == [0, 1]

    # A different process (this test) reads what the writer committed.
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        status = await ctx.status()
        assert status.journal_head == written["journal_head"] == 4
        assert status.projection_watermark == status.journal_head
        roles = await ctx.governance.query_active_roles_at("corpus-a", FAR)
        assert roles == {admin.did: {"corpus_admin"}, written["reviewer"]: {"reviewer"}}
        base = await ctx.shards.get(written["base"])
        assert base is not None and base.sense == "synthetic revised sense"
        deps = await ctx.shards.dependents_of(written["base"])
        assert [d.shard_iri for d in deps] == [written["dependent"]]
        # This process appends; a third process must see it.
        extra = shard(3)
        await ctx.shards.put(extra.shard_iri, extra)
    finally:
        await ctx.close()

    read = run_proc("read", str(storage_root), "corpus-a")
    assert read["journal_head"] == read["watermark"] == 5
    assert [e["position"] for e in read["events"]] == [0, 1]
    assert read["shards"][written["base"]] == "synthetic revised sense"
    assert set(read["shards"]) == {written["base"], written["dependent"], extra.shard_iri}
    assert read["dependents"][written["base"]] == [written["dependent"]]
    assert read["roles"][written["reviewer"]] == ["reviewer"]
