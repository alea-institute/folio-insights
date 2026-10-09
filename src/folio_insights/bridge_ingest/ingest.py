"""Ingest a folio-enrich proposition record into a corpus as hypothesis shards.

Writes go through ``CorpusStorageContext.ingest_shards`` so the PII gate, model
validation and the SHACL suite apply unchanged. Ingest is idempotent per shard
IRI (plan R12): an IRI already in the corpus is never rewritten and is
reported as ``existing``; only new IRIs are written, in one batch.

Operation IDs are deterministic: ``bridge-ingest:<record sha256[:16]>:<sha256
of the sorted new IRIs[:16]>`` (or the caller's ``op_id``). The second part
keeps a retry that finds fewer new IRIs (some landed meanwhile) from reusing
an operation ID for a different batch.

Races: another writer can land an IRI between the existence check and the
write. The same record pushed twice surfaces as ``OperationIdConflict`` (or
replays the committed batch); a different record that shares a span surfaces
as ``ShardIdentityViolation`` (its ``extracted_at`` or extractor differs from
the committed revision). Either way ingest re-checks which IRIs exist and
retries, at most ``MAX_ATTEMPTS`` times. After the write, every shard
reported refused is checked once more: one that is in the corpus (it landed
from the other writer) moves to ``existing`` and keeps its manifest
provenance.

When the batch is refused (PII, SHACL, record validation), each new shard is
retried alone so one refused shard is reported as ``refused`` instead of
sinking the record; the others still land.

The provenance manifest is appended after the shards, in a worker thread,
through the same PII gate (``ManifestBusy`` if its lock stays held; the shards
are already committed then, and a re-push appends the provenance).
"""
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from folio_propositions import PropositionDocumentRecord
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from folio_insights.bridge_ingest.manifest import RefusedManifestLine, append_manifest_async
from folio_insights.bridge_ingest.mapping import (
    DEFAULT_EXTRACTOR_DID,
    DEFAULT_FRAMEWORK_ID,
    SkippedProposition,
    propositions_to_shards,
)
from folio_insights.bridge_ingest.record import load_record
from folio_insights.shards.subtypes import HypothesisShard
from folio_insights.storage import (
    OperationIdConflict,
    PiiRejected,
    ShaclViolation,
    ShardIdentityViolation,
    ShardRecordInvalid,
    StorageConfig,
    open_corpus_storage,
)

MAX_ATTEMPTS = 3

# Per-shard refusals: the storage gates' input refusals. Everything else
# (storage failures, lock timeouts) propagates.
REFUSALS: tuple[type[BaseException], ...] = (
    PiiRejected,
    ShaclViolation,
    ShardRecordInvalid,
    ShardIdentityViolation,
    ValidationError,
)


class RefusedShard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iri: str
    reason: str


class IngestReport(BaseModel):
    """What one ingest did. Counts and the IRIs behind them."""

    model_config = ConfigDict(extra="forbid")

    corpus: str
    document_id: str
    op_id: str | None = None
    created: int = 0
    existing: int = 0
    skipped: int = 0
    refused: int = 0
    created_iris: list[str] = Field(default_factory=list)
    existing_iris: list[str] = Field(default_factory=list)
    skipped_propositions: list[SkippedProposition] = Field(default_factory=list)
    refused_shards: list[RefusedShard] = Field(default_factory=list)
    manifest_lines_added: int = 0
    manifest_refused: list[RefusedManifestLine] = Field(default_factory=list)


OPEN_ATTEMPTS = 5


async def _open_storage(root: Path, corpus: str, config: StorageConfig | None) -> Any:
    """``open_corpus_storage`` with a short retry on SQLite "database is locked".

    Two processes (or contexts) opening a brand-new journal at the same moment
    race on ``PRAGMA journal_mode = WAL``, which does not wait on the busy
    timeout; the loser gets ``sqlite3.OperationalError``. Concurrent first
    pushes to a fresh storage root hit exactly that, so retry a few times.
    """
    for attempt in range(OPEN_ATTEMPTS):
        try:
            return await open_corpus_storage(root, corpus, config=config)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or attempt == OPEN_ATTEMPTS - 1:
                raise
            await asyncio.sleep(0.05 * (attempt + 1))
    raise AssertionError("unreachable")  # pragma: no cover


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _reason(exc: BaseException) -> str:
    if isinstance(exc, ValidationError):
        return f"ValidationError: {exc.error_count()} error(s)"
    return f"{type(exc).__name__}: {exc}"


