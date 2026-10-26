"""Model-enforced atomic hash binding, shared by both validation engines.

SHACL Core cannot reproduce NFC/URI normalization and canonical JSON hashing.
Read the frozen basis from the validation graph and run the authoritative model
check before reporting conformance. No renderer metadata or RDF library is needed.
"""
from __future__ import annotations

from collections.abc import Collection, Iterator

from folio_insights.shapes.fields import FI, SHAPES_NS, SHARD_CLASS, RDF_TYPE, XSD_INTEGER, XSD_STRING
from folio_insights.shapes.rendering import Term, ValidationGraph, iri, lit
from folio_insights.shards.envelope import AtomicEnvelope, AtomicIdentity

BINDING_COMPONENT = SHAPES_NS + "atomic#IdentityBindingConstraintComponent"
BINDING_SHAPE = SHAPES_NS + "model-AtomicEnvelope-identity-binding"


def _scalar(g: ValidationGraph, node: Term, name: str, datatype: str = XSD_STRING):
    values = g.values(node, FI + name)
    if len(values) != 1 or values[0][0] != "L" or values[0][2] != datatype:
        raise ValueError("missing or malformed identity input")
    return int(values[0][1]) if datatype == XSD_INTEGER else values[0][1]


def identity_binding_errors(
    g: ValidationGraph, *, focus: Collection[Term] | None = None,
) -> Iterator[tuple[Term, str]]:
    for node, props in g.nodes.items():
        if focus is not None and node not in focus:
            continue
        atomic = FI + "identityRecipe" in props or (
            iri(SHARD_CLASS) in props.get(RDF_TYPE, ())
            and lit("3", XSD_INTEGER) in props.get(FI + "schemaVersion", ())
        )
        if not atomic:
            continue
        try:
            recipe = _scalar(g, node, "identityRecipe")
            if recipe not in ("legacy-v1", "atomic-v1"):
                raise ValueError("unknown identity recipe")
            basis_nodes = g.values(node, FI + "atomicIdentity")
            key_values = g.values(node, FI + "propositionKey")
            basis = None
            key = _scalar(g, node, "propositionKey") if key_values else None
            if basis_nodes:
                if len(basis_nodes) != 1:
                    raise ValueError("multiple identity bases")
                basis_node = basis_nodes[0]
                basis = AtomicIdentity.model_validate({
                    "text": _scalar(g, basis_node, "text"),
                    "start": _scalar(g, basis_node, "start", XSD_INTEGER),
                    "end": _scalar(g, basis_node, "end", XSD_INTEGER),
                    "source_snapshot_digest": _scalar(g, basis_node, "sourceSnapshotDigest"),
                })
            # Construct only the fields this invariant reads. Other model
            # invariants remain the shapes' responsibility; reviewed sense
            # edits must never replace the frozen extraction-time basis.
            envelope = AtomicEnvelope.model_construct(
                identity_recipe=recipe, proposition_key=key, atomic_identity=basis,
                **{
                    name: _scalar(g, node, predicate)
                    for name, predicate in (
                        ("source_uri", "sourceUri"), ("source_span", "sourceSpan"),
                        ("shard_iri", "shardIri"), ("provenance_hash", "provenanceHash"),
                    )
                },
            )
            envelope._identity_binding()
        except ValueError:
            # Fixed text: API/status reports never echo candidate content.
            yield node, "Atomic identity binding failed (model-enforced frozen basis/key/IRI check)"
