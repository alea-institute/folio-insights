"""PR #44 review regressions (Phase 9 U6): one failing-first test per should-fix item.

1. A fork is released only by a logged human disposition of THAT fork.
2. The FP gate computes the labeled set's digest itself and ties records to cases.
3. The certifier must name a human, and the reviewed sample must be meaningful.
4. The shipped Rule 1 seeds fire on the production P1-cluster path.
5. ``scripts/seed_dispositions.py`` writes only dispositions the log accepts.
6. Reviewer- and fixture-supplied IRIs and terms cannot break the Turtle.
7. The fork triples are private; only the gated renderer reaches them.
"""
from __future__ import annotations

import importlib.util
import pathlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from pyoxigraph import RdfFormat
from pyoxigraph import parse as rdf_parse

from folio_insights.models.framework import FrameworkRegistry
from folio_insights.polysemy.dispositions import (
    DispositionRecord,
    ProposedFork,
    append_disposition,
)
from folio_insights.polysemy.distinguo import (
    ForkNotReleased,
    ForkProposal,
    build_distinguo_fork,
    emit_distinguo_fork_ttl,
    emit_fork_ttl,
)
from folio_insights.polysemy.fixture_loader import ShardFixture, consideration_fixtures_to_ttl
from folio_insights.polysemy.fp_audit import AGENT_LABELER_ID, Certification, fp_gate
from folio_insights.polysemy.labeled_set import LabeledSet
from tests.polysemy._signed import CORPUS, DID, signed_certificate, signed_record

pytestmark = [pytest.mark.polysemy_spike, pytest.mark.usefixtures("registered_polysemy_reviewer")]

REPO = pathlib.Path(__file__).resolve().parents[2]
CL, LA, UK = "us.common_law", "us.louisiana.civil_code", "uk.england.common_law"
REVIEWER = DID


# ── 1. fork release ─────────────────────────────────────────────────────────


def _fork(**overrides):  # noqa: ANN202
    fields = dict(
        term="consideration", cluster_id="fi:PrototypeCluster_0a1b2c3d", framework_ids=[CL, LA],
        registry=FrameworkRegistry.with_defaults(), reviewer_did=REVIEWER,
        created_at_iso="2026-10-20T12:00:00+00:00",
        proportional_relation="bargain is to common law as cause is to civil law",
    )
    fields.update(overrides)
    return build_distinguo_fork(**fields)


def _disposition(proposed: ProposedFork, **overrides) -> DispositionRecord:
    fields = dict(
        cluster_id=proposed.cluster_id, term=proposed.term, proposed_fork=proposed,
        decision="accept", rationale="analogous senses", reviewer_did=REVIEWER,
        reviewed_at_iso="2026-10-20T12:01:00+00:00",
        detector_verdict={"kind": "rule", "decision": "polysemy"}, labeler="human",
    )
    fields.update(overrides)
    return signed_record(DispositionRecord(**fields))


def test_release_requires_the_disposed_fork_itself(tmp_path: pathlib.Path) -> None:
    """Probe: a human accept of a 2-framework rationis proposal must not release
    a 3-framework analogica fork."""
    log = tmp_path / "dispositions.jsonl"
    small = _fork(distinction_kind="rationis", proportional_relation=None, prime_analogate=None)
    record = _disposition(small.to_proposed_fork())
    append_disposition(record, log)
    assert emit_distinguo_fork_ttl(small, record, dispositions_path=log)
    bigger = _fork(framework_ids=[CL, LA, UK])
    with pytest.raises(ForkNotReleased, match="proposed fork"):
        emit_distinguo_fork_ttl(bigger, record, dispositions_path=log)


def test_release_requires_the_disposition_in_the_log(tmp_path: pathlib.Path) -> None:
    fork = _fork()
    record = _disposition(fork.to_proposed_fork())
    log = tmp_path / "dispositions.jsonl"
    with pytest.raises(ForkNotReleased, match="log"):
        emit_distinguo_fork_ttl(fork, record, dispositions_path=log)
    append_disposition(_disposition(fork.to_proposed_fork(), rationale="another"), log)
    with pytest.raises(ForkNotReleased, match="log"):
        emit_distinguo_fork_ttl(fork, record, dispositions_path=log)
    append_disposition(record, log)
    assert "fi:distinguishes" in emit_distinguo_fork_ttl(fork, record, dispositions_path=log)


# ── 2 + 3. the gate's digest and certifier ─────────────────────────────────


