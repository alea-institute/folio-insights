"""Full-fidelity validation rendering of shard records (Phase 11 KTD2).

The Phase 13 projection is the Gate-2 query layout and deliberately drops
most envelope fields, the subtype fields and every nested model, so SHACL
over the projection alone could never be "full". This module renders a
shard's JSON mapping, every field included, into a small ``ValidationGraph``
that the compiled engine (``compiled.py``) and the pyshacl adapter
(``pyshacl_adapter.py``) both validate.

Mapping (from the same ``fields.model_spec`` walk the generator uses):

* the shard node is the shard IRI when it is a valid IRI, else a blank node,
  typed ``fi:Shard`` plus ``fi:<Subtype>`` for a known ``shard_type``;
* each field becomes ``fi:<camelCase(field)>`` (``fields.PREDICATE_OVERRIDES``
  keeps existing vocabulary), and scalar names match the projection's;
* nested models become typed blank nodes; list items carry ``fi:listIndex``;
* ``dict`` fields become ``fi:MapEntry`` nodes (``fi:entryKey``/``fi:entryValue``)
  in key order; ``Any`` values (null included) become canonical-JSON
  ``rdf:JSON`` literals;
* any other ``None`` renders as absence.

Values are rendered from their JSON type, with two lossless schema-guided
coercions Pydantic itself accepts: an integer in a ``float`` field becomes an
``xsd:double``, and a string in a ``datetime`` field becomes an
``xsd:dateTime`` literal (ill-formed text stays ill-formed, so the datatype
constraint reports it; a naive timestamp is read as UTC so naive and aware
bounds compare, see ``utc_datetime_lexical``). Keys the model does not declare, null-valued ones
included, are rendered under ``fis:undeclared#<key>``: a closed shape reports
them exactly like ``extra="forbid"``, and a camelCase alias of a declared
field (``sourceSpan``) can never satisfy that field's constraints.

Terms are plain tuples for speed: ``("I", iri)``, ``("B", label)`` and
``("L", lexical, datatype_iri)``. No RDF library is imported here.
"""
from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from collections.abc import Mapping
from urllib.parse import quote
from typing import Any

from pydantic import BaseModel

from folio_insights.shapes.fields import (
    SHAPES_NS,
    DICT_ENTRY_CLASS,
    ENTRY_KEY,
    ENTRY_VALUE,
    LIST_INDEX,
    RDF_JSON,
    RDF_TYPE,
    SHARD_CLASS,
    XSD_BOOLEAN,
    XSD_DATETIME,
    XSD_DOUBLE,
    XSD_INTEGER,
    XSD_STRING,
    FieldSpec,
    ModelSpec,
    model_spec,
)
from folio_insights.shards.envelope import ShardEnvelope
from folio_insights.shards.subtypes import (
    ConflictingAuthoritiesShard,
    DisputedPropositionShard,
    GlossShard,
    HypothesisShard,
    SimpleAssertionShard,
)

Term = tuple

SHARD_MODELS: tuple[type[ShardEnvelope], ...] = (
    SimpleAssertionShard,
    DisputedPropositionShard,
    ConflictingAuthoritiesShard,
    GlossShard,
    HypothesisShard,
)
SUBTYPE_BY_TAG: dict[str, type[ShardEnvelope]] = {
    model.model_fields["shard_type"].default: model for model in SHARD_MODELS
}

# A conservative absolute-IRI check (scheme ":" then no whitespace or
# characters IRIs forbid). Anything else becomes a blank node.
_IRI_RE = re.compile(r'^[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>"{}|\\^`]*$')


def iri(value: str) -> Term:
    return ("I", value)


def lit(lexical: str, datatype: str) -> Term:
    return ("L", lexical, datatype)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def utc_datetime_lexical(value: str) -> str:
    """The validation-view lexical form of a ``datetime`` field value.

    A naive timestamp (Pydantic keeps naive input naive) is rendered as UTC,
    so every engine sees comparable, offset-carrying ``xsd:dateTime``
    literals; aware and ill-formed values are rendered unchanged (an
    ill-formed one stays ill-formed, so the datatype constraint reports it).
    This affects only the validation rendering: stored records, their bytes,
    ``canonical_content_hash`` and signatures are untouched (review P2-1).
    """
    if not value or value[-1] in "Zz":
        return value
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is not None and parsed.tzinfo.utcoffset(parsed) is not None:
        return value
    return parsed.replace(tzinfo=UTC).isoformat()


