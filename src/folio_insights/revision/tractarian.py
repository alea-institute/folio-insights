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
  form the top level). "Of the corpus" is judged at each point of the
  history: a dangling parent becomes the primary parent from the moment it is
  committed.
* **Sticky ordinals.** The journal is replayed in commit order, and for every
  parent (the root level counts as one) the index records the position at
  which each shard FIRST had that parent. A shard's ordinal under a parent is
  the rank of that position among every shard that has EVER had that parent
  (ties, within one batch, break by the shards' first commit positions, then
  by IRI). So:

  - a new child only ever appends an ordinal;
  - a shard that leaves a parent (a content edit of ``elaborates`` /
    ``depends_on_axioms``, or a dangling parent that later arrives) vacates
    its ordinal: the path becomes a gap that no other shard ever takes;
  - a shard returning to a former parent gets its old ordinal back;
  - every other shard keeps its path. A path changes only when the shard's
    own primary parent, or an ancestor's, changes; a revision that keeps the
    parent keeps the path.

  A batch (journal rows of one ``ingest_shards`` call) is one event: a child
  written before its parent in the same batch is never a root.
* **Findings, never errors.** A second or later ``elaborates`` entry
  (``extra_parent``: the tree is strict, the first one wins), a primary-parent
  candidate that is not a shard of the corpus (``dangling_parent``), and a
  legacy parent cycle (``parent_cycle``) are reported on
  ``TractarianIndex.findings``. A cycle is cut when it closes during the
  replay, at its first-committed member, which is placed as a root (with the
  sticky root ordinal of that moment) until the cycle is broken.

``TractarianIndex`` answers ``path_of``, ``iri_of``, ``children`` and
``tree``. Build it from storage with ``await TractarianIndex.from_context(ctx)``
(the current shards, their first journal positions and every revision's
parent fields, at one watermark), or from ``(shard, first_position)`` entries
plus an optional ``revisions`` history of ``TractarianRevision`` records.
Without ``revisions`` the entries stand for a history in which each shard was
committed once, at its first position, in its current form, each in its own
event.

Stdlib + Pydantic only, like the rest of ``revision/``.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from folio_insights.shards import ShardEnvelope
    from folio_insights.storage.context import CorpusStorageContext

ParentField = Literal["elaborates", "depends_on_axioms"]
FindingKind = Literal["extra_parent", "dangling_parent", "parent_cycle"]

_Link = tuple[str, ParentField]


@dataclass(frozen=True)
class TractarianRevision:
    """One committed revision's parent fields, as the replay needs them.

    ``batch`` groups consecutive journal rows written by one operation into one
    event (``None``: an event of its own)."""

    position: int
    iri: str
    elaborates: tuple[str, ...]
    depends_on_axioms: tuple[str, ...]
    batch: str | None = None

    @classmethod
    def of(cls, shard: ShardEnvelope, position: int, batch: str | None = None,
           ) -> TractarianRevision:
        return cls(int(position), shard.shard_iri, tuple(shard.elaborates),
                   tuple(shard.depends_on_axioms), batch)

    @classmethod
    def from_payload(cls, position: int, iri: str, payload: bytes | str | Mapping[str, Any],
                     batch: str | None = None) -> TractarianRevision:
        """From a journal payload (the current-version record JSON), without model
        validation; a missing or malformed field reads empty."""
        record = payload if isinstance(payload, Mapping) else json.loads(payload)

        def heads(name: str) -> tuple[str, ...]:
            values = record.get(name)
            if not isinstance(values, list):
                return ()
            return tuple(v for v in values if isinstance(v, str))

        return cls(int(position), iri, heads("elaborates"), heads("depends_on_axioms"), batch)

    def candidates(self) -> tuple[_Link, ...]:
        """The primary-parent candidates in priority order (self-references dropped)."""
        out: list[_Link] = []
        if self.elaborates and self.elaborates[0] != self.iri:
            out.append((self.elaborates[0], "elaborates"))
        if self.depends_on_axioms and self.depends_on_axioms[0] != self.iri:
            out.append((self.depends_on_axioms[0], "depends_on_axioms"))
        return tuple(out)


