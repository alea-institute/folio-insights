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
            f"folio-enrich backend not found at {enrich_path}.\n"
            f"\n"
            f"folio-insights imports services from folio-enrich via a sys.path\n"
            f"bridge. Clone folio-enrich as a sibling directory:\n"
            f"\n"
            f"    git clone https://github.com/alea-institute/folio-enrich\n"
            f"\n"
            f"Or set the FOLIO_INSIGHTS_FOLIO_ENRICH_PATH environment variable\n"
            f"(or FOLIO_ENRICH_PATH in a .env file) to point at an existing\n"
            f"folio-enrich/backend directory."
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


class BridgeIntegrityError(RuntimeError):
    """Raised when a required folio-enrich bridge symbol cannot be imported.

    A ``sys.path`` bridge couples folio-insights to folio-enrich by directory
    layout *and* internal API — either can change with no signal to us. When
    the deterministic entity-ruler import breaks, the pipeline must fail LOUD:
    a silent per-item fallback to LLM guessing is what produced ~60%
    wrong-concept IRIs in book-UAT (docs/solutions/sys-path-bridge-staleness.md).
    """


def get_entity_ruler() -> Any:
    """Import and return folio-enrich's FOLIOEntityRuler class.

    This is the DETERMINISTIC FOLIO concept matcher: it loads FOLIO concept
    labels/aliases as spaCy EntityRuler patterns (``load_patterns``) and
    returns real FOLIO IRIs via ``find_matches`` (``.entity_id`` / ``.text``).

    folio-enrich was reorganized: the old monolithic
    ``app.services.concept.entity_ruler.AhoCorasickMatcher`` split into a
    low-level string matcher (``app.services.matching.aho_corasick``) and this
    FOLIO-aware ruler (``app.services.entity_ruler.ruler``). The ruler's API
    (``load_patterns(dict[str, LabelInfo])`` + ``find_matches`` →
    ``EntityRulerMatch(.text, .entity_id, ...)``) is what folio-insights'
    FolioTaggerStage consumes.

    Raises ``BridgeIntegrityError`` (never returns None) if the symbol is
    missing, so callers surface a loud failure instead of degrading silently.
    """
    enrich_path = _ensure_folio_enrich_path()
    try:
        from app.services.entity_ruler.ruler import FOLIOEntityRuler
    except ImportError as exc:  # module moved, or a runtime dep (spacy) missing
        raise BridgeIntegrityError(
            "Could not import the deterministic FOLIO entity ruler "
            "(app.services.entity_ruler.ruler.FOLIOEntityRuler) from "
            f"folio-enrich at {enrich_path!r}.\n"
            f"  Underlying import error: {exc!r}\n"
            "\n"
            "This is the DETERMINISTIC IRI path. Without it the FOLIO tagger "
            "would fall back to LLM/semantic guessing and emit wrong-concept "
            "IRIs silently (see docs/solutions/sys-path-bridge-staleness.md).\n"
            "\n"
            "Likely causes:\n"
            "  1. folio-enrich was reorganized again — check the module path.\n"
            "  2. A bridge-tier runtime dep is missing in THIS venv. The ruler "
            "needs 'spacy'; install the bridge deps:\n"
            "       VIRTUAL_ENV=\"$PWD/.venv\" uv pip install -e '.[dev]'\n"
        ) from exc

    return FOLIOEntityRuler


# Backwards-compatible alias. The symbol used to be an Aho-Corasick matcher;
# the deterministic FOLIO matcher is now FOLIOEntityRuler. Callers should
# prefer get_entity_ruler(); this keeps older import sites working.
def get_aho_corasick_matcher() -> Any:
    """Deprecated alias for :func:`get_entity_ruler`."""
    return get_entity_ruler()


def verify_deterministic_bridge() -> Any:
    """Startup canary: import + instantiate the deterministic ruler, loudly.

    Returns the ``FOLIOEntityRuler`` *class* on success. Raises
    ``BridgeIntegrityError`` with actionable guidance on failure. Call this
    once at pipeline init to trip the moment the sibling reorganizes or a dep
    goes missing — rather than discovering it as silently-wrong output.
    """
    ruler_cls = get_entity_ruler()
    # Instantiation shouldn't touch the ontology, but confirms the class is
    # constructible (spaCy import path is exercised lazily inside _get_nlp).
    ruler_cls()
    return ruler_cls


def get_citation_extractor() -> Any:
    """Import and return the CitationExtractor from folio-enrich."""
    _ensure_folio_enrich_path()
    from app.services.individual.citation_extractor import CitationExtractor

    return CitationExtractor
