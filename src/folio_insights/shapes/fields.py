"""One field walk shared by the SHACL generator and the validation renderer.

``model_spec(Model)`` turns a Pydantic model into a ``ModelSpec``: the RDF
class of its instances and one ``FieldSpec`` per field (predicate IRI, value
kind, datatype, enumeration, cardinality, numeric and length bounds, nested
model). ``pydantic_to_shacl`` emits shapes from these specs and
``rendering`` turns instance data into triples from the same specs, so the
shapes and the data they validate cannot drift apart (Phase 11 KTD2/KTD3).

Only the constructs the shard models use are supported. Anything else raises
``UnsupportedFieldType`` so a model change that the generator cannot express
fails generation loudly instead of producing a weaker shape.

Pure stdlib + Pydantic: no RDF library is imported here.
"""
from __future__ import annotations

import types
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from typing import Any, Literal, Union, get_args, get_origin

import annotated_types
from pydantic import BaseModel
from pydantic.fields import FieldInfo

FI = "https://folio-insights.aleainstitute.ai/vocab/"
SHAPES_NS = "https://folio-insights.aleainstitute.ai/shapes/"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

XSD_STRING = f"{XSD}string"
XSD_BOOLEAN = f"{XSD}boolean"
XSD_INTEGER = f"{XSD}integer"
XSD_DOUBLE = f"{XSD}double"
XSD_DATETIME = f"{XSD}dateTime"
RDF_JSON = f"{RDF}JSON"
RDF_TYPE = f"{RDF}type"

# Structural predicates the renderer adds (ignored by closed shapes).
LIST_INDEX = f"{FI}listIndex"
ENTRY_KEY = f"{FI}entryKey"
ENTRY_VALUE = f"{FI}entryValue"
SHARD_CLASS = f"{FI}Shard"
DICT_ENTRY_CLASS = f"{FI}MapEntry"

ScalarKind = Literal["scalar", "model", "dict", "json"]

_SCALAR_DATATYPES: dict[type, str] = {
    str: XSD_STRING,
    bool: XSD_BOOLEAN,
    int: XSD_INTEGER,
    float: XSD_DOUBLE,
    datetime: XSD_DATETIME,
}

# Predicates that keep existing vocabulary instead of fi:<camelCase(field)>:
# ``fi:signedAction`` is the SignedActionEnumShape path (vocab/shapes.ttl), and
# the dependency edges use the projection's singular predicates
# (storage/projection.py DEPENDENCY_PREDICATES; a test pins the agreement).
PREDICATE_OVERRIDES: dict[tuple[str, str], str] = {
    ("AttestedSignature", "action"): "signedAction",
    ("ShardEnvelope", "depends_on_axioms"): "dependsOnAxiom",
    ("ShardEnvelope", "depends_on_definitions"): "dependsOnDefinition",
    ("ShardEnvelope", "depends_on_precedents"): "dependsOnPrecedent",
    ("ShardEnvelope", "depends_on_shards"): "dependsOnShard",
}

# Instance classes that would collide with a different meaning in the vocab:
# ``fi:ContentEdit`` is the governance-event class (a subclass of fi:Shard in
# vocab/classes.ttl); an entry of a shard's ``content_edits`` list is not one.
CLASS_OVERRIDES: dict[str, str] = {
    "ContentEdit": "ContentEditRecord",
}


class UnsupportedFieldType(TypeError):
    """A model field uses a construct the generator cannot express."""


def camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def class_iri(model: type[BaseModel]) -> str:
    name = model.__name__
    return f"{FI}{CLASS_OVERRIDES.get(name, name)}"


@dataclass(frozen=True)
class FieldSpec:
    """How one model field maps to RDF and which constraints it carries."""

    name: str
    predicate: str
    kind: ScalarKind
    datatype: str | None = None          # scalar kind only
    enum: tuple[str, ...] | None = None  # Literal[...] values
    many: bool = False                   # list[...] field
    required: bool = False               # Pydantic-required, not nullable, not a list
    nullable: bool = False
    model: type[BaseModel] | None = None  # model kind only
    dict_value_datatype: str | None = None  # dict kind only
    min_inclusive: float | None = None
    max_inclusive: float | None = None
    min_length: int | None = None        # str min_length
    min_items: int | None = None         # list min_length


@dataclass(frozen=True, eq=False)
class ModelSpec:
    model: type[BaseModel]
    class_iri: str
    fields: tuple[FieldSpec, ...]
    by_name: dict[str, FieldSpec] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.by_name.update({spec.name: spec for spec in self.fields})

    def field(self, name: str) -> FieldSpec | None:
        return self.by_name.get(name)


