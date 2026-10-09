"""Ingest a folio-enrich proposition record into a corpus as hypothesis shards.

Writes go through ``CorpusStorageContext.ingest_shards`` so the PII gate, model
validation and the SHACL suite apply unchanged. Ingest is idempotent per shard
IRI (plan R12): an IRI already in the corpus is never rewritten and is
reported as ``existing``; only new IRIs are written, in one batch.

Operation IDs are deterministic: ``bridge-ingest:<record sha256[:16]>:<sha256
of the sorted new IRIs[:16]>`` (or the caller's ``op_id``). The second part
keeps a retry that finds fewer new IRIs (some landed meanwhile) from reusing
an operation ID for a different batch. A concurrent writer that commits the
same IRIs first surfaces as ``OperationIdConflict``; ingest then re-checks
which IRIs exist and retries once.

When the batch is refused (PII, SHACL, record validation), each new shard is
retried alone so one refused shard is reported as ``refused`` instead of
sinking the record; the others still land.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from folio_propositions import PropositionDocumentRecord
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from folio_insights.bridge_ingest.manifest import append_manifest
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
    ctx = await open_corpus_storage(root, corpus, config=storage_config)
    try:
        created: list[str] = []
        refused: list[RefusedShard] = []
        existing: list[str] = []
        for attempt in range(2):
            existing = [
                s.shard_iri for s in mapped.shards
                if await ctx.shards.get_record(s.shard_iri) is not None
            ]
            present = set(existing)
            new = [s for s in mapped.shards if s.shard_iri not in present]
            if not new:
                break
            op = op_id or (
                f"bridge-ingest:{loaded.sha256[:16]}:"
                f"{_sha(chr(10).join(sorted(s.shard_iri for s in new)))[:16]}"
            )
            report.op_id = op
            try:
                created, refused = await _write_new(ctx, new, op)
            except REFUSALS as exc:  # a one-shard batch refused
                created, refused = [], [RefusedShard(iri=new[0].shard_iri, reason=_reason(exc))]
                break
            except OperationIdConflict:
                if attempt == 1 or op_id is not None:
                    raise
                continue  # another writer landed some IRIs: re-check and retry
            break
    finally:
        await ctx.close()

    report.created, report.created_iris = len(created), created
    report.existing, report.existing_iris = len(existing), existing
    report.refused, report.refused_shards = len(refused), refused
    landed = set(created) | set(existing)
    report.manifest_lines_added = append_manifest(
        root, corpus, [entry for entry in mapped.manifest if entry.iri in landed]
    )
    return report


__all__ = ["REFUSALS", "IngestReport", "RefusedShard", "ingest_record"]
