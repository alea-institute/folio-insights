"""The bridge-ingest provenance manifest (plan KTD6).

The shard envelope is ``extra="forbid"`` and owned by another lane, so enrich
provenance (every proposition id, type, span and citation edge behind a shard
IRI) lives beside the journal at ``<corpus storage root>/bridge-ingest/
manifest.jsonl``: one JSON line per ``(corpus, iri, document_id,
proposition_id)``. The storage root holds every corpus, so each line names
its corpus.

PII: every candidate line passes the corpus PII gate (the same ``PiiGate``
``ctx.ingest_shards`` applies to shards) before it is appended; a refused
line is dropped and reported by IRI, field path and pattern name only, never
by value. Citation edges carry only ``edge_type`` and
``authority_individual_id`` (``authority_text`` is free text and is not kept).

Concurrency: appends take an exclusive, non-blocking ``flock`` on
``manifest.lock`` in the same directory, retried for at most
``LOCK_TIMEOUT_S`` seconds; a lock that stays held raises ``ManifestBusy``.
Under the lock the seen-key set is reused from a cache keyed by the file's
``(st_size, st_mtime_ns)`` (rescanned only when the file changed), only new
lines are appended in one write, and the file is ``fsync`` ed. Reads take no
lock: an append is a single write of whole lines, and ``read_manifest`` skips
an unparsable (torn) trailing line instead of failing.

The ``*_async`` wrappers run the blocking work in a worker thread so the
event loop never waits on the lock, a rescan or ``fsync``.
"""
from __future__ import annotations

import asyncio
import errno
import fcntl
import json
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from folio_insights.bridge_ingest.mapping import ManifestEntry
from folio_insights.storage.errors import PiiRejected
from folio_insights.storage.pii import PiiGate

MANIFEST_DIRNAME = "bridge-ingest"
MANIFEST_FILENAME = "manifest.jsonl"
LOCK_FILENAME = "manifest.lock"
LOCK_TIMEOUT_S = 5.0
_LOCK_POLL_S = 0.02
_CACHE_MAX = 8

Key = tuple[str, str, str, str]


class ManifestBusy(RuntimeError):
    """The manifest lock stayed held past ``LOCK_TIMEOUT_S``; nothing was appended."""


class RefusedManifestLine(BaseModel):
    """A manifest line the PII gate refused (named by field path, never value)."""

    model_config = ConfigDict(extra="forbid")

    iri: str
    field_path: str
    pattern: str


_cache_lock = threading.Lock()
# path -> ((st_size, st_mtime_ns), seen keys)
_SEEN: OrderedDict[str, tuple[tuple[int, int], set[Key]]] = OrderedDict()
# (path, corpus) -> ((st_size, st_mtime_ns), iri -> lines)
_READ: OrderedDict[tuple[str, str], tuple[tuple[int, int], dict[str, list[dict[str, Any]]]]] = (
    OrderedDict()
)


def _cache_put(cache: OrderedDict, key: Any, value: Any) -> None:
    with _cache_lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > _CACHE_MAX:
            cache.popitem(last=False)


def _cache_get(cache: OrderedDict, key: Any) -> Any:
    with _cache_lock:
        return cache.get(key)


def manifest_path(corpus_root: Path) -> Path:
    return Path(corpus_root) / MANIFEST_DIRNAME / MANIFEST_FILENAME


def _key(line: dict[str, Any]) -> Key:
    return (
        str(line.get("corpus")),
        str(line.get("iri")),
        str(line.get("document_id")),
        str(line.get("proposition_id")),
    )


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _iter_lines(path: Path) -> Iterator[dict[str, Any]]:
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue  # a torn trailing line after a crash
            if isinstance(obj, dict):
                yield obj


