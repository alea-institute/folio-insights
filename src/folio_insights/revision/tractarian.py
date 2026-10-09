"""Tractarian path identifiers (drain U4, R12, KTD8; PHILOSOPHY.md Part IV).

"A Tractarian shard identifier is not a flat UUID; it is a path in a
dependency tree." Every shard of a corpus gets a decimal path (``1``, ``1.1``,
``1.2.3``) whose position encodes what the shard elaborates. The path is a
DISPLAY identifier shown alongside the content-hash URN; it never replaces the
URN, never enters the signed envelope and is never stored.

Derivation (pure, deterministic, recomputable from the journal; no sidecar)
-----------------------------------------------------------------------------
* **Primary parent.** ``elaborates[0]`` when it names another shard of the
  corpus; else ``depends_on_axioms[0]`` when it names another shard of the
  corpus; else the shard is a root (kernel shards and free-standing shards
  form the top level).
* **Ordinals.** Roots are numbered ``1..n`` and each parent's children
  ``<parent>.1..k`` by each shard's FIRST commit position (ties, possible only
  for hand-built entries, break by IRI). A new shard commits after every
  existing one, so it only ever appends an ordinal: existing paths do not
  renumber. A path moves only when its shard's primary parent changes (a
  content edit of ``elaborates`` / ``depends_on_axioms``, or a dangling
  parent that later arrives in the corpus); a revision that keeps the parent
  keeps the path, because ordinals follow the first revision, not the latest.
* **Findings, never errors.** A second or later ``elaborates`` entry
  (``extra_parent``: the tree is strict, the first one wins), a primary-parent
  candidate that is not a shard of the corpus (``dangling_parent``), and a
  legacy parent cycle (``parent_cycle``: the member that committed first is
  cut loose as a root) are reported on ``TractarianIndex.findings``.

``TractarianIndex`` answers ``path_of``, ``iri_of``, ``children`` and
``tree``. Build it from ``(shard, first_position)`` entries, or from a storage
context with ``await TractarianIndex.from_context(ctx)`` (one read of the
current shards and their first journal positions at one watermark).

Stdlib + Pydantic only, like the rest of ``revision/``.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from folio_insights.shards import ShardEnvelope
    from folio_insights.storage.context import CorpusStorageContext

ParentField = Literal["elaborates", "depends_on_axioms"]
FindingKind = Literal["extra_parent", "dangling_parent", "parent_cycle"]

_WHITE, _GRAY, _BLACK = 0, 1, 2


@dataclass(frozen=True)
class TractarianFinding:
    """Something the tree had to resolve: ``iri``'s ``field`` names ``target``."""

    kind: FindingKind
    iri: str
    target: str
    field: ParentField

    @property
    def detail(self) -> str:
        if self.kind == "extra_parent":
            return f"{self.iri} also elaborates {self.target}; its path follows elaborates[0]"
        if self.kind == "dangling_parent":
            return f"{self.iri} {self.field} {self.target}, which is not a shard of this corpus"
        return (
            f"{self.iri} is on a parent cycle through {self.target}; "
            "it is placed as a root"
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "iri": self.iri,
            "target": self.target,
            "field": self.field,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class TractarianNode:
    """One shard's place in the tree."""

    path: str
    iri: str
    first_position: int
    parent_iri: str | None
    parent_field: ParentField | None

    @property
    def depth(self) -> int:
        return self.path.count(".") + 1


class TractarianIndex:
    """The Tractarian tree of one corpus (see the module docstring)."""

    def __init__(self, entries: Iterable[tuple[ShardEnvelope, int]]) -> None:
        shards: dict[str, ShardEnvelope] = {}
        first: dict[str, int] = {}
        for shard, position in entries:
            iri = shard.shard_iri
            if iri in shards:
                raise ValueError(f"duplicate Tractarian entry for {iri!r}")
            shards[iri] = shard
            first[iri] = int(position)

        def order(iri: str) -> tuple[int, str]:
            return (first[iri], iri)

        findings: list[TractarianFinding] = []
        parent: dict[str, tuple[str, ParentField]] = {}
        for iri in sorted(shards, key=order):
            shard = shards[iri]
            chosen: tuple[str, ParentField] | None = None
            if shard.elaborates:
                head = shard.elaborates[0]
                if head in shards and head != iri:
                    chosen = (head, "elaborates")
                elif head != iri:
                    findings.append(TractarianFinding("dangling_parent", iri, head, "elaborates"))
                else:
                    findings.append(TractarianFinding("parent_cycle", iri, head, "elaborates"))
                for extra in dict.fromkeys(shard.elaborates[1:]):
                    if extra != head:
                        findings.append(TractarianFinding("extra_parent", iri, extra, "elaborates"))
            if chosen is None and shard.depends_on_axioms:
                head = shard.depends_on_axioms[0]
                if head in shards and head != iri:
                    chosen = (head, "depends_on_axioms")
                elif head != iri:
                    findings.append(
                        TractarianFinding("dangling_parent", iri, head, "depends_on_axioms")
                    )
                else:
                    findings.append(
                        TractarianFinding("parent_cycle", iri, head, "depends_on_axioms")
                    )
            if chosen is not None:
                parent[iri] = chosen

        # Legacy parent cycles: cut each at its first-committed member.
        color = dict.fromkeys(shards, _WHITE)
        for start in sorted(shards, key=order):
            if color[start] != _WHITE:
                continue
            trail: list[str] = []
            node: str | None = start
            while node is not None and color[node] == _WHITE:
                color[node] = _GRAY
                trail.append(node)
                link = parent.get(node)
                node = link[0] if link is not None else None
            if node is not None and color[node] == _GRAY:
                cycle = trail[trail.index(node):]
                cut = min(cycle, key=order)
                target, field = parent.pop(cut)
                findings.append(TractarianFinding("parent_cycle", cut, target, field))
            for member in trail:
                color[member] = _BLACK

        children: dict[str | None, list[str]] = {None: []}
        for iri in sorted(shards, key=order):
            link = parent.get(iri)
            children.setdefault(link[0] if link else None, []).append(iri)

        nodes: dict[str, TractarianNode] = {}
        by_path: dict[str, str] = {}
        stack: list[tuple[str | None, str]] = [(None, "")]
        while stack:
            owner, prefix = stack.pop()
            for ordinal, iri in enumerate(children.get(owner, ()), start=1):
                path = f"{prefix}{ordinal}"
                link = parent.get(iri)
                nodes[iri] = TractarianNode(
                    path=path,
                    iri=iri,
                    first_position=first[iri],
                    parent_iri=link[0] if link else None,
                    parent_field=link[1] if link else None,
                )
                by_path[path] = iri
                stack.append((iri, f"{path}."))

        self._nodes = nodes
        self._by_path = by_path
        self._children = children
        self.findings: tuple[TractarianFinding, ...] = tuple(findings)

    # ── construction ──────────────────────────────────────────────────────

    @classmethod
    async def from_context(cls, ctx: CorpusStorageContext) -> TractarianIndex:
        """The tree of the committed corpus behind a storage context."""
        return cls(await ctx.shards_in_commit_order())

    # ── reads ─────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, iri: object) -> bool:
        return iri in self._nodes

    def path_of(self, iri: str) -> str | None:
        """``iri``'s path, or ``None`` when it is not a shard of the corpus."""
        node = self._nodes.get(iri)
        return None if node is None else node.path

    def iri_of(self, path: str) -> str | None:
        """The shard IRI at ``path``, or ``None``."""
        return self._by_path.get(path)

    def node(self, iri: str) -> TractarianNode | None:
        return self._nodes.get(iri)

    def children(self, path: str | None = None) -> list[str]:
        """The child paths of ``path`` in ordinal order (``None``: the roots).
        Unknown paths have no children."""
        if path is None:
            owner = None
        else:
            owner = self._by_path.get(path)
            if owner is None:
                return []
        return [self._nodes[iri].path for iri in self._children.get(owner, ())]

    def nodes(self) -> Iterator[TractarianNode]:
        """Every node in depth-first path order (``1``, ``1.1``, ``1.1.1``,
        ``1.2``, ``2`` ...)."""
        stack = list(reversed(self._children.get(None, ())))
        while stack:
            iri = stack.pop()
            yield self._nodes[iri]
            stack.extend(reversed(self._children.get(iri, ())))

    def tree(self) -> list[dict[str, Any]]:
        """The nested tree as JSON-ready dicts: ``path``, ``iri``,
        ``parent_field`` and ``children`` (iteratively built, so a deep chain
        never hits the recursion limit)."""
        rendered: dict[str, dict[str, Any]] = {}
        roots: list[dict[str, Any]] = []
        for node in self.nodes():
            entry: dict[str, Any] = {
                "path": node.path,
                "iri": node.iri,
                "parent_field": node.parent_field,
                "children": [],
            }
            rendered[node.iri] = entry
            if node.parent_iri is None:
                roots.append(entry)
            else:
                rendered[node.parent_iri]["children"].append(entry)
        return roots


__all__ = [
    "FindingKind",
    "ParentField",
    "TractarianFinding",
    "TractarianIndex",
    "TractarianNode",
]
