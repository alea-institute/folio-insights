"""Phase 11 U4: full SHACL on every storage write, and an honest full_shacl.

* Violations refuse put, ingest, bulk load (in-process and pooled) and
  governance appends, and leave the journal and projection unchanged.
* Warnings never refuse.
* ``status().full_shacl`` moves through ``disabled``, ``unvalidated``,
  ``pass`` and ``fail`` only on evidence. A suite-less write, a changed suite
  or a restore makes it ``unvalidated``. A cross-shard violation makes it
  ``fail``, and fixing it returns it to ``pass``.
* ``validate_corpus`` (compiled and pyshacl engines) and the CLI record the
  result.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from folio_insights.shapes.suite import SUITE_PATHS, ShaclSuite, default_suite
from folio_insights.storage import (
    CorpusStorageContext,
    ShaclViolation,
    StorageConfig,
)
from folio_insights.storage.shacl_status import MarkerStore
from tests.storage.conftest import at, genesis, new_identity, open_ctx, role_assertion, shard

pytestmark = pytest.mark.storage

T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 6, 1, tzinfo=UTC)


def inverted(n: int):  # noqa: ANN201
    """A model-valid shard the suite refuses (valid_time_start >= end)."""
    return shard(n, valid_time_start=T2, valid_time_end=T1)


async def _count(ctx: CorpusStorageContext) -> int:
    rows = await ctx.query("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }")
    return int(rows[0]["n"].value)


@pytest.mark.parametrize("path", ["put", "ingest", "bulk_pooled", "bulk_in_process"])
async def test_violation_refuses_every_shard_path(storage_root: Path, path: str) -> None:
    ctx = await open_ctx(storage_root)
    try:
        await ctx.shards.put(shard(0).shard_iri, shard(0))
        head, triples = (await ctx.status()).journal_head, await _count(ctx)
        count = 2100 if path.startswith("bulk") else 3
        records = [shard(n) for n in range(1, count)] + [inverted(count)]
        with pytest.raises(ShaclViolation) as info:
            if path == "put":
                await ctx.shards.put(records[-1].shard_iri, records[-1])
            elif path == "ingest":
                await ctx.ingest_shards(records)
            else:
                await ctx.bulk_load_shards(records, parallel=path == "bulk_pooled")
        assert "fi:validTimeStart must be earlier" in str(info.value)
        assert info.value.results[0]["component"] == "LessThanConstraintComponent"
        assert "value" not in info.value.results[0]
        status = await ctx.status()
        assert status.journal_head == head
        assert await _count(ctx) == triples
        assert status.full_shacl == "pass"
    finally:
        await ctx.close()


async def test_shacl_runs_before_the_generic_hook_and_earliest_refusal_wins(
    storage_root: Path,
) -> None:
    seen: list[str] = []

    def hook(s) -> None:  # noqa: ANN001
        seen.append(s.shard_iri)
        if s.shard_iri == shard(5).shard_iri:
            raise RuntimeError("hook refusal")

    ctx = await open_ctx(storage_root, shard_validator=hook)
    try:
        with pytest.raises(ShaclViolation):
            await ctx.ingest_shards([shard(1), inverted(2), shard(5)])
        assert seen == [shard(1).shard_iri]  # the SHACL refusal of record 2 came first
        seen.clear()
        records = [shard(n) for n in range(10, 2110)]
        records[3] = shard(5)       # hook refusal at index 3
        records[2000] = inverted(9)  # SHACL refusal later, in another pool chunk
        with pytest.raises(RuntimeError, match="hook refusal"):
            await ctx.bulk_load_shards(records, parallel=True)
    finally:
        await ctx.close()


async def test_warnings_never_refuse(storage_root: Path) -> None:
    ctx = await open_ctx(storage_root)
    try:
        # Unsigned, contested with one vote, hand-made IRI: Warnings only.
        odd = shard(
            1, shard_iri="fi:shard:handmade", contested=True,
            epistemic_status="contested", contest_votes={"did:key:zA": "for"},
        )
        await ctx.shards.put(odd.shard_iri, odd)
        status = await ctx.status()
        assert status.journal_head == 0 and status.full_shacl == "pass"
        result = await ctx.validate_corpus()
        assert result.conforms and result.warnings == 3  # unsigned, IRI form, one vote
        assert (await ctx.status()).shacl_warnings == result.warnings
    finally:
        await ctx.close()


EXTRA_SHAPE = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/> .
@prefix fis: <https://folio-insights.aleainstitute.ai/shapes/> .
fis:NoReviewerGrantsShape a sh:NodeShape ;
    sh:targetClass fi:GovernanceEvent ;
    sh:property [ sh:path fi:role ; sh:not [ sh:hasValue "reviewer" ] ;
                  sh:message "synthetic test rule: no reviewer grants" ] .
"""


