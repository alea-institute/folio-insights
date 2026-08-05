"""Migration item #1: folio-insights pinned to the folio-resolve package.

Proves (a) the FourPathReconciler base path now runs on ``folio_resolve.Reconciler`` (no
folio-enrich checkout needed) and (b) the new gates are ON in the tagger — the alias blocklist
drops Action->Auction and the place-name gate drops uncorroborated Slovenia-style place hits.
All fully mocked; no folio-enrich, no network.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from folio_insights.models.knowledge_unit import ConceptTag
from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage
from folio_insights.services.bridge.reconciliation_bridge import FourPathReconciler


def test_base_reconciler_runs_on_pinned_package() -> None:
    from folio_resolve import Reconciler

    reconciler = FourPathReconciler(base_reconciler=Reconciler())
    ruler = [{"iri": "R1", "label": "Cross-Examination", "concept_text": "cross-examination", "confidence": 0.72, "branch": "Service"}]
    llm = [{"iri": "R1", "label": "Cross-Examination", "concept_text": "cross-examination", "confidence": 0.6, "branch": "Service"}]
    results = reconciler.reconcile(ruler, llm, [], [])
    assert len(results) == 1
    assert results[0].iri == "R1"
    # both_agree -> both paths recorded, confidence boosted above the max input.
    assert set(results[0].contributing_paths) == {"entity_ruler", "llm"}
    assert results[0].confidence > 0.72


def test_alias_blocklist_drops_action_auction() -> None:
    # Ch02 unit 4b06a90c: "Action != Auction". The shipped seed blocks this pairing on the REAL
    # Auction IRI (proving-run defect #3 fixed — the old seed used a synthetic EXAMPLE-Auction IRI
    # that could never fire on live resolution).
    stage = FolioTaggerStage()
    auction_iri = "https://folio.openlegalstandard.org/R8kOvHwkY6TrQmB7RnYiWNO"
    tags = [
        ConceptTag(iri=auction_iri, label="Action", confidence=0.9, extraction_path="llm", branch="Event"),
        ConceptTag(iri="R-cause", label="Cause of Action", confidence=0.8, extraction_path="llm", branch="Objectives"),
    ]
    kept = stage._apply_match_gates(tags)
    kept_iris = {t.iri for t in kept}
    assert auction_iri not in kept_iris
    assert "R-cause" in kept_iris


def _folio_service_returning(label: str, branch: str) -> MagicMock:
    concept = MagicMock()
    concept.preferred_label = label
    concept.label = label
    concept.branch = branch
    svc = MagicMock()
    svc.get_concept.return_value = concept
    svc.search_by_label.return_value = []
    return svc


def test_place_gate_drops_uncorroborated_nonheading_mismap() -> None:
    # Ch02 defect #1: a place-branch tag resolved on a single (non-heading) path whose surface
    # does NOT match the place name ("Decision Maker" -> Slovenia) is a mis-map — vetoed.
    from folio_insights.services.bridge.reconciliation_bridge import ReconciledConcept

    stage = FolioTaggerStage()
    svc = _folio_service_returning("Slovenia", "Location")
    rc = ReconciledConcept(
        iri="R-slovenia", label="Decision Maker", confidence=0.9,
        contributing_paths=["llm"], branch="Location",
    )
    tags = stage._reconciled_to_tags([rc], svc)
    assert all(t.iri != "R-slovenia" for t in tags)


def test_place_gate_eliminates_heading_only_slovenia_propagation() -> None:
    # Ch02 finding 003 / defect: the OLD gate exempted heading_context, so Slovenia propagated to
    # 118 units. Heading context now contributes at most one signal (< min 2) and no longer exempts
    # — a place carried by headings alone is vetoed.
    from folio_insights.services.bridge.reconciliation_bridge import ReconciledConcept

    stage = FolioTaggerStage()
    svc = _folio_service_returning("Slovenia", "Location")
    rc = ReconciledConcept(
        iri="R-slovenia", label="Slovenia", confidence=0.9,
        contributing_paths=["heading_context"], branch="Location",
    )
    tags = stage._reconciled_to_tags([rc], svc)
    assert all(t.iri != "R-slovenia" for t in tags)


def test_place_gate_keeps_corroborated_place() -> None:
    # A genuinely-mentioned place corroborated across >= 2 non-heading paths (ruler + llm both
    # agree) is kept — the veto targets mis-maps, not real place mentions.
    from folio_insights.services.bridge.reconciliation_bridge import ReconciledConcept

    stage = FolioTaggerStage()
    svc = _folio_service_returning("Delaware", "Location")
    rc = ReconciledConcept(
        iri="R-delaware", label="Delaware", confidence=0.9,
        contributing_paths=["entity_ruler", "llm"], branch="Location",
    )
    tags = stage._reconciled_to_tags([rc], svc)
    assert any(t.iri == "R-delaware" for t in tags)


def test_agency_homonym_vetoed() -> None:
    # Ch02 defect #1: "effect of answers" -> Federal Election Commission (Governmental Body) is an
    # agency homonym; the gate now governs the governmental-body branch too.
    from folio_insights.services.bridge.reconciliation_bridge import ReconciledConcept

    stage = FolioTaggerStage()
    svc = _folio_service_returning("Federal Election Commission", "Governmental Body")
    rc = ReconciledConcept(
        iri="R-fec", label="effect of answers", confidence=0.95,
        contributing_paths=["llm"], branch="Governmental Body",
    )
    tags = stage._reconciled_to_tags([rc], svc)
    assert all(t.iri != "R-fec" for t in tags)


def test_whole_string_bar_rejects_place_mismap_on_real_scale() -> None:
    # Ch02 defect #2: FOLIO search returns 0-100; the old 0.6 bar accepted the 90.0 place
    # over-score ("law" -> Delaware). The 92.0 bar rejects it, so the tag becomes proposed_class.
    from folio_insights.services.bridge.reconciliation_bridge import ReconciledConcept

    stage = FolioTaggerStage()

    class _Match:
        def __init__(self, iri: str, label: str, branch: str) -> None:
            self.iri, self.preferred_label, self.branch = iri, label, branch

    folio_service = MagicMock()
    folio_service.search_by_label.return_value = [(_Match("R-delaware", "Delaware", "Location"), 90.0)]

    rc = ReconciledConcept(iri="", label="law", confidence=0.9, contributing_paths=["llm"], branch="")
    tags = stage._reconciled_to_tags([rc], folio_service)
    assert all(t.iri != "R-delaware" for t in tags)
    assert tags and tags[0].extraction_path == "proposed_class"


def _unit(text: str, section: list[str]):
    """A minimal KnowledgeUnit for the source-classification gate."""
    from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span

    return KnowledgeUnit(
        text=text,
        original_span=Span(start=0, end=len(text), source_file="ch.md"),
        unit_type=KnowledgeType.PRINCIPLE,
        source_file="ch.md",
        source_section=section,
    )


def test_metadata_source_excluded_from_tagging_by_section_label() -> None:
    # Ch02 unit d3c44e2a: a metadata/front-matter unit must never be tagged.
    #
    # SCOPE (renamed 2026-08-05): this case is decided ENTIRELY by the section label.
    # "Copyright" is a front-matter marker that folio_resolve.sources.classify_source
    # short-circuits on, so the ISBN text heuristic is never reached. It is a real
    # test of the label rules and it stays — but it is NOT coverage of the text path,
    # and reading it as such is what let folio-resolve F1 live undetected for weeks
    # (see the two tests below). Keep the assertions label-driven here on purpose.
    stage = FolioTaggerStage()
    front = _unit("ISBN 978-0-13-468599-1", ["Front Matter", "Copyright"])
    body = _unit("The plaintiff filed a motion.", ["Chapter 2", "Discovery"])
    assert stage._is_taggable_source(front) is False
    assert stage._is_taggable_source(body) is True


def test_isbn_block_under_marker_free_label_is_still_metadata() -> None:
    # The TEXT heuristic, genuinely exercised. "Publication Data" carries no
    # front-matter / back-matter / metadata section marker, so classify_source falls
    # THROUGH the label rules and the ISBN regex is the only thing that can decide the
    # outcome. A real 13-digit ISBN block must stay excluded.
    #
    # The control assertion is load-bearing: the same label with ordinary prose must be
    # taggable. If it ever stops being, this test has silently reverted to a label test
    # and no longer guards the regex at all.
    stage = FolioTaggerStage()
    control = _unit("The witness identified the exhibit.", ["Publication Data"])
    assert stage._is_taggable_source(control) is True, (
        "'Publication Data' must not be a section marker, or this test proves nothing "
        "about the ISBN regex"
    )

    isbn_only = _unit("ISBN 978-0-13-468599-1", ["Publication Data"])
    isbn_block = _unit(
        "First edition. ISBN 978-0-13-468599-1. Printed in the United States.",
        ["Publication Data"],
    )
    assert stage._is_taggable_source(isbn_only) is False
    assert stage._is_taggable_source(isbn_block) is False


# ---------------------------------------------------------------------------
# THE REGRESSION GUARD FOR F1 — a citation is not metadata.
#
# History, because a green assertion looks like it was always green: under
# folio-resolve <=0.3.0 the SourceClassifier ISBN regex was
# `\b(?:97[89][- ]?)?\d{1,5}[- ]?\d{1,7}[- ]?\d{1,7}[- ]?[\dxX]\b`, which needed only
# FOUR digits — so essentially any legal citation carrying a rule or statute number in
# a sub-200-char unit classified as METADATA. In this repo that was not a cosmetic
# misclassification: FolioTaggerStage._is_taggable_source gates BOTH passes, so such a
# unit was emitted with folio_tags == [] AND harvested into the corpus domain prior as
# if it were front matter — the treatise's most substantive prose steering the prior
# that steers the judge.
#
# Confirmed in this repo's own committed output: in output/uat_ta_ch04_v8/extraction.json
# (1,168 units) all 5 units the metadata gate excluded were false positives — every one
# a Federal Rules of Evidence citation, in a chapter titled "Evidence and Objections".
# Full evidence and file:line citations: folio-resolve
# docs/migration/2026-08-05-v0.3.1-consumer-impact.md §4.1 / §4.1a.
#
# These three cases were committed as xfail(strict=True) against the 0.3.0 pin so that
# bumping to the release carrying the 10-digit regex would turn the suite RED with XPASS
# — a deliberate flip trigger. It fired on 2026-08-05 at ==0.3.1 (all three XPASS), and
# the markers came off in the same commit. From here they are an ordinary guard: they
# fail if the permissive regex ever comes back, or if a future pin regresses below
# 0.3.1.
#
# Do not weaken these assertions to make the suite green — a weakened assertion here is
# exactly the blindness this test was written to remove.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "section"),
    [
        (
            "A party must authenticate a document under Fed. R. Evid. 901-902 before it "
            "may be received in evidence.",
            ["Chapter 4", "Objections", "Authentication"],
        ),
        (
            "Object under FRE 1002 when the proponent offers a duplicate in place of the "
            "original.",
            ["Chapter 4", "Objections", "Original Writings"],
        ),
        (
            "A claim brought under 42 U.S.C. 1983 requires state action.",
            ["Chapter 3", "Civil Rights"],
        ),
    ],
    ids=["fed-r-evid-901-902", "fre-1002", "usc-1983"],
)
def test_citation_dense_body_unit_stays_taggable(text: str, section: list[str]) -> None:
    # The assertion §4.1b of the impact doc says was missing: a must-STAY-taggable
    # case whose section label is marker-free, so the outcome is decided by the text
    # heuristic and nothing else. These are synthetic statements of law written for
    # this test — no manuscript prose.
    stage = FolioTaggerStage()
    assert stage._is_taggable_source(_unit(text, section)) is True


def test_decompose_splits_compound_heading_into_two_tags() -> None:
    # Ch02 unit 12b5e434: "Proposed Findings of Fact and Conclusions of Law" is a compound heading
    # naming TWO sibling FOLIO concepts. Decompose-first resolves each conjunct to its own IRI
    # (scores are on FOLIO's real 0-100 scale; branch is carried through).
    stage = FolioTaggerStage()

    class _Match:
        def __init__(self, iri: str, label: str) -> None:
            self.iri = iri
            self.preferred_label = label
            self.branch = "Document / Artifact"

    def fake_search(label: str):
        table = {
            "Proposed Findings of Fact": [(_Match("R9G2HzzbJMx6tThsp2m6kjM", "Proposed Findings of Fact"), 100.0)],
            "Proposed Conclusions of Law": [(_Match("RNVlq2ReYjeb3r8UkUYvso", "Proposed Conclusions of Law"), 100.0)],
        }
        return table.get(label, [])

    folio_service = MagicMock()
    folio_service.search_by_label.side_effect = fake_search

    from folio_insights.services.bridge.reconciliation_bridge import ReconciledConcept

    rc = ReconciledConcept(
        iri="",
        label="Proposed Findings of Fact and Conclusions of Law",
        confidence=0.8,
        contributing_paths=["heading_context"],
        branch="Document",
    )
    tags = stage._reconciled_to_tags([rc], folio_service)
    iris = {t.iri for t in tags}
    assert iris == {"R9G2HzzbJMx6tThsp2m6kjM", "RNVlq2ReYjeb3r8UkUYvso"}
    # No proposed_class fallback should survive when both conjuncts resolve.
    assert all(t.extraction_path != "proposed_class" for t in tags)
    # Every resolved tag carries its branch (fix a).
    assert all(t.branch == "Document / Artifact" for t in tags)


def test_decompose_falls_back_to_proposed_class_when_unresolvable() -> None:
    # A compound label whose conjuncts also fail to resolve stays a single proposed_class.
    stage = FolioTaggerStage()
    folio_service = MagicMock()
    folio_service.search_by_label.return_value = []

    from folio_insights.services.bridge.reconciliation_bridge import ReconciledConcept

    rc = ReconciledConcept(
        iri="",
        label="Widgets and Gizmos",
        confidence=0.5,
        contributing_paths=["llm"],
        branch="",
    )
    tags = stage._reconciled_to_tags([rc], folio_service)
    assert len(tags) == 1
    assert tags[0].extraction_path == "proposed_class"
    assert tags[0].iri == ""


def test_entity_ruler_uses_pinned_folio_resolve_ruler() -> None:
    # Migration item #1 (continued): the entity-ruler path now runs on the pinned
    # folio_resolve.FOLIOEntityRuler, consuming folio_service.get_all_labels() directly.
    # (folio-enrich moved its AhoCorasickMatcher module, which had silently disabled this path.)
    from folio_resolve import FOLIOEntityRuler
    from folio_resolve.ontology import Concept, LabelInfo

    stage = FolioTaggerStage()

    labels = {
        "Cross-Examination": LabelInfo(
            concept=Concept(iri="R-cross", label="Cross-Examination", branch="Service"),
            label_type="preferred",
        ),
    }
    folio_service = MagicMock()
    folio_service.get_all_labels.return_value = labels

    ruler = stage._get_aho_matcher(folio_service)
    assert isinstance(ruler, FOLIOEntityRuler)
    # The ruler actually finds the loaded label and emits its IRI as entity_id.
    matches = ruler.find_matches("The Cross-Examination began.")
    assert any(getattr(m, "entity_id", "") == "R-cross" for m in matches)


def test_entity_ruler_duck_types_folio_enrich_labelinfo() -> None:
    # folio-enrich's get_all_labels() returns its OWN LabelInfo (concept.iri + label_type).
    # FOLIOEntityRuler must consume it via duck typing with no adapter — this is what makes the
    # one-line migration valid on the live pipeline.
    from dataclasses import dataclass

    stage = FolioTaggerStage()

    @dataclass
    class _EnrichConcept:  # mirrors folio-enrich FOLIOConcept (only .iri is read)
        iri: str

    @dataclass
    class _EnrichLabelInfo:  # mirrors folio-enrich LabelInfo shape
        concept: _EnrichConcept
        label_type: str
        matched_label: str

    labels = {
        "Deposition": _EnrichLabelInfo(_EnrichConcept("R-depo"), "preferred", "Deposition"),
    }
    folio_service = MagicMock()
    folio_service.get_all_labels.return_value = labels

    ruler = stage._get_aho_matcher(folio_service)
    matches = ruler.find_matches("Prepare for the Deposition.")
    assert any(getattr(m, "entity_id", "") == "R-depo" for m in matches)


def test_get_reconciler_uses_pinned_package() -> None:
    stage = FolioTaggerStage()
    embedding_service = MagicMock(index_size=0)
    reconciler = stage._get_reconciler(embedding_service)
    assert isinstance(reconciler, FourPathReconciler)
    # The base is a folio_resolve.Reconciler, not a folio-enrich import.
    from folio_resolve import Reconciler as PinnedReconciler

    assert isinstance(reconciler._base_reconciler, PinnedReconciler)
