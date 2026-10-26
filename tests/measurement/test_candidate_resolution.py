"""Offline proofs for pinned concept selection and ontology ancestry (U41)."""

from types import SimpleNamespace

import pytest

from folio_insights.config import get_settings
from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage
from folio_insights.services.bridge.reconciliation_bridge import ReconciledConcept
from folio_insights.services.folio_ontology import FolioOntologyService


ROOT = "https://folio.test/root"
DEONTIC = "https://folio.test/deontic"
DUTY = "https://folio.test/duty"


def concept(iri, label, parents=(), **kwargs):
    return SimpleNamespace(
        iri=iri, label=label, sub_class_of=list(parents),
        alternative_labels=kwargs.pop("alternative_labels", []),
        definition=kwargs.pop("definition", "A defined concept."), **kwargs,
    )


class Ontology:
    def __init__(self, classes):
        self.classes = classes
        self.by_iri = {c.iri: c for c in classes}

    def __getitem__(self, iri):
        return self.by_iri[iri]

    def get_folio_branches(self):
        return {"EVENT": self.classes}

    def get_parents(self, iri):
        return [self.by_iri[p] for p in self.by_iri[iri].sub_class_of if p in self.by_iri]

    def search_by_label(self, label, include_alt_labels=True):
        return [(c, 100.0) for c in self.classes
                if label.casefold() in [c.label.casefold(),
                                       *[a.casefold() for a in c.alternative_labels]]]


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(FolioOntologyService, "_compute_label_lemmas", lambda self: {})
    return FolioOntologyService(folio=Ontology([
        concept(ROOT, "Event"),
        concept(DEONTIC, "Deontic Specification", [ROOT]),
        concept(DUTY, "Obligation", [DEONTIC], alternative_labels=["Duty"]),
        concept("https://folio.test/old", "Old Obligation", [DEONTIC], deprecated=True),
        concept("https://folio.test/dupe", "Obligation DUPE", [DEONTIC]),
    ]), lemma_cache_dir=tmp_path)


@pytest.fixture
def atomic(monkeypatch):
    monkeypatch.setenv("FOLIO_INSIGHTS_ATOMIC_EXTRACTION", "true")
    get_settings.cache_clear()


def test_selection_is_pinned_and_contains_no_model_iris(service):
    catalog = service.candidate_catalog([DUTY])
    [item] = catalog.model_candidates()
    assert set(item) == {"id", "label", "definition", "branch"}
    assert "https://" not in str(item)
    assert service.resolve_candidate(item["id"], catalog).iri == DUTY
    assert service.resolve_candidate("Duty", catalog).iri == DUTY
    assert service.resolve_candidate(DUTY, catalog) is None
    assert service.resolve_candidate("fabricated", catalog) is None
    assert service.resolve_candidate("Event", catalog) is None
    assert service.resolve_candidate({"iri": DUTY}, catalog) is None


def test_ancestry_and_ontology_update_invalidate_catalog_and_stage_caches(service, atomic):
    stage = FolioTaggerStage()
    catalog = service.candidate_catalog([DUTY])
    [item] = catalog.model_candidates()
    assert service.ancestor_branches(DUTY) == ("Deontic Specification", "Event")
    assert stage._branch_for(DUTY, service) == "Deontic Specification"
    assert stage._label_for(DUTY, service) == "Obligation"
    assert stage._definition_for(DUTY, service) == "A defined concept."
    service.replace_ontology(Ontology([
        concept(ROOT, "Event"),
        concept(DUTY, "Requirement", [ROOT], definition="Updated definition."),
    ]))
    assert service.resolve_candidate(item["id"], catalog) is None
    assert service.candidate_catalog([DUTY]).ontology_digest != catalog.ontology_digest
    assert stage._branch_for(DUTY, service) == "Event"
    assert stage._label_for(DUTY, service) == "Requirement"
    assert stage._definition_for(DUTY, service) == "Updated definition."
    assert "obligation" not in service.get_all_labels()


