"""Core data models: KnowledgeUnit and supporting types."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


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


class StageEvent(BaseModel):
    """A lineage event recorded by a pipeline stage."""

    stage: str
    action: str
    detail: str = ""
    confidence: float | None = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class KnowledgeUnit(BaseModel):
    """A single actionable piece of legal knowledge."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str
    original_span: Span
    unit_type: KnowledgeType
    source_file: str
    source_section: list[str] = Field(default_factory=list)
    folio_tags: list[ConceptTag] = Field(default_factory=list)
    surprise_score: float = 0.0
    confidence: float = 0.0
    content_hash: str = ""
    lineage: list[StageEvent] = Field(default_factory=list)
    cross_references: list[str] = Field(default_factory=list)
