"""Pydantic models for task discovery API endpoints."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from api.models.processing import ActivityEntry, ProcessingStatus


# ---------------------------------------------------------------------------
# Discovery Job (mirrors ProcessingJob pattern)
# ---------------------------------------------------------------------------


class DiscoveryJob(BaseModel):
    """Tracks a long-running task discovery job."""

    id: UUID
    corpus_id: str
    status: ProcessingStatus = ProcessingStatus.PENDING
    current_stage: str | None = None
    progress_pct: int = 0
    total_tasks: int = 0
    activity_log: list[ActivityEntry] = Field(default_factory=list)
    error: str | None = None
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Task Responses
# ---------------------------------------------------------------------------


class TaskResponse(BaseModel):
    """Full task detail for API responses."""

    id: str
    label: str
    description: str = ""
    folio_iri: str | None = None
    folio_label: str = ""
    parent_task_id: str | None = None
    depth: int = 0
    is_procedural: bool = False
    canonical_order: int | None = None
    unit_type_counts: dict[str, int] = Field(default_factory=dict)
    confidence: float = 0.0
    review_status: str = "unreviewed"
    has_contradictions: bool = False
    has_orphans: bool = False
    is_jurisdiction_sensitive: bool = False
    is_manual: bool = False


class TaskTreeNode(BaseModel):
    """A node in the task tree hierarchy."""

    id: str
    label: str
    folio_iri: str | None = None
    parent_id: str | None = None
    unit_count: int = 0
    review_status: str = "unreviewed"
    has_contradictions: bool = False
    has_orphans: bool = False
    is_jurisdiction_sensitive: bool = False
    is_procedural: bool = False
    canonical_order: int | None = None
    is_manual: bool = False
    depth: int = 0
    children: list[TaskTreeNode] = Field(default_factory=list)


# Self-reference for recursive children
TaskTreeNode.model_rebuild()


# ---------------------------------------------------------------------------
# Task Review Requests
# ---------------------------------------------------------------------------


class TaskReviewRequest(BaseModel):
    """Request body for reviewing a task."""

    status: str  # "approved" | "rejected" | "edited"
    edited_label: str | None = None
    note: str | None = None


class TaskCreateRequest(BaseModel):
    """Request body for creating a manual task."""

    label: str
    folio_iri: str | None = None
    parent_task_id: str | None = None
    is_procedural: bool = False


class TaskBulkApproveRequest(BaseModel):
    """Request body for bulk-approving tasks."""

    task_ids: list[str] | None = None
    confidence_min: float | None = None


# ---------------------------------------------------------------------------
# Contradiction Models
# ---------------------------------------------------------------------------


class ContradictionResponse(BaseModel):
    """Contradiction detail for API responses."""

    id: int
    task_id: str
    unit_id_a: str
    unit_id_b: str
    nli_score: float | None = None
    contradiction_type: str = "full"
    resolution: str | None = None
    resolved_text: str | None = None
    resolver_note: str = ""


class ContradictionResolveRequest(BaseModel):
    """Request body for resolving a contradiction."""

    resolution: str  # "keep_both" | "prefer_a" | "prefer_b" | "merge" | "jurisdiction"
    resolved_text: str | None = None
    note: str | None = None


# ---------------------------------------------------------------------------
# Hierarchy Edit
# ---------------------------------------------------------------------------


class HierarchyEditRequest(BaseModel):
    """Request body for recording a hierarchy edit."""

    edit_type: str  # "move" | "merge" | "split" | "create" | "delete"
    source_task_id: str | None = None
    target_task_id: str | None = None
    detail: str = ""


# ---------------------------------------------------------------------------
# Source Authority
# ---------------------------------------------------------------------------


class SourceAuthorityRequest(BaseModel):
    """Request body for setting source authority."""

    source_file: str
    authority_level: int = Field(default=5, ge=1, le=10)
    author: str = ""


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


class DiscoveryStats(BaseModel):
    """Discovery statistics for a corpus."""

    total_tasks: int = 0
    total_subtasks: int = 0
    total_units_assigned: int = 0
    orphan_count: int = 0
    contradiction_count: int = 0
    contradictions_resolved: int = 0
    review_progress_pct: float = 0.0
    by_confidence: dict[str, int] = Field(default_factory=dict)
    by_unit_type: dict[str, int] = Field(default_factory=dict)
    source_coverage: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Discovery Diff
# ---------------------------------------------------------------------------


class DiscoveryDiffEntry(BaseModel):
    """A single entry in the discovery diff.

    Produced by TaskDiscoveryOrchestrator._compute_diff() and consumed
    by the DiffView.svelte frontend component.
    """

    type: str  # "added" | "removed" | "changed"
    id: str  # task ID
    description: str  # human-readable change description
