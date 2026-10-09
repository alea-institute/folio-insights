"""Phase 9 U1 (R4, KTD4): per-cluster consistency — NLI screen, formal check,
explanations, fallbacks. Fake backends; the real HermiT run is in
``test_hermit_cluster.py``."""
from __future__ import annotations

from pathlib import Path

import pytest

from folio_insights.storage import CorpusStorageContext
from folio_insights.validation.clusters import ClusterBuilder, ShardCluster
from folio_insights.validation.consistency import ConsistencyChecker
from folio_insights.validation.formal import OWL_DISJOINT_WITH, RDF_TYPE, RDFS_SUBCLASS_OF
from folio_insights.validation.proposals import RECONCILIATION_STRATEGIES
from folio_insights.validation.validator import build_validator, validate_corpus

from tests.validation.conftest import (
    BrokenNli,
    FakeNli,
    FakeReasoner,
    folio,
    iri,
    type_triple,
    vshard,
)

ENFORCEABLE = "A gratuitous promise without consideration is enforceable."
UNENFORCEABLE = "A gratuitous promise without consideration is not enforceable."


def planted_pair():
    """Two sources, same jurisdiction (us), contradicting propositions."""
    return [
        vshard(1, source_uri="urn:x:source/treatise-a", framework_id="us.common_law",
               sense=ENFORCEABLE, speech_act="holding"),
        vshard(2, source_uri="urn:x:source/casebook-b", framework_id="us.restatement_2d.contracts",
               sense=UNENFORCEABLE, speech_act="restatement_black_letter"),
        vshard(3, source_uri="urn:x:source/casebook-b", framework_id="us.common_law",
               sense="An offer may be revoked before acceptance."),
    ]


def cluster_of(shards, key="test") -> ShardCluster:
    return ShardCluster("jurisdiction", key, tuple(sorted(s.shard_iri for s in shards)))


def test_planted_contradiction_across_two_sources_is_flagged_with_strategies(registry) -> None:
    validator = build_validator(registry, reasoner=None, nli=FakeNli())
    report = validator.validate(planted_pair(), corpus="c")
    contradictions = report.findings_of("contradiction")
    assert len(contradictions) == 1
    finding = contradictions[0]
    assert finding.shards == [iri(1), iri(2)]
    assert finding.checker == "nli"
    # cluster context: the jurisdiction cluster holds both shards; the source
    # clusters do not.
    assert finding.clusters == ["jurisdiction:us"]
    assert finding.detail["source_uris"] == {
        iri(1): "urn:x:source/treatise-a", iri(2): "urn:x:source/casebook-b"}
    strategies = [p.strategy for p in finding.proposals]
    assert strategies[0] == "contextual_limitation"  # different frameworks, same jurisdiction
    assert strategies[-1] == "unreconciled"
    assert set(strategies) <= set(RECONCILIATION_STRATEGIES)
    assert [p.rank for p in finding.proposals] == list(range(1, len(strategies) + 1))
    assert report.applied is False


async def test_planted_contradiction_passes_unit_validation_in_the_store(tmp_path: Path) -> None:
    """Each shard passes unit-level validation (model, PII gate, full SHACL);
    only the cluster validator sees the conflict. Validation writes nothing."""
    ctx = await CorpusStorageContext.open(tmp_path / "storage", "corpus-a")
    try:
        await ctx.ingest_shards(planted_pair())
        assert (await ctx.validate_corpus()).conforms
        head = await ctx.journal_head()
        report = await validate_corpus(ctx, reasoner=None, nli=FakeNli())
        assert [f.shards for f in report.findings_of("contradiction")] == [[iri(1), iri(2)]]
        assert report.corpus == "corpus-a" and report.shard_count == 3
        assert await ctx.journal_head() == head
    finally:
        await ctx.close()


