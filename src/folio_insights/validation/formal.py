"""A cluster's formal content, as ground triples and an OWL document (Phase 9 U1, KTD4).

Shards carry propositions as text plus typed links, not as full OWL axioms,
so the reasoner sees only the part of a shard that is formal:

* its ``triple`` when subject, predicate and object are all IRIs and the
  object is not a typed literal — ``rdf:type`` becomes a class assertion,
  ``rdfs:subClassOf`` / ``owl:disjointWith`` / ``owl:equivalentClass`` class
  axioms, anything else an object-property assertion;
* its dependency edges (``depends_on_*``, ``elaborates``) as ``fi:`` object
  property assertions between shard individuals. They give the reasoner the
  web of the cluster but never make a cluster "formal" on their own.

Around that the checker adds the cluster's TBox slice (``tbox_slice``: the
TBox triples reachable from the cluster's terms) and the caller's
``owl:disjointWith`` seeds. ``owl_ntriples`` renders the lot, with the OWL
declarations HermiT needs, as an N-Triples document.

Pure stdlib; safe for the web tier (only ``validation.hermit`` reasons).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from folio_insights.vocab._constants import FI_PREFIX

if TYPE_CHECKING:
    from folio_insights.shards import ShardEnvelope

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
RDF_TYPE = f"{RDF}type"
RDFS_SUBCLASS_OF = f"{RDFS}subClassOf"
OWL_DISJOINT_WITH = f"{OWL}disjointWith"
OWL_EQUIVALENT_CLASS = f"{OWL}equivalentClass"
OWL_CLASS = f"{OWL}Class"
OWL_NAMED_INDIVIDUAL = f"{OWL}NamedIndividual"
OWL_OBJECT_PROPERTY = f"{OWL}ObjectProperty"
OWL_ONTOLOGY = f"{OWL}Ontology"
OWL_THING = f"{OWL}Thing"
OWL_NOTHING = f"{OWL}Nothing"

CLASS_AXIOM_PREDICATES = frozenset({RDFS_SUBCLASS_OF, OWL_DISJOINT_WITH, OWL_EQUIVALENT_CLASS})
SYMMETRIC_PREDICATES = frozenset({OWL_DISJOINT_WITH, OWL_EQUIVALENT_CLASS})

# Envelope dependency fields -> the fi: predicate the projection writes.
DEPENDENCY_PREDICATES: dict[str, str] = {
    "depends_on_axioms": f"{FI_PREFIX}dependsOnAxiom",
    "depends_on_definitions": f"{FI_PREFIX}dependsOnDefinition",
    "depends_on_precedents": f"{FI_PREFIX}dependsOnPrecedent",
    "depends_on_shards": f"{FI_PREFIX}dependsOnShard",
    "elaborates": f"{FI_PREFIX}elaborates",
}

Triple3 = tuple[str, str, str]

# An absolute IRI: a scheme, a colon, and no character N-Triples forbids.
_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>\"{}|\\^`]+$")
_BNODE = re.compile(r"^_:[A-Za-z0-9_][A-Za-z0-9_.\-]*$")


@dataclass(frozen=True)
class FormalVerdict:
    """A reasoner's verdict on one set of formal triples: whether the ontology
    is consistent, and the IRIs of the named classes it makes unsatisfiable."""

    consistent: bool
    unsatisfiable: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class FormalReasoner(Protocol):
    """Consistency and class satisfiability over ground triples. HermiT
    (``validation.hermit``) implements it in the worker tier."""

    @property
    def name(self) -> str: ...

    def check(self, triples: Sequence[Triple3]) -> FormalVerdict: ...


def is_iri(term: object) -> bool:
    """True for an absolute IRI that N-Triples can carry unescaped."""
    return isinstance(term, str) and bool(_IRI.match(term)) and not term.startswith("_:")


def _is_node(term: str) -> bool:
    return is_iri(term) or bool(_BNODE.match(term))


def shard_axioms(shard: ShardEnvelope) -> tuple[Triple3, ...]:
    """The formal triple a shard asserts (empty when its triple is not formal)."""
    t = shard.triple
    if t.object_datatype is None and is_iri(t.subject) and is_iri(t.predicate) and is_iri(t.object):
        return ((t.subject, t.predicate, t.object),)
    return ()


def dependency_axioms(shard: ShardEnvelope) -> tuple[Triple3, ...]:
    """The shard's dependency edges as ``fi:`` object-property assertions."""
    out: list[Triple3] = []
    if not is_iri(shard.shard_iri):
        return ()
    for name, predicate in DEPENDENCY_PREDICATES.items():
        for target in getattr(shard, name):
            if target != shard.shard_iri and is_iri(target):
                out.append((shard.shard_iri, predicate, target))
    return tuple(out)


