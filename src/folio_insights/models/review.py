"""Review workflow models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ReviewStatus(str, Enum):
    """Status of a reviewed knowledge unit."""

    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class ReviewDecision(BaseModel):
    """A reviewer's decision on a knowledge unit."""

    unit_id: str
    status: ReviewStatus
    edited_text: str | None = None
    reviewer_note: str = ""
    reviewed_at: str
