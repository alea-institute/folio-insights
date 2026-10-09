"""Phase 9 U1 (R4, KTD4): the cluster consistency check with REAL HermiT.

Worker-tier: these tests need owlready2 and a Java runtime (both in the
worker image). Without them they skip cleanly; the pure-Python paths are
covered in ``test_consistency.py`` and ``test_formal.py``.
"""
from __future__ import annotations

import pytest

from folio_insights.validation.formal import OWL_DISJOINT_WITH, RDFS_SUBCLASS_OF
from folio_insights.validation.hermit import HermitClusterReasoner, hermit_available
from folio_insights.validation.validator import build_validator

from tests.validation.conftest import FakeNli, folio, iri, type_triple, vshard

_AVAILABLE, _REASON = hermit_available()
pytestmark = pytest.mark.skipif(not _AVAILABLE, reason=f"HermiT unavailable: {_REASON}")


def test_hermit_reports_consistency_and_unsatisfiable_classes_by_iri() -> None:
    reasoner = HermitClusterReasoner(xmx_mb=512)
    a, b, hybrid = folio("A"), folio("B"), folio("Hybrid")
    clash = [("urn:x:party/1", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", a),
             ("urn:x:party/1", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", b),
             (a, OWL_DISJOINT_WITH, b)]
    assert reasoner.check(clash).consistent is False
    unsat = reasoner.check([(hybrid, RDFS_SUBCLASS_OF, a), (hybrid, RDFS_SUBCLASS_OF, b),
                            (a, OWL_DISJOINT_WITH, b)])
    assert unsat.consistent is True and unsat.unsatisfiable == (hybrid,)
    assert reasoner.check(clash[:1]).consistent is True


def test_planted_formal_contradiction_across_two_sources_with_hermit(registry) -> None:
    party = "urn:x:party/acme"
    shards = [
        vshard(1, source_uri="urn:x:source/a", triple=type_triple(party, folio("Merchant")),
               sense="Acme is a merchant."),
        vshard(2, source_uri="urn:x:source/b", triple=type_triple(party, folio("Consumer")),
               sense="Acme buys for personal use."),
        vshard(3, source_uri="urn:x:source/b", triple=type_triple(party, folio("Person")),
               sense="Acme is a person."),
    ]
    validator = build_validator(
        registry, reasoner=HermitClusterReasoner(xmx_mb=512), nli=FakeNli(),
        disjoint_seeds=[(folio("Merchant"), folio("Consumer"))], axes=["jurisdiction"],
    )
    report = validator.validate(shards, corpus="c")
    [finding] = report.findings_of("contradiction")
    assert finding.checker == "hermit"
    assert finding.shards == [iri(1), iri(2)]
    assert finding.detail["reasoner"] == "hermit" and finding.detail["minimal"] is True
    assert finding.detail["background_axioms"] == [
        [folio("Merchant"), OWL_DISJOINT_WITH, folio("Consumer")]]
    assert finding.clusters == ["jurisdiction:us"]
    assert report.cluster("jurisdiction:us").mode == "formal+textual"
    assert finding.proposals[-1].strategy == "unreconciled"
