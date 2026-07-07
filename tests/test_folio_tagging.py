"""Tests for FOLIO four-path tagging, heading context, and reconciliation.

Covers:
  - Four extraction paths produce tagged results
  - Confidence pipeline produces scores in [0, 1]
  - Heading context path with proximity weighting
  - Extraction path is recorded on each ConceptTag
  - FourPathReconciler integrates all four paths
  - Lineage records which paths contributed
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from folio_insights.models.knowledge_unit import (
    ConceptTag,
    KnowledgeType,
    KnowledgeUnit,
    Span,
)
from folio_insights.pipeline.stages.base import InsightsJob
from folio_insights.services.bridge.reconciliation_bridge import (
    FourPathReconciler,
    ReconciledConcept,
)
from folio_insights.services.heading_context import HeadingContextExtractor


# ---------- FourPathReconciler ----------


def test_four_path():
    """Provide a knowledge unit with clear FOLIO concept match; verify folio_tags non-empty."""
    reconciler = FourPathReconciler()

    ruler = [{"iri": "https://folio.test/123", "label": "Cross-Examination", "confidence": 0.85, "branch": "Litigation"}]
    llm = [{"iri": "https://folio.test/123", "label": "Cross-Examination", "confidence": 0.8, "concept_text": "Cross-Examination", "branch": "Litigation"}]
    semantic = [{"iri": "https://folio.test/123", "label": "Cross-Examination", "confidence": 0.75, "branch": "Litigation"}]
    heading = [{"iri": "https://folio.test/456", "label": "Expert Witnesses", "confidence": 0.7, "branch": "Litigation"}]

    results = reconciler.reconcile(ruler, llm, semantic, heading)

    assert len(results) >= 1

    # Check that the main concept has extraction paths recorded
    cross_exam = [r for r in results if r.label == "Cross-Examination"]
    assert len(cross_exam) >= 1
    assert len(cross_exam[0].contributing_paths) >= 1

    # Check that heading context concept is also present
    expert = [r for r in results if r.label == "Expert Witnesses"]
    assert len(expert) >= 1
    assert "heading_context" in expert[0].contributing_paths


def test_confidence_pipeline():
    """Verify confidence scores are between 0 and 1."""
    reconciler = FourPathReconciler()

    ruler = [{"iri": "https://folio.test/1", "label": "Deposition", "confidence": 0.9, "branch": ""}]
    llm = [{"iri": "https://folio.test/1", "label": "Deposition", "confidence": 0.85, "concept_text": "Deposition", "branch": ""}]
    semantic = []
    heading = []

    results = reconciler.reconcile(ruler, llm, semantic, heading)

    for r in results:
        assert 0.0 <= r.confidence <= 1.0


def test_reconciler_semantic_boost():
    """Semantic path boosts confidence of matching base concepts."""
    reconciler = FourPathReconciler()

    ruler = [{"iri": "https://folio.test/1", "label": "Witness", "confidence": 0.7, "branch": ""}]
    llm = []
    semantic = [{"iri": "https://folio.test/1", "label": "Witness", "confidence": 0.6, "branch": ""}]
    heading = []

    results = reconciler.reconcile(ruler, llm, semantic, heading)
    witness = [r for r in results if r.label == "Witness"][0]

    # Semantic should have boosted confidence by 0.1
    assert witness.confidence >= 0.75  # 0.7 + 0.1 = 0.8, capped at 1.0
    assert "semantic" in witness.contributing_paths


def test_reconciler_heading_boost():
    """Heading context boosts confidence of matching concepts."""
    reconciler = FourPathReconciler()

    ruler = [{"iri": "https://folio.test/1", "label": "Trial", "confidence": 0.7, "branch": ""}]
    llm = []
    semantic = []
    heading = [{"iri": "https://folio.test/1", "label": "Trial", "confidence": 0.5, "branch": ""}]

    results = reconciler.reconcile(ruler, llm, semantic, heading)
    trial = [r for r in results if r.label == "Trial"][0]

    assert trial.confidence >= 0.7  # at least original, boosted by heading
    assert "heading_context" in trial.contributing_paths


# ---------- HeadingContextExtractor ----------


@pytest.mark.asyncio
async def test_heading_context_path():
    """Heading context extracts ConceptTags with proximity weighting."""
    mock_folio = MagicMock()

    # Return different matches for different headings
    def search_by_label(text):
        if "Methodology" in text:
            return [(MagicMock(iri="https://folio.test/method", preferred_label="Methodology", branch="Litigation"), 0.85)]
        if "Expert Witnesses" in text:
            return [(MagicMock(iri="https://folio.test/expert", preferred_label="Expert Witnesses", branch="Litigation"), 0.80)]
        if "Expert" in text or "8" in text:
            return [(MagicMock(iri="https://folio.test/expert", preferred_label="Expert Witnesses", branch="Litigation"), 0.75)]
        return []

    mock_folio.search_by_label = search_by_label

    extractor = HeadingContextExtractor(mock_folio)
    tags = await extractor.extract_heading_concepts(
        section_path=["Chapter 8: Expert Witnesses", "Methodology"],
        folio_service=mock_folio,
    )

    assert len(tags) >= 1

    # Most specific heading (Methodology) should have highest confidence weight
    method_tags = [t for t in tags if "Methodology" in t.label]
    assert len(method_tags) >= 1
    assert method_tags[0].extraction_path == "heading_context"

    # All tags have valid confidence
    for tag in tags:
        assert 0.0 <= tag.confidence <= 1.0
        assert tag.extraction_path == "heading_context"


@pytest.mark.asyncio
async def test_heading_context_empty_path():
    """Empty section_path produces no heading concepts."""
    mock_folio = MagicMock()
    extractor = HeadingContextExtractor(mock_folio)
    tags = await extractor.extract_heading_concepts([], mock_folio)
    assert tags == []


@pytest.mark.asyncio
async def test_heading_context_proximity_weighting():
    """Verify proximity weighting: immediate > parent > chapter."""
    mock_folio = MagicMock()

    # All headings return similar confidence from FOLIO
    mock_folio.search_by_label.return_value = [
        (MagicMock(iri="https://folio.test/concept", preferred_label="Concept", branch=""), 0.9)
    ]

    extractor = HeadingContextExtractor(mock_folio)
    tags = await extractor.extract_heading_concepts(
        section_path=["Chapter", "Section", "Subsection"],
        folio_service=mock_folio,
    )

    # Should have 3 tags (one per heading level)
    assert len(tags) == 3

    # Most specific (Subsection) has weight 1.0, so highest confidence
    # Parent (Section) has weight 0.7
    # Chapter has weight 0.4
    # All have FOLIO score 0.9, so confidences are 0.9*1.0, 0.9*0.7, 0.9*0.4
    confidences = sorted([t.confidence for t in tags], reverse=True)
    assert confidences[0] > confidences[1] > confidences[2]


# ---------- Extraction path recording ----------


def test_extraction_path_recorded():
    """Each ConceptTag has extraction_path in valid set."""
    valid_paths = {"entity_ruler", "llm", "semantic", "heading_context"}

    reconciler = FourPathReconciler()
    ruler = [{"iri": "https://folio.test/1", "label": "A", "confidence": 0.8, "branch": ""}]
    llm = [{"iri": "https://folio.test/2", "label": "B", "confidence": 0.7, "concept_text": "B", "branch": ""}]
    semantic = [{"iri": "https://folio.test/3", "label": "C", "confidence": 0.6, "branch": ""}]
    heading = [{"iri": "https://folio.test/4", "label": "D", "confidence": 0.5, "branch": ""}]

    results = reconciler.reconcile(ruler, llm, semantic, heading)

    for r in results:
        for path in r.contributing_paths:
            assert path in valid_paths


# ---------- Lineage ----------


def test_lineage():
    """Verify tagged units can have lineage from folio_tagger stage."""
    from folio_insights.pipeline.stages.base import record_lineage

    unit = KnowledgeUnit(
        text="Lock expert into document list",
        original_span=Span(start=0, end=30, source_file="test.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="test.md",
    )

    record_lineage(
        unit,
        stage="folio_tagger",
        action="tag",
        detail="3 concepts, paths=['entity_ruler', 'llm', 'heading_context']",
    )

    assert len(unit.lineage) == 1
    assert unit.lineage[0].stage == "folio_tagger"
    assert unit.lineage[0].action == "tag"
    assert "entity_ruler" in unit.lineage[0].detail
    assert "heading_context" in unit.lineage[0].detail


# ---------- FolioTaggerStage instantiation ----------


def test_folio_tagger_stage_name():
    """FolioTaggerStage has correct name and references all four paths."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    stage = FolioTaggerStage()
    assert stage.name == "folio_tagger"

    # Verify the module mentions all four paths
    import inspect
    source = inspect.getsource(FolioTaggerStage)
    assert "entity_ruler" in source
    assert "llm" in source
    assert "semantic" in source
    assert "heading_context" in source


