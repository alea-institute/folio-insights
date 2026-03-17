"""Bridge adapter for folio-enrich's ingestion registry.

Wraps format detection and multi-format ingestion to extract text +
structural elements from source files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from folio_insights.services.bridge.folio_bridge import _ensure_folio_enrich_path

logger = logging.getLogger(__name__)

# Extension -> folio-enrich DocumentFormat value
_EXT_MAP: dict[str, str] = {
    ".txt": "plain_text",
    ".md": "markdown",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
    ".docx": "word",
    ".doc": "word",
    ".rtf": "rtf",
    ".eml": "email",
    ".msg": "email",
}


class IngestionBridge:
    """Wraps folio-enrich's ingestion registry for multi-format file ingestion."""

    def __init__(self) -> None:
        _ensure_folio_enrich_path()

    def detect_and_ingest(
        self, file_path: Path
    ) -> tuple[str, list[dict[str, Any]]]:
        """Detect format from extension and ingest a file.

        Returns a tuple of (extracted_text, list_of_element_dicts).
        Each element dict has keys: text, element_type, section_path, page, level.

        Raises FileNotFoundError if the file does not exist.
        Raises ValueError for unsupported formats.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Source file not found: {file_path}")

        ext = file_path.suffix.lower()
        fmt_value = _EXT_MAP.get(ext)
        if fmt_value is None:
            raise ValueError(f"Unsupported format for ingestion bridge: {ext}")

        try:
            from app.models.document import DocumentFormat, DocumentInput
            from app.services.ingestion.registry import ingest_with_elements

            doc_format = DocumentFormat(fmt_value)

            # Read file content
            if doc_format in (DocumentFormat.PDF, DocumentFormat.WORD):
                import base64
                raw_bytes = file_path.read_bytes()
                content = base64.b64encode(raw_bytes).decode("ascii")
            else:
                content = file_path.read_text(encoding="utf-8", errors="replace")

            doc_input = DocumentInput(
                content=content,
                format=doc_format,
                filename=file_path.name,
            )

            text, elements = ingest_with_elements(doc_input)

            # Convert TextElement pydantic models to plain dicts
            element_dicts = []
            for elem in elements:
                element_dicts.append({
                    "text": elem.text,
                    "element_type": elem.element_type,
                    "section_path": list(elem.section_path),
                    "page": elem.page,
                    "level": elem.level,
                })

            return text, element_dicts

        except Exception:
            logger.exception("Failed to ingest file: %s", file_path)
            raise
