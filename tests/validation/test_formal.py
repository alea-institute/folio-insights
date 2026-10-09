"""Phase 9 U1 (KTD4): formal content extraction and the OWL N-Triples document."""
from __future__ import annotations

import pytest

from folio_insights.shards import Triple
from folio_insights.validation.formal import (
    OWL_DISJOINT_WITH,
    RDF_TYPE,
    RDFS_SUBCLASS_OF,
    dependency_axioms,
    is_iri,
    owl_ntriples,
    shard_axioms,
    tbox_slice,
)

from tests.validation.conftest import folio, iri, vshard


def test_only_all_iri_untyped_triples_are_formal() -> None:
    assert shard_axioms(vshard(1)) == ()  # plain-text triple
    formal = vshard(2, triple=Triple(subject="urn:x:a", predicate=RDF_TYPE, object=folio("A")))
    assert shard_axioms(formal) == (("urn:x:a", RDF_TYPE, folio("A")),)
    literal = vshard(3, triple=Triple(subject="urn:x:a", predicate="urn:x:p", object="urn:x:o",
                                      object_datatype="http://www.w3.org/2001/XMLSchema#string"))
    assert shard_axioms(literal) == ()
    assert not is_iri("has space:x") and not is_iri("_:b0") and is_iri("urn:folio:shard/1")


def test_dependency_edges_become_fi_assertions() -> None:
    s = vshard(1, depends_on_shards=[iri(2)], elaborates=[iri(3)], depends_on_axioms=[iri(1)])
    assert sorted(p.rsplit("/", 1)[1] for _, p, _ in dependency_axioms(s)) == [
        "dependsOnShard", "elaborates"]  # the self-reference is dropped


def test_tbox_slice_follows_reachable_terms_and_drops_literals() -> None:
    a, b, c, d = (folio(x) for x in "ABCD")
    tbox = [
        (a, RDFS_SUBCLASS_OF, b),
        (b, RDFS_SUBCLASS_OF, c),
        (d, OWL_DISJOINT_WITH, c),          # symmetric: reached through c
        (folio("Z"), RDFS_SUBCLASS_OF, folio("Y")),  # unreachable
        (a, "http://www.w3.org/2000/01/rdf-schema#label", "not an IRI"),
    ]
    assert tbox_slice(tbox, {a}) == sorted([(a, RDFS_SUBCLASS_OF, b), (b, RDFS_SUBCLASS_OF, c),
                                            (d, OWL_DISJOINT_WITH, c)])


def test_owl_document_declares_terms_and_is_deterministic() -> None:
    triples = [("urn:x:i", RDF_TYPE, folio("A")), (folio("A"), OWL_DISJOINT_WITH, folio("B")),
               ("urn:x:i", "urn:x:rel", "urn:x:j")]
    doc = owl_ntriples(triples, ontology_iri="urn:x:onto")
    assert doc == owl_ntriples(list(reversed(triples)), ontology_iri="urn:x:onto")
    lines = doc.splitlines()
    assert lines[0] == "<urn:x:onto> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> " \
                       "<http://www.w3.org/2002/07/owl#Ontology> ."
    assert f"<{folio('B')}> <{RDF_TYPE}> <http://www.w3.org/2002/07/owl#Class> ." in lines
    assert f"<urn:x:rel> <{RDF_TYPE}> <http://www.w3.org/2002/07/owl#ObjectProperty> ." in lines
    assert f"<urn:x:j> <{RDF_TYPE}> <http://www.w3.org/2002/07/owl#NamedIndividual> ." in lines
    with pytest.raises(ValueError):
        owl_ntriples([("urn:x:i", "urn:x:p", "a literal")], ontology_iri="urn:x:onto")
