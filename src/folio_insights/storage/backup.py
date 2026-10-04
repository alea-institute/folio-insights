"""Snapshot and restore of a storage root (Phase 13 U4, KTD5).

A snapshot is a directory holding:

* ``journal.sqlite3`` — an online copy of the authoritative journal taken
  with aiosqlite ``Connection.backup`` (SQLite's backup API: a consistent
  point-in-time copy, every row byte-for-byte, op_ids included);
* ``projection.oxigraph`` — a RocksDB backup of the projection (optional;
  ``include_projection=False`` snapshots the journal only and a restore then
  rebuilds the projection from it);
* ``snapshot.json`` — the manifest: per corpus the journal head, the
  payload sha256 of the head row and row counts, plus the projection
  watermarks, schema and adapter versions, the TBox digest, the sha256 of
  the copied journal file and the sha256 of every projection backup file.

Ordering: the projection lock is held while both copies are taken, so the
projection cannot advance during the snapshot, and the journal copy is
taken AFTER the projection copy. The journal only grows, so every corpus's
projection watermark is at or below its journal head in the snapshot; a
restore replays the difference (and the watermark digest check rebuilds a
projection that does not match).

Restore goes into a NEW destination only. It is assembled in a hidden
sibling directory, checked, and only then renamed into place with a
no-replace rename:

* the journal copy's sha256, SQLite integrity check, schema version, heads
  and head-row digests against the manifest;
* by DEFAULT the projection is REBUILT from that journal
  (``rebuild_projection=True``); the snapshot's projection is used only on
  request, and then only after every file's sha256 matches the manifest
  (symlinks and unlisted or missing files are refused);
* a full open and catch-up of every corpus.

What these checks establish is consistency with the manifest. The manifest
itself is NOT authenticated (unsigned): someone who can rewrite the
snapshot directory can rewrite ``snapshot.json`` to match. Keep snapshots
where only the operator can write; rebuilding the projection from the
journal (the default) at least never serves RDF that the journal does not
produce.

An interrupted or failed restore never creates the destination and never
writes to the snapshot or to any live storage root; at worst it leaves a
``.<dest>.restoring-*`` directory that is safe to delete.

Snapshots, restores and their destinations are refused inside the served
output directory; nothing here reads credentials.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from folio_insights import __version__
from folio_insights.storage._paths import inside_served_output, rename_noreplace
from folio_insights.storage.errors import StorageError
from folio_insights.storage.journal import JOURNAL_FILENAME, JOURNAL_SCHEMA_VERSION
from folio_insights.storage.projection import (
    PROJECTION_ADAPTER_VERSION,
    PROJECTION_DIRNAME,
    ProjectionHandle,
    ProjectionLock,
)

SNAPSHOT_MANIFEST = "snapshot.json"
SNAPSHOT_FORMAT = "folio-insights/storage-snapshot/v1"


class SnapshotError(StorageError):
    """A snapshot could not be taken, or does not verify."""


class RestoreRefused(ValueError):
    """The restore destination is not a new, separate location."""


@dataclass(frozen=True)
class SnapshotResult:
    path: Path
    manifest: dict[str, Any]


@dataclass(frozen=True)
class RestoreResult:
    path: Path
    corpora: dict[str, int]
    projection: str  # "restored" or "rebuilt"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _journal_summary(path: Path) -> dict[str, dict[str, Any]]:
    """Per-corpus head, head-row digest and row counts of a closed journal."""
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        out: dict[str, dict[str, Any]] = {}
        rows = conn.execute(
            "SELECT corpus, MAX(position), COUNT(*), "
            "SUM(kind = 'governance') FROM journal GROUP BY corpus ORDER BY corpus"
        ).fetchall()
        for corpus, head, count, governance in rows:
            (sha,) = conn.execute(
                "SELECT payload_sha256 FROM journal WHERE corpus = ? AND position = ?",
                (corpus, head),
            ).fetchone()
            out[corpus] = {
                "journal_head": int(head),
                "head_payload_sha256": sha,
                "rows": int(count),
                "governance_rows": int(governance or 0),
            }
        return out
    finally:
        conn.close()


def _integrity_check(path: Path) -> None:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        (result,) = conn.execute("PRAGMA integrity_check").fetchone()
        (version,) = conn.execute(
            "SELECT value FROM storage_meta WHERE key = 'journal_schema_version'"
        ).fetchone()
    finally:
        conn.close()
    if result != "ok":
        raise SnapshotError(f"journal copy failed the SQLite integrity check: {result}")
    if version != str(JOURNAL_SCHEMA_VERSION):
        raise SnapshotError(
            f"journal schema version {version!r} is not supported by this code "
            f"({JOURNAL_SCHEMA_VERSION}); restore with the matching code version"
        )


def _tree_digests(root: Path) -> dict[str, str]:
    """sha256 of every regular file under ``root`` (relative POSIX paths).
    Symlinks and special files are refused, never followed."""
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        for name in [*dirnames, *filenames]:
            path = base / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise SnapshotError(f"refusing symlink in snapshot projection: {path}")
            if name in filenames:
                if not stat.S_ISREG(mode):
                    raise SnapshotError(f"refusing non-regular file in snapshot: {path}")
                out[path.relative_to(root).as_posix()] = _file_sha256(path)
    return out


def _copy_verified_tree(src: Path, dst: Path, expected: dict[str, str]) -> None:
    """Copy ``src`` to ``dst`` (no symlinks followed), then require the COPY
    to match ``expected`` exactly: same file set, same sha256 per file."""
    if src.is_symlink() or not src.is_dir():
        raise SnapshotError(f"snapshot projection {src} is not a plain directory")
    for rel in expected:
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise SnapshotError(f"snapshot manifest projection path {rel!r} is not contained")
    _tree_digests(src)  # refuses symlinks / special files before copying
    shutil.copytree(src, dst, symlinks=True)
    actual = _tree_digests(dst)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(k for k in set(actual) & set(expected) if actual[k] != expected[k])
        raise SnapshotError(
            "snapshot projection does not match its manifest digests "
            f"(missing {len(missing)}, unlisted {len(extra)}, changed {len(changed)})"
        )


def _inside(path: Path, other: Path) -> bool:
    path, other = path.resolve(), other.resolve()
    return path == other or other in path.parents


async def _acquire(lock: ProjectionLock) -> None:
    deadline = lock.deadline()
    delay = 0.002
    while not lock.try_acquire():
        if time.monotonic() > deadline:
            raise lock.timeout_error()
        await asyncio.sleep(delay)
        delay = min(delay * 2, 0.05)


async def snapshot_storage(
    root: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    include_projection: bool = True,
    lock_timeout_s: float = 120.0,
) -> SnapshotResult:
    """Snapshot the storage root at ``root`` into the NEW directory ``destination``."""
    src = Path(root)
    dest = Path(destination)
    journal = src / JOURNAL_FILENAME
    if not journal.exists():
        raise SnapshotError(f"no journal at {journal}")
    if dest.exists():
        raise SnapshotError(f"snapshot destination {dest} already exists")
    if _inside(dest, src):
        raise SnapshotError("snapshot destination must be outside the storage root")
    if inside_served_output(dest) is not None:
        raise SnapshotError("snapshot destination must not be inside the served output directory")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.partial-{uuid.uuid4().hex}"
    tmp.mkdir(mode=0o700)
    try:
        projection: dict[str, Any] = {"included": include_projection}
        lock = ProjectionLock(src, timeout_s=lock_timeout_s)
        await _acquire(lock)
        try:
            if include_projection and (src / PROJECTION_DIRNAME).exists():
                handle = await asyncio.to_thread(ProjectionHandle, src)
                try:
                    corpora = await _corpora(journal)
                    states = {c: handle.state(c) for c in corpora}
                    projection["tbox_digest"] = handle.tbox_digest()
                    projection["watermarks"] = {
                        c: {"watermark": s.watermark, "payload_sha256": s.payload_sha256}
                        for c, s in states.items()
                    }
                    await asyncio.to_thread(handle.backup, tmp / PROJECTION_DIRNAME)
                    projection["files"] = await asyncio.to_thread(
                        _tree_digests, tmp / PROJECTION_DIRNAME
                    )
                finally:
                    await asyncio.to_thread(handle.close)
            else:
                projection["included"] = False
            # Journal AFTER the projection: heads >= watermarks in the copy.
            async with aiosqlite.connect(f"file:{journal}?mode=ro", uri=True) as source:
                async with aiosqlite.connect(tmp / JOURNAL_FILENAME) as target:
                    await source.backup(target)
        finally:
            lock.release()

        copied = tmp / JOURNAL_FILENAME
        await asyncio.to_thread(_integrity_check, copied)
        # A self-contained single file: no WAL side files in the snapshot.
        with sqlite3.connect(copied) as conn:
            conn.execute("PRAGMA journal_mode = DELETE")
        manifest = {
            "format": SNAPSHOT_FORMAT,
            "created_at": datetime.now(UTC).isoformat(),
            "code_version": __version__,
            "journal_schema_version": JOURNAL_SCHEMA_VERSION,
            "projection_adapter_version": PROJECTION_ADAPTER_VERSION,
            "journal_sha256": _file_sha256(copied),
            "corpora": await asyncio.to_thread(_journal_summary, copied),
            "projection": projection,
        }
        (tmp / SNAPSHOT_MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        rename_noreplace(tmp, dest)
    except FileExistsError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SnapshotError(f"snapshot destination {dest} appeared during the snapshot") from exc
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return SnapshotResult(path=dest, manifest=manifest)


async def _corpora(journal: Path) -> list[str]:
    async with aiosqlite.connect(f"file:{journal}?mode=ro", uri=True) as conn:
        rows = await conn.execute_fetchall("SELECT DISTINCT corpus FROM journal ORDER BY corpus")
    return [str(r[0]) for r in rows]


def read_snapshot_manifest(snapshot: str | os.PathLike[str]) -> dict[str, Any]:
    path = Path(snapshot) / SNAPSHOT_MANIFEST
    try:
        manifest = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"unreadable snapshot manifest {path}: {exc}") from exc
    if manifest.get("format") != SNAPSHOT_FORMAT:
        raise SnapshotError(f"{path} is not a {SNAPSHOT_FORMAT} manifest")
    return manifest


async def restore_storage(
    snapshot: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    rebuild_projection: bool = True,
    process_pool: bool = False,
) -> RestoreResult:
    """Restore ``snapshot`` into the NEW storage root ``destination``."""
    from folio_insights.storage.context import CorpusStorageContext, StorageConfig

    snap = Path(snapshot)
    dest = Path(destination)
    if dest.exists():
        raise RestoreRefused(
            f"restore destination {dest} already exists; restores go into a new "
            "destination only (never over live or existing data)"
        )
    if _inside(dest, snap) or _inside(snap, dest):
        raise RestoreRefused("restore destination must be separate from the snapshot")
    if inside_served_output(dest) is not None:
        raise RestoreRefused("restore destination must not be inside the served output directory")
    manifest = read_snapshot_manifest(snap)
    if manifest.get("journal_schema_version") != JOURNAL_SCHEMA_VERSION:
        raise SnapshotError(
            f"snapshot journal schema {manifest.get('journal_schema_version')!r} does not "
            f"match this code ({JOURNAL_SCHEMA_VERSION}); restore with the matching code"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.restoring-{uuid.uuid4().hex}"
    tmp.mkdir(mode=0o700)
    try:
        journal = tmp / JOURNAL_FILENAME
        await asyncio.to_thread(shutil.copy2, snap / JOURNAL_FILENAME, journal)
        if _file_sha256(journal) != manifest["journal_sha256"]:
            raise SnapshotError("snapshot journal does not match its manifest digest")
        await asyncio.to_thread(_integrity_check, journal)
        summary = await asyncio.to_thread(_journal_summary, journal)
        if summary != manifest["corpora"]:
            raise SnapshotError("snapshot journal heads do not match its manifest")

        has_projection = bool(manifest["projection"].get("included")) and (
            snap / PROJECTION_DIRNAME
        ).exists()
        use_projection = has_projection and not rebuild_projection
        if use_projection:
            expected = manifest["projection"].get("files")
            if not isinstance(expected, dict) or not expected:
                raise SnapshotError(
                    "snapshot manifest lists no projection file digests; restore with "
                    "rebuild_projection=True"
                )
            await asyncio.to_thread(
                _copy_verified_tree, snap / PROJECTION_DIRNAME, tmp / PROJECTION_DIRNAME,
                expected,
            )

        # Open every corpus: replays journal rows past each watermark and
        # rebuilds any projection whose watermark digest does not match.
        config = StorageConfig(event_verifier=None, process_pool=process_pool)
        heads: dict[str, int] = {}
        for corpus, expected in summary.items():
            # Without a copied projection this open IS the rebuild: the empty
            # projection replays the whole journal (bulk path when large).
            ctx = await CorpusStorageContext.open(tmp, corpus, config=config)
            try:
                status = await ctx.status()
            finally:
                await ctx.close()
            if not status.journal_head == status.projection_watermark == expected[
                "journal_head"
            ]:
                raise SnapshotError(
                    f"restored corpus {corpus!r} did not reach journal head "
                    f"{expected['journal_head']}"
                )
            heads[corpus] = status.journal_head
        rename_noreplace(tmp, dest)
    except FileExistsError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RestoreRefused(f"restore destination {dest} appeared during the restore") from exc
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return RestoreResult(
        path=dest, corpora=heads, projection="restored" if use_projection else "rebuilt"
    )


__all__ = [
    "SNAPSHOT_FORMAT",
    "SNAPSHOT_MANIFEST",
    "RestoreRefused",
    "RestoreResult",
    "SnapshotError",
    "SnapshotResult",
    "read_snapshot_manifest",
    "restore_storage",
    "snapshot_storage",
]
