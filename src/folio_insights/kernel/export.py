"""Kernel derivation chain export: JSON and Turtle (R11).

``chain_to_json`` and ``chain_to_turtle`` serialize a ``DerivationTree``'s
derivation chain: the root, every kernel shard it reaches, and the edges of the
shortest path to each.

* **JSON** carries the ``derivedFromKernel`` view directly: one entry per
  kernel shard reached, with its citation, path and typed edges. Keys are
  sorted and lists are in a fixed order, so the same corpus always exports the
  same bytes.
* **Turtle** uses only terms the vocabulary already declares. ``fi:derivedFromKernel``
  is named in PHILOSOPHY.md but is not a vocabulary term, and this unit adds
  none (no ``VOCAB_VERSION`` change), so the chain is written edge by edge
  with the envelope's own predicates (``fi:elaborates``, ``fi:dependsOnAxiom``,
  ``fi:dependsOnDefinition``, ``fi:dependsOnPrecedent``, ``fi:dependsOnShard``)
  and every kernel node is typed ``fi:CommonAxiom``. The storage projection
  does not type kernel shards (its adapter is unchanged); this export is the
  one place the ``fi:CommonAxiom`` typing is emitted.
"""
from __future__ import annotations

import json
from typing import Any

from folio_insights.kernel.catalog import KernelCatalog, load_catalog
from folio_insights.kernel.traversal import DerivationTree
from folio_insights.vocab._constants import FI_PREFIX

CHAIN_FORMAT = "folio-insights/kernel-chain/v1"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD_ANY_URI = "http://www.w3.org/2001/XMLSchema#anyURI"

# Derivation field -> declared fi: predicate (the dependency names match the
# storage projection's DEPENDENCY_PREDICATES; a test pins the equality).
EDGE_PREDICATES: dict[str, str] = {
    "elaborates": "elaborates",
    "depends_on_axioms": "dependsOnAxiom",
    "depends_on_definitions": "dependsOnDefinition",
    "depends_on_precedents": "dependsOnPrecedent",
    "depends_on_shards": "dependsOnShard",
}


def chain_as_dict(tree: DerivationTree, *, catalog: KernelCatalog | None = None) -> dict[str, Any]:
    """The chain as a JSON-ready dict (stable order)."""
    catalog = catalog or load_catalog()
    nodes = []
    for iri in tree.chain_nodes():
        maxim = catalog.by_iri(iri)
        nodes.append({
            "iri": iri,
            "kernel": maxim is not None,
            "citation": maxim.citation if maxim else None,
            "citation_uri": maxim.citation_uri if maxim else None,
        })
    return {
        "format": CHAIN_FORMAT,
        "root": tree.root,
        "max_depth": tree.max_depth,
        "kernel_reached": tree.kernel_reached,
        "derivedFromKernel": [d.as_dict() for d in tree.derivations],
        "nodes": nodes,
        "edges": [
            {**e.as_dict(), "predicate": FI_PREFIX + EDGE_PREDICATES[e.field]}
            for e in tree.chain_edges()
        ],
        "missing": list(tree.missing),
        "truncated": tree.truncated,
    }


def chain_to_json(tree: DerivationTree, *, catalog: KernelCatalog | None = None) -> str:
    """The chain as stable, sorted JSON text (trailing newline)."""
    return json.dumps(
        chain_as_dict(tree, catalog=catalog), indent=2, sort_keys=True, ensure_ascii=False
    ) + "\n"


def chain_triples(
    tree: DerivationTree, *, catalog: KernelCatalog | None = None
) -> list[tuple[str, str, str | tuple[str]]]:
    """The chain as (subject, predicate, object) with IRIs as ``str`` and
    literals as 1-tuples, in a stable order."""
    catalog = catalog or load_catalog()
    out: list[tuple[str, str, str | tuple[str]]] = []
    for iri in tree.chain_nodes():
        out.append((iri, RDF_TYPE, FI_PREFIX + "Shard"))
        maxim = catalog.by_iri(iri)
        if maxim is not None:
            out.append((iri, RDF_TYPE, FI_PREFIX + "CommonAxiom"))
            out.append((iri, FI_PREFIX + "reference", (maxim.citation,)))
            out.append((iri, FI_PREFIX + "sourceUri", maxim.citation_uri))
    for edge in tree.chain_edges():
        out.append((edge.source, FI_PREFIX + EDGE_PREDICATES[edge.field], edge.target))
    return out


def chain_to_turtle(tree: DerivationTree, *, catalog: KernelCatalog | None = None) -> str:
    """The chain as Turtle, using declared vocabulary terms only."""
    from pyoxigraph import Literal, NamedNode, RdfFormat, Triple, serialize

    def obj(value: str | tuple[str]) -> Any:
        if isinstance(value, tuple):
            return Literal(value[0])
        try:
            return NamedNode(value)
        except ValueError:  # a non-IRI reference string, as the projection writes it
            return Literal(value, datatype=NamedNode(XSD_ANY_URI))

    triples = [
        Triple(NamedNode(s), NamedNode(p), obj(o))
        for s, p, o in chain_triples(tree, catalog=catalog)
    ]
    return serialize(triples, format=RdfFormat.TURTLE, prefixes={"fi": FI_PREFIX}).decode("utf-8")


__all__ = [
    "CHAIN_FORMAT",
    "EDGE_PREDICATES",
    "chain_as_dict",
    "chain_to_json",
    "chain_to_turtle",
    "chain_triples",
]
