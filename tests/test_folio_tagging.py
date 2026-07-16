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
from unittest.mock import MagicMock

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


def test_llm_path_resolves_folio_iri_above_bar():
    """UAT I-1: an LLM-path label that clears the whole-string bar resolves to its canonical IRI.

    FOLIO's search_by_label returns a 0-100 score; the calibrated bar is 92.0. A clean full match
    (100.0) resolves. (The old class-local 0.6 bar was a scale bug — it accepted every 90.0 place
    over-score; see the Ch02 proving-run fix.)
    """
    from unittest.mock import MagicMock

    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    concept_mock = MagicMock(
        iri="https://folio.openlegalstandard.org/abc123",
        preferred_label="Cross-Examination",
        branch="Service",
    )
    folio_svc = _make_folio_mock([(concept_mock, 100.0)])

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
    """Regression guard: a strong full match (100.0 on the 0-100 scale) still resolves."""
    from unittest.mock import MagicMock

    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    concept_mock = MagicMock(
        iri="https://folio.openlegalstandard.org/ggg777",
        preferred_label="Expert Witness",
        branch="Actor / Player",
    )
    folio_svc = _make_folio_mock([(concept_mock, 100.0)])

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


# ---------- Judge stage + domain prior + metadata-as-signal (2026-07-16 wiring) ----------


class _FakeJudgeProvider:
    """A judge provider whose ``structured`` returns a fixed verdict payload."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls: list[str] = []

    async def structured(self, prompt: str, *, schema=None, temperature=0) -> dict:  # noqa: ARG002
        self.calls.append(prompt)
        return self._payload


@pytest.mark.asyncio
async def test_judge_rejects_non_ruler_tag():
    """A 'rejected' verdict drops the non-ruler tag; the judge cannot resurrect a gated tag."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    stage = FolioTaggerStage()
    fake = _FakeJudgeProvider({"judged": [{"iri_hash": "c0", "adjusted_score": 0, "verdict": "rejected"}]})
    stage._judge_provider = fake

    unit = KnowledgeUnit(
        text="A charge to the jury on the burden of proof.",
        original_span=Span(start=0, end=10, source_file="t.md"),
        unit_type=KnowledgeType.PRINCIPLE,
        source_file="t.md",
    )
    tags = [
        ConceptTag(iri="https://folio.test/encumbrance", label="charge", confidence=0.8,
                   extraction_path="llm", branch="Asset"),
    ]
    folio_svc = _make_folio_mock([])  # definition lookup tolerated

    out = await stage._run_judge(unit, tags, folio_service=folio_svc, prior_context="Litigation / Trial Practice")
    assert out == []  # the definition-level judge rejected charge->Encumbrance in a litigation context
    assert fake.calls and "Litigation / Trial Practice" in fake.calls[0]


@pytest.mark.asyncio
async def test_judge_leaves_ruler_and_proposed_tags_untouched():
    """Entity-ruler and proposed-class tags bypass the judge entirely."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    stage = FolioTaggerStage()
    stage._judge_provider = _FakeJudgeProvider({"judged": []})

    unit = KnowledgeUnit(
        text="Cross-examination technique.",
        original_span=Span(start=0, end=10, source_file="t.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="t.md",
    )
    tags = [
        ConceptTag(iri="https://folio.test/xe", label="Cross-Examination", confidence=0.9,
                   extraction_path="entity_ruler", branch="Service"),
        ConceptTag(iri="", label="novel-thing", confidence=0.5,
                   extraction_path="proposed_class", branch=""),
    ]
    out = await stage._run_judge(unit, tags, folio_service=_make_folio_mock([]), prior_context="")
    assert len(out) == 2  # neither adjudicated


@pytest.mark.asyncio
async def test_judge_confirmed_records_calibration_sample():
    """A confirmed verdict keeps the tag and records a 'correct' calibration sample."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    stage = FolioTaggerStage()
    stage._judge_provider = _FakeJudgeProvider(
        {"judged": [{"iri_hash": "c0", "adjusted_score": 82, "verdict": "confirmed"}]}
    )
    unit = KnowledgeUnit(
        text="Burden of proof.",
        original_span=Span(start=0, end=10, source_file="t.md"),
        unit_type=KnowledgeType.PRINCIPLE,
        source_file="t.md",
    )
    tags = [ConceptTag(iri="https://folio.test/bop", label="Burden of Proof", confidence=0.8,
                       extraction_path="llm", branch="Litigation")]
    out = await stage._run_judge(unit, tags, folio_service=_make_folio_mock([]), prior_context="")
    assert len(out) == 1
    assert stage._calibration_samples == [(80.0, "correct")]


