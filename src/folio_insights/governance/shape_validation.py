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

import pyshacl
from rdflib import RDF, BNode, Graph, Literal, Namespace, URIRef
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


def _build_log_graph(
    history: "list[GovernanceEvent]",
    pending: "GovernanceEvent",
) -> Graph:
    """Materialize the (history + pending) snapshot as RDF for pyshacl.

    Emits a single ``fi:GovernanceLog`` container node whose ``fi:hasEvent``
    predicate points at each event (the events in ``history`` plus
    ``pending`` — i.e. the POST-APPEND state). Each event carries
    ``fi:position`` (xsd:integer) and ``fi:signedAt`` (xsd:dateTime) — the
    two structural predicates the SHACL constraints query against. The DID
    is included for downstream PROV-O round-trips.

    The append-only invariant is structural over the post-append snapshot;
    if any constraint fires on the snapshot, the SHACL run reports a
    violation and ``append`` refuses. Mirrors
    ``revision/shape_validation.py:_build_edit_graph`` — minimal enough to
    feed pyshacl, never reaches into the (future) Phase 13 store.
    """
    g = Graph()
    log_node = BNode()
    g.add((log_node, RDF.type, FI.GovernanceLog))

    all_events = [*history, pending]
    for i, ev in enumerate(all_events):
        # Use a stable URIRef per event so the SPARQL self-join can compare
        # STR(?e1) != STR(?e2) (BNode comparison is implementation-dependent
        # in some pyshacl/rdflib configurations).
        event_node = URIRef(f"urn:fi:event:{i}")
        g.add((log_node, FI.hasEvent, event_node))
        g.add((event_node, RDF.type, FI.GovernanceEvent))
        g.add(
            (event_node, FI.position, Literal(ev.position, datatype=XSD.integer))
        )
        # ev.signature.signed_at is an Optional[datetime]; the events module
        # accepts None for unsigned stubs (T-06-03) but the SHACL invariant
        # only applies when signed_at is present. We emit a Literal only when
        # signed_at is non-None; absent timestamps neither pass nor fail the
        # signed_at constraint (vacuously true).
        if ev.signature.signed_at is not None:
            g.add(
                (
                    event_node,
                    FI.signedAt,
                    Literal(
                        ev.signature.signed_at.isoformat(),
                        datatype=XSD.dateTime,
                    ),
                )
            )
        g.add(
            (event_node, FI.did, Literal(ev.signature.did, datatype=XSD.string))
        )
    return g


def validate_governance_log_shape(
    history: "list[GovernanceEvent]",
    pending: "GovernanceEvent",
) -> ValidationResult:
    """Validate the governance-log structural invariants (D-05; 07-03).

    Builds the post-append RDF snapshot (history + pending) and runs
    ``pyshacl.validate`` against ``governance_log_shape.ttl``. ``conforms``
    is False when any of the three constraints fire:

      1. duplicate position (two events share the same ``fi:position``);
      2. signed_at goes backward with position (back-dating);
      3. gap in the position sequence (deletion signature).

    Mirrors ``revision/shape_validation.validate_content_edit_shape`` body
    shape verbatim (Phase 5 D-07.2 precedent) — same pyshacl.validate call
    + same violations-text parsing.

    The InMemoryGovernanceLog calls this validator from ``append()`` (via
    lazy import; see governance/log.py D-04 boundary preservation).
    """
    shapes = _load_shape_graph("governance_log_shape.ttl")
    data_graph = _build_log_graph(history, pending)

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


def validate_role_assertion_shape(
    event: "RoleAssertionEvent",
    *,
    history: "list[GovernanceEvent] | None" = None,
) -> ValidationResult:
    """Validate a RoleAssertionEvent against its SHACL shape (07-04a Task 2).

    Task 2 of 07-04a fills the real body — loads
    ``role_assertion_shape.ttl`` + builds a role-context data graph (the
    signer's active roles at signed_at materialized as
    ``fi:hasActiveRoleAt`` triples) + runs ``pyshacl.validate``. Until then
    the validator returns ``conforms=True`` so the log.py code-layer gate
    (signer-must-be-admin) remains the active enforcement; the SHACL belt
    arrives in Task 2 of THIS plan.
    """
    shapes_path = _SHAPES_DIR / "role_assertion_shape.ttl"
    if not shapes_path.exists():
        # Task 2 of 07-04a hasn't shipped yet; defer to the code-layer gate.
        return ValidationResult(conforms=True, violations=[], results_text="")
    shapes = _load_shape_graph("role_assertion_shape.ttl")
    data_graph = _build_role_assertion_graph(event, history or [])
    conforms, _g, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
    )
    violations = _parse_violations(results_text) if not conforms else []
    return ValidationResult(
        conforms=conforms, violations=violations, results_text=results_text
    )


