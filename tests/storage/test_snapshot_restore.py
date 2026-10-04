"""U4: snapshot (aiosqlite backup + projection backup) and restore into a new
destination; an interrupted restore leaves the original intact."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import folio_insights.storage.backup as backup
from folio_insights.storage import CorpusStorageContext, ProjectionRecoveryPending
from folio_insights.storage.backup import (
    RestoreRefused,
    SnapshotError,
    read_snapshot_manifest,
    restore_storage,
    snapshot_storage,
)
from folio_insights.storage.journal import JOURNAL_FILENAME
from folio_insights.storage.projection import ProjectionHandle

from tests.storage.conftest import (
    REPO_ROOT,
    at,
    genesis,
    new_identity,
    role_assertion,
    role_revocation,
    shard,
)

pytestmark = pytest.mark.storage

FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
_QUERIES = (
    "SELECT ?g ?s ?p ?o WHERE { GRAPH ?g { ?s ?p ?o } }",
    "SELECT ?s (COUNT(?p) AS ?n) WHERE { ?s ?p ?o } GROUP BY ?s",
)


async def _populate(root: Path) -> None:
    admin, reviewer = new_identity(), new_identity()
    a = await CorpusStorageContext.open(root, "corpus-a")
    b = await CorpusStorageContext.open(root, "corpus-b")
    try:
        await a.governance.append(genesis("corpus-a", admin), op_id="genesis:corpus-a")
        await a.governance.append(
            role_assertion("corpus-a", admin, reviewer.did, "reviewer", at(1)), op_id="op-grant"
        )
        await a.ingest_shards([shard(n) for n in range(1, 8)], op_id="op-ingest")
        await a.shards.put(shard(3).shard_iri, shard(3, sense="revised"), op_id="op-rev")
        await a.governance.append(
            role_revocation("corpus-a", admin, reviewer.did, "reviewer", at(2)),
            op_id="op-revoke",
        )
        await b.governance.append(genesis("corpus-b", admin))
        await b.ingest_shards([shard(n) for n in range(20, 23)])
    finally:
        await a.close()
        await b.close()


def _rows(root: Path) -> list[tuple]:
    with sqlite3.connect(root / JOURNAL_FILENAME) as conn:
        return conn.execute("SELECT * FROM journal ORDER BY corpus, position").fetchall()


async def _observe(root: Path) -> dict:
    out: dict = {"rows": _rows(root)}
    for corpus in ("corpus-a", "corpus-b"):
        ctx = await CorpusStorageContext.open(root, corpus)
        try:
            status = await ctx.status()
            records = {}
            async for s in ctx.shards.iter_shards():
                rec = await ctx.shards.get_record(s.shard_iri)
                records[s.shard_iri] = (rec.position, rec.payload, rec.original_bytes,
                                        rec.source_schema_version)
            out[corpus] = {
                "head": (status.journal_head, status.projection_watermark),
                "roles": await ctx.governance.query_active_roles_at(corpus, FAR_FUTURE),
                "events": [e.model_dump_json() async for e in ctx.governance.iter_events(corpus)],
                "records": records,
                "queries": [
                    sorted(tuple(str(v) for v in r.values()) for r in await ctx.query(q))
                    for q in _QUERIES
                ],
            }
        finally:
            await ctx.close()
    return out


def _tree_digest(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


@pytest.mark.parametrize("include_projection", [True, False])
async def test_snapshot_restore_matches_original(tmp_path: Path, include_projection: bool) -> None:
    root = tmp_path / "live"
    await _populate(root)
    before = await _observe(root)
    assert before["corpus-a"]["roles"]  # the admin, but no longer the reviewer
    assert all("reviewer" not in roles for roles in before["corpus-a"]["roles"].values())

    snap = await snapshot_storage(root, tmp_path / "snap", include_projection=include_projection)
    manifest = read_snapshot_manifest(snap.path)
    assert manifest["corpora"]["corpus-a"]["journal_head"] == 10
    assert manifest["projection"]["included"] is include_projection
    assert not list(snap.path.glob(f"{JOURNAL_FILENAME}-*"))  # no WAL side files

    # Writes after the snapshot are not in it.
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    await ctx.ingest_shards([shard(40)])
    await ctx.close()

    restored = await restore_storage(snap.path, tmp_path / "restored")
    assert restored.projection == ("restored" if include_projection else "rebuilt")
    assert restored.corpora == {"corpus-a": 10, "corpus-b": 3}
    after = await _observe(tmp_path / "restored")
    assert after == before  # positions, op_ids, roles, revisions, RDF queries
    assert ("corpus-a", 7) in {(r[0], r[1]) for r in after["rows"]}
    assert {r[2] for r in after["rows"]} >= {"genesis:corpus-a", "op-grant", "op-rev",
                                              "op-revoke", "op-ingest#0"}

    rebuilt = await restore_storage(snap.path, tmp_path / "rebuilt", rebuild_projection=True)
    assert rebuilt.projection == "rebuilt"
    assert await _observe(tmp_path / "rebuilt") == before


async def test_snapshot_of_a_lagging_projection_restores_to_the_journal_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "live"
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    await ctx.ingest_shards([shard(1), shard(2)])

    def boom(self, corpus, rows, **kwargs):  # noqa: ANN001, ANN003, ANN202
        raise OSError("synthetic projection failure")

    monkeypatch.setattr(ProjectionHandle, "apply", boom)
    with pytest.raises(ProjectionRecoveryPending):
        await ctx.shards.put(shard(3).shard_iri, shard(3))
    snap = await snapshot_storage(root, tmp_path / "snap")
    lag = snap.manifest["projection"]["watermarks"]["corpus-a"]["watermark"]
    assert (lag, snap.manifest["corpora"]["corpus-a"]["journal_head"]) == (1, 2)
    monkeypatch.undo()

    restored = await restore_storage(snap.path, tmp_path / "restored")
    assert restored.corpora == {"corpus-a": 2}
    ctx = await CorpusStorageContext.open(tmp_path / "restored", "corpus-a")
    try:
        assert [s.shard_iri async for s in ctx.shards.iter_shards()] == sorted(
            shard(n).shard_iri for n in (1, 2, 3)
        )
    finally:
        await ctx.close()


async def test_restore_refuses_anything_but_a_new_destination(tmp_path: Path) -> None:
    root = tmp_path / "live"
    await _populate(root)
    snap = await snapshot_storage(root, tmp_path / "snap")
    for existing in (root, tmp_path / "empty"):
        existing.mkdir(exist_ok=True)
        with pytest.raises(RestoreRefused, match="new"):
            await restore_storage(snap.path, existing)
    with pytest.raises(RestoreRefused, match="separate"):
        await restore_storage(snap.path, snap.path / "inside")
    with pytest.raises(SnapshotError, match="already exists"):
        await snapshot_storage(root, snap.path)
    with pytest.raises(SnapshotError, match="outside"):
        await snapshot_storage(root, root / "snap")


async def test_interrupted_restore_leaves_original_and_snapshot_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "live"
    await _populate(root)
    before = await _observe(root)
    snap = await snapshot_storage(root, tmp_path / "snap")
    snap_digest = _tree_digest(snap.path)

    def interrupted(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise KeyboardInterrupt("synthetic interruption while copying the projection")

    monkeypatch.setattr(backup.shutil, "copytree", interrupted)
    with pytest.raises(KeyboardInterrupt):
        await restore_storage(snap.path, tmp_path / "restored")
    monkeypatch.undo()
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".restored.restoring-*"))
    assert _tree_digest(snap.path) == snap_digest
    assert await _observe(root) == before


def test_killed_restore_process_leaves_original_and_snapshot_intact(tmp_path: Path) -> None:
    import asyncio

    root = tmp_path / "live"
    asyncio.run(_populate(root))
    snap = asyncio.run(snapshot_storage(root, tmp_path / "snap")).path
    snap_digest = _tree_digest(snap)
    live_rows = _rows(root)
    code = (
        "import asyncio, os, shutil, sys\n"
        "import folio_insights.storage.backup as b\n"
        "real = shutil.copytree\n"
        "def die(src, dst, *a, **k):\n"
        "    real(src, dst, *a, **k)\n"
        "    os._exit(17)  # killed after the projection copy, before verification\n"
        "b.shutil.copytree = die\n"
        "asyncio.run(b.restore_storage(sys.argv[1], sys.argv[2]))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)])
    proc = subprocess.run(
        [sys.executable, "-c", code, str(snap), str(tmp_path / "restored")],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 17, proc.stderr
    assert not (tmp_path / "restored").exists()
    leftovers = list(tmp_path.glob(".restored.restoring-*"))
    assert len(leftovers) == 1  # safe to delete; never mistaken for a restore
    assert _tree_digest(snap) == snap_digest
    assert _rows(root) == live_rows

    shutil.rmtree(leftovers[0])
    result = asyncio.run(restore_storage(snap, tmp_path / "restored"))
    assert result.corpora == {"corpus-a": 10, "corpus-b": 3}


async def test_tampered_snapshot_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "live"
    await _populate(root)
    snap = await snapshot_storage(root, tmp_path / "snap")
    with open(snap.path / JOURNAL_FILENAME, "r+b") as f:
        f.seek(-64, os.SEEK_END)
        f.write(b"\x00" * 8)
    with pytest.raises(SnapshotError, match="digest"):
        await restore_storage(snap.path, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
