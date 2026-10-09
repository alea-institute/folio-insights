"""Cross-reference check: shards citing shards in incompatible frameworks
(Phase 9 U1, R4).

Carnap's lesson (PRD §8 P2): a proposition means what it means inside its
linguistic framework. A shard that rests on a shard from another framework
imports that framework's meaning postulates without saying so. The
``CrossReferenceChecker`` walks every citation edge whose both ends are in the
corpus and classifies the two frameworks through the corpus registry:

* **compatible** (no finding): the same framework; one framework an ancestor
  of the other in the registry's ``parent`` chain; the same jurisdiction; or
  a pair the caller explicitly allows.
* ``nested_jurisdiction`` (``info``): one jurisdiction contains the other
  (``us`` and ``us.louisiana``). Often legitimate, sometimes the classic
  civil-law / common-law crossing; the reviewer decides.
* ``unrelated_jurisdiction`` (``warning``): neither contains the other.
* ``unregistered`` (``warning``): either framework is not in the registry.

Citation edges are the ``depends_on_precedents``, ``depends_on_definitions``
and ``depends_on_shards`` lists plus ``elaborates``. ``depends_on_axioms`` is
excluded by default: kernel axioms (the regulae iuris) are framework-neutral
common axioms that every framework may rest on. Edges to IRIs outside the
corpus are not checked here.

Pure stdlib + Pydantic; safe for the web tier.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal

from folio_insights.validation.proposals import propose_for_citation
from folio_insights.validation.report import Finding, finding_id

if TYPE_CHECKING:
    from folio_insights.models.framework import Framework, FrameworkRegistry
    from folio_insights.shards import ShardEnvelope

CITATION_FIELDS: tuple[str, ...] = (
    "depends_on_precedents",
    "depends_on_definitions",
    "depends_on_shards",
    "elaborates",
)
ALL_CITATION_FIELDS: tuple[str, ...] = (*CITATION_FIELDS, "depends_on_axioms")

Relation = Literal[
    "same_framework",
    "framework_lineage",
    "same_jurisdiction",
    "allowed_pair",
    "nested_jurisdiction",
    "unrelated_jurisdiction",
    "unregistered",
]
COMPATIBLE: frozenset[str] = frozenset(
    {"same_framework", "framework_lineage", "same_jurisdiction", "allowed_pair"}
)


def _lineage(registry: FrameworkRegistry, framework: Framework) -> list[str]:
    """``framework``'s ID and every ancestor ID (bounded against bad data)."""
    out: list[str] = []
    node: Framework | None = framework
    while node is not None and node.id not in out and len(out) < 64:
        out.append(node.id)
        node = registry.get(node.parent) if node.parent else None
    return out


def _contains(outer: str, inner: str) -> bool:
    return inner.startswith(outer + ".")


class CrossReferenceChecker:
    """Flag citations between shards in incompatible frameworks."""

    def __init__(
        self,
        registry: FrameworkRegistry | None,
        *,
        fields: Iterable[str] = CITATION_FIELDS,
        allowed_pairs: Iterable[tuple[str, str]] = (),
    ) -> None:
        fields = tuple(fields)
        unknown = [f for f in fields if f not in ALL_CITATION_FIELDS]
        if unknown:
            raise ValueError(f"unknown citation fields {unknown}; expected {ALL_CITATION_FIELDS}")
        self.registry = registry
        self.fields = fields
        # Allowed pairs are symmetric: allowing (a, b) allows (b, a).
        self.allowed_pairs = frozenset(
            frozenset(pair) for pair in allowed_pairs if len(set(pair)) == 2
        )

    def relation(self, citing_id: str, cited_id: str) -> Relation:
        """How framework ``citing_id`` relates to framework ``cited_id``."""
        if citing_id == cited_id:
            return "same_framework"
        if frozenset((citing_id, cited_id)) in self.allowed_pairs:
            return "allowed_pair"
        registry = self.registry
        citing = registry.get(citing_id) if registry is not None else None
        cited = registry.get(cited_id) if registry is not None else None
        if citing is None or cited is None or registry is None:
            return "unregistered"
        if cited_id in _lineage(registry, citing) or citing_id in _lineage(registry, cited):
            return "framework_lineage"
        if citing.jurisdiction == cited.jurisdiction:
            return "same_jurisdiction"
        if _contains(citing.jurisdiction, cited.jurisdiction) or _contains(
            cited.jurisdiction, citing.jurisdiction
        ):
            return "nested_jurisdiction"
        return "unrelated_jurisdiction"

    def check(self, shards: Iterable[ShardEnvelope]) -> list[Finding]:
        """One finding per incompatible (citing, cited) pair, ordered by ID."""
        by_iri = {s.shard_iri: s for s in shards}
        found: dict[str, Finding] = {}
        for iri in sorted(by_iri):
            citing = by_iri[iri]
            edges: dict[str, list[str]] = {}
            for field in self.fields:
                for target in getattr(citing, field):
                    if target in by_iri and target != iri:
                        edges.setdefault(target, []).append(field)
            for target, via in sorted(edges.items()):
                cited = by_iri[target]
                relation = self.relation(citing.framework_id, cited.framework_id)
                if relation in COMPATIBLE:
                    continue
                fid = finding_id("cross_framework_citation", "crossref", [iri, target],
                                 {"citing": iri})
                found[fid] = Finding(
                    id=fid,
                    kind="cross_framework_citation",
                    checker="crossref",
                    severity="info" if relation == "nested_jurisdiction" else "warning",
                    shards=[iri, target],
                    summary=(
                        f"{iri} ({citing.framework_id}) cites {target} "
                        f"({cited.framework_id}) via {', '.join(via)}: {relation.replace('_', ' ')}."
                    ),
                    detail={
                        "citing": iri,
                        "cited": target,
                        "fields": via,
                        "citing_framework": citing.framework_id,
                        "cited_framework": cited.framework_id,
                        "citing_jurisdiction": self._jurisdiction(citing.framework_id),
                        "cited_jurisdiction": self._jurisdiction(cited.framework_id),
                        "relation": relation,
                    },
                    proposals=propose_for_citation(citing, cited, relation=relation),
                )
        return [found[k] for k in sorted(found, key=lambda k: (found[k].shards, k))]

    def _jurisdiction(self, framework_id: str) -> str | None:
        if self.registry is None:
            return None
        framework = self.registry.get(framework_id)
        return None if framework is None else framework.jurisdiction


__all__ = [
    "ALL_CITATION_FIELDS",
    "CITATION_FIELDS",
    "COMPATIBLE",
    "CrossReferenceChecker",
    "Relation",
]
