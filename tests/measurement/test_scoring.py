"""One-to-one, exhaustive, proposition-scoped measurement contracts."""
from __future__ import annotations

from itertools import permutations

import pytest

from folio_insights.measurement.gold import load_gold, load_ontology
from folio_insights.measurement.matching import (
    MATCHER_POLICY, EquivalenceEdge, Prediction, PredictionDocument,
    freeze_equivalences, match_document,
)
from folio_insights.measurement.schema import TagSelection
from folio_insights.measurement.scoring import (
    HumanAnchor, PoolAudit, TagDecision, TagPool, score_suite,
)


def suite_at(index=0):
    full = load_gold()
    return full.model_copy(update={"documents": (full.documents[index],)})


def prediction(prop, **updates):
    return Prediction.model_validate({**prop.model_dump(), **updates})


def row(doc, props=None, **updates):
    return PredictionDocument.model_validate({
        "source_id": doc.source.source_id, "source_sha256": doc.source.sha256,
        "propositions": [p.model_dump() for p in (
            props if props is not None else [prediction(p) for p in doc.propositions])],
        "coverage_complete": True, "judgments_complete": True, **updates,
    })


def score(suite, rows, **kwargs):
    return score_suite(suite, rows, ontology=load_ontology(), **kwargs)


def counts(axis):
    return axis.tp, axis.fp, axis.fn


def test_compound_prediction_cannot_cover_rule_and_three_elements():
    suite = suite_at()
    doc = suite.documents[0]
    claims = tuple(p for p in doc.propositions if p.item_id.startswith("contract-"))
    assert len(claims) == 4
    suite = suite.model_copy(update={"documents": (
        doc.model_copy(update={"propositions": claims}),)})
    doc = suite.documents[0]
    compound = prediction(claims[0], item_id="compound", text="One compound assertion.")
    rows = (row(doc, [compound]),)
    edges = tuple(EquivalenceEdge(source_id=doc.source.source_id,
        prediction_id="compound", gold_id=p.item_id, verdict="equivalent",
        author="independent-adjudicator", reason="Recorded semantic review.") for p in claims)
    bundle = freeze_equivalences(suite, rows, edges)
    result = score(suite, rows, equivalences=bundle)
    assert counts(result.micro.propositions) == (1, 0, 3)
    assert result.micro.propositions.recall == .25
    assert result.micro.propositions.precision == 1


def test_duplicates_extras_omissions_and_tags_are_proposition_scoped():
    suite = suite_at()
    doc = suite.documents[0]
    first, missed = doc.propositions[:2]
    duplicate_tags = prediction(first, tags=[t.model_dump() for t in (*first.tags, first.tags[0])])
    extra = prediction(first, item_id="extra", text="Unsupported additional assertion.")
    props = [duplicate_tags, extra, *[prediction(p) for p in doc.propositions[2:]]]
    result = score(suite, (row(doc, props),))
    ontology = load_ontology()
    def meaning_tags(prop):
        return {ontology.resolve(t.label, t.branch).iri for t in prop.tags
                if MATCHER_POLICY.classify_tag(ontology.resolve(t.label, t.branch), ontology)
                == "meaning"}
    expected_tp = sum(len(meaning_tags(p)) for p in (first, *doc.propositions[2:]))
    assert counts(result.micro.propositions) == (len(doc.propositions) - 1, 1, 1)
    assert counts(result.micro.tags) == (expected_tp, len(meaning_tags(extra)), len(meaning_tags(missed)))
    duplicated = [prediction(p) for p in doc.propositions] + [prediction(first, item_id="duplicate")]
    result = score(suite, (row(doc, duplicated),))
    assert counts(result.micro.propositions) == (len(doc.propositions), 1, 0)


