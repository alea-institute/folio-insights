"""File upload endpoint with ZIP extraction and path traversal protection."""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter(prefix="/api/v1", tags=["upload"])

# Supported individual file extensions (matches ingestion stage)
SUPPORTED_EXTENSIONS: set[str] = {
    ".md", ".txt", ".docx", ".pdf", ".html", ".rtf",
    ".eml", ".msg", ".xml", ".csv", ".xlsx", ".tsv", ".wpd",
}

# ZIP archives are also accepted (extracted server-side)
_ARCHIVE_EXTENSIONS: set[str] = {".zip"}

_ALL_ACCEPTED: set[str] = SUPPORTED_EXTENSIONS | _ARCHIVE_EXTENSIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _output_dir() -> Path:
    """Lazy import to avoid circular dependency with api.main."""
    from api.main import _output_dir

    return _output_dir


def _corpus_meta_path(corpus_id: str) -> Path:
    return _output_dir() / corpus_id / "corpus-meta.json"


def _sources_dir(corpus_id: str) -> Path:
    return _output_dir() / corpus_id / "sources"


def _extract_zip_safely(zip_path: Path, target_dir: Path) -> list[dict]:
    """Extract a ZIP archive with path traversal protection.

    Returns list of {"filename": str, "size": int} for each extracted file.
    Raises HTTPException(400) if any entry attempts path traversal.
    """
    extracted: list[dict] = []
    target_resolved = str(target_dir.resolve())

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            # Skip directories and macOS metadata
            if info.is_dir() or info.filename.startswith("__MACOSX"):
                continue

            target = target_dir / info.filename
            resolved = str(target.resolve())

            # Zip Slip protection
            if not resolved.startswith(target_resolved):
                raise HTTPException(
                    status_code=400,
                    detail=f"Zip entry escapes target directory: {info.filename}",
                )

            # Ensure parent directory exists (for nested ZIP entries)
            target.parent.mkdir(parents=True, exist_ok=True)

            # Extract the file
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)

            extracted.append({
                "filename": target.name,
                "size": info.file_size,
            })

    return extracted


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/corpus/{corpus_id}/upload")
async def upload_files(
    corpus_id: str,
    files: list[UploadFile] = File(...),
) -> dict:
    """Upload one or more files to a corpus.

    Accepts individual files in 13 supported formats plus ZIP archives.
    ZIP archives are extracted server-side with path traversal protection.
    """
    # Validate corpus exists
    if not _corpus_meta_path(corpus_id).exists():
        raise HTTPException(status_code=404, detail=f"Corpus '{corpus_id}' not found")

    sources = _sources_dir(corpus_id)
    sources.mkdir(parents=True, exist_ok=True)

    # Validate file extensions upfront
    rejected: list[str] = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in _ALL_ACCEPTED:
            rejected.append(f.filename or "(unnamed)")

    if rejected:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format(s): {', '.join(rejected)}",
        )

    uploaded: list[dict] = []

    for f in files:
        filename = f.filename or "unnamed"
        ext = Path(filename).suffix.lower()

        if ext in _ARCHIVE_EXTENSIONS:
            # Write ZIP to temp file, then extract safely
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                shutil.copyfileobj(f.file, tmp)

            try:
                extracted = _extract_zip_safely(tmp_path, sources)
                uploaded.extend(extracted)
            finally:
                tmp_path.unlink(missing_ok=True)
        else:
            # Write individual file directly to sources
            dest = sources / filename
            with open(dest, "wb") as out:
                shutil.copyfileobj(f.file, out)
            uploaded.append({
                "filename": filename,
                "size": dest.stat().st_size,
            })

    return {"uploaded": uploaded, "count": len(uploaded)}