def _labeled(n: int = 10, certification: dict | None = None) -> LabeledSet:
    cases = [
        {"id": f"c-{i}", "term": "lease", "gold": "polysemy" if i % 2 else "univocal",
         "senses": {CL: ["a"], LA: ["b"]},
         "disposition": {"labeler": "agent", "decision": "accept" if i % 2 else "reject",
                         "rationale": "r"}}
        for i in range(n)
    ]
    doc = {"format": "folio-insights/polysemy-labeled-set/v1", "cases": cases, "corpus": CORPUS}
    base = LabeledSet.model_validate(doc)
    if certification is not None:
        cert = {"certified_by": DID, "certified_at": "2026-10-21T00:00:00Z",
                "sample_reviewed": ["c-0", "c-1"], "cases_sha256": base.cases_sha256()}
        cert.update(certification)
        doc["certification"] = signed_certificate(Certification.model_validate(cert))
        return LabeledSet.model_validate(doc)
    return base


def _case_records(labeled: LabeledSet) -> list[DispositionRecord]:
    return [
        DispositionRecord(
            cluster_id=f"fi:C_{c.id}", term=c.term, proposed_fork=ProposedFork(cluster_id="x", term=c.term),
            decision=c.disposition.decision, rationale=c.disposition.rationale,
            reviewer_did=AGENT_LABELER_ID, reviewed_at_iso="2026-10-20T00:00:00+00:00",
            detector_verdict={"decision": "coincidence"}, audit_label=c.id, labeler="agent",
        )
        for c in labeled.cases
    ]


def test_gate_does_not_take_a_caller_digest() -> None:
    """Probe: 40 unrelated accepts + a certification + its own digest returned pass."""
    labeled = _labeled(certification={})
    unrelated = [
        DispositionRecord(
            cluster_id="fi:C_x", term="t", proposed_fork=ProposedFork(cluster_id="x", term="t"),
            decision="accept", rationale="ok", reviewer_did="did:key:z1",
            reviewed_at_iso="2026-10-20T00:00:00+00:00", detector_verdict={"decision": "polysemy"},
        )
        for _ in range(40)
    ]
    with pytest.raises(TypeError):
        fp_gate(unrelated, certification=labeled.certification,  # type: ignore[call-arg]
                cases_sha256=labeled.cases_sha256())
    report = fp_gate(unrelated, labeled=labeled)
    assert report.status != "pass"
    assert "do not match" in report.certification_problem


def test_gate_certifies_only_matching_records() -> None:
    labeled = _labeled(n=40, certification={"sample_reviewed": [f"c-{i}" for i in range(8)]})
    report = fp_gate(_case_records(labeled), labeled=labeled)
    assert report.certified and report.status == "pass"


@pytest.mark.parametrize("certifier", [
    AGENT_LABELER_ID, "assistant", "AI", "an AI reviewer", "claude-opus", "GPT-4o",
    "review-bot", "Model", "llm:judge",
])
def test_certifier_must_name_a_human(certifier: str) -> None:
    with pytest.raises(ValidationError):
        Certification(certified_by=certifier, certified_at=datetime(2026, 10, 21, tzinfo=UTC),
                      sample_reviewed=("c-0",), cases_sha256="a" * 64)


@pytest.mark.parametrize("certifier", ["did:key:z6MkHumanReviewer", "Damien", "maintainer@example.org"])
def test_human_certifiers_are_accepted(certifier: str) -> None:
    Certification(certified_by=certifier, certified_at=datetime(2026, 10, 21, tzinfo=UTC),
                  sample_reviewed=("c-0",), cases_sha256="a" * 64)


def test_certification_sample_must_be_meaningful() -> None:
    too_small = _labeled(n=40, certification={"sample_reviewed": ["c-1", "c-3", "c-5"]})
    report = fp_gate(_case_records(too_small), labeled=too_small)
    assert report.status == "provisional" and "sample" in report.certification_problem
    one_label = _labeled(n=40, certification={"sample_reviewed": [f"c-{i}" for i in range(1, 20, 2)]})
    report = fp_gate(_case_records(one_label), labeled=one_label)
    assert report.status == "provisional" and "label" in report.certification_problem


# ── 4. shipped seeds on the production path ─────────────────────────────────


