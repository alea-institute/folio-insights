"""Offline regressions for label provenance and translation matching."""

from types import SimpleNamespace

import pytest
from lxml import etree

from folio_insights.services.folio_ontology import FolioOntologyService

_IRI = "https://example.org/Claims"


@pytest.fixture
def folio_stub():
    tree = etree.fromstring(f"""<rdf:RDF
        xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        xmlns:owl="http://www.w3.org/2002/07/owl#"
        xmlns:skos="http://www.w3.org/2004/02/skos/core#">
      <owl:Class rdf:about="{_IRI}">
        <skos:altLabel>Dependency Claims</skos:altLabel>
        <skos:altLabel xml:lang="en-gb">Dependency Claims</skos:altLabel>
        <skos:altLabel xml:lang="es-mx">Gasto Procesal</skos:altLabel>
        <skos:altLabel xml:lang="es-mx">Reclamaciones</skos:altLabel>
        <skos:altLabel>Claims Alias</skos:altLabel>
        <skos:hiddenLabel>X1</skos:hiddenLabel>
      </owl:Class>
    </rdf:RDF>""")
    concept = SimpleNamespace(
        iri=_IRI,
        label="Claims",
        alternative_labels=[
            "Dependency Claims", "Gasto Procesal", "Reclamaciones", "Claims Alias", "X1",
        ],
        translations={"en-gb": "Dependency Claims", "es-mx": "Reclamaciones"},
        hidden_label="X1",
    )

    class FolioStub:
        classes = [concept]

        def get_folio_branches(self):
            return {}

        def get_parents(self, iri):
            return []

        def __getitem__(self, iri):
            assert iri == _IRI
            return concept

        def search_by_label(self, label, include_alt_labels=True, limit=10):
            return [(concept, 100.0)]

        def search_by_prefix(self, prefix):
            return [concept]

    stub = FolioStub()
    stub.tree = tree
    return stub


def test_untagged_aliases_and_hidden_label_keep_parser_order(folio_stub, tmp_path, monkeypatch):
    monkeypatch.setattr(FolioOntologyService, "_compute_label_lemmas", lambda self: {})
    service = FolioOntologyService(folio=folio_stub, lemma_cache_dir=tmp_path)

    aliases = ["Dependency Claims", "Claims Alias", "X1"]
    assert service.get_concept(_IRI).alternative_labels == aliases
    assert [concept.alternative_labels for concept in service.search_by_prefix("Claim")] == [aliases]
    assert list(service.get_all_labels()) == ["claims", "dependency claims", "claims alias", "x1"]


def test_label_search_respects_translation_matching(folio_stub, tmp_path):
    default_service = FolioOntologyService(folio=folio_stub, lemma_cache_dir=tmp_path)
    translation_service = FolioOntologyService(
        folio=folio_stub, lemma_cache_dir=tmp_path, translation_matching_enabled=True,
    )

    [(hit, score)] = default_service.search_by_label("Gasto Procesal")
    assert hit.iri == _IRI
    assert score < 100.0
    assert translation_service.search_by_label("Gasto Procesal") == [(hit, 100.0)]
