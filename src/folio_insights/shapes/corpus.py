"""Corpus-tier SHACL: ``sh:sparql`` constraints run natively in pyoxigraph (KTD5).

Cross-shard rules (supersession alignment, reciprocity, back pointers) relate
two shards. They run as SPARQL over the corpus projection. Every write path
already keeps that projection current. They do not run over the
per-record rendering.

SHACL-SPARQL pre-binds ``$this`` to each focus node. Here each constraint is
rewritten once:

* ``$this`` becomes ``?this``;
* the owning shape's target (``targetClass``, ``targetSubjectsOf``,
  ``targetObjectsOf``, ``targetNode``) becomes a trailing ``FILTER EXISTS`` in
  the outer group, one query per target;
* an optional leading ``VALUES ?this { ... }`` restricts the run to given
  focus nodes (the incremental check after a write).

This relies on each constraint body binding ``$this`` in a triple pattern
(true of every shape in the suite; the differential tests run each one). A
body that only mentions ``$this`` inside a FILTER would need pre-binding.

Every solution row is one result. Its focus node is ``?this``, its value is
``?value`` when the query projects it, and its severity is the owning shape's.
Results agree with pyshacl's ``SPARQLConstraintComponent`` results; the
differential tests check this.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from pyoxigraph import BlankNode, Literal, NamedNode

from folio_insights.shapes.compiled import ShaclResult, SparqlConstraint
from folio_insights.shapes.rendering import Term

QueryFn = Callable[[str], list[dict[str, Any]]]

_THIS = re.compile(r"\$this\b")
_WHERE = re.compile(r"\bWHERE\s*\{", re.IGNORECASE)
_PREFIX_DECL = re.compile(r"\bPREFIX\s+([A-Za-z][\w.-]*)?:", re.IGNORECASE)
_MESSAGE_VAR = re.compile(r"\{[?$](\w+)\}")


def _target_filter(kind: str, value: Term) -> str:
    """The owning shape's target as a trailing ``FILTER EXISTS``.

    A filter applies to its whole group wherever it is written, so placing it
    last lets the constraint body (always selective here: it matches the bad
    case) drive the join instead of a scan of every target instance."""
    if kind == "targetClass":
        return f"FILTER EXISTS {{ ?this a <{value[1]}> }}"
    if kind == "targetSubjectsOf":
        return f"FILTER EXISTS {{ ?this <{value[1]}> ?__target }}"
    if kind == "targetObjectsOf":
        return f"FILTER EXISTS {{ ?__target <{value[1]}> ?this }}"
    if kind == "targetNode":
        return f"FILTER (?this = {_sparql_term(value)})"
    raise ValueError(f"unknown target kind {kind}")


def _sparql_term(term: Term) -> str:
    if term[0] == "I":
        return f"<{term[1]}>"
    if term[0] == "L":
        escaped = term[1].replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"^^<{term[2]}>'
    raise ValueError("blank nodes cannot be SPARQL focus nodes")


def rewrite(
    constraint: SparqlConstraint, kind: str, value: Term, focus: Sequence[str] | None = None
) -> str:
    """The executable SELECT for one constraint and one of its targets."""
    body = _THIS.sub("?this", constraint.select)
    declared = {m.group(1) or "" for m in _PREFIX_DECL.finditer(body)}
    prologue = "".join(
        f"PREFIX {prefix}: <{namespace}>\n"
        for prefix, namespace in constraint.prefixes
        if prefix not in declared
    )
    head = ""
    if focus is not None:
        head = " VALUES ?this { " + " ".join(f"<{iri}>" for iri in focus) + " } "
    tail = " " + _target_filter(kind, value) + " "
    match = _WHERE.search(body)
    start = match.end() if match is not None else body.index("{") + 1
    end = body.rindex("}")
    return prologue + body[:start] + head + body[start:end] + tail + body[end:]


def from_ox(term: Any) -> Term | None:
    if term is None:
        return None
    if isinstance(term, NamedNode):
        return ("I", term.value)
    if isinstance(term, BlankNode):
        return ("B", term.value)
    if isinstance(term, Literal):
        if term.language:
            return ("L", term.value, f"@{term.language}")
        return ("L", term.value, term.datatype.value)
    return None


def _message(template: str, row: dict[str, Any]) -> str:
    def sub(match: re.Match[str]) -> str:
        term = from_ox(row.get(match.group(1)))
        return term[1] if term is not None else match.group(0)

    return _MESSAGE_VAR.sub(sub, template)


def run_constraints(
    query: QueryFn,
    constraints: Iterable[SparqlConstraint],
    *,
    focus: Sequence[str] | None = None,
) -> list[ShaclResult]:
    """Run every corpus-tier constraint; ``focus`` limits the focus IRIs."""
    if focus is not None and not focus:
        return []
    seen: set[tuple[Any, ...]] = set()
    results: list[ShaclResult] = []
    for constraint in constraints:
        for kind, value in constraint.targets:
            for row in query(rewrite(constraint, kind, value, focus)):
                this = from_ox(row.get("this"))
                if this is None:
                    continue
                value_term = from_ox(row.get("value"))
                key = (constraint.shape, constraint.select, this, value_term)
                if key in seen:
                    continue
                seen.add(key)
                results.append(
                    ShaclResult(
                        focus=this,
                        path=None,
                        value=value_term,
                        component="SPARQLConstraintComponent",
                        severity=constraint.severity,
                        source_shape=constraint.shape,
                        messages=tuple(_message(m, row) for m in constraint.messages),
                    )
                )
    return results


def store_query(store: Any, **kwargs: Any) -> QueryFn:
    """A ``QueryFn`` over a pyoxigraph ``Store`` (tests and ad-hoc runs)."""

    def run(sparql: str) -> list[dict[str, Any]]:
        solutions = store.query(sparql, **kwargs)
        names = [v.value for v in solutions.variables]
        return [{name: sol[name] for name in names} for sol in solutions]

    return run


__all__ = ["QueryFn", "from_ox", "rewrite", "run_constraints", "store_query"]
