"""Multi-format ingestion stage.

Walks a source directory, detects file formats, and delegates to the
appropriate bridge adapter for text extraction + structural elements.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import httpx

from folio_insights.config import get_settings
from folio_insights.models.corpus import CorpusDocument
from folio_insights.pipeline.stages.base import InsightsJob, InsightsPipelineStage
from folio_insights.services.bridge.ingestion_bridge import IngestionBridge
from folio_insights.services.bridge.mapper_bridge import MapperBridge
from folio_insights.services.corpus_registry import CorpusRegistry

logger = logging.getLogger(__name__)

# Extensions handled by folio-enrich's ingestion registry
_BRIDGE_EXTENSIONS: set[str] = {
    ".md", ".txt", ".docx", ".doc", ".pdf",
    ".html", ".htm", ".rtf", ".eml", ".msg",
}

# Extensions handled by folio-mapper's file parser
_TABULAR_EXTENSIONS: set[str] = {".csv", ".xlsx", ".tsv"}

# Extensions with custom handling
_XML_EXTENSIONS: set[str] = {".xml"}
_WPD_EXTENSIONS: set[str] = {".wpd"}

# All supported extensions
SUPPORTED_EXTENSIONS: set[str] = (
    _BRIDGE_EXTENSIONS | _TABULAR_EXTENSIONS | _XML_EXTENSIONS | _WPD_EXTENSIONS
)

# Extension -> format name for corpus document records
_FORMAT_NAMES: dict[str, str] = {
    ".md": "markdown", ".txt": "plain_text", ".docx": "word", ".doc": "word",
    ".pdf": "pdf", ".html": "html", ".htm": "html", ".rtf": "rtf",
    ".eml": "email", ".msg": "email", ".csv": "csv", ".xlsx": "excel",
    ".tsv": "tsv", ".xml": "xml", ".wpd": "wordperfect",
}


def _parse_markdown_elements(raw_content: str) -> list[dict[str, Any]]:
    """Parse raw markdown to extract headings and paragraphs as elements.

    folio-enrich's MarkdownIngestor strips heading markers without
    returning structured elements. This function reads the raw markdown
    to produce elements with heading levels for the structure parser.
    """
    import re

    elements: list[dict[str, Any]] = []
    lines = raw_content.split("\n")
    current_block: list[str] = []
    in_list = False

    def _flush_block() -> None:
        """Flush accumulated paragraph/list lines as elements."""
        if not current_block:
            return
        text = "\n".join(current_block).strip()
        if text:
            elem_type = "list_item" if in_list else "paragraph"
            elements.append({
                "text": text,
                "element_type": elem_type,
                "section_path": [],
                "page": None,
                "level": None,
            })
        current_block.clear()

    for line in lines:
        stripped = line.strip()

        # Heading detection
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            _flush_block()
            in_list = False
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            elements.append({
                "text": heading_text,
                "element_type": "heading",
                "section_path": [],
                "page": None,
                "level": level,
            })
            continue

        # List item detection
        list_match = re.match(r"^[\s]*[-*+]\s+(.+)$", stripped) or re.match(
            r"^[\s]*\d+\.\s+(.+)$", stripped
        )
        if list_match:
            if not in_list:
                _flush_block()
                in_list = True
            elements.append({
                "text": list_match.group(1).strip(),
                "element_type": "list_item",
                "section_path": [],
                "page": None,
                "level": None,
            })
            continue

        # Empty line = paragraph break
        if not stripped:
            _flush_block()
            in_list = False
            continue

        # Regular text
        if in_list:
            _flush_block()
            in_list = False
        current_block.append(stripped)

    _flush_block()
    return elements


def _parse_plaintext_elements(raw_content: str) -> list[dict[str, Any]]:
    """Parse plain text into paragraph elements (split on blank lines)."""
    elements: list[dict[str, Any]] = []
    for para in raw_content.split("\n\n"):
        text = para.strip()
        if text:
            elements.append({
                "text": text,
                "element_type": "paragraph",
                "section_path": [],
                "page": None,
                "level": None,
            })
    return elements


def _compute_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of file contents."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def _ingest_xml(file_path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Ingest an XML file using lxml, preserving element hierarchy."""
    from lxml import etree

    tree = etree.parse(str(file_path))
    root = tree.getroot()

    elements: list[dict[str, Any]] = []
    texts: list[str] = []

    def _walk(node, path: list[str], depth: int = 0) -> None:
        tag = etree.QName(node.tag).localname if isinstance(node.tag, str) else str(node.tag)
        current_path = path + [tag]

        # Extract text from this node
        if node.text and node.text.strip():
            text = node.text.strip()
            texts.append(text)
            elements.append({
                "text": text,
                "element_type": "paragraph",
                "section_path": list(current_path),
                "page": None,
                "level": depth,
            })

        for child in node:
            _walk(child, current_path, depth + 1)

            # Tail text (text after a child element)
            if child.tail and child.tail.strip():
                tail_text = child.tail.strip()
                texts.append(tail_text)
                elements.append({
                    "text": tail_text,
                    "element_type": "paragraph",
                    "section_path": list(current_path),
                    "page": None,
                    "level": depth,
                })

    _walk(root, [])
    full_text = "\n\n".join(texts)
    return full_text, elements