def test_cluster_without_formal_axioms_falls_back_to_nli_and_labels_it() -> None:
    shards = planted_pair()[:2]
    checker = ConsistencyChecker(reasoner=FakeReasoner(), nli=FakeNli())
    result = checker.check_cluster(cluster_of(shards), {s.shard_iri: s for s in shards})
    assert result.mode == "nli_fallback"
    assert result.checkers == ["nli"]
    assert any("no formal axioms" in n for n in result.notes)
    assert result.formal_axiom_count == 0
    assert [f.checker for f in result.findings] == ["nli"]


def test_reasoner_unavailable_falls_back_and_says_why() -> None:
    shards = [vshard(1, triple=type_triple("urn:x:party/1", folio("A")))]
    shards.append(vshard(2, triple=type_triple("urn:x:party/1", folio("B"))))
    checker = ConsistencyChecker(reasoner=None, nli=FakeNli(), disjoint_seeds=[(folio("A"), folio("B"))])
    result = checker.check_cluster(cluster_of(shards), {s.shard_iri: s for s in shards})
    assert result.mode == "nli_fallback"
    assert any("formal reasoner disabled" in n for n in result.notes)
    assert result.formal_axiom_count == 2


def test_unchecked_cluster_never_reads_consistent() -> None:
    shards = planted_pair()[:2]
    checker = ConsistencyChecker(reasoner=None, nli=None)
    result = checker.check_cluster(cluster_of(shards), {s.shard_iri: s for s in shards})
    assert result.mode == "unchecked" and result.checkers == [] and result.findings == []


def test_formal_contradiction_is_minimized_to_the_conflicting_shards() -> None:
    party = "urn:x:party/1"
    shards = [
        vshard(1, triple=type_triple(party, folio("Merchant")), source_uri="urn:x:source/a"),
        vshard(2, triple=type_triple(party, folio("Consumer")), source_uri="urn:x:source/b"),
        vshard(3, triple=type_triple(party, folio("Person")), source_uri="urn:x:source/c"),
        vshard(4, triple=type_triple("urn:x:party/2", folio("Merchant"))),
    ]
    tbox = [
        (folio("Merchant"), OWL_DISJOINT_WITH, folio("Consumer")),
        (folio("Merchant"), RDFS_SUBCLASS_OF, folio("Person")),
        (folio("Unrelated"), RDFS_SUBCLASS_OF, folio("Thing")),
    ]
    reasoner = FakeReasoner()
    checker = ConsistencyChecker(reasoner=reasoner, nli=FakeNli(), tbox=tbox)
    result = checker.check_cluster(cluster_of(shards), {s.shard_iri: s for s in shards})
    assert result.mode == "formal+textual"
    assert result.checkers == ["hermit", "nli"]
    [finding] = result.findings
    assert finding.kind == "contradiction" and finding.checker == "hermit"
    assert finding.shards == [iri(1), iri(2)]
    assert finding.detail["minimal"] is True
    assert finding.detail["shard_axioms"][iri(1)] == [[party, RDF_TYPE, folio("Merchant")]]
    # the background is minimized to the one participating TBox axiom
    assert finding.detail["background_axioms"] == [
        [folio("Merchant"), OWL_DISJOINT_WITH, folio("Consumer")]]
    assert finding.proposals[-1].strategy == "unreconciled"
    assert reasoner.calls <= checker.max_reasoner_calls


def test_disjoint_conflicts_are_each_reported() -> None:
    shards = [
        vshard(1, triple=type_triple("urn:x:party/1", folio("A"))),
        vshard(2, triple=type_triple("urn:x:party/1", folio("B"))),
        vshard(3, triple=type_triple("urn:x:party/2", folio("A"))),
        vshard(4, triple=type_triple("urn:x:party/2", folio("B"))),
    ]
    checker = ConsistencyChecker(reasoner=FakeReasoner(), nli=None,
                                 disjoint_seeds=[(folio("A"), folio("B"))])
    result = checker.check_cluster(cluster_of(shards), {s.shard_iri: s for s in shards})
    assert sorted(f.shards for f in result.findings) == [[iri(1), iri(2)], [iri(3), iri(4)]]
    assert result.mode == "formal"


