"""Pure-Python OWL 2 EL profile check over a TBox graph (Phase 9 U4, KTD5).

ELK needs the Java OWL API, which has no maintained Python binding, so the
profile is enforced syntactically: every OWL construct in the TBox's RDF
mapping is checked against the OWL 2 EL restrictions (OWL 2 Profiles, 2nd
edition, section 2). A violation names the axiom's triples and the EL
constraint it breaks. HermiT stays the reasoner for both profiles behind the
``Reasoner`` protocol (``reason/reasoner.py``).

Flagged (not in OWL 2 EL):

* inverse object properties (``owl:inverseOf``);
* functional object properties, inverse-functional, symmetric, asymmetric and
  irreflexive properties, and disjoint properties;
* universal restrictions (``owl:allValuesFrom``), every cardinality
  restriction (EL has none, so 0 and 1 are flagged too), disjunction
  (``owl:unionOf``, ``owl:disjointUnionOf``), negation (``owl:complementOf``,
  ``owl:datatypeComplementOf``), enumerations of more than one individual,
  and datatype facet restrictions (``owl:withRestrictions``);
* datatypes outside the OWL 2 EL datatype map used as a range or filler
  (``xsd:boolean``, ``xsd:double``, ``xsd:float``, the sized integers, ...).

Allowed constructs (``owl:intersectionOf``, ``owl:someValuesFrom``,
``owl:hasValue``, ``owl:hasSelf``, ``owl:oneOf`` with one member,
``owl:disjointWith``, ``owl:equivalentClass``, sub-properties, property chains,
transitive and reflexive properties, functional data properties, ``owl:hasKey``,
domains and ranges) pass. Triples in other vocabularies (SHACL shapes, labels,
comments) are not OWL axioms and are ignored.

Pure stdlib: terms are taken as N-Triples strings (``str()`` of a pyoxigraph
term), so this module imports no RDF library and no JVM.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

OWL = "http://www.w3.org/2002/07/owl#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
XSD = "http://www.w3.org/2001/XMLSchema#"

_TYPE = f"<{RDF}type>"
_FIRST = f"<{RDF}first>"
_REST = f"<{RDF}rest>"
_NIL = f"<{RDF}nil>"


def _iri(ns: str, local: str) -> str:
    return f"<{ns}{local}>"


# The OWL 2 EL datatype map (OWL 2 Profiles §2.2.1).
EL_DATATYPES: frozenset[str] = frozenset(
    {
        _iri(RDF, "PlainLiteral"),
        _iri(RDF, "XMLLiteral"),
        _iri(RDFS, "Literal"),
        _iri(OWL, "real"),
        _iri(OWL, "rational"),
        *(
            _iri(XSD, local)
            for local in (
                "decimal",
                "integer",
                "nonNegativeInteger",
                "string",
                "normalizedString",
                "token",
                "Name",
                "NCName",
                "NMTOKEN",
                "hexBinary",
                "base64Binary",
                "anyURI",
                "dateTime",
                "dateTimeStamp",
            )
        ),
    }
)

# Property characteristics EL has no counterpart for (by rdf:type).
_FORBIDDEN_PROPERTY_TYPES: dict[str, tuple[str, str]] = {
    _iri(OWL, "InverseFunctionalProperty"): (
        "inverse-functional-property",
        "OWL 2 EL has no inverse-functional object properties",
    ),
    _iri(OWL, "SymmetricProperty"): (
        "symmetric-property",
        "OWL 2 EL has no symmetric object properties",
    ),
    _iri(OWL, "AsymmetricProperty"): (
        "asymmetric-property",
        "OWL 2 EL has no asymmetric object properties",
    ),
    _iri(OWL, "IrreflexiveProperty"): (
        "irreflexive-property",
        "OWL 2 EL has no irreflexive object properties",
    ),
    _iri(OWL, "AllDisjointProperties"): (
        "disjoint-properties",
        "OWL 2 EL has no disjoint properties",
    ),
}

# Constructs forbidden wherever they appear (by predicate).
_FORBIDDEN_PREDICATES: dict[str, tuple[str, str]] = {
    _iri(OWL, "inverseOf"): (
        "inverse-object-property",
        "OWL 2 EL has no inverse object properties (owl:inverseOf)",
    ),
    _iri(OWL, "propertyDisjointWith"): (
        "disjoint-properties",
        "OWL 2 EL has no disjoint properties",
    ),
    _iri(OWL, "allValuesFrom"): (
        "universal-restriction",
        "OWL 2 EL has no universal quantification (owl:allValuesFrom)",
    ),
    _iri(OWL, "unionOf"): (
        "disjunction",
        "OWL 2 EL has no disjunction (owl:unionOf)",
    ),
    _iri(OWL, "disjointUnionOf"): (
        "disjunction",
        "OWL 2 EL has no disjoint unions (owl:disjointUnionOf)",
    ),
    _iri(OWL, "complementOf"): (
        "negation",
        "OWL 2 EL has no class negation (owl:complementOf)",
    ),
    _iri(OWL, "datatypeComplementOf"): (
        "negation",
        "OWL 2 EL has no data range complement (owl:datatypeComplementOf)",
    ),
    _iri(OWL, "withRestrictions"): (
        "datatype-restriction",
        "OWL 2 EL has no datatype facet restrictions (owl:withRestrictions)",
    ),
    **{
        _iri(OWL, local): (
            "cardinality-restriction",
            f"OWL 2 EL has no cardinality restrictions (owl:{local})",
        )
        for local in (
            "cardinality",
            "minCardinality",
            "maxCardinality",
            "qualifiedCardinality",
            "minQualifiedCardinality",
            "maxQualifiedCardinality",
        )
    },
}

# Where a datatype IRI names a data range the profile must support.
_DATA_RANGE_PREDICATES: frozenset[str] = frozenset(
    {
        _iri(RDFS, "range"),
        _iri(OWL, "someValuesFrom"),
        _iri(OWL, "onDatatype"),
        _iri(OWL, "equivalentClass"),
    }
)
_RDF_DATATYPES: frozenset[str] = frozenset(
    _iri(RDF, local)
    for local in ("PlainLiteral", "XMLLiteral", "langString", "HTML", "JSON",
                  "CompoundLiteral", "dirLangString")
)


@dataclass(frozen=True)
class ELViolation:
    """One TBox axiom outside OWL 2 EL.

    ``rule`` is a short stable identifier, ``constraint`` the EL restriction
    broken, ``subject`` the axiom's subject (N-Triples term) and ``triples``
    the axiom's triples (N-Triples lines, the offending triple first).
    """

    rule: str
    constraint: str
    subject: str
    triples: tuple[str, ...]

    def describe(self) -> str:
        return f"{self.constraint}: {self.triples[0]}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "constraint": self.constraint,
            "subject": self.subject,
            "triples": list(self.triples),
        }


def _term(value: Any) -> str:
    """N-Triples form of a term (pyoxigraph terms already print that way)."""
    n3 = getattr(value, "n3", None)
    if callable(n3):  # rdflib term
        return n3()
    return str(value)


def _triples(source: Iterable[Any]) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for item in source:
        if hasattr(item, "subject") and hasattr(item, "predicate"):
            s, p, o = item.subject, item.predicate, item.object
        else:
            s, p, o = item
        out.append((_term(s), _term(p), _term(o)))
    return out


def _line(t: tuple[str, str, str]) -> str:
    return f"{t[0]} {t[1]} {t[2]} ."


def _is_datatype(term: str) -> bool:
    return (
        term.startswith(f"<{XSD}")
        or term in _RDF_DATATYPES
        or term in {_iri(RDFS, "Literal"), _iri(OWL, "real"), _iri(OWL, "rational")}
    )


def check_el_profile(triples: Iterable[Any]) -> list[ELViolation]:
    """Every OWL 2 EL violation in ``triples`` (pyoxigraph quads/triples,
    rdflib triples, or N-Triples string 3-tuples), deterministically ordered."""
    graph = _triples(triples)
    by_subject: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    types: dict[str, set[str]] = defaultdict(set)
    for t in graph:
        by_subject[t[0]].append(t)
        if t[1] == _TYPE:
            types[t[0]].add(t[2])

    def axiom(t: tuple[str, str, str]) -> tuple[str, ...]:
        """The offending triple, then the rest of an anonymous subject's triples."""
        lines = [_line(t)]
        if t[0].startswith("_:"):
            lines.extend(_line(x) for x in sorted(by_subject[t[0]]) if x != t)
        return tuple(lines)

    def list_length(node: str) -> int:
        n, seen = 0, set()
        while node != _NIL and node not in seen:
            seen.add(node)
            firsts = [x for x in by_subject[node] if x[1] == _FIRST]
            rests = [x for x in by_subject[node] if x[1] == _REST]
            if not firsts or not rests:
                break
            n += 1
            node = rests[0][2]
        return n

    data_properties = {s for s, ts in types.items() if _iri(OWL, "DatatypeProperty") in ts}
    out: list[ELViolation] = []
    for t in sorted(set(graph)):
        s, p, o = t
        if p == _TYPE and o in _FORBIDDEN_PROPERTY_TYPES:
            rule, constraint = _FORBIDDEN_PROPERTY_TYPES[o]
            out.append(ELViolation(rule, constraint, s, axiom(t)))
        elif p == _TYPE and o == _iri(OWL, "FunctionalProperty") and s not in data_properties:
            out.append(
                ELViolation(
                    "functional-object-property",
                    "OWL 2 EL has functional data properties only, no functional object properties",
                    s,
                    axiom(t),
                )
            )
        elif p in _FORBIDDEN_PREDICATES:
            rule, constraint = _FORBIDDEN_PREDICATES[p]
            out.append(ELViolation(rule, constraint, s, axiom(t)))
        elif p == _iri(OWL, "oneOf") and list_length(o) > 1:
            out.append(
                ELViolation(
                    "enumeration",
                    "OWL 2 EL enumerations (owl:oneOf) may name only one individual",
                    s,
                    axiom(t),
                )
            )
        elif p in _DATA_RANGE_PREDICATES and _is_datatype(o) and o not in EL_DATATYPES:
            out.append(
                ELViolation(
                    "datatype-outside-el",
                    f"datatype {o} is not in the OWL 2 EL datatype map",
                    s,
                    axiom(t),
                )
            )
    return out


def format_violations(violations: Iterable[ELViolation], *, limit: int = 10) -> str:
    """A short multi-line description naming each axiom and its constraint."""
    items = list(violations)
    lines = [f"- {v.describe()}" for v in items[:limit]]
    if len(items) > limit:
        lines.append(f"- ... and {len(items) - limit} more")
    return "\n".join(lines)


__all__ = [
    "EL_DATATYPES",
    "ELViolation",
    "check_el_profile",
    "format_violations",
]
