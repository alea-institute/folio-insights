"""Phase 9 U6 (R9): the canonical common-law vs civil-law fork has the PRD §8 P6 shape.

PRD acceptance: "consideration" in common-law and civil-law contexts forks into
jurisdiction-scoped classes under a shared skos:Concept, with fi:analogousTo
linking them and fi:primeAnalogate pointing to the common-law sense
(configurable). The fork is released only by a human disposition.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError
from pyoxigraph import NamedNode, RdfFormat, Store

from folio_insights.models.framework import FrameworkRegistry, UnregisteredFramework
from folio_insights.polysemy.dispositions import DispositionRecord, ProposedFork
from folio_insights.polysemy.distinguo import (
    ForkNotReleased,
    build_distinguo_fork,
    emit_distinguo_fork_ttl,
)
from folio_insights.shapes import pyshacl_adapter
from folio_insights.shapes.compiled import turtle_graph
from folio_insights.shapes.suite import SUITE_PATHS
from folio_insights.vocab._constants import framework_iri

pytestmark = pytest.mark.polysemy_spike

FI = "https://folio-insights.aleainstitute.ai/vocab/"
SKOS = "http://www.w3.org/2004/02/skos/core#"
CL, LA, UK = "us.common_law", "us.louisiana.civil_code", "uk.england.common_law"
REVIEWER = "did:key:z6MkReviewerSynthetic"
CL_SENSE = "urn:folio:term/consideration#us.common_law"
LA_SENSE = "urn:folio:term/consideration#us.louisiana.civil_code"
GROUPING = "urn:folio:term/consideration"


def _fork(**overrides):  # noqa: ANN202
    fields = dict(
        term="consideration",
        cluster_id="fi:PrototypeCluster_0a1b2c3d",
        framework_ids=[LA, CL],
        registry=FrameworkRegistry.with_defaults(),
        reviewer_did=REVIEWER,
        created_at_iso="2026-10-20T12:00:00+00:00",
        proportional_relation="bargain is to common-law enforceability as cause is to civil-law enforceability",
    )
    fields.update(overrides)
    return build_distinguo_fork(**fields)


def _disposition(fork, **overrides) -> DispositionRecord:  # noqa: ANN001
    fields = dict(
        cluster_id=fork.cluster_id,
        term=fork.term,
        proposed_fork=ProposedFork(cluster_id=fork.cluster_id, term=fork.term),
        decision="accept",
        rationale="analogous senses; common-law prime",
        reviewer_did=fork.reviewer_did,
        reviewed_at_iso="2026-10-20T12:01:00+00:00",
        detector_verdict={"kind": "rule", "decision": "polysemy"},
        labeler="human",
    )
    fields.update(overrides)
    return DispositionRecord(**fields)


def _graph(ttl: str) -> Store:
    store = Store()
    store.load(ttl.encode("utf-8"), format=RdfFormat.TURTLE)
    return store


def _objects(store: Store, s: str, p: str) -> set[str]:
    return {q.object.value for q in store.quads_for_pattern(NamedNode(s), NamedNode(p), None)}


def test_canonical_fork_shape() -> None:
    fork = _fork()
    store = _graph(emit_distinguo_fork_ttl(fork, _disposition(fork)))
    rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    # Shared SKOS grouping that distinguishes both senses.
    assert f"{SKOS}Concept" in _objects(store, GROUPING, rdf_type)
    assert _objects(store, GROUPING, f"{FI}distinguishes") == {CL_SENSE, LA_SENSE}
    assert _objects(store, GROUPING, f"{SKOS}narrower") == {CL_SENSE, LA_SENSE}
    assert _objects(store, GROUPING, f"{FI}distinctionKind") == {"analogica"}
    # Jurisdiction-scoped OWL classes linked to their registered framework IRIs.
    for sense, fw, jurisdiction in ((CL_SENSE, CL, "us"), (LA_SENSE, LA, "us.louisiana")):
        assert "http://www.w3.org/2002/07/owl#Class" in _objects(store, sense, rdf_type)
        assert _objects(store, sense, f"{SKOS}broader") == {GROUPING}
        assert _objects(store, sense, f"{FI}framework") == {framework_iri(fw)}
        assert _objects(store, sense, f"{FI}jurisdiction") == {jurisdiction}
    # Analogia: the civil-law sense points at the common-law prime.
    assert _objects(store, LA_SENSE, f"{FI}analogousTo") == {CL_SENSE}
    assert _objects(store, LA_SENSE, f"{FI}primeAnalogate") == {CL_SENSE}
    assert len(_objects(store, LA_SENSE, f"{FI}proportionalRelation")) == 1
    assert _objects(store, CL_SENSE, f"{FI}analogousTo") == set()


def test_prime_analogate_is_configurable() -> None:
    fork = _fork(prime_analogate=LA)
    store = _graph(emit_distinguo_fork_ttl(fork, _disposition(fork)))
    assert _objects(store, CL_SENSE, f"{FI}primeAnalogate") == {LA_SENSE}
    assert _objects(store, LA_SENSE, f"{FI}primeAnalogate") == set()


def test_default_prime_needs_a_common_law_sense() -> None:
    assert _fork(framework_ids=[UK, LA]).prime_analogate == UK
    with pytest.raises(ValueError, match="prime analogate"):
        _fork(framework_ids=[LA, "us.federal.fre"])
    with pytest.raises(ValidationError):
        _fork(prime_analogate="us.ucc")  # not one of the fork's frameworks


def test_fork_needs_registered_frameworks_and_the_triad() -> None:
    with pytest.raises(UnregisteredFramework):
        _fork(framework_ids=[CL, "us.texas.civil_code"])
    with pytest.raises(ValidationError):
        _fork(proportional_relation=None)
    rationis = _fork(distinction_kind="rationis", proportional_relation=None, prime_analogate=None)
    assert rationis.prime_analogate is None


def test_fork_conforms_to_the_distinguo_shapes() -> None:
    fork = _fork()
    report = pyshacl_adapter.validate(turtle_graph(emit_distinguo_fork_ttl(fork, _disposition(fork))),
                                      SUITE_PATHS)
    assert report.conforms, report.text


def test_prd_appendix_c_analogical_pairs_query() -> None:
    """PRD Appendix C: 'all analogical pairs across common-law and civil-law frameworks'."""
    fork = _fork()
    store = _graph(emit_distinguo_fork_ttl(fork, _disposition(fork)))
    rows = list(store.query(f"""
        PREFIX fi: <{FI}>
        SELECT ?classA ?classB ?proportion WHERE {{
          ?classA fi:analogousTo ?classB ; fi:framework ?fwA .
          ?classB fi:framework ?fwB .
          ?classA fi:proportionalRelation ?proportion .
          FILTER(?fwA != ?fwB)
        }}"""))
    assert [(r["classA"].value, r["classB"].value) for r in rows] == [(LA_SENSE, CL_SENSE)]


@pytest.mark.parametrize("overrides, reason", [
    ({"labeler": "agent"}, "labeler"),
    ({"labeler": None}, "labeler"),
    ({"decision": "reject"}, "decision"),
    ({"cluster_id": "fi:PrototypeCluster_other"}, "another cluster"),
    ({"term": "lease"}, "another term"),
    ({"reviewer_did": "did:key:zSomeoneElse"}, "proposer"),
])
def test_fork_is_released_only_by_a_human_disposition(overrides: dict, reason: str) -> None:
    fork = _fork()
    with pytest.raises(ForkNotReleased, match=reason):
        emit_distinguo_fork_ttl(fork, _disposition(fork, **overrides))


def test_modify_releases_too() -> None:
    fork = _fork()
    assert "fi:distinguishes" in emit_distinguo_fork_ttl(
        fork, _disposition(fork, decision="modify")
    )