def test_unsatisfiable_class_is_explained_by_its_shards() -> None:
    shards = [
        vshard(1, triple=type_triple("urn:x:party/1", folio("A"))),
        vshard(2, triple=Triple3(folio("Hybrid"), RDFS_SUBCLASS_OF, folio("A"))),
        vshard(3, triple=Triple3(folio("Hybrid"), RDFS_SUBCLASS_OF, folio("B"))),
    ]
    checker = ConsistencyChecker(reasoner=FakeReasoner(), nli=None,
                                 disjoint_seeds=[(folio("A"), folio("B"))])
    result = checker.check_cluster(cluster_of(shards), {s.shard_iri: s for s in shards})
    [finding] = result.findings
    assert finding.kind == "unsatisfiable_class"
    assert finding.detail["class"] == folio("Hybrid")
    assert finding.shards == [iri(2), iri(3)]
    # the background is minimized too (review fix C4), so minimal is honest
    assert finding.detail["background_axioms"] == [[folio("A"), OWL_DISJOINT_WITH, folio("B")]]
    assert finding.detail["minimal"] is True and finding.detail["background_minimal"] is True


def test_tbox_inconsistent_on_its_own_is_reported_once() -> None:
    party = "urn:x:party/9"
    shards = [vshard(1, triple=type_triple(party, folio("A"))),
              vshard(2, triple=type_triple("urn:x:party/8", folio("A")))]
    tbox = [(party, RDF_TYPE, folio("X")), (party, RDF_TYPE, folio("Y")),
            (folio("X"), OWL_DISJOINT_WITH, folio("Y"))]
    checker = ConsistencyChecker(reasoner=FakeReasoner(), nli=None, tbox=tbox)
    result = checker.check_cluster(cluster_of(shards), {s.shard_iri: s for s in shards})
    assert [f.kind for f in result.findings] == ["tbox_inconsistent"]
    assert result.findings[0].shards == []


def test_reasoner_budget_exhaustion_reports_a_partial_explanation() -> None:
    # six distinct axioms (A1..B3 under two disjoint classes): no cache hits
    names = [f"{'A' if n % 2 else 'B'}{n}" for n in range(1, 7)]
    shards = [vshard(n, triple=type_triple("urn:x:party/1", folio(name)))
              for n, name in enumerate(names, start=1)]
    tbox = [(folio(name), RDFS_SUBCLASS_OF, folio(name[0])) for name in names]
    checker = ConsistencyChecker(reasoner=FakeReasoner(), nli=None, max_reasoner_calls=3,
                                 tbox=tbox, disjoint_seeds=[(folio("A"), folio("B"))])
    result = checker.check_cluster(cluster_of(shards), {s.shard_iri: s for s in shards})
    [finding] = result.findings
    assert finding.detail["minimal"] is False
    assert len(finding.shards) > 2
    assert any("budget (3) exhausted" in n for n in result.notes)


def test_nli_failure_is_reported_never_passed() -> None:
    shards = planted_pair()[:2]
    checker = ConsistencyChecker(reasoner=None, nli=BrokenNli())
    result = checker.check_cluster(cluster_of(shards), {s.shard_iri: s for s in shards})
    assert result.mode == "unchecked"
    assert any("failed: RuntimeError" in n for n in result.notes)
    assert checker.nli_status.startswith("failed")


def test_supersession_pairs_and_oversized_clusters_are_not_screened() -> None:
    a = vshard(1, sense=ENFORCEABLE, superseded_by=iri(2))
    b = vshard(2, sense=UNENFORCEABLE, supersedes=iri(1))
    nli = FakeNli()
    result = ConsistencyChecker(reasoner=None, nli=nli).check_cluster(
        cluster_of([a, b]), {a.shard_iri: a, b.shard_iri: b})
    assert result.findings == [] and nli.scored == []
    shards = [vshard(n) for n in range(1, 5)]  # 6 pairs
    capped = ConsistencyChecker(reasoner=None, nli=FakeNli(), max_nli_pairs=5).check_cluster(
        cluster_of(shards), {s.shard_iri: s for s in shards})
    assert capped.mode == "unchecked" and "exceed the cap" in capped.notes[0] + capped.notes[-1]


