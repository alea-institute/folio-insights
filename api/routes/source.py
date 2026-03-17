"""Source context endpoint: read source file spans from disk."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter()

# Context window: chars before/after the span
_CONTEXT_CHARS = 500


@router.get("/source")
async def get_source(
    file: str = Query(..., description="Path to source file"),
    start: int = Query(0, description="Span start offset"),
    end: int = Query(0, description="Span end offset"),
) -> dict:
    """Read source file from disk and return text around the extraction span.

    Returns context window of 500 chars before *start* and 500 chars after
    *end*, with the span text itself in between.  Never persists or caches
    source text -- reads fresh each time.
    """
    source_path = Path(file)
    if not source_path.exists():
        return {
            "found": False,
            "message": "Source file not available",
            "file_path": str(source_path),
            "section_breadcrumb": "",
            "text": "",
        }

    try:
        content = source_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {
            "found": False,
            "message": "Source file not available",
            "file_path": str(source_path),
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
        "file_path": str(source_path),
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
