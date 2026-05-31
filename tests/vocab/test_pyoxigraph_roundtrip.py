"""Phase 8 Plan 08-04 Task 2 — rdflib + pyoxigraph round-trip + per-predicate IRI queryability.

Tests 4 + 5 close checker warning W-1 by exercising per-predicate IRI
queryability for VOCAB-02 (4 analogia predicates + 4 distinction kinds) and
VOCAB-03 (5 elaboration / dependency / closure / predication-mode predicates)
against BOTH the rdflib graph and the pyoxigraph store. Plan 08-01 / 08-03
chose the distinction-kind modeling route (NamedIndividual in
predicates.ttl OR sh:in literal in shapes.ttl); the test accepts either.

VOCAB-01 acceptance gate 1: "TTL parses with both rdflib and pyoxigraph;
owl:versionIRI stable" — covered by tests 1, 2, and the companion
``test_owl_version_iri.py``.

PITFALLS D7 mitigation: pyoxigraph 0.5.7 silently returns empty on
RDF-star ``<<`` / ``>>`` patterns. Test 3 grep-asserts zero hits across
the 5 vocab TTL files.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import pytest
from rdflib import OWL, RDF, URIRef

from folio_insights.vocab import FI_PREFIX, load_graph, load_pyoxigraph_store

# ---------------------------------------------------------------------------
# VOCAB-02 + VOCAB-03 predicate IRIs (W-1 fix)
# ---------------------------------------------------------------------------

VOCAB_02_03_PREDICATE_LOCAL_NAMES: tuple[str, ...] = (
    # VOCAB-02 (analogia + distinguo) — 4 predicates
    "primeAnalogate",
    "proportionalRelation",
    "distinguishes",
    "distinctionKind",
    # VOCAB-03 (Tractarian / Spinozan / Russellian / Aristotelian) — 5 predicates
    "elaborates",
    "dependsOnAxiom",
    "dependsOnDefinition",
    "closureMarker",
    "predicationMode",
)

DISTINCTION_KIND_VALUES: tuple[str, ...] = (
    "realis",
    "rationis",
    "rationis_cum_fundamento_in_re",
    "analogica",
)

_TTL_FILE_NAMES: tuple[str, ...] = (
    "predicates.ttl",
    "classes.ttl",
    "bfo_spine.ttl",
    "bfo_mapping.ttl",
    "shapes.ttl",
)

_OWL_PREFIX = "PREFIX owl: <http://www.w3.org/2002/07/owl#>"


# ---------------------------------------------------------------------------
# 1. pyoxigraph parses all 5 TTL files + ≥5 ontologies
# ---------------------------------------------------------------------------


def test_pyoxigraph_loads_all_five_ttl_files() -> None:
    """pyoxigraph.Store.load() succeeds for all 5 TTL files; ≥5 ontology IRIs visible."""
    store = load_pyoxigraph_store()
    assert len(store) > 0, "pyoxigraph store must have at least one quad after loading"

    results = list(
        store.query(f"{_OWL_PREFIX} SELECT ?ont WHERE {{ ?ont a owl:Ontology }}")
    )
    assert len(results) >= 5, (
        f"Expected ≥5 owl:Ontology declarations (one per TTL file); got {len(results)}"
    )


# ---------------------------------------------------------------------------
# 2. rdflib ↔ pyoxigraph parity at the ontology-IRI level (D-09 / VOCAB-01)
# ---------------------------------------------------------------------------


def test_rdflib_pyoxigraph_parity_on_ontology_iris() -> None:
    """The ontology-IRI set must be identical in rdflib vs pyoxigraph."""
    rdflib_g = load_graph(include_bfo_mapping=True)
    pyox_s = load_pyoxigraph_store()

    rdflib_iris = {
        str(s)
        for s in rdflib_g.subjects(RDF.type, OWL.Ontology)
    }
    pyox_iris = {
        str(row["ont"])
        for row in pyox_s.query(
            f"{_OWL_PREFIX} SELECT ?ont WHERE {{ ?ont a owl:Ontology }}"
        )
    }

    assert rdflib_iris == pyox_iris, (
        "rdflib and pyoxigraph disagree on the ontology IRI set:\n"
        f"  only in rdflib:    {sorted(rdflib_iris - pyox_iris)}\n"
        f"  only in pyoxigraph: {sorted(pyox_iris - rdflib_iris)}"
    )
    # And there should be ≥5 (one per file).
    assert len(rdflib_iris) >= 5


# ---------------------------------------------------------------------------
# 3. PITFALLS D7 mitigation — no RDF-star syntax in any vocab TTL
# ---------------------------------------------------------------------------


def test_no_rdf_star_syntax_in_vocab_ttls() -> None:
    """PITFALLS D7: pyoxigraph 0.5.7 dropped rdf-star; reject any ``<<`` / ``>>`` triple-term syntax."""
    pkg_root = files("folio_insights.vocab")
    offenders: list[str] = []
    for name in _TTL_FILE_NAMES:
        text = (pkg_root / name).read_text(encoding="utf-8")  # type: ignore[union-attr]
        if "<<" in text or ">>" in text:
            offenders.append(name)
    assert not offenders, (
        f"PITFALLS D7 violation: RDF-star syntax found in {offenders}; "
        "pyoxigraph 0.5.7 silently returns empty against << / >> patterns."
    )


# ---------------------------------------------------------------------------
# 4. Per-predicate IRI queryability (W-1 fix — VOCAB-02 + VOCAB-03)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stores():
    """Pre-load both stores once per module — keeps the 13 parameterized cases fast."""
    return load_graph(include_bfo_mapping=True), load_pyoxigraph_store()


@pytest.mark.parametrize("local_name", VOCAB_02_03_PREDICATE_LOCAL_NAMES)
def test_vocab_02_03_predicate_iris_queryable_in_both_stores(local_name: str, stores) -> None:
    """Each VOCAB-02/-03 predicate IRI must resolve to ≥1 owl:*Property declaration in BOTH stores."""
    rdflib_g, pyox_s = stores
    iri = f"{FI_PREFIX}{local_name}"

    # rdflib side — use the graph API (more reliable than parameterized SPARQL).
    pred_uri = URIRef(iri)
    rdflib_types = {
        str(t) for t in rdflib_g.objects(pred_uri, RDF.type)
        if t in (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty)
    }
    rdflib_ok = bool(rdflib_types)

    # pyoxigraph side — parameterise via SPARQL VALUES (no f-string IRI interpolation
    # into a parser, just a clean BIND-style probe).
    pyox_query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        SELECT ?type WHERE {{
            <{iri}> a ?type .
            FILTER(?type = owl:ObjectProperty
                || ?type = owl:DatatypeProperty
                || ?type = owl:AnnotationProperty)
        }}
    """
    pyox_rows = list(pyox_s.query(pyox_query))
    pyox_ok = bool(pyox_rows)

    failures = []
    if not rdflib_ok:
        failures.append("rdflib")
    if not pyox_ok:
        failures.append("pyoxigraph")
    assert not failures, (
        f"fi:{local_name} (IRI {iri}) not declared as owl:*Property in: {failures}"
    )