def test_maximum_matching_uses_augmenting_paths_and_is_order_independent():
    suite = suite_at()
    doc = suite.documents[0]
    gold = doc.propositions[:2]
    doc = doc.model_copy(update={"propositions": gold})
    suite = suite.model_copy(update={"documents": (doc,)})
    a = prediction(gold[0], item_id="a", text="Alternate A")
    b = prediction(gold[0], item_id="b", text="Alternate B")
    edges = tuple(EquivalenceEdge(source_id=doc.source.source_id, prediction_id=p,
        gold_id=g, verdict="equivalent", author="reviewer", reason="Equivalent atomic meaning.")
        for p, g in [("a", gold[0].item_id), ("a", gold[1].item_id), ("b", gold[0].item_id)])
    seen = []
    for props in permutations([a, b]):
        rows = (row(doc, props),)
        bundle = freeze_equivalences(suite, rows, edges)
        matched = match_document(doc, rows[0], bundle)
        assert len(matched.pairs) == 2
        seen.append(matched.pairs)
    assert seen[0] == seen[1]


def test_exact_matching_needs_atomic_text_kind_and_exact_grounded_occurrence():
    suite = suite_at()
    doc = suite.documents[0]
    first = doc.propositions[0]
    for changes in [{"text": "Different meaning"}, {"kind": "fact"},
                    {"span": {"start": first.span.start + 1, "end": first.span.end}},
                    {"span": {"start": 0, "end": len(doc.source.text) + 1}}]:
        result = score(suite, (row(doc, [prediction(first, **changes)]),))
        assert result.micro.propositions.tp == 0
    assert result.sources[doc.source.source_id].diagnostics.invalid_grounding == (first.item_id,)


def test_passing_statutes_stay_unanchored_until_damien_verifies():
    suite = suite_at(4)
    rows = (row(suite.documents[0]),)
    result = score(suite, rows)
    genre = result.genres["statutes-regulations"]
    assert genre.target_met is True
    assert genre.label == "judge agreement, unanchored"
    anchor = HumanAnchor(genre="statutes-regulations", verified_by="Damien Riehl",
        annotation_id="anchor-1", verified_at="2026-10-26T12:00:00Z")
    anchored = score(suite, rows, anchors=(anchor,))
    assert anchored.genres["statutes-regulations"].label == "human-anchored"
    assert anchored.genres["statutes-regulations"].target_met is True
    with pytest.raises(ValueError):
        HumanAnchor(genre="statutes-regulations", verified_by="codex",
                    annotation_id="self", verified_at="2026-10-26T12:00:00Z")


def test_empty_predictions_are_evaluated_but_missing_sources_are_incomplete():
    suite = suite_at()
    doc = suite.documents[0]
    empty = score(suite, (row(doc, []),))
    assert empty.readiness == "ready"
    assert empty.micro.propositions.precision is None
    assert empty.micro.propositions.precision_denominator == 0
    assert empty.micro.propositions.recall == 0
    assert empty.micro.tags.precision is None
    assert empty.micro.tags.recall == 0
    assert empty.micro.target_met is False
    absent = score(suite, ())
    assert absent.readiness == "incomplete"
    assert absent.sources[doc.source.source_id].propositions.recall is None
    assert "missing source" in " ".join(absent.reasons)
    for flag in ["coverage_complete", "judgments_complete"]:
        assert score(suite, (row(doc, **{flag: False}),)).readiness == "incomplete"


def test_uncertain_alignment_and_stale_equivalence_inputs_cannot_score_ready():
    suite = suite_at()
    doc = suite.documents[0]
    props = [prediction(p) for p in doc.propositions]
    props[0] = prediction(doc.propositions[0], text="Paraphrase")
    rows = (row(doc, props),)
    edge = EquivalenceEdge(source_id=doc.source.source_id, prediction_id=props[0].item_id,
        gold_id=doc.propositions[0].item_id, verdict="uncertain", author="reviewer",
        reason="Needs adjudication.")
    bundle = freeze_equivalences(suite, rows, (edge,))
    result = score(suite, rows, equivalences=bundle)
    assert result.readiness == "incomplete"
    assert "uncertain" in " ".join(result.reasons)
    assert bundle.matcher_version == MATCHER_POLICY.version
    assert bundle.gold_sha256 and bundle.predictions_sha256
    changed = (row(doc),)
    with pytest.raises(ValueError, match="equivalence"):
        score(suite, changed, equivalences=bundle)


