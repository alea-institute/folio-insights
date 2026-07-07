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
    """Canary: the deterministic FOLIO entity ruler imports AND matches.

    Trips the moment folio-enrich reorganizes the ruler module or a runtime
    dep (spacy) goes missing — the exact silent break that produced ~60%
    wrong-concept IRIs in book-UAT (docs/solutions/sys-path-bridge-staleness.md).
    A bare import success is not enough: we assert a *known* legal string
    resolves to a real FOLIO IRI via the ruler's find_matches().
    """
    from folio_insights.services.bridge.folio_bridge import (
        get_folio_service,
        verify_deterministic_bridge,
    )

    RulerClass = verify_deterministic_bridge()  # raises BridgeIntegrityError if broken
    ruler = RulerClass()
    ruler.load_patterns(get_folio_service().get_all_labels())

    matches = ruler.find_matches(
        "Counsel filed a motion for summary judgment before the deposition."
    )
    iris = [getattr(m, "entity_id", "") for m in matches]
    labels = [getattr(m, "text", "") for m in matches]
    assert any(iri.startswith("https://folio.openlegalstandard.org/") for iri in iris), (
        f"deterministic ruler produced no FOLIO IRIs (got {list(zip(labels, iris))})"
    )
    assert any("deposition" in (l or "").lower() for l in labels), (
        f"expected a 'deposition' match from the ruler, got {labels}"
    )


@pytest.mark.integration
def test_bridge_integrity_error_is_loud():
    """A missing bridge symbol raises BridgeIntegrityError, never returns None."""
    from folio_insights.services.bridge.folio_bridge import (
        BridgeIntegrityError,
        get_entity_ruler,
    )

    # Happy path returns a class (not None).
    cls = get_entity_ruler()
    assert cls is not None and isinstance(cls, type)
    # The error type exists and is a RuntimeError subclass (loud by design).
    assert issubclass(BridgeIntegrityError, RuntimeError)


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
