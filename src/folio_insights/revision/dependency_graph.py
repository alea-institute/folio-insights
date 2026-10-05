"""The explicit shard dependency web (Phase 9 U3, KTD7; PRD §8 P3).

A ``DependencyGraph`` holds the ``depends_on_*`` edges of a corpus: an edge
``dependent -> dependency`` for every IRI a shard's four dependency lists name.
It is built from ONE bulk adjacency read (``PersistentShardStore.
dependency_edges`` answers it with a single projection query; an in-memory
store is walked once), never from per-shard queries.

* ``dependents`` / ``dependencies`` — one hop.
* ``transitive_dependents`` — every shard that rests on an IRI, with its hop
  depth (breadth-first, so a shard reachable at depths 1 and 3 reads 1).
* ``cycles`` — iterative depth-first search with three-color marking; each
  cycle is a finding (canonically rotated, deduplicated), never an error.

Stdlib + Pydantic only (the shard envelope is the only folio import).
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from folio_insights.revision.store import DEPENDENCY_FIELDS

if TYPE_CHECKING:
    from folio_insights.revision.store import ShardStore
    from folio_insights.shards import ShardEnvelope

_WHITE, _GRAY, _BLACK = 0, 1, 2


@dataclass(frozen=True)
class DependencyEdge:
    """``dependent`` names ``dependency`` in its ``field`` list."""

    dependent: str
    dependency: str
    field: str


def shard_edges(shard: ShardEnvelope) -> list[DependencyEdge]:
    """The dependency edges one shard declares (a self-reference included: the
    graph reports it as a one-node cycle)."""
    out: list[DependencyEdge] = []
    for name in DEPENDENCY_FIELDS:
        for target in getattr(shard, name):
            out.append(DependencyEdge(shard.shard_iri, target, name))
    return out


class DependencyGraph:
    """Adjacency over shard IRIs (and the external IRIs they depend on)."""

    def __init__(self, edges: Iterable[DependencyEdge | tuple[str, str]] = (),
                 nodes: Iterable[str] = ()) -> None:
        self._deps: dict[str, set[str]] = {}
        self._rdeps: dict[str, set[str]] = {}
        self._edge_count = 0
        self._self_loops: set[str] = set()
        for node in nodes:
            self._deps.setdefault(node, set())
            self._rdeps.setdefault(node, set())
        for edge in edges:
            src, dst = (
                (edge.dependent, edge.dependency) if isinstance(edge, DependencyEdge) else edge
            )
            if src == dst:  # a self-dependency: a cycle finding, not an edge to walk
                self._self_loops.add(src)
                self._deps.setdefault(src, set())
                self._rdeps.setdefault(src, set())
                continue
            bucket = self._deps.setdefault(src, set())
            if dst not in bucket:
                bucket.add(dst)
                self._edge_count += 1
            self._rdeps.setdefault(dst, set()).add(src)
            self._deps.setdefault(dst, set())
            self._rdeps.setdefault(src, set())

    # ── construction ─────────────────────────────────────────────────────

    @classmethod
    def from_shards(cls, shards: Iterable[ShardEnvelope]) -> DependencyGraph:
        nodes: list[str] = []
        edges: list[DependencyEdge] = []
        for shard in shards:
            nodes.append(shard.shard_iri)
            edges.extend(shard_edges(shard))
        return cls(edges, nodes)

    @classmethod
    async def from_store(cls, store: ShardStore) -> DependencyGraph:
        """One bulk read: the store's ``dependency_edges()`` when it has one
        (the persistent store: a single projection query), else one walk of
        ``iter_shards()``."""
        bulk: Any = getattr(store, "dependency_edges", None)
        if callable(bulk):
            nodes, edges = await bulk()
            return cls(edges, nodes)
        return cls.from_shards([s async for s in store.iter_shards()])

    # ── reads ────────────────────────────────────────────────────────────

    @property
    def node_count(self) -> int:
        return len(self._deps)

    @property
    def edge_count(self) -> int:
        return self._edge_count

    def __contains__(self, iri: object) -> bool:
        return iri in self._deps

    def dependencies(self, iri: str) -> list[str]:
        return sorted(self._deps.get(iri, ()))

    def dependents(self, iri: str) -> list[str]:
        return sorted(self._rdeps.get(iri, ()))

    def transitive_dependents(self, iri: str) -> dict[str, int]:
        """Every shard resting on ``iri`` (directly or not) -> minimum hop depth."""
        return self._bfs(iri, self._rdeps)

    def transitive_dependencies(self, iri: str) -> dict[str, int]:
        return self._bfs(iri, self._deps)

    @staticmethod
    def _bfs(start: str, adjacency: dict[str, set[str]]) -> dict[str, int]:
        depth: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        seen = {start}
        while queue:
            node, d = queue.popleft()
            for nxt in sorted(adjacency.get(node, ())):
                if nxt not in seen:
                    seen.add(nxt)
                    depth[nxt] = d + 1
                    queue.append((nxt, d + 1))
        return depth

    def cycles(self) -> list[tuple[str, ...]]:
        """Every elementary cycle reached by a back edge in a DFS, as findings.

        Iterative DFS with white/gray/black marking over the dependency
        direction, neighbours in sorted order (deterministic). A back edge to
        a gray node closes a cycle; it is rotated to start at its smallest IRI
        and deduplicated. A shard that depends on itself is the one-node cycle
        ``(iri,)``.
        """
        color = dict.fromkeys(self._deps, _WHITE)
        found: dict[tuple[str, ...], None] = {}
        for root in sorted(self._deps):
            if color[root] != _WHITE:
                continue
            path: list[str] = [root]
            on_path = {root: 0}
            color[root] = _GRAY
            stack: list[tuple[str, Iterable[str]]] = [(root, iter(sorted(self._deps[root])))]
            while stack:
                node, neighbours = stack[-1]
                advanced = False
                for nxt in neighbours:
                    state = color.get(nxt, _WHITE)
                    if state == _WHITE:
                        color[nxt] = _GRAY
                        on_path[nxt] = len(path)
                        path.append(nxt)
                        stack.append((nxt, iter(sorted(self._deps.get(nxt, ())))))
                        advanced = True
                        break
                    if state == _GRAY:
                        cycle = path[on_path[nxt]:]
                        pivot = cycle.index(min(cycle))
                        found[tuple(cycle[pivot:] + cycle[:pivot])] = None
                if not advanced:
                    stack.pop()
                    color[node] = _BLACK
                    on_path.pop(node, None)
                    path.pop()
        for node in self._self_loops:
            found[(node,)] = None
        return sorted(found)

    def is_acyclic(self) -> bool:
        return not self.cycles()


__all__ = [
    "DependencyEdge",
    "DependencyGraph",
    "shard_edges",
]
