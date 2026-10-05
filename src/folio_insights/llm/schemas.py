"""Validated output schemas for every structured LLM task.

These are plain Pydantic models with no provider or pipeline imports, so the template registry
can hash them and stage modules can import them without pulling in an SDK. Each model mirrors
the JSON-schema dict the call site used to pass to the folio-enrich bridge; fields that schema
marked optional keep a default here, required ones stay required so a malformed reply fails
validation and triggers the port's single retry layer instead of flowing on as a half-empty dict.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DistilledOutput(BaseModel):
    """Structured output from the distillation LLM call."""

    distilled_text: str
    preserved_nuances: list[str] = Field(default_factory=list)


class ClassificationOutput(BaseModel):
    """Knowledge-type classification of one unit."""

    unit_type: str
    confidence: float
    reasoning: str = ""


class NoveltyOutput(BaseModel):
    """Novelty / surprise score of one unit."""

    score: float
    reasoning: str = ""


class ConceptCandidate(BaseModel):
    """One FOLIO concept label the LLM concept path proposes (never an IRI)."""

    concept_text: str
    confidence: float = 0.5


class ConceptOutput(BaseModel):
    """LLM concept-identification output. Labels only: the LLM never mints an IRI (R1)."""

    concepts: list[ConceptCandidate] = Field(default_factory=list)


class JudgedCandidate(BaseModel):
    """One judge verdict, keyed by the short candidate id the prompt assigned (``c0``...)."""

    iri_hash: str
    adjusted_score: float
    verdict: str
    reasoning: str = ""


class JudgeOutput(BaseModel):
    """The definition-level judge's verdicts for one unit's non-ruler candidates."""

    judged: list[JudgedCandidate] = Field(default_factory=list)


class BoundaryRefinement(BaseModel):
    """An LLM-suggested boundary split within a text segment."""

    start_char: int
    end_char: int
    rationale: str = ""


class BoundaryRefinementResponse(BaseModel):
    """Structured response from the LLM boundary refinement call."""

    boundaries: list[BoundaryRefinement] = Field(default_factory=list)


class PolysemyVerdict(BaseModel):
    """Instructor response model for the polysemy LLM-fallback and FP-audit calls.

    Kept separate from ``polysemy.detector.LLMVerdict`` so that the LLM contract (what the model
    is asked to produce) is decoupled from the detector output contract (what downstream
    consumers read).
    """

    decision: Literal["polysemy", "homonymy", "coincidence", "uncertain"]
    polysemy_vs_homonymy_reasoning: str
    rationale: str


class FrameworkChoice(BaseModel):
    """The framework detector's LLM stage (Phase 9 U2): one of the REGISTERED
    framework IDs listed in the prompt, or null. The detector rejects any ID
    that is not registered; the LLM never mints one (KTD12)."""

    framework_id: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
