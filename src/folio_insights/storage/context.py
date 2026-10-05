"""Corpus storage context: one journal, one projection, one corpus (Phase 13 U2).

``CorpusStorageContext.open(root, corpus)`` is the single constructor callers
use (U3 wires every CLI command through it). It owns:

* the SQLite journal (``<root>/journal.sqlite3``) — the authoritative commit
  record for shard revisions and governance events (KTD2);
* the Oxigraph projection (``<root>/projection.oxigraph``) — a replayable
  named-graph view with a durable per-corpus applied-position watermark;
* ``shards`` (``PersistentShardStore``) and ``governance``
  (``PersistentGovernanceLog``), the persistent implementations of the
  existing ``ShardStore`` and five-method ``GovernanceLog`` seams;
* ``proposals`` (``PersistentProposalLedger``), the append-only
  proposed-class governance ledger (not projected to RDF).

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

Seams for the CLI (U3, wired) and later units:

* U3 — every governance / corpus CLI command opens one context per
  invocation (``governance.cli._state.corpus_storage``). ``journal_head``
  is the state position a saved retraction preview records;
  ``PersistentGovernanceLog.append(..., op_id=, expected_head=)`` commits it
  only if the journal has not moved (checked inside the write transaction);
  ``committed_governance_op`` returns an already-committed operation so a
  retried ``--apply`` commits at most once. ``cached_event_verifier`` lets a
  caller verify did:web / did:plc signers from a pre-populated cache.
* U4 — exports, bulk load, dumps and restore: ``ctx.query`` (corpus-scoped,
  read-only SPARQL), ``PersistentShardStore.get_record`` (original bytes and
  source version), ``journal_path`` / ``projection_path`` for snapshots, and
  ``rebuild_projection`` after a restore.
* Phase 11 — full SHACL (``StorageConfig.shacl``, the compiled default suite
  unless set to ``None``). The local tier runs on every shard write (put,
  ingest, bulk load; inside the pool workers for large batches) after the
  PII gate and model validation, and on every governance event inside the
  write transaction; a Violation refuses with ``ShaclViolation`` and leaves
  storage unchanged. After each commit the corpus tier (``sh:sparql``
  supersession rules) re-checks the written shards and their one-hop
  neighbours on the projection and advances the per-corpus status marker
  (``shacl_status``). ``status().full_shacl`` is ``disabled``,
  ``unvalidated``, ``pass`` or ``fail`` and never claims ``pass`` for state
  the current suite did not validate; ``validate_corpus()`` validates
  everything and records the result. ``StorageConfig.shard_validator`` /
  ``event_validator`` remain generic extra hooks that run after the suite.
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
from typing import TYPE_CHECKING, Any, TypeVar

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
from folio_insights.shapes.corpus import run_constraints
from folio_insights.shapes.suite import ShaclSuite, default_suite
from folio_insights.shards.records import IDENTITY_FIELDS
from folio_insights.storage.errors import (
    CorpusIsolationError,
    GovernanceEventReplayed,
    JournalStateChanged,
    OperationIdConflict,
    ProjectionRecoveryFailed,
    ProjectionRecoveryPending,
    ShardIdentityViolation,
    ShardRecordInvalid,
    StorageClosed,
)
from folio_insights.storage._parallel import (
    PARALLEL_MIN_ITEMS,
    PreparedRecord,
    map_chunks,
    prepare_chunk,
    prepare_one,
    validate_chunk,
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
from folio_insights.storage.shacl_status import (
    DISABLED,
    FAIL,
    FULL_SHACL_STATES,
    PASS,
    UNVALIDATED,
    CorpusValidation,
    MarkerStore,
    ShaclMarker,
    ShaclStatus,
    cap_failing,
    check_event,
    check_shard_payload,
    result_entry,
)
from folio_insights.storage.projection import (
    BULK_LOAD_MIN_ROWS,
    PROJECTION_ADAPTER_VERSION,
    PROJECTION_DIRNAME,
    ProjectionHandle,
    ProjectionLock,
    load_row_shard,
)

if TYPE_CHECKING:
    from folio_insights.identity.cache import DidDocCache

T = TypeVar("T")

# Above this many written shards the post-commit corpus tier runs over the
# whole corpus instead of a VALUES-restricted focus set (cheaper and complete).
INCREMENTAL_FOCUS_LIMIT = 256

_EVENT_ADAPTER: TypeAdapter = TypeAdapter(GovernanceEvent)

EventVerifier = Callable[[GovernanceEvent], Awaitable[bool]]


def cached_event_verifier(cache: DidDocCache) -> EventVerifier:
    """An ``EventVerifier`` that resolves signer keys from ``cache`` only.

    did:key signers verify offline. A did:web or did:plc signer verifies only
    when ``cache`` already holds its DID-document snapshot (pre-populated by
    the caller, e.g. the CLI); any resolver that would need the network is
    refused, so an uncached rotatable DID fails closed.
    """
    from folio_insights.identity.verifier import verify_attestation

    async def _no_network(*_args: Any) -> dict:
        raise ConnectionRefusedError("storage signature verification is offline")

    async def _verify(event: GovernanceEvent) -> bool:
        if not event.signature.signature:
            return False
        payload = event.signature_payload().decode("utf-8")
        return await verify_attestation(
            payload,
            event.signature,
            cache=cache,
            http=_no_network,
            plc_resolver=_no_network,
        )

    return _verify


async def verify_event_signature_offline(event: GovernanceEvent) -> bool:
    """Phase 6 ``verify_attestation`` over the event payload, with no network
    and an empty DID-document cache: did:key signers verify; did:web and
    did:plc signers fail closed unless a caller supplies
    ``cached_event_verifier`` with a pre-populated cache."""
    from folio_insights.identity.cache import InMemoryDidDocCache

    return await cached_event_verifier(InMemoryDidDocCache())(event)


@dataclass(frozen=True)
class StorageConfig:
    """Per-context storage policy.

    * ``pii_gate`` — the configurable ingest gate (defaults: SSN, ABA, phone).
    * ``event_verifier`` — signature check run on every governance append
      before the journal transaction; ``None`` disables it (test doubles only).
    * ``shacl`` — the Phase 11 SHACL suite (default: the compiled
      ``shapes.default_suite()``; ``None`` disables it and ``full_shacl``
      reads ``disabled``). Its local tier refuses Violations on every shard
      write and governance append; its corpus tier sets ``full_shacl``.
    * ``shard_validator`` — an extra generic hook for shards, called on
      every shard write (put, ingest, bulk load) after the PII gate, model
      validation and the SHACL suite, before the journal transaction.
      Raise to refuse.
    * ``event_validator`` — the same hook for governance events, called after
      signature verification and before the journal transaction (whose
      in-transaction authorization and SHACL check still run afterwards).

    Neither hook replaces a built-in check, and installing one does not
    change ``full_shacl``, which only the SHACL suite's results set.
    """

    pii_gate: PiiGate = field(default_factory=PiiGate)
    event_verifier: EventVerifier | None = verify_event_signature_offline
    shacl: ShaclSuite | None = field(default_factory=default_suite)
    shard_validator: Callable[[ShardEnvelope], None] | None = None
    event_validator: Callable[[GovernanceEvent], None] | None = None
    busy_timeout_s: float = 30.0
    projection_lock_timeout_s: float = 120.0
    replay_batch_size: int = 256
    bulk_replay_batch_size: int = 16384
    # Opt in to the forkserver process pool for every large batch this
    # context handles (the storage CLI does; library callers get it only from
    # ``bulk_load_shards``). See ``bulk_load_shards`` for the __main__ caveat.
    process_pool: bool = False


@dataclass(frozen=True)
class StorageStatus:
    corpus: str
    journal_head: int
    projection_watermark: int
    projection_adapter_version: int
    full_shacl: str
    validation_hooks: tuple[str, ...] = ()
    # Phase 11: what the full_shacl value rests on.
    shacl_suite_digest: str | None = None
    shacl_validated_through: int | None = None
    shacl_violations: int = 0
    shacl_warnings: int | None = None


@dataclass(frozen=True)
class BulkLoadResult:
    """What ``bulk_load_shards`` committed (or found already committed)."""

    op_id: str | None
    records: int
    first_position: int
    last_position: int


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


async def _authorize_in_transaction(
    event: GovernanceEvent, snapshot: InMemoryGovernanceLog, corpus: str
) -> None:
    """Re-run the central ``authorize()`` decision against the committed
    history read inside the write transaction (KTD3).

    A CLI command authorizes before it builds and signs; a revocation
    committed in between would otherwise still let the revoked signer
    append. Every event goes through the same policy the CLI uses: the
    first event of a corpus as the genesis carve-out (``corpus_init``), any
    other as its own action, with roles resolved at commit time.
    """
    from folio_insights.governance.authorize import GENESIS_ACTION, Allow, authorize
    from folio_insights.governance.log import NotAuthorized

    signer = event.signature.did
    if await snapshot.latest_position(corpus) < 0:
        decision = await authorize(
            signer,
            GENESIS_ACTION,
            corpus,
            log=snapshot,
            admin_did=getattr(event, "subject_did", None),
        )
    else:
        decision = await authorize(signer, event.action, corpus, log=snapshot)
    if not isinstance(decision, Allow):
        raise NotAuthorized(
            f"governance {event.action} event refused: signer {signer!r} is not "
            f"authorized in corpus {corpus!r} at commit time "
            f"({getattr(decision, 'reason', decision)}); nothing was appended"
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
        # Envelopes this process validated for its own commits, keyed by
        # (position, payload sha256): the projection reuses them instead of
        # re-validating the same bytes. Only current-version records whose
        # payload IS the validated input are cached; cleared every catch-up.
        self._shard_cache: dict[tuple[int, str], ShardEnvelope] = {}
        # (watermark, chain digest) last verified against or written from this
        # context's journal (see ``_chain_matches``).
        self._verified_chain: tuple[int, str] | None = None
        self._closed = True
        self._write_lock = asyncio.Lock()
        from folio_insights.storage.governance import PersistentGovernanceLog
        from folio_insights.storage.proposals import PersistentProposalLedger
        from folio_insights.storage.shards import PersistentShardStore

        self.shards = PersistentShardStore(self)
        self.governance = PersistentGovernanceLog(self)
        self.proposals = PersistentProposalLedger(self)

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
        parallel: bool = False,
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
                await asyncio.to_thread(handle.ensure_tbox)
                state = await asyncio.to_thread(handle.state, self.corpus)
                head = await self._journal.head(self.corpus)
                stale_adapter = state.adapter_version not in (None, PROJECTION_ADAPTER_VERSION)
                if (
                    rebuild
                    or stale_adapter
                    or state.watermark > head
                    or not await self._chain_matches(state)
                ):
                    # KTD5: derived RDF is rebuilt from the journal, never trusted
                    # past it (a projection newer than a restored journal) or
                    # beside it (a journal whose applied prefix differs in any
                    # row: the chain digest covers every row up to the watermark).
                    await asyncio.to_thread(handle.reset, self.corpus)
                    watermark = -1
                else:
                    watermark = state.watermark
                cache = self._shard_cache

                def _load(row: JournalRow) -> ShardEnvelope:
                    cached = cache.pop((row.position, row.payload_sha256), None)
                    return cached if cached is not None else load_row_shard(row)

                while watermark < head:
                    limit = (
                        self.config.bulk_replay_batch_size
                        if head - watermark >= BULK_LOAD_MIN_ROWS
                        else self.config.replay_batch_size
                    )
                    rows = await self._journal.rows_after(
                        self.corpus, watermark, limit=limit, with_original=False
                    )
                    if not rows:
                        break
                    watermark = await asyncio.to_thread(
                        handle.apply,
                        self.corpus,
                        rows,
                        load=_load,
                        parallel=parallel or self.config.process_pool,
                    )
                    self._confirmed = watermark
                self._confirmed = watermark
                cache.clear()
                applied = await asyncio.to_thread(handle.state, self.corpus)
                # Written by apply from this journal's own rows: trusted.
                self._verified_chain = (
                    (applied.watermark, applied.chain_digest)
                    if applied.chain_digest is not None
                    else None
                )
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

    async def _chain_matches(self, state: Any) -> bool:
        """The projection was built from exactly this journal's rows.

        Recomputes the chain digest over (position, op_id, payload_sha256,
        committed_at) of every row up to the watermark and compares it with
        the projection's. Incremental from the last digest this context
        verified or wrote, so steady-state reads cost nothing extra. A
        projection without a chain digest (pre-U4 fix) never matches and is
        rebuilt once. Also re-checks the watermark row's payload digest.
        """
        from folio_insights.storage.projection import CHAIN_GENESIS, chain_over

        watermark = state.watermark
        if watermark < 0:
            return True
        if state.chain_digest is None or state.payload_sha256 is None:
            return False
        cached = self._verified_chain
        if cached is not None and cached[0] == watermark:
            return cached[1] == state.chain_digest
        start, digest = (
            cached if cached is not None and cached[0] < watermark else (-1, CHAIN_GENESIS)
        )
        rows = await self._journal.chain_rows(self.corpus, after=start, upto=watermark)
        if len(rows) != watermark - start or rows[-1].payload_sha256 != state.payload_sha256:
            return False
        digest = chain_over(digest, rows)
        if digest != state.chain_digest:
            return False
        self._verified_chain = (watermark, digest)
        return True

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

    async def _after_commit(self, op_id: str, position: int, *, parallel: bool = False) -> None:
        try:
            await self._catch_up(parallel=parallel)
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
        head = await self._journal.head(self.corpus)
        shacl = await self._shacl_status(head)
        return StorageStatus(
            corpus=self.corpus,
            journal_head=head,
            projection_watermark=watermark,
            projection_adapter_version=PROJECTION_ADAPTER_VERSION,
            full_shacl=shacl.state,
            shacl_suite_digest=shacl.suite_digest,
            shacl_validated_through=shacl.validated_through,
            shacl_violations=shacl.violations,
            shacl_warnings=shacl.warnings,
            validation_hooks=tuple(
                name
                for name, hook in (
                    ("shard_validator", self.config.shard_validator),
                    ("event_validator", self.config.event_validator),
                )
                if hook is not None
            ),
        )

    async def journal_head(self) -> int:
        """The corpus journal head after the barrier: the committed state
        position a saved preview records and a guarded write compares."""
        return await self._barrier()

    async def committed_governance_op(self, op_id: str) -> GovernanceEvent | None:
        """The governance event committed under ``op_id``, or ``None``.

        Lets a caller that retries a saved operation (``retract --apply``)
        return the committed result instead of signing a second event.
        """
        upto = await self._barrier()
        row = await self._journal.find_op(self.corpus, op_id)
        if row is None or row.position > upto:
            return None
        if row.kind != KIND_GOVERNANCE:
            raise OperationIdConflict(
                f"operation ID {op_id!r} was committed as a {row.kind} write, "
                "not a governance event"
            )
        return _event_from_row(row)

    async def query(self, sparql: str, *, include_tbox: bool = False) -> Any:
        """Read-only SPARQL over this corpus's named graphs at the committed
        watermark. SERVICE clauses are refused. Results are materialized.

        ``include_tbox`` adds the shared TBox graph (default graph and named
        graphs), so ``GRAPH ?g`` returns the ABox, governance and TBox
        partitions of this corpus and nothing of any other corpus."""
        _, result = await self._read_projection(
            lambda h, _wm: h.query(self.corpus, sparql, include_tbox=include_tbox)
        )
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
        self,
        event: GovernanceEvent,
        *,
        op_id: str | None,
        expected_head: int | None = None,
    ) -> GovernanceEvent:
        self._ensure_open()
        self._check_corpus(event.corpus)
        # Work on a private copy: neither the caller, the verifier nor a hook
        # can change the event between verification and persistence.
        event = event.model_copy(deep=True)
        dumped = event.model_dump(mode="json")
        request_sha = _canonical_sha(dumped)
        op = op_id or f"governance:{request_sha}"
        # PII gate first, like shards and proposal-ledger operations: a refused
        # event never reaches the journal, the projection or any dump. It scans
        # the operation ID and every leaf of the event, signature objects
        # included (only exactly-shaped signatures and digests are exempt).
        self.config.pii_gate.check({"op_id": op, "event": dumped})

        verifier = self.config.event_verifier
        if verifier is not None and not await verifier(event.model_copy(deep=True)):
            raise InvalidSignature(
                f"governance {event.action} event signature did not verify for "
                f"signer {event.signature.did!r}; nothing was appended"
            )
        if self.config.event_validator is not None:
            # Phase 11 hook: after the built-ins, on a copy (it can refuse,
            # never rewrite what is persisted).
            self.config.event_validator(event.model_copy(deep=True))

        async with self._write_lock:
            self._ensure_open()
            async with self._journal.write(self.corpus) as tx:
                existing = await tx.find_op(op)
                appended = False
                if existing is not None:
                    row = check_replay(existing, request_sha)
                else:
                    if expected_head is not None:
                        # Saved-preview freshness (KTD3, R4): compared inside
                        # the serialized transaction, so no writer can land
                        # between this check and the append.
                        actual = await tx.head()
                        if actual != expected_head:
                            raise JournalStateChanged(
                                expected=expected_head, actual=actual
                            )
                    history = [_event_from_row(r) for r in await tx.governance_rows()]
                    _refuse_replayed_event(event, history)
                    snapshot = InMemoryGovernanceLog._from_history(self.corpus, history)
                    await _authorize_in_transaction(event, snapshot, self.corpus)
                    persisted = await snapshot.append(event)
                    if self.config.shacl is not None:
                        # Phase 11: the event as the projection will store
                        # it, with its log position now assigned.
                        check_event(
                            self.corpus, persisted.model_dump(mode="json"), self.config.shacl
                        )
                    appended = True
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
        if appended:
            await self._shacl_after_write(row.position, row.position, [])
        return _event_from_row(row)

    # ── shard writes ──────────────────────────────────────────────────────

    def _prepare(self, raw: bytes | str | Mapping[str, Any]) -> tuple[LoadedShardRecord, bytes]:
        """Every check a shard write passes before any journal transaction:

        1. the PII gate over the parsed raw input, BEFORE model validation;
        2. the U17 adapter (full model validation; a failure is re-raised as
           ``ShardRecordInvalid`` without input values);
        3. the PII gate over the stored original bytes when they are not the
           text already scanned, and over the migrated payload when it
           differs from the original;
        4. the Phase 11 SHACL suite's local tier over the current-version
           payload (a Violation raises ``ShaclViolation``);
        5. the generic hook (``shard_validator``), which runs only AFTER the
           built-in checks above and can add refusals, never remove them.

        Returns the loaded record and the current-version payload.
        """
        loaded, prepared = prepare_one(raw, self.config.pii_gate)
        self._check_shacl(prepared.payload)
        self._run_shard_hook(loaded.shard)
        return loaded, prepared.payload

    def _check_shacl(self, payload: bytes) -> None:
        if self.config.shacl is not None:
            check_shard_payload(payload, self.config.shacl)

    def _shacl_paths(self) -> tuple[str, ...] | None:
        suite = self.config.shacl
        return tuple(str(p) for p in suite.paths) if suite is not None else None

    def _run_shard_hook(self, shard: ShardEnvelope) -> None:
        """The Phase 11 shard hook, on a deep copy: it can refuse, but cannot
        change what the identity / append-only checks, the journal or the
        projection cache see."""
        if self.config.shard_validator is not None:
            self.config.shard_validator(shard.model_copy(deep=True))

    def _prepare_many(
        self, raws: list[bytes | str | Mapping[str, Any]], *, parallel: bool = False
    ) -> list[tuple[PreparedRecord, ShardEnvelope | None]]:
        """``_prepare`` for a batch, in input order.

        The refusal raised is the one with the earliest input index, whether
        it comes from a built-in check or from the Phase 11 hook, so the
        outcome never depends on batch size or on the process pool. With
        ``parallel`` (explicit opt-in: ``bulk_load_shards`` and the storage
        CLI) a large batch runs the built-in checks in the process pool and
        returns bytes only; the hook always runs here, per chunk, in order.
        """
        out: list[tuple[PreparedRecord, ShardEnvelope | None]] = []
        if parallel and len(raws) >= PARALLEL_MIN_ITEMS:
            for records, failure in map_chunks(
                prepare_chunk, raws, self.config.pii_gate, self._shacl_paths()
            ):
                # Hook the records of this chunk that precede its first
                # built-in refusal: an earlier hook refusal wins.
                hooked = self.config.shard_validator is not None
                for record in records:
                    if hooked:
                        self._run_shard_hook(load_shard_record(record.payload).shard)
                    out.append((record, None))
                if failure is not None:
                    raise failure[1]
            return out
        for raw in raws:
            loaded, prepared = prepare_one(raw, self.config.pii_gate)
            self._check_shacl(prepared.payload)
            self._run_shard_hook(loaded.shard)
            # Cache only when the committed payload IS the validated input.
            out.append((prepared, loaded.shard if prepared.original_bytes is None else None))
        return out

    def _remember(self, shard: ShardEnvelope | None, row: JournalRow) -> None:
        """Cache a validated envelope for the projection (see ``_shard_cache``)."""
        if shard is not None:
            self._shard_cache[(row.position, row.payload_sha256)] = shard

    async def _check_revision(
        self, tx: JournalTransaction, shard: ShardEnvelope
    ) -> int:
        """Identity is frozen and append-only lists never shrink across
        revisions. Returns the prior revision's position (``-1`` if new)."""
        prior_row = await tx.latest_shard(shard.shard_iri)
        if prior_row is None:
            return -1
        _check_identity(load_shard_record(prior_row.payload).shard, shard)
        return prior_row.position

    def _pending_shard(
        self, record: PreparedRecord, *, op_id: str, request_sha: str
    ) -> PendingRow:
        return PendingRow(
            op_id=op_id,
            request_sha256=request_sha,
            kind=KIND_SHARD,
            subject=record.shard_iri,
            record_schema_version=record.record_schema_version,
            payload=record.payload,
            source_schema_version=record.source_schema_version,
            # NULL means "the original bytes ARE the payload" (a current-version
            # record): lossless, and it halves the journal for bulk loads.
            original_bytes=record.original_bytes,
        )

    async def _put_shard(
        self, shard_iri: str, shard: ShardEnvelope, *, op_id: str | None
    ) -> ShardEnvelope:
        self._ensure_open()
        if shard.shard_iri != shard_iri:
            raise ShardIdentityViolation(
                f"put key {shard_iri!r} does not match shard_iri {shard.shard_iri!r}"
            )
        loaded, payload = self._prepare(dump_shard_record(shard))  # full validation
        payload_sha = sha256_hex(payload)
        request_sha = sha256_hex(f"{shard_iri}\n{payload_sha}".encode("utf-8"))

        async with self._write_lock:
            self._ensure_open()
            async with self._journal.write(self.corpus) as tx:
                # An explicit op_id is looked up first, so retrying it after a
                # later revision returns the committed result instead of
                # tripping the revision check against the newer row.
                existing = await tx.find_op(op_id) if op_id is not None else None
                appended = False
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
                                _prepared_record(loaded, payload),
                                op_id=op,
                                request_sha=request_sha,
                            )
                        )
                        appended = True
                        if payload == loaded.original_bytes:
                            self._remember(loaded.shard, row)
        await self._after_commit(op, row.position)
        if appended:
            await self._shacl_after_write(row.position, row.position, [shard_iri])
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
        rows = await self._ingest(records, op_id=op_id)
        return [load_shard_record(r.payload).shard for r in rows]

    async def bulk_load_shards(
        self,
        records: Iterable[bytes | str | Mapping[str, Any] | ShardEnvelope],
        *,
        op_id: str | None = None,
        parallel: bool = True,
    ) -> BulkLoadResult:
        """``ingest_shards`` for large loads: the same checks, the same single
        journal transaction and the same projection catch-up (which bulk-loads
        add-only batches), without re-validating every committed record into
        a returned list. Returns positions and counts instead.

        ``parallel`` (default on) runs the per-record checks and the
        projection rendering in a ``forkserver`` process pool for batches of
        2,048 or more. Worker start-up re-imports the caller's ``__main__``,
        so a script calling this must guard its entry point with
        ``if __name__ == "__main__":`` (or pass ``parallel=False``).
        ``ingest_shards`` never uses the pool."""
        rows = await self._ingest(records, op_id=op_id, parallel=parallel)
        if not rows:
            return BulkLoadResult(op_id=op_id, records=0, first_position=-1, last_position=-1)
        return BulkLoadResult(
            op_id=rows[0].op_id.rsplit("#", 1)[0],
            records=len(rows),
            first_position=rows[0].position,
            last_position=rows[-1].position,
        )

    async def _ingest(
        self,
        records: Iterable[bytes | str | Mapping[str, Any] | ShardEnvelope],
        *,
        op_id: str | None,
        parallel: bool = False,
    ) -> list[JournalRow]:
        self._ensure_open()
        parallel = parallel or self.config.process_pool
        prepared = self._prepare_many(
            [dump_shard_record(r) if isinstance(r, ShardEnvelope) else r for r in records],
            parallel=parallel,
        )
        if not prepared:
            return []
        request_sha = sha256_hex(
            "\n".join(
                f"{rec.shard_iri}:{sha256_hex(rec.original)}:{sha256_hex(rec.payload)}"
                for rec, _ in prepared
            ).encode("utf-8")
        )
        op = op_id or f"ingest:{request_sha}"

        appended = False
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
                    # One query for every subject's committed revision, then the
                    # same frozen-identity check per record, in batch order (a
                    # record revising an earlier record of this batch is
                    # checked against that record).
                    latest = await tx.latest_shards_for([rec.shard_iri for rec, _ in prepared])
                    batch: dict[str, bytes] = {}
                    for rec, cached in prepared:
                        prior_payload = batch.get(rec.shard_iri)
                        if prior_payload is None and rec.shard_iri in latest:
                            prior_payload = latest[rec.shard_iri].payload
                        if prior_payload is not None:
                            _check_identity(
                                load_shard_record(prior_payload).shard,
                                cached or load_shard_record(rec.payload).shard,
                            )
                        batch[rec.shard_iri] = rec.payload
                    rows = await tx.append_many(
                        [
                            self._pending_shard(
                                rec, op_id=f"{op}#{index}", request_sha=request_sha
                            )
                            for index, (rec, _) in enumerate(prepared)
                        ]
                    )
                    for (_, cached), row in zip(prepared, rows):
                        self._remember(cached, row)
                    appended = True
        await self._after_commit(op, rows[-1].position, parallel=parallel)
        if appended:
            await self._shacl_after_write(
                rows[0].position, rows[-1].position, [rec.shard_iri for rec, _ in prepared]
            )
        return rows

    # ── Phase 11 SHACL: status, incremental corpus tier, full validation ──

    async def shacl_status(self) -> ShaclStatus:
        """The Phase 11 ``full_shacl`` state at the committed head."""
        return await self._shacl_status(await self._barrier())

    async def _shacl_status(self, head: int) -> ShaclStatus:
        suite = self.config.shacl
        if suite is None:
            return ShaclStatus(DISABLED)
        marker = await asyncio.to_thread(MarkerStore(self.root, self.corpus).read)
        if marker is None:
            if head < 0:  # an empty corpus trivially conforms
                return ShaclStatus(PASS, suite.digest, -1)
            return ShaclStatus(UNVALIDATED, suite.digest)
        if marker.suite_digest != suite.digest or marker.position != head:
            return ShaclStatus(
                UNVALIDATED, suite.digest, None, len(marker.failing), marker.warnings
            )
        if head >= 0:
            row = await self._journal.row_at(self.corpus, head)
            if row is None or row.payload_sha256 != marker.payload_sha256:
                return ShaclStatus(UNVALIDATED, suite.digest)
        state = FAIL if marker.failing or marker.failing_truncated else PASS
        return ShaclStatus(state, suite.digest, marker.position, len(marker.failing), marker.warnings)

    async def _corpus_tier(
        self, suite: ShaclSuite, focus: set[str] | None
    ) -> tuple[list[Any], set[str] | None]:
        """Run the suite's ``sh:sparql`` constraints over this corpus's
        projection. With ``focus`` (small), re-check those shards and their
        one-hop IRI neighbours and return the re-checked set; otherwise run
        over the whole corpus and return ``None`` (complete)."""
        constraints = suite.sparql
        corpus = self.corpus

        def read(handle: ProjectionHandle, _wm: int) -> tuple[list[Any], set[str] | None]:
            def query(sparql: str) -> list[dict[str, Any]]:
                return handle.query(corpus, sparql)

            if focus is None or len(focus) > INCREMENTAL_FOCUS_LIMIT:
                return run_constraints(query, constraints), None
            from pyoxigraph import NamedNode

            terms = []
            for iri in sorted(focus):
                try:
                    terms.append(str(NamedNode(iri)))
                except ValueError:
                    continue
            rechecked = {t[1:-1] for t in terms}
            if terms:
                rows = query(
                    "SELECT DISTINCT ?n WHERE { VALUES ?t { " + " ".join(terms) + " } "
                    "{ ?n ?p ?t } UNION { ?t ?p ?n } FILTER(isIRI(?n)) }"
                )
                rechecked.update(r["n"].value for r in rows)
            if not constraints:
                return [], rechecked
            return run_constraints(query, constraints, focus=sorted(rechecked)), rechecked

        _, out = await self._read_projection(read)
        return out

    async def _shacl_after_write(self, first: int, last: int, written: list[str]) -> None:
        """Advance the status marker over rows ``first..last`` when it is
        contiguous with them under the current suite; otherwise leave it
        behind (``full_shacl`` then reads ``unvalidated``)."""
        suite = self.config.shacl
        if suite is None:
            return
        store = MarkerStore(self.root, self.corpus)

        def contiguous(marker: ShaclMarker | None) -> bool:
            if marker is None:
                return first == 0
            return marker.suite_digest == suite.digest and marker.position == first - 1

        current = await asyncio.to_thread(store.read)
        if not contiguous(current):
            return
        prior = list(current.failing) if current is not None else []
        focus = set(written) | {
            str(e["focus"]) for e in prior if e.get("tier") == "corpus" and e.get("focus")
        }
        if focus:
            results, rechecked = await self._corpus_tier(suite, focus)
        else:  # e.g. a governance event with no failing shards to re-check
            results, rechecked = [], set()
        new_entries = [result_entry(r, "corpus") for r in results if r.severity == "Violation"]
        written_set = set(written)
        if rechecked is None:  # complete corpus-tier run
            kept = [e for e in prior if e.get("tier") != "corpus" and e.get("focus") not in written_set]
        else:
            kept = [
                e
                for e in prior
                if not (e.get("tier") == "corpus" and e.get("focus") in rechecked)
                and not (e.get("tier") == "local" and e.get("focus") in written_set)
            ]
        failing, truncated = cap_failing(kept + new_entries)
        truncated = truncated or bool(current is not None and current.failing_truncated and rechecked is not None)
        row = await self._journal.row_at(self.corpus, last)
        if row is None:  # pragma: no cover - the row was just committed
            return

        def apply(marker: ShaclMarker | None) -> ShaclMarker | None:
            if not contiguous(marker):  # another writer moved it meanwhile
                return None
            return ShaclMarker(
                corpus=self.corpus,
                suite_digest=suite.digest,
                position=last,
                payload_sha256=row.payload_sha256,
                failing=failing,
                failing_truncated=truncated,
                warnings=marker.warnings if marker is not None else None,
                updated_by="incremental",
            )

        await asyncio.to_thread(store.update, apply)

    async def validate_corpus(
        self, *, engine: str = "compiled", parallel: bool = False
    ) -> CorpusValidation:
        """Validate every current shard and governance event of this corpus
        against the full suite, run the corpus tier over the whole
        projection, and record the result in the status marker.

        ``engine="pyshacl"`` runs the local tier with the reference engine
        (slow; for cross-checks). The corpus tier always runs natively in
        pyoxigraph. ``parallel`` uses the process pool for large corpora.
        """
        if engine not in ("compiled", "pyshacl"):
            raise ValueError(f"unknown SHACL engine {engine!r}")
        suite = self.config.shacl or default_suite()
        upto = await self._barrier()
        shard_rows = await self._current_shard_rows(upto)
        event_rows = await self._journal.governance_rows(self.corpus, upto=upto)
        entries: list[dict[str, Any]] = []
        warnings = 0
        payloads = [row.payload for row in shard_rows]
        if engine == "compiled":
            for chunk_entries, chunk_warnings in map_chunks(
                validate_chunk,
                payloads,
                tuple(str(p) for p in suite.paths),
                parallel=parallel or self.config.process_pool,
            ):
                entries.extend(chunk_entries)
                warnings += chunk_warnings
        else:
            from folio_insights.shapes import pyshacl_adapter
            from folio_insights.shapes.rendering import render_shard

            for payload in payloads:
                graph, _node = render_shard(json.loads(payload))
                report = await asyncio.to_thread(pyshacl_adapter.validate, graph, suite.paths)
                for r in report.results:
                    severity = str(r["severity"]).rsplit("#", 1)[-1]
                    if severity == "Violation":
                        focus = r["focus"]
                        entries.append({
                            "focus": focus[1] if focus and focus[0] == "I" else str(focus),
                            "path": r["path"],
                            "component": str(r["component"]).rsplit("#", 1)[-1],
                            "severity": severity,
                            "source_shape": str(r["source_shape"]),
                            "message": (r["message"] or [""])[0],
                            "tier": "local",
                        })
                    else:
                        warnings += 1
        from folio_insights.storage.shacl_status import event_graph

        for row in event_rows:
            report = suite.validate_graph(event_graph(self.corpus, json.loads(row.payload)))
            entries.extend(result_entry(r, "local") for r in report.violations)
            warnings += len(report.warnings)
        corpus_results, _ = await self._corpus_tier(suite, None)
        entries.extend(result_entry(r, "corpus") for r in corpus_results if r.severity == "Violation")
        warnings += sum(1 for r in corpus_results if r.severity != "Violation")

        failing, truncated = cap_failing(entries)
        row = await self._journal.row_at(self.corpus, upto) if upto >= 0 else None

        def apply(marker: ShaclMarker | None) -> ShaclMarker | None:
            if (
                marker is not None
                and marker.suite_digest == suite.digest
                and marker.position > upto
            ):
                return None  # a newer write already advanced it; keep that
            return ShaclMarker(
                corpus=self.corpus,
                suite_digest=suite.digest,
                position=upto,
                payload_sha256=row.payload_sha256 if row is not None else None,
                failing=failing,
                failing_truncated=truncated,
                warnings=warnings,
                updated_by="full",
            )

        await asyncio.to_thread(MarkerStore(self.root, self.corpus).update, apply)
        return CorpusValidation(
            corpus=self.corpus,
            position=upto,
            suite_digest=suite.digest,
            engine=engine,
            shards=len(shard_rows),
            events=len(event_rows),
            conforms=not entries,
            violations=len(entries),
            warnings=warnings,
            results=tuple(failing),
        )

    # ── internal reads used by the adapters ───────────────────────────────

    async def _shard_record(self, shard_iri: str, upto: int) -> StoredShardRecord | None:
        row = await self._journal.latest_shard(self.corpus, shard_iri, upto=upto)
        if row is None:
            return None
        return _stored(row)

    async def _current_shard_rows(self, upto: int) -> list[JournalRow]:
        return await self._journal.latest_shards(self.corpus, upto=upto)


def _prepared_record(loaded: LoadedShardRecord, payload: bytes) -> PreparedRecord:
    return PreparedRecord(
        original_bytes=None if payload == loaded.original_bytes else loaded.original_bytes,
        payload=payload,
        source_schema_version=loaded.source_schema_version,
        record_schema_version=loaded.shard.schema_version,
        shard_iri=loaded.shard.shard_iri,
    )


def _check_identity(prior: ShardEnvelope, shard: ShardEnvelope) -> None:
    """Identity is frozen and append-only lists never shrink across revisions."""
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
    "FULL_SHACL_STATES",
    "INCREMENTAL_FOCUS_LIMIT",
    "BulkLoadResult",
    "CorpusStorageContext",
    "StorageConfig",
    "StorageStatus",
    "StoredShardRecord",
    "cached_event_verifier",
    "open_corpus_storage",
    "verify_event_signature_offline",
]
