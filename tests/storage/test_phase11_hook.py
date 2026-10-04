"""U4: the Phase 11 validation hook runs after, never instead of, the
built-in write checks; full SHACL stays reported as deferred."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from folio_insights.governance.log import InvalidSignature
from folio_insights.shards import dump_shard_record
from folio_insights.storage import (
    FULL_SHACL_STATUS,
    PiiRejected,
    ShardIdentityViolation,
    ShardRecordInvalid,
)

from tests.storage.conftest import at, genesis, new_identity, open_ctx, role_assertion, shard

pytestmark = pytest.mark.storage


class Phase11Refusal(ValueError):
    pass


class RecordingHook:
    def __init__(self, refuse: set[str] | None = None) -> None:
        self.seen: list[str] = []
        self.refuse = refuse or set()

    def shard(self, s) -> None:  # noqa: ANN001
        self.seen.append(s.shard_iri)
        if s.shard_iri in self.refuse:
            raise Phase11Refusal(f"synthetic shape violation on {s.shard_iri}")

    def event(self, e) -> None:  # noqa: ANN001
        self.seen.append(f"event:{e.action}:{e.signature.did}")
        if "events" in self.refuse:
            raise Phase11Refusal("synthetic event shape violation")


async def test_hook_only_sees_records_that_passed_the_builtin_checks(
    storage_root: Path,
) -> None:
    hook = RecordingHook()
    ctx = await open_ctx(storage_root, shard_validator=hook.shard, event_validator=hook.event)
    try:
        with pytest.raises(PiiRejected):
            await ctx.ingest_shards([shard(1, sense="ssn 123-45-6789")])
        bad = json.loads(dump_shard_record(shard(2)))
        bad["confidence"] = "not-a-float"
        with pytest.raises(ShardRecordInvalid):
            await ctx.ingest_shards([bad])
        assert hook.seen == []  # refused before the hook ever ran

        await ctx.shards.put(shard(3).shard_iri, shard(3))
        assert hook.seen == [shard(3).shard_iri]
        # The hook accepting a write does not waive the frozen-identity check.
        with pytest.raises(ShardIdentityViolation):
            await ctx.shards.put(shard(3).shard_iri, shard(3, source_span="moved"))
        status = await ctx.status()
        assert status.journal_head == 0
        assert status.full_shacl == FULL_SHACL_STATUS == "deferred-to-phase-11"
        assert status.validation_hooks == ("shard_validator", "event_validator")
    finally:
        await ctx.close()


@pytest.mark.parametrize("path", ["put", "ingest", "bulk"])
async def test_hook_refusal_leaves_storage_unchanged(storage_root: Path, path: str) -> None:
    count = 2100 if path == "bulk" else 3  # bulk crosses the process-pool threshold
    records = [shard(n) for n in range(count)]
    hook = RecordingHook(refuse={records[-1].shard_iri})
    ctx = await open_ctx(storage_root, shard_validator=hook.shard)
    try:
        with pytest.raises(Phase11Refusal):
            if path == "put":
                await ctx.shards.put(records[-1].shard_iri, records[-1])
            elif path == "ingest":
                await ctx.ingest_shards(records)
            else:
                await ctx.bulk_load_shards(records)
        status = await ctx.status()
        assert (status.journal_head, status.projection_watermark) == (-1, -1)
        assert hook.seen[-1] == records[-1].shard_iri
    finally:
        await ctx.close()


async def test_event_hook_runs_after_signature_verification(storage_root: Path, admin) -> None:
    hook = RecordingHook(refuse={"events"})
    ctx = await open_ctx(storage_root, event_validator=hook.event)
    try:
        forged = genesis("corpus-a", admin).model_copy(deep=True)
        forged.signature.signature = "A" * 86
        with pytest.raises(InvalidSignature):
            await ctx.governance.append(forged)
        assert hook.seen == []  # an unverified event never reaches the hook
        with pytest.raises(Phase11Refusal):
            await ctx.governance.append(genesis("corpus-a", admin))
        assert (await ctx.status()).journal_head == -1
    finally:
        await ctx.close()

    hook = RecordingHook()
    ctx = await open_ctx(storage_root, event_validator=hook.event)
    try:
        await ctx.governance.append(genesis("corpus-a", admin))
        # Authorization still runs inside the write transaction after the hook.
        outsider = new_identity()
        from folio_insights.governance.log import NotAuthorized

        with pytest.raises(NotAuthorized):
            await ctx.governance.append(
                role_assertion("corpus-a", outsider, outsider.did, "reviewer", at(1))
            )
        assert len(hook.seen) == 2 and (await ctx.status()).journal_head == 0
    finally:
        await ctx.close()
