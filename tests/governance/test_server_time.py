"""R17 / KTD12 / AE6: governance time is the server's commit time.

The signer chooses ``signature.signed_at`` before signing, so it must never
decide when a role was held. Persistent appends are checked (and recorded) at
the journal transaction's server commit time, history is windowed by each
stored row's ``committed_at``, and ``signed_at`` must sit within
``SIGNING_SKEW`` of the server time or the append is refused.

The server clock is pinned through ``storage.context._server_now`` (the
module seam) so commit times are exact; AE6 itself also runs on the real
clock. Every identity is a freshly generated did:key; all data is synthetic.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from folio_insights.governance import (
    SIGNING_SKEW,
    GovernanceClockSkew,
    InMemoryGovernanceLog,
    NotAuthorized,
)
from folio_insights.governance.authorize import Allow, Deny, authorize
from folio_insights.governance.events import ExtractEvent, GovernanceEvent
from folio_insights.governance.roles import active_roles_at
from folio_insights.governance.shape_validation import validate_role_assertion_shape
from folio_insights.shards import AttestedSignature
from folio_insights.storage import CorpusStorageContext, StorageConfig
from folio_insights.storage import context as storage_context
from folio_insights.storage.context import verify_event_signature_offline

from tests.storage.conftest import (
    Identity,
    genesis,
    new_identity,
    role_assertion,
    role_revocation,
    sign_event,
)

pytestmark = pytest.mark.governance

CORPUS = "corpus-a"
# A fixed server epoch for pinned-clock tests (synthetic; never "now").
S0 = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


def m(minutes: float) -> datetime:
    return S0 + timedelta(minutes=minutes)


class ServerClock:
    """A settable stand-in for the server clock."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> ServerClock:
    pinned = ServerClock(S0)
    monkeypatch.setattr(storage_context, "_server_now", pinned)
    return pinned


@pytest.fixture
async def store(tmp_path: Path):
    ctx = await CorpusStorageContext.open(tmp_path / "storage", CORPUS)
    try:
        yield ctx
    finally:
        await ctx.close()


def extract(signer: Identity, signed_at: datetime, n: int = 1) -> ExtractEvent:
    event = ExtractEvent(
        corpus=CORPUS,
        signature=AttestedSignature(did=signer.did, action="extract", signed_at=signed_at),
        shard_iri=f"urn:folio:shard/{n:032x}",
    )
    return sign_event(event, signer, signed_at)  # type: ignore[return-value]


async def head(ctx: CorpusStorageContext) -> int:
    return (await ctx.status()).journal_head


async def committed_times(ctx: CorpusStorageContext) -> list[datetime]:
    rows = await ctx._journal.governance_rows(CORPUS, upto=None)
    return [datetime.fromisoformat(r.committed_at) for r in rows]


# ── AE6 ──────────────────────────────────────────────────────────────────


async def test_ae6_signed_an_hour_ago_is_refused_on_the_real_clock(store) -> None:
    admin, reviewer = new_identity(), new_identity()
    now = datetime.now(UTC)
    await store.governance.append(genesis(CORPUS, admin, now))

    stale = role_assertion(CORPUS, admin, reviewer.did, "reviewer", now - timedelta(hours=1))
    with pytest.raises(GovernanceClockSkew, match="before the server commit time"):
        await store.governance.append(stale)
    future = role_assertion(CORPUS, admin, reviewer.did, "reviewer", now + timedelta(hours=1))
    with pytest.raises(GovernanceClockSkew, match="after the server commit time"):
        await store.governance.append(future)
    assert await head(store) == 0

    fresh = role_assertion(CORPUS, admin, reviewer.did, "reviewer", datetime.now(UTC))
    assert (await store.governance.append(fresh)).position == 1


async def test_ae6_within_skew_accepted_and_window_is_commit_time(store, clock) -> None:
    admin, reviewer = new_identity(), new_identity()
    await store.governance.append(genesis(CORPUS, admin, m(0)))

    clock.at = m(10)
    # Signed four minutes before the commit: inside SIGNING_SKEW, accepted.
    grant = role_assertion(CORPUS, admin, reviewer.did, "reviewer", m(6))
    await store.governance.append(grant)
    assert (await committed_times(store))[1] == m(10)

    # The window opens at commit time m(10), not at signed_at m(6).
    before = await store.governance.query_active_roles_at(CORPUS, m(8))
    assert reviewer.did not in before
    after = await store.governance.query_active_roles_at(CORPUS, m(10))
    assert after[reviewer.did] == {"reviewer"}