@pytest.mark.parametrize("label", ["Unknown Duty", "Old Obligation", "Obligation DUPE"])
def test_unresolved_labels_stay_review_proposals(service, atomic, label):
    tags = FolioTaggerStage()._reconciled_to_tags([
        ReconciledConcept(iri="", label=label, confidence=.8, contributing_paths=["llm"]),
    ], service, source_text=label)
    assert len(tags) == 1
    assert tags[0].iri == ""
    assert tags[0].extraction_path == "proposed_class"


@pytest.mark.parametrize("path", ["llm", "semantic", "heading_context"])
def test_concept_own_label_does_not_supply_source_evidence(service, atomic, path):
    tags = FolioTaggerStage()._reconciled_to_tags([
        ReconciledConcept(iri=DUTY if path != "llm" else "", label="Obligation",
                          confidence=.8, contributing_paths=[path]),
    ], service, source_text="The business sent a notification.")
    assert not any(t.iri for t in tags)


def test_label_resolution_is_not_a_semantic_verdict(service, atomic):
    tags = FolioTaggerStage()._reconciled_to_tags([
        ReconciledConcept(iri="", label="Duty", confidence=.8, contributing_paths=["llm"]),
    ], service, source_text="The duty requires notice.")
    [tag] = tags
    assert (tag.iri, tag.branch, tag.judge_status) == (DUTY, "Deontic Specification", None)


def test_model_carried_iri_is_refused_even_when_label_matches(service, atomic):
    assert FolioTaggerStage()._reconciled_to_tags([
        ReconciledConcept(iri=DUTY, label="Duty", confidence=.8, contributing_paths=["llm"]),
    ], service, source_text="The duty requires notice.") == []


def test_validated_semantic_origin_is_bound_to_source_and_catalog(service, atomic):
    from folio_insights.services.folio_ontology import SemanticSelectionVerdict

    stage = FolioTaggerStage()
    catalog = service.candidate_catalog([DUTY])
    selection = catalog.model_candidates()[0]["id"]
    text = "The business is required to notify its customers."
    verdict = SemanticSelectionVerdict.for_source(
        selection, catalog, text, verdict="correct", reason="Required conduct imposes a duty.",
    )
    tag = stage.resolve_semantic_tag(selection, catalog, service, source_text=text,
                                     verdict=verdict, confidence=.8)
    assert (tag.iri, tag.extraction_path, tag.judge_status) == (DUTY, "semantic_validated", "judged")
    assert stage.resolve_semantic_tag(selection, catalog, service, source_text="Other source.",
                                      verdict=verdict, confidence=.8) is None
    uncertain = SemanticSelectionVerdict.for_source(
        selection, catalog, text, verdict="uncertain", reason="Ambiguous conduct.",
    )
    assert stage.resolve_semantic_tag(selection, catalog, service, source_text=text,
                                      verdict=uncertain, confidence=.8) is None
    assert stage.resolve_semantic_tag(DUTY, catalog, service, source_text=text,
                                      verdict=verdict, confidence=.8) is None


def test_legacy_switch_keeps_legacy_branch_and_b9(service):
    stage = FolioTaggerStage()
    assert get_settings().atomic_extraction is False
    assert stage._branch_for(DUTY, service) == "Event"
    tags = stage._reconciled_to_tags([
        ReconciledConcept(iri=DUTY, label="Obligation", confidence=.8,
                          contributing_paths=["semantic"]),
    ], service)
    assert tags == []


