"""Phase 11 full SHACL on storage writes: checks, the status marker, reports.

Write-time checks (plan KTD4/KTD5):

* ``check_shard_payload`` runs the local tier of the suite on a shard's
  current-version payload. A Violation raises ``ShaclViolation``; Warnings
  never refuse. It runs in-process or inside the bulk-load pool workers.
* ``check_event`` runs the governance-event shapes on an event as the
  projection renders it, inside the write transaction (where its log
  position is known).

Status marker (plan KTD7): one JSON sidecar per corpus,
``<root>/shacl-status/<sha256(corpus)[:32]>.json``, written atomically under
its own ``flock``. It records:

* ``suite_digest``: which suite produced the result;
* ``position`` and ``payload_sha256``: the last journal row the result covers;
* ``failing``: Violation focus nodes, capped at ``MAX_FAILING``, with
  ``failing_truncated`` set when the cap was hit;
* ``warnings``: the Warning count of the last full validation, or ``None``
  when no full validation has run.

A write advances the marker only when it is contiguous with it: the marker
covers exactly the rows before the write, under the same suite. Anything else
leaves the marker behind the head, and ``status()`` then reads
``unvalidated``. That covers a write from a suite-less context, a concurrent
writer that lost the race, a restored journal, or a changed suite. Snapshots
do not copy the sidecar, so a restored root reads ``unvalidated`` until it is
validated again. None of these cases can report a false ``pass``.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from folio_insights.shapes.compiled import ShaclResult, turtle_graph
from folio_insights.shapes.suite import ShaclSuite
from folio_insights.storage.errors import ShaclViolation

STATUS_DIRNAME = "shacl-status"
MARKER_FORMAT = 1
MAX_FAILING = 1000

DISABLED = "disabled"
UNVALIDATED = "unvalidated"
PASS = "pass"
FAIL = "fail"
FULL_SHACL_STATES: tuple[str, ...] = (DISABLED, UNVALIDATED, PASS, FAIL)


def result_entry(result: ShaclResult, tier: str) -> dict[str, Any]:
    """A result as recorded and raised: no offending value, only fixed text."""
    entry = result.as_dict()
    entry.pop("value", None)
    entry["tier"] = tier
    return entry


# ── write-time checks ─────────────────────────────────────────────────────


def check_shard_payload(payload: bytes | Mapping[str, Any], suite: ShaclSuite) -> int:
    """Local-tier check of one shard record; returns its Warning count."""
    data = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
    report = suite.validate_shard(data)
    if report.violations:
        subject = f"shard {data.get('shard_iri')!r}" if isinstance(data, Mapping) else "shard"
        raise ShaclViolation(subject, [result_entry(r, "local") for r in report.violations])
    return len(report.warnings)


def event_graph(corpus: str, event_json: Mapping[str, Any]):  # noqa: ANN201 - ValidationGraph
    """A governance event rendered exactly as the projection stores it."""
    from folio_insights.storage.projection import governance_triples

    lines = "".join(
        f"{s} {p} {o} .\n"
        for s, p, o in governance_triples(corpus, dict(event_json), journal_position=0)
    )
    return turtle_graph(lines, prefix="ev")


def check_event(corpus: str, event_json: Mapping[str, Any], suite: ShaclSuite) -> int:
    report = suite.validate_graph(event_graph(corpus, event_json))
    if report.violations:
        raise ShaclViolation(
            f"governance {event_json.get('action')!r} event",
            [result_entry(r, "local") for r in report.violations],
        )
    return len(report.warnings)


# ── status marker ─────────────────────────────────────────────────────────


@dataclass
class ShaclMarker:
    corpus: str
    suite_digest: str
    position: int
    payload_sha256: str | None
    failing: list[dict[str, Any]] = field(default_factory=list)
    failing_truncated: bool = False
    warnings: int | None = None
    updated_by: str = "incremental"
    format: int = MARKER_FORMAT

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ShaclMarker | None:
        if data.get("format") != MARKER_FORMAT:
            return None
        try:
            return cls(
                corpus=str(data["corpus"]),
                suite_digest=str(data["suite_digest"]),
                position=int(data["position"]),
                payload_sha256=data.get("payload_sha256"),
                failing=list(data.get("failing") or []),
                failing_truncated=bool(data.get("failing_truncated", False)),
                warnings=data.get("warnings"),
                updated_by=str(data.get("updated_by", "incremental")),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _marker_stem(corpus: str) -> str:
    return hashlib.sha256(corpus.encode("utf-8")).hexdigest()[:32]


class MarkerStore:
    """The sidecar for one corpus under one storage root."""

    def __init__(self, root: Path, corpus: str) -> None:
        self.dir = root / STATUS_DIRNAME
        self.corpus = corpus
        stem = _marker_stem(corpus)
        self.path = self.dir / f"{stem}.json"
        self.lock_path = self.dir / f"{stem}.lock"

    def read(self) -> ShaclMarker | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return None
        marker = ShaclMarker.from_json(data)
        if marker is None or marker.corpus != self.corpus:
            return None
        return marker

    def _write(self, marker: ShaclMarker) -> None:
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".marker-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(asdict(marker), handle, sort_keys=True, indent=1)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def update(self, fn) -> ShaclMarker | None:  # noqa: ANN001 - (marker|None) -> marker|None
        """Read-modify-write under the marker lock; ``fn`` returns the new
        marker, or ``None`` to leave the file unchanged."""
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            new = fn(self.read())
            if new is not None:
                self._write(new)
            return new
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def cap_failing(entries: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    unique: dict[tuple, dict[str, Any]] = {}
    for entry in entries:
        key = (entry.get("focus"), entry.get("source_shape"), entry.get("path"), entry.get("component"))
        unique.setdefault(key, entry)
    ordered = sorted(unique.values(), key=lambda e: (str(e.get("focus")), str(e.get("source_shape"))))
    return ordered[:MAX_FAILING], len(ordered) > MAX_FAILING


@dataclass(frozen=True)
class ShaclStatus:
    state: str
    suite_digest: str | None = None
    validated_through: int | None = None
    violations: int = 0
    warnings: int | None = None


@dataclass(frozen=True)
class CorpusValidation:
    """Result of ``CorpusStorageContext.validate_corpus``."""

    corpus: str
    position: int
    suite_digest: str
    engine: str
    shards: int
    events: int
    conforms: bool
    violations: int
    warnings: int
    results: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["results"] = list(self.results)
        out["full_shacl"] = PASS if self.conforms else FAIL
        return out


__all__ = [
    "DISABLED",
    "FAIL",
    "FULL_SHACL_STATES",
    "MAX_FAILING",
    "PASS",
    "STATUS_DIRNAME",
    "UNVALIDATED",
    "CorpusValidation",
    "MarkerStore",
    "ShaclMarker",
    "ShaclStatus",
    "cap_failing",
    "check_event",
    "check_shard_payload",
    "event_graph",
    "result_entry",
]
