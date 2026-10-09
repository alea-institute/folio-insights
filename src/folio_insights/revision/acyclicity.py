"""The dependency-cycle guard (drain U4, R13, KTD9).

A write may not close a cycle in the dependency web: the four
``depends_on_*`` lists PLUS the Tractarian ``elaborates`` edges. A cycle there
would make derivation (``kernel/traversal.py``), the Tractarian tree and the
retraction cascade circular, so the storage layer refuses the whole batch with
``DependencyCycle`` before anything is appended (``storage/context.py``,
``StorageConfig.refuse_dependency_cycles``).

What counts as closing a cycle
------------------------------
The graph *after* the write is the committed graph with every batch shard's
out-edges replaced by the edges of its last revision in the batch. Only the
edges a batch ADDS (an edge its shard did not already declare in its committed
revision) can close a cycle: a write that leaves a legacy cycle's edges as
they were (for example a signature or retraction-driven revision of a shard
already on a stored cycle) is not refused, and ``folio-insights graph
validate`` reports the stored cycle instead. A self-edge is a one-node cycle.

The search is incremental: it reads committed adjacency only for nodes
reachable from the targets of the new edges, a frontier at a time (one bulk
read per breadth-first level), then runs one iterative Tarjan SCC pass over
that forward closure. A new edge ``u -> v`` closes a cycle exactly when ``u``
and ``v`` share a strongly connected component; the named cycle is the
shortest path ``v -> ... -> u`` followed by the closing edge back to ``v``.
Work is linear in the closure, so bulk loads into an empty corpus stay cheap
and a large corpus is read only where the batch touches it.

The search core is sans-IO (a generator that yields the IRIs whose committed
adjacency it needs), so the same algorithm runs over an in-memory
``DependencyGraph`` (``check_new_edges``) and inside the journal write
transaction (``afind_new_cycle`` with an async loader).

Stdlib + Pydantic only, like the rest of ``revision/``.
"""
from __future__ import annotations

from collections import deque
from collections.abc import (
    Awaitable,
    Callable,
    Generator,
    Iterable,
    Mapping,
    Sequence,
)
from typing import TYPE_CHECKING, Any

from folio_insights.revision.dependency_graph import ELABORATES_FIELD
from folio_insights.revision.store import DEPENDENCY_FIELDS

if TYPE_CHECKING:
    from folio_insights.revision.dependency_graph import DependencyGraph
    from folio_insights.shards import ShardEnvelope

# Every field whose IRIs are edges for the guard: dependencies, then elaborates.
EDGE_FIELDS: tuple[str, ...] = (*DEPENDENCY_FIELDS, ELABORATES_FIELD)

# What the sans-IO search yields (IRIs to load) and is sent back (their
# committed out-edges; an IRI absent from the mapping has none).
_Load = list[str]
_Loaded = Mapping[str, Sequence[str]]
_Search = Generator[_Load, _Loaded, "list[str] | None"]


class DependencyCycle(ValueError):
    """A write would close a cycle in the dependency web; nothing was written.

    ``cycle`` is the closed path as IRIs, first == last (``[A, B, A]``; a
    self-edge is ``[A, A]``). The path starts at the target of the edge the
    write adds and ends with that edge, so ``"A -> B -> A"`` reads "A already
    rests on B, and the write makes B rest on A".
    """

    def __init__(self, cycle: Sequence[str]) -> None:
        self.cycle: list[str] = list(cycle)
        super().__init__(
            "write refused: it would close a dependency cycle "
            + " -> ".join(self.cycle)
        )

    @property
    def path(self) -> str:
        """The cycle as ``"A -> B -> A"``."""
        return " -> ".join(self.cycle)


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def shard_out_edges(shard: ShardEnvelope) -> tuple[str, ...]:
    """Every IRI ``shard`` points at through ``EDGE_FIELDS``, in field order,
    deduplicated (a self-reference included)."""
    return _unique(target for name in EDGE_FIELDS for target in getattr(shard, name))


def record_out_edges(record: Mapping[str, Any]) -> tuple[str, ...]:
    """``shard_out_edges`` over a decoded shard record (the journal payload
    JSON), without model validation. A missing or non-list field reads empty,
    so a legacy record that predates a field contributes no edges for it."""
    out: list[str] = []
    for name in EDGE_FIELDS:
        values = record.get(name)
        if isinstance(values, list):
            out.extend(v for v in values if isinstance(v, str))
    return _unique(out)


