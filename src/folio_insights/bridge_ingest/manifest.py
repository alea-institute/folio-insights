"""The bridge-ingest provenance manifest (plan KTD6).

The shard envelope is ``extra="forbid"`` and owned by another lane, so enrich
provenance (every proposition id, type, span and citation edge behind a shard
IRI) lives beside the journal at ``<corpus storage root>/bridge-ingest/
manifest.jsonl``: one JSON line per ``(corpus, iri, document_id,
proposition_id)``. The storage root holds every corpus, so each line names
its corpus.

Appends take an exclusive ``flock`` on ``manifest.lock`` in the same
directory, re-read the existing keys under the lock, append only new lines
in one ``write`` and ``fsync`` before releasing. Readers never see a partial
line except after a crash mid-write; ``read_manifest`` skips an unparsable
trailing line instead of failing.
"""
from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from folio_insights.bridge_ingest.mapping import ManifestEntry

MANIFEST_DIRNAME = "bridge-ingest"
MANIFEST_FILENAME = "manifest.jsonl"
_LOCK_FILENAME = "manifest.lock"


def manifest_path(corpus_root: Path) -> Path:
    return Path(corpus_root) / MANIFEST_DIRNAME / MANIFEST_FILENAME


def _key(line: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(line.get("corpus")),
        str(line.get("iri")),
        str(line.get("document_id")),
        str(line.get("proposition_id")),
    )


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


def append_manifest(corpus_root: Path, corpus: str, entries: Iterable[ManifestEntry]) -> int:
    """Append the not-yet-recorded lines of ``entries``; return how many were added."""
    candidates = manifest_lines(corpus, entries)
    if not candidates:
        return 0
    path = manifest_path(corpus_root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_fd = os.open(path.parent / _LOCK_FILENAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        seen = {_key(line) for line in _iter_lines(path)}
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
        return len(new)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def read_manifest(corpus_root: Path, corpus: str) -> dict[str, list[dict[str, Any]]]:
    """``iri -> manifest lines`` for one corpus (file order)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for line in _iter_lines(manifest_path(corpus_root)):
        if line.get("corpus") != corpus:
            continue
        out.setdefault(str(line.get("iri")), []).append(line)
    return out


__all__ = [
    "MANIFEST_DIRNAME",
    "MANIFEST_FILENAME",
    "append_manifest",
    "manifest_lines",
    "manifest_path",
    "read_manifest",
]
