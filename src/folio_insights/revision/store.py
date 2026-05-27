"""Phase 5 ShardStore seam — in-memory, by-IRI persistence (CONTEXT D-02, D-03).

The ``edit_shard_content`` / ``get_shard_at`` write + read paths look shards up
*by IRI* (the PRD §6.4 signature is ``edit_shard_content(shard_iri, ...)``). D-02
keeps that signature honest with a thin ``ShardStore`` protocol over an in-memory
dict; Phase 13 swaps a persistent Oxigraph-backed store in behind the *same*
async interface without touching any caller (D-03 — the path is ``async def`` so
Phase 10 Arq + Phase 13 async Oxigraph slot in without signature churn).

Analog: ``shards/iri_registry.py::ShardIRIRegistry`` (the existing in-memory-dict
+ typed-raise idiom) — this store mirrors the dict-backed shape but keys by
``shard_iri`` and exposes plain ``get`` / ``put`` rather than mint-and-register.

Boundary (05-PATTERNS L134): this module lives in ``revision/`` (OUTSIDE the
``shards/`` dep-leak guard), but the D-02 seam is deliberately stdlib + Pydantic
ONLY — NO ``aiosqlite`` / ``pyoxigraph`` / ``oxrdflib`` import here. Phase 13 is
the place that fills the persistent backend; in Phase 5 the dict IS the store.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from folio_insights.shards import ShardEnvelope


@runtime_checkable
class ShardStore(Protocol):
    """By-IRI shard persistence seam (D-02). Phase 13 swaps Oxigraph behind it."""

    async def get(self, shard_iri: str) -> ShardEnvelope | None:
        """Return the shard stored under ``shard_iri``, or ``None`` if unseen."""
        ...

    async def put(self, shard_iri: str, shard: ShardEnvelope) -> None:
        """Store ``shard`` under ``shard_iri`` (insert or overwrite)."""
        ...


class InMemoryShardStore:
    """Process-local in-memory ``ShardStore`` (D-02). Reset per construction.

    Stdlib + Pydantic only — the dict IS the seam Phase 13 replaces with a
    persistent Oxigraph-backed store behind the identical async interface.
    """

    def __init__(self) -> None:
        self._d: dict[str, ShardEnvelope] = {}

    async def get(self, shard_iri: str) -> ShardEnvelope | None:
        return self._d.get(shard_iri)

    async def put(self, shard_iri: str, shard: ShardEnvelope) -> None:
        self._d[shard_iri] = shard


__all__ = ["ShardStore", "InMemoryShardStore"]
