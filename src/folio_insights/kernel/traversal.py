"""Kernel derivation: which kernel maxims a shard derives from, and how (R11, KTD8).

PHILOSOPHY.md's axiomatic-kernel layer says every non-kernel shard is a theorem
whose derivation chain terminates in the kernel or in cited authority. That
chain is already in the envelope: ``elaborates`` (the Tractarian edge) and the
four ``depends_on_*`` lists. ``derivation_tree`` walks those fields
breadth-first from a shard and reports every kernel shard reached with the
shortest path to it; ``derived_from_kernel`` returns just those derivations
(the ``folio:derivedFromKernel`` view). Nothing is stored: the view is
recomputed from current shards on every call (KTD8).

* **Edges walked**, in this fixed order per shard: ``elaborates``,
  ``depends_on_axioms``, ``depends_on_definitions``, ``depends_on_precedents``,
  ``depends_on_shards``. Each edge records the field it came from.
* **Kernel detection** is the packaged manifest (``catalog.is_kernel_iri``):
  a kernel IRI terminates its branch whether or not the corpus has seeded it.
* **Shortest path, deterministic.** BFS visits each IRI once, so the first path
  to a kernel shard is a shortest one; ties break by the field order above and
  then list order, so the same corpus always yields the same path.
* **Cycle-safe and bounded.** A visited set stops cycles; ``max_depth`` bounds
  the number of hops, and ``truncated`` reports a frontier cut off by it.
* **Dangling references** (a cited IRI that is neither stored nor kernel) are
  listed in ``missing`` instead of failing the walk.

The walk reads through anything with an async ``get(iri)`` (a ``ShardStore``
such as ``ctx.shards``), a ``CorpusStorageContext`` or a plain mapping.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from folio_insights.kernel.catalog import KernelCatalog, load_catalog

if TYPE_CHECKING:
    from folio_insights.shards import ShardEnvelope

# Envelope fields a derivation follows, in tie-break order.
DERIVATION_FIELDS: tuple[str, ...] = (
    "elaborates",
    "depends_on_axioms",
    "depends_on_definitions",
    "depends_on_precedents",
    "depends_on_shards",
)
DEFAULT_MAX_DEPTH = 32


class UnknownShard(KeyError):
    """The traversal root is neither a stored shard nor a kernel IRI."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else "unknown shard"


@dataclass(frozen=True, order=True)
class DerivationEdge:
    """``source`` names ``target`` in its ``field`` list."""

    source: str
    target: str
    field: str

    def as_dict(self) -> dict[str, str]:
        return {"from": self.source, "to": self.target, "field": self.field}


@dataclass(frozen=True)
class KernelDerivation:
    """One kernel shard reached from the root, with the shortest path to it.

    ``path`` runs from the root to ``kernel_iri`` (both included); ``edges``
    has one entry per hop, in path order.
    """

    kernel_iri: str
    citation: str
    citation_uri: str
    path: tuple[str, ...]
    edges: tuple[DerivationEdge, ...]

    @property
    def depth(self) -> int:
        return len(self.edges)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kernel_iri": self.kernel_iri,
            "citation": self.citation,
            "citation_uri": self.citation_uri,
            "depth": self.depth,
            "path": list(self.path),
            "edges": [e.as_dict() for e in self.edges],
        }


@dataclass(frozen=True)
class DerivationTree:
    """The result of a walk from ``root``."""

    root: str
    max_depth: int
    derivations: tuple[KernelDerivation, ...]
    visited: tuple[str, ...]
    missing: tuple[str, ...]
    truncated: bool
    edges_walked: tuple[DerivationEdge, ...] = field(default=())

    @property
    def kernel_reached(self) -> bool:
        return bool(self.derivations)

    def chain_edges(self) -> tuple[DerivationEdge, ...]:
        """Every edge on some derivation path (deduplicated, sorted)."""
        return tuple(sorted({e for d in self.derivations for e in d.edges}))

    def chain_nodes(self) -> tuple[str, ...]:
        """The root plus every node on some derivation path (sorted)."""
        return tuple(sorted({self.root, *(n for d in self.derivations for n in d.path)}))


