"""Flat proposition references behind the former Tractarian navigation interface.

References are the frozen shard IRIs, independent of commit order, logical
relationships and revision history. Legacy parent fields remain readable in
historical records; they never determine navigation or become typed links.
The interface names remain for the graph CLI and API's existing payload shape.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from folio_insights.shards import ShardEnvelope
    from folio_insights.storage.context import CorpusStorageContext


@dataclass(frozen=True)
class TractarianRevision:
    """Historical parent metadata from one committed revision, never traversed."""

    position: int
    iri: str
    elaborates: tuple[str, ...]
    depends_on_axioms: tuple[str, ...]
    batch: str | None = None

    @classmethod
    def of(cls, shard: ShardEnvelope, position: int, batch: str | None = None,
           ) -> TractarianRevision:
        hierarchy = getattr(shard, "legacy_hierarchy", None)
        elaborates = hierarchy.elaborates if hierarchy else tuple(shard.elaborates)
        return cls(int(position), shard.shard_iri, elaborates,
                   tuple(shard.depends_on_axioms), batch)

    @classmethod
    def from_payload(cls, position: int, iri: str, payload: bytes | str | Mapping[str, Any],
                     batch: str | None = None) -> TractarianRevision:
        """Read original or migrated historical metadata without model validation."""
        record = payload if isinstance(payload, Mapping) else json.loads(payload)

        def heads(value: Any) -> tuple[str, ...]:
            if not isinstance(value, (list, tuple)):
                return ()
            return tuple(v for v in value if isinstance(v, str))

        hierarchy = record.get("legacy_hierarchy")
        elaborates = (hierarchy.get("elaborates") if isinstance(hierarchy, Mapping)
                      else record.get("elaborates"))
        return cls(int(position), iri, heads(elaborates),
                   heads(record.get("depends_on_axioms")), batch)


@dataclass(frozen=True)
class TractarianNode:
    """A flat reference; parent fields stay empty for payload compatibility."""

    path: str
    iri: str
    first_position: int
    parent_iri: None = None
    parent_field: None = None

    @property
    def depth(self) -> int:
        return 1


class TractarianIndex:
    """Flat navigation over stable proposition IRIs, in first-commit order."""

    def __init__(
        self,
        entries: Iterable[tuple[ShardEnvelope, int]],
        revisions: Iterable[TractarianRevision] | None = None,
    ) -> None:
        nodes: dict[str, TractarianNode] = {}
        for shard, position in entries:
            iri = shard.shard_iri
            if iri in nodes:
                raise ValueError(f"duplicate proposition entry for {iri!r}")
            nodes[iri] = TractarianNode(iri, iri, int(position))
        if revisions is not None:
            first: dict[str, int] = {}
            for rev in sorted(revisions, key=lambda r: (r.position, r.iri)):
                first.setdefault(rev.iri, rev.position)
            if first != {iri: node.first_position for iri, node in nodes.items()}:
                raise ValueError("the revision history does not match the entries")
        self._nodes = dict(sorted(nodes.items(), key=lambda item: (
            item[1].first_position, item[0],
        )))
        self.findings: tuple[()] = ()

    @classmethod
    async def from_context(cls, ctx: CorpusStorageContext) -> TractarianIndex:
        entries = await ctx.shards_in_commit_order()
        return cls(entries)

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, iri: object) -> bool:
        return iri in self._nodes

    def path_of(self, iri: str) -> str | None:
        """The frozen IRI, or None for a proposition outside this corpus."""
        return iri if iri in self._nodes else None

    def iri_of(self, path: str) -> str | None:
        return self.path_of(path)

    def node(self, iri: str) -> TractarianNode | None:
        return self._nodes.get(iri)

    def children(self, path: str | None = None) -> list[str]:
        """All flat references at the root; propositions have no children."""
        return list(self._nodes) if path is None else []

    def nodes(self) -> Iterator[TractarianNode]:
        return iter(self._nodes.values())

    def tree(self) -> list[dict[str, Any]]:
        """Flat entries in the existing graph response shape."""
        return [
            {"path": n.iri, "iri": n.iri, "parent_field": None, "children": []}
            for n in self.nodes()
        ]


__all__ = ["TractarianIndex", "TractarianNode", "TractarianRevision"]
