"""Getters for the FOLIO/enrich-derived services folio-insights depends on.

Historically every getter here inserted ``settings.folio_enrich_path`` into
``sys.path`` and imported folio-enrich's working tree. Deployed images do not ship
that checkout, so those getters silently degraded in production. As of the
2026-10-09 bridge retirement (``docs/bridge-retirement-2026-10-09.md``) the
getters return in-repo implementations with parity tests
(``tests/test_bridge_retirement_parity.py``) and no longer touch ``sys.path``:

* ``get_folio_service``      -> ``folio_insights.services.folio_ontology.FolioOntologyService``
* ``get_embedding_service``  -> ``folio_insights.services.embedding.EmbeddingService``
* ``get_normalizer``         -> ``folio_insights.services.text_normalization``
* ``get_citation_extractor`` -> ``folio_insights.services.citation_extraction.CitationExtractor``
* ``get_entity_ruler``       -> pinned ``folio_resolve.FOLIOEntityRuler`` (unchanged)

``_ensure_folio_enrich_path`` remains only for the KEPT ``ingestion_bridge``
(folio-enrich's multi-format ingestion registry) and the integration parity tests.
Function names and return-value contracts are unchanged, so callers do not change.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

_path_ensured = False


def _ensure_folio_enrich_path() -> str:
    """Add folio-enrich's backend directory to sys.path if not already present.

    Also sets environment variables needed by folio-enrich's Settings
    so that importing ``app.config`` does not fail.

    Returns the resolved path string.
    """
    global _path_ensured
    if _path_ensured:
        return _get_enrich_path()

    enrich_path = _get_enrich_path()

    if enrich_path not in sys.path:
        sys.path.insert(0, enrich_path)

    _path_ensured = True
    logger.info("folio-enrich path ensured: %s", enrich_path)
    return enrich_path


def _get_enrich_path() -> str:
    """Resolve the folio-enrich backend path from settings."""
    from folio_insights.config import get_settings

    settings = get_settings()
    enrich_path = str(settings.folio_enrich_path.expanduser().resolve())

    if not os.path.isdir(enrich_path):
        raise FileNotFoundError(
            f"folio-enrich backend not found at {enrich_path}.\n"
            f"\n"
            f"folio-insights still imports folio-enrich's multi-format ingestion\n"
            f"registry (IngestionBridge: .md/.txt/.docx/.pdf/.html/.rtf/.eml/.msg)\n"
            f"via a sys.path bridge. Clone folio-enrich as a sibling directory:\n"
            f"\n"
            f"    git clone https://github.com/alea-institute/folio-enrich\n"
            f"\n"
            f"Or set the FOLIO_INSIGHTS_FOLIO_ENRICH_PATH environment variable\n"
            f"(or FOLIO_ENRICH_PATH in a .env file) to point at an existing\n"
            f"folio-enrich/backend directory."
        )
    return enrich_path


def get_folio_service() -> Any:
    """Return the process-wide FOLIO ontology read service.

    In-repo ``FolioOntologyService`` (vendored from folio-enrich's ``FolioService``):
    ``search_by_label``, ``get_concept``, ``get_all_labels`` with the same return shapes.
    """
    from folio_insights.services.folio_ontology import FolioOntologyService

    return FolioOntologyService.get_instance()


def get_embedding_service() -> Any:
    """Return the process-wide embedding service (sentence-transformers all-MiniLM-L6-v2)."""
    from folio_insights.services.embedding import EmbeddingService

    return EmbeddingService.get_instance()


def get_normalizer() -> dict[str, Any]:
    """Return the in-repo normalizer functions.

    Returns a dict with keys: ``split_sentences``, ``chunk_text``,
    ``normalize_and_chunk``.
    """
    from folio_insights.services.text_normalization import (
        chunk_text,
        normalize_and_chunk,
        split_sentences,
    )

    return {
        "split_sentences": split_sentences,
        "chunk_text": chunk_text,
        "normalize_and_chunk": normalize_and_chunk,
    }


class BridgeIntegrityError(RuntimeError):
    """A required deterministic-matcher symbol cannot be imported.

    A sys.path bridge couples this package to a sibling checkout by directory
    layout and internal API, and either can change without notice. When the
    deterministic matcher breaks, callers must fail loud: a silent per-item
    fallback to LLM guessing yields plausible but wrong IRIs.
    """


def get_entity_ruler() -> Any:
    """Return the deterministic FOLIO entity-ruler class.

    It is the pinned ``folio_resolve.FOLIOEntityRuler``: ``load_patterns(labels)``
    with ``FolioService.get_all_labels()`` output, then ``find_matches(text)``
    returning matches with ``.entity_id`` (the FOLIO IRI) and ``.text``. It
    replaces the old import of folio-enrich's ``AhoCorasickMatcher`` from
    ``app.services.concept.entity_ruler``, a module folio-enrich has since
    moved, and it needs neither the sys.path bridge nor spaCy.

    Raises ``BridgeIntegrityError`` (never returns ``None``) when the symbol is
    missing.
    """
    try:
        from folio_resolve import FOLIOEntityRuler
    except ImportError as exc:
        raise BridgeIntegrityError(
            "Could not import the deterministic FOLIO entity ruler "
            "(folio_resolve.FOLIOEntityRuler). It is the deterministic IRI path; without it "
            "the tagger would fall back to LLM/semantic IRIs. Reinstall the pinned "
            f"folio-resolve dependency. Underlying error: {exc!r}"
        ) from exc
    return FOLIOEntityRuler


def get_aho_corasick_matcher() -> Any:
    """Deprecated alias for :func:`get_entity_ruler` (kept for old import sites)."""
    return get_entity_ruler()


def verify_deterministic_bridge() -> Any:
    """Startup canary: import and instantiate the deterministic ruler, loudly.

    Returns the ruler class, or raises ``BridgeIntegrityError``.
    """
    ruler_cls = get_entity_ruler()
    ruler_cls()
    return ruler_cls


def get_citation_extractor() -> Any:
    """Return the in-repo CitationExtractor class (vendored from folio-enrich)."""
    from folio_insights.services.citation_extraction import CitationExtractor

    return CitationExtractor