async def test_skew_boundary_is_inclusive(store, clock) -> None:
    admin, reviewer = new_identity(), new_identity()
    await store.governance.append(genesis(CORPUS, admin, m(0)))
    clock.at = m(20)
    at_edge = role_assertion(CORPUS, admin, reviewer.did, "reviewer", m(20) - SIGNING_SKEW)
    await store.governance.append(at_edge)
    past_edge = role_revocation(
        CORPUS, admin, reviewer.did, "reviewer",
        m(20) - SIGNING_SKEW - timedelta(microseconds=1),
    )
    with pytest.raises(GovernanceClockSkew):
        await store.governance.append(past_edge)


async def test_missing_signed_at_is_refused(tmp_path: Path, clock) -> None:
    # The verifier is off so the event reaches the in-transaction skew check
    # (with it on, an untimed event never verifies in the first place).
    ctx = await CorpusStorageContext.open(
        tmp_path / "s", CORPUS, config=StorageConfig(event_verifier=None)
    )
    try:
        admin = new_identity()
        await ctx.governance.append(genesis(CORPUS, admin, m(0)))
        event = role_assertion(CORPUS, admin, new_identity().did, "reviewer", m(0))
        untimed = event.model_copy(
            update={"signature": event.signature.model_copy(update={"signed_at": None})}
        )
        with pytest.raises(GovernanceClockSkew, match="no signed_at"):
            await ctx.governance.append(untimed)
        assert await head(ctx) == 0
    finally:
        await ctx.close()


# ── role windows at server time ──────────────────────────────────────────


async def test_role_granted_at_T_is_not_usable_before_T(store, clock) -> None:
    admin, extractor = new_identity(), new_identity()
    await store.governance.append(genesis(CORPUS, admin, m(0)))

    # Before the grant commits, the extractor cannot act ...
    clock.at = m(10)
    with pytest.raises(NotAuthorized):
        await store.governance.append(extract(extractor, m(10)))

    # ... the grant commits at T = m(20), its signed_at backdated to m(16).
    clock.at = m(20)
    await store.governance.append(role_assertion(CORPUS, admin, extractor.did, "extractor", m(16)))

    # An event committed before T cannot use it, even signed before T: the
    # role window is the grant's commit time, so asof m(17) has no role.
    assert extractor.did not in await store.governance.query_active_roles_at(CORPUS, m(17))
    denied = await authorize(extractor.did, "extract", CORPUS, log=store.governance, asof=m(17))
    assert denied == Deny(reason="no_active_role")

    # At and after T it is usable.
    allowed = await authorize(extractor.did, "extract", CORPUS, log=store.governance, asof=m(20))
    assert isinstance(allowed, Allow)
    clock.at = m(21)
    assert (await store.governance.append(extract(extractor, m(18)))).position == 2


async def test_backdated_grant_cannot_authorize_earlier_committed_actions(store, clock) -> None:
    """Under signed_at windows a grant signed at m(16) "covered" m(16)..m(20);
    under server time it covers nothing committed before m(20)."""
    admin, extractor = new_identity(), new_identity()
    await store.governance.append(genesis(CORPUS, admin, m(0)))
    clock.at = m(20)
    await store.governance.append(role_assertion(CORPUS, admin, extractor.did, "extractor", m(16)))

    # Replaying an action as if committed at m(18) against the stored history
    # (windowed by committed_at) still refuses it.
    rows = await store._journal.governance_rows(CORPUS, upto=None)
    history = [storage_context._event_from_row(r) for r in rows]
    times = [datetime.fromisoformat(r.committed_at) for r in rows]
    snapshot = InMemoryGovernanceLog._from_history(CORPUS, history, committed_at=times)
    decision = await authorize(extractor.did, "extract", CORPUS, log=snapshot, asof=m(18))
    assert decision == Deny(reason="no_active_role")


async def test_revoked_admin_cannot_backdate_past_the_revocation(store, clock) -> None:
    """The Phase 7 bug R17 closes: windowed by signed_at, a revoked admin's
    assertion signed one minute before the revocation's signed_at passed the
    signer-must-be-admin check."""
    first, second, mallory = new_identity(), new_identity(), new_identity()
    await store.governance.append(genesis(CORPUS, first, m(0)))
    clock.at = m(1)
    await store.governance.append(role_assertion(CORPUS, first, second.did, "corpus_admin", m(1)))
    clock.at = m(10)
    await store.governance.append(role_revocation(CORPUS, second, first.did, "corpus_admin", m(10)))

    clock.at = m(11)
    backdated = role_assertion(CORPUS, first, mallory.did, "corpus_admin", m(9))
    with pytest.raises(NotAuthorized):
        await store.governance.append(backdated)
    assert await head(store) == 2


