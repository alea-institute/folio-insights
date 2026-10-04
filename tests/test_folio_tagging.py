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


# ---------- B9: carried IRIs must be supported by their evidence text (governance plan U3) -------
#
# Every label and IRI below is synthetic. The verifier gates IRIs that a non-deterministic path
# (llm / semantic / heading_context) carried into reconciliation, against the text the concept
# was matched FROM, never against the concept's own label. The entity ruler stays trusted.

_B9_IRI = "https://folio.test/SyntheticQuorumization"
_B9_OTHER = "https://folio.test/SyntheticLanternIsles"


def _b9_concept(iri: str, label: str, *, alts=None, branch: str = "Synthetic Branch"):
    from types import SimpleNamespace

    return SimpleNamespace(iri=iri, preferred_label=label, alternative_labels=alts or [],
                           folio_pref_label="", label="", hidden_label="", branch=branch)


def _b9_folio(concepts: dict, search: dict | None = None):
    from unittest.mock import MagicMock

    search = search or {}
    svc = MagicMock()
    svc.get_concept.side_effect = lambda iri: concepts.get(iri)
    svc.search_by_label.side_effect = lambda text: search.get(text.lower(), [])
    return svc


def _b9_rc(label: str, paths: list[str], iri: str, evidence: str = "") -> ReconciledConcept:
    return ReconciledConcept(
        iri=iri, label=label, confidence=0.7, contributing_paths=paths, branch="",
        evidence_text=evidence,
    )


def _b9_tags(reconciled, svc):
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    return [(t.iri, t.extraction_path) for t in FolioTaggerStage()._reconciled_to_tags(reconciled, svc)]


def test_b9_unrelated_llm_iri_is_dropped_and_label_becomes_proposed():
    svc = _b9_folio({_B9_OTHER: _b9_concept(_B9_OTHER, "Synthetic Lantern Isles")})
    assert _b9_tags([_b9_rc("quorum widget", ["llm"], _B9_OTHER)], svc) == [("", "proposed_class")]


@pytest.mark.parametrize("path", ["semantic", "heading_context"])
def test_b9_unsupported_semantic_or_heading_tag_is_dropped(path):
    """The label is the matched concept's own label: with evidence that does not name the
    concept the tag is dropped (not re-resolved to the same concept, not proposed)."""
    wrong = _b9_concept(_B9_OTHER, "Synthetic Lantern Isles")
    svc = _b9_folio({_B9_OTHER: wrong}, search={"synthetic lantern isles": [(wrong, 100.0)]})
    rc = _b9_rc("Synthetic Lantern Isles", [path], _B9_OTHER,
                evidence="Synthetic Lanyard Island Practice")
    assert _b9_tags([rc], svc) == []


@pytest.mark.parametrize("path", ["semantic", "heading_context"])
def test_b9_concept_label_alone_is_never_evidence(path):
    """Regression for the tautology: without evidence text, a semantic or heading tag cannot
    be verified against its own label, so it is dropped."""
    svc = _b9_folio({_B9_IRI: _b9_concept(_B9_IRI, "Synthetic Quorumization")})
    assert _b9_tags([_b9_rc("Synthetic Quorumization", [path], _B9_IRI)], svc) == []


def test_b9_rejected_llm_iri_is_re_resolved_through_label_resolver():
    right = _b9_concept(_B9_IRI, "Synthetic Quorumization")
    svc = _b9_folio(
        {_B9_OTHER: _b9_concept(_B9_OTHER, "Synthetic Lantern Isles"), _B9_IRI: right},
        search={"synthetic quorumization": [(right, 100.0)]},
    )
    assert _b9_tags([_b9_rc("Synthetic Quorumization", ["llm"], _B9_OTHER)], svc) == [
        (_B9_IRI, "llm")
    ]


def test_b9_supported_iris_are_kept_by_order_case_plural_and_alt_label():
    svc = _b9_folio({
        _B9_IRI: _b9_concept(_B9_IRI, "Synthetic Quorumization", alts=["Zephyr Assembly Rule"]),
    })
    assert _b9_tags([_b9_rc("synthetic quorumizations", ["llm"], _B9_IRI)], svc) == [
        (_B9_IRI, "llm")
    ]
    unit = "Before the vote, check the zephyr assembly rules with the synthetic clerk."
    assert _b9_tags([_b9_rc("Synthetic Quorumization", ["semantic"], _B9_IRI, unit)], svc) == [
        (_B9_IRI, "semantic")
    ]
    assert _b9_tags(
        [_b9_rc("Synthetic Quorumization", ["heading_context"], _B9_IRI, "Synthetic Quorumization")],
        svc,
    ) == [(_B9_IRI, "heading_context")]