def test_outside_pool_tags_wait_for_authored_adjudication():
    suite = suite_at()
    doc = suite.documents[0]
    prop = doc.propositions[0]
    new = TagSelection(label="Privacy Law", branch="Area of Law")
    rows = (row(doc, [prediction(prop, tags=[t.model_dump() for t in (*prop.tags, new)]),
                      *[prediction(p) for p in doc.propositions[1:]]]),)
    pending = score(suite, rows)
    assert pending.readiness == "incomplete"
    assert pending.micro.tags.fp == 0
    assert len(pending.pending_tags) == 1
    assert pending.pending_tags[0].tag_iri == load_ontology().resolve(new.label, new.branch).iri
    for accepted in [False, True]:
        decisions = tuple(TagDecision(tag=t, accepted=True, author="gold-author",
            reason="Pooled gold.") for t in prop.tags)
        pool = TagPool(source_id=doc.source.source_id, gold_id=prop.item_id,
            decisions=(*decisions, TagDecision(tag=new, accepted=accepted,
                       author="adjudicator", reason="Reviewed new pool candidate.")))
        result = score(suite, rows, tag_pools=(pool,))
        assert result.readiness == "ready"
        assert result.micro.tags.fp == (0 if accepted else 1)
        assert result.micro.tags.tp == pending.micro.tags.tp + int(accepted)


@pytest.mark.parametrize("missing,limited", [(1, False), (2, True)])
def test_pool_miss_rate_is_visible_beside_genre_recall(missing, limited):
    suite = suite_at()
    result = score(suite, (row(suite.documents[0]),), pool_audits=(PoolAudit(
        genre="opinions", sampled_tags=20, missing_tags=missing,
        uncorrected_missing_tags=missing),))
    genre = result.genres["opinions"]
    assert genre.pool_miss_rate == missing / 20
    assert genre.tag_recall_label == ("pool-limited" if limited else None)
    assert genre.tags.recall == 1


@pytest.mark.parametrize("label,branch", [
    ("Judicial Opinion", "Document / Artifact"),
    ("Brief", "Document / Artifact"),
    ("Statutes", "Legal Authorities"),
    ("Jury Instructions", "Document / Artifact"),
])
def test_source_genre_tags_are_separate_versioned_diagnostics(label, branch):
    suite = suite_at()
    doc = suite.documents[0]
    source_type = TagSelection(label=label, branch=branch)
    props = [p.model_copy(update={"tags": (source_type,)}) for p in doc.propositions]
    doc = doc.model_copy(update={"propositions": tuple(props)})
    suite = suite.model_copy(update={"documents": (doc,)})
    result = score(suite, (row(doc),))
    assert result.matcher_policy.source_type_version == "source-genre-v1"
    assert "Law Review Article" in result.matcher_policy.source_type_labels
    assert counts(result.micro.tags) == (0, 0, 0)
    assert result.micro.tags.precision is None and result.micro.tags.recall is None
    assert counts(result.micro.diagnostics.source_types) == (len(props), 0, 0)
    missed = score(suite, (row(doc, []),))
    assert missed.micro.tags.fn == 0
    assert missed.micro.diagnostics.source_types.fn == len(props)
    extra = score(suite, (row(doc, [prediction(props[0], text="Wrong claim")]),))
    assert extra.micro.tags.fp == 0
    assert extra.micro.diagnostics.source_types.fp == 1


def test_document_artifact_meaning_tags_are_not_all_excluded():
    ontology = load_ontology()
    for label in ["Evidence", "Citation to Caselaw", "Noncompete Agreement", "Notice"]:
        assert MATCHER_POLICY.classify_tag(ontology.resolve(label, "Document / Artifact"),
                                         ontology) == "meaning"


