"""Phase 7 SHACL validator wrapper for the 8 governance shapes (D-04 exempt).

This module is the SHACL validator wrapper for the 8 governance shapes shipped
across plans 07-03 / 07-04a / 07-04b / 07-05a / 07-05b:

  1. governance_log     (07-03)   — log shape (position monotonicity, etc.)
  2. role_assertion     (07-04a)  — corpus_admin signer, valid role Literal
  3. role_revocation    (07-04a)  — same constraints; revoked_role Literal
  4. promotion          (07-04b)  — cited_iris non-empty (D-20)
  5. contest            (07-05a)  — voter_did present, position_text non-empty
  6. contest_resolution (07-05a)  — resolution_path in arbiter/distinguo/aporetic
  7. supersession       (07-05a)  — old/new shard_iri present and distinct
  8. retraction         (07-05b)  — cascade_preview_hash present

D-04 boundary exemption (T-7-12 dep-leak grep-guard exemption):
``rdflib`` and ``pyshacl`` imports are SAFE here — this module is the lone
exempted file under ``src/folio_insights/governance/`` (mirrors
``revision/shape_validation.py`` which enjoys the same exemption against the
``shards/`` dep-leak boundary). The dep stays out of ``governance/log.py``,
``events.py``, ``authorize.py``, and every other ``governance/`` module.
``tests/governance/test_dep_leak_guard.py`` enforces the boundary and EXEMPTS
this single filename by basename check.

This file ships the skeleton: the ``ValidationResult`` dataclass + the
graph-building helpers + 8 ``NotImplementedError``-stubbed per-event
validators. The real bodies (TTL load + pyshacl.validate call) land in the
later plans that own each shape.

Boundary policy: pyshacl + rdflib live here. Phase 13 may swap the backend
behind the GovernanceLog Protocol without touching this file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rdflib import RDF, BNode, Graph, Literal, Namespace
from rdflib.namespace import XSD

if TYPE_CHECKING:
    from folio_insights.governance.events import (
        ContestEvent,
        ContestResolutionEvent,
        GovernanceEvent,
        PromotionEvent,
        RetractionEvent,
        RoleAssertionEvent,
        RoleRevocationEvent,
        SupersessionEvent,
    )

# Phase-local namespace — mirrors revision/shape_validation.py's FI namespace
# so the governance shapes can share predicates with the content-edit shape
# (e.g. ``fi:editedAt``) if/when they cross-reference.
FI = Namespace("https://folio-insights.example/")

# Directory holding the per-shape TTL files. Each later plan (07-03/04a/04b/
# 05a/05b) writes its own TTL into this directory; the loader picks them up by
# filename.
_SHAPES_DIR = Path(__file__).parent / "shapes"


@dataclass
class ValidationResult:
    """Result of a SHACL validation run.

    Verbatim signature copied from ``revision/shape_validation.py`` so a
    single ``ValidationResult`` type is reused across the Phase 5 content-edit
    guard and the Phase 7 governance guards. Tests + reviewers can compare
    structurally identical results without per-module type juggling.
    """

    conforms: bool
    violations: list[str]
    results_text: str


def _load_shape_graph(filename: str) -> Graph:
    """Load a per-shape TTL file from ``governance/shapes/``.

    Raises ``FileNotFoundError`` if the TTL hasn't shipped yet (the later
    plans add the files); the stubbed validators below raise
    ``NotImplementedError`` BEFORE reaching this helper, so the placeholder
    state is honest: the loader exists, the stubs are clearly unimplemented,
    and downstream callers cannot accidentally consume an empty graph as a
    "passed" validation.
    """
    path = _SHAPES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Governance shape TTL not found: {path}. The file ships in the "
            f"plan that owns its shape (07-03/07-04a/07-04b/07-05a/07-05b)."
        )
    g = Graph()
    g.parse(str(path), format="turtle")
    return g


def _build_event_graph(event: GovernanceEvent) -> Graph:
    """Materialize a GovernanceEvent as a minimal local RDF graph for pyshacl.

    Mirrors ``revision/shape_validation.py:_build_edit_graph`` — emits the
    event as an ``fi:GovernanceEvent`` node carrying typed literals for every
    Pydantic field on the event class. Later plans extend this with
    event-specific predicates as their TTL shapes demand.

    The implementation below is a SKELETON: it adds the universal slots
    (``action``, ``corpus``, ``position``) every event carries, and lets each
    per-shape validator extend the graph with its own predicates if needed.
    This matches the ``revision/`` pattern where each validator builds the
    minimal graph its shape expects.
    """
    g = Graph()
    event_node = BNode()
    g.add((event_node, RDF.type, FI.GovernanceEvent))
    # Universal slots from _BaseEvent (D-16).
    g.add((event_node, FI.action, Literal(event.action, datatype=XSD.string)))
    g.add((event_node, FI.corpus, Literal(event.corpus, datatype=XSD.string)))
    g.add((event_node, FI.position, Literal(event.position, datatype=XSD.integer)))
    return g


# ── Per-event validator stubs (8 shapes; bodies filled in later plans) ──


def validate_governance_log_shape(event: GovernanceEvent) -> ValidationResult:
    """Validate the governance-log structural invariants (07-03)."""
    raise NotImplementedError(
        "filled by 07-03 (GovernanceLog Protocol + log shape)"
    )


def validate_role_assertion_shape(event: RoleAssertionEvent) -> ValidationResult:
    """Validate a RoleAssertionEvent against its SHACL shape (07-04a)."""
    raise NotImplementedError(
        "filled by 07-04a (Roles + Authorize + role_assertion shape)"
    )


def validate_role_revocation_shape(event: RoleRevocationEvent) -> ValidationResult:
    """Validate a RoleRevocationEvent against its SHACL shape (07-04a)."""
    raise NotImplementedError(
        "filled by 07-04a (Roles + Authorize + role_revocation shape)"
    )


def validate_promotion_shape(event: PromotionEvent) -> ValidationResult:
    """Validate a PromotionEvent (cited_iris non-empty, D-20) — (07-04b)."""
    raise NotImplementedError("filled by 07-04b (promotion shape)")


def validate_contest_shape(event: ContestEvent) -> ValidationResult:
    """Validate a ContestEvent (voter_did + position_text) — (07-05a)."""
    raise NotImplementedError("filled by 07-05a (contest shape)")


def validate_contest_resolution_shape(
    event: ContestResolutionEvent,
) -> ValidationResult:
    """Validate a ContestResolutionEvent (GOV-05 paths) — (07-05a)."""
    raise NotImplementedError("filled by 07-05a (contest_resolution shape)")


def validate_supersession_shape(event: SupersessionEvent) -> ValidationResult:
    """Validate a SupersessionEvent (old != new shard_iri) — (07-05a)."""
    raise NotImplementedError("filled by 07-05a (supersession shape)")


def validate_retraction_shape(event: RetractionEvent) -> ValidationResult:
    """Validate a RetractionEvent (cascade_preview_hash committed) — (07-05b)."""
    raise NotImplementedError("filled by 07-05b (retraction shape)")


__all__ = [
    "ValidationResult",
    "validate_contest_resolution_shape",
    "validate_contest_shape",
    "validate_governance_log_shape",
    "validate_promotion_shape",
    "validate_retraction_shape",
    "validate_role_assertion_shape",
    "validate_role_revocation_shape",
    "validate_supersession_shape",
]