# ---------- UAT I-1 regression: LLM-path IRI resolution ----------


def _make_folio_mock(results):
    """Helper: build a mock FolioService whose search_by_label returns `results`."""
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock.search_by_label.return_value = results
    return mock


def test_llm_path_resolves_folio_iri_at_06_threshold():
    """UAT I-1: LLM-path label with FOLIO score 0.65 resolves to canonical IRI.

    Current code uses a 0.7 threshold, so this test FAILS on unmodified
    folio_tagger.py. After the fix lowers the threshold to 0.6, it passes.
    """
    from unittest.mock import MagicMock

    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    concept_mock = MagicMock(
        iri="https://folio.openlegalstandard.org/abc123",
        preferred_label="Cross-Examination",
    )
    folio_svc = _make_folio_mock([(concept_mock, 0.65)])

    stage = FolioTaggerStage()
    reconciled = [
        ReconciledConcept(
            iri="",
            label="cross-examine",
            confidence=0.7,
            contributing_paths=["llm"],
            branch="",
        )
    ]

    tags = stage._reconciled_to_tags(reconciled, folio_svc)
    assert len(tags) == 1
    assert tags[0].iri == "https://folio.openlegalstandard.org/abc123"
    assert tags[0].label == "cross-examine"


def test_llm_path_unresolved_label_routes_to_proposed_class():
    """UAT I-1: LLM-path label with NO FOLIO match becomes extraction_path='proposed_class'.

    This makes downstream consumers (proposed_classes.json, OWL exporter)
    correctly distinguish 'LLM found it but FOLIO doesn't have it' from
    'ordinary LLM path tag that happens to be empty'.
    """
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    folio_svc = _make_folio_mock([])  # no FOLIO match

    stage = FolioTaggerStage()
    reconciled = [
        ReconciledConcept(
            iri="",
            label="totally-novel-concept-xyz",
            confidence=0.6,
            contributing_paths=["llm"],
            branch="",
        )
    ]

    tags = stage._reconciled_to_tags(reconciled, folio_svc)
    assert len(tags) == 1
    assert tags[0].iri == ""
    assert tags[0].extraction_path == "proposed_class"
    assert tags[0].label == "totally-novel-concept-xyz"


