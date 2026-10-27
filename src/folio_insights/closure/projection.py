"""Recover closure under the storage lock and capture complete count snapshots."""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING, Any

from pyoxigraph import NamedNode, Store

from folio_insights.closure.declarations import LEDGER_KIND, load_declarations
from folio_insights.query.closed_world import CLOSED_UNDER, ClosedWorldSnapshot
from folio_insights.storage.projection import (
    CHAIN_GENESIS, ProjectionHandle, corpus_graph, corpus_graphs, governance_graph,
)

if TYPE_CHECKING:
    from folio_insights.storage.context import CorpusStorageContext


async def sync_closure(ctx: CorpusStorageContext, handle: ProjectionHandle, watermark: int,
                       main_digest: str | None) -> None:
    """Fold exactly one metadata prefix against the projection's main-journal prefix."""
    entries = await ctx.proposals.entries()
    if not any(entry.kind == LEDGER_KIND for entry in entries):
        # The common case needs neither signature checks nor main-journal reconstruction.
        await asyncio.to_thread(handle.replace_closure, ctx.corpus, (), None)
        return

    def members() -> set[str]:
        return {quad.subject.value for graph in (corpus_graph(ctx.corpus), governance_graph(ctx.corpus))
                for quad in handle.graph_quads(graph) if isinstance(quad.subject, NamedNode)}

    loaded = await load_declarations(
        ctx, main_head=watermark, main_digest=main_digest or CHAIN_GENESIS,
        entries=entries, known_members=await asyncio.to_thread(members),
    )
    handle.closure_scopes = tuple(declaration.scope for declaration in loaded.active)
    digest = hashlib.sha256(json.dumps(
        [loaded.main_head, loaded.main_digest, loaded.ledger_head, loaded.ledger_digest],
        separators=(",", ":"),
    ).encode()).hexdigest()
    triples = [(member, CLOSED_UNDER, declaration.scope_iri)
               for declaration in loaded.active for member in declaration.members]
    await asyncio.to_thread(handle.replace_closure, ctx.corpus, triples, digest)


class SnapshotRunner:
    """An immutable, corpus-isolated RDF copy; all awaits in one count read this copy."""

    def __init__(self, handle: ProjectionHandle, corpus: str) -> None:
        self._store = Store()
        self._graphs = corpus_graphs(corpus)
        self._store.extend(quad for graph in self._graphs for quad in handle.graph_quads(graph))

    async def query(self, sparql: str, *, include_tbox: bool = False) -> Any:
        # ClosedWorldQuery's fixed SELECT templates validate every interpolated IRI.
        result = self._store.query(sparql, default_graph=self._graphs, named_graphs=self._graphs)
        names = [variable.value for variable in result.variables]
        return [{name: row[name] for name in names} for row in result]


async def capture_snapshot(ctx: CorpusStorageContext) -> ClosedWorldSnapshot:
    def read(handle: ProjectionHandle, _watermark: int) -> ClosedWorldSnapshot:
        return ClosedWorldSnapshot(SnapshotRunner(handle, ctx.corpus), handle.closure_scopes)

    _, snapshot = await ctx._read_projection(read)
    return snapshot