Getter = Callable[[str], Awaitable["ShardEnvelope | None"]]


def _getter(source: Any) -> Getter:
    """An async by-IRI lookup over a store, a storage context or a mapping."""
    if isinstance(source, Mapping):
        mapping = source

        async def get(iri: str) -> ShardEnvelope | None:
            return mapping.get(iri)

        return get
    shards = getattr(source, "shards", None)
    if shards is not None and callable(getattr(shards, "get", None)):
        return shards.get  # CorpusStorageContext
    if callable(getattr(source, "get", None)):
        return source.get  # ShardStore
    raise TypeError(f"cannot read shards from {type(source).__name__}")


async def derivation_tree(
    source: Any,
    iri: str,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    catalog: KernelCatalog | None = None,
) -> DerivationTree:
    """Walk ``iri``'s derivation fields breadth-first (module docstring).

    Raises ``UnknownShard`` when ``iri`` is neither stored nor a kernel IRI,
    and ``ValueError`` for a negative ``max_depth``.
    """
    if max_depth < 0:
        raise ValueError("max_depth must be >= 0")
    catalog = catalog or load_catalog()
    get = _getter(source)
    is_kernel = catalog.manifest.__contains__

    if not is_kernel(iri) and await get(iri) is None:
        raise UnknownShard(f"no shard {iri!r} in this corpus and not a kernel IRI")

    # parent[node] = the edge that first reached it (BFS => shortest path).
    parent: dict[str, DerivationEdge | None] = {iri: None}
    order: list[str] = [iri]
    walked: list[DerivationEdge] = []
    missing: list[str] = []
    kernels: list[str] = []
    truncated = False
    frontier = [iri]
    depth = 0
    while frontier:
        nxt: list[str] = []
        for node in frontier:
            if is_kernel(node):
                kernels.append(node)
                continue  # the kernel terminates a derivation
            shard = await get(node)
            if shard is None:
                missing.append(node)
                continue
            for field_name in DERIVATION_FIELDS:
                for target in getattr(shard, field_name):
                    edge = DerivationEdge(node, target, field_name)
                    if depth >= max_depth:
                        truncated = True
                        continue
                    walked.append(edge)
                    if target in parent:
                        continue  # already reached by a path at most as short
                    parent[target] = edge
                    order.append(target)
                    nxt.append(target)
        frontier = nxt
        depth += 1

    derivations = []
    for kernel_iri in kernels:
        edges: list[DerivationEdge] = []
        node = kernel_iri
        while (edge := parent[node]) is not None:
            edges.append(edge)
            node = edge.source
        edges.reverse()
        path = (iri, *(e.target for e in edges))
        maxim = catalog.by_iri(kernel_iri)
        if maxim is None:  # unreachable: manifest membership implies a catalog entry
            raise RuntimeError(f"kernel IRI {kernel_iri!r} has no catalog entry")
        derivations.append(
            KernelDerivation(kernel_iri, maxim.citation, maxim.citation_uri, path, tuple(edges))
        )
    derivations.sort(key=lambda d: (d.depth, d.citation_uri, d.kernel_iri))
    return DerivationTree(
        root=iri,
        max_depth=max_depth,
        derivations=tuple(derivations),
        visited=tuple(order),
        missing=tuple(sorted(missing)),
        truncated=truncated,
        edges_walked=tuple(walked),
    )


async def derived_from_kernel(
    source: Any,
    iri: str,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    catalog: KernelCatalog | None = None,
) -> list[KernelDerivation]:
    """Every kernel shard ``iri`` derives from, each with its shortest path.

    An empty list means no kernel shard is reachable within ``max_depth``.
    """
    tree = await derivation_tree(source, iri, max_depth=max_depth, catalog=catalog)
    return list(tree.derivations)


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DERIVATION_FIELDS",
    "DerivationEdge",
    "DerivationTree",
    "KernelDerivation",
    "UnknownShard",
    "derivation_tree",
    "derived_from_kernel",
]