def test_pairs_and_member_sets_are_scored_once_across_axes(registry) -> None:
    shards = [
        vshard(1, source_uri="urn:x:doc", sense=ENFORCEABLE),
        vshard(2, source_uri="urn:x:doc", sense=UNENFORCEABLE),
    ]
    nli = FakeNli()
    validator = build_validator(registry, reasoner=None, nli=nli)
    report = validator.validate(shards)
    # the source and jurisdiction clusters have the same members
    assert {c.id for c in report.clusters} == {"source:urn:x:doc", "jurisdiction:us"}
    assert len(nli.scored) == 2  # one pair, both directions, once
    [finding] = report.findings_of("contradiction")
    assert finding.clusters == ["source:urn:x:doc", "jurisdiction:us"]
    strategies = [p.strategy for p in finding.proposals]
    assert "textual_correction" in strategies and "retraction_later" in strategies


def test_checker_rejects_bad_configuration() -> None:
    with pytest.raises(ValueError, match="nli_threshold"):
        ConsistencyChecker(reasoner=None, nli_threshold=0.0)
    with pytest.raises(ValueError, match="max_reasoner_calls"):
        ConsistencyChecker(reasoner=None, max_reasoner_calls=0)


def test_auto_reasoner_reports_its_availability(monkeypatch) -> None:
    import folio_insights.validation.hermit as hermit

    monkeypatch.setattr(hermit, "hermit_available", lambda: (False, "no Java runtime found"))
    checker = ConsistencyChecker(reasoner="auto")
    assert checker.reasoner is None
    assert checker.reasoner_status == "unavailable: no Java runtime found"


def test_builder_cluster_feeds_the_checker(registry) -> None:
    shards = planted_pair()
    clusters = ClusterBuilder(registry=registry, axes=["jurisdiction"]).build(shards).clusters
    checker = ConsistencyChecker(reasoner=None, nli=FakeNli())
    result = checker.check_cluster(clusters[0], {s.shard_iri: s for s in shards})
    assert [f.shards for f in result.findings] == [[iri(1), iri(2)]]


# ── review fix C3: an NLI screen that compared nothing is not a check ──────


def test_nli_with_no_comparable_text_pairs_reads_unchecked() -> None:
    a = vshard(1, sense="", source_span="", source_uri="urn:x:s")
    b = vshard(2, sense="", source_span="", source_uri="urn:x:s")
    nli = FakeNli()
    result = ConsistencyChecker(reasoner=None, nli=nli).check_cluster(
        cluster_of([a, b]), {a.shard_iri: a, b.shard_iri: b})
    assert result.mode == "unchecked"
    assert "nli" not in result.checkers
    assert result.findings == [] and nli.scored == []
    assert any("NLI: no comparable text pairs" in n for n in result.notes)
    assert result.detail["nli"]["pairs_scored"] == 0
    assert result.detail["nli"]["excluded_empty_text"] == [iri(1), iri(2)]


def test_supersession_only_cluster_reads_unchecked_not_screened() -> None:
    a = vshard(1, sense=ENFORCEABLE, superseded_by=iri(2))
    b = vshard(2, sense=UNENFORCEABLE, supersedes=iri(1))
    result = ConsistencyChecker(reasoner=None, nli=FakeNli()).check_cluster(
        cluster_of([a, b]), {a.shard_iri: a, b.shard_iri: b})
    assert result.mode == "unchecked" and result.checkers == []
    assert any("NLI: no comparable text pairs" in n for n in result.notes)
    assert result.detail["nli"]["supersession_pairs_skipped"] == 1


