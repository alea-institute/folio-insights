"""Persistent ``GovernanceLog`` over the corpus journal (Phase 13 U2, D-04/D-05).

Keeps the five-method Protocol surface and nothing else public (D-05 part b):
``append``, ``query_active_roles_at``, ``get_by_position``, ``iter_events`` and
``latest_position``. ``append`` accepts an optional keyword ``op_id`` for
replay protection; the Protocol's positional call shape is unchanged.

Every gate is the in-memory log's own code: the context loads the committed
history inside its ``BEGIN IMMEDIATE`` transaction and runs
``InMemoryGovernanceLog._from_history(...).append(event)`` there, so genesis
carve-out, signer-must-be-admin, last-admin lockout, monotonic positions and
the SHACL shapes hold under competing writers. Signature verification
(``StorageConfig.event_verifier``) runs before the transaction. The journal's
UPDATE/DELETE triggers are the third defense-in-depth layer.

Reads pass the projection barrier and stay at or below the watermark. A log
bound to corpus A refuses questions about corpus B (``CorpusIsolationError``).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING

from folio_insights.governance.events import GovernanceEvent
from folio_insights.governance.roles import active_roles_at

if TYPE_CHECKING:
    from folio_insights.storage.context import CorpusStorageContext


class PersistentGovernanceLog:
    """``GovernanceLog`` backed by the SQLite journal of one corpus."""

    def __init__(self, ctx: CorpusStorageContext) -> None:
        self._ctx = ctx

    async def append(
        self,
        event: GovernanceEvent,
        *,
        op_id: str | None = None,
        expected_head: int | None = None,
    ) -> GovernanceEvent:
        """Single write entry (D-06). Returns the persisted event with its
        position. Retrying the same ``op_id`` (or, by default, the identical
        signed event) returns the committed event instead of appending.

        ``expected_head`` makes the append conditional: inside the write
        transaction the corpus journal head must still equal it (the state a
        saved preview was built against), else ``JournalStateChanged`` and
        nothing is appended."""
        return await self._ctx._append_governance(
            event, op_id=op_id, expected_head=expected_head
        )

    async def query_active_roles_at(
        self, corpus: str, asof: datetime
    ) -> dict[str, set[str]]:
        self._ctx._check_corpus(corpus)
        return await active_roles_at(corpus, asof, log=self)

    async def get_by_position(
        self, corpus: str, position: int
    ) -> GovernanceEvent | None:
        self._ctx._check_corpus(corpus)
        upto = await self._ctx._barrier()
        if position < 0:
            return None
        row = await self._ctx._journal.governance_row_at(corpus, position, upto=upto)
        if row is None:
            return None
        from folio_insights.storage.context import _event_from_row

        return _event_from_row(row)

    async def iter_events(self, corpus: str) -> AsyncIterator[GovernanceEvent]:
        self._ctx._check_corpus(corpus)
        upto = await self._ctx._barrier()
        from folio_insights.storage.context import _event_from_row

        for row in await self._ctx._journal.governance_rows(corpus, upto=upto):
            yield _event_from_row(row)

    async def latest_position(self, corpus: str) -> int:
        self._ctx._check_corpus(corpus)
        upto = await self._ctx._barrier()
        return await self._ctx._journal.latest_governance_position(corpus, upto=upto)


__all__ = ["PersistentGovernanceLog"]