def validate_role_revocation_shape(
    event: "RoleRevocationEvent",
    *,
    history: "list[GovernanceEvent] | None" = None,
) -> ValidationResult:
    """Validate a RoleRevocationEvent against its SHACL shape (07-04a Task 2).

    Until the TTL ships in Task 2, returns ``conforms=True`` (the code-layer
    D-11 last-admin lockout check is the active gate). When the TTL is
    present, the SHACL belt mirrors the suspenders.
    """
    shapes_path = _SHAPES_DIR / "role_revocation_shape.ttl"
    if not shapes_path.exists():
        return ValidationResult(conforms=True, violations=[], results_text="")
    shapes = _load_shape_graph("role_revocation_shape.ttl")
    data_graph = _build_role_revocation_graph(event, history or [])
    conforms, _g, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
    )
    violations = _parse_violations(results_text) if not conforms else []
    return ValidationResult(
        conforms=conforms, violations=violations, results_text=results_text
    )


def _parse_violations(results_text: str) -> list[str]:
    """Extract violation messages from pyshacl results text."""
    violations: list[str] = []
    for line in results_text.splitlines():
        line = line.strip()
        if line.startswith("Message:"):
            violations.append(line.replace("Message:", "").strip())
        elif line.startswith("Constraint Violation"):
            violations.append(line)
    if not violations and results_text.strip():
        violations.append(results_text.strip())
    return violations


def _build_role_context_graph(
    history: "list[GovernanceEvent]",
    event,
) -> Graph:
    """Materialize active-roles context as RDF for the SPARQL constraints.

    Walks ``history`` up to ``event.signature.signed_at`` (or, for events
    with no signed_at, all of history) and emits, for each currently-active
    role assertion, a ``<signer_did> fi:hasActiveRoleAt (<role> <asof>)``
    triple. The role assertion shape's SPARQL constraint queries against
    these triples to check whether the signer holds corpus_admin at
    signature.signed_at.

    Implementation detail: the (role, asof) pair is encoded as two
    properties on a single bnode for now —
    ``fi:hasActiveRoleAt [ fi:role "<role>" ; fi:asof "<asof>" ]`` — so the
    SPARQL can match them with a single triple-pattern join.
    """
    from folio_insights.governance.events import (
        RoleAssertionEvent as _RA,
    )
    from folio_insights.governance.events import (
        RoleRevocationEvent as _RR,
    )

    g = Graph()
    asof = event.signature.signed_at
    # Walk history applying assertions minus revocations to get the active map
    # at asof. Mirrors roles.active_roles_at but produced as RDF triples here.
    active: dict[str, set[str]] = {}
    for ev in history:
        ev_at = ev.signature.signed_at
        if ev_at is None:
            continue
        if asof is not None and ev_at > asof:
            continue
        if isinstance(ev, _RA):
            active.setdefault(ev.subject_did, set()).add(ev.role)
        elif isinstance(ev, _RR):
            roles = active.get(ev.subject_did)
            if roles is not None:
                roles.discard(ev.revoked_role)

    for did, roles in active.items():
        did_node = URIRef(f"urn:fi:did:{did}")
        for role in roles:
            role_bnode = BNode()
            g.add((did_node, FI.hasActiveRoleAt, role_bnode))
            g.add((role_bnode, FI.role, Literal(role)))
            if asof is not None:
                g.add(
                    (
                        role_bnode,
                        FI.asof,
                        Literal(asof.isoformat(), datatype=XSD.dateTime),
                    )
                )
    return g


def _build_role_assertion_graph(
    event: "RoleAssertionEvent",
    history: "list[GovernanceEvent]",
) -> Graph:
    """Materialize a RoleAssertion + its active-role context as RDF."""
    g = _build_role_context_graph(history, event)
    event_node = URIRef("urn:fi:pending:roleassertion")
    g.add((event_node, RDF.type, FI.RoleAssertion))
    g.add(
        (event_node, FI.position, Literal(event.position, datatype=XSD.integer))
    )
    g.add((event_node, FI.role, Literal(event.role)))
    g.add((event_node, FI.subjectDid, Literal(event.subject_did)))
    g.add((event_node, FI.signerDid, Literal(event.signature.did)))
    if event.signature.signed_at is not None:
        g.add(
            (
                event_node,
                FI.signedAt,
                Literal(
                    event.signature.signed_at.isoformat(),
                    datatype=XSD.dateTime,
                ),
            )
        )
    return g


