"""Phase 9 U2 (R5) — write-time framework checks, signed admin registration,
valid-time windows and the temporal "FRE 702 at T" query.

Disposable corpus roots, generated identities, synthetic shards.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from folio_insights.cli import cli
from folio_insights.frameworks.query import shards_in_framework_at
from folio_insights.frameworks.registry import (
    LEDGER_KIND,
    FrameworkRegistrationRefused,
    load_registry,
    open_framework_checked_context,
    register_framework,
    sign_registration,
    verify_registration,
)
from folio_insights.frameworks.valid_time import (
    SourceTimeMetadata,
    infer_valid_time,
    statute_windows,
)
from folio_insights.identity.keys import generate_keypair, load_signing_key
from folio_insights.models.framework import (
    Framework,
    MalformedFrameworkId,
    UnregisteredFramework,
)
from folio_insights.storage import CorpusStorageContext

from tests.storage.conftest import Identity, at, genesis, new_identity, role_assertion, shard
from tests.storage.conftest import fresh_signing_clock  # noqa: F401  (autouse: sign at now, R17)

DGCL = Framework(id="us.delaware.dgcl", label="Delaware General Corporation Law",
                 jurisdiction="us.delaware")


async def _seed(root: Path, admin: Identity, reviewer: Identity | None = None) -> None:
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        await ctx.governance.append(genesis("corpus-a", admin, at(0)))
        if reviewer is not None:
            await ctx.governance.append(
                role_assertion("corpus-a", admin, reviewer.did, "reviewer", at(1))
            )
    finally:
        await ctx.close()


async def test_unregistered_or_malformed_id_is_refused_at_write(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    await _seed(root, new_identity())
    ctx, guard = await open_framework_checked_context(root, "corpus-a")
    try:
        head = await ctx.journal_head()
        with pytest.raises(UnregisteredFramework, match="us.delaware.dgcl"):
            await ctx.shards.put(shard(1).shard_iri, shard(1, framework_id="us.delaware.dgcl"))
        with pytest.raises(MalformedFrameworkId):
            await ctx.shards.put(shard(2).shard_iri, shard(2, framework_id="US Federal"))
        with pytest.raises(UnregisteredFramework):
            await ctx.ingest_shards([shard(3, framework_id="us.federal.fre"),
                                     shard(4, framework_id="standin.unknown")])
        assert await ctx.journal_head() == head  # journal unchanged
        await ctx.shards.put(shard(5).shard_iri, shard(5, framework_id="us.federal.fre"))
        assert await ctx.journal_head() == head + 1
    finally:
        await ctx.close()


async def test_admin_registration_extends_the_corpus_registry(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    admin = new_identity()
    await _seed(root, admin)
    ctx, guard = await open_framework_checked_context(root, "corpus-a")
    try:
        registration = await register_framework(
            ctx, DGCL, signing_key=admin.sk, did=admin.did
        )
        assert verify_registration(registration)
        assert registration.signer_did == admin.did
        await guard.refresh(ctx)
        await ctx.shards.put(shard(1).shard_iri, shard(1, framework_id="us.delaware.dgcl"))
        # a retry commits once; a different definition under the same ID refuses
        again = await register_framework(
            ctx, DGCL, signing_key=admin.sk, did=admin.did
        )
        assert again == registration
        entries = [e for e in await ctx.proposals.entries() if e.kind == LEDGER_KIND]
        assert len(entries) == 1
        with pytest.raises(ValueError, match="already registered"):
            await register_framework(
                ctx, DGCL.model_copy(update={"label": "Other"}), signing_key=admin.sk,
                did=admin.did,
            )
    finally:
        await ctx.close()

    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        assert "us.delaware.dgcl" in await load_registry(ctx)  # persisted per corpus
    finally:
        await ctx.close()
    other = await CorpusStorageContext.open(root, "corpus-b")
    try:
        assert "us.delaware.dgcl" not in await load_registry(other)  # not leaked
    finally:
        await other.close()


async def test_registering_without_the_admin_role_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    admin, reviewer, stranger = new_identity(), new_identity(), new_identity()
    await _seed(root, admin, reviewer)
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        for who in (reviewer, stranger):
            with pytest.raises(FrameworkRegistrationRefused, match="corpus_admin"):
                await register_framework(ctx, DGCL, signing_key=who.sk, did=who.did)
        # an admin key signing under someone else's DID never verifies
        forged = sign_registration("corpus-a", DGCL, signing_key=stranger.sk, did=admin.did)
        assert not verify_registration(forged)
        assert await ctx.proposals.head() == -1  # nothing appended
    finally:
        await ctx.close()


def test_tampered_registration_does_not_verify() -> None:
    admin = new_identity()
    reg = sign_registration("corpus-a", DGCL, signing_key=admin.sk, did=admin.did)
    assert verify_registration(reg)
    assert not verify_registration(reg.model_copy(update={"corpus": "corpus-b"}))
    assert not verify_registration(
        reg.model_copy(update={"framework": DGCL.model_copy(update={"label": "x"})})
    )


# ── valid time ────────────────────────────────────────────────────────────


def test_statute_with_effective_and_amendment_dates_yields_windows() -> None:
    meta = SourceTimeMetadata(
        kind="statute", effective_date=date(1975, 7, 1),
        amendment_dates=(date(2023, 12, 1), date(2000, 12, 1)), repeal_date=date(2030, 1, 1),
    )
    windows = statute_windows(meta)
    assert [(w.start.date(), w.end.date()) for w in windows] == [
        (date(1975, 7, 1), date(2000, 12, 1)),
        (date(2000, 12, 1), date(2023, 12, 1)),
        (date(2023, 12, 1), date(2030, 1, 1)),
    ]
    assert windows[0].evidence == ("effective_date=1975-07-01", "next amendment_date=2000-12-01")
    assert windows[-1].evidence[-1] == "repeal_date=2030-01-01"
    mid = infer_valid_time(meta.model_copy(update={"version_date": date(2010, 6, 1)}))
    assert (mid.start.date(), mid.end.date()) == (date(2000, 12, 1), date(2023, 12, 1))
    assert "version_date=2010-06-01" in mid.evidence
    latest = infer_valid_time(meta)
    assert latest.start.date() == date(2023, 12, 1) and "latest version" in latest.evidence[-1]
    assert infer_valid_time(meta.model_copy(update={"version_date": date(1900, 1, 1)})) is None


def test_case_and_restatement_windows_record_evidence() -> None:
    case = infer_valid_time(SourceTimeMetadata(kind="case", decision_date=date(1993, 6, 28),
                                               overruled_date=date(2010, 1, 1)))
    assert (case.start.date(), case.end.date()) == (date(1993, 6, 28), date(2010, 1, 1))
    rest = infer_valid_time(SourceTimeMetadata(kind="restatement", publication_year=1981))
    assert rest.start == datetime(1981, 1, 1, tzinfo=UTC) and rest.end is None
    assert rest.evidence == ("publication_year=1981",)
    assert infer_valid_time(SourceTimeMetadata()) is None


async def test_fre_702_at_t_returns_the_right_shard(tmp_path: Path) -> None:
    windows = statute_windows(SourceTimeMetadata(
        kind="rules", effective_date=date(1975, 7, 1),
        amendment_dates=(date(2000, 12, 1), date(2023, 12, 1)),
    ))
    shards = [
        shard(10 + i, framework_id="us.federal.fre", reference="fre:rule702",
              sense=f"rule 702 version {i}", valid_time_start=w.start, valid_time_end=w.end)
        for i, w in enumerate(windows)
    ] + [shard(20, framework_id="us.federal.frcp", reference="fre:rule702",
               valid_time_start=windows[0].start)]
    root = tmp_path / "storage"
    ctx, _guard = await open_framework_checked_context(root, "corpus-a")
    try:
        await ctx.ingest_shards(shards)
        for when, expected in [
            (date(1980, 1, 1), "rule 702 version 0"),
            (date(2000, 12, 1), "rule 702 version 1"),  # half-open: the boundary moves on
            (date(2023, 11, 30), "rule 702 version 1"),
            (date(2025, 1, 1), "rule 702 version 2"),
        ]:
            rows = await shards_in_framework_at(ctx, "us.federal.fre", when, reference="fre:rule702")
            assert [sense for _iri, sense in rows] == [expected], when
        assert await shards_in_framework_at(ctx, "us.federal.fre", date(1960, 1, 1)) == []
        with pytest.raises(MalformedFrameworkId):
            await shards_in_framework_at(ctx, "FRE } INSERT", date(2025, 1, 1))
    finally:
        await ctx.close()


# ── CLI ───────────────────────────────────────────────────────────────────


def test_cli_register_list_export(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    admin_key = tmp_path / "admin.jwk"
    admin_did = generate_keypair(admin_key)
    admin = Identity(load_signing_key(admin_key), admin_did)
    other_key = tmp_path / "other.jwk"
    generate_keypair(other_key)
    asyncio.run(_seed(root, admin))
    runner = CliRunner()
    common = ["--corpus", "corpus-a", "--corpus-root", str(root)]

    refused = runner.invoke(cli, ["framework", "register", "us.delaware.dgcl", "--label", "DGCL",
                                  "--jurisdiction", "us.delaware", "--key-path", str(other_key),
                                  *common])
    assert refused.exit_code == 1 and "corpus_admin" in refused.output

    bad = runner.invoke(cli, ["framework", "register", "us.delaware.dgcl.2024", "--label", "x",
                              "--jurisdiction", "us.delaware", "--key-path", str(admin_key),
                              *common])
    assert bad.exit_code == 2

    ok = runner.invoke(cli, ["framework", "register", "us.delaware.dgcl", "--label", "DGCL",
                             "--jurisdiction", "us.delaware", "--key-path", str(admin_key),
                             *common])
    assert ok.exit_code == 0, ok.output
    listed = runner.invoke(cli, ["framework", "list", *common])
    assert listed.exit_code == 0 and "us.delaware.dgcl" in listed.output
    out = tmp_path / "frameworks.ttl"
    exported = runner.invoke(cli, ["framework", "export", "--out", str(out), *common])
    assert exported.exit_code == 0 and "skos:ConceptScheme" in out.read_text()
    missing = runner.invoke(cli, ["framework", "list", "--corpus", "nope", "--corpus-root",
                                  str(root)])
    assert missing.exit_code == 1


# ── review P1: registration is bound to ledger-controlled time ─────────────


async def _seed_revoked(root: Path) -> tuple[Identity, Identity]:
    from tests.storage.conftest import role_revocation

    admin, former = new_identity(), new_identity()
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        await ctx.governance.append(genesis("corpus-a", admin, at(0)))
        await ctx.governance.append(role_assertion("corpus-a", admin, former.did, "corpus_admin", at(1)))
        await ctx.governance.append(role_revocation("corpus-a", admin, former.did, "corpus_admin", at(10)))
    finally:
        await ctx.close()
    return admin, former


async def test_revoked_admin_cannot_register_with_a_backdated_time(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    _admin, former = await _seed_revoked(root)
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        with pytest.raises(FrameworkRegistrationRefused):
            await register_framework(ctx, DGCL, signing_key=former.sk, did=former.did)
        # ``at()`` is anchored at the real clock (R17 fixtures), so an hour
        # back is what "backdated" means here.
        with pytest.raises(FrameworkRegistrationRefused, match="not within"):
            await register_framework(
                ctx, DGCL, signing_key=former.sk, did=former.did, now=at(-3600)
            )
        with pytest.raises(TypeError):
            await register_framework(  # the old caller-chosen signing time is gone
                ctx, DGCL, signing_key=former.sk, did=former.did, signed_at=at(5)  # type: ignore[call-arg]
            )
        # a backdated row appended straight to the ledger is refused on load
        forged = sign_registration("corpus-a", DGCL, signing_key=former.sk, did=former.did,
                                   signed_at=at(-3600))
        await ctx.proposals.append(LEDGER_KIND, forged.model_dump(mode="json"), op_id="forged")
        with pytest.raises(FrameworkRegistrationRefused, match="commit time"):
            await load_registry(ctx)
    finally:
        await ctx.close()


async def test_current_time_row_from_a_revoked_admin_is_refused_on_load(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    _admin, former = await _seed_revoked(root)
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        row = sign_registration("corpus-a", DGCL, signing_key=former.sk, did=former.did)
        await ctx.proposals.append(LEDGER_KIND, row.model_dump(mode="json"), op_id="direct")
        with pytest.raises(FrameworkRegistrationRefused, match="not a corpus admin"):
            await load_registry(ctx)
    finally:
        await ctx.close()


async def test_non_admin_row_appended_directly_is_refused_on_load(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    reviewer = new_identity()
    await _seed(root, new_identity(), reviewer)
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        row = sign_registration("corpus-a", DGCL, signing_key=reviewer.sk, did=reviewer.did)
        await ctx.proposals.append(LEDGER_KIND, row.model_dump(mode="json"), op_id="direct")
        with pytest.raises(FrameworkRegistrationRefused, match="not a corpus admin"):
            await load_registry(ctx)
    finally:
        await ctx.close()


async def test_registration_replayed_into_another_corpus_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    admin = new_identity()
    await _seed(root, admin)
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        registration = await register_framework(ctx, DGCL, signing_key=admin.sk, did=admin.did)
    finally:
        await ctx.close()
    other = await CorpusStorageContext.open(root, "corpus-b")
    try:
        await other.governance.append(genesis("corpus-b", admin, at(0)))  # same admin there too
        await other.proposals.append(LEDGER_KIND, registration.model_dump(mode="json"), op_id="replay")
        with pytest.raises(FrameworkRegistrationRefused, match="this corpus"):
            await load_registry(other)
    finally:
        await other.close()


@pytest.mark.parametrize("bad", ["us.federal.fre\n", "us.federal.fre\r\n", "us.ucc\n"])
def test_framework_ids_with_trailing_newlines_are_malformed(bad: str) -> None:
    from folio_insights.models.framework import check_framework_id

    with pytest.raises(MalformedFrameworkId):
        check_framework_id(bad)
    with pytest.raises(ValueError):
        Framework(id=bad, label="x", jurisdiction="us")


def test_framework_iris_never_collide_with_namespace_or_scheme() -> None:
    from folio_insights.models.framework import FRAMEWORK_SCHEME_IRI
    from folio_insights.vocab._constants import FRAMEWORK_NS, framework_iri

    with pytest.raises(ValueError):
        framework_iri("")
    assert framework_iri("scheme") != FRAMEWORK_SCHEME_IRI
    assert not FRAMEWORK_SCHEME_IRI.startswith(FRAMEWORK_NS)