def double_lexical(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "INF" if value > 0 else "-INF"
    return repr(float(value))


class ValidationGraph:
    """A tiny in-memory graph: node -> predicate -> values (insertion order)."""

    __slots__ = ("nodes", "_bnodes", "_prefix")

    def __init__(self, bnode_prefix: str = "n") -> None:
        self.nodes: dict[Term, dict[str, list[Term]]] = {}
        self._bnodes = 0
        self._prefix = bnode_prefix

    def bnode(self) -> Term:
        self._bnodes += 1
        return ("B", f"{self._prefix}{self._bnodes}")

    def add(self, s: Term, p: str, o: Term) -> None:
        props = self.nodes.get(s)
        if props is None:
            props = self.nodes[s] = {}
        values = props.get(p)
        if values is None:
            props[p] = [o]
        else:
            values.append(o)

    def values(self, s: Term, p: str) -> list[Term]:
        props = self.nodes.get(s)
        if props is None:
            return []
        return props.get(p, [])

    def triples(self) -> list[tuple[Term, str, Term]]:
        return [
            (s, p, o)
            for s, props in self.nodes.items()
            for p, values in props.items()
            for o in values
        ]

    def subjects_of_type(self, class_iri: str) -> list[Term]:
        target = ("I", class_iri)
        return [s for s, props in self.nodes.items() if target in props.get(RDF_TYPE, ())]

    def subjects_with(self, predicate: str) -> list[Term]:
        return [s for s, props in self.nodes.items() if predicate in props]

    def merge(self, other: ValidationGraph) -> None:
        for s, p, o in other.triples():
            self.add(s, p, o)


def _scalar(value: Any, datatype: str | None) -> Term | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return lit("true" if value else "false", XSD_BOOLEAN)
    if isinstance(value, int):
        if datatype == XSD_DOUBLE:
            return lit(double_lexical(float(value)), XSD_DOUBLE)
        return lit(str(value), XSD_INTEGER)
    if isinstance(value, float):
        return lit(double_lexical(value), XSD_DOUBLE)
    if isinstance(value, str):
        if datatype == XSD_DATETIME:
            return lit(utc_datetime_lexical(value), XSD_DATETIME)
        return lit(value, XSD_STRING)
    return lit(canonical_json(value), RDF_JSON)


def _render_value(g: ValidationGraph, s: Term, spec: FieldSpec, value: Any, index: int | None) -> None:
    if spec.kind == "json":
        g.add(s, spec.predicate, lit(canonical_json(value), RDF_JSON))
        return
    if spec.kind == "model" and isinstance(value, Mapping):
        assert spec.model is not None
        node = g.bnode()
        g.add(s, spec.predicate, node)
        if index is not None:
            g.add(node, LIST_INDEX, lit(str(index), XSD_INTEGER))
        _render_model(g, node, model_spec(spec.model), value)
        return
    if spec.kind == "dict" and isinstance(value, Mapping):
        for key in sorted(value, key=str):
            entry = g.bnode()
            g.add(s, spec.predicate, entry)
            g.add(entry, RDF_TYPE, iri(DICT_ENTRY_CLASS))
            g.add(entry, ENTRY_KEY, lit(str(key), XSD_STRING))
            term = _scalar(value[key], spec.dict_value_datatype)
            if term is not None:
                g.add(entry, ENTRY_VALUE, term)
        return
    term = _scalar(value, spec.datatype)
    if term is not None:
        g.add(s, spec.predicate, term)


def _render_field(g: ValidationGraph, s: Term, spec: FieldSpec, value: Any) -> None:
    if spec.kind == "json":
        # ``Any`` keeps JSON null as data (an audit record's old_value may be null).
        g.add(s, spec.predicate, lit(canonical_json(value), RDF_JSON))
        return
    if value is None:
        return
    if isinstance(value, list) and (spec.many or spec.kind in ("scalar", "model")):
        for index, item in enumerate(value):
            if item is None:
                continue
            _render_value(g, s, spec, item, index if spec.kind == "model" else None)
        return
    _render_value(g, s, spec, value, None)


def _render_model(g: ValidationGraph, node: Term, spec: ModelSpec, data: Mapping[str, Any]) -> None:
    g.add(node, RDF_TYPE, iri(spec.class_iri))
    props = g.nodes[node]
    by_name = spec.by_name
    for key, value in data.items():
        field = by_name.get(key)
        if field is None:
            # Undeclared key: rendered so the closed shape reports it, under
            # its own namespace so a camelCase alias ("sourceSpan") can never
            # stand in for the declared field's predicate, and null included
            # (Pydantic's extra="forbid" refuses {"bogus": null} too).
            term = _scalar(value, None) if value is not None else lit("null", RDF_JSON)
            g.add(node, undeclared_predicate(key), term)
            continue
        if field.kind == "scalar" and value is not None:
            # Hot path (most fields): same terms as _render_field, inline.
            datatype = field.datatype
            items = value if isinstance(value, list) else (value,)
            out = []
            for item in items:
                if item is None:
                    continue
                if type(item) is str:
                    if datatype == XSD_DATETIME:
                        out.append(("L", utc_datetime_lexical(item), XSD_DATETIME))
                    else:
                        out.append(("L", item, XSD_STRING))
                else:
                    term = _scalar(item, datatype)
                    if term is not None:
                        out.append(term)
            if out:
                existing = props.get(field.predicate)
                if existing is None:
                    props[field.predicate] = out
                else:
                    existing.extend(out)
            continue
        _render_field(g, node, field, value)


UNDECLARED_NS = f"{SHAPES_NS}undeclared#"


def undeclared_predicate(key: Any) -> str:
    """The predicate of a key the model does not declare (never allowed by
    a closed shape, never equal to a declared field's predicate)."""
    return UNDECLARED_NS + quote(str(key), safe="")


def shard_node(data: Mapping[str, Any], g: ValidationGraph) -> Term:
    shard_iri = data.get("shard_iri")
    if isinstance(shard_iri, str) and _IRI_RE.match(shard_iri):
        return iri(shard_iri)
    return g.bnode()


def render_shard(
    data: Mapping[str, Any] | BaseModel,
    *,
    graph: ValidationGraph | None = None,
    bnode_prefix: str = "n",
) -> tuple[ValidationGraph, Term]:
    """Render one shard (a JSON mapping or a model) as ``(graph, shard node)``.

    Pass ``graph`` to accumulate several shards into one graph (blank-node
    labels stay unique because the graph allocates them).
    """
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    g = graph if graph is not None else ValidationGraph(bnode_prefix)
    node = shard_node(data, g)
    g.add(node, RDF_TYPE, iri(SHARD_CLASS))
    tag = data.get("shard_type")
    model = SUBTYPE_BY_TAG.get(tag) if isinstance(tag, str) else None
    spec = model_spec(model if model is not None else ShardEnvelope)
    _render_model(g, node, spec, data)
    if model is None:
        # Unknown discriminator: no subtype class; only the fi:Shard shapes apply.
        g.nodes[node][RDF_TYPE] = [iri(SHARD_CLASS)]
    return g, node


def render_model(
    data: Mapping[str, Any] | BaseModel,
    model: type[BaseModel],
    *,
    graph: ValidationGraph | None = None,
    node: Term | None = None,
) -> tuple[ValidationGraph, Term]:
    """Render a non-shard model instance (tests and ad-hoc validation)."""
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    g = graph if graph is not None else ValidationGraph()
    subject = node if node is not None else g.bnode()
    _render_model(g, subject, model_spec(model), data)
    return g, subject


def to_ntriples(graph: ValidationGraph) -> str:
    """N-Triples text for ``graph`` (debugging and pyoxigraph loading)."""
    lines = [f"{_nt(s)} <{p}> {_nt(o)} ." for s, p, o in graph.triples()]
    return "\n".join(lines) + ("\n" if lines else "")


def _nt(term: Term) -> str:
    kind = term[0]
    if kind == "I":
        return f"<{term[1]}>"
    if kind == "B":
        return f"_:{term[1]}"
    escaped = (
        term[1].replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    )
    return f'"{escaped}"^^<{term[2]}>'


__all__ = [
    "SHARD_MODELS",
    "SUBTYPE_BY_TAG",
    "Term",
    "ValidationGraph",
    "canonical_json",
    "double_lexical",
    "iri",
    "lit",
    "render_model",
    "render_shard",
    "shard_node",
    "to_ntriples",
]