# ---------------------------------------------------------------------------
# 5. Per-distinction-kind queryability (W-1 fix — VOCAB-02 distinction kinds)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", DISTINCTION_KIND_VALUES)
def test_vocab_02_distinction_kinds_queryable_in_both_stores(kind: str, stores) -> None:
    """Each Scotist distinction kind must be evidenced via Route A or Route B in BOTH stores."""
    rdflib_g, pyox_s = stores

    # Route A — NamedIndividual in predicates.ttl
    route_a_rdflib = (URIRef(f"{FI_PREFIX}{kind}"), RDF.type, OWL.NamedIndividual) in rdflib_g
    route_a_pyox_rows = list(pyox_s.query(f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        ASK {{
            <{FI_PREFIX}{kind}> a ?t .
            FILTER(?t = owl:NamedIndividual
                || ?t = <{FI_PREFIX}DistinctionKind>)
        }}
    """))
    route_a_pyox = bool(route_a_pyox_rows) and bool(route_a_pyox_rows[0])

    # Route B — sh:in literal in shapes.ttl (or anywhere in vocab)
    route_b_query = f"""
        PREFIX sh: <http://www.w3.org/ns/shacl#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        ASK {{
            ?shape sh:in/rdf:rest*/rdf:first "{kind}" .
        }}
    """
    route_b_rdflib_rows = list(rdflib_g.query(route_b_query))
    route_b_rdflib = bool(route_b_rdflib_rows) and bool(route_b_rdflib_rows[0])
    route_b_pyox_rows = list(pyox_s.query(route_b_query))
    route_b_pyox = bool(route_b_pyox_rows) and bool(route_b_pyox_rows[0])

    rdflib_ok = route_a_rdflib or route_b_rdflib
    pyox_ok = route_a_pyox or route_b_pyox

    routes = (
        f"Route A (NamedIndividual): rdflib={route_a_rdflib} pyoxigraph={route_a_pyox} | "
        f"Route B (sh:in literal): rdflib={route_b_rdflib} pyoxigraph={route_b_pyox}"
    )
    assert rdflib_ok and pyox_ok, (
        f"Distinction kind {kind!r} not queryable in both stores. {routes}"
    )
