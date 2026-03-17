"""Bridge adapter for importing folio-enrich services.

Uses sys.path manipulation to import folio-enrich's services as a library
without modifying folio-enrich's codebase.
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
            f"folio-enrich backend not found at {enrich_path}. "
            f"Set FOLIO_INSIGHTS_FOLIO_ENRICH_PATH or update .env"
        )
    return enrich_path


def get_folio_service() -> Any:
    """Import and return the FolioService singleton from folio-enrich.

    Returns an instance of ``app.services.folio.folio_service.FolioService``.
    """
    _ensure_folio_enrich_path()
    from app.services.folio.folio_service import FolioService

    return FolioService.get_instance()


def get_embedding_service() -> Any:
    """Import and return the EmbeddingService singleton from folio-enrich."""
    _ensure_folio_enrich_path()
    from app.services.embedding.service import EmbeddingService

    return EmbeddingService.get_instance()


def get_normalizer() -> dict[str, Any]:
    """Import and return normalizer functions from folio-enrich.

    Returns a dict with keys: ``split_sentences``, ``chunk_text``,
    ``normalize_and_chunk``.
    """
    _ensure_folio_enrich_path()
    from app.services.normalization.normalizer import (
        chunk_text,
        normalize_and_chunk,
        split_sentences,
    )

    return {
        "split_sentences": split_sentences,
        "chunk_text": chunk_text,
        "normalize_and_chunk": normalize_and_chunk,
    }


def get_aho_corasick_matcher() -> Any:
    """Import and return the AhoCorasickMatcher from folio-enrich."""
    _ensure_folio_enrich_path()
    from app.services.concept.entity_ruler import AhoCorasickMatcher

    return AhoCorasickMatcher


def get_citation_extractor() -> Any:
    """Import and return the CitationExtractor from folio-enrich."""
    _ensure_folio_enrich_path()
    from app.services.individual.citation_extractor import CitationExtractor

    return CitationExtractor
