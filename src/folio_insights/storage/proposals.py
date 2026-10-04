"""Persistent proposed-class ledger over the corpus journal file.

The storage seam for the proposed-class governance pipeline (governance plan
KTD3). It is deliberately small and knows nothing about proposals. It appends
and reads JSON operations for one corpus, and ``folio_insights.proposals``
folds them into registry state.

Same write discipline as shards and governance events:

* **Explicit operation IDs.** ``append`` requires ``op_id``. Retrying the
  same operation ID with the same request returns the committed row.
  Reusing it for a different request raises ``OperationIdConflict``.
* **PII gate first.** The configured PII gate scans the operation ID, the
  kind and every string and integer leaf of the payload before the write
  transaction, so a refused operation never reaches the journal file.
* **No source text.** A payload that carries a key named in
  ``FORBIDDEN_PAYLOAD_KEYS`` (``excerpt``, ``source_text`` and their
  variants) anywhere is refused: the ledger holds references, never text.
* **Guarded appends.** ``expected_head`` makes an append conditional on the
  ledger head the caller computed against. The comparison runs inside the
  ``BEGIN IMMEDIATE`` transaction, so it is atomic with every other writer.
  On a mismatch, ``JournalStateChanged`` is raised and nothing is appended.
* **Append-only.** The table's triggers refuse UPDATE, DELETE, replace and
  non-contiguous positions.

Ledger rows are not replayed into the RDF projection. They never move the
projection watermark. Snapshots copy them because they copy the whole journal
file. Dumps and exports do not include them yet.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import jcs

from folio_insights.storage.errors import JournalStateChanged
from folio_insights.storage.journal import ProposalLedgerRow, check_replay

if TYPE_CHECKING:
    from folio_insights.storage.context import CorpusStorageContext

_KIND = re.compile(r"[a-z][a-z0-9_]{0,63}")
MAX_OP_ID_CHARS = 200
FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "excerpt", "source_text", "source_text_excerpt", "supporting_excerpt", "text",
})


class ProposalPayloadRefused(ValueError):
    """A ledger payload carried a forbidden (text-bearing) key. The message
    names the location, never a value."""


_SAFE_KEY = re.compile(r"[a-z_][a-z0-9_]{0,63}")


def _refuse_text_keys(value: Any, path: str) -> None:
    """Refuse a forbidden key anywhere in ``value``. Paths name only plain
    snake_case keys and list indexes; any other key is shown as ``<key>``."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in FORBIDDEN_PAYLOAD_KEYS:
                raise ProposalPayloadRefused(
                    f"proposal ledger payload carries a forbidden text key under {path} "
                    f"(one of {sorted(FORBIDDEN_PAYLOAD_KEYS)}); nothing was appended"
                )
            part = key if isinstance(key, str) and _SAFE_KEY.fullmatch(key) else "<key>"
            _refuse_text_keys(item, f"{path}.{part}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _refuse_text_keys(item, f"{path}[{index}]")


@dataclass(frozen=True)
class ProposalLedgerEntry:
    """A committed ledger operation with its decoded payload."""

    position: int
    op_id: str
    kind: str
    payload: dict[str, Any]
    payload_sha256: str
    committed_at: str
    record_schema_version: int


def _entry(row: ProposalLedgerRow) -> ProposalLedgerEntry:
    return ProposalLedgerEntry(
        position=row.position,
        op_id=row.op_id,
        kind=row.kind,
        payload=json.loads(row.payload),
        payload_sha256=row.payload_sha256,
        committed_at=row.committed_at,
        record_schema_version=row.record_schema_version,
    )


class PersistentProposalLedger:
    """The append-only proposal ledger of one corpus."""

    def __init__(self, ctx: CorpusStorageContext) -> None:
        self._ctx = ctx

    @property
    def corpus(self) -> str:
        return self._ctx.corpus

    async def append(
        self,
        kind: str,
        payload: Mapping[str, Any],
        *,
        op_id: str,
        expected_head: int | None = None,
    ) -> tuple[ProposalLedgerEntry, bool]:
        """Commit one operation. Returns ``(entry, replayed)``: ``replayed``
        is true when ``op_id`` was already committed for this same request."""
        ctx = self._ctx
        ctx._ensure_open()
        if not isinstance(op_id, str) or not op_id.strip() or len(op_id) > MAX_OP_ID_CHARS:
            raise ValueError(
                "a proposal ledger append needs an explicit, non-empty op_id of at most "
                f"{MAX_OP_ID_CHARS} characters"
            )
        if not isinstance(kind, str) or not _KIND.fullmatch(kind):
            raise ValueError("proposal ledger kind must be a short snake_case name")
        if not isinstance(payload, Mapping):
            raise TypeError("proposal ledger payload must be a JSON object")
        body = jcs.canonicalize(dict(payload))
        request = {"kind": kind, "payload": json.loads(body)}
        _refuse_text_keys(request["payload"], "payload")
        ctx.config.pii_gate.check({"op_id": op_id, **request})
        request_sha = hashlib.sha256(jcs.canonicalize(request)).hexdigest()

        async with ctx._write_lock:
            ctx._ensure_open()
            async with ctx._journal.write(ctx.corpus) as tx:
                existing = await tx.find_proposal_op(op_id)
                if existing is not None:
                    return _entry(check_replay(existing, request_sha)), True
                if expected_head is not None:
                    actual = await tx.proposal_head()
                    if actual != expected_head:
                        raise JournalStateChanged(expected=expected_head, actual=actual)
                row = await tx.append_proposal(
                    op_id=op_id, request_sha256=request_sha, kind=kind, payload=body
                )
        return _entry(row), False

    async def entries(self) -> list[ProposalLedgerEntry]:
        """Every committed operation of this corpus, in position order."""
        self._ctx._ensure_open()
        return [_entry(r) for r in await self._ctx._journal.proposal_rows(self.corpus)]

    async def head(self) -> int:
        """The last committed position (``-1`` for an empty ledger)."""
        self._ctx._ensure_open()
        return await self._ctx._journal.proposal_head(self.corpus)


__all__ = [
    "FORBIDDEN_PAYLOAD_KEYS",
    "PersistentProposalLedger",
    "ProposalLedgerEntry",
    "ProposalPayloadRefused",
]
