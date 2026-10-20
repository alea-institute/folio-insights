"""Phase 9 U6: the detector reads P1 clusters and P2 frameworks; fi:inFramework is an IRI."""
from __future__ import annotations

import pytest
from pyoxigraph import NamedNode, RdfFormat
from pyoxigraph import parse as rdf_parse

from folio_insights.models.framework import FrameworkRegistry
from folio_insights.polysemy.candidates import polysemy_candidates
from folio_insights.polysemy.detector import detect_polysemy
from folio_insights.polysemy.fixture_loader import (
    ShardFixture,
    consideration_fixtures_to_ttl,
)
from folio_insights.polysemy.prototype_cluster import build_prototype_cluster
from folio_insights.polysemy.tbox import disjointness_seed_ttl, load_tbox_seeds
from folio_insights.shards import Triple
from folio_insights.store.pyoxigraph_store import PyoxigraphStore
from folio_insights.validation.clusters import ClusterBuilder
from folio_insights.vocab._constants import framework_iri
from tests.validation.conftest import folio, vshard

pytestmark = pytest.mark.polysemy_spike

CL, LA = "us.common_law", "us.louisiana.civil_code"
CONCEPT = folio("Consideration")


def _about(n: int, framework_id: str, axiom: str):  # noqa: ANN202
    return vshard(
        n,
        framework_id=framework_id,
        triple=Triple(subject=CONCEPT, predicate="urn:x:p", object="synthetic object"),
        logical_form_imputed=axiom,
    )


def test_candidates_come_from_clusters_and_registry() -> None:
    registry = FrameworkRegistry.with_defaults()
    shards = [
        _about(1, CL, "A promise binds when bargained for."),
        _about(2, CL, "Detriment to the promisee supports a promise."),
        _about(3, LA, "An obligation needs a lawful cause."),
        _about(4, "us.unregistered_body", "Never resolved into a framework."),
        vshard(5, triple=Triple(subject=folio("Lease"), predicate="urn:x:p", object="o")),
    ]
    clusters = ClusterBuilder(registry=registry).build(shards)
    found = polysemy_candidates(shards, clusters, registry)

    assert [(c.term, c.concept) for c in found.candidates] == [("consideration", CONCEPT)]
    candidate = found.candidates[0]
    assert candidate.frameworks == (CL, LA)
    assert [s.iri for s in candidate.shards] == [shards[0].shard_iri, shards[1].shard_iri,
                                                 shards[2].shard_iri]
    assert all(s.axiom_summary == s0.logical_form_imputed
               for s, s0 in zip(candidate.shards, shards[:3]))
    assert all(c.startswith("doctrinal:") for c in candidate.clusters)
    assert found.unregistered_frameworks == {"us.unregistered_body": [shards[3].shard_iri]}


def test_concept_term_keys() -> None:
    from folio_insights.polysemy.candidates import concept_term

    assert concept_term(folio("Consideration")) == "consideration"
    assert concept_term("urn:x:vocab#GoodFaith") == "good faith"
    assert concept_term("urn:x:vocab/marital_property/") == "marital property"


def test_concept_label_overrides_the_local_name() -> None:
    registry = FrameworkRegistry.with_defaults()
    shards = [_about(1, CL, "a"), _about(2, LA, "b")]
    clusters = ClusterBuilder(registry=registry).build(shards)
    found = polysemy_candidates(shards, clusters, registry,
                                concept_label=lambda iri: "  Bargained  Consideration ")
    assert [c.term for c in found.candidates] == ["bargained consideration"]
    assert {s.term for s in found.candidates[0].shards} == {"bargained consideration"}


def test_single_framework_concept_is_not_a_candidate() -> None:
    registry = FrameworkRegistry.with_defaults()
    shards = [_about(1, CL, "a"), _about(2, CL, "b")]
    clusters = ClusterBuilder(registry=registry).build(shards)
    assert polysemy_candidates(shards, clusters, registry).candidates == []


def test_candidate_runs_through_the_detector() -> None:
    """End to end: cluster -> candidate -> prototype cluster -> Rule 1 on seeds."""
    registry = FrameworkRegistry.with_defaults()
    shards = [_about(n, CL, f"Bargained-for exchange element {n}.") for n in range(1, 4)]
    shards += [_about(n, LA, f"Lawful cause element {n}.") for n in range(4, 7)]
    candidate = polysemy_candidates(
        shards, ClusterBuilder(registry=registry).build(shards), registry
    ).candidates[0]
    store = PyoxigraphStore(path=None)
    cluster = build_prototype_cluster(list(candidate.shards))
    assert detect_polysemy(cluster, store).matched_rules == ["R1-no-conflict"]
    load_tbox_seeds(store, disjointness_seed_ttl(candidate.term, [(CL, LA)]))
    assert detect_polysemy(cluster, store).matched_rules != ["R1-no-conflict"]


def test_in_framework_is_an_iri_for_ids_and_labels() -> None:
    rows = [
        ShardFixture(iri="urn:x:s1", framework=LA, source_doc="d", extracted_text="t",
                     axiom_summary="a"),
        ShardFixture(iri="urn:x:s2", framework="CommonLaw", source_doc="d", extracted_text="t",
                     axiom_summary="a"),
    ]
    triples = list(rdf_parse(consideration_fixtures_to_ttl(rows).encode(), format=RdfFormat.TURTLE))
    objects = {t.object for t in triples if t.predicate.value.endswith("vocab/inFramework")}
    assert objects == {NamedNode(framework_iri(LA)), NamedNode(framework_iri(CL))}


def test_fixture_refuses_an_unknown_framework_tag() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ShardFixture(iri="urn:x", framework="Civil Law!", source_doc="d", extracted_text="t",
                     axiom_summary="a")
