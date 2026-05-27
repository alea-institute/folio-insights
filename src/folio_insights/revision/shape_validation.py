"""Defense-in-depth forward-only SHACL guard (CONTEXT D-07.2; exit criterion 2).

This module ships the literal "SHACL guard" the operator reads from exit
criterion 2: a REAL pyshacl run over the ``content_edits`` chain, beside the
always-on Pydantic validator.

Two-layer division (state explicitly so no effort is wasted making SHACL do what
it cannot):

* The AUTHORITATIVE forward-only/append-only gate is the Pydantic
  ``@model_validator`` on ``ShardEnvelope`` (Plan 05-01, ``shards/envelope.py``) —
  always-on, rejects a non-monotonic ``edited_at`` chain at construction.
* ``validate_content_edit_shape(shard)`` here is DEFENSE-IN-DEPTH (the distinguo
  ``validate_*_shape()`` idiom — ``polysemy/distinguo.py``), but unlike distinguo's
  Python-level re-check, it runs an actual ``pyshacl.validate`` over a minimal
  local RDF graph built from the shard's edit chain (D-07.2). It catches a
  back-dated chain that bypassed the Pydantic validator (e.g. a record loaded via
  ``model_construct``).

What SHACL CAN enforce: forward-only monotonicity — a ``sh:sparql`` self-join over
the edit chain flags any adjacent pair where ``editedAt`` decreases (a back-dated
insert, the temporal sense of "edit to a past version").

What SHACL CANNOT enforce: immutability of past entries (D-08a — no mutation or
deletion of an existing ``ContentEdit``). SHACL is stateless over a single graph
snapshot and cannot detect a deletion (RESEARCH L115-124). That half is carried
structurally by ``ContentEdit`` ``frozen=True`` + the ``IMMUTABLE_FIELD_PATHS``
gate (Plan 02). This module does NOT attempt it.

Boundary: rdflib/pyshacl imports are SAFE here — ``revision/`` is OUTSIDE the
``shards/`` dep-leak boundary (``tests/shards/test_dep_leak_guard.py`` forbids
these imports under ``shards/`` only).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pyshacl
from rdflib import RDF, BNode, Graph, Literal, Namespace
from rdflib.collection import Collection
from rdflib.namespace import XSD

if TYPE_CHECKING:  # avoid a runtime import cycle / keep this module RDF-focused
    from folio_insights.shards import ShardEnvelope

# Phase-local namespace mirroring the shape TTL (do NOT reuse export/shapes.ttl's
# OWL-export namespace — different domain).
FI = Namespace("https://folio-insights.example/")

# The forward-only shape lives beside this module (Phase-5-local, NOT appended to
# export/shapes.ttl).
_SHAPE_PATH = Path(__file__).parent / "content_edit_shape.ttl"


@dataclass
class ValidationResult:
    """Result of a SHACL validation run (mirrors services/shacl_validator.py)."""

    conforms: bool
    violations: list[str]
    results_text: str


def _build_edit_graph(shard: ShardEnvelope) -> Graph:
    """Map a shard's ``content_edits`` chain to a minimal local RDF graph.

    Emits the shard as an ``fi:Shard`` node whose ``fi:contentEdits`` points at an
    ``rdf:List`` of edit nodes; each edit node carries ``fi:editedAt`` (a typed
    ``xsd:dateTime`` literal) and an integer ``fi:seq`` (0-based append order).
    This is exactly the RESEARCH L79 mapping the verified shape expects — it does
    NOT pull the Phase-13 store forward, it builds just enough to feed pyshacl.
    """
    g = Graph()
    shard_node = BNode()
    g.add((shard_node, RDF.type, FI.Shard))

    edit_nodes: list[BNode] = []
    for i, edit in enumerate(shard.content_edits):
        edit_node = BNode()
        g.add(
            (
                edit_node,
                FI.editedAt,
                Literal(edit.edited_at.isoformat(), datatype=XSD.dateTime),
            )
        )
        g.add((edit_node, FI.seq, Literal(i, datatype=XSD.integer)))
        edit_nodes.append(edit_node)

    # Build the rdf:List (Collection wires rdf:first/rdf:rest/rdf:nil for us).
    list_head = BNode()
    Collection(g, list_head, edit_nodes)
    g.add((shard_node, FI.contentEdits, list_head))
    return g


def validate_content_edit_shape(shard: ShardEnvelope) -> ValidationResult:
    """Run the forward-only SHACL shape against a shard's edit chain (D-07.2).

    Builds a minimal local RDF graph from ``shard.content_edits`` and runs
    ``pyshacl.validate`` against ``content_edit_shape.ttl``. ``conforms`` is False
    when any adjacent edit pair is back-dated (a violation the ``sh:sparql``
    self-join matches). Mirrors the load/run pattern in
    ``services/shacl_validator.py`` L80-100.

    Returns:
        ValidationResult with ``conforms`` / ``violations`` / ``results_text``.
    """
    shapes = Graph()
    shapes.parse(str(_SHAPE_PATH), format="turtle")

    data_graph = _build_edit_graph(shard)

    conforms, _results_graph, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
    )

    violations: list[str] = []
    if not conforms:
        for line in results_text.splitlines():
            line = line.strip()
            if line.startswith("Message:"):
                violations.append(line.replace("Message:", "").strip())
            elif line.startswith("Constraint Violation"):
                violations.append(line)
        # Ensure at least one violation is reported even if parsing missed it.
        if not violations:
            violations.append(results_text.strip())

    return ValidationResult(
        conforms=conforms,
        violations=violations,
        results_text=results_text,
    )


__all__ = ["ValidationResult", "validate_content_edit_shape"]