def test_shipped_seeds_fire_through_the_p1_cluster_path() -> None:
    from folio_insights.polysemy.candidates import polysemy_candidates
    from folio_insights.polysemy.detector import detect_polysemy
    from folio_insights.polysemy.prototype_cluster import build_prototype_cluster
    from folio_insights.polysemy.tbox import load_tbox_seeds
    from folio_insights.shards import Triple
    from folio_insights.store.pyoxigraph_store import PyoxigraphStore
    from folio_insights.validation.clusters import ClusterBuilder
    from tests.validation.conftest import folio, vshard

    registry = FrameworkRegistry.with_defaults()
    concept = folio("Consideration")
    shards = [
        vshard(n, framework_id=fw, logical_form_imputed=f"axiom {n}",
               triple=Triple(subject=concept, predicate="urn:x:p", object="o"))
        for n, fw in enumerate([CL, CL, CL, LA, LA, LA], start=1)
    ]
    found = polysemy_candidates(shards, ClusterBuilder(registry=registry).build(shards), registry)
    candidate = found.candidates[0]
    assert candidate.concept == concept and candidate.term == "consideration"
    store = PyoxigraphStore(path=None)
    load_tbox_seeds(store)  # the SHIPPED seeds, nothing case-specific
    verdict = detect_polysemy(build_prototype_cluster(list(candidate.shards)), store)
    assert verdict.matched_rules != ["R1-no-conflict"]


# ── 5. seed script ──────────────────────────────────────────────────────────


def test_seed_dispositions_script_writes_valid_records(tmp_path: pathlib.Path) -> None:
    spec = importlib.util.spec_from_file_location("seed_dispositions", REPO / "scripts" / "seed_dispositions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    log = tmp_path / "dispositions.jsonl"
    assert module.seed(log) == 22
    from folio_insights.polysemy.dispositions import read_dispositions

    assert all(r.decision != "reject" or r.rationale.strip() for r in read_dispositions(log))


# ── 6. IRIs and terms in hand-built Turtle ──────────────────────────────────


def _parses(ttl: str) -> list:
    return list(rdf_parse(ttl.encode("utf-8"), format=RdfFormat.TURTLE))


@pytest.mark.parametrize("bad", ["urn:x:a> <urn:x:b", "urn:x a", 'urn:x:"q"', "urn:x:{a}", ""])
def test_fork_proposal_refuses_an_illegal_prime_iri(bad: str) -> None:
    with pytest.raises(ValidationError):
        ForkProposal(term="consideration", cluster_id="c", uses_analogousTo=True, prime_analogate=bad,
                     proportional_relation="r", distinction_kind="analogica",
                     source_frameworks=("CommonLaw",), reviewer_did=REVIEWER, created_at_iso="2026-10-20T00:00:00Z")


def test_emit_fork_ttl_rechecks_a_bypassed_prime_iri() -> None:
    fork = ForkProposal.model_construct(
        term="consideration", cluster_id="c", uses_analogousTo=True,
        prime_analogate="urn:x:a> . <urn:x:evil> <urn:x:p> <urn:x:o", proportional_relation="r",
        distinction_kind="analogica", source_frameworks=("CommonLaw",), reviewer_did=REVIEWER,
        created_at_iso="2026-10-20T00:00:00Z",
    )
    with pytest.raises(ValueError, match="IRI"):
        emit_fork_ttl(fork)


def test_emit_fork_ttl_quotes_the_term_in_the_subject() -> None:
    fork = ForkProposal(term="good faith", cluster_id="c", uses_analogousTo=False,
                        distinction_kind="rationis", source_frameworks=("CommonLaw",),
                        reviewer_did=REVIEWER, created_at_iso="2026-10-20T00:00:00Z")
    subjects = {t.subject.value for t in _parses(emit_fork_ttl(fork))}
    assert subjects == {"urn:folio:term/good%20faith#commonlaw"}


def test_fixture_ttl_escapes_term_and_refuses_bad_iris() -> None:
    row = ShardFixture(iri="urn:x:s1", framework=CL, source_doc="d\nline", extracted_text="t",
                       axiom_summary='a "quoted"\naxiom', term='say "hi"')
    terms = {t.object.value for t in _parses(consideration_fixtures_to_ttl([row]))
             if t.predicate.value.endswith("termOfArt")}
    assert terms == {'say "hi"'}
    with pytest.raises(ValueError, match="IRI"):
        consideration_fixtures_to_ttl([row.model_copy(update={"iri": "urn:x:a> <urn:x:b"})])


# ── 7. private fork triples ─────────────────────────────────────────────────


def test_fork_triples_are_private() -> None:
    from folio_insights.polysemy import distinguo

    assert not hasattr(distinguo, "distinguo_fork_triples")
    assert "_distinguo_fork_triples" not in distinguo.__all__
    users = sorted(
        str(p.relative_to(REPO)) for root in ("src", "api", "scripts")
        for p in (REPO / root).rglob("*.py")
        if "_distinguo_fork_triples" in p.read_text(encoding="utf-8")
    )
    assert users == ["src/folio_insights/polysemy/distinguo.py"]
