"""Source context endpoint: read source file spans from disk."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter()

# Context window: chars before/after the span
_CONTEXT_CHARS = 500


def _output_dir() -> Path:
    """Late import to avoid a circular import with api.main."""
    from api.main import _output_dir

    return _output_dir


def _confine(file: str) -> Path | None:
    """Resolve *file* inside the configured output dir, or return None.

    Relative paths resolve against the output dir; absolute paths must already
    point inside it. Symlinks are resolved first, so a link that escapes the
    output dir is rejected too.
    """
    root = _output_dir().resolve()
    candidate = Path(file)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        return None
    return resolved


@router.get("/source")
async def get_source(
    file: str = Query(..., description="Path to source file"),
    start: int = Query(0, description="Span start offset"),
    end: int = Query(0, description="Span end offset"),
) -> dict:
    """Read source file from disk and return text around the extraction span.

    Returns context window of 500 chars before *start* and 500 chars after
    *end*, with the span text itself in between.  Never persists or caches
    source text -- reads fresh each time. Only files inside the configured
    output dir are readable.
    """
    source_path = _confine(file)
    if source_path is None or not source_path.is_file():
        return {
            "found": False,
            "message": "Source file not available",
            "file_path": file,
            "section_breadcrumb": "",
            "text": "",
        }

    try:
        content = source_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {
            "found": False,
            "message": "Source file not available",
            "file_path": file,
            "section_breadcrumb": "",
            "text": "",
        }

    # Clamp offsets
    start = max(0, min(start, len(content)))
    end = max(start, min(end, len(content)))

    ctx_start = max(0, start - _CONTEXT_CHARS)
    ctx_end = min(len(content), end + _CONTEXT_CHARS)
    context_text = content[ctx_start:ctx_end]

    # Build breadcrumb from headings preceding the span
    breadcrumb = _extract_breadcrumb(content, start)

    return {
        "found": True,
        "file_path": file,
        "section_breadcrumb": breadcrumb,
        "text": context_text,
        "span_start_in_context": start - ctx_start,
        "span_end_in_context": end - ctx_start,
    }


def _extract_breadcrumb(content: str, offset: int) -> str:
    """Extract section breadcrumb from markdown headings preceding *offset*."""
    lines = content[:offset].split("\n")
    headings: list[str] = []
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
            if title:
                headings.insert(0, title)
            if level <= 1:
                break
    return " > ".join(headings) if headings else ""