def manifest_lines(corpus: str, entries: Iterable[ManifestEntry]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in entries:
        for source in entry.sources:
            out.append(
                {"corpus": corpus, "iri": entry.iri, "source_uri": entry.source_uri,
                 **source.model_dump(mode="json")}
            )
    return out


def _acquire(lock_fd: int, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                raise
        if time.monotonic() >= deadline:
            raise ManifestBusy("bridge-ingest manifest is locked by another writer; retry")
        time.sleep(_LOCK_POLL_S)


def _seen_keys(path: Path) -> set[Key]:
    stamp = _stamp(path)
    if stamp is None:
        return set()
    cached = _cache_get(_SEEN, str(path))
    if cached is not None and cached[0] == stamp:
        return set(cached[1])
    seen = {_key(line) for line in _iter_lines(path)}
    _cache_put(_SEEN, str(path), (stamp, set(seen)))
    return seen


def append_manifest(
    corpus_root: Path,
    corpus: str,
    entries: Iterable[ManifestEntry],
    *,
    pii_gate: PiiGate | None = None,
    lock_timeout_s: float | None = None,
) -> tuple[int, list[RefusedManifestLine]]:
    """Append the not-yet-recorded, PII-clean lines of ``entries``.

    Returns ``(lines added, lines refused by the PII gate)``. Raises
    ``ManifestBusy`` when the lock stays held.
    """
    gate = pii_gate if pii_gate is not None else PiiGate()
    candidates: list[dict[str, Any]] = []
    refused: list[RefusedManifestLine] = []
    for line in manifest_lines(corpus, entries):
        try:
            gate.check(line)
        except PiiRejected as exc:
            refused.append(
                RefusedManifestLine(
                    iri=str(line.get("iri")), field_path=exc.field_path, pattern=exc.pattern_name,
                )
            )
            continue
        candidates.append(line)
    if not candidates:
        return 0, refused
    path = manifest_path(corpus_root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_fd = os.open(path.parent / LOCK_FILENAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        _acquire(lock_fd, LOCK_TIMEOUT_S if lock_timeout_s is None else lock_timeout_s)
        try:
            seen = _seen_keys(path)
            new: list[dict[str, Any]] = []
            for line in candidates:
                key = _key(line)
                if key in seen:
                    continue
                seen.add(key)
                new.append(line)
            if new:
                payload = "".join(
                    json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n" for line in new
                ).encode("utf-8")
                fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                try:
                    view = memoryview(payload)
                    while view:
                        view = view[os.write(fd, view):]
                    os.fsync(fd)
                finally:
                    os.close(fd)
                stamp = _stamp(path)
                if stamp is not None:
                    _cache_put(_SEEN, str(path), (stamp, seen))
            return len(new), refused
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


def read_manifest(corpus_root: Path, corpus: str) -> dict[str, list[dict[str, Any]]]:
    """``iri -> manifest lines`` for one corpus (file order). Takes no lock.

    The returned mapping may be shared with a cache: treat it as read-only.
    """
    path = manifest_path(corpus_root)
    stamp = _stamp(path)
    if stamp is None:
        return {}
    key = (str(path), corpus)
    cached = _cache_get(_READ, key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    out: dict[str, list[dict[str, Any]]] = {}
    for line in _iter_lines(path):
        if line.get("corpus") != corpus:
            continue
        out.setdefault(str(line.get("iri")), []).append(line)
    _cache_put(_READ, key, (stamp, out))
    return out


async def append_manifest_async(
    corpus_root: Path,
    corpus: str,
    entries: Iterable[ManifestEntry],
    *,
    pii_gate: PiiGate | None = None,
    lock_timeout_s: float | None = None,
) -> tuple[int, list[RefusedManifestLine]]:
    """``append_manifest`` in a worker thread (never blocks the event loop)."""
    items = list(entries)
    return await asyncio.to_thread(
        append_manifest, corpus_root, corpus, items,
        pii_gate=pii_gate, lock_timeout_s=lock_timeout_s,
    )


async def read_manifest_async(corpus_root: Path, corpus: str) -> dict[str, list[dict[str, Any]]]:
    """``read_manifest`` in a worker thread."""
    return await asyncio.to_thread(read_manifest, corpus_root, corpus)


__all__ = [
    "LOCK_FILENAME",
    "LOCK_TIMEOUT_S",
    "MANIFEST_DIRNAME",
    "MANIFEST_FILENAME",
    "ManifestBusy",
    "RefusedManifestLine",
    "append_manifest",
    "append_manifest_async",
    "manifest_lines",
    "manifest_path",
    "read_manifest",
    "read_manifest_async",
]
