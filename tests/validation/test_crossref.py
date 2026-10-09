"""Phase 9 U1 (R4): cross-reference — citations across incompatible frameworks."""
from __future__ import annotations

import pytest

from folio_insights.models.framework import Framework
from folio_insights.validation.crossref import CrossReferenceChecker

from tests.validation.conftest import iri, vshard


def test_cross_framework_citation_is_flagged_with_proposals(registry) -> None:
    shards = [
        vshard(1, framework_id="us.louisiana.civil_code", depends_on_precedents=[iri(2)]),
        vshard(2, framework_id="uk.england.common_law"),
    ]
    [finding] = CrossReferenceChecker(registry).check(shards)
    assert finding.kind == "cross_framework_citation" and finding.checker == "crossref"
    assert finding.shards == [iri(1), iri(2)]
    assert finding.severity == "warning"
    assert finding.detail["relation"] == "unrelated_jurisdiction"
    assert finding.detail["fields"] == ["depends_on_precedents"]
    assert finding.detail["citing_jurisdiction"] == "us.louisiana"
    assert [p.strategy for p in finding.proposals] == [
        "jurisdictional_scoping", "voice_attribution", "contextual_limitation", "unreconciled"]


def test_compatible_citations_are_not_flagged(registry) -> None:
    registry.register(Framework(id="us.federal.fre.privilege", label="FRE privileges",
                                jurisdiction="us.federal", parent="us.federal.fre"))
    shards = [
        vshard(1, framework_id="us.common_law", depends_on_shards=[iri(2)]),  # same framework
        vshard(2, framework_id="us.common_law", depends_on_definitions=[iri(3)]),
        vshard(3, framework_id="us.ucc"),                                   # same jurisdiction (us)
        vshard(4, framework_id="us.federal.fre.privilege", elaborates=[iri(5)]),
        vshard(5, framework_id="us.federal.fre"),                           # registry lineage
        vshard(6, framework_id="us.federal.frcp", depends_on_shards=[iri(5)]),  # same jurisdiction
        vshard(7, framework_id="us.common_law", depends_on_shards=["urn:folio:shard/" + "e" * 32]),
    ]
    assert CrossReferenceChecker(registry).check(shards) == []


def test_nested_jurisdiction_is_info_and_allowed_pairs_are_silent(registry) -> None:
    shards = [
        vshard(1, framework_id="us.louisiana.civil_code", depends_on_shards=[iri(2)]),
        vshard(2, framework_id="us.common_law"),
    ]
    [finding] = CrossReferenceChecker(registry).check(shards)
    assert finding.detail["relation"] == "nested_jurisdiction" and finding.severity == "info"
    allowed = CrossReferenceChecker(
        registry, allowed_pairs=[("us.common_law", "us.louisiana.civil_code")])
    assert allowed.check(shards) == []


def test_unregistered_framework_and_axiom_edges(registry) -> None:
    shards = [
        vshard(1, framework_id="us.common_law", depends_on_shards=[iri(2)],
               depends_on_axioms=[iri(3)]),
        vshard(2, framework_id="us.federal.fixture"),       # not registered
        vshard(3, framework_id="uk.england.common_law"),    # kernel-like axiom
    ]
    checker = CrossReferenceChecker(registry)
    [finding] = checker.check(shards)
    assert finding.detail["relation"] == "unregistered" and finding.shards == [iri(1), iri(2)]
    with_axioms = CrossReferenceChecker(
        registry, fields=["depends_on_shards", "depends_on_axioms"]).check(shards)
    assert sorted(f.shards[1] for f in with_axioms) == [iri(2), iri(3)]
    with pytest.raises(ValueError, match="unknown citation fields"):
        CrossReferenceChecker(registry, fields=["cites"])
    assert CrossReferenceChecker(None).relation("us.ucc", "us.common_law") == "unregistered"
