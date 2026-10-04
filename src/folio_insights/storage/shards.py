"""Persistent ``ShardStore`` over the corpus journal (Phase 13 U2, KTD4).

Implements the typed corpus-scoped seam from ``revision/store.py``:

* ``get`` / ``put`` — the Phase 5 by-IRI surface. Every ``put`` is a new
  journal revision (nothing is overwritten); it goes through the U17 adapter
  (``dump_shard_record`` + ``load_shard_record`` validation), the PII gate and
  the frozen-identity check before the append.
* ``iter_shards`` — the current revision of every shard in the corpus.
* ``dependents_of`` — answered by the Oxigraph projection (the dependency
  edges), then materialized from the journal at the same watermark.
* ``get_record`` — the stored revision with its original bytes and source
  schema version (export/audit seam for U4).

All reads pass the projection barrier first and read at the watermark.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from folio_insights.shards import ShardEnvelope, load_shard_record

if TYPE_CHECKING:
    from folio_insights.storage.context import CorpusStorageContext, StoredShardRecord


class PersistentShardStore:
    """``ShardStore`` backed by the SQLite journal and Oxigraph projection."""

    def __init__(self, ctx: CorpusStorageContext) -> None:
        self._ctx = ctx

    @property
    def corpus(self) -> str:
        return self._ctx.corpus

    async def get(self, shard_iri: str) -> ShardEnvelope | None:
        record = await self.get_record(shard_iri)
        return None if record is None else record.shard

    async def get_record(self, shard_iri: str) -> StoredShardRecord | None:
        upto = await self._ctx._barrier()
        return await self._ctx._shard_record(shard_iri, upto)

    async def put(
        self, shard_iri: str, shard: ShardEnvelope, *, op_id: str | None = None
    ) -> None:
        """Append a new revision of ``shard_iri``.

        Retry safety needs an explicit ``op_id``: retrying it returns the
        committed result even after later revisions of the same shard. The
        default op_id is derived from the prior revision's position, so it is
        NOT retry-safe once another revision lands; callers (U3) must pass an
        explicit op_id for any write they may retry.
        """
        await self._ctx._put_shard(shard_iri, shard, op_id=op_id)

    async def iter_shards(self) -> AsyncIterator[ShardEnvelope]:
        upto = await self._ctx._barrier()
        for row in await self._ctx._current_shard_rows(upto):
            yield load_shard_record(row.payload).shard

    async def dependents_of(self, shard_iri: str) -> list[ShardEnvelope]:
        corpus = self._ctx.corpus
        watermark, iris = await self._ctx._read_projection(
            lambda handle, _wm: handle.dependents(corpus, shard_iri)
        )
        out: list[ShardEnvelope] = []
        for iri in iris:
            if iri == shard_iri:
                continue
            record = await self._ctx._shard_record(iri, watermark)
            if record is not None:
                out.append(record.shard)
        return out


__all__ = ["PersistentShardStore"]
