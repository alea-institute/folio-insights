"""Drain U3 (R10, R20, KTD7) — seeding the kernel into a corpus.

Seeded shards pass the envelope model, the SHACL local and corpus tiers and
the FrameworkGuard; a second seed writes nothing; only a corpus admin can
seed a corpus that still needs the kernel frameworks.
"""
from __future__ import annotations

import dataclasses
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import folio_insights
from folio_insights.frameworks.registry import (
    LEDGER_KIND,
    FrameworkRegistrationRefused,
    load_registry,
    open_framework_checked_context,
    register_framework,
)
from folio_insights.identity.cache import InMemoryDidDocCache
from folio_insights.identity.verifier import verify_attestation
from folio_insights.kernel import seed as seed_module
from folio_insights.kernel.catalog import COLLECTIONS, KernelCatalog, dataset_sha256, load_catalog
from folio_insights.kernel.seed import (
    KERNEL_EPISTEMIC_STATUS,
    KERNEL_EXTRACTOR_MODEL,
    KERNEL_PREDICATE,
    KernelSeedError,
    _ranges,
    kernel_shard,
    seed_kernel,
    seed_op_id,
)
from folio_insights.models.framework import Framework, UnregisteredFramework
from folio_insights.shapes.suite import default_suite
from folio_insights.shards import SimpleAssertionShard, dump_shard_record, load_shard_record
from folio_insights.shards.minting import mint_shard_iri
from folio_insights.storage import CorpusStorageContext, OperationIdConflict

from tests.kernel.conftest import SeededCorpus, bootstrap_corpus
from tests.storage.conftest import new_identity, role_assertion


async def _all_shards(ctx: CorpusStorageContext) -> list:
    return [s async for s in ctx.shards.iter_shards()]


def test_first_seed_writes_every_maxim_and_registers_both_frameworks(
    seeded: SeededCorpus,
) -> None:
    first = seeded.first
    assert first.written == 299 and first.already_present == 0
    by_key = {c.collection: c for c in first.collections}
    assert len(by_key["liber_sextus"].written) == 88
    assert len(by_key["digest"].written) == 211
    assert all(c.framework_registered for c in first.collections)
    assert {c.framework_id for c in first.collections} == {
        "ius_commune.canon.liber_sextus", "ius_commune.roman.digest",
    }


def test_second_seed_writes_nothing(seeded: SeededCorpus) -> None:
    second = seeded.second
    assert second.written == 0 and second.already_present == 299
    assert not any(c.framework_registered for c in second.collections)


async def test_seeded_corpus_holds_exactly_the_kernel(seeded: SeededCorpus) -> None:
    ctx = await CorpusStorageContext.open(seeded.root, seeded.corpus)
    try:
        shards = await _all_shards(ctx)
        assert {s.shard_iri for s in shards} == load_catalog().manifest
        # 299 shard rows + 1 genesis event: the second seed appended nothing.
        assert await ctx.journal_head() == 299
        ledger = [e for e in await ctx.proposals.entries() if e.kind == LEDGER_KIND]
        assert sorted(e.payload["framework"]["id"] for e in ledger) == [
            "ius_commune.canon.liber_sextus", "ius_commune.roman.digest",
        ]
        registry = await load_registry(ctx)
        for spec in COLLECTIONS.values():
            assert registry.get(spec.framework.id) == spec.framework
    finally:
        await ctx.close()


async def test_seeded_shards_pass_every_gate(seeded: SeededCorpus) -> None:
    suite = default_suite()
    ctx, guard = await open_framework_checked_context(seeded.root, seeded.corpus)
    try:
        shards = await _all_shards(ctx)
        for shard in shards:
            # envelope model: the stored record re-validates as the subtype
            reloaded = load_shard_record(dump_shard_record(shard)).shard
            assert isinstance(reloaded, SimpleAssertionShard) and reloaded == shard
            report = suite.validate_shard(shard)  # SHACL local tier
            assert report.conforms and not report.results, report
            guard(shard)  # FrameworkGuard against the corpus registry
        validation = await ctx.validate_corpus()  # full suite + corpus tier
        assert validation.conforms and validation.violations == 0
        assert validation.warnings == 0 and validation.shards == 299
    finally:
        await ctx.close()


