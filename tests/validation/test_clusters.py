"""Phase 9 U1 (R4): ``ClusterBuilder`` on its four axes. Synthetic shards only."""
from __future__ import annotations

import pytest

from folio_insights.bfo.spine import ParentMapResolver
from folio_insights.shards import Triple
from folio_insights.validation.clusters import ClusterBuilder, shard_concepts

from tests.validation.conftest import folio, iri, vshard


def keyed(cluster_set, axis):
    return {c.key: c.members for c in cluster_set.by_axis(axis)}


def test_source_axis_groups_by_document_and_drops_singletons() -> None:
    shards = [
        vshard(1, source_uri="urn:x:doc/a"),
        vshard(2, source_uri="urn:x:doc/a"),
        vshard(3, source_uri="urn:x:doc/b"),
    ]
    result = ClusterBuilder(axes=["source"]).build(shards)
    assert keyed(result, "source") == {"urn:x:doc/a": (iri(1), iri(2))}
    assert result.clusters[0].id == "source:urn:x:doc/a"
    assert result.shard_count == 3


def test_tractarian_subtree_follows_primary_elaborates_parent() -> None:
    # 1 <- 2 <- 3 ; 4 elaborates 3 first (primary) and 6 second ; 5 is a lone root;
    # 6 <- 7. An out-of-corpus first parent is skipped in favour of the next one.
    shards = [
        vshard(1),
        vshard(2, elaborates=[iri(1)]),
        vshard(3, elaborates=[iri(2)]),
        vshard(4, elaborates=[iri(3), iri(6)]),
        vshard(5),
        vshard(6),
        vshard(7, elaborates=["urn:folio:shard/" + "f" * 32, iri(6)]),
    ]
    result = ClusterBuilder(axes=["tractarian"]).build(shards)
    assert keyed(result, "tractarian") == {
        iri(1): (iri(1), iri(2), iri(3), iri(4)),
        iri(6): (iri(6), iri(7)),
    }
    assert result.elaborates_cycles == []


def test_tractarian_loop_is_rooted_at_its_smallest_iri_and_reported() -> None:
    shards = [
        vshard(1, elaborates=[iri(3)]),
        vshard(2, elaborates=[iri(1)]),
        vshard(3, elaborates=[iri(2)]),
        vshard(4, elaborates=[iri(2)]),
    ]
    result = ClusterBuilder(axes=["tractarian"]).build(shards)
    assert keyed(result, "tractarian") == {iri(1): (iri(1), iri(2), iri(3), iri(4))}
    assert result.elaborates_cycles == [(iri(1), iri(3), iri(2))]


PARENTS = {
    folio("BreachOfContract"): [folio("ContractLaw")],
    folio("AnticipatoryRepudiation"): [folio("BreachOfContract")],
    folio("Consideration"): [folio("ContractFormation")],
    folio("ContractFormation"): [folio("ContractLaw")],
    folio("ContractLaw"): [folio("AreaOfLaw")],
    folio("Negligence"): [folio("TortLaw")],
    folio("TortLaw"): [folio("AreaOfLaw")],
    # A multi-parent concept: both a contract and a tort topic.
    folio("Misrepresentation"): [folio("ContractLaw"), folio("TortLaw")],
}


def concept_shard(n: int, concept: str):
    return vshard(n, triple=Triple(subject=concept, predicate="urn:x:p", object="urn:x:o"))


def test_doctrinal_axis_shares_an_ancestor_at_the_configured_depth() -> None:
    shards = [
        concept_shard(1, folio("AnticipatoryRepudiation")),
        concept_shard(2, folio("Consideration")),
        concept_shard(3, folio("Negligence")),
        concept_shard(4, folio("Misrepresentation")),
        concept_shard(5, folio("BreachOfContract")),
        vshard(6),  # no FOLIO concept at all
    ]
    resolver = ParentMapResolver(PARENTS)
    depth1 = ClusterBuilder(axes=["doctrinal"], folio_resolver=resolver, doctrinal_depth=1).build(shards)
    assert keyed(depth1, "doctrinal") == {
        folio("ContractLaw"): (iri(1), iri(2), iri(4), iri(5)),
        folio("TortLaw"): (iri(3), iri(4)),
    }
    assert depth1.shards_without_concepts == [iri(6)]
    depth2 = ClusterBuilder(axes=["doctrinal"], folio_resolver=resolver, doctrinal_depth=2).build(shards)
    # depth 2: BreachOfContract (1 and 5); ContractFormation has one member; a
    # concept shallower than the depth keys on itself.
    assert keyed(depth2, "doctrinal") == {folio("BreachOfContract"): (iri(1), iri(5))}
    depth0 = ClusterBuilder(axes=["doctrinal"], folio_resolver=resolver, doctrinal_depth=0).build(shards)
    assert keyed(depth0, "doctrinal") == {folio("AreaOfLaw"): (iri(1), iri(2), iri(3), iri(4), iri(5))}


def test_doctrinal_axis_without_a_resolver_keys_on_the_concept_itself() -> None:
    shards = [concept_shard(1, folio("Negligence")), concept_shard(2, folio("Negligence"))]
    result = ClusterBuilder(axes=["doctrinal"]).build(shards)
    assert keyed(result, "doctrinal") == {folio("Negligence"): (iri(1), iri(2))}


def test_shard_concepts_reads_subject_object_and_reference_only() -> None:
    s = vshard(1, triple=Triple(subject=folio("A"), predicate=folio("P"), object=folio("B")),
               reference=folio("C"))
    assert shard_concepts(s) == (folio("A"), folio("B"), folio("C"))


def test_jurisdiction_axis_uses_the_framework_registry(registry) -> None:
    shards = [
        vshard(1, framework_id="us.common_law"),
        vshard(2, framework_id="us.ucc"),             # also jurisdiction "us"
        vshard(3, framework_id="uk.england.common_law"),
        vshard(4, framework_id="uk.england.common_law"),
        vshard(5, framework_id="us.federal.fixture"),  # not registered
    ]
    result = ClusterBuilder(axes=["jurisdiction"], registry=registry).build(shards)
    assert keyed(result, "jurisdiction") == {
        "uk.england": (iri(3), iri(4)),
        "us": (iri(1), iri(2)),
    }
    assert result.unresolved_frameworks == {"us.federal.fixture": [iri(5)]}


def test_all_axes_are_deterministic_and_ordered(registry) -> None:
    shards = [
        vshard(2, source_uri="urn:x:doc/a", elaborates=[iri(1)]),
        vshard(1, source_uri="urn:x:doc/a"),
    ]
    first = ClusterBuilder(registry=registry).build(shards)
    second = ClusterBuilder(registry=registry).build(list(reversed(shards)))
    assert first.clusters == second.clusters
    assert [c.axis for c in first.clusters] == ["source", "tractarian", "jurisdiction"]
    assert first.containing([iri(1), iri(2)]) == first.clusters
    assert first.containing([]) == []


def test_builder_rejects_bad_configuration() -> None:
    with pytest.raises(ValueError, match="unknown cluster axes"):
        ClusterBuilder(axes=["source", "vibes"])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="doctrinal_depth"):
        ClusterBuilder(doctrinal_depth=-1)
    with pytest.raises(ValueError, match="min_size"):
        ClusterBuilder(min_size=0)