def test_llm_path_high_score_still_resolves():
    """Regression guard: score 0.92 still resolves (pre-existing behavior preserved)."""
    from unittest.mock import MagicMock

    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    concept_mock = MagicMock(
        iri="https://folio.openlegalstandard.org/ggg777",
        preferred_label="Expert Witness",
    )
    folio_svc = _make_folio_mock([(concept_mock, 0.92)])

    stage = FolioTaggerStage()
    reconciled = [
        ReconciledConcept(
            iri="",
            label="expert witness",
            confidence=0.7,
            contributing_paths=["llm"],
            branch="",
        )
    ]

    tags = stage._reconciled_to_tags(reconciled, folio_svc)
    assert tags[0].iri == "https://folio.openlegalstandard.org/ggg777"


def test_llm_path_low_score_routes_to_proposed_class():
    """UAT I-1: match score below 0.6 is treated as 'no match' and routed to proposed_class."""
    from unittest.mock import MagicMock

    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    concept_mock = MagicMock(iri="https://folio.test/weak", preferred_label="Weak Match")
    folio_svc = _make_folio_mock([(concept_mock, 0.4)])

    stage = FolioTaggerStage()
    reconciled = [
        ReconciledConcept(
            iri="",
            label="ambiguous-term",
            confidence=0.5,
            contributing_paths=["llm"],
            branch="",
        )
    ]

    tags = stage._reconciled_to_tags(reconciled, folio_svc)
    assert tags[0].iri == ""
    assert tags[0].extraction_path == "proposed_class"


