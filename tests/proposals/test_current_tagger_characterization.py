"""U1 characterization: the current tagger and discovery behaviour the governance
pipeline builds on (proposed-class governance plan, KTD2 / R3).

These tests pin what ``origin/master`` (folio-resolve 0.4.0) does today, BEFORE any
logic from the historical governance branch is re-authored:

* which reconciled concepts become matched tags (non-empty IRI) and which become
  ``proposed_class`` tags (``iri == ''``);
* the shape of ``proposed_classes.json``, which is the registry's input;
* discovery's FOLIO-mapping vote, including the rule that empty-IRI proposed tags
  never vote.

Every label and IRI here is synthetic. A test documented as "characterization"
records current behaviour that a later unit may change on purpose; such a change
must update the test in the same commit and say why.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from folio_insights.models.knowledge_unit import (
    ConceptTag,
    KnowledgeType,
    KnowledgeUnit,
    Span,
)
from folio_insights.models.task import DiscoveryJob, TaskCandidate
from folio_insights.pipeline.discovery.stages.folio_mapping import FolioMappingStage
from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage
from folio_insights.quality.output_formatter import OutputFormatter
from folio_insights.services.bridge.reconciliation_bridge import ReconciledConcept

IRI_A = "https://folio.test/SyntheticDoctrineA"
IRI_B = "https://folio.test/SyntheticDoctrineB"


def _concept(iri: str, label: str, branch: str = "Synthetic Branch") -> MagicMock:
    return MagicMock(iri=iri, preferred_label=label, branch=branch)


def _folio(search: dict[str, list] | None = None, concepts: dict[str, MagicMock] | None = None):
    """A fake FolioService: ``search_by_label`` answers from ``search`` (exact
    lower-case key), ``get_concept`` from ``concepts``."""
    search = search or {}
    concepts = concepts or {}
    svc = MagicMock()
    svc.search_by_label.side_effect = lambda text: search.get(text.lower(), [])
    svc.get_concept.side_effect = lambda iri: concepts.get(iri)
    return svc


def _rc(label: str, paths: list[str], iri: str = "", confidence: float = 0.7) -> ReconciledConcept:
    return ReconciledConcept(
        iri=iri, label=label, confidence=confidence, contributing_paths=paths, branch=""
    )


def _unit(uid: str, text: str, tags: list[ConceptTag]) -> KnowledgeUnit:
    unit = KnowledgeUnit(
        id=uid,
        text=text,
        original_span=Span(start=0, end=len(text), source_file="synthetic.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="synthetic.md",
        source_section=["Synthetic Part", "Synthetic Section"],
    )
    unit.folio_tags = tags
    return unit


# ---------- tagger: matched vs proposed ----------


def test_path_supplied_iri_is_a_matched_tag_with_ontology_branch():
    svc = _folio(concepts={IRI_A: _concept(IRI_A, "Synthetic Doctrine A")})
    tags = FolioTaggerStage()._reconciled_to_tags(
        [_rc("Synthetic Doctrine A", ["entity_ruler"], iri=IRI_A)], svc
    )
    assert [(t.iri, t.extraction_path, t.branch) for t in tags] == [
        (IRI_A, "entity_ruler", "Synthetic Branch")
    ]


def test_label_resolving_above_the_bar_is_a_matched_tag():
    svc = _folio(search={"synthetic doctrine b": [(_concept(IRI_B, "Synthetic Doctrine B"), 100.0)]})
    tags = FolioTaggerStage()._reconciled_to_tags([_rc("synthetic doctrine b", ["llm"])], svc)
    assert [(t.iri, t.extraction_path) for t in tags] == [(IRI_B, "llm")]


def test_unresolved_label_is_a_proposed_class_with_empty_iri():
    tags = FolioTaggerStage()._reconciled_to_tags(
        [_rc("Synthetic Tort Doctrine A", ["llm"], confidence=0.55)], _folio()
    )
    assert len(tags) == 1
    tag = tags[0]
    assert tag.iri == ""
    assert tag.extraction_path == "proposed_class"
    assert tag.label == "Synthetic Tort Doctrine A"
    assert tag.confidence == 0.55


def test_mixed_batch_partitions_into_matched_and_proposed():
    svc = _folio(
        search={"synthetic doctrine b": [(_concept(IRI_B, "Synthetic Doctrine B"), 100.0)]},
        concepts={IRI_A: _concept(IRI_A, "Synthetic Doctrine A")},
    )
    reconciled = [
        _rc("Synthetic Doctrine A", ["entity_ruler"], iri=IRI_A),
        _rc("synthetic doctrine b", ["llm"]),
        _rc("Synthetic Remedy Doctrine C", ["llm"]),
        _rc("Synthetic Procedure Doctrine D", ["semantic"]),
    ]
    tags = FolioTaggerStage()._reconciled_to_tags(reconciled, svc)
    matched = sorted(t.iri for t in tags if t.iri)
    proposed = sorted(t.label for t in tags if t.extraction_path == "proposed_class")
    assert matched == [IRI_A, IRI_B]
    assert proposed == ["Synthetic Procedure Doctrine D", "Synthetic Remedy Doctrine C"]
    assert all(t.iri == "" for t in tags if t.extraction_path == "proposed_class")


def test_llm_carried_iri_is_currently_trusted_characterization():
    """Characterization: on master an IRI the LLM path carried is kept as-is,
    without a concept-label check. The historical B9 fix gates it through a
    verifier; U3 transfers that deliberately and must update this test."""
    svc = _folio(concepts={IRI_A: _concept(IRI_A, "Synthetic Doctrine A")})
    tags = FolioTaggerStage()._reconciled_to_tags(
        [_rc("an unrelated synthetic phrase", ["llm"], iri=IRI_A)], svc
    )
    assert [(t.iri, t.extraction_path) for t in tags] == [(IRI_A, "llm")]


# ---------- proposed_classes.json: the registry's input ----------


def test_proposed_classes_report_lists_only_empty_iri_tags_first_seen_per_label():
    units = [
        _unit("u1", "Synthetic unit one.", [
            ConceptTag(iri=IRI_A, label="Synthetic Doctrine A", confidence=0.9,
                       extraction_path="entity_ruler"),
            ConceptTag(iri="", label="Synthetic Tort Doctrine A", confidence=0.6,
                       extraction_path="proposed_class"),
        ]),
        _unit("u2", "Synthetic unit two.", [
            ConceptTag(iri="", label="Synthetic Tort Doctrine A", confidence=0.7,
                       extraction_path="proposed_class"),
            # Case differs: the report de-duplicates on the exact label only, so
            # the registry must normalize (U2).
            ConceptTag(iri="", label="synthetic tort doctrine a", confidence=0.5,
                       extraction_path="proposed_class"),
            ConceptTag(iri="", label="", confidence=0.5, extraction_path="proposed_class"),
        ]),
    ]
    report = OutputFormatter().format_proposed_classes_report(units)
    rows = report["proposed_classes"]
    assert report["total_proposed"] == 2
    assert [(r["proposed_label"], r["source_unit_id"]) for r in rows] == [
        ("Synthetic Tort Doctrine A", "u1"),
        ("synthetic tort doctrine a", "u2"),
    ]
    assert set(rows[0]) == {
        "proposed_label", "extraction_path", "confidence", "source_unit_id",
        "source_text", "source_section",
    }


# ---------- discovery: FOLIO-mapping vote ----------


def _discover(units: list[KnowledgeUnit], label: str = "Synthetic Task") -> DiscoveryJob:
    job = DiscoveryJob(
        corpus_name="synthetic",
        source_dir=Path("/nonexistent/synthetic"),
        knowledge_units=units,
        task_candidates=[
            TaskCandidate(
                label=label,
                source_signal="heading",
                confidence=0.8,
                heading_path=["Synthetic Part", "Synthetic Section"],
                knowledge_unit_ids=[u.id for u in units],
            )
        ],
    )
    svc = MagicMock()
    svc.get_concept.return_value = None  # no deeper concept
    return asyncio.run(FolioMappingStage(folio_service=svc).execute(job))


def _proposed(label: str) -> ConceptTag:
    return ConceptTag(iri="", label=label, confidence=0.6, extraction_path="proposed_class")


def test_most_frequent_matched_iri_wins():
    units = [
        _unit("u1", "one", [ConceptTag(iri=IRI_A, label="A", confidence=0.8, extraction_path="entity_ruler")]),
        _unit("u2", "two", [ConceptTag(iri=IRI_B, label="B", confidence=0.8, extraction_path="entity_ruler"),
                             ConceptTag(iri=IRI_A, label="A", confidence=0.8, extraction_path="entity_ruler")]),
    ]
    candidate = _discover(units).task_candidates[0]
    assert (candidate.folio_iri, candidate.folio_label) == (IRI_A, "A")


def test_empty_iri_proposed_tags_never_vote():
    """R3 / B9 rule: proposed tags pool into one '' bucket; if they voted, a
    majority of proposals would map the task to IRI '' and drop it from export."""
    unit = _unit("u1", "one", [
        _proposed("Synthetic Tort Doctrine A"),
        _proposed("Synthetic Tort Doctrine B"),
        _proposed("Synthetic Tort Doctrine C"),
        ConceptTag(iri=IRI_A, label="Synthetic Doctrine A", confidence=0.72,
                   extraction_path="entity_ruler"),
    ])
    job = _discover([unit])
    candidate = job.task_candidates[0]
    assert candidate.folio_iri == IRI_A
    assert candidate.folio_label == "Synthetic Doctrine A"
    assert "Synthetic Task" not in job.metadata.get("proposed_siblings", [])


def test_empty_iri_tags_do_not_dilute_mapped_confidence():
    """Only voting (matched) tags feed the FOLIO confidence blend."""
    only_matched = _discover([_unit("u1", "one", [
        ConceptTag(iri=IRI_A, label="A", confidence=0.9, extraction_path="entity_ruler")])]).task_candidates[0]
    with_proposed = _discover([_unit("u1", "one", [
        ConceptTag(iri=IRI_A, label="A", confidence=0.9, extraction_path="entity_ruler"),
        ConceptTag(iri="", label="Synthetic Tort Doctrine A", confidence=0.1,
                   extraction_path="proposed_class")])]).task_candidates[0]
    assert with_proposed.confidence == only_matched.confidence


def test_all_proposed_candidate_routes_to_proposed_siblings():
    job = _discover([_unit("u1", "one", [_proposed("Synthetic Tort Doctrine A")])],
                    label="Synthetic Novel Task")
    candidate = job.task_candidates[0]
    assert not candidate.folio_iri
    assert "Synthetic Novel Task" in job.metadata.get("proposed_siblings", [])
