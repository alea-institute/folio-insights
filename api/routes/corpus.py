"""Corpus CRUD endpoints: create, list, get, delete, list files."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.models.processing import CorpusCreateRequest, CorpusInfo, slugify

router = APIRouter(prefix="/api/v1", tags=["corpus"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _output_dir() -> Path:
    """Lazy import to avoid circular dependency with api.main."""
    from api.main import _output_dir

    return _output_dir


def _corpus_dir(corpus_id: str) -> Path:
    return _output_dir() / corpus_id


def _corpus_meta_path(corpus_id: str) -> Path:
    return _corpus_dir(corpus_id) / "corpus-meta.json"


def _sources_dir(corpus_id: str) -> Path:
    return _corpus_dir(corpus_id) / "sources"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_corpus_info(corpus_id: str) -> CorpusInfo:
    """Read corpus metadata from disk and return a CorpusInfo model."""
    meta_path = _corpus_meta_path(corpus_id)
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail=f"Corpus '{corpus_id}' not found")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    sources = _sources_dir(corpus_id)
    file_count = len([f for f in sources.iterdir() if f.is_file()]) if sources.exists() else 0

    # Determine processing status from job file
    processing_status = "not_processed"
    last_processed = None
    job_path = _output_dir() / ".jobs" / f"{corpus_id}.json"
    if job_path.exists():
        try:
            job_data = json.loads(job_path.read_text(encoding="utf-8"))
            job_status = job_data.get("status", "")
            if job_status == "completed":
                processing_status = "completed"
                last_processed = job_data.get("updated_at")
            elif job_status == "processing":
                processing_status = "processing"
            elif job_status == "failed":
                processing_status = "failed"
            elif job_status == "pending":
                processing_status = "pending"
        except (json.JSONDecodeError, KeyError):
            pass
    elif (_corpus_dir(corpus_id) / "extraction.json").exists():
        # Fallback: extraction.json exists but no job file
        processing_status = "completed"

    return CorpusInfo(
        id=meta["id"],
        name=meta["name"],
        file_count=file_count,
        processing_status=processing_status,
        last_processed=last_processed,
        created_at=meta["created_at"],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/corpora", status_code=201)
async def create_corpus(body: CorpusCreateRequest) -> CorpusInfo:
    """Create a new named corpus."""
    corpus_id = slugify(body.name)
    cdir = _corpus_dir(corpus_id)

    if cdir.exists():
        raise HTTPException(status_code=409, detail=f"Corpus '{corpus_id}' already exists")

    # Create directory structure
    cdir.mkdir(parents=True, exist_ok=True)
    _sources_dir(corpus_id).mkdir(parents=True, exist_ok=True)

    # Write metadata
    now = _now_iso()
    meta = {"id": corpus_id, "name": body.name, "created_at": now}
    _corpus_meta_path(corpus_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return CorpusInfo(id=corpus_id, name=body.name, file_count=0, created_at=now)


@router.get("/corpora")
async def list_corpora() -> list[CorpusInfo]:
    """List all corpora found in the output directory."""
    output = _output_dir()
    if not output.exists():
        return []

    corpora: list[CorpusInfo] = []
    for entry in sorted(output.iterdir()):
        if entry.is_dir() and (entry / "corpus-meta.json").exists():
            try:
                corpora.append(_read_corpus_info(entry.name))
            except HTTPException:
                continue
    return corpora


@router.get("/corpora/{corpus_id}")
async def get_corpus(corpus_id: str) -> CorpusInfo:
    """Get details for a single corpus."""
    return _read_corpus_info(corpus_id)


@router.delete("/corpora/{corpus_id}", status_code=204)
async def delete_corpus(corpus_id: str) -> None:
    """Delete a corpus and all its files."""
    cdir = _corpus_dir(corpus_id)
    if not cdir.exists():
        raise HTTPException(status_code=404, detail=f"Corpus '{corpus_id}' not found")

    shutil.rmtree(cdir)


@router.get("/corpora/{corpus_id}/files")
async def list_corpus_files(corpus_id: str) -> list[dict]:
    """List files in a corpus source directory."""
    meta_path = _corpus_meta_path(corpus_id)
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail=f"Corpus '{corpus_id}' not found")

    sources = _sources_dir(corpus_id)
    if not sources.exists():
        return []

    files = []
    for f in sorted(sources.iterdir()):
        if f.is_file():
            files.append({
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "format": f.suffix.lstrip(".") or "unknown",
            })
    return files
