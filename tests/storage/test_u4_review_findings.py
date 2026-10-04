"""Regression tests for the independent U4 review (2026-10-04).

One test (or group) per finding; each fails on the pre-fix code.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from pyoxigraph import Literal, NamedNode, Quad, Store

import folio_insights.storage._parallel as parallel
import folio_insights.storage._paths as paths
from folio_insights.cli import cli
from folio_insights.shards import AttestedSignature, dump_shard_record
from folio_insights.storage import (
    CorpusStorageContext,
    PiiRejected,
    ShardIdentityViolation,
    StorageConfig,
    StorageError,
)
from folio_insights.storage.backup import (
    RestoreRefused,
    SnapshotError,
    restore_storage,
    snapshot_storage,
)
from folio_insights.storage.dump import DumpError, restore_ttl_dump, run_ttl_dump
from folio_insights.storage.exports import ExportRefused, export_corpus
from folio_insights.storage.journal import JOURNAL_FILENAME
from folio_insights.storage.projection import PROJECTION_DIRNAME, corpus_graph, fi

from tests.storage.conftest import T0, at, genesis, new_identity, role_assertion, shard

pytestmark = pytest.mark.storage

SENSE = "SELECT ?v WHERE { ?s <https://folio-insights.aleainstitute.ai/vocab/sense> ?v }"


async def _senses(ctx: CorpusStorageContext) -> list[str]:
    return sorted(r["v"].value for r in await ctx.query(SENSE))


# ── P1: Phase 11 hooks can mutate what they validate ──────────────────────


def _mutating_hook(s) -> None:  # noqa: ANN001
    sig = AttestedSignature(did="did:example:hook", signed_at=T0)
    if not s.signatures:
        s.signatures.append(sig)
    s.sense = "HOOK-REWRITTEN"


@pytest.mark.parametrize("path", ["ingest", "put"])
async def test_mutating_shard_hook_cannot_bypass_checks_or_poison_state(
    tmp_path: Path, path: str
) -> None:
    sig = AttestedSignature(did="did:example:a", signed_at=T0)
    ctx = await CorpusStorageContext.open(tmp_path, "c")
    await ctx.ingest_shards([shard(1, signatures=[sig])])
    await ctx.close()
    ctx = await CorpusStorageContext.open(
        tmp_path, "c", config=StorageConfig(shard_validator=_mutating_hook)
    )
    try:
        shrinking = shard(1, sense="v2", signatures=[])
        with pytest.raises(ShardIdentityViolation, match="shrink"):
            if path == "ingest":
                await ctx.ingest_shards([shrinking])
            else:
                await ctx.shards.put(shrinking.shard_iri, shrinking)
        # A legitimate write: the hook's rewrite reaches neither journal nor RDF.
        await ctx.ingest_shards([shard(2)])
        assert (await ctx.shards.get(shard(2).shard_iri)).sense == "synthetic sense 2"
        assert "HOOK-REWRITTEN" not in await _senses(ctx)
        live = await _senses(ctx)
        await ctx.rebuild_projection()
        assert await _senses(ctx) == live
    finally:
        await ctx.close()


async def test_mutating_event_hook_cannot_change_the_persisted_event(tmp_path: Path) -> None:
    admin, other = new_identity(), new_identity()

    def hook(event) -> None:  # noqa: ANN001
        if getattr(event, "role", None) == "reviewer":
            event.role = "corpus_admin"

    ctx = await CorpusStorageContext.open(tmp_path, "c", config=StorageConfig(event_validator=hook))
    try:
        await ctx.governance.append(genesis("c", admin))
        event = await ctx.governance.append(
            role_assertion("c", admin, other.did, "reviewer", at(1))
        )
        assert event.role == "reviewer"
        stored = await ctx.governance.get_by_position("c", 1)
        assert stored is not None and stored.role == "reviewer"
    finally:
        await ctx.close()


# ── P1: restore served a tampered snapshot projection ─────────────────────


async def _snapshot(tmp_path: Path) -> Path:
    ctx = await CorpusStorageContext.open(tmp_path / "root", "c")
    try:
        await ctx.ingest_shards([shard(n) for n in range(3)])
    finally:
        await ctx.close()
    return (await snapshot_storage(tmp_path / "root", tmp_path / "snap")).path


def _tamper_projection(snap: Path) -> None:
    store = Store(str(snap / PROJECTION_DIRNAME))
    s1 = NamedNode(shard(1).shard_iri)
    g = corpus_graph("c")
    for q in list(store.quads_for_pattern(s1, fi("sense"), None, g)):
        store.remove(q)
    store.add(Quad(s1, fi("sense"), Literal("TAMPERED sense"), g))
    store.flush()
    del store


async def test_tampered_snapshot_projection_is_never_served(tmp_path: Path) -> None:
    snap = await _snapshot(tmp_path)
    _tamper_projection(snap)
    # Default: rebuilt from the verified journal.
    result = await restore_storage(snap, tmp_path / "restored")
    assert result.projection == "rebuilt"
    ctx = await CorpusStorageContext.open(tmp_path / "restored", "c")
    try:
        assert "TAMPERED sense" not in await _senses(ctx)
    finally:
        await ctx.close()
    # Opting into the snapshot projection: refused on digest mismatch.
    with pytest.raises(SnapshotError, match="digests"):
        await restore_storage(snap, tmp_path / "restored-copy", rebuild_projection=False)
    assert not (tmp_path / "restored-copy").exists()


async def test_symlink_in_snapshot_projection_is_refused(tmp_path: Path) -> None:
    snap = await _snapshot(tmp_path)
    victim = next(p for p in (snap / PROJECTION_DIRNAME).iterdir() if p.is_file())
    outside = tmp_path / "outside"
    shutil.copy2(victim, outside)
    victim.unlink()
    victim.symlink_to(outside)
    with pytest.raises(SnapshotError, match="symlink"):
        await restore_storage(snap, tmp_path / "restored", rebuild_projection=False)
    assert not (tmp_path / "restored").exists()


# ── P2: watermark check compared one row only ─────────────────────────────


async def test_journal_differing_before_the_watermark_row_is_detected(tmp_path: Path) -> None:
    last = shard(9)
    for name, first in (("A", shard(1)), ("B", shard(2))):
        ctx = await CorpusStorageContext.open(tmp_path / name, "c")
        try:
            await ctx.ingest_shards([first])
            await ctx.ingest_shards([last])  # identical watermark row payload
        finally:
            await ctx.close()
    for f in (tmp_path / "A").glob(f"{JOURNAL_FILENAME}*"):
        f.unlink()
    for f in (tmp_path / "B").glob(f"{JOURNAL_FILENAME}*"):
        shutil.copy2(f, tmp_path / "A" / f.name)
    ctx = await CorpusStorageContext.open(tmp_path / "A", "c")
    try:
        served = await ctx.query(
            "SELECT ?s WHERE { ?s a <https://folio-insights.aleainstitute.ai/vocab/Shard> }"
        )
        assert sorted(r["s"].value for r in served) == sorted(
            [shard(2).shard_iri, last.shard_iri]
        )
    finally:
        await ctx.close()


# ── P2: winning refusal depended on batch size ────────────────────────────


class _HookRefused(ValueError):
    pass


@pytest.mark.parametrize("use_pool", [True, False])
async def test_earliest_refusal_wins_at_any_batch_size(tmp_path: Path, use_pool: bool) -> None:
    def hook(s) -> None:  # noqa: ANN001
        if s.shard_iri == shard(0).shard_iri:
            raise _HookRefused("hook refuses record 0")

    raws = [json.loads(dump_shard_record(shard(n))) for n in range(2600)]
    raws[2500]["sense"] = "ssn 123-45-6789"
    ctx = await CorpusStorageContext.open(tmp_path, "c", config=StorageConfig(shard_validator=hook))
    try:
        with pytest.raises(_HookRefused):
            await ctx.bulk_load_shards(raws, parallel=use_pool)
    finally:
        await ctx.close()


# ── P2: implicit pool from ingest_shards ──────────────────────────────────


async def test_ingest_shards_never_uses_the_process_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_pool():  # noqa: ANN202
        raise AssertionError("ingest_shards started the process pool")

    monkeypatch.setattr(parallel, "_get_pool", no_pool)
    ctx = await CorpusStorageContext.open(tmp_path, "c")
    try:
        assert len(await ctx.ingest_shards([shard(n) for n in range(2100)])) == 2100
        await ctx.rebuild_projection()
    finally:
        await ctx.close()


# ── P2: dump repository boundaries and git hardening ──────────────────────


async def _root_with_corpus(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    ctx = await CorpusStorageContext.open(root, "c")
    try:
        await ctx.ingest_shards([shard(1)])
    finally:
        await ctx.close()
    return root


async def test_dump_refuses_a_not_yet_existing_path_inside_another_repo(tmp_path: Path) -> None:
    root = await _root_with_corpus(tmp_path)
    parent = tmp_path / "checkout"
    parent.mkdir()
    subprocess.run(["git", "init", "-q", str(parent)], check=True)
    with pytest.raises(DumpError, match="its own work tree"):
        await run_ttl_dump(root, parent / "a" / "dumps", init=True)
    assert not (parent / "a").exists()


async def test_dump_git_runs_no_repo_hooks_fsmonitor_or_inherited_git_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = await _root_with_corpus(tmp_path)
    repo = tmp_path / "dumprepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    hook_marker, fsm_marker = tmp_path / "HOOK_RAN", tmp_path / "FSMONITOR_RAN"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\necho hook >> {hook_marker}\n")
    hook.chmod(0o755)
    subprocess.run(
        ["git", "-C", str(repo), "config", "core.fsmonitor", f"echo x >> {fsm_marker}; false"],
        check=True,
    )
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    subprocess.run(["git", "init", "-q", str(decoy)], check=True)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    result = await run_ttl_dump(root, repo)
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    assert result.commit is not None
    assert not hook_marker.exists() and not fsm_marker.exists()
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert head == result.commit
    decoy_log = subprocess.run(["git", "-C", str(decoy), "log"], capture_output=True, text=True)
    assert decoy_log.returncode != 0  # nothing was committed into the decoy


# ── P2: PII under signatures skipped the gate ─────────────────────────────


@pytest.mark.parametrize("field", ["did", "signing_key_id", "signature"])
async def test_pii_inside_signature_objects_is_refused(tmp_path: Path, field: str) -> None:
    record = json.loads(dump_shard_record(shard(1, signatures=[
        AttestedSignature(did="did:example:a", signed_at=T0)
    ])))
    record["signatures"][0][field] = "call (212) 555-0142 now"
    ctx = await CorpusStorageContext.open(tmp_path, "c")
    try:
        with pytest.raises(PiiRejected, match=f"signatures\\[0\\]\\.{field}"):
            await ctx.ingest_shards([record])
        assert (await ctx.status()).journal_head == -1
    finally:
        await ctx.close()


# ── P2: served output directory ───────────────────────────────────────────


async def test_snapshot_and_restore_refuse_the_served_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = await _root_with_corpus(tmp_path)
    served = tmp_path / "served"
    monkeypatch.setattr(paths, "served_output_dirs", lambda: (served.resolve(),))
    with pytest.raises(SnapshotError, match="served output"):
        await snapshot_storage(root, served / "snap")
    snap = (await snapshot_storage(root, tmp_path / "snap")).path
    with pytest.raises(RestoreRefused, match="served output"):
        await restore_storage(snap, served / "restored")
    assert not served.exists()


async def test_served_output_guard_fails_closed_and_ignores_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import folio_insights.config as config

    monkeypatch.setenv("FOLIO_INSIGHTS_OUTPUT_DIR", "output")
    config.get_settings.cache_clear()
    monkeypatch.chdir(tmp_path)
    dirs = paths.served_output_dirs()
    assert (tmp_path / "output").resolve() in dirs
    assert (paths._PROJECT_ROOT / "output").resolve() in dirs  # independent of cwd

    def broken():  # noqa: ANN202
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(config, "get_settings", broken)
    root = await _root_with_corpus(tmp_path)
    ctx = await CorpusStorageContext.open(root, "c")
    try:
        with pytest.raises(StorageError, match="served output"):
            await export_corpus(ctx, tmp_path / "x")
    finally:
        await ctx.close()


# ── nits ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("native", [True, False])
def test_rename_noreplace_never_replaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         native: bool) -> None:
    if not native:
        monkeypatch.setattr(paths, "_renameat2", None)
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (dst / "keep").write_text("existing")
    with pytest.raises(FileExistsError):
        paths.rename_noreplace(src, dst)
    assert (dst / "keep").read_text() == "existing" and src.exists()
    paths.rename_noreplace(src, tmp_path / "new")
    assert (tmp_path / "new").is_dir()


async def test_restore_ttl_dump_refuses_manifest_paths_outside_the_dump(tmp_path: Path) -> None:
    root = await _root_with_corpus(tmp_path)
    repo = tmp_path / "repo"
    await run_ttl_dump(root, repo, init=True)
    secret = tmp_path / "elsewhere.ttl"
    secret.write_text("<urn:a> <urn:b> <urn:c> .\n")
    manifest_path = next((repo / "corpora").glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["path"] = "../elsewhere.ttl"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DumpError, match="escapes"):
        restore_ttl_dump(repo, tmp_path / "rdf")
    assert not (tmp_path / "rdf").exists()


@pytest.mark.parametrize("command", ["status", "export"])
def test_cli_refuses_unknown_corpus_without_creating_it(tmp_path: Path, command: str) -> None:
    import asyncio

    root = asyncio.run(_root_with_corpus(tmp_path))
    args = ["storage", command, "nope", "--corpus-root", str(root)]
    if command == "export":
        args += ["--out", str(tmp_path / "x")]
    out = CliRunner().invoke(cli, args)
    assert out.exit_code == 1 and "no corpus 'nope'" in out.output
    from folio_insights.storage.journal import committed_corpora

    assert committed_corpora(root / JOURNAL_FILENAME) == ["c"]
    empty = tmp_path / "empty-root"
    out = CliRunner().invoke(cli, ["storage", "status", "c", "--corpus-root", str(empty)])
    assert out.exit_code == 1 and not empty.exists()
    assert not os.path.exists(tmp_path / "x")
    assert ExportRefused  # imported for the export refusal family


async def test_restore_never_replaces_a_destination_that_appears_mid_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = await _snapshot(tmp_path)
    dest = tmp_path / "restored"
    real_status = CorpusStorageContext.status

    async def racing_status(self):  # noqa: ANN001, ANN202
        result = await real_status(self)
        dest.mkdir(exist_ok=True)  # another process claims the destination
        (dest / "theirs").write_text("not ours")
        return result

    monkeypatch.setattr(CorpusStorageContext, "status", racing_status)
    with pytest.raises(RestoreRefused, match="appeared"):
        await restore_storage(snap, dest)
    assert sorted(p.name for p in dest.iterdir()) == ["theirs"]
    assert not list(tmp_path.glob(".restored.restoring-*"))