def test_empty_text_shards_in_a_screened_cluster_are_recorded(registry) -> None:
    shards = [*planted_pair()[:2], vshard(9, sense="", source_span="")]
    result = ConsistencyChecker(reasoner=None, nli=FakeNli()).check_cluster(
        cluster_of(shards), {s.shard_iri: s for s in shards})
    assert result.mode == "nli_fallback" and result.checkers == ["nli"]
    assert result.detail["nli"] == {
        "pairs_scored": 1,
        "excluded_empty_text": [iri(9)],
        "supersession_pairs_skipped": 0,
    }
    assert any("1 shard(s) with no text" in n for n in result.notes)
    # the detail reaches the report's cluster entry
    report = build_validator(registry, reasoner=None, nli=FakeNli()).validate(shards)
    entry = next(c for c in report.clusters if set(c.members) == {s.shard_iri for s in shards})
    assert entry.detail["nli"]["excluded_empty_text"] == [iri(9)]


# ── review fix C4: no formal verdict, no formal mode; honest "minimal" ─────


def test_budget_exhausted_before_the_cluster_verdict_reads_unchecked() -> None:
    shards = [vshard(1, triple=type_triple("urn:x:party/1", folio("A"))),
              vshard(2, triple=type_triple("urn:x:party/1", folio("B")))]
    checker = ConsistencyChecker(reasoner=FakeReasoner(), nli=None, max_reasoner_calls=1,
                                 disjoint_seeds=[(folio("A"), folio("B"))])
    result = checker.check_cluster(cluster_of(shards), {s.shard_iri: s for s in shards})
    assert result.mode == "unchecked"
    assert result.checkers == [] and result.findings == []
    assert any("before the cluster verdict" in n for n in result.notes)
    assert not any("explanations partial" in n for n in result.notes)


def test_budget_exhausted_before_verdict_falls_back_to_nli_when_available() -> None:
    shards = [vshard(1, triple=type_triple("urn:x:party/1", folio("A")), sense=ENFORCEABLE),
              vshard(2, triple=type_triple("urn:x:party/1", folio("B")), sense=UNENFORCEABLE)]
    checker = ConsistencyChecker(reasoner=FakeReasoner(), nli=FakeNli(), max_reasoner_calls=1,
                                 disjoint_seeds=[(folio("A"), folio("B"))])
    result = checker.check_cluster(cluster_of(shards), {s.shard_iri: s for s in shards})
    assert result.mode == "nli_fallback" and result.checkers == ["nli"]


def test_unminimized_background_is_not_reported_as_minimal() -> None:
    party = "urn:x:party/1"
    shards = [vshard(1, triple=type_triple(party, folio("Merchant"))),
              vshard(2, triple=type_triple(party, folio("Consumer")))]
    # 50 background axioms reachable from Merchant: above the minimization cap.
    tbox = [(folio("Merchant"), RDFS_SUBCLASS_OF, folio(f"P{k}")) for k in range(50)]
    checker = ConsistencyChecker(reasoner=FakeReasoner(), nli=None, tbox=tbox,
                                 disjoint_seeds=[(folio("Merchant"), folio("Consumer"))])
    result = checker.check_cluster(cluster_of(shards), {s.shard_iri: s for s in shards})
    [finding] = result.findings
    assert finding.shards == [iri(1), iri(2)]
    assert finding.detail["shards_minimal"] is True
    assert finding.detail["background_minimal"] is False
    assert finding.detail["minimal"] is False
    assert len(finding.detail["background_axioms"]) == 51
    assert any("background axioms not minimized" in n for n in result.notes)
    assert not any("budget" in n for n in result.notes)  # not a budget problem


def test_minimized_explanation_reports_both_halves_minimal() -> None:
    party = "urn:x:party/1"
    shards = [vshard(1, triple=type_triple(party, folio("Merchant"))),
              vshard(2, triple=type_triple(party, folio("Consumer")))]
    checker = ConsistencyChecker(reasoner=FakeReasoner(), nli=None,
                                 disjoint_seeds=[(folio("Merchant"), folio("Consumer"))])
    [finding] = checker.check_cluster(
        cluster_of(shards), {s.shard_iri: s for s in shards}).findings
    assert finding.detail["minimal"] is True
    assert finding.detail["shards_minimal"] is True
    assert finding.detail["background_minimal"] is True


def Triple3(s, p, o):  # noqa: N802 - a Triple builder named for readability
    from folio_insights.shards import Triple

    return Triple(subject=s, predicate=p, object=o)