async def _ingest_wpd(file_path: Path, doctor_url: str) -> tuple[str, list[dict[str, Any]]]:
    """Ingest a WordPerfect file via the Doctor microservice.

    Converts WPD to HTML, then parses the HTML via the ingestion bridge.
    """
    url = f"{doctor_url.rstrip('/')}/api/v1/convert/wpd/to/html/"
    async with httpx.AsyncClient(timeout=60.0) as client:
        with open(file_path, "rb") as f:
            resp = await client.post(url, files={"file": (file_path.name, f)})
        resp.raise_for_status()

    html_content = resp.text

    # Write temp HTML and ingest via bridge
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False) as tmp:
        tmp.write(html_content)
        tmp_path = Path(tmp.name)

    try:
        bridge = IngestionBridge()
        return bridge.detect_and_ingest(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


class IngestionStage(InsightsPipelineStage):
    """Walk source directory and ingest all supported file formats."""

    @property
    def name(self) -> str:
        return "ingestion"

    async def execute(self, job: InsightsJob) -> InsightsJob:
        """Ingest files from job.source_dir.

        For each supported file:
        1. Check corpus_registry -- skip if already processed
        2. Route to the appropriate ingestor
        3. Create CorpusDocument and store ingested data in job.metadata
        """
        settings = get_settings()
        source_dir = Path(job.source_dir)

        if not source_dir.exists():
            raise FileNotFoundError(f"Source directory not found: {source_dir}")

        # Load existing registry from corpus output dir so re-runs skip already-processed files
        corpus_dir = settings.output_dir / job.corpus_name
        registry = CorpusRegistry.load(corpus_dir, job.corpus_name)

        # Collect all supported files
        all_files = sorted(
            f for f in source_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        )

        # Filter to files that need processing
        new_files = [f for f in all_files if registry.needs_processing(f)]

        if not new_files:
            logger.info("No new files to process in %s", source_dir)
            job.metadata.setdefault("ingested", {})
            return job

        logger.info(
            "Ingesting %d new files (%d total found) from %s",
            len(new_files), len(all_files), source_dir,
        )

        ingestion_bridge = IngestionBridge()
        mapper_bridge = MapperBridge()
        ingested: dict[str, dict[str, Any]] = job.metadata.get("ingested", {})

        for file_path in new_files:
            ext = file_path.suffix.lower()
            format_name = _FORMAT_NAMES.get(ext, "unknown")

            try:
                if ext in _BRIDGE_EXTENSIONS:
                    text, elements = ingestion_bridge.detect_and_ingest(file_path)

                    # Supplement with local element parsing if bridge
                    # returned no structural elements (e.g. markdown ingestor)
                    if not elements:
                        raw_content = file_path.read_text(encoding="utf-8", errors="replace")
                        if ext == ".md":
                            elements = _parse_markdown_elements(raw_content)
                        else:
                            elements = _parse_plaintext_elements(raw_content)

                elif ext in _TABULAR_EXTENSIONS:
                    items = mapper_bridge.parse_tabular(file_path)
                    text = "\n".join(item.get("text", "") for item in items)
                    elements = [
                        {
                            "text": item.get("text", ""),
                            "element_type": "paragraph",
                            "section_path": [],
                            "page": None,
                            "level": None,
                        }
                        for item in items
                    ]

                elif ext in _XML_EXTENSIONS:
                    text, elements = _ingest_xml(file_path)

                elif ext in _WPD_EXTENSIONS:
                    if settings.doctor_url:
                        text, elements = await _ingest_wpd(
                            file_path, settings.doctor_url
                        )
                    else:
                        logger.warning(
                            "Skipping WPD file %s: DOCTOR_URL not configured",
                            file_path,
                        )
                        continue
                else:
                    logger.warning("Skipping unsupported file: %s", file_path)
                    continue

                # Store ingested data
                file_key = str(file_path.resolve())
                ingested[file_key] = {
                    "text": text,
                    "elements": elements,
                }

                # Create CorpusDocument and mark processed
                content_hash = _compute_hash(file_path)
                doc = CorpusDocument(
                    file_path=file_key,
                    content_hash=content_hash,
                    format=format_name,
                    unit_count=0,
                )
                job.documents.append(doc)
                registry.mark_processed(file_path, format_name)

                logger.info("Ingested: %s (%s, %d chars)", file_path.name, format_name, len(text))

            except Exception:
                logger.exception("Failed to ingest %s, skipping", file_path)

        job.metadata["ingested"] = ingested
        job.metadata.setdefault("lineage", [])
        job.metadata["lineage"].append({
            "stage": "ingestion",
            "action": "ingest_directory",
            "detail": f"{len(new_files)} files ingested from {source_dir}",
        })

        return job