async def test_governance_event_violation_refuses_inside_the_transaction(
    storage_root: Path, tmp_path: Path, admin
) -> None:  # noqa: ANN001
    extra = tmp_path / "extra.shacl.ttl"
    extra.write_text(EXTRA_SHAPE)
    suite = ShaclSuite([*SUITE_PATHS, extra])
    ctx = await open_ctx(storage_root, shacl=suite)
    try:
        await ctx.governance.append(genesis("corpus-a", admin))
        with pytest.raises(ShaclViolation, match="no reviewer grants"):
            await ctx.governance.append(
                role_assertion("corpus-a", admin, new_identity().did, "reviewer", at(5))
            )
        await ctx.governance.append(
            role_assertion("corpus-a", admin, new_identity().did, "arbiter", at(6))
        )
        status = await ctx.status()
        assert status.journal_head == 1
        assert status.full_shacl == "pass"
        assert status.shacl_suite_digest == suite.digest != default_suite().digest
    finally:
        await ctx.close()
    # The default suite did not validate those rows: a different digest.
    ctx = await open_ctx(storage_root)
    try:
        assert (await ctx.status()).full_shacl == "unvalidated"
        assert (await ctx.validate_corpus()).conforms
        assert (await ctx.status()).full_shacl == "pass"
    finally:
        await ctx.close()


async def test_status_lifecycle(storage_root: Path) -> None:
    disabled = await open_ctx(storage_root, shacl=None)
    try:
        assert (await disabled.status()).full_shacl == "disabled"
    finally:
        await disabled.close()

    ctx = await open_ctx(storage_root)
    try:
        assert (await ctx.status()).full_shacl == "pass"  # empty corpus
        await ctx.shards.put(shard(1).shard_iri, shard(1))
        status = await ctx.status()
        assert (status.full_shacl, status.shacl_validated_through) == ("pass", 0)
    finally:
        await ctx.close()

    # A write the suite never saw (and that it would refuse).
    off = await open_ctx(storage_root, shacl=None)
    try:
        await off.shards.put(inverted(2).shard_iri, inverted(2))
    finally:
        await off.close()

    ctx = await open_ctx(storage_root)
    try:
        assert (await ctx.status()).full_shacl == "unvalidated"
        # Later writes are not contiguous with the marker: still unvalidated.
        await ctx.shards.put(shard(3).shard_iri, shard(3))
        assert (await ctx.status()).full_shacl == "unvalidated"
        result = await ctx.validate_corpus()
        assert not result.conforms
        assert {r["focus"] for r in result.results} == {inverted(2).shard_iri}
        status = await ctx.status()
        assert (status.full_shacl, status.shacl_violations) == ("fail", 1)
        # Revising the bad shard under the suite clears its local failure.
        fixed = shard(2, valid_time_start=T1, valid_time_end=T2)
        await ctx.shards.put(fixed.shard_iri, fixed)
        assert (await ctx.status()).full_shacl == "pass"
    finally:
        await ctx.close()


async def test_cross_shard_violation_reports_fail_then_pass_when_fixed(storage_root: Path) -> None:
    ctx = await open_ctx(storage_root)
    try:
        b = shard(2)  # still current: no valid_time_end
        a = shard(1, supersedes=b.shard_iri, valid_time_start=T2)
        await ctx.shards.put(b.shard_iri, b)
        await ctx.shards.put(a.shard_iri, a)  # committed, not refused (corpus tier)
        status = await ctx.status()
        assert (status.full_shacl, status.shacl_violations) == ("fail", 1)
        assert not (await ctx.validate_corpus()).conforms

        # Close B's interval, point back: the incremental re-check of the
        # failing node and B's neighbours returns the corpus to pass.
        b2 = shard(2, valid_time_end=T2, superseded_by=a.shard_iri, epistemic_status="superseded")
        await ctx.shards.put(b2.shard_iri, b2)
        status = await ctx.status()
        assert (status.full_shacl, status.shacl_violations) == ("pass", 0)
        assert (await ctx.validate_corpus()).conforms

        # Breaking B again is caught from B's side (A is B's neighbour).
        b3 = b2.model_copy(update={"valid_time_end": T1})
        await ctx.shards.put(b3.shard_iri, b3)
        assert (await ctx.status()).full_shacl == "fail"
    finally:
        await ctx.close()