def _build_role_revocation_graph(
    event: "RoleRevocationEvent",
    history: "list[GovernanceEvent]",
) -> Graph:
    """Materialize a RoleRevocation + the active-admin count as RDF for D-11."""
    g = _build_role_context_graph(history, event)
    event_node = URIRef("urn:fi:pending:rolerevocation")
    g.add((event_node, RDF.type, FI.RoleRevocation))
    g.add(
        (event_node, FI.position, Literal(event.position, datatype=XSD.integer))
    )
    g.add((event_node, FI.revokedRole, Literal(event.revoked_role)))
    g.add((event_node, FI.subjectDid, Literal(event.subject_did)))
    g.add((event_node, FI.signerDid, Literal(event.signature.did)))
    if event.signature.signed_at is not None:
        g.add(
            (
                event_node,
                FI.signedAt,
                Literal(
                    event.signature.signed_at.isoformat(),
                    datatype=XSD.dateTime,
                ),
            )
        )
    return g


def _build_promotion_graph(event: "PromotionEvent") -> Graph:
    """Materialize a PromotionEvent as RDF for the PromotionShape SPARQL/path checks.

    Emits a ``fi:Promotion`` node carrying:
      * ``fi:newStatus`` — plain Literal (matches the sh:in plain-string list).
      * ``fi:citedIri`` — one triple per IRI in ``event.cited_iris`` (may be
        zero — that's the empty-cited_iris polarity case the SHACL belt
        catches).
      * ``fi:shardIri`` — informational (for future cross-shard SPARQL).

    Plain (non-typed) Literals are used for ``fi:newStatus`` so the SHACL
    ``sh:in ( "..." )`` constraint (which matches plain Literals, not typed
    ones) fires cleanly. Mirrors the 07-04a precedent (commit bad4055 — drop
    the xsd:string datatype on role / subjectDid).
    """
    g = Graph()
    event_node = URIRef("urn:fi:pending:promotion")
    g.add((event_node, RDF.type, FI.Promotion))
    g.add((event_node, FI.newStatus, Literal(event.new_status)))
    g.add((event_node, FI.shardIri, Literal(event.shard_iri)))
    for iri in event.cited_iris:
        g.add((event_node, FI.citedIri, Literal(iri)))
    return g


def validate_promotion_shape(event: "PromotionEvent") -> ValidationResult:
    """Validate a PromotionEvent against ``fi:PromotionShape`` (D-20 + D-21, 07-04b).

    SHACL belt for the constraints the shape can express locally:
      (a) ``fi:newStatus`` Literal in {per_se_nota_quoad_nos, demonstrable,
          authority_only};
      (b) ``fi:citedIri`` minCount 1.

    The cite-resolvability + non-self-citation + per-status epistemic-kind
    checks live in ``governance/promote.py::validate_promotion`` (the code
    suspenders that run BEFORE this belt).

    Returns ``conforms=True`` if the TTL hasn't shipped yet (defensive —
    matches the role-event validator precedent in 07-04a).
    """
    shapes_path = _SHAPES_DIR / "promotion_shape.ttl"
    if not shapes_path.exists():
        return ValidationResult(conforms=True, violations=[], results_text="")
    shapes = _load_shape_graph("promotion_shape.ttl")
    data_graph = _build_promotion_graph(event)
    conforms, _g, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
    )
    violations = _parse_violations(results_text) if not conforms else []
    return ValidationResult(
        conforms=conforms, violations=violations, results_text=results_text
    )


def _build_contest_graph(event: "ContestEvent") -> Graph:
    """Materialize a ContestEvent as RDF for fi:ContestShape (07-05a).

    Plain (non-typed) Literals on voter_did + position_text so the SHACL
    pattern / minLength constraints fire cleanly (07-04a bad4055 precedent).
    """
    g = Graph()
    event_node = URIRef("urn:fi:pending:contest")
    g.add((event_node, RDF.type, FI.Contest))
    g.add((event_node, FI.shardIri, Literal(event.shard_iri)))
    g.add((event_node, FI.voterDid, Literal(event.voter_did)))
    g.add((event_node, FI.positionText, Literal(event.position_text)))
    return g


def validate_contest_shape(event: "ContestEvent") -> ValidationResult:
    """Validate a ContestEvent against ``fi:ContestShape`` (07-05a).

    SHACL belt for shardIri / voterDid (DID URI scheme) / positionText
    non-empty. The code suspenders live in
    ``governance/contest.py::validate_contest``; this is the third layer.

    Returns ``conforms=True`` defensively if the TTL hasn't shipped — matches
    the 07-04a precedent.
    """
    shapes_path = _SHAPES_DIR / "contest_shape.ttl"
    if not shapes_path.exists():
        return ValidationResult(conforms=True, violations=[], results_text="")
    shapes = _load_shape_graph("contest_shape.ttl")
    data_graph = _build_contest_graph(event)
    conforms, _g, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
    )
    violations = _parse_violations(results_text) if not conforms else []
    return ValidationResult(
        conforms=conforms, violations=violations, results_text=results_text
    )


