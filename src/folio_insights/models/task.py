"""Data models for Phase 2: task hierarchy discovery.

Defines the core domain objects for discovered advocacy tasks,
task candidates, contradictions, and the overall task hierarchy.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from folio_insights.models.corpus import CorpusDocument
from folio_insights.models.knowledge_unit import KnowledgeUnit


class TaskCandidate(BaseModel):
    """A candidate task discovered from heading or content analysis.

    Candidates are produced by HeadingAnalysis and ContentClustering stages,
    then refined by FolioMapping. They are promoted to DiscoveredTasks
    during HierarchyConstruction.
    """

    label: str
    folio_iri: str | None = None
    folio_label: str = ""
    source_signal: str  # "heading", "clustering", "llm"
    confidence: float
    heading_path: list[str] = Field(default_factory=list)
    knowledge_unit_ids: list[str] = Field(default_factory=list)
    is_procedural: bool = False
    canonical_order: int | None = None
    source_file: str = ""


class DiscoveredTask(BaseModel):
    """A validated task in the discovered hierarchy.

    Each task maps to a FOLIO concept IRI (or proposes a new sibling).
    Knowledge units link to tasks; units are grouped by type under each task.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    label: str
    description: str = ""
    folio_iri: str | None = None
    folio_label: str = ""
    parent_task_id: str | None = None
    parent_iris: list[str] = Field(default_factory=list)
    depth: int = 0
    is_procedural: bool = False
    canonical_order: int | None = None
    unit_type_counts: dict[str, int] = Field(default_factory=dict)
    confidence: float = 0.0
    source_signals: list[str] = Field(default_factory=list)
    is_manual: bool = False
    has_contradictions: bool = False
    has_orphans: bool = False
    is_jurisdiction_sensitive: bool = False
    review_status: str = "unreviewed"
    metadata: dict = Field(default_factory=dict)


class Contradiction(BaseModel):
    """A detected semantic contradiction between two knowledge units.

    Found by cross-encoder NLI screening and confirmed by LLM analysis.
    Stored with both positions and source references for reviewer resolution.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    unit_id_a: str
    unit_id_b: str
    nli_score: float
    contradiction_type: str = "full"  # "full", "partial", "jurisdictional"
    explanation: str = ""
    context_dependency: str = ""
    resolution: str | None = None  # "keep_both", "prefer_a", "prefer_b", "merge", "jurisdiction"
    resolved_text: str | None = None
    resolver_note: str = ""
    resolved_at: str | None = None


class TaskHierarchy(BaseModel):
    """The complete discovered task hierarchy for a corpus.

    Links tasks to knowledge units bidirectionally and tracks
    contradictions and orphan units.
    """

    tasks: list[DiscoveredTask] = Field(default_factory=list)
    task_unit_links: dict[str, list[str]] = Field(default_factory=dict)
    unit_task_links: dict[str, list[str]] = Field(default_factory=dict)
    contradictions: list[Contradiction] = Field(default_factory=list)
    orphan_unit_ids: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class DiscoveryJob(BaseModel):
    """Pipeline job carrying state across task discovery stages.

    Analogous to InsightsJob for the extraction pipeline, but typed
    for the 6-stage discovery pipeline.
    """

    corpus_name: str
    source_dir: Path
    knowledge_units: list[KnowledgeUnit] = Field(default_factory=list)
    documents: list[CorpusDocument] = Field(default_factory=list)
    task_candidates: list[TaskCandidate] = Field(default_factory=list)
    discovered_tasks: list[DiscoveredTask] = Field(default_factory=list)
    task_hierarchy: TaskHierarchy | None = None
    contradictions: list[Contradiction] = Field(default_factory=list)
    orphan_unit_ids: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


def compute_task_confidence(
    folio_confidence: float,
    heading_confidence: float,
    folio_weight: float = 0.7,
    heading_weight: float = 0.3,
) -> float:
    """Compute weighted blend of FOLIO and heading confidence.

    Per CONTEXT.md: FOLIO tags get much higher weight than heading context.
    Default weights: 70% FOLIO, 30% heading.

    Args:
        folio_confidence: Confidence from FOLIO tag matching (0-1).
        heading_confidence: Confidence from heading proximity (0-1).
        folio_weight: Weight for FOLIO signal (default 0.7).
        heading_weight: Weight for heading signal (default 0.3).

    Returns:
        Blended confidence score.
    """
    return (folio_confidence * folio_weight) + (heading_confidence * heading_weight)