async def test_large_batches_use_the_complete_corpus_tier(storage_root: Path) -> None:
    ctx = await open_ctx(storage_root)
    try:
        b = shard(1)
        records = [shard(n) for n in range(2, 400)] + [
            b, shard(0, supersedes=b.shard_iri, valid_time_start=T2),
        ]
        await ctx.ingest_shards(records)
        status = await ctx.status()
        assert (status.full_shacl, status.shacl_violations) == ("fail", 1)
    finally:
        await ctx.close()


async def test_marker_is_never_a_false_pass_after_racing_writers(storage_root: Path) -> None:
    a = await open_ctx(storage_root)
    b = await open_ctx(storage_root)
    try:
        await asyncio.gather(
            *[a.shards.put(shard(n).shard_iri, shard(n)) for n in range(0, 20, 2)],
            *[b.shards.put(shard(n).shard_iri, shard(n)) for n in range(1, 20, 2)],
        )
        status = await a.status()
        assert status.journal_head == 19
        assert status.full_shacl in ("pass", "unvalidated")
        if status.full_shacl == "pass":
            assert status.shacl_validated_through == status.journal_head
        assert (await a.validate_corpus()).conforms
    finally:
        await a.close()
        await b.close()


async def test_swapped_marker_payload_reads_unvalidated(storage_root: Path) -> None:
    ctx = await open_ctx(storage_root)
    try:
        await ctx.shards.put(shard(1).shard_iri, shard(1))
        store = MarkerStore(storage_root, "corpus-a")
        marker = store.read()
        assert marker is not None and marker.position == 0
        store.update(lambda m: m.__class__(**{**m.__dict__, "payload_sha256": "0" * 64}))
        assert (await ctx.status()).full_shacl == "unvalidated"
    finally:
        await ctx.close()


async def test_pyshacl_engine_agrees_with_compiled(storage_root: Path) -> None:
    off = await open_ctx(storage_root, shacl=None)
    try:
        await off.ingest_shards([shard(1), inverted(2), shard(3, sense="x")])
    finally:
        await off.close()
    ctx = await open_ctx(storage_root)
    try:
        compiled = await ctx.validate_corpus()
        reference = await ctx.validate_corpus(engine="pyshacl")
        assert compiled.violations == reference.violations == 1
        assert compiled.warnings == reference.warnings
        assert {r["focus"] for r in compiled.results} == {r["focus"] for r in reference.results}
    finally:
        await ctx.close()


async def test_export_manifest_carries_fail(storage_root: Path, tmp_path: Path) -> None:
    from folio_insights.storage.exports import ExportFormat, export_corpus

    ctx = await open_ctx(storage_root)
    try:
        b = shard(2)
        await ctx.ingest_shards([b, shard(1, supersedes=b.shard_iri, valid_time_start=T2)])
        result = await export_corpus(ctx, tmp_path / "out", formats=[ExportFormat.N_QUADS])
        assert result.manifest["full_shacl"] == "fail"
    finally:
        await ctx.close()


def test_cli_validate_and_status(tmp_path: Path) -> None:
    from folio_insights.cli import cli

    root = tmp_path / "root"

    async def seed() -> None:
        off = await CorpusStorageContext.open(root, "corpus-a", config=StorageConfig(shacl=None))
        try:
            await off.ingest_shards([shard(1), inverted(2)])
        finally:
            await off.close()

    asyncio.run(seed())
    runner = CliRunner()
    status = runner.invoke(cli, ["storage", "status", "corpus-a", "--corpus-root", str(root)])
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["full_shacl"] == "unvalidated"

    out = runner.invoke(cli, ["storage", "validate", "corpus-a", "--corpus-root", str(root)])
    assert out.exit_code == 1, out.output
    report = json.loads(out.output)
    assert report["full_shacl"] == "fail" and report["violations"] == 1
    assert report["results"][0]["focus"] == inverted(2).shard_iri

    status = runner.invoke(cli, ["storage", "status", "corpus-a", "--corpus-root", str(root)])
    assert json.loads(status.output)["full_shacl"] == "fail"

    missing = runner.invoke(cli, ["storage", "validate", "nope", "--corpus-root", str(root)])
    assert missing.exit_code == 1 and "no corpus" in missing.output