def _events(revisions: Sequence[TractarianRevision]) -> list[list[TractarianRevision]]:
    """Revisions in commit order, grouped into events (one batch = one event)."""
    events: list[list[TractarianRevision]] = []
    for rev in sorted(revisions, key=lambda r: (r.position, r.iri)):
        if events and rev.batch is not None and events[-1][-1].batch == rev.batch:
            events[-1].append(rev)
        else:
            events.append([rev])
    return events


class _Replay:
    """Replays revision events, maintaining each shard's effective primary parent
    (kept acyclic: a closing cycle is cut) and the position at which each shard
    first had each parent."""

    def __init__(self, first: Mapping[str, int]) -> None:
        self.first = first
        self.candidates: dict[str, tuple[_Link, ...]] = {}
        self.arrived: set[str] = set()
        self.waiting: dict[str, set[str]] = {}
        self.parent: dict[str, _Link | None] = {}
        self.cut: dict[str, _Link] = {}  # cycle members placed as roots -> their link
        self.since: dict[tuple[str | None, str], int] = {}

    def order(self, iri: str) -> tuple[int, str]:
        return (self.first[iri], iri)

    def _resolve(self, iri: str) -> _Link | None:
        for link in self.candidates.get(iri, ()):
            if link[0] in self.arrived:
                return link
        return None

    def _path_up(self, start: str, goal: str) -> list[str] | None:
        """The effective-parent walk from ``start`` until ``goal`` (``None`` if the
        walk reaches a root first)."""
        trail: list[str] = []
        node: str | None = start
        while node is not None:
            if node == goal:
                return trail
            trail.append(node)
            link = self.parent.get(node)
            node = link[0] if link is not None else None
        return None

    def _set(self, iri: str, link: _Link | None, position: int) -> None:
        self.parent[iri] = link
        self.since.setdefault((link[0] if link is not None else None, iri), position)

    def _place(self, iri: str, position: int) -> None:
        self.cut.pop(iri, None)
        link = self._resolve(iri)
        if link is not None:
            loop = self._path_up(link[0], iri)
            if loop is not None:  # this link would close a parent cycle: cut it
                victim = min([iri, *loop], key=self.order)
                if victim == iri:
                    self.cut[iri] = link
                    self._set(iri, None, position)
                    return
                victim_link = self.parent[victim]
                assert victim_link is not None
                self.cut[victim] = victim_link
                self._set(victim, None, position)
        self._set(iri, link, position)

    def apply(self, event: list[TractarianRevision]) -> None:
        position = event[0].position
        touched: list[str] = []
        for rev in event:
            self.candidates[rev.iri] = rev.candidates()
            for target, _field in self.candidates[rev.iri]:
                if target not in self.arrived:
                    self.waiting.setdefault(target, set()).add(rev.iri)
            touched.append(rev.iri)
        for rev in event:
            if rev.iri not in self.arrived:
                self.arrived.add(rev.iri)
                touched.extend(self.waiting.pop(rev.iri, ()))
        for iri in sorted(set(touched), key=self.order):
            self._place(iri, position)
        # A cut member rejoins its parent once its cycle no longer closes.
        for iri in sorted(self.cut, key=self.order):
            link = self._resolve(iri)
            if link is None or self._path_up(link[0], iri) is None:
                del self.cut[iri]
                self._set(iri, link, position)
            else:
                self.cut[iri] = link

    def ordinals(self) -> dict[tuple[str | None, str], int]:
        """``(parent, shard) -> ordinal`` over every shard that ever had the parent."""
        members: dict[str | None, list[tuple[int, int, str]]] = {}
        for (owner, iri), position in self.since.items():
            members.setdefault(owner, []).append((position, self.first[iri], iri))
        out: dict[tuple[str | None, str], int] = {}
        for owner, ranked in members.items():
            for ordinal, (_position, _first, iri) in enumerate(sorted(ranked), start=1):
                out[(owner, iri)] = ordinal
        return out


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

    def __init__(
        self,
        entries: Iterable[tuple[ShardEnvelope, int]],
        revisions: Iterable[TractarianRevision] | None = None,
    ) -> None:
        shards: dict[str, ShardEnvelope] = {}
        first: dict[str, int] = {}
        for shard, position in entries:
            iri = shard.shard_iri
            if iri in shards:
                raise ValueError(f"duplicate Tractarian entry for {iri!r}")
            shards[iri] = shard
            first[iri] = int(position)
        if revisions is None:
            history = [TractarianRevision.of(s, first[iri]) for iri, s in shards.items()]
        else:
            history = list(revisions)
            _check_history(shards, first, history)

        def order(iri: str) -> tuple[int, str]:
            return (first[iri], iri)

        findings: list[TractarianFinding] = []
        for iri in sorted(shards, key=order):
            shard = shards[iri]
            resolved = False
            if shard.elaborates:
                head = shard.elaborates[0]
                if head in shards and head != iri:
                    resolved = True
                elif head != iri:
                    findings.append(TractarianFinding("dangling_parent", iri, head, "elaborates"))
                else:
                    findings.append(TractarianFinding("parent_cycle", iri, head, "elaborates"))
                for extra in dict.fromkeys(shard.elaborates[1:]):
                    if extra != head:
                        findings.append(TractarianFinding("extra_parent", iri, extra, "elaborates"))
            if not resolved and shard.depends_on_axioms:
                head = shard.depends_on_axioms[0]
                if head not in shards:
                    findings.append(
                        TractarianFinding("dangling_parent", iri, head, "depends_on_axioms")
                    )
                elif head == iri:
                    findings.append(
                        TractarianFinding("parent_cycle", iri, head, "depends_on_axioms")
                    )

        replay = _Replay(first)
        for event in _events(history):
            replay.apply(event)
        for iri in sorted(replay.cut, key=order):
            target, field = replay.cut[iri]
            findings.append(TractarianFinding("parent_cycle", iri, target, field))
        parent: dict[str, _Link] = {
            iri: link for iri, link in replay.parent.items() if link is not None
        }
        ordinal = replay.ordinals()

        children: dict[str | None, list[str]] = {None: []}
        for iri in shards:
            link = parent.get(iri)
            children.setdefault(link[0] if link else None, []).append(iri)
        for owner, kids in children.items():
            kids.sort(key=lambda iri, owner=owner: ordinal[(owner, iri)])

        nodes: dict[str, TractarianNode] = {}
        by_path: dict[str, str] = {}
        stack: list[tuple[str | None, str]] = [(None, "")]
        while stack:
            owner, prefix = stack.pop()
            for iri in children.get(owner, ()):
                path = f"{prefix}{ordinal[(owner, iri)]}"
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
        """The tree of the committed corpus behind a storage context (its current
        shards and full revision history, read at one watermark)."""
        entries, rows = await ctx.shard_revision_history()
        return cls(entries, [
            TractarianRevision.from_payload(row.position, row.iri, row.payload, row.batch)
            for row in rows
        ])

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