def tbox_slice(tbox: Iterable[Triple3], terms: Iterable[str], *, max_rounds: int = 16) -> list[Triple3]:
    """The TBox triples relevant to ``terms``: every triple whose subject is a
    relevant term (or whose object is, for a symmetric class axiom), closed
    over the terms those triples introduce (bounded by ``max_rounds``).

    Triples with a literal object (labels, comments, datatype facets) are
    dropped: the slice is the IRI / blank-node skeleton the cluster needs."""
    tbox = [
        t for t in tbox
        if len(t) == 3 and _is_node(t[0]) and is_iri(t[1]) and _is_node(t[2])
    ]
    relevant = set(terms)
    picked: set[Triple3] = set()
    for _ in range(max_rounds):
        grew = False
        for s, p, o in tbox:
            if (s, p, o) in picked:
                continue
            if s in relevant or (p in SYMMETRIC_PREDICATES and o in relevant):
                picked.add((s, p, o))
                for term in (s, o):
                    if term not in relevant:
                        relevant.add(term)
                        grew = True
        if not grew:
            break
    return sorted(picked)


def terms_of(triples: Iterable[Triple3]) -> set[str]:
    out: set[str] = set()
    for s, p, o in triples:
        out.update((s, p, o))
    return out


def _nt_term(term: str) -> str:
    if _BNODE.match(term):
        return term
    if not is_iri(term):
        raise ValueError(f"not an IRI or blank node: {term!r}")
    return f"<{term}>"


def _declarations(triples: Sequence[Triple3]) -> set[Triple3]:
    """OWL 2 declarations so HermiT reads every term with the intended type."""
    decls: set[Triple3] = set()
    for s, p, o in triples:
        if p == RDF_TYPE:
            if o in {OWL_CLASS, OWL_NAMED_INDIVIDUAL, OWL_OBJECT_PROPERTY, OWL_ONTOLOGY}:
                continue
            if is_iri(s):
                decls.add((s, RDF_TYPE, OWL_NAMED_INDIVIDUAL))
            if is_iri(o) and o not in {OWL_THING, OWL_NOTHING}:
                decls.add((o, RDF_TYPE, OWL_CLASS))
        elif p in CLASS_AXIOM_PREDICATES:
            for term in (s, o):
                if is_iri(term) and term not in {OWL_THING, OWL_NOTHING}:
                    decls.add((term, RDF_TYPE, OWL_CLASS))
        elif p.startswith((RDF, RDFS, OWL)):
            continue  # TBox vocabulary (domain, range, restrictions, lists ...)
        elif is_iri(s) and is_iri(o):
            decls.add((p, RDF_TYPE, OWL_OBJECT_PROPERTY))
            decls.add((s, RDF_TYPE, OWL_NAMED_INDIVIDUAL))
            decls.add((o, RDF_TYPE, OWL_NAMED_INDIVIDUAL))
    return decls


def owl_ntriples(triples: Iterable[Triple3], *, ontology_iri: str) -> str:
    """An N-Triples OWL document: an ontology header, declarations, then the
    triples (sorted, so the same content always yields the same bytes)."""
    body = sorted(set(triples))
    lines = [f"{_nt_term(ontology_iri)} <{RDF_TYPE}> <{OWL_ONTOLOGY}> ."]
    for s, p, o in sorted(_declarations(body) | set(body)):
        if not _is_node(o):
            raise ValueError(f"formal content must be IRIs or blank nodes; got object {o!r}")
        lines.append(f"{_nt_term(s)} {_nt_term(p)} {_nt_term(o)} .")
    return "\n".join(lines) + "\n"


__all__ = [
    "CLASS_AXIOM_PREDICATES",
    "DEPENDENCY_PREDICATES",
    "FormalReasoner",
    "FormalVerdict",
    "OWL_DISJOINT_WITH",
    "RDFS_SUBCLASS_OF",
    "RDF_TYPE",
    "Triple3",
    "dependency_axioms",
    "is_iri",
    "owl_ntriples",
    "shard_axioms",
    "tbox_slice",
    "terms_of",
]
