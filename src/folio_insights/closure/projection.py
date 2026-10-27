"""Recover closure under the storage lock and capture complete count snapshots."""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pyoxigraph import NamedNode, Store

from folio_insights.closure.declarations import (
    LEDGER_KIND, ClosureDeclaration, ClosureDeclarationRefused, _ledger_digest,
    capture_main_state, load_declarations,
)
from folio_insights.query.closed_world import CLOSED_UNDER, ClosedWorldSnapshot
from folio_insights.storage.projection import (
    CHAIN_GENESIS, ProjectionHandle, _refuse_service, corpus_graph, corpus_graphs, governance_graph,
)

if TYPE_CHECKING:
    from folio_insights.storage.context import CorpusStorageContext


@dataclass(frozen=True)
class ClosureProjectionCache:
    """Authority derived from complete verified main and metadata prefixes."""

    corpus: str
    token: tuple[int, str, int, str]
    active: tuple[ClosureDeclaration, ...]


async def sync_closure(ctx: CorpusStorageContext, handle: ProjectionHandle, watermark: int,
                       main_digest: str | None) -> None:
    """Fold exactly one metadata prefix against the projection's main-journal prefix."""
    entries = await ctx.proposals.entries()
    if not any(entry.kind == LEDGER_KIND for entry in entries):
        ctx._closure_cache = None
        handle.closure_scopes = ()
        await asyncio.to_thread(handle.replace_closure, ctx.corpus, (), None)
        return

    def members() -> set[str]:
        return {quad.subject.value for graph in (corpus_graph(ctx.corpus), governance_graph(ctx.corpus))
                for quad in handle.graph_quads(graph) if isinstance(quad.subject, NamedNode)}

    head, digest = await capture_main_state(ctx, upto=watermark)
    if digest != (main_digest or CHAIN_GENESIS):
        raise ClosureDeclarationRefused("captured main journal digest does not match")
    token = (head, digest, len(entries) - 1, _ledger_digest(entries))
    cached = ctx._closure_cache
    if cached is None or cached.corpus != ctx.corpus or cached.token != token:
        loaded = await load_declarations(
            ctx, main_head=head, main_digest=digest, entries=entries,
            known_members=await asyncio.to_thread(members),
        )
        cached = ClosureProjectionCache(ctx.corpus, token, loaded.active)
        ctx._closure_cache = cached
    handle.closure_scopes = tuple(declaration.scope for declaration in cached.active)
    digest = hashlib.sha256(json.dumps(
        token, separators=(",", ":"),
    ).encode()).hexdigest()
    triples = ((member, CLOSED_UNDER, declaration.scope_iri)
               for declaration in cached.active for member in declaration.members)
    await asyncio.to_thread(handle.replace_closure, ctx.corpus, triples, digest)


class SnapshotRunner:
    """An immutable, corpus-isolated RDF copy; all awaits in one count read this copy."""

    def __init__(self, handle: ProjectionHandle, corpus: str) -> None:
        self._store = Store()
        self._graphs = corpus_graphs(corpus)
        self._store.extend(quad for graph in self._graphs for quad in handle.graph_quads(graph))

    async def query(self, sparql: str, *, include_tbox: bool = False) -> Any:
        _refuse_service(sparql)
        result = self._store.query(sparql, default_graph=self._graphs, named_graphs=self._graphs)
        names = [variable.value for variable in result.variables]
        return [{name: row[name] for name in names} for row in result]


async def capture_snapshot(ctx: CorpusStorageContext) -> ClosedWorldSnapshot:
    def read(handle: ProjectionHandle, _watermark: int) -> ClosedWorldSnapshot:
        return ClosedWorldSnapshot(SnapshotRunner(handle, ctx.corpus), handle.closure_scopes)

    _, snapshot = await ctx._read_projection(read)
    return snapshot