class Provider:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def structured(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.result


def unit_with_text(text):
    from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span

    return KnowledgeUnit(text=text, original_span=Span(start=0, end=len(text), source_file="t.txt"),
                         unit_type=KnowledgeType.PRINCIPLE, source_file="t.txt")


@pytest.mark.asyncio
async def test_label_model_boundary_through_reconciliation(service, atomic, monkeypatch):
    from folio_insights.llm.templates import CONCEPT
    from folio_insights.services.bridge.llm_bridge import LLMBridge
    from folio_insights.services.bridge.reconciliation_bridge import FourPathReconciler

    provider = Provider({"concepts": [{"concept_text": "Duty", "confidence": .8}]})
    monkeypatch.setattr(LLMBridge, "get_llm_for_task", lambda self, task: provider)

    async def headings(*args):
        return []

    unit = unit_with_text("The duty requires notice.")
    await FolioTaggerStage()._tag_unit(
        unit, folio_service=service, embedding_service=None, aho_matcher=None,
        heading_extractor=SimpleNamespace(extract_heading_candidates=headings),
        reconciler=FourPathReconciler(),
    )
    [tag] = unit.folio_tags
    assert (tag.iri, tag.branch) == (DUTY, "Deontic Specification")
    assert unit.lineage[-1].template_id == CONCEPT.id
    assert provider.calls[0][1]["template"] is CONCEPT


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", [DUTY, "urn:folio:fake"])
async def test_label_model_boundary_refuses_iris(atomic, monkeypatch, selection):
    from folio_insights.services.bridge.llm_bridge import LLMBridge

    provider = Provider({"concepts": [{"concept_text": selection, "confidence": .9}]})
    monkeypatch.setattr(LLMBridge, "get_llm_for_task", lambda self, task: provider)
    assert await FolioTaggerStage()._run_llm_concept("The duty requires notice.", []) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", [DUTY, "fabricated"])
async def test_judge_boundary_refuses_out_of_catalog_ids(service, atomic, selection):
    from folio_insights.llm.templates import BRANCH_JUDGE
    from folio_insights.models.knowledge_unit import ConceptTag

    provider = Provider({"judged": [{"iri_hash": selection, "adjusted_score": 80,
                                     "verdict": "confirmed"}]})
    stage = FolioTaggerStage()
    stage._judge_provider = provider
    tag = ConceptTag(iri=DUTY, label="Duty", confidence=.8, extraction_path="llm")
    unit = unit_with_text("The duty requires notice.")
    [unjudged] = await stage._run_judge(unit, [tag], folio_service=service, prior_context="")
    assert unjudged.judge_status == "unjudged"
    assert DUTY not in provider.calls[0][0]
    assert provider.calls[0][1]["template"] is BRANCH_JUDGE
    assert unit.lineage[-1].action == "judge_unavailable"


def test_ambiguous_labels_do_not_choose_a_winner(service):
    service.replace_ontology(Ontology([
        concept(ROOT, "Event"),
        concept(DUTY, "Duty", [ROOT]),
        concept("https://folio.test/other", "Another Duty", [ROOT], alternative_labels=["Duty"]),
    ]))
    catalog = service.candidate_catalog()
    assert service.resolve_candidate("Duty", catalog) is None
    selection = next(c["id"] for c in catalog.model_candidates() if c["label"] == "Duty")
    assert service.resolve_candidate(selection, catalog).iri == DUTY


def test_bridge_exposes_resolver_owned_catalog(service, monkeypatch):
    from folio_insights.services.bridge import folio_bridge

    monkeypatch.setattr(folio_bridge, "get_folio_service", lambda: service)
    catalog = folio_bridge.get_candidate_catalog([DUTY])
    assert service.resolve_candidate(catalog.model_candidates()[0]["id"], catalog).iri == DUTY


def test_deontic_branch_is_found_when_membership_omits_root(service, atomic):
    # folio-python's get_folio_branches excludes the top-level root from its result.
    folio = service._get_folio()
    folio.get_folio_branches = lambda: {"EVENT": folio.classes[1:]}
    service.replace_ontology(folio)
    assert service.ancestor_branches(DUTY) == ("Deontic Specification", "Event")
    assert FolioTaggerStage()._branch_for(DUTY, service) == "Deontic Specification"


@pytest.mark.parametrize("path", ["semantic", "heading_context"])
def test_atomic_carried_concepts_still_require_their_own_b9_evidence(service, atomic, path):
    stage = FolioTaggerStage()
    tags = stage._reconciled_to_tags([
        ReconciledConcept(iri=DUTY, label="Obligation", confidence=.8,
                          contributing_paths=[path], evidence_text="A different heading."),
    ], service, source_text="The duty requires notice.")
    assert tags == []
    assert stage._iri_rejections == 1
