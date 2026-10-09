# Vendored from folio-enrich backend/app/services/individual/citation_extractor.py @ 510a652 (MIT).
"""In-repo legal citation extractor (Eyecite + CiteURL).

Replaces the sys.path bridge to folio-enrich's
``app.services.individual.citation_extractor.CitationExtractor``. The extraction
logic is copied verbatim; folio-enrich's ``app.models.annotation`` pydantic models
(``Individual``, ``IndividualClassLink``, ``Span``, ``StageEvent``) became the
local equivalents below (same fields the extractor populates).

Both libraries are optional imports, exactly as in the enrich original: when
``eyecite`` / ``citeurl`` are not installed the corresponding pass logs a warning
and contributes nothing. Neither is a folio-insights dependency today, so this
extractor (like the bridge it replaces, which ran enrich's code in this same
environment) returns no citations unless they are installed. Declaring them is a
separate behavior change: it would start reclassifying citation-bearing units as
``KnowledgeType.CITATION`` in ``knowledge_classifier``. Parity with the enrich
implementation is pinned by ``tests/test_bridge_retirement_parity.py``.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class StageEvent(BaseModel):
    stage: str
    action: str
    detail: str = ""
    confidence: float | None = None
    timestamp: str = ""
    reasoning: str = ""


class Span(BaseModel):
    start: int
    end: int
    text: str
    sentence_text: str | None = None


class IndividualClassLink(BaseModel):
    annotation_id: str | None = None
    folio_iri: str | None = None
    folio_label: str | None = None
    branch: str = ""
    relationship: str = "instance_of"
    confidence: float = 0.0


class Individual(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    mention_text: str
    individual_type: str = "named_entity"
    span: Span
    class_links: list[IndividualClassLink] = Field(default_factory=list)
    confidence: float = 0.0
    source: str = "llm"
    normalized_form: str | None = None
    url: str | None = None
    lineage: list[StageEvent] = Field(default_factory=list)


# Citation type → FOLIO class label mapping
_CITATION_TYPE_MAP: dict[str, str] = {
    "FullCaseCitation": "Caselaw",
    "ShortCaseCitation": "Caselaw",
    "FullLawCitation": "Statute",
    "FullJournalCitation": "Legal Scholarship",
    "SupraCitation": "Caselaw",
    "IdCitation": "Caselaw",
    "UnknownCitation": "Legal Citation",
}


def _eyecite_type_name(citation) -> str:
    """Get the class name of an eyecite citation object."""
    return type(citation).__name__


def _extract_with_eyecite(text: str) -> list[Individual]:
    """Run eyecite extraction synchronously. Returns Individual objects."""
    try:
        from eyecite import get_citations
    except ImportError:
        logger.warning("eyecite not installed — skipping citation extraction")
        return []

    try:
        citations = get_citations(text)
    except Exception:
        logger.exception("eyecite extraction failed")
        return []

    individuals: list[Individual] = []
    for cite in citations:
        cite_type = _eyecite_type_name(cite)

        # Get matched text and span
        matched_text = cite.matched_text()
        if not matched_text:
            continue

        # Find span in original text
        token = cite.token
        start = token.start if hasattr(token, "start") else text.find(matched_text)
        end = token.end if hasattr(token, "end") else start + len(matched_text)

        if start < 0:
            continue

        # Determine FOLIO class label from citation type
        folio_label = _CITATION_TYPE_MAP.get(cite_type, "Legal Citation")

        # Build normalized form using eyecite's clean output methods
        if hasattr(cite, "corrected_citation_full"):
            full = cite.corrected_citation_full()
            normalized = full if full and full != matched_text else None
        elif hasattr(cite, "corrected_citation"):
            corr = cite.corrected_citation()
            normalized = corr if corr and corr != matched_text else None
        else:
            normalized = None

        individual = Individual(
            id=str(uuid4()),
            name=matched_text.strip(),
            mention_text=matched_text,
            individual_type="legal_citation",
            span=Span(start=start, end=end, text=matched_text),
            class_links=[
                IndividualClassLink(
                    folio_label=folio_label,
                    relationship="instance_of",
                    confidence=0.92,
                )
            ],
            confidence=0.92,
            source="eyecite",
            normalized_form=normalized,
            lineage=[
                StageEvent(
                    stage="individual_extraction",
                    action="created",
                    detail=f"eyecite: {cite_type}",
                    confidence=0.92,
                )
            ],
        )
        individuals.append(individual)

    return individuals


def _normalize_with_citeurl(text: str, individuals: list[Individual]) -> list[Individual]:
    """Run CiteURL normalization on existing individuals + find additional citations."""
    try:
        from citeurl import Citator
    except ImportError:
        logger.warning("citeurl not installed — skipping citation normalization")
        return individuals

    try:
        citator = Citator()
    except Exception:
        logger.exception("Failed to initialize CiteURL Citator")
        return individuals

    # Try to normalize existing eyecite individuals
    for ind in individuals:
        try:
            cite = citator.cite(ind.mention_text)
            if cite:
                if cite.URL:
                    ind.url = cite.URL
                normalized = str(cite)
                if normalized and normalized != ind.mention_text:
                    ind.normalized_form = normalized
        except Exception:
            pass  # CiteURL couldn't parse this particular citation

    # Also run CiteURL's own extraction on the full text for anything eyecite missed
    extra: list[Individual] = []
    try:
        citeurl_citations = citator.list_cites(text)
    except Exception:
        logger.debug("CiteURL list_cites failed", exc_info=True)
        return individuals

    # Build set of existing spans to avoid duplicates
    existing_spans = {(ind.span.start, ind.span.end) for ind in individuals}

    for cite in citeurl_citations:
        # CiteURL cites from list_cites have .start and .end on source_text tokens
        try:
            matched = cite.matched_text() if hasattr(cite, "matched_text") else str(cite)
            if not matched:
                continue

            # Find position in text
            start = text.find(matched)
            if start < 0:
                continue
            end = start + len(matched)

            if (start, end) in existing_spans:
                continue

            url = cite.URL if hasattr(cite, "URL") else None
            normalized = str(cite) if str(cite) != matched else None

            individual = Individual(
                id=str(uuid4()),
                name=matched.strip(),
                mention_text=matched,
                individual_type="legal_citation",
                span=Span(start=start, end=end, text=matched),
                class_links=[
                    IndividualClassLink(
                        folio_label="Legal Citation",
                        relationship="instance_of",
                        confidence=0.90,
                    )
                ],
                confidence=0.90,
                source="citeurl",
                normalized_form=normalized,
                url=url,
                lineage=[
                    StageEvent(
                        stage="individual_extraction",
                        action="created",
                        detail="citeurl: additional citation",
                        confidence=0.90,
                    )
                ],
            )
            extra.append(individual)
            existing_spans.add((start, end))
        except Exception:
            continue

    return individuals + extra


class CitationExtractor:
    """Extracts legal citations using Eyecite + CiteURL."""

    async def extract(self, text: str) -> list[Individual]:
        """Extract citations from text. Runs sync libraries in executor."""
        loop = asyncio.get_running_loop()

        # Run eyecite in executor (sync library)
        individuals = await loop.run_in_executor(
            None, partial(_extract_with_eyecite, text)
        )

        # Run citeurl normalization + additional extraction in executor
        individuals = await loop.run_in_executor(
            None, partial(_normalize_with_citeurl, text, individuals)
        )

        logger.info("Citation extraction found %d citations", len(individuals))
        return individuals