def test_counts_micro_genres_sources_diagnostics_and_serialization():
    suite = load_gold()
    rows = tuple(row(d) for d in suite.documents)
    result = score(suite, rows)
    assert result.readiness == "ready" and result.micro.target_met
    for axis in ["propositions", "tags"]:
        assert getattr(result.micro, axis).tp == sum(
            getattr(r, axis).tp for r in result.sources.values())
        assert getattr(result.micro, axis).tp == sum(
            getattr(r, axis).tp for r in result.genres.values())
    assert result.micro.diagnostics.links.fn == 0
    assert result.micro.diagnostics.links.fp == 0
    assert result.micro.diagnostics.links.tp > 0
    assert result.micro.diagnostics.branches.recall == 1
    assert result.model_validate_json(result.model_dump_json(round_trip=True)) == result
    # Source hashes are coverage evidence, not caller assertions to ignore.
    bad = rows[0].model_copy(update={"source_sha256": "0" * 64})
    assert score(suite, (bad, *rows[1:])).readiness == "incomplete"


def test_alias_tags_deduplicate_by_resolver_identity():
    suite = suite_at()
    doc = suite.documents[0]
    props = [prediction(p) for p in doc.propositions]
    props[0] = prediction(doc.propositions[0], tags=[t.model_dump() for t in (
        *doc.propositions[0].tags, TagSelection(label="Duty", branch="Deontic Specification"))])
    assert counts(score(suite, (row(doc, props),)).micro.tags) == counts(
        score(suite, (row(doc),)).micro.tags)


def test_pool_and_equivalence_changes_have_independent_content_pins():
    suite = suite_at()
    doc = suite.documents[0]
    rows = (row(doc),)
    initial = score(suite, rows)
    extra = TagSelection(label="Privacy Law", branch="Area of Law")
    pool = TagPool(source_id=doc.source.source_id, gold_id=doc.propositions[0].item_id,
        decisions=(TagDecision(tag=extra, accepted=True, author="adjudicator",
                               reason="Missing meaning tag."),))
    changed = score(suite, rows, tag_pools=(pool,))
    assert changed.micro.tags.fn == initial.micro.tags.fn + 1
    assert changed.tag_pools_sha256 != initial.tag_pools_sha256
    assert changed.equivalences_sha256 == initial.equivalences_sha256
    assert changed.gold_sha256 == initial.gold_sha256


def test_policy_changes_require_a_new_version():
    with pytest.raises(ValueError, match="policy"):
        MATCHER_POLICY.model_validate({"source_type_labels": ["Evidence"]})


def test_source_type_ancestry_and_law_review_article_are_classified():
    from folio_insights.measurement.gold import OntologyConcept
    ontology = load_ontology()
    root = ontology.resolve("Judicial Opinion", "Document / Artifact")
    # Tiny recorded-ontology-style extension exercises ancestry without fetching OWL.
    for label, parent in [("Law Review Article", root.branch_iri),
                          ("Appellate Opinion", root.iri)]:
        iri = f"urn:test:{label.replace(' ', '-')}"
        ontology.concepts[iri] = OntologyConcept(iri=iri, label=label, parents=(parent,))
        from folio_insights.measurement.gold import ResolvedConcept
        resolved = ResolvedConcept(iri, label, root.branch_iri, root.branch_label, (iri, parent))
        assert MATCHER_POLICY.classify_tag(resolved, ontology) == "source-type"


def test_partial_unknown_selections_stay_unresolved_and_coverage_never_passes():
    suite = suite_at()
    doc = suite.documents[0]
    props = [prediction(p) for p in doc.propositions]
    props[0] = prediction(doc.propositions[0], tags=[
        {"label": "Imaginary unresolved class", "branch": "Area of Law"}])
    result = score(suite, (row(doc, props),))
    assert result.readiness == "incomplete"
    assert result.micro.target_met is None
    assert result.micro.diagnostics.unresolved_tags
    assert result.micro.tags.fp == 0


def test_score_intervals_preserve_unmeasurable_denominators():
    from folio_insights.measurement.scoring import Counts
    exact = Counts(tp=20)
    assert exact.precision_interval == pytest.approx((.8388748419471806, 1.0))
    assert exact.recall_interval == exact.precision_interval
    assert Counts(fn=20).precision_interval is None
    assert Counts(fn=20).recall_interval == pytest.approx((0, .16112515805281938))
    assert Counts(tp=20, evaluated=False).recall_interval is None
