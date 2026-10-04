"""Corpus storage context: one journal, one projection, one corpus (Phase 13 U2).

``CorpusStorageContext.open(root, corpus)`` is the single constructor callers
use (U3 wires every CLI command through it). It owns:

* the SQLite journal (``<root>/journal.sqlite3``) — the authoritative commit
  record for shard revisions and governance events (KTD2);
* the Oxigraph projection (``<root>/projection.oxigraph``) — a replayable
  named-graph view with a durable per-corpus applied-position watermark;
* ``shards`` (``PersistentShardStore``) and ``governance``
  (``PersistentGovernanceLog``), the persistent implementations of the
  existing ``ShardStore`` and five-method ``GovernanceLog`` seams.

Write path (KTD3): validate and gate the input, then inside one
``BEGIN IMMEDIATE`` transaction check operation-ID replay, re-check state
(authorization, identity) against that transaction's view, allocate the next
``(corpus, position)`` and append. After COMMIT the projection catches up. A
projection failure after COMMIT is *pending recovery*, not an abort: the call
raises ``ProjectionRecoveryPending`` and closes the context; reopening replays
the journal, and retrying the operation ID returns the committed result.

Read path: every read first passes the barrier, which brings the projection's
watermark up to the journal head, then reads at ``position <= watermark``. A
barrier failure closes the context rather than serve a mixed revision.

Two databases are never committed atomically together and this module never
claims they are; the watermark is what makes the pair coherent.

Seams left for later units:

* U3 — CLI wiring: construct one context per command from the corpus root and
  pass ``ctx.shards`` / ``ctx.governance`` where the CLI now builds in-memory
  doubles. ``retract`` should use ``ShardStore.dependents_of`` instead of
  ``store._d``, and pass an explicit ``op_id`` (stored in the saved preview)
  so a retried ``--apply`` commits at most once.
* U4 — exports, bulk load, dumps and restore: ``ctx.query`` (corpus-scoped,
  read-only SPARQL), ``PersistentShardStore.get_record`` (original bytes and
  source version), ``journal_path`` / ``projection_path`` for snapshots, and
  ``rebuild_projection`` after a restore. Full SHACL is deferred to Phase 11;
  ``StorageConfig.shard_validator`` is the explicit hook and ``status()``
  reports ``full_shacl='deferred-to-phase-11'`` until it is wired.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import jcs
from pydantic import TypeAdapter, ValidationError

from folio_insights.governance.events import GovernanceEvent
from folio_insights.governance.log import InMemoryGovernanceLog, InvalidSignature
from folio_insights.shards import (
    LoadedShardRecord,
    ShardEnvelope,
    dump_shard_record,
    load_shard_record,
)
from folio_insights.shards.records import IDENTITY_FIELDS
from folio_insights.storage.errors import (
    CorpusIsolationError,
    GovernanceEventReplayed,
    OperationIdConflict,
    ProjectionRecoveryFailed,
    ProjectionRecoveryPending,
    ShardIdentityViolation,
    ShardRecordInvalid,
    StorageClosed,
)
from folio_insights.storage.journal import (
    GOVERNANCE_RECORD_SCHEMA_VERSION,
    JOURNAL_FILENAME,
    KIND_GOVERNANCE,
    KIND_SHARD,
    Journal,
    JournalRow,
    JournalTransaction,
    PendingRow,
    check_replay,
    sha256_hex,
)
from folio_insights.storage.pii import PiiGate
from folio_insights.storage.projection import (
    PROJECTION_ADAPTER_VERSION,
    PROJECTION_DIRNAME,
    ProjectionHandle,
    ProjectionLock,
)

T = TypeVar("T")

FULL_SHACL_STATUS = "deferred-to-phase-11"

_EVENT_ADAPTER: TypeAdapter = TypeAdapter(GovernanceEvent)

EventVerifier = Callable[[GovernanceEvent], Awaitable[bool]]


async def verify_event_signature_offline(event: GovernanceEvent) -> bool:
    """Phase 6 ``verify_attestation`` over the event payload, with no network.

    did:key signers verify offline. Any resolver that would need the network
    (did:web, did:plc) is refused, so the event fails closed until U3 supplies
    a pre-populated ``DidDocCache``.
    """
    from folio_insights.identity.cache import InMemoryDidDocCache
    from folio_insights.identity.verifier import verify_attestation

    if not event.signature.signature:
        return False

    async def _no_network(*_args: Any) -> dict:
        raise ConnectionRefusedError("storage signature verification is offline")

    payload = event.signature_payload().decode("utf-8")
    return await verify_attestation(
        payload,
        event.signature,
        cache=InMemoryDidDocCache(),
        http=_no_network,
        plc_resolver=_no_network,
    )


@dataclass(frozen=True)
class StorageConfig:
    """Per-context storage policy.

    * ``pii_gate`` — the configurable ingest gate (defaults: SSN, ABA, phone).
    * ``event_verifier`` — signature check run on every governance append
      before the journal transaction; ``None`` disables it (test doubles only).
    * ``shard_validator`` — Phase 11 full-SHACL hook, called on every shard
      write before the journal append. ``None`` means deferred, and
      ``status()`` says so; it is never reported as passed.
    """

    pii_gate: PiiGate = field(default_factory=PiiGate)
    event_verifier: EventVerifier | None = verify_event_signature_offline
    shard_validator: Callable[[ShardEnvelope], None] | None = None
    busy_timeout_s: float = 30.0
    projection_lock_timeout_s: float = 120.0
    replay_batch_size: int = 256


@dataclass(frozen=True)
class StorageStatus:
    corpus: str
    journal_head: int
    projection_watermark: int
    projection_adapter_version: int
    full_shacl: str


@dataclass(frozen=True)
class StoredShardRecord:
    """A shard revision as the journal holds it (U4 export / audit seam)."""

    shard: ShardEnvelope
    position: int
    original_bytes: bytes
    source_schema_version: int
    payload: bytes


def _event_from_row(row: JournalRow) -> GovernanceEvent:
    return _EVENT_ADAPTER.validate_json(row.payload)


def _canonical_sha(data: Any) -> str:
    return hashlib.sha256(jcs.canonicalize(data)).hexdigest()


def _replay_keys(event: GovernanceEvent) -> tuple[str | None, tuple[str, str]]:
    """What identifies a signed governance event independent of its
    operation ID: the signature value, and the (signer DID, signed payload
    hash) pair."""
    payload_sha = hashlib.sha256(event.signature_payload()).hexdigest()
    return (event.signature.signature or None), (event.signature.did, payload_sha)


def _refuse_replayed_event(event: GovernanceEvent, history: list[GovernanceEvent]) -> None:
    """Refuse ``event`` if its signature value, or its (signer DID, signed
    payload hash), already appears in committed ``history``.

    The v2 signed payload (``events.SIGNATURE_PAYLOAD_FORMAT``) binds
    ``signed_at``, the signer DID and ``did_doc_snapshot_at``, so a legitimate
    repeat by the same signer (revoke, re-grant, revoke) signs a different
    payload and is accepted, and a replay with a moved ``signed_at`` fails
    signature verification before this point. What remains is the verbatim
    replay, possibly under a fresh operation ID; this check refuses it.
    """
    signature, signed = _replay_keys(event)
    for prior in history:
        prior_signature, prior_signed = _replay_keys(prior)
        if (signature is not None and signature == prior_signature) or signed == prior_signed:
            raise GovernanceEventReplayed(
                f"governance {event.action} event signed by {event.signature.did!r} "
                f"is already journaled at governance position {prior.position}; "
                "a committed signed event cannot be appended again"
            )


_SAFE_LOC_PART = re.compile(r"[a-z_][a-z0-9_]*")


def _safe_loc(err: Mapping[str, Any]) -> str:
    """An error location with input-derived parts masked: an extra key is
    input text, and so is any part that is not a plain snake_case name."""
    loc = list(err["loc"])
    parts: list[str] = []
    for index, part in enumerate(loc):
        if isinstance(part, int):
            parts.append(str(part))
        elif err["type"] == "extra_forbidden" and index == len(loc) - 1:
            parts.append("<extra key>")
        elif isinstance(part, str) and _SAFE_LOC_PART.fullmatch(part):
            parts.append(part)
        else:
            parts.append("<key>")
    return ".".join(parts) or "<root>"


def _sanitized_validation_error(exc: ValidationError) -> ShardRecordInvalid:
    """Re-state a pydantic error with masked locations and error types only;
    no input values, messages or keys."""
    problems = "; ".join(
        f"{_safe_loc(err)}: {err['type']}"
        for err in exc.errors(include_url=False, include_input=False, include_context=False)
    )
    return ShardRecordInvalid(
        f"shard record failed validation ({exc.error_count()} error(s)): {problems}"
    )


def _parse_raw_json(raw: bytes | str | Mapping[str, Any]) -> Any:
    """The raw record as parsed JSON for the pre-validation PII gate, or
    ``None`` when it does not parse (the adapter then refuses it)."""
    if isinstance(raw, Mapping):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


class CorpusStorageContext:
    """Persistent storage bound to one corpus under one storage root."""

    def __init__(self, root: Path, corpus: str, config: StorageConfig) -> None:
        if not isinstance(corpus, str) or not corpus:
            raise ValueError("corpus must be a non-empty string")
        self.root = root
        self.corpus = corpus
        self.config = config
        self._journal = Journal(root / JOURNAL_FILENAME, busy_timeout_s=config.busy_timeout_s)
        self._confirmed = -1
        self._closed = True
        self._write_lock = asyncio.Lock()
        from folio_insights.storage.governance import PersistentGovernanceLog
        from folio_insights.storage.shards import PersistentShardStore

        self.shards = PersistentShardStore(self)
        self.governance = PersistentGovernanceLog(self)

    # ── lifecycle ─────────────────────────────────────────────────────────

    @classmethod
    async def open(
        cls,
        root: str | Path,
        corpus: str,
        *,
        config: StorageConfig | None = None,
    ) -> CorpusStorageContext:
        """Open (creating if needed) and recover: replay any committed journal
        rows the projection has not applied. Raises ``ProjectionRecoveryFailed``
        if recovery cannot finish; nothing is served in that case."""
        root_path = Path(root)
        root_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        ctx = cls(root_path, corpus, config or StorageConfig())
        await ctx._journal.open()
        ctx._closed = False
        try:
            await ctx._catch_up()
        except Exception as exc:
            await ctx._fail_closed()
            if isinstance(exc, ProjectionRecoveryFailed):
                raise
            raise ProjectionRecoveryFailed(
                f"projection recovery for corpus {corpus!r} could not finish: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        return ctx

    async def close(self) -> None:
        self._closed = True
        await self._journal.close()

    async def __aenter__(self) -> CorpusStorageContext:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def journal_path(self) -> Path:
        return self.root / JOURNAL_FILENAME

    @property
    def projection_path(self) -> Path:
        return self.root / PROJECTION_DIRNAME

    def _ensure_open(self) -> None:
        if self._closed:
            raise StorageClosed(f"storage context for corpus {self.corpus!r} is closed")

    def _check_corpus(self, corpus: str) -> None:
        if corpus != self.corpus:
            raise CorpusIsolationError(
                f"this storage context is bound to corpus {self.corpus!r}, "
                f"not {corpus!r}"
            )

    async def _fail_closed(self) -> None:
        self._closed = True
        await self._journal.close()

    # ── projection catch-up / barrier ─────────────────────────────────────

    async def _acquire(self, lock: ProjectionLock) -> None:
        deadline = lock.deadline()
        delay = 0.002
        while not lock.try_acquire():
            if time.monotonic() > deadline:
                raise lock.timeout_error()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 0.05)

    async def _catch_up(
        self,
        read: Callable[[ProjectionHandle, int], T] | None = None,
        *,
        rebuild: bool = False,
    ) -> tuple[int, T | None]:
        """Under the projection lock: replay journal rows past the watermark,
        then (optionally) run ``read`` against the caught-up projection.

        Journal reads here go through the journal's read-only connection, so
        they see committed rows only, never an open write transaction. A
        projection watermark past the committed head is rebuilt.

        Catch-up failures propagate as-is (callers decide to fail closed);
        an exception from ``read`` is wrapped in ``_ReadError`` so it does not
        close the context.
        """
        lock = ProjectionLock(self.root, timeout_s=self.config.projection_lock_timeout_s)
        await self._acquire(lock)
        try:
            handle = await asyncio.to_thread(ProjectionHandle, self.root)
            try:
                state = await asyncio.to_thread(handle.state, self.corpus)
                head = await self._journal.head(self.corpus)
                stale_adapter = state.adapter_version not in (None, PROJECTION_ADAPTER_VERSION)
                if rebuild or stale_adapter or state.watermark > head:
                    # KTD5: derived RDF is rebuilt from the journal, never trusted
                    # past it (e.g. a projection newer than a restored journal).
                    await asyncio.to_thread(handle.reset, self.corpus)
                    watermark = -1
                else:
                    watermark = state.watermark
                while watermark < head:
                    rows = await self._journal.rows_after(
                        self.corpus, watermark, limit=self.config.replay_batch_size
                    )
                    if not rows:
                        break
                    watermark = await asyncio.to_thread(handle.apply, self.corpus, rows)
                    self._confirmed = watermark
                self._confirmed = watermark
                result: T | None = None
                if read is not None:
                    try:
                        result = await asyncio.to_thread(read, handle, watermark)
                    except Exception as exc:
                        raise _ReadError(exc) from exc
                return watermark, result
            finally:
                await asyncio.to_thread(handle.close)
        finally:
            lock.release()

    async def _barrier(self) -> int:
        """Bring the projection up to the committed head; return the watermark
        every read in this call must stay at or below."""
        self._ensure_open()
        head = await self._journal.head(self.corpus)
        if head == self._confirmed:
            return self._confirmed
        # head > confirmed: catch up. head < confirmed: the projection is past
        # the committed journal (e.g. it applied rows that were later rolled
        # back, or the journal was restored); _catch_up rebuilds it.
        try:
            await self._catch_up()
        except Exception as exc:
            await self._fail_closed()
            raise ProjectionRecoveryFailed(
                f"projection for corpus {self.corpus!r} could not reach journal "
                f"position {head}: {type(exc).__name__}: {exc}"
            ) from exc
        return self._confirmed

    async def _read_projection(self, read: Callable[[ProjectionHandle, int], T]) -> tuple[int, T]:
        self._ensure_open()
        try:
            watermark, result = await self._catch_up(read)
        except _ReadError as wrapped:
            raise wrapped.original from None
        except Exception as exc:
            await self._fail_closed()
            raise ProjectionRecoveryFailed(
                f"projection for corpus {self.corpus!r} could not catch up: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        return watermark, result  # type: ignore[return-value]

    async def _after_commit(self, op_id: str, position: int) -> None:
        try:
            await self._catch_up()
        except Exception as exc:
            await self._fail_closed()
            raise ProjectionRecoveryPending(
                f"operation {op_id!r} committed at journal position {position}, but "
                f"the projection could not catch up ({type(exc).__name__}: {exc}); "
                "reopen the corpus to recover, then retry the same operation ID",
                op_id=op_id,
                position=position,
            ) from exc

    # ── public read surface ───────────────────────────────────────────────

    async def status(self) -> StorageStatus:
        watermark = await self._barrier()
        return StorageStatus(
            corpus=self.corpus,
            journal_head=await self._journal.head(self.corpus),
            projection_watermark=watermark,
            projection_adapter_version=PROJECTION_ADAPTER_VERSION,
            full_shacl=FULL_SHACL_STATUS,
        )

    async def query(self, sparql: str) -> Any:
        """Read-only SPARQL over this corpus's named graphs at the committed
        watermark. SERVICE clauses are refused. Results are materialized."""
        _, result = await self._read_projection(lambda h, _wm: h.query(self.corpus, sparql))
        return result

    async def rebuild_projection(self) -> int:
        """Drop and replay this corpus's projection from the journal (U4 seam)."""
        self._ensure_open()
        try:
            watermark, _ = await self._catch_up(rebuild=True)
        except Exception as exc:
            await self._fail_closed()
            raise ProjectionRecoveryFailed(
                f"projection rebuild for corpus {self.corpus!r} failed: {exc}"
            ) from exc
        return watermark

    # ── governance writes ─────────────────────────────────────────────────

    async def _append_governance(
        self, event: GovernanceEvent, *, op_id: str | None
    ) -> GovernanceEvent:
        self._ensure_open()
        self._check_corpus(event.corpus)
        request_sha = _canonical_sha(event.model_dump(mode="json"))
        op = op_id or f"governance:{request_sha}"

        verifier = self.config.event_verifier
        if verifier is not None and not await verifier(event):
            raise InvalidSignature(
                f"governance {event.action} event signature did not verify for "
                f"signer {event.signature.did!r}; nothing was appended"
            )

        async with self._write_lock:
            self._ensure_open()
            async with self._journal.write(self.corpus) as tx:
                existing = await tx.find_op(op)
                if existing is not None:
                    row = check_replay(existing, request_sha)
                else:
                    history = [_event_from_row(r) for r in await tx.governance_rows()]
                    _refuse_replayed_event(event, history)
                    snapshot = InMemoryGovernanceLog._from_history(self.corpus, history)
                    persisted = await snapshot.append(event)
                    row = await tx.append(
                        PendingRow(
                            op_id=op,
                            request_sha256=request_sha,
                            kind=KIND_GOVERNANCE,
                            subject=persisted.action,
                            record_schema_version=GOVERNANCE_RECORD_SCHEMA_VERSION,
                            payload=persisted.model_dump_json().encode("utf-8"),
                            governance_position=persisted.position,
                        )
                    )
        await self._after_commit(op, row.position)
        return _event_from_row(row)

    # ── shard writes ──────────────────────────────────────────────────────

    def _load_gated(self, raw: bytes | str | Mapping[str, Any]) -> LoadedShardRecord:
        """PII gate over the parsed raw input BEFORE model validation, then the
        U17 adapter. A validation failure is re-raised as ``ShardRecordInvalid``
        without input values, so refused text never reaches an error message."""
        parsed = _parse_raw_json(raw)
        if parsed is not None:
            self.config.pii_gate.check(parsed)
        try:
            return load_shard_record(raw)
        except ValidationError as exc:
            raise _sanitized_validation_error(exc) from None

    def _gate(self, loaded: LoadedShardRecord, payload: bytes) -> None:
        """PII gate over the raw input AND the migrated payload, then the
        Phase 11 hook. Runs before any journal transaction starts."""
        self.config.pii_gate.check(json.loads(loaded.original_bytes))
        if payload != loaded.original_bytes:
            self.config.pii_gate.check(json.loads(payload))
        if self.config.shard_validator is not None:
            self.config.shard_validator(loaded.shard)

    async def _check_revision(
        self, tx: JournalTransaction, shard: ShardEnvelope
    ) -> int:
        """Identity is frozen and append-only lists never shrink across
        revisions. Returns the prior revision's position (``-1`` if new)."""
        prior_row = await tx.latest_shard(shard.shard_iri)
        if prior_row is None:
            return -1
        prior = load_shard_record(prior_row.payload).shard
        before = json.loads(prior.model_dump_json(include=set(IDENTITY_FIELDS)))
        after = json.loads(shard.model_dump_json(include=set(IDENTITY_FIELDS)))
        if before != after:
            changed = sorted(k for k in IDENTITY_FIELDS if before.get(k) != after.get(k))
            raise ShardIdentityViolation(
                f"revision of {shard.shard_iri!r} would change frozen identity "
                f"fields {changed}"
            )
        for name in ("signatures", "content_edits"):
            if len(getattr(shard, name)) < len(getattr(prior, name)):
                raise ShardIdentityViolation(
                    f"revision of {shard.shard_iri!r} would shrink append-only {name!r}"
                )
        return prior_row.position

    def _pending_shard(
        self, loaded: LoadedShardRecord, payload: bytes, *, op_id: str, request_sha: str
    ) -> PendingRow:
        return PendingRow(
            op_id=op_id,
            request_sha256=request_sha,
            kind=KIND_SHARD,
            subject=loaded.shard.shard_iri,
            record_schema_version=loaded.shard.schema_version,
            payload=payload,
            source_schema_version=loaded.source_schema_version,
            original_bytes=loaded.original_bytes,
        )

    async def _put_shard(
        self, shard_iri: str, shard: ShardEnvelope, *, op_id: str | None
    ) -> ShardEnvelope:
        self._ensure_open()
        if shard.shard_iri != shard_iri:
            raise ShardIdentityViolation(
                f"put key {shard_iri!r} does not match shard_iri {shard.shard_iri!r}"
            )
        payload = dump_shard_record(shard)
        loaded = self._load_gated(payload)  # full model validation on write
        self._gate(loaded, payload)
        payload_sha = sha256_hex(payload)
        request_sha = sha256_hex(f"{shard_iri}\n{payload_sha}".encode("utf-8"))

        async with self._write_lock:
            self._ensure_open()
            async with self._journal.write(self.corpus) as tx:
                # An explicit op_id is looked up first, so retrying it after a
                # later revision returns the committed result instead of
                # tripping the revision check against the newer row.
                existing = await tx.find_op(op_id) if op_id is not None else None
                if existing is not None:
                    op = op_id
                    row = check_replay(existing, request_sha)
                else:
                    prior_position = await self._check_revision(tx, loaded.shard)
                    op = op_id or (
                        f"shard:{sha256_hex(shard_iri.encode('utf-8'))}:"
                        f"{prior_position}:{payload_sha}"
                    )
                    existing = None if op_id is not None else await tx.find_op(op)
                    if existing is not None:
                        row = check_replay(existing, request_sha)
                    else:
                        row = await tx.append(
                            self._pending_shard(
                                loaded, payload, op_id=op, request_sha=request_sha
                            )
                        )
        await self._after_commit(op, row.position)
        return load_shard_record(row.payload).shard

    async def ingest_shards(
        self,
        records: Iterable[bytes | str | Mapping[str, Any] | ShardEnvelope],
        *,
        op_id: str | None = None,
    ) -> list[ShardEnvelope]:
        """Bulk ingest: every record goes through the U17 adapter (legacy
        versions migrate forward), the PII gate and validation BEFORE anything
        is appended; then all rows commit in one transaction. One refusal
        leaves the journal and the projection unchanged. Re-ingesting the same
        batch (or retrying ``op_id``) returns the committed shards."""
        self._ensure_open()
        prepared: list[tuple[LoadedShardRecord, bytes]] = []
        for record in records:
            raw = dump_shard_record(record) if isinstance(record, ShardEnvelope) else record
            loaded = self._load_gated(raw)
            payload = dump_shard_record(loaded.shard)
            self._gate(loaded, payload)
            prepared.append((loaded, payload))
        if not prepared:
            return []
        request_sha = sha256_hex(
            "\n".join(
                f"{ld.shard.shard_iri}:{sha256_hex(ld.original_bytes)}:{sha256_hex(p)}"
                for ld, p in prepared
            ).encode("utf-8")
        )
        op = op_id or f"ingest:{request_sha}"

        async with self._write_lock:
            self._ensure_open()
            async with self._journal.write(self.corpus) as tx:
                first = await tx.find_op(f"{op}#0")
                if first is not None:
                    # Exact-ID lookups: rows <op>#0 .. <op>#N-1 of THIS batch
                    # only (a prefix match would also return other operations
                    # such as "<op>#0#..." or a different-case op_id).
                    rows = []
                    for index in range(len(prepared)):
                        committed = await tx.find_op(f"{op}#{index}")
                        if committed is None:
                            raise OperationIdConflict(
                                f"operation ID {op!r} was already committed with "
                                f"{index} row(s), not {len(prepared)}"
                            )
                        rows.append(check_replay(committed, request_sha))
                else:
                    rows = []
                    for index, (loaded, payload) in enumerate(prepared):
                        await self._check_revision(tx, loaded.shard)
                        rows.append(
                            await tx.append(
                                self._pending_shard(
                                    loaded,
                                    payload,
                                    op_id=f"{op}#{index}",
                                    request_sha=request_sha,
                                )
                            )
                        )
        await self._after_commit(op, rows[-1].position)
        return [load_shard_record(r.payload).shard for r in rows]

    # ── internal reads used by the adapters ───────────────────────────────

    async def _shard_record(self, shard_iri: str, upto: int) -> StoredShardRecord | None:
        row = await self._journal.latest_shard(self.corpus, shard_iri, upto=upto)
        if row is None:
            return None
        return _stored(row)

    async def _current_shard_rows(self, upto: int) -> list[JournalRow]:
        return await self._journal.latest_shards(self.corpus, upto=upto)


def _stored(row: JournalRow) -> StoredShardRecord:
    return StoredShardRecord(
        shard=load_shard_record(row.payload).shard,
        position=row.position,
        original_bytes=row.original_bytes if row.original_bytes is not None else row.payload,
        source_schema_version=(
            row.source_schema_version
            if row.source_schema_version is not None
            else row.record_schema_version
        ),
        payload=row.payload,
    )


class _ReadError(Exception):
    def __init__(self, original: BaseException) -> None:
        super().__init__(str(original))
        self.original = original


async def open_corpus_storage(
    root: str | Path, corpus: str, *, config: StorageConfig | None = None
) -> CorpusStorageContext:
    """Convenience alias for ``CorpusStorageContext.open``."""
    return await CorpusStorageContext.open(root, corpus, config=config)


__all__ = [
    "FULL_SHACL_STATUS",
    "CorpusStorageContext",
    "StorageConfig",
    "StorageStatus",
    "StoredShardRecord",
    "open_corpus_storage",
    "verify_event_signature_offline",
]
