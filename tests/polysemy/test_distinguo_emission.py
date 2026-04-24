"""Phase 1 distinguo emission tests — VOCAB-02.

Plan 01-04 flips the 3 Wave-0 xfail placeholders to 9 real tests covering:

Task 1 (this module, tests 1-5):
  - Atomic-triad invariant (Pitfall 5 guard) enforced at pydantic construction
  - distinction_kind Literal enum forbids a 5th value
  - validate_fork_proposal_shape() as defense-in-depth for model_construct bypass

Task 2 (tests 6-9):
  - emit_fork_ttl() shape (prefix, predicates, literal form for distinctionKind)
  - TTL round-trip via pyoxigraph bulk_load under urn:folio:proposal/<cluster_id>
  - Pre-emit validator catches model_construct bypass
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from folio_insights.polysemy.distinguo import (
    FI_VOCAB,
    ForkProposal,
    emit_fork_ttl,
    validate_fork_proposal_shape,
)

pytestmark = pytest.mark.polysemy_spike


# ---- canonical example values (reused across the suite) ----
CLUSTER_ID = "a1b2c3d4"
TERM = "consideration"
PRIME_IRI = "urn:folio:term/consideration#restatement"
PROP_RELATION = "bargained-for exchange (CL) ↔ bargain + mutual inducement (R2d)"
FRAMEWORKS = ("CommonLaw", "Restatement2d")
REVIEWER_DID = "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"
CREATED_AT = "2026-04-24T17:30:00+00:00"


def _complete_fork(**overrides) -> ForkProposal:
    """Build a canonical analogia fork with all 4 required fields present."""
    kwargs = dict(
        term=TERM,
        cluster_id=CLUSTER_ID,
        uses_analogousTo=True,
        prime_analogate=PRIME_IRI,
        proportional_relation=PROP_RELATION,
        distinction_kind="analogica",
        source_frameworks=FRAMEWORKS,
        reviewer_did=REVIEWER_DID,
        created_at_iso=CREATED_AT,
    )
    kwargs.update(overrides)
    return ForkProposal(**kwargs)


# =========================================================================
# Task 1 — model invariants + validator
# =========================================================================


def test_analogousTo_requires_sub_properties() -> None:
    """uses_analogousTo=True + prime_analogate=None raises ValidationError
    at construction time (fail-fast; Pitfall 5 atomic-triad guard)."""
    with pytest.raises(ValidationError) as exc_info:
        ForkProposal(
            term=TERM,
            cluster_id=CLUSTER_ID,
            uses_analogousTo=True,
            prime_analogate=None,  # MISSING — triggers the guard
            proportional_relation=PROP_RELATION,
            distinction_kind="analogica",
            source_frameworks=FRAMEWORKS,
            reviewer_did=REVIEWER_DID,
            created_at_iso=CREATED_AT,
        )
    assert "prime_analogate" in str(exc_info.value)


def test_analogousTo_requires_sub_properties_relation() -> None:
    """uses_analogousTo=True + proportional_relation=None raises ValidationError
    at construction time (Pitfall 5 atomic-triad guard — relation branch)."""
    with pytest.raises(ValidationError) as exc_info:
        ForkProposal(
            term=TERM,
            cluster_id=CLUSTER_ID,
            uses_analogousTo=True,
            prime_analogate=PRIME_IRI,
            proportional_relation=None,  # MISSING — triggers the guard
            distinction_kind="analogica",
            source_frameworks=FRAMEWORKS,
            reviewer_did=REVIEWER_DID,
            created_at_iso=CREATED_AT,
        )
    assert "proportional_relation" in str(exc_info.value)


def test_distinctionKind_enum() -> None:
    """A 5th distinction_kind value (not in the Literal) raises ValidationError
    at construction time — VOCAB-02 4-enum lock."""
    with pytest.raises(ValidationError) as exc_info:
        ForkProposal(
            term=TERM,
            cluster_id=CLUSTER_ID,
            uses_analogousTo=True,
            prime_analogate=PRIME_IRI,
            proportional_relation=PROP_RELATION,
            distinction_kind="analogy",  # 5th value — not in Literal
            source_frameworks=FRAMEWORKS,
            reviewer_did=REVIEWER_DID,
            created_at_iso=CREATED_AT,
        )
    assert "distinction_kind" in str(exc_info.value)


def test_validate_fork_proposal_shape_happy_path() -> None:
    """A fully-populated analogia fork passes validate_fork_proposal_shape
    with no exception (returns None)."""
    fork = _complete_fork()
    # Must not raise and must return None explicitly.
    assert validate_fork_proposal_shape(fork) is None


def test_fork_without_analogousTo_allows_missing_subproperties() -> None:
    """A plain distinctio-rationis fork (uses_analogousTo=False) is valid
    even when prime_analogate AND proportional_relation are both None —
    a simple distinctio rationis does NOT need the analogia triad."""
    fork = ForkProposal(
        term=TERM,
        cluster_id=CLUSTER_ID,
        uses_analogousTo=False,
        prime_analogate=None,
        proportional_relation=None,
        distinction_kind="rationis",
        source_frameworks=FRAMEWORKS,
        reviewer_did=REVIEWER_DID,
        created_at_iso=CREATED_AT,
    )
    # Pydantic accepted it; validator also accepts it.
    assert fork.uses_analogousTo is False
    assert validate_fork_proposal_shape(fork) is None


def test_to_proposed_fork_projects_down() -> None:
    """ForkProposal.to_proposed_fork() projects to the canonical JSONL
    shape — preserves uses_analogousTo and copies source_frameworks tuple
    into the JSONL frameworks list (for 01-05 CLI modify path)."""
    fork = _complete_fork()
    pf = fork.to_proposed_fork()
    assert pf.cluster_id == CLUSTER_ID
    assert pf.term == TERM
    assert pf.uses_analogousTo is True
    assert pf.prime_analogate == PRIME_IRI
    assert pf.proportional_relation == PROP_RELATION
    assert pf.distinction_kind == "analogica"
    assert pf.frameworks == list(FRAMEWORKS)


# =========================================================================
# Task 2 — emit_fork_ttl + pyoxigraph round-trip
# =========================================================================


def test_emit_fork_ttl_shape() -> None:
    """emit_fork_ttl() output carries the canonical analogia triad shape:
    fi: prefix declared; fi:analogousTo + fi:primeAnalogate +
    fi:proportionalRelation + fi:distinctionKind all present; distinctionKind
    emitted as a string literal (not an IRI)."""
    fork = _complete_fork()
    ttl = emit_fork_ttl(fork)

    assert ttl.startswith(
        f"@prefix fi: <{FI_VOCAB}> ."
    ), f"Must start with fi: prefix, got: {ttl[:80]!r}"
    assert "fi:analogousTo" in ttl
    assert "fi:primeAnalogate" in ttl
    assert "fi:proportionalRelation" in ttl
    assert "fi:distinctionKind" in ttl
    # distinctionKind value MUST be a quoted literal, NOT an IRI.
    assert '"analogica"' in ttl
    assert "<analogica>" not in ttl
    assert f"<{FI_VOCAB}analogica>" not in ttl


def test_ttl_roundtrip_pyoxigraph() -> None:
    """Emitted TTL loaded into pyoxigraph under urn:folio:proposal/<cluster_id>
    survives SPARQL SELECT: fi:primeAnalogate resolves to the expected IRI."""
    import pyoxigraph

    from folio_insights.store.pyoxigraph_store import PyoxigraphStore

    fork = _complete_fork()
    ttl = emit_fork_ttl(fork)
    graph_iri = f"urn:folio:proposal/{fork.cluster_id}"
    graph_name = pyoxigraph.NamedNode(graph_iri)

    wrapper = PyoxigraphStore(path=None)
    wrapper.store.bulk_load(
        ttl.encode("utf-8"),
        pyoxigraph.RdfFormat.TURTLE,
        to_graph=graph_name,
    )

    rows = wrapper.query_rdf12(
        f"""
        PREFIX fi: <{FI_VOCAB}>
        SELECT ?o WHERE {{
            GRAPH <{graph_iri}> {{
                ?s fi:primeAnalogate ?o
            }}
        }}
        """,
    )
    assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
    # pyoxigraph QuerySolution: rows[0]["o"] is a NamedNode; str(NamedNode) is "<iri>"
    o_node = rows[0]["o"]
    assert isinstance(o_node, pyoxigraph.NamedNode)
    assert o_node.value == fork.prime_analogate


def test_ttl_roundtrip_preserves_distinctionKind() -> None:
    """fi:distinctionKind round-trips as a plain string literal
    (not coerced to an IRI). Also implicitly confirms fi:analogousTo
    and fi:proportionalRelation are in the same graph (atomic triad)."""
    import pyoxigraph

    from folio_insights.store.pyoxigraph_store import PyoxigraphStore

    fork = _complete_fork()
    ttl = emit_fork_ttl(fork)
    graph_iri = f"urn:folio:proposal/{fork.cluster_id}"

    wrapper = PyoxigraphStore(path=None)
    wrapper.store.bulk_load(
        ttl.encode("utf-8"),
        pyoxigraph.RdfFormat.TURTLE,
        to_graph=pyoxigraph.NamedNode(graph_iri),
    )

    rows = wrapper.query_rdf12(
        f"""
        PREFIX fi: <{FI_VOCAB}>
        SELECT ?k WHERE {{
            GRAPH <{graph_iri}> {{
                ?s fi:distinctionKind ?k
            }}
        }}
        """,
    )
    assert len(rows) == 1
    k_node = rows[0]["k"]
    assert isinstance(k_node, pyoxigraph.Literal)
    assert k_node.value == "analogica"

    # Atomic triad sanity — all three predicates present in the same graph.
    triad_rows = wrapper.query_rdf12(
        f"""
        PREFIX fi: <{FI_VOCAB}>
        SELECT ?p WHERE {{
            GRAPH <{graph_iri}> {{
                ?s ?p ?o
                FILTER(?p IN (
                    fi:analogousTo,
                    fi:primeAnalogate,
                    fi:proportionalRelation
                ))
            }}
        }}
        """,
    )
    present = {row["p"].value for row in triad_rows}
    assert present == {
        f"{FI_VOCAB}analogousTo",
        f"{FI_VOCAB}primeAnalogate",
        f"{FI_VOCAB}proportionalRelation",
    }, f"Atomic triad missing: {present}"


def test_emit_refuses_invalid_shape_defense_in_depth() -> None:
    """A fork built via model_construct() (bypasses the pydantic validator)
    with uses_analogousTo=True + prime_analogate=None MUST be rejected by
    emit_fork_ttl's preflight validate_fork_proposal_shape call."""
    # model_construct bypasses field validators AND model validators.
    bypassed = ForkProposal.model_construct(
        term=TERM,
        cluster_id=CLUSTER_ID,
        uses_analogousTo=True,
        prime_analogate=None,  # would have raised via pydantic; bypassed here
        proportional_relation=PROP_RELATION,
        distinction_kind="analogica",
        source_frameworks=FRAMEWORKS,
        reviewer_did=REVIEWER_DID,
        created_at_iso=CREATED_AT,
    )
    with pytest.raises(ValueError) as exc_info:
        emit_fork_ttl(bypassed)
    assert "prime_analogate" in str(exc_info.value)
