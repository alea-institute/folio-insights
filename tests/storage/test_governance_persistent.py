"""Persistent GovernanceLog keeps the Protocol and every Phase 7 gate."""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from folio_insights.governance.log import (
    GovernanceLog,
    InvalidSignature,
    NotAuthorized,
    WouldLockoutCorpusAdmin,
)
from folio_insights.revision.store import ShardStore
from folio_insights.storage import CorpusStorageContext, PersistentGovernanceLog

from tests.storage.conftest import (
    at,
    genesis,
    new_identity,
    role_assertion,
    role_revocation,
    sign_event,
)

pytestmark = pytest.mark.storage

PROTOCOL_METHODS = {
    "append",
    "query_active_roles_at",
    "get_by_position",
    "iter_events",
    "latest_position",
}


def test_public_surface_is_exactly_the_protocol() -> None:
    public = {n for n in dir(PersistentGovernanceLog) if not n.startswith("_")}
    assert public == PROTOCOL_METHODS
    for name in PROTOCOL_METHODS:
        method = getattr(PersistentGovernanceLog, name)
        assert inspect.iscoroutinefunction(method) or inspect.isasyncgenfunction(method)


async def test_adapters_satisfy_runtime_protocols(ctx: CorpusStorageContext) -> None:
    assert isinstance(ctx.governance, GovernanceLog)
    assert isinstance(ctx.shards, ShardStore)
    assert await ctx.governance.latest_position("corpus-a") == -1


async def _journal_head(ctx: CorpusStorageContext) -> int:
    return (await ctx.status()).journal_head


async def test_invalid_signatures_are_refused_before_append(
    ctx: CorpusStorageContext, admin
) -> None:
    await ctx.governance.append(genesis("corpus-a", admin))
    good = role_assertion("corpus-a", admin, new_identity().did, "reviewer", at(1))

    # Tampered content: the signature no longer covers the event.
    tampered = good.model_copy(update={"role": "arbiter"})
    # Signed by a key that does not match the claimed DID.
    impostor = new_identity()
    impostor_sig = sign_event(good, impostor, at(1)).signature
    forged = good.model_copy(
        update={
            "signature": impostor_sig.model_copy(
                update={"did": admin.did, "signing_key_id": admin.key_id}
            )
        }
    )
    # Honestly unsigned.
    unsigned = good.model_copy(
        update={"signature": good.signature.model_copy(update={"signature": ""})}
    )
    for bad in (tampered, forged, unsigned):
        with pytest.raises(InvalidSignature):
            await ctx.governance.append(bad)
    assert await _journal_head(ctx) == 0
    assert (await ctx.governance.append(good)).position == 1


async def test_non_admin_and_revoked_signers_are_refused(
    ctx: CorpusStorageContext, admin
) -> None:
    second = new_identity()
    outsider = new_identity()
    await ctx.governance.append(genesis("corpus-a", admin))
    with pytest.raises(NotAuthorized):
        await ctx.governance.append(
            role_assertion("corpus-a", outsider, new_identity().did, "reviewer", at(1))
        )
    await ctx.governance.append(
        role_assertion("corpus-a", admin, second.did, "corpus_admin", at(2))
    )
    await ctx.governance.append(
        role_revocation("corpus-a", admin, second.did, "corpus_admin", at(3))
    )
    # The revoked admin can no longer appoint anyone.
    with pytest.raises(NotAuthorized):
        await ctx.governance.append(
            role_assertion("corpus-a", second, new_identity().did, "reviewer", at(4))
        )
    # A non-genesis self-signed assertion is refused too.
    with pytest.raises(NotAuthorized):
        await ctx.governance.append(
            role_assertion("corpus-a", outsider, outsider.did, "corpus_admin", at(5))
        )
    assert await ctx.governance.latest_position("corpus-a") == 2


async def test_last_admin_lockout_is_refused(ctx: CorpusStorageContext, admin) -> None:
    await ctx.governance.append(genesis("corpus-a", admin))
    with pytest.raises(WouldLockoutCorpusAdmin):
        await ctx.governance.append(
            role_revocation("corpus-a", admin, admin.did, "corpus_admin", at(1))
        )
    assert await ctx.governance.latest_position("corpus-a") == 0


async def test_positions_and_signed_at_order_enforced(ctx: CorpusStorageContext, admin) -> None:
    await ctx.governance.append(genesis("corpus-a", admin, at(10)))
    # signed_at moving backward with position is refused by the SHACL shape.
    with pytest.raises(ValueError):
        await ctx.governance.append(
            role_assertion("corpus-a", admin, new_identity().did, "reviewer", at(5))
        )
    # A spoofed explicit position is refused.
    spoof = role_assertion("corpus-a", admin, new_identity().did, "reviewer", at(11))
    with pytest.raises(ValueError):
        await ctx.governance.append(spoof.model_copy(update={"position": 0}))
    assert await ctx.governance.latest_position("corpus-a") == 0


async def test_verifier_can_be_disabled_for_unsigned_test_doubles(storage_root: Path) -> None:
    from folio_insights.governance.events import RoleAssertionEvent
    from folio_insights.shards import AttestedSignature
    from folio_insights.storage import StorageConfig

    unsigned_did = "did:key:zUnsignedFixtureSigner"

    ctx = await CorpusStorageContext.open(
        storage_root, "corpus-a", config=StorageConfig(event_verifier=None)
    )
    try:
        event = RoleAssertionEvent(
            corpus="corpus-a",
            signature=AttestedSignature(
                did=unsigned_did, action="role_assertion", signed_at=at(0)
            ),
            subject_did=unsigned_did,
            role="corpus_admin",
        )
        assert (await ctx.governance.append(event)).position == 0
    finally:
        await ctx.close()
