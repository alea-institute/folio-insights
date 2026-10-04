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

Phase 13 (KTD4) adds the typed corpus-scoped seam: every store names its
``corpus`` and exposes ``iter_shards`` / ``dependents_of``. The persistent
implementation is ``folio_insights.storage.shards.PersistentShardStore``.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from folio_insights.shards import ShardEnvelope


# The four dependency lists a shard may cite (D-18 cascade inputs). The typed
# ``dependents_of`` seam below and the Phase 13 projection read the same set.
DEPENDENCY_FIELDS: tuple[str, ...] = (
    "depends_on_precedents",
    "depends_on_definitions",
    "depends_on_shards",
    "depends_on_axioms",
)

DEFAULT_CORPUS = "default"


def depends_on(shard: ShardEnvelope, shard_iri: str) -> bool:
    """True iff any ``depends_on_*`` list of ``shard`` names ``shard_iri``."""
    return any(shard_iri in getattr(shard, name) for name in DEPENDENCY_FIELDS)


@runtime_checkable
class ShardStore(Protocol):
    """Corpus-scoped, by-IRI shard persistence seam (D-02; Phase 13 KTD4).

    Every store is bound to one corpus. ``get``/``put`` are the Phase 5 by-IRI
    surface; ``iter_shards`` and ``dependents_of`` are the typed enumeration
    seam that replaces private-dictionary inspection (``store._d``) so a
    persistent backend never silently loses the dependency graph.
    """

    @property
    def corpus(self) -> str:
        """The corpus this store is bound to."""
        ...

    async def get(self, shard_iri: str) -> ShardEnvelope | None:
        """Return the shard stored under ``shard_iri``, or ``None`` if unseen."""
        ...

    async def put(self, shard_iri: str, shard: ShardEnvelope) -> None:
        """Store ``shard`` under ``shard_iri`` (insert or new revision)."""
        ...

    def iter_shards(self) -> AsyncIterator[ShardEnvelope]:
        """Every current shard in this corpus, ordered by IRI."""
        ...

    async def dependents_of(self, shard_iri: str) -> list[ShardEnvelope]:
        """Current shards (other than ``shard_iri``) whose dependency lists
        name ``shard_iri``, ordered by IRI."""
        ...


class InMemoryShardStore:
    """Process-local in-memory ``ShardStore`` (D-02). Reset per construction.

    Stdlib + Pydantic only. Phase 13's persistent store lives in
    ``folio_insights.storage`` behind the identical async interface.
    """

    def __init__(self, corpus: str = DEFAULT_CORPUS) -> None:
        self._corpus = corpus
        self._d: dict[str, ShardEnvelope] = {}

    @property
    def corpus(self) -> str:
        return self._corpus

    async def get(self, shard_iri: str) -> ShardEnvelope | None:
        return self._d.get(shard_iri)

    async def put(self, shard_iri: str, shard: ShardEnvelope) -> None:
        self._d[shard_iri] = shard

    async def iter_shards(self) -> AsyncIterator[ShardEnvelope]:
        for iri in sorted(self._d):
            yield self._d[iri]

    async def dependents_of(self, shard_iri: str) -> list[ShardEnvelope]:
        return [
            self._d[iri]
            for iri in sorted(self._d)
            if iri != shard_iri and depends_on(self._d[iri], shard_iri)
        ]


__all__ = [
    "DEFAULT_CORPUS",
    "DEPENDENCY_FIELDS",
    "InMemoryShardStore",
    "ShardStore",
    "depends_on",
]