async def test_backwards_clock_never_hides_a_committed_revocation(store, clock) -> None:
    first, second, mallory = new_identity(), new_identity(), new_identity()
    await store.governance.append(genesis(CORPUS, first, m(0)))
    clock.at = m(1)
    await store.governance.append(role_assertion(CORPUS, first, second.did, "corpus_admin", m(1)))
    clock.at = m(30)
    await store.governance.append(role_revocation(CORPUS, second, first.did, "corpus_admin", m(30)))

    # The wall clock steps back an hour. The commit time is clamped to the
    # newest committed row, so the revocation stays visible.
    clock.at = m(-30)
    with pytest.raises(GovernanceClockSkew):
        await store.governance.append(role_assertion(CORPUS, first, mallory.did, "reviewer", m(-30)))
    with pytest.raises(NotAuthorized):
        await store.governance.append(role_assertion(CORPUS, first, mallory.did, "reviewer", m(30)))

    await store.governance.append(role_assertion(CORPUS, second, mallory.did, "reviewer", m(30)))
    times = await committed_times(store)
    assert times == sorted(times)
    assert times[-1] == m(30)


async def test_retrying_a_committed_operation_is_not_a_skew_refusal(store, clock) -> None:
    admin, reviewer = new_identity(), new_identity()
    await store.governance.append(genesis(CORPUS, admin, m(0)))
    grant = role_assertion(CORPUS, admin, reviewer.did, "reviewer", m(0))
    committed = await store.governance.append(grant, op_id="grant-1")
    clock.at = m(120)  # the signed_at is now far outside the skew
    again = await store.governance.append(grant, op_id="grant-1")
    assert again == committed
    assert await head(store) == 1


# ── replay of stored history ─────────────────────────────────────────────


async def test_replay_of_stored_history_gives_the_same_outcomes(tmp_path: Path, clock) -> None:
    root = tmp_path / "storage"
    a, b, c, d = (new_identity() for _ in range(4))
    script: list[tuple[float, GovernanceEvent]] = [
        (0, genesis(CORPUS, a, m(0))),
        (2, role_assertion(CORPUS, a, b.did, "corpus_admin", m(1))),
        (3, extract(c, m(3))),                                        # refused: no role
        (5, role_assertion(CORPUS, b, c.did, "extractor", m(4))),
        (6, extract(c, m(5), n=2)),                                   # accepted at m(6)
        (8, role_revocation(CORPUS, b, c.did, "extractor", m(8))),
        (9, extract(c, m(8), n=3)),                                   # refused: revoked
        (12, role_revocation(CORPUS, a, b.did, "corpus_admin", m(11))),
        (13, role_assertion(CORPUS, b, d.did, "reviewer", m(11))),    # refused: revoked
        (14, role_revocation(CORPUS, a, a.did, "corpus_admin", m(14))),  # refused: lockout
    ]
    outcomes: list[tuple[str, datetime, GovernanceEvent]] = []
    ctx = await CorpusStorageContext.open(root, CORPUS)
    try:
        for minute, event in script:
            clock.at = m(minute)
            try:
                await ctx.governance.append(event)
                outcomes.append(("ok", m(minute), event))
            except ValueError as exc:
                outcomes.append((type(exc).__name__, m(minute), event))
        live_roles = {
            minute: await ctx.governance.query_active_roles_at(CORPUS, m(minute))
            for minute in range(0, 16)
        }
    finally:
        await ctx.close()
    assert [o[0] for o in outcomes] == [
        "ok", "ok", "NotAuthorized", "ok", "ok", "ok", "NotAuthorized", "ok",
        "NotAuthorized", "WouldLockoutCorpusAdmin",
    ]

    # Reopen: the stored history and its commit times re-derive every
    # decision and every role window.
    ctx = await CorpusStorageContext.open(root, CORPUS)
    try:
        rows = await ctx._journal.governance_rows(CORPUS, upto=None)
        assert {
            minute: await ctx.governance.query_active_roles_at(CORPUS, m(minute))
            for minute in range(0, 16)
        } == live_roles
    finally:
        await ctx.close()
    history = [storage_context._event_from_row(r) for r in rows]
    times = [datetime.fromisoformat(r.committed_at) for r in rows]
    assert times == [at for verdict, at, _ in outcomes if verdict == "ok"]

    for verdict, at, event in outcomes:
        prior = [i for i, t in enumerate(times) if t < at]
        snapshot = InMemoryGovernanceLog._from_history(
            CORPUS, history[: len(prior)], committed_at=times[: len(prior)]
        )
        try:
            await storage_context._authorize_in_transaction(event, snapshot, CORPUS, at)
            await snapshot._append(event, server_time=at)
            replayed = "ok"
        except ValueError as exc:
            replayed = type(exc).__name__
        assert replayed == verdict, (verdict, at, event.action)