# ---------- B9 regression: LLM-carried IRIs gated through the verifier ----------
#
# Root cause (docs/solutions/llm-path-unverified-iris.md): the base reconciler's
# embedding triage binds LLM concept_text to a folio_iri, so llm/semantic/
# heading tags arrive at _reconciled_to_tags ALREADY carrying an IRI and
# previously skipped _label_matches_concept — emitting country IRIs for
# advocacy terms (compassion -> Northern Mariana Islands). These lock in the
# fix: non-entity_ruler IRIs are verified; entity_ruler is trusted.


def _concept(iri, preferred_label, alternative_labels=None, branch=""):
    """A FOLIO concept stub with real string labels (not auto-mocked attrs)."""
    from unittest.mock import MagicMock

    return MagicMock(
        iri=iri,
        preferred_label=preferred_label,
        folio_pref_label=preferred_label,
        hidden_label="",
        alternative_labels=list(alternative_labels or []),
        branch=branch,
    )


def _folio_svc_with_concepts(concepts_by_iri, search_results=None):
    """Mock FolioService: get_concept(iri) -> stub; search_by_label -> results."""
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock.get_concept.side_effect = lambda iri: concepts_by_iri.get(iri)
    mock.search_by_label.return_value = search_results or []
    return mock


def test_b9_llm_carried_country_iri_is_dropped_to_proposed_class():
    """The 'compassion'->country failure class: an LLM tag arriving WITH a
    country IRI whose concept label does not match the unit label gets its IRI
    dropped and is demoted to proposed_class (no deterministic re-resolution)."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    country_iri = "https://folio.openlegalstandard.org/RmpNorthernMariana"
    svc = _folio_svc_with_concepts(
        {country_iri: _concept(country_iri, "Northern Mariana Islands",
                               alternative_labels=["MP"], branch="Location")},
        search_results=[],  # no honest deterministic match for "compassion"
    )

    stage = FolioTaggerStage()
    reconciled = [
        ReconciledConcept(
            iri=country_iri,
            label="compassion",
            confidence=0.6,
            contributing_paths=["llm"],
            branch="Location",
        )
    ]

    tags = stage._reconciled_to_tags(reconciled, svc)
    assert len(tags) == 1
    assert tags[0].iri == "", "LLM-carried country IRI must be dropped"
    assert tags[0].extraction_path == "proposed_class"
    assert tags[0].branch == "", "stale country branch must be cleared"


def test_b9_short_country_code_alt_label_no_longer_false_matches():
    """Calibration item 3: partial_ratio must NOT accept a 2-char country code
    alt-label ('MP') as a match for 'compassion' (which contains 'mp')."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    concept = _concept(
        "https://folio.test/mp", "Northern Mariana Islands",
        alternative_labels=["MP", "Northern Mariana Is."],
    )
    assert FolioTaggerStage._label_matches_concept("compassion", concept) is False
    # And 'non' must not match 'Lebanon' via containment either.
    leb = _concept("https://folio.test/lb", "Lebanon", alternative_labels=["LB"])
    assert FolioTaggerStage._label_matches_concept("non", leb) is False


def test_b9_genuine_morphological_variant_still_matches():
    """Guard against over-correction: long genuine variants still pass
    (partial_ratio fires when both strings are >=6 chars and length-comparable)."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    concept = _concept("https://folio.test/cx", "Cross-Examination")
    assert FolioTaggerStage._label_matches_concept("cross-examine", concept) is True


def test_b9_long_substring_containment_no_longer_false_matches():
    """ce-review hardening: partial_ratio containment of a 6+ char term inside
    a much longer label ('mariana' inside 'Northern Mariana Islands') must not
    pass — the length-ratio guard (>=0.6) blocks it."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    concept = _concept("https://folio.test/mp", "Northern Mariana Islands")
    assert FolioTaggerStage._label_matches_concept("mariana", concept) is False
    # 'video' inside 'Montevideo' (ratio 0.5) is likewise blocked.
    mv = _concept("https://folio.test/mv", "Montevideo")
    assert FolioTaggerStage._label_matches_concept("video", mv) is False


