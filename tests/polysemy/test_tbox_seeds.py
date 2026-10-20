"""Phase 9 U6 (decision 7): owl:disjointWith seeds give Rule 1 something real to read."""
from __future__ import annotations

import pytest
from pyoxigraph import RdfFormat
from pyoxigraph import parse as rdf_parse

from folio_insights.polysemy.tbox import (
    TBOX_GRAPH_IRI,
    disjointness_seed_ttl,
    framework_conflicts,
    has_framework_conflicting_axiom,
    load_tbox_seeds,
    seed_ttl,
    term_class_iri,
)
from folio_insights.reason.el_profile import check_el_profile
from folio_insights.reason.reasoner import SubsumptionReasoner, SubsumptionResult
from folio_insights.reason.structural import StructuralReasoner
from folio_insights.store.pyoxigraph_store import PyoxigraphStore

pytestmark = pytest.mark.polysemy_spike

CL, LA, R2, FRE = "us.common_law", "us.louisiana.civil_code", "us.restatement_2d.contracts", "us.federal.fre"


@pytest.fixture
def seeded() -> PyoxigraphStore:
    store = PyoxigraphStore(path=None)
    load_tbox_seeds(store)
    return store


def test_tbox_graph_is_the_shared_tbox() -> None:
    from folio_insights.storage.projection import TBOX_GRAPH

    assert TBOX_GRAPH_IRI == TBOX_GRAPH.value


def test_term_class_iri_accepts_labels_and_ids() -> None:
    assert term_class_iri("consideration", "CommonLaw") == "urn:folio:term/consideration#us.common_law"
    assert term_class_iri("consideration", LA) == "urn:folio:term/consideration#us.louisiana.civil_code"
    assert term_class_iri("good faith", "us.ucc") == "urn:folio:term/good%20faith#us.ucc"


def test_shipped_seeds_are_el_and_registered() -> None:
    from folio_insights.models.framework import FrameworkRegistry

    triples = list(rdf_parse(seed_ttl().encode("utf-8"), format=RdfFormat.TURTLE))
    assert any(t.predicate.value.endswith("#disjointWith") for t in triples)
    assert check_el_profile(triples) == []
    registry = FrameworkRegistry.with_defaults()
    for t in triples:
        framework_id = t.subject.value.split("#", 1)[1]
        registry.resolve(framework_id)


def test_rule1_reads_the_seeds(seeded: PyoxigraphStore) -> None:
    assert has_framework_conflicting_axiom(seeded, "consideration", [CL, LA])
    assert has_framework_conflicting_axiom(seeded, "consideration", ["CommonLaw", "CivilLaw"])
    assert has_framework_conflicting_axiom(seeded, "consideration", [FRE, R2])
    # The bargain-based senses are not stated disjoint.
    assert not has_framework_conflicting_axiom(seeded, "consideration", [CL, R2])


def test_rule1_is_joined_to_term_and_frameworks(seeded: PyoxigraphStore) -> None:
    """The spike's ASK matched any disjointWith anywhere; this one does not."""
    assert not has_framework_conflicting_axiom(seeded, "lease", [CL, LA])
    assert not has_framework_conflicting_axiom(seeded, "consideration", [CL, "us.federal.frcp"])


def test_seeds_in_another_graph_are_not_read() -> None:
    store = PyoxigraphStore(path=None)
    load_tbox_seeds(store, graph="urn:x:elsewhere")
    assert not has_framework_conflicting_axiom(store, "consideration", [CL, LA])


def test_structural_reasoner_closure_and_evidence() -> None:
    store = PyoxigraphStore(path=None)
    ttl = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "<urn:x:A1> rdfs:subClassOf <urn:x:A> .\n"
        "<urn:x:B1> rdfs:subClassOf <urn:x:B> .\n"
        "<urn:x:B> owl:disjointWith <urn:x:A> .\n"
    )
    load_tbox_seeds(store, ttl)
    reasoner = StructuralReasoner(store, TBOX_GRAPH_IRI)
    assert isinstance(reasoner, SubsumptionReasoner)
    result = reasoner.are_disjoint("urn:x:A1", "urn:x:B1")
    assert isinstance(result, SubsumptionResult)
    assert result.holds and result.relation == "disjoint_with"
    assert result.evidence == (("urn:x:B", "http://www.w3.org/2002/07/owl#disjointWith", "urn:x:A"),)
    assert reasoner.is_subclass_of("urn:x:A1", "urn:x:A").holds
    assert reasoner.is_subclass_of("urn:x:A1", "urn:x:A1").holds
    assert not reasoner.is_subclass_of("urn:x:A", "urn:x:A1").holds
    assert not reasoner.are_disjoint("urn:x:A1", "urn:x:A").holds


def test_iris_are_never_spliced_into_query_text() -> None:
    """A term such as "service" must not trip the SEC-01 SERVICE preflight."""
    store = PyoxigraphStore(path=None)
    load_tbox_seeds(store, disjointness_seed_ttl("service", [(CL, "us.federal.frcp")]))
    found = framework_conflicts(store, "service", ["us.federal.frcp", CL])
    assert [r.holds for r in found] == [True]
