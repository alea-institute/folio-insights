"""Integration tests for the folio-enrich bridge adapters.

These tests require folio-enrich to be present on disk at the configured
path. They are marked with ``@pytest.mark.integration`` and can be skipped
in CI by running ``pytest -m "not integration"``.
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_folio_service_import():
    """Verify get_folio_service() returns a FolioService instance."""
    from folio_insights.services.bridge.folio_bridge import get_folio_service

    svc = get_folio_service()
    # FolioService should have a get_all_labels method
    assert hasattr(svc, "get_all_labels")
    assert hasattr(svc, "search_by_label")
    assert hasattr(svc, "get_concept")

    labels = svc.get_all_labels()
    assert len(labels) > 15000, f"Expected 15K+ labels, got {len(labels)}"


@pytest.mark.integration
def test_deterministic_entity_ruler_canary():
    """B5 canary: the deterministic ruler imports, loads the live FOLIO labels and
    emits a real FOLIO IRI for a plain legal term. Trips if the pinned ruler or
    the label source breaks, instead of letting tagging degrade silently."""
    from folio_insights.services.bridge.folio_bridge import (
        get_folio_service,
        verify_deterministic_bridge,
    )

    ruler = verify_deterministic_bridge()()
    ruler.load_patterns(get_folio_service().get_all_labels())
    matches = ruler.find_matches("The parties scheduled a deposition for next week.")
    iris = [getattr(m, "entity_id", "") for m in matches]
    assert any(iri.startswith("https://folio.openlegalstandard.org/") for iri in iris), iris


@pytest.mark.integration
def test_normalizer_import():
    """Verify get_normalizer() returns callable functions."""
    from folio_insights.services.bridge.folio_bridge import get_normalizer

    normalizer = get_normalizer()
    assert callable(normalizer["split_sentences"])
    assert callable(normalizer["chunk_text"])
    assert callable(normalizer["normalize_and_chunk"])

    # Quick smoke test
    sentences = normalizer["split_sentences"]("Hello world. This is a test.")
    assert len(sentences) >= 2


@pytest.mark.integration
def test_settings_isolation():
    """Verify folio-insights settings do not conflict with folio-enrich settings.

    folio-enrich uses env_prefix FOLIO_ENRICH_ and folio-insights uses
    FOLIO_INSIGHTS_, so they should not interfere.
    """
    from folio_insights.config import get_settings

    settings = get_settings()
    assert str(settings.folio_enrich_path).endswith("backend")

    # Importing folio-enrich's settings should work independently
    from folio_insights.services.bridge.folio_bridge import _ensure_folio_enrich_path

    _ensure_folio_enrich_path()
    from app.config import settings as enrich_settings

    assert enrich_settings.app_name == "FOLIO Enrich"
