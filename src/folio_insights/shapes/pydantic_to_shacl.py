"""Pydantic-to-SHACL generator (Phase 11 SHACL-02, KTD3).

``generate_ttl()`` emits one SHACL file covering every shard model and every
nested model it reaches, from the same ``fields.model_spec`` walk the
validation renderer uses:

* ``fis:gen-ShardDiscriminator`` targets ``fi:Shard`` and checks
  ``fi:shardType`` against the five subtype tags;
* one closed shape per subtype (``sh:closed``, mirroring ``extra="forbid"``),
  targeting ``fi:<Subtype>`` and listing every field, inherited ones included;
* one closed shape per nested model, reached through ``sh:node``;
* one closed shape per ``dict`` value datatype (``fi:MapEntry`` nodes).

Per field: Pydantic-required (not nullable, not a list) gives
``sh:minCount 1``; a non-list, non-map field gives ``sh:maxCount 1``; ``Literal`` gives
``sh:in``; the Python type gives ``sh:datatype``; ``ge``/``le`` give
``sh:minInclusive``/``sh:maxInclusive``; ``min_length`` gives ``sh:minLength``
on strings and ``sh:minCount`` on lists; a nested model gives ``sh:node``.
Every generated constraint is ``sh:Violation``: it states only what the model
already guarantees.

Model invariants that live in ``@model_validator`` code (the disputed
epistemic subset, sic/non non-empty, no self-gloss, positive TTL, the
forward-only edit chain) are not visible to the generator; the hand-written
``ttl/subtypes.shacl.ttl`` carries them.

Output is byte-deterministic (declaration order, no timestamps). The committed
copy lives at ``generated/shard_models.shacl.ttl``; ``scripts/generate_shapes.py
--check`` fails on drift (SHACL-04).
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from folio_insights.shapes.fields import (
    DICT_ENTRY_CLASS,
    ENTRY_KEY,
    ENTRY_VALUE,
    FI,
    LIST_INDEX,
    RDF_TYPE,
    SHAPES_NS,
    SHARD_CLASS,
    XSD_DOUBLE,
    XSD_INTEGER,
    FieldSpec,
    model_spec,
    nested_models,
)
from folio_insights.shapes.rendering import SHARD_MODELS

GENERATED_PATH = Path(__file__).parent / "generated" / "shard_models.shacl.ttl"

_PREFIXES = {
    "sh": "http://www.w3.org/ns/shacl#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "fi": FI,
    "fis": SHAPES_NS,
}


def _curie(iri: str) -> str:
    for prefix, ns in _PREFIXES.items():
        if iri.startswith(ns):
            local = iri[len(ns):]
            if local and all(c.isalnum() or c in "_-" for c in local):
                return f"{prefix}:{local}"
    return f"<{iri}>"


def _string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    )
    return f'"{escaped}"'


def _number(value: float | int, datatype: str) -> str:
    if datatype == XSD_INTEGER:
        return f'"{int(value)}"^^xsd:integer'
    if datatype == XSD_DOUBLE:
        return f'"{float(value)!r}"^^xsd:double'
    raise ValueError(f"numeric bound on non-numeric datatype {datatype}")


def shape_iri(model: type[BaseModel]) -> str:
    return f"{SHAPES_NS}gen-{model.__name__}"


def map_entry_shape_iri(datatype: str) -> str:
    return f"{SHAPES_NS}gen-MapEntry-{datatype.rsplit('#', 1)[-1]}"


def _describe(owner: str, spec: FieldSpec) -> str:
    parts = []
    if spec.required:
        parts.append("required")
    if spec.kind != "dict":
        parts.append("list" if spec.many else "single-valued")
    if spec.enum is not None:
        parts.append("one of " + ", ".join(spec.enum))
    elif spec.kind == "model" and spec.model is not None:
        parts.append(f"a {spec.model.__name__}")
    elif spec.kind == "dict":
        parts.append("a string-keyed map")
    elif spec.datatype is not None:
        parts.append(_curie(spec.datatype))
    if spec.min_inclusive is not None or spec.max_inclusive is not None:
        parts.append(f"in [{spec.min_inclusive}, {spec.max_inclusive}]")
    if spec.min_length is not None:
        parts.append(f"at least {spec.min_length} character(s)")
    if spec.min_items is not None:
        parts.append(f"at least {spec.min_items} item(s)")
    return f"{owner}.{spec.name} must be " + ", ".join(parts) + " (generated from the Pydantic model)"


def _property(owner: str, spec: FieldSpec) -> str:
    lines = [f"sh:path {_curie(spec.predicate)}", f"sh:name {_string(spec.name)}"]
    min_count = 1 if spec.required else (spec.min_items or 0)
    if min_count:
        lines.append(f"sh:minCount {min_count}")
    if not spec.many and spec.kind != "dict":
        # A map renders one fi:MapEntry per key, so it has no upper bound.
        lines.append("sh:maxCount 1")
    if spec.kind == "model":
        assert spec.model is not None
        lines.append(f"sh:node {_curie(shape_iri(spec.model))}")
    elif spec.kind == "dict":
        assert spec.dict_value_datatype is not None
        lines.append(f"sh:node {_curie(map_entry_shape_iri(spec.dict_value_datatype))}")
    else:
        assert spec.datatype is not None
        lines.append(f"sh:datatype {_curie(spec.datatype)}")
    if spec.enum is not None:
        lines.append("sh:in ( " + " ".join(_string(v) for v in spec.enum) + " )")
    if spec.min_inclusive is not None:
        lines.append(f"sh:minInclusive {_number(spec.min_inclusive, spec.datatype or '')}")
    if spec.max_inclusive is not None:
        lines.append(f"sh:maxInclusive {_number(spec.max_inclusive, spec.datatype or '')}")
    if spec.min_length is not None:
        lines.append(f"sh:minLength {spec.min_length}")
    lines.append(f"sh:message {_string(_describe(owner, spec))}")
    body = " ;\n        ".join(lines)
    return f"[\n        {body} ;\n    ]"


def _closed_shape(
    subject: str, *, target: str | None, comment: str, properties: list[str], name: str
) -> str:
    head = [f"{_curie(subject)} a sh:NodeShape"]
    head.append(f"    rdfs:comment {_string(comment)}")
    if target is not None:
        head.append(f"    sh:targetClass {_curie(target)}")
    head.append("    sh:closed true")
    head.append(
        f"    sh:message {_string(f'{name} is closed: undeclared field (mirrors extra=forbid; generated)')}"
    )
    head.append(f"    sh:ignoredProperties ( {_curie(RDF_TYPE)} {_curie(LIST_INDEX)} )")
    for prop in properties:
        head.append(f"    sh:property {prop}")
    return " ;\n".join(head) + " .\n"


def generate_ttl() -> str:
    """The generated shapes as Turtle text (deterministic)."""
    out: list[str] = [
        "# GENERATED by scripts/generate_shapes.py from the Pydantic shard models.",
        "# DO NOT EDIT: regenerate with `python scripts/generate_shapes.py`;",
        "# `--check` (tests + the Dagger shapes stage) fails on drift (SHACL-04).",
        "# Generator: src/folio_insights/shapes/pydantic_to_shacl.py (Phase 11 KTD3).",
        "",
    ]
    prefixes = dict(_PREFIXES)
    prefixes["rdfs"] = "http://www.w3.org/2000/01/rdf-schema#"
    out.extend(f"@prefix {p}: <{ns}> ." for p, ns in sorted(prefixes.items()))
    out.append("")

    tags = [m.model_fields["shard_type"].default for m in SHARD_MODELS]
    out.append(
        f"{_curie(SHAPES_NS + 'gen-ShardDiscriminator')} a sh:NodeShape ;\n"
        f"    rdfs:comment {_string('Every fi:Shard names one of the five subtypes (ShardType).')} ;\n"
        f"    sh:targetClass {_curie(SHARD_CLASS)} ;\n"
        "    sh:property [\n"
        "        sh:path fi:shardType ;\n"
        "        sh:minCount 1 ;\n"
        "        sh:maxCount 1 ;\n"
        "        sh:datatype xsd:string ;\n"
        "        sh:in ( " + " ".join(_string(t) for t in tags) + " ) ;\n"
        f"        sh:message {_string('fi:shardType must be one of the five ShardType values (generated)')} ;\n"
        "    ] .\n"
    )

    for model in SHARD_MODELS:
        spec = model_spec(model)
        out.append(
            _closed_shape(
                shape_iri(model),
                target=spec.class_iri,
                comment=f"Generated from {model.__module__}.{model.__qualname__}.",
                properties=[_property(model.__name__, f) for f in spec.fields],
                name=model.__name__,
            )
        )

    datatypes: list[str] = []
    for model in nested_models(SHARD_MODELS):
        spec = model_spec(model)
        out.append(
            _closed_shape(
                shape_iri(model),
                target=None,
                comment=f"Generated from {model.__module__}.{model.__qualname__} (reached through sh:node).",
                properties=[_property(model.__name__, f) for f in spec.fields],
                name=model.__name__,
            )
        )
        datatypes.extend(f.dict_value_datatype for f in spec.fields if f.dict_value_datatype)
    for model in SHARD_MODELS:
        datatypes.extend(
            f.dict_value_datatype for f in model_spec(model).fields if f.dict_value_datatype
        )

    for datatype in sorted(set(datatypes)):
        key = (
            f"[ sh:path {_curie(ENTRY_KEY)} ; sh:minCount 1 ; sh:maxCount 1 ; "
            f"sh:datatype xsd:string ; sh:message {_string('map entry needs exactly one string key (generated)')} ; ]"
        )
        value = (
            f"[ sh:path {_curie(ENTRY_VALUE)} ; sh:minCount 1 ; sh:maxCount 1 ; "
            f"sh:datatype {_curie(datatype)} ; "
            f"sh:message {_string(f'map entry needs exactly one {_curie(datatype)} value (generated)')} ; ]"
        )
        out.append(
            _closed_shape(
                map_entry_shape_iri(datatype),
                target=None,
                comment=f"A {_curie(DICT_ENTRY_CLASS)} of a string-keyed map with {_curie(datatype)} values.",
                properties=[key, value],
                name="MapEntry",
            )
        )
    return "\n".join(out)


def write_generated(path: Path = GENERATED_PATH) -> bool:
    """Write the generated TTL; returns True when the file changed."""
    text = generate_ttl()
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def check_generated(path: Path = GENERATED_PATH) -> bool:
    """True when the committed TTL equals a fresh generation."""
    return path.exists() and path.read_text(encoding="utf-8") == generate_ttl()


__all__ = [
    "GENERATED_PATH",
    "check_generated",
    "generate_ttl",
    "map_entry_shape_iri",
    "shape_iri",
    "write_generated",
]