def _predicate_for(model: type[BaseModel], name: str) -> str:
    for klass in model.__mro__:
        local = PREDICATE_OVERRIDES.get((klass.__name__, name))
        if local is not None:
            return f"{FI}{local}"
    return f"{FI}{camel(name)}"


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        nullable = len(args) != len(get_args(annotation))
        if len(args) != 1:
            raise UnsupportedFieldType(f"union {annotation!r} has more than one non-None member")
        return args[0], nullable
    return annotation, False


def _literal_values(annotation: Any) -> tuple[str, ...] | None:
    if get_origin(annotation) is Literal:
        values = get_args(annotation)
        if not all(isinstance(v, str) for v in values):
            raise UnsupportedFieldType(f"Literal {annotation!r} has non-string values")
        return tuple(values)
    return None


def _bounds(info: FieldInfo) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in info.metadata:
        if isinstance(item, annotated_types.Ge):
            out["min_inclusive"] = item.ge
        elif isinstance(item, annotated_types.Le):
            out["max_inclusive"] = item.le
        elif isinstance(item, annotated_types.MinLen):
            out["min_length"] = item.min_length
        else:
            raise UnsupportedFieldType(f"field constraint {item!r} is not supported")
    return out


def _field_spec(model: type[BaseModel], name: str, info: FieldInfo) -> FieldSpec:
    annotation, nullable = _unwrap_optional(info.annotation)
    many = False
    if get_origin(annotation) is list:
        (annotation,) = get_args(annotation)
        many = True
        inner, inner_nullable = _unwrap_optional(annotation)
        if inner_nullable:
            raise UnsupportedFieldType(f"{model.__name__}.{name}: list of optional values")
        annotation = inner
    bounds = _bounds(info)
    min_items = None
    if many and "min_length" in bounds:
        min_items = bounds.pop("min_length")
    required = info.is_required() and not nullable and not many
    common: dict[str, Any] = {
        "name": name,
        "predicate": _predicate_for(model, name),
        "many": many,
        "required": required,
        "nullable": nullable,
        "min_items": min_items,
        **bounds,
    }

    enum = _literal_values(annotation)
    if enum is not None:
        return FieldSpec(kind="scalar", datatype=XSD_STRING, enum=enum, **common)
    if annotation is Any:
        return FieldSpec(kind="json", datatype=RDF_JSON, **common)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return FieldSpec(kind="model", model=annotation, **common)
    if get_origin(annotation) is dict:
        key_type, value_type = get_args(annotation)
        if key_type is not str or value_type not in _SCALAR_DATATYPES:
            raise UnsupportedFieldType(f"{model.__name__}.{name}: dict[{key_type}, {value_type}]")
        if many:
            raise UnsupportedFieldType(f"{model.__name__}.{name}: list of dicts")
        return FieldSpec(
            kind="dict", dict_value_datatype=_SCALAR_DATATYPES[value_type], **common
        )
    if annotation in _SCALAR_DATATYPES:
        return FieldSpec(kind="scalar", datatype=_SCALAR_DATATYPES[annotation], **common)
    raise UnsupportedFieldType(f"{model.__name__}.{name}: unsupported type {annotation!r}")


@cache
def model_spec(model: type[BaseModel]) -> ModelSpec:
    """The field specs of ``model`` (inherited fields included), in declaration order."""
    fields = tuple(
        _field_spec(model, name, info) for name, info in model.model_fields.items()
    )
    return ModelSpec(model=model, class_iri=class_iri(model), fields=fields)


def nested_models(roots: tuple[type[BaseModel], ...]) -> tuple[type[BaseModel], ...]:
    """Every model reachable from ``roots`` through model-kind fields,
    roots excluded, in a stable first-seen order."""
    seen: list[type[BaseModel]] = []
    stack = list(roots)
    while stack:
        current = stack.pop(0)
        for spec in model_spec(current).fields:
            if spec.model is not None and spec.model not in seen and spec.model not in roots:
                seen.append(spec.model)
                stack.append(spec.model)
    return tuple(seen)


__all__ = [
    "CLASS_OVERRIDES",
    "DICT_ENTRY_CLASS",
    "ENTRY_KEY",
    "ENTRY_VALUE",
    "FI",
    "LIST_INDEX",
    "PREDICATE_OVERRIDES",
    "RDF_JSON",
    "RDF_TYPE",
    "SHAPES_NS",
    "SHARD_CLASS",
    "XSD_BOOLEAN",
    "XSD_DATETIME",
    "XSD_DOUBLE",
    "XSD_INTEGER",
    "XSD_STRING",
    "FieldSpec",
    "ModelSpec",
    "UnsupportedFieldType",
    "camel",
    "class_iri",
    "model_spec",
    "nested_models",
]
