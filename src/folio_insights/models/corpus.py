"""Corpus tracking models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CorpusDocument(BaseModel):
    """Tracks a single source document within a corpus."""

    file_path: str
    content_hash: str
    format: str
    processed_at: str | None = None
    unit_count: int = 0


class CorpusManifest(BaseModel):
    """Top-level manifest for a named corpus."""

    name: str
    documents: list[CorpusDocument] = Field(default_factory=list)
    created_at: str
    updated_at: str
