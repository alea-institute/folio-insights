"""Migration item #1: folio-insights pinned to the folio-matching package.

Proves (a) the FourPathReconciler base path now runs on ``folio_matching.Reconciler`` (no
folio-enrich checkout needed) and (b) the new gates are ON in the tagger — the alias blocklist
drops Action->Auction and the place-name gate drops uncorroborated Slovenia-style place hits.
All fully mocked; no folio-enrich, no network.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from folio_insights.models.knowledge_unit import ConceptTag
from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage
from folio_insights.services.bridge.reconciliation_bridge import FourPathReconciler


def test_base_reconciler_runs_on_pinned_package() -> None:
    from folio_matching import Reconciler

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
    # Ch02 unit 4b06a90c: "Action != Auction". The seed blocklist blocks this pairing.
    stage = FolioTaggerStage()
    blocked_iri = "https://folio.openlegalstandard.org/EXAMPLE-Auction"
    tags = [
        ConceptTag(iri=blocked_iri, label="Action", confidence=0.9, extraction_path="llm", branch="Events"),
        ConceptTag(iri="R-cause", label="Cause of Action", confidence=0.8, extraction_path="llm", branch="Objectives"),
    ]
    kept = stage._apply_match_gates(tags)
    kept_iris = {t.iri for t in kept}
    assert blocked_iri not in kept_iris
    assert "R-cause" in kept_iris


def test_place_name_gate_drops_uncorroborated_place() -> None:
    # Ch02 finding 003: bare place-name hit on a single path is demoted out.
    stage = FolioTaggerStage()
    tags = [
        ConceptTag(iri="R-slovenia", label="Slovenia", confidence=0.6, extraction_path="semantic", branch="Location"),
        ConceptTag(iri="R-body", label="Cross-Examination", confidence=0.7, extraction_path="llm", branch="Service"),
    ]
    kept = stage._apply_match_gates(tags)
    assert all(t.iri != "R-slovenia" for t in kept)
    assert any(t.iri == "R-body" for t in kept)


def test_place_name_gate_keeps_heading_corroborated_place() -> None:
    stage = FolioTaggerStage()
    tags = [
        ConceptTag(iri="R-slovenia", label="Slovenia", confidence=0.6, extraction_path="heading_context", branch="Location"),
    ]
    kept = stage._apply_match_gates(tags)
    assert any(t.iri == "R-slovenia" for t in kept)


def test_get_reconciler_uses_pinned_package() -> None:
    stage = FolioTaggerStage()
    embedding_service = MagicMock(index_size=0)
    reconciler = stage._get_reconciler(embedding_service)
    assert isinstance(reconciler, FourPathReconciler)
    # The base is a folio_matching.Reconciler, not a folio-enrich import.
    from folio_matching import Reconciler as PinnedReconciler

    assert isinstance(reconciler._base_reconciler, PinnedReconciler)
