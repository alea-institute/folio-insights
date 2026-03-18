"""Pydantic models for corpus management and processing jobs."""

from __future__ import annotations

import enum
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProcessingStatus(str, enum.Enum):
    """Status of a corpus processing job."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ActivityEntry(BaseModel):
    """A single timestamped activity log entry."""

    timestamp: str
    stage: str
    message: str


class CorpusInfo(BaseModel):
    """Public representation of a corpus."""

    id: str
    name: str
    file_count: int = 0
    processing_status: str = "not_processed"
    last_processed: str | None = None
    created_at: str


class ProcessingJob(BaseModel):
    """Tracks a long-running pipeline processing job."""

    id: UUID = Field(default_factory=uuid4)
    corpus_id: str
    status: ProcessingStatus = ProcessingStatus.PENDING
    current_stage: str | None = None
    progress_pct: int = 0
    total_units: int = 0
    activity_log: list[ActivityEntry] = Field(default_factory=list)
    error: str | None = None
    created_at: str
    updated_at: str


class CorpusCreateRequest(BaseModel):
    """Request body for creating a new corpus."""

    name: str = Field(..., min_length=1, max_length=100)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def slugify(name: str) -> str:
    """Convert a human-readable name to a URL-safe slug.

    Lowercases, replaces non-alphanumeric runs with hyphens,
    strips leading/trailing hyphens, and collapses multiples.
    """
    result = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return re.sub(r"-+", "-", result)
