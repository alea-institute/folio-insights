"""A told-axiom ``SubsumptionReasoner`` over one TBox graph (Phase 9 U6, KTD10).

``StructuralReasoner`` answers class subsumption and disjointness from the
axioms a TBox graph states, closed under ``rdfs:subClassOf``:

* ``A ⊑ B`` holds when an ``rdfs:subClassOf`` chain (length 0 or more) leads
  from ``A`` to ``B``;
* ``A`` and ``B`` are disjoint when some superclass of ``A`` (``A`` itself
  included) is stated ``owl:disjointWith`` some superclass of ``B``, in either
  direction.

That is sound for the OWL 2 EL fragment the shared TBox keeps to (KTD5), but
not complete: entailments that need equivalence, intersections or
existentials are HermiT's job (``reason.reasoner.HermitReasoner``, worker tier).
The polysemy detector's Rule 1 needs only told disjointness, which this
answers, and it runs in the web tier: pyoxigraph only, no JVM.

It reads triples by pattern (``quads_for_pattern``) rather than SPARQL, so a
class IRI is never spliced into query text: no injection, and no false SEC-01
``SERVICE`` refusal for a term such as "service" inside an IRI.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pyoxigraph import NamedNode

from folio_insights.reason.reasoner import SubsumptionResult

if TYPE_CHECKING:
    from folio_insights.store.pyoxigraph_store import PyoxigraphStore

OWL_DISJOINT_WITH = "http://www.w3.org/2002/07/owl#disjointWith"
RDFS_SUBCLASS_OF = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
# Bound on the superclass walk: a pathological TBox cannot make one question unbounded.
MAX_SUPERCLASSES = 10_000


class StructuralReasoner:
    """Told-axiom subsumption and disjointness over ``graph`` in ``store``."""

    name = "structural"

    def __init__(self, store: PyoxigraphStore, graph: str) -> None:
        self.store = store
        self.graph = NamedNode(graph)

    def _objects(self, subject: str, predicate: str) -> list[str]:
        quads = self.store.store.quads_for_pattern(
            NamedNode(subject), NamedNode(predicate), None, self.graph
        )
        return sorted(q.object.value for q in quads if isinstance(q.object, NamedNode))

    def superclasses(self, cls: str) -> list[str]:
        """``cls`` and every told superclass of it (sorted)."""
        seen = {cls}
        frontier = [cls]
        while frontier and len(seen) < MAX_SUPERCLASSES:
            node = frontier.pop()
            for parent in self._objects(node, RDFS_SUBCLASS_OF):
                if parent not in seen:
                    seen.add(parent)
                    frontier.append(parent)
        return sorted(seen)

    def is_subclass_of(self, sub: str, sup: str) -> SubsumptionResult:
        return SubsumptionResult(
            relation="subclass_of",
            left=sub,
            right=sup,
            holds=sup in self.superclasses(sub),
            reasoner=self.name,
        )

    def are_disjoint(self, left: str, right: str) -> SubsumptionResult:
        left_up, right_up = self.superclasses(left), set(self.superclasses(right))
        left_set = set(left_up)
        evidence: list[tuple[str, str, str]] = []
        for x in left_up:
            evidence += [(x, OWL_DISJOINT_WITH, y) for y in self._objects(x, OWL_DISJOINT_WITH)
                         if y in right_up]
        for y in sorted(right_up):
            evidence += [(y, OWL_DISJOINT_WITH, x) for x in self._objects(y, OWL_DISJOINT_WITH)
                         if x in left_set]
        unique = tuple(sorted(set(evidence)))
        return SubsumptionResult(
            relation="disjoint_with",
            left=left,
            right=right,
            holds=bool(unique),
            reasoner=self.name,
            evidence=unique,
        )


__all__ = ["MAX_SUPERCLASSES", "OWL_DISJOINT_WITH", "RDFS_SUBCLASS_OF", "StructuralReasoner"]