async def test_seeded_fields_follow_ktd7(seeded: SeededCorpus) -> None:
    catalog = load_catalog()
    ctx = await CorpusStorageContext.open(seeded.root, seeded.corpus)
    try:
        for maxim in (catalog.by_citation("VI 5.12.6"), catalog.by_citation("D.50.17.6")):
            assert maxim is not None
            shard = await ctx.shards.get(maxim.shard_iri)
            assert shard is not None
            spec = COLLECTIONS[maxim.collection]
            assert shard.shard_type == "simple_assertion"
            assert shard.provenance_hash == maxim.provenance_hash
            assert shard.source_uri == maxim.citation_uri
            assert shard.source_span == maxim.latin
            assert shard.layer == "L0_primitive"
            assert shard.speech_act == "statutory_text"
            assert shard.epistemic_status == KERNEL_EPISTEMIC_STATUS == "authority_only"
            assert shard.verification_method == "textual_citation"
            assert shard.predication_mode == "per_se"
            assert shard.fork == "synthetic_a_posteriori"
            assert shard.bfo_category == "continuant_dependent"
            assert shard.triple.subject == maxim.shard_iri
            assert shard.triple.predicate == KERNEL_PREDICATE
            assert shard.triple.object == maxim.latin
            assert shard.sense == maxim.latin
            assert shard.reference == maxim.reference
            assert shard.logical_form_imputed == "unanalysed"
            assert shard.confidence == 1.0
            assert shard.framework_id == spec.framework.id
            assert shard.valid_time_start == spec.valid_from
            assert shard.extractor_model == KERNEL_EXTRACTOR_MODEL
            assert shard.extractor_version == folio_insights.__version__
            assert shard.extraction_prompt_hash == dataset_sha256(maxim.collection)
            assert shard.first_extractor_did == seeded.admin.did
            assert shard.extracted_at == datetime.fromisoformat(
                maxim.provenance.retrieved_at.replace("Z", "+00:00")
            )
            assert shard.depends_on_axioms == [] and shard.elaborates == []
        digest6 = await ctx.shards.get(catalog.by_citation("D.50.17.6").shard_iri)
        assert digest6.reference == "D.50.17.6 (Ulpianus libro septimo ad Sabinum)"
        assert COLLECTIONS["liber_sextus"].valid_from == datetime(1298, 3, 3, tzinfo=UTC)
        assert COLLECTIONS["digest"].valid_from == datetime(533, 12, 16, tzinfo=UTC)
    finally:
        await ctx.close()


async def test_seeded_extract_signatures_verify(seeded: SeededCorpus) -> None:
    catalog = load_catalog()
    ctx = await CorpusStorageContext.open(seeded.root, seeded.corpus)
    try:
        cache = InMemoryDidDocCache()
        for maxim in catalog.maxims[:5] + catalog.maxims[-5:]:
            shard = await ctx.shards.get(maxim.shard_iri)
            assert len(shard.signatures) == 1
            sig = shard.signatures[0]
            assert sig.did == seeded.admin.did and sig.action == "extract"
            assert await verify_attestation(shard, sig, cache=cache)
            tampered = shard.model_copy(update={"sense": "Nemo tenetur."})
            assert not await verify_attestation(tampered, sig, cache=cache)
    finally:
        await ctx.close()


def test_kernel_shard_is_deterministic_for_fixed_inputs() -> None:
    admin = new_identity()
    maxim = load_catalog().by_citation("VI 5.12.6")
    when = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    a = kernel_shard(maxim, extractor_did=admin.did, signing_key=admin.sk, signed_at=when)
    b = kernel_shard(maxim, extractor_did=admin.did, signing_key=admin.sk, signed_at=when)
    exclude = {"transaction_time"}
    assert a.model_dump(exclude=exclude) == b.model_dump(exclude=exclude)
    unsigned = kernel_shard(maxim, extractor_did=admin.did)
    assert unsigned.signatures == []
    with pytest.raises(KernelSeedError, match="not the did:key"):
        kernel_shard(maxim, extractor_did=new_identity().did, signing_key=admin.sk)


def test_seed_op_ids_are_compact_and_deterministic() -> None:
    assert _ranges([1, 2, 3, 5, 7, 8]) == "1-3,5,7-8"
    assert _ranges([3, 1, 2, 2]) == "1-3"
    ls = load_catalog().collection("liber_sextus")
    sha = dataset_sha256("liber_sextus")[:16]
    assert seed_op_id("liber_sextus", ls) == f"kernel-seed:liber_sextus:{sha}:1-88"
    assert seed_op_id("liber_sextus", [ls[5], ls[0]]) == f"kernel-seed:liber_sextus:{sha}:1,6"
    # The dataset revision is part of the identity of the batch.
    other = "ab" * 32
    assert seed_op_id("liber_sextus", ls, dataset_sha256=other) == (
        "kernel-seed:liber_sextus:abababababababab:1-88"
    )
    with pytest.raises(ValueError):
        seed_op_id("digest", [])