def test_build_domain_prior_has_base_subjects_and_harvests_metadata():
    """The prior carries the base litigation subjects and folds in metadata-unit FOLIO mappings."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    stage = FolioTaggerStage()

    # A metadata (front-matter) unit and a body unit.
    meta = KnowledgeUnit(
        text="Table of Contents. Evidence and Objections.",
        original_span=Span(start=0, end=10, source_file="t.md"),
        unit_type=KnowledgeType.PRINCIPLE,
        source_file="t.md",
        source_section=["Table of Contents"],
    )
    body = KnowledgeUnit(
        text="An objection must be timely.",
        original_span=Span(start=0, end=10, source_file="t.md"),
        unit_type=KnowledgeType.RULE,
        source_file="t.md",
        source_section=["Chapter 4", "Objections"],
    )
    job = InsightsJob(corpus_name="ch04-test", source_dir=Path("."), units=[meta, body])

    # Fake aho-matcher: metadata text maps to one FOLIO concept (multi-word, so it clears the
    # singleton noise filter).
    match = MagicMock(entity_id="https://folio.test/evidence")
    match.text = "Rules of Evidence"
    aho = MagicMock()
    aho.find_matches.return_value = [match]

    folio_svc = _make_folio_mock([])  # base-subject IRI resolution returns nothing -> label-only

    prior = stage._build_domain_prior(job, folio_svc, aho)
    labels = [t.label for t in prior.active_tags()]
    assert "Litigation" in labels and "Trial Practice" in labels
    assert "Rules of Evidence" in labels  # harvested from the metadata unit
    # The metadata unit recorded a metadata-signal lineage event (not an insight tag).
    assert any(e.action == "metadata-signal" for e in meta.lineage)


@pytest.mark.asyncio
async def test_judge_normalizes_mixed_scale_confidence():
    """A 0-100-scale confidence (e.g. 90.0) is normalized before the judge sees it (Ch04 seam)."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    stage = FolioTaggerStage()
    fake = _FakeJudgeProvider({"judged": [{"iri_hash": "c0", "adjusted_score": 88, "verdict": "confirmed"}]})
    stage._judge_provider = fake

    unit = KnowledgeUnit(
        text="Document references can violate foundation rules.",
        original_span=Span(start=0, end=10, source_file="t.md"),
        unit_type=KnowledgeType.RULE,
        source_file="t.md",
    )
    tags = [ConceptTag(iri="https://folio.test/od", label="Objection Document", confidence=90.0,
                       extraction_path="heading_context", branch="Document Artifact")]
    out = await stage._run_judge(unit, tags, folio_service=_make_folio_mock([]), prior_context="")
    # 90.0 normalized to 0.90 -> judge score 90.0 (not 9000); confirmed clamp keeps it near 90.
    assert stage._calibration_samples[0][0] == 90.0
    assert out[0].confidence <= 1.0


def test_metadata_harvest_filters_one_word_singletons():
    """Single-occurrence one-word ruler fragments ('non', 'rule') never enter the prior."""
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    stage = FolioTaggerStage()
    meta = KnowledgeUnit(
        text="Table of Contents. Fed. R. Evid. and objections. Fed. R. Evid. again. non rule",
        original_span=Span(start=0, end=10, source_file="t.md"),
        unit_type=KnowledgeType.PRINCIPLE,
        source_file="t.md",
        source_section=["Table of Contents"],
    )
    job = InsightsJob(corpus_name="c", source_dir=Path("."), units=[meta])

    def _m(entity_id, text):
        m = MagicMock(entity_id=entity_id)
        m.text = text
        return m

    aho = MagicMock()
    aho.find_matches.return_value = [
        _m("https://folio.test/fre", "Fed. R. Evid."),  # multi-word singleton -> kept
        _m("https://folio.test/non", "non"),            # 1-word singleton, <4 chars -> dropped
        _m("https://folio.test/rule", "rule"),          # 1-word singleton -> dropped
    ]
    prior = stage._build_domain_prior(job, None, aho)
    labels = [t.label for t in prior.active_tags()]
    assert "Fed. R. Evid." in labels
    assert "non" not in labels and "rule" not in labels