@pytest.mark.parametrize(
    ("evidence", "concept_label"),
    [
        ("contract", "Contractor"),
        ("licensor", "Licensee"),
        ("appellant", "Appellate"),
        ("employment", "Employee"),
        ("arbitration", "Arbitrator"),
        ("mediation", "Mediator"),
        ("corporation", "Corporate"),
        ("defamation", "Defamatory"),
        ("lantern", "Northern Synthetic Lantern Isles"),  # a word inside a longer name
        ("venue transfer", "Venezuela Region"),
        ("al", "AL"),  # codes shorter than three letters never count
    ],
)
def test_b9_stem_collisions_and_fragments_are_rejected(evidence, concept_label):
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    concept = _b9_concept(_B9_OTHER, concept_label)
    assert FolioTaggerStage._label_matches_concept(evidence, concept) is False


def test_b9_heading_end_to_end_rejects_a_fuzzy_wrong_concept():
    """HeadingContextExtractor -> FourPathReconciler -> _reconciled_to_tags with a synthetic
    heading that fuzzy-matches an unrelated concept: the tag must not survive."""
    import asyncio

    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    wrong = _b9_concept("https://folio.test/RWrongPlace", "Synthetic Venezuela Region")
    right = _b9_concept("https://folio.test/RRight", "Synthetic Venue Transfer")

    class _Folio:
        def __init__(self, hit):
            self.hit = hit

        def search_by_label(self, q):  # noqa: ARG002
            return [(self.hit, 0.55)]

        def get_concept(self, iri):
            return {wrong.iri: wrong, right.iri: right}.get(iri)

    async def run(svc):
        cands = await HeadingContextExtractor().extract_heading_candidates(
            ["Synthetic Venue Transfer Practice"], svc
        )
        rc = FourPathReconciler(None).reconcile([], [], [], cands)
        return [(t.iri, t.extraction_path) for t in FolioTaggerStage()._reconciled_to_tags(rc, svc)]

    assert asyncio.run(run(_Folio(wrong))) == []
    assert asyncio.run(run(_Folio(right))) == [(right.iri, "heading_context")]


def test_b9_semantic_end_to_end_checks_the_unit_text():
    from types import SimpleNamespace

    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    wrong = _b9_concept("https://folio.test/RWrong", "Synthetic Lantern Isles")
    right = _b9_concept("https://folio.test/RRight", "Synthetic Quorumization")
    svc = _b9_folio({wrong.iri: wrong, right.iri: right})

    class _Embeddings:
        index_size = 2

        def search(self, text, top_k):  # noqa: ARG002
            return [SimpleNamespace(label=c.preferred_label, score=0.8,
                                    metadata={"iri": c.iri, "branch": c.branch})
                    for c in (wrong, right)]

    stage = FolioTaggerStage()
    unit = "Confirm the synthetic quorumization before the clerk calls the vote."
    semantic = stage._run_semantic(unit, _Embeddings())
    reconciled = FourPathReconciler(None).reconcile([], [], semantic, [])
    tags = stage._reconciled_to_tags(reconciled, svc)
    assert [(t.iri, t.extraction_path) for t in tags] == [(right.iri, "semantic")]


def test_b9_a_check_that_cannot_run_never_green_lights_an_iri():
    from unittest.mock import MagicMock

    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    failing = MagicMock()
    failing.get_concept.side_effect = RuntimeError("synthetic lookup failure")
    failing.search_by_label.return_value = []
    assert _b9_tags([_b9_rc("Synthetic Quorumization", ["llm"], _B9_IRI)], failing) == [
        ("", "proposed_class")
    ]
    unknown = _b9_folio({})
    assert _b9_tags([_b9_rc("Synthetic Quorumization", ["llm"], _B9_IRI)], unknown) == [
        ("", "proposed_class")
    ]
    tags = FolioTaggerStage()._reconciled_to_tags(
        [_b9_rc("Synthetic Quorumization", ["llm"], _B9_IRI)], None
    )
    assert [(t.iri, t.extraction_path) for t in tags] == [("", "proposed_class")]


def test_b9_non_string_concept_attributes_are_ignored():
    """Duck-typed concepts (MagicMock attributes, None) never count as labels."""
    from unittest.mock import MagicMock

    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    concept = MagicMock()  # every attribute is a MagicMock, none is a str
    assert FolioTaggerStage._label_matches_concept("anything", concept) is False
    assert FolioTaggerStage._label_matches_concept("", _b9_concept(_B9_IRI, "x")) is False


# ---------- B5: the deterministic IRI path fails loud, or reports degraded ----------


