"""Core data models: KnowledgeUnit and supporting types."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator

LinkType = Literal["exception-to", "penalty-for", "condition-of", "cites", "contradicts"]
LocalPropositionId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
PropositionKind = Literal["rule", "element", "exception", "penalty", "fact", "definition",
                          "advice", "citation", "outcome"]


class SourceProvenance(BaseModel):
    """Reference to the canonical source snapshot, without copying its text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_snapshot_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    genre: Literal["opinions", "statutes-regulations", "briefs", "know-how"]
    subgenre: str = ""


class PropositionLink(BaseModel):
    """A directed, document-local link; it is not a logical dependency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relation: LinkType
    target_id: LocalPropositionId


class UnresolvedCitation(BaseModel):
    """An external citation retained until deterministic target resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relation: Literal["cites"] = "cites"
    citation: str = Field(min_length=1)


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
    # Absent on legacy extraction JSON. Atomic identity is assigned by deterministic minting,
    # never by an extractor; these fields record support and meaning, not a key or an IRI.
    provenance: SourceProvenance | None = None
    proposition_kind: PropositionKind | None = None
    links: list[PropositionLink] = Field(default_factory=list)
    unresolved_citations: list[UnresolvedCitation] = Field(default_factory=list)

    def is_grounded(self, source_text: str, *, source_snapshot_id: str) -> bool:
        """Check exact snapshot support, independently of the legacy anchor score.

        Offsets count Unicode code points. This proves a verbatim source anchor, not
        semantic entailment of the atomic text. No serialized flag can supply this proof.
        """
        provenance = self.provenance
        span = self.original_span
        return (
            provenance is not None
            and provenance.source_snapshot_id == source_snapshot_id
            and provenance.source_sha256 == hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            and span.source_file == self.source_file
            and 0 <= span.start < span.end <= len(source_text)
            and self.source_snippet == source_text[span.start:span.end]
        )


def finalize_document(
    units: list[KnowledgeUnit], *, source_text: str, source_snapshot_id: str,
) -> list[KnowledgeUnit]:
    """Validate atomic output after every document-local proposition ID is stable.

    Return revalidated copies so mutations during extraction cannot bypass the link
    schema. Old JSON remains readable without provenance, but cannot claim snapshot
    grounding here. Reciprocal links are valid; logical dependency DAG rules live elsewhere.
    """
    finalized = [KnowledgeUnit.model_validate(unit.model_dump()) for unit in units]
    ids = {unit.id for unit in finalized}
    if len(ids) != len(finalized):
        raise ValueError("duplicate proposition ID")
    id_adapter = TypeAdapter(LocalPropositionId)
    for unit in finalized:
        # Use the same local-ID contract for both endpoints without changing legacy reads.
        id_adapter.validate_python(unit.id)
        if not unit.is_grounded(source_text, source_snapshot_id=source_snapshot_id):
            raise ValueError(f"{unit.id}: not grounded in source snapshot")
        for link in unit.links:
            if link.target_id == unit.id:
                raise ValueError(f"{unit.id}: self link is invalid")
            if link.target_id not in ids:
                raise ValueError(f"{unit.id}: missing link target {link.target_id}")
    return finalized