def _search(batch: Mapping[str, Sequence[str]]) -> _Search:
    """Sans-IO core. ``batch`` maps each written shard IRI (in batch order) to
    its post-write out-edges. Yields lists of IRIs whose COMMITTED out-edges it
    needs; returns the closed cycle or ``None``."""
    if not batch:
        return None
    committed: dict[str, tuple[str, ...]] = {}
    got = yield list(batch)
    for iri in batch:
        committed[iri] = tuple(got.get(iri, ()))

    new_edges: list[tuple[str, str]] = []
    for src, targets in batch.items():
        before = set(committed[src])
        for dst in targets:
            if dst not in before:
                if dst == src:
                    return [src, src]
                new_edges.append((src, dst))
    if not new_edges:
        return None

    def adjacency(node: str) -> Sequence[str]:
        return batch[node] if node in batch else committed.get(node, ())

    # Forward closure from every new-edge target, loading committed adjacency
    # one breadth-first level at a time. Batch shards use their batch edges.
    reached: set[str] = set()
    frontier = list(_unique(dst for _, dst in new_edges))
    while frontier:
        need = [n for n in frontier if n not in batch and n not in committed]
        if need:
            got = yield need
            for n in need:
                committed[n] = tuple(got.get(n, ()))
        reached.update(frontier)
        queued: dict[str, None] = {}
        for node in frontier:
            for nxt in adjacency(node):
                if nxt not in reached:
                    queued[nxt] = None
        frontier = list(queued)

    candidates = [(src, dst) for src, dst in new_edges if src in reached]
    if not candidates:
        return None
    component = _tarjan(reached, adjacency)
    for src, dst in candidates:
        if component[src] == component[dst]:
            return [*_shortest_path(dst, src, adjacency), dst]
    return None


def _tarjan(
    nodes: set[str], adjacency: Callable[[str], Sequence[str]]
) -> dict[str, int]:
    """Iterative Tarjan: node -> strongly connected component id. ``nodes``
    must be closed under ``adjacency`` (a forward closure is)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    component: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = 0
    next_component = 0
    for root in sorted(nodes):
        if root in index:
            continue
        work: list[tuple[str, Iterable[str]]] = [(root, iter(adjacency(root)))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, neighbours = work[-1]
            advanced = False
            for nxt in neighbours:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(adjacency(nxt))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component[member] = next_component
                    if member == node:
                        break
                next_component += 1
    return component


def _shortest_path(
    start: str, goal: str, adjacency: Callable[[str], Sequence[str]]
) -> list[str]:
    """Breadth-first ``start -> ... -> goal`` (neighbours in declared order,
    so the named path is deterministic). The caller guarantees reachability."""
    previous: dict[str, str | None] = {start: None}
    queue: deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            break
        for nxt in adjacency(node):
            if nxt not in previous:
                previous[nxt] = node
                queue.append(nxt)
    path: list[str] = []
    cursor: str | None = goal
    while cursor is not None:
        path.append(cursor)
        cursor = previous[cursor]
    return path[::-1]


def _batch_edges(new_shards: Iterable[ShardEnvelope]) -> dict[str, tuple[str, ...]]:
    """Each written IRI's post-write out-edges: its LAST revision in the batch
    wins (batch order is preserved for deterministic findings)."""
    batch: dict[str, tuple[str, ...]] = {}
    for shard in new_shards:
        batch.pop(shard.shard_iri, None)
        batch[shard.shard_iri] = shard_out_edges(shard)
    return batch


def run_search(
    batch: Mapping[str, Sequence[str]],
    load: Callable[[list[str]], _Loaded],
) -> list[str] | None:
    """Drive the search with a synchronous committed-adjacency loader."""
    search = _search(batch)
    try:
        request = next(search)
        while True:
            request = search.send(load(request))
    except StopIteration as done:
        return done.value


async def arun_search(
    batch: Mapping[str, Sequence[str]],
    load: Callable[[list[str]], Awaitable[_Loaded]],
) -> list[str] | None:
    """Drive the search with an async loader (the journal write transaction)."""
    search = _search(batch)
    try:
        request = next(search)
        while True:
            request = search.send(await load(request))
    except StopIteration as done:
        return done.value


def _graph_loader(graph: DependencyGraph) -> Callable[[list[str]], _Loaded]:
    # The graph keeps self-loops out of its adjacency; they are committed
    # edges too, so a batch that keeps one is not "adding" it.
    self_loops: set[str] = getattr(graph, "_self_loops", set())

    def load(iris: list[str]) -> _Loaded:
        out: dict[str, tuple[str, ...]] = {}
        for iri in iris:
            if iri in graph:
                targets = graph.dependencies(iri)
                out[iri] = (*targets, iri) if iri in self_loops else tuple(targets)
        return out

    return load


def find_new_cycle(
    committed_graph: DependencyGraph, new_shards: Iterable[ShardEnvelope]
) -> list[str] | None:
    """The cycle ``new_shards`` would close over ``committed_graph``, or
    ``None``. Build the committed graph with ``include_elaborates=True``;
    otherwise committed ``elaborates`` edges are invisible to the check."""
    return run_search(_batch_edges(new_shards), _graph_loader(committed_graph))


def check_new_edges(
    committed_graph: DependencyGraph, new_shards: Iterable[ShardEnvelope]
) -> None:
    """Raise ``DependencyCycle`` if writing ``new_shards`` (as one batch) over
    ``committed_graph`` would close a cycle: a cycle against committed edges,
    a cycle internal to the batch, or a self-edge."""
    cycle = find_new_cycle(committed_graph, new_shards)
    if cycle is not None:
        raise DependencyCycle(cycle)


__all__ = [
    "EDGE_FIELDS",
    "DependencyCycle",
    "arun_search",
    "check_new_edges",
    "find_new_cycle",
    "record_out_edges",
    "run_search",
    "shard_out_edges",
]
