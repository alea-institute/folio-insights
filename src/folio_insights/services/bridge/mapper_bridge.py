"""Bridge adapter for folio-mapper's FileParser for Excel/CSV/TSV ingestion.

Uses importlib to load folio-mapper modules directly from disk, avoiding
namespace conflicts with folio-enrich's ``app`` package.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_mapper_path: str | None = None
_mapper_checked = False


def _get_mapper_path() -> str | None:
    """Resolve and cache the folio-mapper backend path."""
    global _mapper_path, _mapper_checked
    if _mapper_checked:
        return _mapper_path

    from folio_insights.config import get_settings

    settings = get_settings()
    resolved = str(settings.folio_mapper_path.expanduser().resolve())

    if not os.path.isdir(resolved):
        logger.warning(
            "folio-mapper backend not found at %s. "
            "Tabular file parsing will use fallback.",
            resolved,
        )
        _mapper_path = None
    else:
        _mapper_path = resolved
        logger.info("folio-mapper path resolved: %s", resolved)

    _mapper_checked = True
    return _mapper_path


def _load_mapper_file_parser():
    """Load folio-mapper's file_parser module directly via importlib.

    This avoids adding folio-mapper to sys.path, which would conflict
    with folio-enrich's ``app`` package.
    """
    mapper_root = _get_mapper_path()
    if mapper_root is None:
        return None

    file_parser_path = Path(mapper_root) / "app" / "services" / "file_parser.py"
    if not file_parser_path.exists():
        logger.warning("folio-mapper file_parser.py not found at %s", file_parser_path)
        return None

    try:
        spec = importlib.util.spec_from_file_location(
            "folio_mapper_file_parser", str(file_parser_path)
        )
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        logger.exception("Failed to load folio-mapper file_parser")
        return None


class MapperBridge:
    """Wraps folio-mapper's FileParser for Excel/CSV/TSV ingestion."""

    def __init__(self) -> None:
        self._mapper_available = _get_mapper_path() is not None

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
        """Parse using folio-mapper's file_parser loaded via importlib."""
        try:
            mod = _load_mapper_file_parser()
            if mod is None:
                return self._parse_fallback(file_path)

            content = file_path.read_bytes()
            result = mod.parse_file(content, file_path.name)
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
