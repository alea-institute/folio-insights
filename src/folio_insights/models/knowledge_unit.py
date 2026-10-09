"""Core data models: KnowledgeUnit and supporting types."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class KnowledgeType(str, Enum):
    """Classification of a knowledge unit."""

    ADVICE = "advice"
    PRINCIPLE = "principle"
    CITATION = "citation"
    RULE = "procedural_rule"
    PITFALL = "pitfall"


class Span(BaseModel):
    """Character-level location in a source file."""

    start: int
    end: int
    source_file: str


class ConceptTag(BaseModel):
    """A FOLIO concept tag applied to a knowledge unit."""

    iri: str
    label: str
    confidence: float
    extraction_path: str  # "entity_ruler", "llm", "semantic", "heading_context"
    branch: str = ""
    # LLM-judge outcome for a non-ruler IRI (Phase 10 KTD7): "judged" when the judge ruled on it,
    # "unjudged" when the judge was down or skipped it (the tag is kept, but a minter must treat
    # it as unverified). None when no judge applies (ruler / proposed-class tags) or the judge
    # stage was not enabled for the run (see ``metadata.folio_tagger.judge_enabled``).
    judge_status: str | None = None


class StageEvent(BaseModel):
    """A lineage event recorded by a pipeline stage.

    An event written as the direct result of an LLM call also names the registered prompt
    template that call used (KTD2): ``template_id`` is the
    :class:`~folio_insights.llm.templates.PromptTemplate` id and ``template_hash`` its identity
    hash. Deterministic events leave both ``None``. The fields are optional so lineage written
    before they existed (old ``extraction.json`` files and checkpoints) still loads; a unit's
    prompt hash is derived from them by ``folio_insights.llm.templates.unit_prompt_hash``.
    """

    stage: str
    action: str
    detail: str = ""
    confidence: float | None = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    template_id: str | None = None
    template_hash: str | None = None

    @model_validator(mode="after")
    def _template_identity_is_whole(self) -> StageEvent:
        """A template id without its hash (or the reverse) cannot identify a prompt."""
        if (self.template_id is None) != (self.template_hash is None):
            raise ValueError(
                "StageEvent template_id and template_hash must be given together "
                f"(got template_id={self.template_id!r}, template_hash={self.template_hash!r})"
            )
        return self


class KnowledgeUnit(BaseModel):
    """A single actionable piece of legal knowledge."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str
    original_span: Span
    # Verifiable source anchor (RUB-EXTRACT-05): a unit may paraphrase, but it carries the exact
    # source substring at its span, the anchor's match score (1.0 = exact) and whether the score
    # reached the verification threshold (services.anchoring, 0.85).
    source_snippet: str = ""
    anchor_verified: bool = False
    anchor_score: float = 0.0
    unit_type: KnowledgeType
    source_file: str
    source_section: list[str] = Field(default_factory=list)
    folio_tags: list[ConceptTag] = Field(default_factory=list)
    surprise_score: float = 0.0
    confidence: float = 0.0
    content_hash: str = ""
    lineage: list[StageEvent] = Field(default_factory=list)
    cross_references: list[str] = Field(default_factory=list)
