"""Bridge adapter for folio-mapper's FileParser for Excel/CSV/TSV ingestion."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_mapper_path_ensured = False


def _ensure_mapper_path() -> str | None:
    """Add folio-mapper's backend directory to sys.path if configured.

    Returns the resolved path or None if not configured/found.
    """
    global _mapper_path_ensured
    if _mapper_path_ensured:
        return _get_mapper_path()

    mapper_path = _get_mapper_path()
    if mapper_path is None:
        return None

    if mapper_path not in sys.path:
        sys.path.insert(0, mapper_path)

    _mapper_path_ensured = True
    logger.info("folio-mapper path ensured: %s", mapper_path)
    return mapper_path


def _get_mapper_path() -> str | None:
    """Resolve folio-mapper backend path from settings."""
    from folio_insights.config import get_settings

    settings = get_settings()
    mapper_path = str(settings.folio_mapper_path.expanduser().resolve())

    if not os.path.isdir(mapper_path):
        logger.warning(
            "folio-mapper backend not found at %s. "
            "Tabular file parsing will use fallback.",
            mapper_path,
        )
        return None
    return mapper_path


class MapperBridge:
    """Wraps folio-mapper's FileParser for Excel/CSV/TSV ingestion."""

    def __init__(self) -> None:
        self._mapper_available = _ensure_mapper_path() is not None

    def parse_tabular(self, file_path: Path) -> list[dict[str, Any]]:
        """Parse a tabular file (CSV, XLSX, TSV) and return rows as dicts.

        Falls back to basic CSV parsing if folio-mapper is not available.

        Args:
            file_path: Path to the tabular file.

        Returns:
            List of dicts, each representing a parsed item with ``text`` key.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Tabular file not found: {file_path}")

        if self._mapper_available:
            return self._parse_via_mapper(file_path)
        return self._parse_fallback(file_path)

    def _parse_via_mapper(self, file_path: Path) -> list[dict[str, Any]]:
        """Parse using folio-mapper's file_parser."""
        try:
            from app.services.file_parser import parse_file

            content = file_path.read_bytes()
            result = parse_file(content, file_path.name)
            return [
                {"text": item.text, "index": item.index}
                for item in result.items
            ]
        except Exception:
            logger.exception("folio-mapper parse failed for %s, using fallback", file_path)
            return self._parse_fallback(file_path)

    def _parse_fallback(self, file_path: Path) -> list[dict[str, Any]]:
        """Basic CSV/TSV fallback when folio-mapper is not available."""
        import csv

        ext = file_path.suffix.lower()
        delimiter = "\t" if ext == ".tsv" else ","

        items: list[dict[str, Any]] = []
        try:
            with open(file_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f, delimiter=delimiter)
                for i, row in enumerate(reader):
                    text = " | ".join(cell.strip() for cell in row if cell.strip())
                    if text:
                        items.append({"text": text, "index": i})
        except Exception:
            logger.exception("Fallback tabular parse failed for %s", file_path)

        return items
