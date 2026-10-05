"""pyshacl adapter: the reference SHACL engine (Phase 11 KTD6).

rdflib and pyshacl are imported ONLY here (and by the older per-domain
validators that already owned them). Every graph built is in-memory; nothing
is written to an RDF store through rdflib (STORAGE-02 / KTD6 of Phase 13).
The storage write path never imports this module: it uses the compiled
engine (``compiled.py``), which this module is the oracle for.

Used by ``POST /validate``, by ``storage validate --engine pyshacl`` and by the
differential tests.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import pyshacl
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, SH

from folio_insights.shapes.fields import XSD_STRING as _XSD_STRING
from folio_insights.shapes.rendering import Term, ValidationGraph


def to_rdflib(graph: ValidationGraph, *, into: Graph | None = None) -> Graph:
    g = into if into is not None else Graph()
    for s, p, o in graph.triples():
        g.add((_term(s), URIRef(p), _term(o)))
    return g


def _term(term: Term) -> Any:
    kind = term[0]
    if kind == "I":
        return URIRef(term[1])
    if kind == "B":
        return BNode(term[1])
    if term[2] == _XSD_STRING:
        # RDF 1.1: "x" and "x"^^xsd:string are one term, but rdflib compares
        # them unequal (sh:in, sh:hasValue). Shapes write plain strings.
        return Literal(term[1])
    return Literal(term[1], datatype=URIRef(term[2]))


def term_key(node: Any) -> Term:
    """An rdflib node as a rendering term (for comparing results)."""
    if isinstance(node, URIRef):
        return ("I", str(node))
    if isinstance(node, BNode):
        return ("B", str(node))
    if isinstance(node, Literal):
        if node.language:
            return ("L", str(node), f"@{node.language}")
        return ("L", str(node), str(node.datatype) if node.datatype else _XSD_STRING)
    raise TypeError(f"unexpected rdflib node {node!r}")


@cache
def _shapes_graph(paths: tuple[Path, ...], drop_sparql: bool) -> Graph:
    g = Graph()
    for path in paths:
        g.parse(str(path), format="turtle")
    if drop_sparql:
        # The local tier (what an isolated candidate can be checked against):
        # remove the sh:sparql constraints, which need the corpus.
        for shape, constraint in list(g.subject_objects(SH.sparql)):
            g.remove((shape, SH.sparql, constraint))
    return g


@dataclass
class PyshaclResult:
    conforms: bool
    results: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""


def validate(
    data: ValidationGraph | Graph,
    shape_paths: Iterable[Path],
    *,
    local_only: bool = True,
) -> PyshaclResult:
    """Run pyshacl (no inference) and return its report as plain data.

    ``local_only`` drops ``sh:sparql`` constraints (corpus-tier shapes).
    """
    shapes = _shapes_graph(tuple(sorted(Path(p) for p in shape_paths)), local_only)
    data_graph = to_rdflib(data) if isinstance(data, ValidationGraph) else data
    conforms, report, text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
        allow_warnings=True,
    )
    results = []
    # Top-level results only: pyshacl also types the nested sh:detail
    # results of sh:node / logical constraints as sh:ValidationResult.
    top_level = [
        result
        for node in report.subjects(RDF.type, SH.ValidationReport)
        for result in report.objects(node, SH.result)
    ]
    for result in top_level:
        focus = report.value(result, SH.focusNode)
        path = report.value(result, SH.resultPath)
        value = report.value(result, SH.value)
        results.append(
            {
                "focus": term_key(focus) if focus is not None else None,
                "path": str(path) if isinstance(path, URIRef) else None,
                "component": str(report.value(result, SH.sourceConstraintComponent)),
                "severity": str(report.value(result, SH.resultSeverity)),
                "message": [str(m) for m in report.objects(result, SH.resultMessage)],
                "value": term_key(value) if value is not None else None,
                "source_shape": report.value(result, SH.sourceShape),
            }
        )
    return PyshaclResult(conforms=bool(conforms), results=results, text=text)


__all__ = ["PyshaclResult", "term_key", "to_rdflib", "validate"]