def _check_history(
    shards: Mapping[str, ShardEnvelope],
    first: Mapping[str, int],
    history: Sequence[TractarianRevision],
) -> None:
    """The revision history must be the entries' history: the same shards, each
    first committed at its entry's position, the latest revision carrying the
    entry's parent fields."""
    seen: dict[str, int] = {}
    latest: dict[str, TractarianRevision] = {}
    for rev in sorted(history, key=lambda r: (r.position, r.iri)):
        seen.setdefault(rev.iri, rev.position)
        latest[rev.iri] = rev
    if seen != dict(first):
        missing = sorted(set(first) - set(seen))[:3]
        extra = sorted(set(seen) - set(first))[:3]
        moved = sorted(i for i in set(first) & set(seen) if first[i] != seen[i])[:3]
        raise ValueError(
            "the revision history does not match the entries "
            f"(missing {missing}, unknown {extra}, first position differs {moved})"
        )
    for iri, shard in shards.items():
        rev = latest[iri]
        if (rev.elaborates, rev.depends_on_axioms) != (
            tuple(shard.elaborates), tuple(shard.depends_on_axioms)
        ):
            raise ValueError(f"the latest revision of {iri!r} does not match its entry")


__all__ = [
    "FindingKind",
    "ParentField",
    "TractarianFinding",
    "TractarianIndex",
    "TractarianNode",
    "TractarianRevision",
]
