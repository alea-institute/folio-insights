"""Shard clusters on four axes (Phase 9 U1, PRINCIPLE-01).

PHILOSOPHY.md P1: "every shard belongs to one or more clusters (shards from a
common document, doctrinal neighborhood, or holding)". ``ClusterBuilder``
makes those clusters explicit, one axis at a time:

* ``source`` — shards extracted from the same source document
  (``source_uri``).
* ``tractarian`` — a Tractarian subtree: a root shard (one with no in-corpus
  ``elaborates`` parent) and every shard that elaborates it, transitively,
  through each shard's PRIMARY parent (its first in-corpus ``elaborates``
  entry). The tree is computed here from ``elaborates`` alone, so this module
  does not depend on the Tractarian-path registry.
* ``doctrinal`` — shards whose FOLIO concepts share an ancestor at a
  configurable depth below the FOLIO roots. Ancestry comes from an injected
  ``BranchResolver`` (``bfo.spine``): the caller supplies FOLIO, tests supply
  a fixture map. Without a resolver every concept is its own root.
* ``jurisdiction`` — shards whose ``framework_id`` resolves, through the
  corpus framework registry, to the same jurisdiction.

A shard may sit in several clusters on one axis (a multi-parent FOLIO concept)
and in clusters on every axis. Clusters smaller than ``min_size`` are dropped:
one shard alone cannot hold a cross-shard contradiction. Everything is
deterministic: clusters are ordered by ``(axis, key)`` and members by IRI.

Pure stdlib + Pydantic; safe for the web tier.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from folio_insights.bfo.spine import FOLIO_PREFIX, BranchResolver

if TYPE_CHECKING:
    from folio_insights.models.framework import FrameworkRegistry
    from folio_insights.shards import ShardEnvelope

ClusterAxis = Literal["source", "tractarian", "doctrinal", "jurisdiction"]
CLUSTER_AXES: tuple[ClusterAxis, ...] = ("source", "tractarian", "doctrinal", "jurisdiction")

DEFAULT_DOCTRINAL_DEPTH = 2
# Bounds on the FOLIO ancestry walk: a deep or densely multi-parent hierarchy
# must not turn one shard into an unbounded path enumeration.
MAX_ANCESTRY_DEPTH = 64
MAX_ROOT_PATHS = 32


def is_folio_concept(term: str) -> bool:
    """The default concept filter: an IRI in the FOLIO namespace."""
    return term.startswith(FOLIO_PREFIX)


def shard_concepts(
    shard: ShardEnvelope, concept_filter: Callable[[str], bool] = is_folio_concept
) -> tuple[str, ...]:
    """The concept IRIs a shard is about: its triple's subject and object and
    its ``reference``, kept when ``concept_filter`` accepts them (sorted,
    de-duplicated). The predicate is a relation, not a topic, and is skipped."""
    candidates = (shard.triple.subject, shard.triple.object, shard.reference)
    return tuple(sorted({c for c in candidates if c and concept_filter(c)}))


@dataclass(frozen=True)
class ShardCluster:
    """One cluster: an axis, the key the members share, and the member IRIs."""

    axis: ClusterAxis
    key: str
    members: tuple[str, ...]

    @property
    def id(self) -> str:
        return f"{self.axis}:{self.key}"

    @property
    def size(self) -> int:
        return len(self.members)

    def __contains__(self, shard_iri: object) -> bool:
        return shard_iri in self.members


@dataclass
class ClusterSet:
    """The clusters of a corpus plus what the builder could not place."""

    clusters: list[ShardCluster]
    # framework_id -> shard IRIs whose framework the registry does not know.
    unresolved_frameworks: dict[str, list[str]] = field(default_factory=dict)
    # Shards with no concept IRI (they sit on no doctrinal cluster).
    shards_without_concepts: list[str] = field(default_factory=list)
    # Primary-parent ``elaborates`` loops found while rooting subtrees.
    elaborates_cycles: list[tuple[str, ...]] = field(default_factory=list)
    shard_count: int = 0

    def by_axis(self, axis: ClusterAxis) -> list[ShardCluster]:
        return [c for c in self.clusters if c.axis == axis]

    def containing(self, shard_iris: Iterable[str]) -> list[ShardCluster]:
        """Every cluster holding ALL of ``shard_iris`` (cluster context for a finding)."""
        wanted = set(shard_iris)
        if not wanted:
            return []
        return [c for c in self.clusters if wanted.issubset(c.members)]

    def diagnostics(self) -> dict[str, object]:
        return {
            "unresolved_frameworks": {k: list(v) for k, v in sorted(self.unresolved_frameworks.items())},
            "shards_without_concepts": list(self.shards_without_concepts),
            "elaborates_cycles": [list(c) for c in self.elaborates_cycles],
        }


class ClusterBuilder:
    """Group shards into clusters on the configured axes.

    Args:
        registry: the corpus framework registry (``frameworks.registry.
            load_registry``). Without one the jurisdiction axis is empty and
            every framework reads as unresolved.
        folio_resolver: FOLIO ancestry (direct ``rdfs:subClassOf`` parents).
        doctrinal_depth: depth below the FOLIO roots of the shared ancestor
            that defines a doctrinal neighbourhood (a root is depth 0). A
            concept shallower than the depth keys on itself.
        concept_filter: which triple terms count as concept IRIs.
        axes: the axes to build (default: all four).
        min_size: smallest cluster kept (default 2).
    """

    def __init__(
        self,
        *,
        registry: FrameworkRegistry | None = None,
        folio_resolver: BranchResolver | None = None,
        doctrinal_depth: int = DEFAULT_DOCTRINAL_DEPTH,
        concept_filter: Callable[[str], bool] = is_folio_concept,
        axes: Sequence[ClusterAxis] = CLUSTER_AXES,
        min_size: int = 2,
    ) -> None:
        if doctrinal_depth < 0:
            raise ValueError(f"doctrinal_depth must be >= 0, got {doctrinal_depth}")
        if min_size < 1:
            raise ValueError(f"min_size must be >= 1, got {min_size}")
        unknown = [a for a in axes if a not in CLUSTER_AXES]
        if unknown:
            raise ValueError(f"unknown cluster axes {unknown}; expected a subset of {CLUSTER_AXES}")
        self.registry = registry
        self.folio_resolver = folio_resolver
        self.doctrinal_depth = doctrinal_depth
        self.concept_filter = concept_filter
        self.axes: tuple[ClusterAxis, ...] = tuple(dict.fromkeys(axes))
        self.min_size = min_size
        self._root_paths: dict[str, tuple[tuple[str, ...], ...]] = {}

    # ── public ────────────────────────────────────────────────────────────

    def build(self, shards: Iterable[ShardEnvelope]) -> ClusterSet:
        """Every cluster of ``shards`` on the configured axes."""
        by_iri: dict[str, ShardEnvelope] = {}
        for shard in shards:
            by_iri[shard.shard_iri] = shard  # the current revision wins
        result = ClusterSet(clusters=[], shard_count=len(by_iri))
        groups: dict[tuple[ClusterAxis, str], set[str]] = defaultdict(set)
        if "source" in self.axes:
            for iri, shard in by_iri.items():
                groups[("source", shard.source_uri)].add(iri)
        if "tractarian" in self.axes:
            roots, cycles = self._tractarian_roots(by_iri)
            result.elaborates_cycles = cycles
            for iri, root in roots.items():
                groups[("tractarian", root)].add(iri)
        if "doctrinal" in self.axes:
            for iri, shard in by_iri.items():
                concepts = shard_concepts(shard, self.concept_filter)
                if not concepts:
                    result.shards_without_concepts.append(iri)
                    continue
                for key in self._doctrinal_keys(concepts):
                    groups[("doctrinal", key)].add(iri)
        resolve = self.registry is not None or "jurisdiction" in self.axes
        for iri, shard in by_iri.items() if resolve else ():
            jurisdiction = self._jurisdiction(shard.framework_id)
            if jurisdiction is None:
                result.unresolved_frameworks.setdefault(shard.framework_id, []).append(iri)
            elif "jurisdiction" in self.axes:
                groups[("jurisdiction", jurisdiction)].add(iri)
        for members in result.unresolved_frameworks.values():
            members.sort()
        result.shards_without_concepts.sort()
        order = {axis: n for n, axis in enumerate(CLUSTER_AXES)}
        result.clusters = sorted(
            (
                ShardCluster(axis, key, tuple(sorted(members)))
                for (axis, key), members in groups.items()
                if len(members) >= self.min_size
            ),
            key=lambda c: (order[c.axis], c.key),
        )
        return result

    def jurisdiction_of(self, framework_id: str) -> str | None:
        """The registered jurisdiction of ``framework_id`` (None if unknown)."""
        return self._jurisdiction(framework_id)

    # ── axes ──────────────────────────────────────────────────────────────

    def _jurisdiction(self, framework_id: str) -> str | None:
        if self.registry is None:
            return None
        framework = self.registry.get(framework_id)
        return None if framework is None else framework.jurisdiction

    @staticmethod
    def _tractarian_roots(
        by_iri: Mapping[str, ShardEnvelope],
    ) -> tuple[dict[str, str], list[tuple[str, ...]]]:
        """Map each shard to the root of its primary-parent chain.

        The primary parent is the first ``elaborates`` entry that names a shard
        in the corpus (out-of-corpus parents are ignored). A primary-parent
        loop has no root; its members root at the loop's smallest IRI and the
        loop is reported (the cycle guard belongs to the write path, not here).
        """
        parent: dict[str, str | None] = {}
        for iri, shard in by_iri.items():
            parent[iri] = next(
                (p for p in shard.elaborates if p in by_iri and p != iri), None
            )
        root_of: dict[str, str] = {}
        cycles: list[tuple[str, ...]] = []
        for start in sorted(by_iri):
            if start in root_of:
                continue
            chain: list[str] = []
            on_chain: dict[str, int] = {}
            node: str | None = start
            while node is not None and node not in root_of and node not in on_chain:
                on_chain[node] = len(chain)
                chain.append(node)
                node = parent[node]
            if node is None:
                root = chain[-1]
            elif node in root_of:
                root = root_of[node]
            else:  # a loop: chain[on_chain[node]:] is the cycle
                loop = chain[on_chain[node]:]
                root = min(loop)
                pivot = loop.index(root)
                cycles.append(tuple(loop[pivot:] + loop[:pivot]))
            for member in chain:
                root_of[member] = root
        return root_of, sorted(set(cycles))

    def _doctrinal_keys(self, concepts: Iterable[str]) -> set[str]:
        keys: set[str] = set()
        depth = self.doctrinal_depth
        for concept in concepts:
            for path in self._paths_from_root(concept):
                # path[0] is a root, path[-1] the concept itself.
                keys.add(path[depth] if len(path) > depth else concept)
        return keys

    def _paths_from_root(self, concept: str) -> tuple[tuple[str, ...], ...]:
        """Every root-to-``concept`` ancestry path (bounded, memoized)."""
        cached = self._root_paths.get(concept)
        if cached is not None:
            return cached
        resolver = self.folio_resolver
        complete: list[tuple[str, ...]] = []
        # Depth-first over upward paths; each partial path is concept-first.
        stack: list[tuple[str, ...]] = [(concept,)]
        while stack and len(complete) < MAX_ROOT_PATHS:
            path = stack.pop()
            head = path[-1]
            parents = [] if resolver is None else sorted(set(resolver.parents(head)))
            parents = [p for p in parents if p not in path]  # ignore ancestry loops
            if not parents or len(path) > MAX_ANCESTRY_DEPTH:
                complete.append(tuple(reversed(path)))
                continue
            for p in reversed(parents):
                stack.append((*path, p))
        result = tuple(sorted(complete))
        self._root_paths[concept] = result
        return result


__all__ = [
    "CLUSTER_AXES",
    "ClusterAxis",
    "ClusterBuilder",
    "ClusterSet",
    "DEFAULT_DOCTRINAL_DEPTH",
    "ShardCluster",
    "is_folio_concept",
    "shard_concepts",
]