def test_b9_exact_alt_label_abbreviation_still_passes():
    """Documented trade-off boundary: an abbreviation that IS one of the
    concept's own labels passes via token_sort_ratio == 100 (no partial_ratio
    needed); an abbreviation NOT among the labels fails and demotes."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    us = _concept("https://folio.test/us", "United States",
                  alternative_labels=["US", "USA"])
    assert FolioTaggerStage._label_matches_concept("US", us) is True
    # 'writ' is NOT a label of 'Writ of Habeas Corpus' -> rejected (accepted
    # over-correction: demote to proposed_class rather than trust the IRI).
    whc = _concept("https://folio.test/whc", "Writ of Habeas Corpus")
    assert FolioTaggerStage._label_matches_concept("writ", whc) is False


def test_b9_llm_wrong_iri_reresolves_to_correct_concept():
    """A rejected LLM IRI gets a second chance: if the label resolves
    deterministically to a concept that DOES match, keep the corrected IRI."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    wrong_iri = "https://folio.test/argentina"
    right_iri = "https://folio.openlegalstandard.org/CasePrep"
    right = _concept(right_iri, "Case Preparation", branch="Litigation")
    svc = _folio_svc_with_concepts(
        {wrong_iri: _concept(wrong_iri, "Argentina", alternative_labels=["AR"],
                             branch="Location")},
        search_results=[(right, 0.9)],  # honest deterministic match
    )

    stage = FolioTaggerStage()
    reconciled = [
        ReconciledConcept(
            iri=wrong_iri,
            label="Case Preparation",
            confidence=0.6,
            contributing_paths=["llm"],
            branch="Location",
        )
    ]

    tags = stage._reconciled_to_tags(reconciled, svc)
    assert tags[0].iri == right_iri, "wrong IRI must be re-resolved to the right one"
    assert tags[0].branch == "Litigation"
    assert tags[0].extraction_path == "llm"  # concept source preserved


def test_b9_entity_ruler_iri_is_trusted_not_reverified():
    """entity_ruler (exact/alias) tags keep their IRI even if a naive verifier
    would reject them — blanket re-verification strips good ruler tags."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    ruler_iri = "https://folio.openlegalstandard.org/RulerExact"
    # get_concept deliberately returns a mismatching label; must be ignored.
    svc = _folio_svc_with_concepts(
        {ruler_iri: _concept(ruler_iri, "Totally Different Label")}
    )

    stage = FolioTaggerStage()
    reconciled = [
        ReconciledConcept(
            iri=ruler_iri,
            label="Voir Dire",
            confidence=0.72,
            contributing_paths=["entity_ruler"],
            branch="Litigation",
        )
    ]

    tags = stage._reconciled_to_tags(reconciled, svc)
    assert tags[0].iri == ruler_iri, "entity_ruler IRI must be trusted"
    assert tags[0].extraction_path == "entity_ruler"
    svc.get_concept.assert_not_called()


def test_b9_semantic_iri_that_matches_label_is_kept():
    """A non-ruler (semantic) IRI whose concept genuinely matches the label
    passes verification and is kept — the fix must not over-correct."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    sem_iri = "https://folio.openlegalstandard.org/Deposition"
    svc = _folio_svc_with_concepts(
        {sem_iri: _concept(sem_iri, "Deposition", branch="Litigation")}
    )

    stage = FolioTaggerStage()
    reconciled = [
        ReconciledConcept(
            iri=sem_iri,
            label="Deposition",
            confidence=0.7,
            contributing_paths=["semantic"],
            branch="Litigation",
        )
    ]

    tags = stage._reconciled_to_tags(reconciled, svc)
    assert tags[0].iri == sem_iri
    assert tags[0].extraction_path == "semantic"


def test_b9_verify_iri_concept_rejects_on_lookup_failure():
    """If get_concept raises or returns None, the IRI is rejected (never kept
    on the strength of a check that could not run)."""
    from unittest.mock import MagicMock

    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    stage = FolioTaggerStage()

    raising = MagicMock()
    raising.get_concept.side_effect = RuntimeError("ontology unavailable")
    assert stage._verify_iri_concept("x", "https://folio.test/x", raising) is False

    missing = MagicMock()
    missing.get_concept.return_value = None
    assert stage._verify_iri_concept("x", "https://folio.test/x", missing) is False