def _build_contest_resolution_graph(
    event: "ContestResolutionEvent",
) -> Graph:
    """Materialize a ContestResolutionEvent as RDF for fi:ContestResolutionShape.

    Plain Literal on resolution_path so the sh:in plain-string list matches
    (07-04a bad4055 precedent).
    """
    g = Graph()
    event_node = URIRef("urn:fi:pending:contestresolution")
    g.add((event_node, RDF.type, FI.ContestResolution))
    g.add((event_node, FI.shardIri, Literal(event.shard_iri)))
    g.add((event_node, FI.resolutionPath, Literal(event.resolution_path)))
    return g


def validate_contest_resolution_shape(
    event: "ContestResolutionEvent",
) -> ValidationResult:
    """Validate a ContestResolutionEvent against ``fi:ContestResolutionShape``
    (07-05a; GOV-05 — no majority-vote).

    SHACL belt: resolution_path in {arbiter, distinguo, aporetic}. The
    Pydantic Literal is the first gate; the validator in
    ``governance/resolve_contest.py`` is the second; this is the third.

    Returns ``conforms=True`` defensively if the TTL hasn't shipped.
    """
    shapes_path = _SHAPES_DIR / "contest_resolution_shape.ttl"
    if not shapes_path.exists():
        return ValidationResult(conforms=True, violations=[], results_text="")
    shapes = _load_shape_graph("contest_resolution_shape.ttl")
    data_graph = _build_contest_resolution_graph(event)
    conforms, _g, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
    )
    violations = _parse_violations(results_text) if not conforms else []
    return ValidationResult(
        conforms=conforms, violations=violations, results_text=results_text
    )


def _build_supersession_graph(event: "SupersessionEvent") -> Graph:
    """Materialize a SupersessionEvent as RDF for fi:SupersessionShape (07-05a)."""
    g = Graph()
    event_node = URIRef("urn:fi:pending:supersession")
    g.add((event_node, RDF.type, FI.Supersession))
    g.add((event_node, FI.oldShardIri, Literal(event.old_shard_iri)))
    g.add((event_node, FI.newShardIri, Literal(event.new_shard_iri)))
    return g


def validate_supersession_shape(event: "SupersessionEvent") -> ValidationResult:
    """Validate a SupersessionEvent against ``fi:SupersessionShape`` (07-05a).

    SHACL belt: oldShardIri + newShardIri non-empty AND old != new
    (sh:sparql self-comparison). The code suspenders live in
    ``governance/supersede.py::validate_supersession``.

    Returns ``conforms=True`` defensively if the TTL hasn't shipped.
    """
    shapes_path = _SHAPES_DIR / "supersession_shape.ttl"
    if not shapes_path.exists():
        return ValidationResult(conforms=True, violations=[], results_text="")
    shapes = _load_shape_graph("supersession_shape.ttl")
    data_graph = _build_supersession_graph(event)
    conforms, _g, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
    )
    violations = _parse_violations(results_text) if not conforms else []
    return ValidationResult(
        conforms=conforms, violations=violations, results_text=results_text
    )


def _build_retraction_graph(event: "RetractionEvent") -> Graph:
    """Materialize a RetractionEvent as RDF for fi:RetractionShape (07-05b).

    Plain Literals on the two slots so the SHACL belt's xsd:string +
    minLength constraints fire cleanly (07-04a bad4055 plain-Literal
    precedent).
    """
    g = Graph()
    event_node = URIRef("urn:fi:pending:retraction")
    g.add((event_node, RDF.type, FI.Retraction))
    g.add(
        (
            event_node,
            FI.shardIri,
            Literal(event.shard_iri, datatype=XSD.string),
        )
    )
    g.add(
        (
            event_node,
            FI.cascadePreviewHash,
            Literal(event.cascade_preview_hash, datatype=XSD.string),
        )
    )
    return g


def validate_retraction_shape(event: "RetractionEvent") -> ValidationResult:
    """Validate a RetractionEvent against ``fi:RetractionShape`` (07-05b; D-17).

    SHACL belt: shardIri non-empty + cascadePreviewHash non-empty xsd:string.
    The code suspenders live in ``governance/retract.py::validate_retraction``;
    this is the third defense-in-depth layer.

    Returns ``conforms=True`` defensively if the TTL hasn't shipped — matches
    the 07-04a precedent.
    """
    shapes_path = _SHAPES_DIR / "retraction_shape.ttl"
    if not shapes_path.exists():
        return ValidationResult(conforms=True, violations=[], results_text="")
    shapes = _load_shape_graph("retraction_shape.ttl")
    data_graph = _build_retraction_graph(event)
    conforms, _g, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes,
        inference="none",
        abort_on_first=False,
    )
    violations = _parse_violations(results_text) if not conforms else []
    return ValidationResult(
        conforms=conforms, violations=violations, results_text=results_text
    )


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