# ── what stays the same ──────────────────────────────────────────────────


async def test_signature_payload_and_verification_are_unchanged(store, clock) -> None:
    admin, reviewer = new_identity(), new_identity()
    await store.governance.append(genesis(CORPUS, admin, m(0)))
    clock.at = m(3)
    grant = role_assertion(CORPUS, admin, reviewer.did, "reviewer", m(1))
    persisted = await store.governance.append(grant)

    # signed_at stays inside the signed payload; the commit time is not in it.
    assert persisted.signature.signed_at == m(1)
    assert persisted.signature_payload() == grant.signature_payload()
    assert await verify_event_signature_offline(persisted)
    row = (await store._journal.governance_rows(CORPUS, upto=None))[1]
    assert "committed_at" not in json.loads(row.payload)
    assert m(3).isoformat() == row.committed_at

    # Moving signed_at after signing still fails verification.
    moved = persisted.model_copy(
        update={"signature": persisted.signature.model_copy(update={"signed_at": m(3)})}
    )
    assert not await verify_event_signature_offline(moved)


async def test_in_memory_log_without_server_clock_windows_by_signed_at() -> None:
    """Documented offline / test behaviour: no server clock, signed_at decides."""
    admin, reviewer = new_identity(), new_identity()
    log = InMemoryGovernanceLog()
    await log.append(genesis(CORPUS, admin, m(-120)))
    await log.append(role_assertion(CORPUS, admin, reviewer.did, "reviewer", m(-60)))
    # The backdated signed_at is honoured here (and only here).
    roles = await log.query_active_roles_at(CORPUS, m(-30))
    assert roles[reviewer.did] == {"reviewer"}
    assert reviewer.did not in await log.query_active_roles_at(CORPUS, m(-90))


async def test_in_memory_snapshot_with_server_times_windows_by_them() -> None:
    admin, reviewer = new_identity(), new_identity()
    log = InMemoryGovernanceLog()
    await log._append(genesis(CORPUS, admin, m(-120)), server_time=m(0))
    await log._append(
        role_assertion(CORPUS, admin, reviewer.did, "reviewer", m(-60)), server_time=m(5)
    )
    assert reviewer.did not in await log.query_active_roles_at(CORPUS, m(-30))
    assert reviewer.did in await log.query_active_roles_at(CORPUS, m(5))
    # An explicit accessor overrides the log's own times.
    by_signed_at = await active_roles_at(
        CORPUS, m(-30), log=log, event_time=lambda e: e.signature.signed_at
    )
    assert reviewer.did in by_signed_at


async def test_untimed_role_event_is_refused_by_the_in_memory_log() -> None:
    admin = new_identity()
    log = InMemoryGovernanceLog()
    await log.append(genesis(CORPUS, admin, m(0)))
    event = role_assertion(CORPUS, admin, new_identity().did, "reviewer", m(1))
    untimed = event.model_copy(
        update={"signature": event.signature.model_copy(update={"signed_at": None})}
    )
    with pytest.raises(NotAuthorized, match="no time"):
        await log.append(untimed)


def test_from_history_rejects_misaligned_commit_times() -> None:
    admin = new_identity()
    first = genesis(CORPUS, admin, m(0)).model_copy(update={"position": 0})
    with pytest.raises(ValueError, match="commit times"):
        InMemoryGovernanceLog._from_history(CORPUS, [first], committed_at=[])


def test_role_shape_context_uses_the_supplied_times() -> None:
    first, second, mallory = new_identity(), new_identity(), new_identity()
    history: list[GovernanceEvent] = [
        genesis(CORPUS, first, m(0)).model_copy(update={"position": 0}),
        role_assertion(CORPUS, first, second.did, "corpus_admin", m(1)).model_copy(
            update={"position": 1}
        ),
    ]
    pending = role_assertion(CORPUS, second, mallory.did, "reviewer", m(2)).model_copy(
        update={"position": 2}
    )
    # By signed_at the second admin's grant (m(1)) precedes m(2): conforms.
    assert validate_role_assertion_shape(pending, history=history).conforms
    # By server time the grant committed at m(9), after the pending m(3).
    server = {0: m(0), 1: m(9)}
    result = validate_role_assertion_shape(
        pending,
        history=history,
        event_time=lambda e: server[e.position],
        asof=m(3),
    )
    assert not result.conforms


def test_signing_skew_is_shared_with_the_framework_registry() -> None:
    from folio_insights.frameworks import registry
    from folio_insights.governance import clock

    assert registry.SIGNING_SKEW is clock.SIGNING_SKEW is SIGNING_SKEW
    assert SIGNING_SKEW == timedelta(minutes=5)