def _with_require(monkeypatch, value: bool) -> None:
    from folio_insights.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("FOLIO_INSIGHTS_REQUIRE_DETERMINISTIC_IRI", "true" if value else "false")


@pytest.fixture
def _reset_settings():
    from folio_insights.config import get_settings

    yield
    get_settings.cache_clear()


def test_b5_missing_folio_service_raises_by_default(monkeypatch, _reset_settings):
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    _with_require(monkeypatch, True)
    with pytest.raises(RuntimeError, match="FolioService unavailable"):
        FolioTaggerStage()._get_entity_ruler(None)
    empty = MagicMock()
    empty.get_all_labels.return_value = {}
    with pytest.raises(RuntimeError, match="no labels"):
        FolioTaggerStage()._get_entity_ruler(empty)


def test_b5_degraded_mode_is_explicit_and_reported(monkeypatch, _reset_settings):
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage

    _with_require(monkeypatch, False)
    ruler, status, reason = FolioTaggerStage()._get_entity_ruler(None)
    assert ruler is None and status == "degraded" and "FolioService unavailable" in reason


def test_b5_active_ruler_is_the_pinned_folio_resolve_ruler(monkeypatch, _reset_settings):
    from folio_resolve import FOLIOEntityRuler

    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage
    from folio_insights.services.bridge.folio_bridge import (
        BridgeIntegrityError,
        get_aho_corasick_matcher,
        get_entity_ruler,
        verify_deterministic_bridge,
    )

    _with_require(monkeypatch, True)
    assert get_entity_ruler() is FOLIOEntityRuler is get_aho_corasick_matcher()
    assert verify_deterministic_bridge() is FOLIOEntityRuler
    assert issubclass(BridgeIntegrityError, RuntimeError)

    loaded = {}

    class _Ruler:
        def load_patterns(self, labels):
            loaded["labels"] = labels

    monkeypatch.setattr(
        "folio_insights.services.bridge.folio_bridge.get_entity_ruler", lambda: _Ruler
    )
    svc = MagicMock()
    svc.get_all_labels.return_value = {"synthetic quorumization": object()}
    ruler, status, reason = FolioTaggerStage()._get_entity_ruler(svc)
    assert isinstance(ruler, _Ruler) and status == "active" and reason == ""
    assert loaded["labels"] == svc.get_all_labels.return_value


def test_b5_missing_ruler_symbol_raises_bridge_integrity_error(monkeypatch):
    import builtins

    from folio_insights.services.bridge.folio_bridge import BridgeIntegrityError, get_entity_ruler

    real_import = builtins.__import__

    def _no_ruler(name, *args, **kwargs):
        if name == "folio_resolve" and args and args[2] and "FOLIOEntityRuler" in args[2]:
            raise ImportError("synthetic: symbol missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_ruler)
    with pytest.raises(BridgeIntegrityError, match="deterministic FOLIO entity ruler"):
        get_entity_ruler()


@pytest.mark.asyncio
async def test_b5_execute_records_degraded_state_and_verification_counts(monkeypatch, _reset_settings):
    from folio_insights.models.corpus import CorpusManifest
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage
    from folio_insights.quality.output_formatter import OutputFormatter

    _with_require(monkeypatch, False)
    stage = FolioTaggerStage()
    monkeypatch.setattr(stage, "_get_folio_service", lambda: None)
    monkeypatch.setattr(stage, "_get_embedding_service", lambda: None)

    async def _no_llm(text, section):  # noqa: ARG001
        return [{"iri": _B9_IRI, "label": "synthetic lantern", "concept_text": "synthetic lantern",
                 "confidence": 0.6, "branch": ""}]

    monkeypatch.setattr(stage, "_run_llm_concept", _no_llm)
    unit = KnowledgeUnit(
        text="A synthetic sentence about a synthetic lantern rule for the tests.",
        original_span=Span(start=0, end=10, source_file="synthetic.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="synthetic.md",
        source_section=["Synthetic Part", "Synthetic Section"],
    )
    job = InsightsJob(corpus_name="synthetic", source_dir=Path("/nonexistent"), units=[unit])
    job = await stage.execute(job)
    meta = job.metadata["folio_tagger"]
    assert meta["deterministic_iri_path"] == "degraded"
    assert meta["carried_iris_rejected"] == 1
    assert [(t.iri, t.extraction_path) for t in unit.folio_tags] == [("", "proposed_class")]
    assert meta["entity_ruler_tags"] == 0
    manifest = CorpusManifest(name="synthetic", created_at="t0", updated_at="t0")
    summary = OutputFormatter().format_units_json(job.units, manifest, job.metadata)["summary"]
    assert summary["folio_tagger"]["deterministic_iri_path"] == "degraded"