async def test_partial_then_full_seed_by_another_admin(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    admin, second_admin = new_identity(), new_identity()
    await bootstrap_corpus(root, "c", admin)
    ctx = await CorpusStorageContext.open(root, "c")
    try:
        # Signed at the real clock, after the genesis event (R17 server-time check).
        when = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
        await ctx.governance.append(
            role_assertion("c", admin, second_admin.did, "corpus_admin", when)
        )
    finally:
        await ctx.close()

    only_ls = await seed_kernel(root, "c", signing_key=admin.sk, collections=["liber_sextus"])
    assert only_ls.written == 88
    assert [c.collection for c in only_ls.collections] == ["liber_sextus"]
    full = await seed_kernel(root, "c", signing_key=second_admin.sk)
    by_key = {c.collection: c for c in full.collections}
    assert len(by_key["liber_sextus"].already_present) == 88  # seeded by the other admin
    assert len(by_key["digest"].written) == 211
    assert not by_key["liber_sextus"].framework_registered
    assert by_key["digest"].framework_registered

    ctx = await CorpusStorageContext.open(root, "c")
    try:
        ls6 = await ctx.shards.get(load_catalog().by_citation("VI 5.12.6").shard_iri)
        d6 = await ctx.shards.get(load_catalog().by_citation("D.50.17.6").shard_iri)
        assert ls6.first_extractor_did == admin.did  # never re-attributed
        assert d6.first_extractor_did == second_admin.did
        head = await ctx.journal_head()
    finally:
        await ctx.close()
    again = await seed_kernel(root, "c", signing_key=admin.sk)
    assert again.written == 0
    ctx = await CorpusStorageContext.open(root, "c")
    try:
        assert await ctx.journal_head() == head
    finally:
        await ctx.close()


async def test_non_admin_seed_is_refused_before_any_write(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    admin, stranger = new_identity(), new_identity()
    await bootstrap_corpus(root, "c", admin)
    ctx = await CorpusStorageContext.open(root, "c")
    try:
        head = await ctx.journal_head()
    finally:
        await ctx.close()
    with pytest.raises(FrameworkRegistrationRefused, match="corpus_admin"):
        await seed_kernel(root, "c", signing_key=stranger.sk)
    ctx = await CorpusStorageContext.open(root, "c")
    try:
        assert await ctx.journal_head() == head
        assert await ctx.proposals.head() == -1
    finally:
        await ctx.close()


async def test_mismatched_did_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    admin = new_identity()
    await bootstrap_corpus(root, "c", admin)
    with pytest.raises(KernelSeedError, match="not the did:key"):
        await seed_kernel(root, "c", signing_key=admin.sk, did=new_identity().did)


async def test_conflicting_framework_definition_refuses_the_seed(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    admin = new_identity()
    await bootstrap_corpus(root, "c", admin)
    ctx, _guard = await open_framework_checked_context(root, "c")
    try:
        other = Framework(id="ius_commune.roman.digest", label="Some other Digest",
                          jurisdiction="ius_commune")
        await register_framework(ctx, other, signing_key=admin.sk, did=admin.did)
    finally:
        await ctx.close()
    with pytest.raises(KernelSeedError, match="different definition"):
        await seed_kernel(root, "c", signing_key=admin.sk)
    ctx = await CorpusStorageContext.open(root, "c")
    try:
        assert await _all_shards(ctx) == []
    finally:
        await ctx.close()


async def test_framework_guard_refuses_a_kernel_shard_without_its_framework(
    tmp_path: Path,
) -> None:
    root = tmp_path / "storage"
    admin = new_identity()
    await bootstrap_corpus(root, "c", admin)
    maxim = load_catalog().by_citation("VI 5.12.6")
    shard = kernel_shard(maxim, extractor_did=admin.did, signing_key=admin.sk)
    ctx, _guard = await open_framework_checked_context(root, "c")
    try:
        with pytest.raises(UnregisteredFramework, match="ius_commune.canon.liber_sextus"):
            await ctx.ingest_shards([shard])
    finally:
        await ctx.close()


async def test_unknown_collection_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    admin = new_identity()
    await bootstrap_corpus(root, "c", admin)
    with pytest.raises(KeyError, match="gratian"):
        await seed_kernel(root, "c", signing_key=admin.sk, collections=["gratian"])


# ── dataset revisions and the race loser (review fix B) ─────────────────────


def _revised_catalog(changes: dict[int, str], tag: str) -> KernelCatalog:
    """The packaged catalog with some Liber Sextus maxims' Latin corrected.

    A corrected transcription mints a new IRI under the same maxim number, and the
    dataset file's bytes (so its SHA-256) change; both are simulated here.
    """
    base = load_catalog()
    maxims = []
    for m in base.maxims:
        if m.collection == "liber_sextus" and m.number in changes:
            latin = changes[m.number]
            iri, provenance_hash = mint_shard_iri(m.citation_uri, latin)
            m = dataclasses.replace(m, latin=latin, shard_iri=iri,
                                    provenance_hash=provenance_hash)
        maxims.append(m)
    digests = dict(base.dataset_sha256)
    digests["liber_sextus"] = hashlib.sha256(
        (digests["liber_sextus"] + tag).encode()).hexdigest()
    return KernelCatalog(tuple(maxims), base.excluded, digests)


async def test_a_dataset_revision_seeds_under_a_new_operation_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrected Latin for already-seeded numbers lands; it never collides with the
    earlier batch's operation ID (which encoded only the maxim numbers)."""
    root = tmp_path / "storage"
    admin = new_identity()
    await bootstrap_corpus(root, "c", admin)
    first = await seed_kernel(root, "c", signing_key=admin.sk, collections=["liber_sextus"])
    assert first.written == 88

    ls = load_catalog().collection("liber_sextus")
    every = _revised_catalog({m.number: m.latin + " (lectio emendata)" for m in ls}, "all")
    monkeypatch.setattr(seed_module, "load_catalog", lambda: every)
    revised = await seed_kernel(root, "c", signing_key=admin.sk, collections=["liber_sextus"])
    assert revised.written == 88 and revised.already_present == 0

    # Two successive corrections of one maxim: each is its own batch.
    for n, tag in ((1, "rev-a"), (2, "rev-b")):
        one = _revised_catalog({5: f"{ls[4].latin} (emendatio {n})"}, tag)
        monkeypatch.setattr(seed_module, "load_catalog", lambda one=one: one)
        again = await seed_kernel(root, "c", signing_key=admin.sk, collections=["liber_sextus"])
        assert again.written == 1, tag
        assert again.already_present == 87, tag


async def test_race_loser_reports_already_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two admins seeding one corpus at once: the loser's batch is refused as an
    operation-ID replay mismatch, and it reports the winner's maxims as present."""
    root = tmp_path / "storage"
    admin, rival = new_identity(), new_identity()
    await bootstrap_corpus(root, "c", admin)
    ctx = await CorpusStorageContext.open(root, "c")
    try:
        when = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
        await ctx.governance.append(role_assertion("c", admin, rival.did, "corpus_admin", when))
    finally:
        await ctx.close()

    real_ingest = CorpusStorageContext.ingest_shards
    raced = []

    async def ingest_after_rival(self, records, *, op_id=None):  # noqa: ANN001, ANN202
        if not raced:  # the loser: the rival commits the same batch first
            raced.append(op_id)
            monkeypatch.setattr(CorpusStorageContext, "ingest_shards", real_ingest)
            winner = await seed_kernel(root, "c", signing_key=rival.sk,
                                       collections=["liber_sextus"])
            assert winner.written == 88
        return await real_ingest(self, records, op_id=op_id)

    monkeypatch.setattr(CorpusStorageContext, "ingest_shards", ingest_after_rival)
    loser = await seed_kernel(root, "c", signing_key=admin.sk, collections=["liber_sextus"])
    assert raced and raced[0].startswith("kernel-seed:liber_sextus:")
    assert loser.written == 0 and loser.already_present == 88
    ctx = await CorpusStorageContext.open(root, "c")
    try:
        ls6 = await ctx.shards.get(load_catalog().by_citation("VI 5.12.6").shard_iri)
        assert ls6.first_extractor_did == rival.did  # the winner's batch, once
        assert len([s async for s in ctx.shards.iter_shards()]) == 88
    finally:
        await ctx.close()


async def test_operation_id_conflict_with_maxims_still_missing_is_a_seed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "storage"
    admin = new_identity()
    await bootstrap_corpus(root, "c", admin)

    async def conflicting(self, records, *, op_id=None):  # noqa: ANN001, ANN202
        raise OperationIdConflict(f"operation ID {op_id!r} was already committed")

    monkeypatch.setattr(CorpusStorageContext, "ingest_shards", conflicting)
    with pytest.raises(KernelSeedError, match="88 of 88 liber_sextus maxims are still missing"):
        await seed_kernel(root, "c", signing_key=admin.sk, collections=["liber_sextus"])
