"""Compiled SHACL engine for the write path (Phase 11 KTD5).

Shape files are parsed with pyoxigraph (no rdflib) and compiled once into
Python objects. Validating a rendered shard is then dictionary lookups and
small closures, a few hundred microseconds rather than the roughly ten
milliseconds per shard that building an rdflib graph and running pyshacl
costs. That difference is what keeps the bulk load at or above 200K triples/s.

pyshacl is the reference: ``tests/shapes/test_compiled_differential.py``
requires both engines to agree (conformance, plus the set of focus node,
path, component and severity) on every fixture and on generated instances and
mutations.

Supported SHACL Core:

* **Targets:** ``sh:targetClass`` (with ``rdfs:subClassOf`` in the data),
  ``sh:targetSubjectsOf``, ``sh:targetObjectsOf`` and ``sh:targetNode``.
* **Shapes:** node and property shapes, with predicate paths only.
* **Components:** ``minCount``, ``maxCount``, ``datatype``, ``in``,
  ``hasValue``, ``pattern`` and ``flags``, ``minLength``, ``maxLength``,
  ``min/maxInclusive``, ``min/maxExclusive``, ``nodeKind``, ``class``,
  ``node``, ``not``, ``and``, ``or``, ``xone``, ``closed`` and
  ``ignoredProperties``, ``equals``, ``disjoint``, ``lessThan`` and
  ``lessThanOrEquals``.
* **Annotations:** ``severity``, ``message`` and ``deactivated``. Non-validating
  annotations such as ``name``, ``description``, ``order``, ``group`` and
  ``rdfs:comment`` are ignored.

``sh:sparql`` constraints are not evaluated here. They are collected as
corpus-tier constraints (``corpus.py``), which run over the projection. Any
other ``sh:`` term on a shape (complex property paths, ``sh:qualified*``,
``sh:languageIn`` and so on) raises ``UnsupportedShaclConstruct`` at compile
time, so the engine never silently skips a constraint it does not implement.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pyoxigraph import BlankNode, Literal, NamedNode, RdfFormat
from pyoxigraph import parse as rdf_parse

from folio_insights.shapes.fields import RDF_TYPE, XSD_STRING
from folio_insights.shapes.rendering import Term, ValidationGraph

SH = "http://www.w3.org/ns/shacl#"
RDFS_SUBCLASS = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
RDF_FIRST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#first"
RDF_REST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"
RDF_NIL = "http://www.w3.org/1999/02/22-rdf-syntax-ns#nil"
XSD = "http://www.w3.org/2001/XMLSchema#"

_EMPTY: list = []  # shared, never mutated

SEVERITIES = {f"{SH}Violation": "Violation", f"{SH}Warning": "Warning", f"{SH}Info": "Info"}

# sh: predicates a shape may carry that this engine evaluates or may ignore.
_EVALUATED = {
    "targetClass", "targetSubjectsOf", "targetObjectsOf", "targetNode",
    "property", "path", "minCount", "maxCount", "datatype", "in", "hasValue",
    "pattern", "flags", "minLength", "maxLength", "minInclusive", "maxInclusive",
    "minExclusive", "maxExclusive", "nodeKind", "class", "node", "not", "and",
    "or", "xone", "closed", "ignoredProperties", "equals", "disjoint",
    "lessThan", "lessThanOrEquals", "severity", "message", "deactivated",
    "sparql",
}
_IGNORED = {"name", "description", "order", "group", "defaultValue"}


class UnsupportedShaclConstruct(ValueError):
    """A shape uses SHACL the compiled engine does not implement."""


@dataclass(frozen=True)
class ShaclResult:
    focus: Term
    path: str | None
    value: Term | None
    component: str           # e.g. "MinCountConstraintComponent"
    severity: str            # "Violation" | "Warning" | "Info"
    source_shape: Term
    messages: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        return self.messages[0] if self.messages else self.component

    def as_dict(self) -> dict[str, Any]:
        return {
            "focus": term_text(self.focus),
            "path": self.path,
            "value": term_text(self.value) if self.value is not None else None,
            "component": self.component,
            "severity": self.severity,
            "source_shape": term_text(self.source_shape),
            "message": self.message,
        }


def term_text(term: Term) -> str:
    if term[0] == "I":
        return term[1]
    if term[0] == "B":
        return f"_:{term[1]}"
    return term[1] if term[2] == XSD_STRING else f'"{term[1]}"^^<{term[2]}>'


# ── shape-graph parsing (pyoxigraph) ──────────────────────────────────────


def _from_ox(term: Any, prefix: str) -> Term:
    if isinstance(term, NamedNode):
        return ("I", term.value)
    if isinstance(term, BlankNode):
        return ("B", f"{prefix}{term.value}")
    if isinstance(term, Literal):
        if term.language:
            return ("L", term.value, f"@{term.language}")
        return ("L", term.value, term.datatype.value)
    raise UnsupportedShaclConstruct(f"unsupported term in a shapes graph: {term!r}")


def load_triples(paths: Sequence[Path]) -> ValidationGraph:
    """Parse Turtle files into one ``ValidationGraph`` (blank nodes kept apart per file)."""
    g = ValidationGraph()
    for index, path in enumerate(paths):
        with open(path, "rb") as handle:
            for triple in rdf_parse(handle, format=RdfFormat.TURTLE):
                g.add(
                    _from_ox(triple.subject, f"f{index}_"),
                    triple.predicate.value,
                    _from_ox(triple.object, f"f{index}_"),
                )
    return g


def turtle_graph(text: str, *, prefix: str = "t") -> ValidationGraph:
    """A ``ValidationGraph`` from Turtle text (validating fork TTL and fixtures)."""
    g = ValidationGraph(bnode_prefix=f"{prefix}x")
    for triple in rdf_parse(text.encode("utf-8"), format=RdfFormat.TURTLE):
        g.add(_from_ox(triple.subject, prefix), triple.predicate.value, _from_ox(triple.object, prefix))
    return g


def _rdf_list(g: ValidationGraph, head: Term) -> list[Term]:
    out: list[Term] = []
    node = head
    seen = set()
    while node != ("I", RDF_NIL):
        if node in seen:
            raise UnsupportedShaclConstruct("cyclic rdf:List in shapes graph")
        seen.add(node)
        first = g.values(node, RDF_FIRST)
        rest = g.values(node, RDF_REST)
        if len(first) != 1 or len(rest) != 1:
            raise UnsupportedShaclConstruct("malformed rdf:List in shapes graph")
        out.append(first[0])
        node = rest[0]
    return out


# ── literal value semantics (mirrors rdflib's lexical conversion) ─────────

_NUMERIC = {f"{XSD}{t}" for t in (
    "integer", "int", "long", "short", "byte", "decimal", "double", "float",
    "nonNegativeInteger", "positiveInteger", "negativeInteger", "nonPositiveInteger",
    "unsignedInt", "unsignedLong", "unsignedShort", "unsignedByte",
)}
_INTEGER = {t for t in _NUMERIC if not t.endswith(("decimal", "double", "float"))}


def _bool(lexical: str) -> bool:
    if lexical in ("true", "1"):
        return True
    if lexical in ("false", "0"):
        return False
    raise ValueError(lexical)


def literal_value(term: Term) -> Any:
    """Python value of a literal, or raise ``ValueError`` when ill-typed."""
    lexical, datatype = term[1], term[2]
    if datatype in _INTEGER:
        return int(lexical)
    if datatype in _NUMERIC:
        return float(lexical)
    if datatype == f"{XSD}boolean":
        return _bool(lexical)
    if datatype == f"{XSD}dateTime":
        return datetime.fromisoformat(lexical)
    return lexical


_WELL_FORMED: dict[tuple[str, str], bool] = {}


def well_formed(term: Term) -> bool:
    key = (term[1], term[2])
    cached = _WELL_FORMED.get(key)
    if cached is None:
        try:
            literal_value(term)
            cached = True
        except (ValueError, TypeError, OverflowError):
            cached = False
        if len(_WELL_FORMED) < 100_000:
            _WELL_FORMED[key] = cached
    return cached


def _compare(a: Term, b: Term) -> int | None:
    """-1/0/1, or None when the two values are not comparable."""
    if a[0] != "L" or b[0] != "L":
        return None
    try:
        va, vb = literal_value(a), literal_value(b)
    except (ValueError, TypeError, OverflowError):
        return None
    numeric = (int, float)
    if isinstance(va, bool) or isinstance(vb, bool):
        if not (isinstance(va, bool) and isinstance(vb, bool)):
            return None
    elif isinstance(va, numeric) != isinstance(vb, numeric):
        return None
    try:
        return (va > vb) - (va < vb)
    except TypeError:
        return None


# ── compiled shapes ───────────────────────────────────────────────────────

# A check takes (engine, graph, focus, value nodes) and yields
# (component, value-or-None) for each failure.
Check = Callable[["CompiledSuite", ValidationGraph, Term, list[Term]], list[tuple[str, Term | None]]]


@dataclass
class Shape:
    key: Term
    path: str | None
    severity: str = "Violation"
    messages: tuple[str, ...] = ()
    deactivated: bool = False
    checks: list[Check] = field(default_factory=list)
    properties: list[Shape] = field(default_factory=list)
    sparql: list[Term] = field(default_factory=list)


@dataclass(frozen=True)
class SparqlConstraint:
    """One ``sh:sparql`` constraint, for the corpus tier (``corpus.py``)."""

    shape: Term
    targets: tuple[tuple[str, Term], ...]
    select: str
    prefixes: tuple[tuple[str, str], ...]
    severity: str
    messages: tuple[str, ...]


def _pattern_check(regex: re.Pattern[str]) -> Check:
    def check(_e, _g, _f, values):  # noqa: ANN001
        out = []
        for v in values:
            if v[0] == "B" or not regex.search(v[1]):
                out.append(("PatternConstraintComponent", v))
        return out
    return check


def _datatype_check(datatype: str) -> Check:
    plain_string = datatype == XSD_STRING

    def check(_e, _g, _f, values):  # noqa: ANN001
        out = []
        for v in values:
            if v[0] != "L" or v[2] != datatype or (not plain_string and not well_formed(v)):
                out.append(("DatatypeConstraintComponent", v))
        return out
    return check


def _count_check(n: int, minimum: bool) -> Check:
    component = "MinCountConstraintComponent" if minimum else "MaxCountConstraintComponent"

    def check(_e, _g, _f, values):  # noqa: ANN001
        bad = len(values) < n if minimum else len(values) > n
        return [(component, None)] if bad else []
    return check


def _in_check(allowed: frozenset[Term]) -> Check:
    def check(_e, _g, _f, values):  # noqa: ANN001
        return [("InConstraintComponent", v) for v in values if v not in allowed]
    return check


def _has_value_check(expected: Term) -> Check:
    def check(_e, _g, _f, values):  # noqa: ANN001
        return [] if expected in values else [("HasValueConstraintComponent", None)]
    return check


def _length_check(n: int, minimum: bool) -> Check:
    component = "MinLengthConstraintComponent" if minimum else "MaxLengthConstraintComponent"

    def check(_e, _g, _f, values):  # noqa: ANN001
        out = []
        for v in values:
            if v[0] == "B":
                out.append((component, v))
                continue
            size = len(v[1])
            if (size < n) if minimum else (size > n):
                out.append((component, v))
        return out
    return check


def _range_check(bound: Term, kind: str) -> Check:
    component = f"{kind[0].upper()}{kind[1:]}ConstraintComponent"
    ok = {
        "minInclusive": lambda c: c >= 0,
        "maxInclusive": lambda c: c <= 0,
        "minExclusive": lambda c: c > 0,
        "maxExclusive": lambda c: c < 0,
    }[kind]

    def check(_e, _g, _f, values):  # noqa: ANN001
        out = []
        for v in values:
            cmp = _compare(v, bound)
            if cmp is None or not ok(cmp):
                out.append((component, v))
        return out
    return check


_NODE_KINDS = {
    f"{SH}IRI": {"I"},
    f"{SH}BlankNode": {"B"},
    f"{SH}Literal": {"L"},
    f"{SH}BlankNodeOrIRI": {"B", "I"},
    f"{SH}BlankNodeOrLiteral": {"B", "L"},
    f"{SH}IRIOrLiteral": {"I", "L"},
}


def _node_kind_check(kinds: set[str]) -> Check:
    def check(_e, _g, _f, values):  # noqa: ANN001
        return [("NodeKindConstraintComponent", v) for v in values if v[0] not in kinds]
    return check


def _class_check(class_iri: str) -> Check:
    def check(engine, g, _f, values):  # noqa: ANN001
        return [
            ("ClassConstraintComponent", v)
            for v in values
            if v[0] == "L" or not engine.is_instance(g, v, class_iri)
        ]
    return check


def _shape_check(component: str, members: list[Shape], mode: str) -> Check:
    def check(engine, g, _f, values):  # noqa: ANN001
        out = []
        for v in values:
            passed = [engine.conforms(g, v, shape) for shape in members]
            if mode == "node" or mode == "and":
                bad = not all(passed)
            elif mode == "not":
                bad = passed[0]
            elif mode == "or":
                bad = not any(passed)
            else:  # xone
                bad = sum(passed) != 1
            if bad:
                out.append((component, v))
        return out
    return check


def _pair_check(other: str, kind: str) -> Check:
    component = f"{kind[0].upper()}{kind[1:]}ConstraintComponent"

    def check(_e, g, focus, values):  # noqa: ANN001
        others = g.values(focus, other)
        out = []
        if kind == "equals":
            out.extend((component, v) for v in values if v not in others)
            out.extend((component, o) for o in others if o not in values)
        elif kind == "disjoint":
            out.extend((component, v) for v in values if v in others)
        else:
            for v in values:
                for o in others:
                    cmp = _compare(v, o)
                    if cmp is None or (cmp >= 0 if kind == "lessThan" else cmp > 0):
                        out.append((component, v))
        return out
    return check


class CompiledSuite:
    """Compiled local-tier shapes plus the collected corpus-tier constraints."""

    def __init__(self, paths: Sequence[Path]) -> None:
        self.paths = tuple(paths)
        self._g = load_triples(self.paths)
        self._compiled: dict[Term, Shape] = {}
        self.targets: list[tuple[str, Term, Shape]] = []
        self.sparql: list[SparqlConstraint] = []
        self._compile_all()

    # ── compilation ──
    def _one(self, node: Term, key: str) -> Term | None:
        values = self._g.values(node, f"{SH}{key}")
        if len(values) > 1:
            raise UnsupportedShaclConstruct(f"sh:{key} has {len(values)} values on {node}")
        return values[0] if values else None

    def _int(self, node: Term, key: str) -> int | None:
        value = self._one(node, key)
        if value is None:
            return None
        if value[0] != "L":
            raise UnsupportedShaclConstruct(f"sh:{key} must be a literal")
        return int(value[1])

    def _shape_nodes(self) -> list[Term]:
        nodes: list[Term] = []
        for s, props in self._g.nodes.items():
            types = props.get(RDF_TYPE, ())
            if (
                ("I", f"{SH}NodeShape") in types
                or ("I", f"{SH}PropertyShape") in types
                or any(f"{SH}{t}" in props for t in ("targetClass", "targetSubjectsOf", "targetObjectsOf", "targetNode"))
            ):
                nodes.append(s)
        return nodes

    def _compile_all(self) -> None:
        for node in self._shape_nodes():
            shape = self.compile(node)
            for kind in ("targetClass", "targetSubjectsOf", "targetObjectsOf", "targetNode"):
                for value in self._g.values(node, f"{SH}{kind}"):
                    self.targets.append((kind, value, shape))
        targetted = {id(s) for _, _, s in self.targets}
        for node, shape in self._compiled.items():
            if shape.sparql and id(shape) not in targetted:
                raise UnsupportedShaclConstruct(f"sh:sparql on an untargeted shape {node}")

    def compile(self, node: Term) -> Shape:
        cached = self._compiled.get(node)
        if cached is not None:
            return cached
        props = self._g.nodes.get(node, {})
        for predicate in props:
            if predicate.startswith(SH):
                local = predicate[len(SH):]
                if local not in _EVALUATED and local not in _IGNORED:
                    raise UnsupportedShaclConstruct(f"sh:{local} is not supported (shape {node})")
        if ("I", "http://www.w3.org/2000/01/rdf-schema#Class") in props.get(RDF_TYPE, ()):
            raise UnsupportedShaclConstruct(f"implicit class target on {node} is not supported")
        path_term = self._one(node, "path")
        if path_term is not None and path_term[0] != "I":
            raise UnsupportedShaclConstruct(f"complex property path on {node} is not supported")
        severity_term = self._one(node, "severity")
        severity = "Violation"
        if severity_term is not None:
            severity = SEVERITIES.get(severity_term[1], "")
            if not severity:
                raise UnsupportedShaclConstruct(f"unknown severity {severity_term}")
        messages = tuple(m[1] for m in self._g.values(node, f"{SH}message"))
        deactivated = self._one(node, "deactivated")
        shape = Shape(
            key=node,
            path=path_term[1] if path_term is not None else None,
            severity=severity,
            messages=messages,
            deactivated=deactivated is not None and deactivated[1] == "true",
        )
        self._compiled[node] = shape  # before recursion (guards sh:node cycles)
        self._compile_constraints(node, shape)
        return shape

    def _compile_constraints(self, node: Term, shape: Shape) -> None:
        g = self._g
        checks = shape.checks
        for key, minimum in (("minCount", True), ("maxCount", False)):
            n = self._int(node, key)
            if n is not None:
                if shape.path is None:
                    raise UnsupportedShaclConstruct(f"sh:{key} on a node shape {node}")
                checks.append(_count_check(n, minimum))
        datatype = self._one(node, "datatype")
        if datatype is not None:
            checks.append(_datatype_check(datatype[1]))
        node_kind = self._one(node, "nodeKind")
        if node_kind is not None:
            kinds = _NODE_KINDS.get(node_kind[1])
            if kinds is None:
                raise UnsupportedShaclConstruct(f"unknown sh:nodeKind {node_kind}")
            checks.append(_node_kind_check(kinds))
        for class_term in g.values(node, f"{SH}class"):
            checks.append(_class_check(class_term[1]))
        in_list = self._one(node, "in")
        if in_list is not None:
            checks.append(_in_check(frozenset(_rdf_list(g, in_list))))
        for expected in g.values(node, f"{SH}hasValue"):
            checks.append(_has_value_check(expected))
        flags_term = self._one(node, "flags")
        for pattern in g.values(node, f"{SH}pattern"):
            flags = 0
            for flag in (flags_term[1] if flags_term else ""):
                flags |= {"i": re.I, "m": re.M, "s": re.S, "x": re.X}[flag]
            checks.append(_pattern_check(re.compile(pattern[1], flags)))
        for key, minimum in (("minLength", True), ("maxLength", False)):
            n = self._int(node, key)
            if n is not None:
                checks.append(_length_check(n, minimum))
        for kind in ("minInclusive", "maxInclusive", "minExclusive", "maxExclusive"):
            bound = self._one(node, kind)
            if bound is not None:
                checks.append(_range_check(bound, kind))
        for kind in ("equals", "disjoint", "lessThan", "lessThanOrEquals"):
            for other in g.values(node, f"{SH}{kind}"):
                if shape.path is None:
                    raise UnsupportedShaclConstruct(f"sh:{kind} on a node shape {node}")
                checks.append(_pair_check(other[1], kind))
        for ref in g.values(node, f"{SH}node"):
            checks.append(_shape_check("NodeConstraintComponent", [self.compile(ref)], "node"))
        for ref in g.values(node, f"{SH}not"):
            checks.append(_shape_check("NotConstraintComponent", [self.compile(ref)], "not"))
        for key, mode in (("and", "and"), ("or", "or"), ("xone", "xone")):
            for head in g.values(node, f"{SH}{key}"):
                members = [self.compile(m) for m in _rdf_list(g, head)]
                checks.append(
                    _shape_check(f"{key[0].upper()}{key[1:]}ConstraintComponent", members, mode)
                )
        closed = self._one(node, "closed")
        if closed is not None and closed[1] == "true":
            allowed = {
                p[1]
                for prop in g.values(node, f"{SH}property")
                for p in g.values(prop, f"{SH}path")
                if p[0] == "I"
            }
            ignored = self._one(node, "ignoredProperties")
            if ignored is not None:
                allowed.update(t[1] for t in _rdf_list(g, ignored))
            frozen_allowed = frozenset(allowed)

            def closed_check(_e, graph, _f, values):  # noqa: ANN001
                out = []
                for v in values:
                    for predicate, objects in graph.nodes.get(v, {}).items():
                        if predicate not in frozen_allowed:
                            out.extend(("ClosedConstraintComponent", (predicate, o)) for o in objects)
                return out

            checks.append(closed_check)
        for prop in g.values(node, f"{SH}property"):
            shape.properties.append(self.compile(prop))
        shape.sparql.extend(g.values(node, f"{SH}sparql"))
        if shape.sparql:
            if shape.path is not None:
                raise UnsupportedShaclConstruct(f"sh:sparql on a property shape {node}")
            targets = tuple(
                (kind, value)
                for kind in ("targetClass", "targetSubjectsOf", "targetObjectsOf", "targetNode")
                for value in g.values(node, f"{SH}{kind}")
            )
            for constraint in shape.sparql:
                select = self._one(constraint, "select")
                if select is None:
                    raise UnsupportedShaclConstruct(f"sh:sparql without sh:select on {node}")
                messages = tuple(m[1] for m in g.values(constraint, f"{SH}message")) or shape.messages
                self.sparql.append(
                    SparqlConstraint(
                        shape=node,
                        targets=targets,
                        select=select[1],
                        prefixes=tuple(self._prefixes(constraint)),
                        severity=shape.severity,
                        messages=messages,
                    )
                )

    def _prefixes(self, constraint: Term) -> list[tuple[str, str]]:
        out = []
        for ontology in self._g.values(constraint, f"{SH}prefixes"):
            for decl in self._g.values(ontology, f"{SH}declare"):
                prefix = self._one(decl, "prefix")
                namespace = self._one(decl, "namespace")
                if prefix is not None and namespace is not None:
                    out.append((prefix[1], namespace[1]))
        return sorted(set(out))

    # ── evaluation ──
    def is_instance(self, g: ValidationGraph, node: Term, class_iri: str) -> bool:
        types = list(g.values(node, RDF_TYPE))
        seen: set[Term] = set()
        while types:
            t = types.pop()
            if t == ("I", class_iri):
                return True
            if t in seen:
                continue
            seen.add(t)
            types.extend(g.values(t, RDFS_SUBCLASS))
        return False

    def focus_nodes(self, g: ValidationGraph, kind: str, value: Term) -> list[Term]:
        if kind == "targetNode":
            return [value]
        if kind == "targetSubjectsOf":
            return g.subjects_with(value[1])
        if kind == "targetObjectsOf":
            seen: dict[Term, None] = {}
            for s, props in g.nodes.items():
                for o in props.get(value[1], ()):
                    seen[o] = None
            return list(seen)
        # targetClass (with rdfs:subClassOf in the data graph)
        return [s for s in g.nodes if self.is_instance(g, s, value[1])]

    def validate_shape(self, g: ValidationGraph, focus: Term, shape: Shape) -> list[ShaclResult]:
        if shape.deactivated:
            return []
        if shape.path is not None:
            props = g.nodes.get(focus)
            values = props.get(shape.path, _EMPTY) if props is not None else _EMPTY
        else:
            values = [focus]
        results: list[ShaclResult] = []
        for check in shape.checks:
            failures = check(self, g, focus, values)
            if not failures:
                continue
            for component, value in failures:
                path = shape.path
                if component == "ClosedConstraintComponent":
                    path, value = value  # type: ignore[misc]
                results.append(
                    ShaclResult(
                        focus=focus,
                        path=path,
                        value=value,
                        component=component,
                        severity=shape.severity,
                        source_shape=shape.key,
                        messages=shape.messages,
                    )
                )
        for prop in shape.properties:
            for v in values:
                results.extend(self.validate_shape(g, v, prop))
        return results

    def conforms(self, g: ValidationGraph, focus: Term, shape: Shape) -> bool:
        """Short-circuit conformance (no result objects): the hot path of
        sh:node / sh:not / sh:and / sh:or / sh:xone members."""
        if shape.deactivated:
            return True
        if shape.path is not None:
            props = g.nodes.get(focus)
            values = props.get(shape.path, _EMPTY) if props is not None else _EMPTY
        else:
            values = [focus]
        for check in shape.checks:
            if check(self, g, focus, values):
                return False
        for prop in shape.properties:
            for v in values:
                if not self.conforms(g, v, prop):
                    return False
        return True

    def validate(
        self, g: ValidationGraph, *, focus: Iterable[Term] | None = None
    ) -> list[ShaclResult]:
        """Validate every target (or only targets within ``focus``)."""
        wanted = set(focus) if focus is not None else None
        # One pass builds the class index the targetClass lookups need; with
        # rdfs:subClassOf in the data the slower closure path is used instead.
        by_class: dict[str, list[Term]] | None = {}
        for s, props in g.nodes.items():
            if RDFS_SUBCLASS in props:
                by_class = None
                break
            for t in props.get(RDF_TYPE, ()):
                by_class.setdefault(t[1], []).append(s)
        results: list[ShaclResult] = []
        for kind, value, shape in self.targets:
            if kind == "targetClass" and by_class is not None:
                nodes = by_class.get(value[1], ())
            else:
                nodes = self.focus_nodes(g, kind, value)
            for node in nodes:
                if wanted is None or node in wanted:
                    results.extend(self.validate_shape(g, node, shape))
        return results


def dumps_results(results: Iterable[ShaclResult]) -> str:
    return json.dumps([r.as_dict() for r in results], indent=2, sort_keys=True)


__all__ = [
    "CompiledSuite",
    "ShaclResult",
    "Shape",
    "SparqlConstraint",
    "UnsupportedShaclConstruct",
    "dumps_results",
    "literal_value",
    "load_triples",
    "term_text",
    "turtle_graph",
    "well_formed",
]