async def _write_new(ctx: Any, new: list[HypothesisShard], op: str) -> tuple[list[str], list[RefusedShard]]:
    try:
        await ctx.ingest_shards(new, op_id=op)
        return [s.shard_iri for s in new], []
    except REFUSALS:
        if len(new) == 1:
            raise
    created: list[str] = []
    refused: list[RefusedShard] = []
    for shard in new:
        iri_hex = shard.shard_iri.rsplit("/", 1)[-1]
        try:
            await ctx.ingest_shards([shard], op_id=f"{op}:{iri_hex}")
        except REFUSALS as exc:
            refused.append(RefusedShard(iri=shard.shard_iri, reason=_reason(exc)))
        else:
            created.append(shard.shard_iri)
    return created, refused


async def ingest_record(
    record_or_path: PropositionDocumentRecord | Mapping[str, Any] | bytes | str | Path,
    *,
    corpus_root: str | Path,
    corpus: str,
    framework_id: str = DEFAULT_FRAMEWORK_ID,
    extractor_did: str = DEFAULT_EXTRACTOR_DID,
    op_id: str | None = None,
    storage_config: StorageConfig | None = None,
    now: datetime | None = None,
) -> IngestReport:
    """Ingest one record (any form ``load_record`` accepts) into ``corpus``.

    Raises a ``BridgeIngestError`` (``ValueError``) when the record itself is
    refused (invalid, no ``source_uri``, ``content_iri`` mismatch); nothing is
    written then. Storage-layer failures propagate unchanged.
    """
    loaded = load_record(record_or_path)
    record = loaded.record
    mapped = propositions_to_shards(
        record, framework_id=framework_id, extractor_did=extractor_did, now=now
    )
    report = IngestReport(
        corpus=corpus,
        document_id=record.document_id,
        skipped=len(mapped.skipped),
        skipped_propositions=mapped.skipped,
    )
    root = Path(corpus_root)
    ctx = await _open_storage(root, corpus, storage_config)
    pii_gate = ctx.config.pii_gate
    try:
        created: list[str] = []
        refused: list[RefusedShard] = []
        existing: list[str] = []
        for attempt in range(MAX_ATTEMPTS):
            existing = [
                s.shard_iri for s in mapped.shards
                if await ctx.shards.get_record(s.shard_iri) is not None
            ]
            present = set(existing)
            new = [s for s in mapped.shards if s.shard_iri not in present]
            created, refused = [], []
            if not new:
                break
            op = op_id or (
                f"bridge-ingest:{loaded.sha256[:16]}:"
                f"{_sha(chr(10).join(sorted(s.shard_iri for s in new)))[:16]}"
            )
            report.op_id = op
            try:
                created, refused = await _write_new(ctx, new, op)
            except (OperationIdConflict, ShardIdentityViolation) as exc:
                # Another writer landed some IRIs first: re-check and retry.
                last = attempt == MAX_ATTEMPTS - 1
                if last or (op_id is not None and isinstance(exc, OperationIdConflict)):
                    raise
                continue
            except REFUSALS as exc:  # a one-shard batch refused
                refused = [RefusedShard(iri=new[0].shard_iri, reason=_reason(exc))]
            break
        # A shard refused because another writer landed the same IRI is present.
        still_refused: list[RefusedShard] = []
        for item in refused:
            if await ctx.shards.get_record(item.iri) is not None:
                existing.append(item.iri)
            else:
                still_refused.append(item)
        refused = still_refused
    finally:
        await ctx.close()

    order = {s.shard_iri: i for i, s in enumerate(mapped.shards)}
    existing = sorted(set(existing), key=order.__getitem__)
    report.created, report.created_iris = len(created), created
    report.existing, report.existing_iris = len(existing), existing
    report.refused, report.refused_shards = len(refused), refused
    landed = set(created) | set(existing)
    report.manifest_lines_added, report.manifest_refused = await append_manifest_async(
        root, corpus, [entry for entry in mapped.manifest if entry.iri in landed],
        pii_gate=pii_gate,
    )
    return report


__all__ = ["MAX_ATTEMPTS", "REFUSALS", "IngestReport", "RefusedShard", "ingest_record"]
