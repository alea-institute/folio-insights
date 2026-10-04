"""Process-parallel CPU stages for bulk loads (Phase 13 U4).

Two pure, deterministic stages dominate a bulk load and hold the GIL:

* ``prepare_chunk`` — the per-record write checks of
  ``CorpusStorageContext._prepare`` minus the Phase 11 hook: the PII gate over
  the parsed raw input, the U17 adapter (full model validation), and the PII
  gate over a migrated payload. It returns bytes only.
* ``render_chunk`` — journal rows to N-Quads text (the projection adapters).

Both run in a ``forkserver`` process pool only for batches of at least
``PARALLEL_MIN_ITEMS``; smaller batches, and any environment where the pool
cannot start, run the same functions in-process. The result is identical
either way: workers run the very functions the serial path runs, chunks keep
input order, and the first refusal in input order is the one raised.

Nothing here writes: the parent process still owns the journal transaction
and every projection write.
"""
from __future__ import annotations

import atexit
import json
import logging
import multiprocessing
import os
import pickle
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

PARALLEL_MIN_ITEMS = 2048
_CHUNK = 1024
_MAX_WORKERS = 8

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class PreparedRecord:
    """A record that passed the per-record checks, as bytes.

    ``original_bytes`` is ``None`` when the input bytes ARE the payload (a
    current-version record), mirroring the journal's NULL convention.
    """

    original_bytes: bytes | None
    payload: bytes
    source_schema_version: int
    record_schema_version: int
    shard_iri: str

    @property
    def original(self) -> bytes:
        return self.payload if self.original_bytes is None else self.original_bytes


def prepare_one(raw: bytes | str | Any, gate: Any) -> tuple[Any, PreparedRecord]:
    """``(loaded record, PreparedRecord)`` for one raw record (in-process)."""
    from pydantic import ValidationError

    from folio_insights.shards import dump_shard_record, load_shard_record
    from folio_insights.storage.context import _parse_raw_json, _sanitized_validation_error

    parsed = _parse_raw_json(raw)
    if parsed is not None:
        gate.check(parsed)
    try:
        loaded = load_shard_record(raw)
    except ValidationError as exc:
        raise _sanitized_validation_error(exc) from None
    if parsed is None:  # pragma: no cover - load_shard_record refuses non-JSON
        gate.check(json.loads(loaded.original_bytes))
    payload = dump_shard_record(loaded.shard)
    if payload != loaded.original_bytes:
        gate.check(json.loads(payload))
    return loaded, PreparedRecord(
        original_bytes=None if payload == loaded.original_bytes else loaded.original_bytes,
        payload=payload,
        source_schema_version=loaded.source_schema_version,
        record_schema_version=loaded.shard.schema_version,
        shard_iri=loaded.shard.shard_iri,
    )


def prepare_chunk(
    raws: Sequence[bytes | str], gate: Any
) -> tuple[list[PreparedRecord], tuple[int, BaseException] | None]:
    """Prepare ``raws`` in order; stop at the first refusal and return it
    with its index in the chunk (exceptions cross the process boundary)."""
    out: list[PreparedRecord] = []
    for index, raw in enumerate(raws):
        try:
            out.append(prepare_one(raw, gate)[1])
        except Exception as exc:  # noqa: BLE001 - re-raised by the parent
            return out, (index, exc)
    return out, None


def render_chunk(rows: Sequence[Any], corpus: str) -> bytes:
    """UTF-8 N-Quads for journal ``rows`` (same adapters as ``apply``)."""
    from folio_insights.storage.projection import row_triples

    parts: list[str] = []
    for row in rows:
        graph, _, triples = row_triples(corpus, row)
        parts.extend(f"{s} {p} {o} {graph} .\n" for s, p, o in triples)
    return "".join(parts).encode("utf-8")


# ── pool ──────────────────────────────────────────────────────────────────

_pool: ProcessPoolExecutor | None = None
_pool_failed = False


def _shutdown() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


def _get_pool() -> ProcessPoolExecutor | None:
    global _pool, _pool_failed
    if _pool is not None or _pool_failed:
        return _pool
    workers = min(_MAX_WORKERS, max(1, (os.cpu_count() or 1) - 1))
    if workers < 2:
        _pool_failed = True
        return None
    try:
        ctx = multiprocessing.get_context("forkserver")
        ctx.set_forkserver_preload(["folio_insights.storage._parallel"])
        _pool = ProcessPoolExecutor(max_workers=workers, mp_context=ctx)
        atexit.register(_shutdown)
    except (OSError, ValueError) as exc:  # pragma: no cover - environment-specific
        logger.warning("bulk-load process pool unavailable, running serially: %s", exc)
        _pool_failed = True
        _pool = None
    return _pool


def _picklable(value: Any) -> bool:
    try:
        pickle.dumps(value)
    except Exception:  # noqa: BLE001 - any failure means "run in-process"
        return False
    return True


def map_chunks(
    fn: Callable[..., R],
    items: Sequence[T],
    *args: Any,
    parallel: bool = True,
) -> list[R]:
    """``[fn(chunk, *args) for chunk in chunks(items)]``, in input order.

    Runs in the process pool only when ``parallel`` and the batch is large
    enough and ``args`` pickle; otherwise in-process. A pool failure
    (``BrokenProcessPool``, ``OSError``) falls back to in-process for the
    whole batch, so a result never mixes the two.
    """
    global _pool_failed
    chunks = [items[i : i + _CHUNK] for i in range(0, len(items), _CHUNK)]
    pool = (
        _get_pool()
        if parallel and len(items) >= PARALLEL_MIN_ITEMS and _picklable(args)
        else None
    )
    if pool is not None:
        try:
            return list(pool.map(fn, chunks, *[[a] * len(chunks) for a in args]))
        except (OSError, RuntimeError) as exc:  # BrokenProcessPool is a RuntimeError
            logger.warning(
                "bulk-load process pool failed, running serially from now on: %s",
                str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__,
            )
            _shutdown()
            _pool_failed = True
    return [fn(chunk, *args) for chunk in chunks]


__all__ = [
    "PARALLEL_MIN_ITEMS",
    "PreparedRecord",
    "map_chunks",
    "prepare_chunk",
    "prepare_one",
    "render_chunk",
]
