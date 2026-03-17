"""Structure parser stage: extract heading hierarchy from ingested elements.

Builds a tree of headings (h1 > h2 > h3 > ...) and attaches the current
section_path to each paragraph/list-item element so downstream stages
know the document context.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from folio_insights.pipeline.stages.base import InsightsJob, InsightsPipelineStage

logger = logging.getLogger(__name__)


class StructuredElement(BaseModel):
    """A document element with resolved heading hierarchy context."""

    text: str
    element_type: str  # "heading", "paragraph", "list_item"
    section_path: list[str] = Field(default_factory=list)
    level: int = 0
    char_offset_start: int = 0
    char_offset_end: int = 0


def _build_structured_elements(
    elements: list[dict[str, Any]],
) -> list[StructuredElement]:
    """Parse elements and resolve heading hierarchy.

    Maintains a stack of headings by level. When a new heading is
    encountered at level N, all headings at level >= N are popped
    and the new heading is pushed.
    """
    structured: list[StructuredElement] = []

    # Stack of (level, heading_text) tracking current position
    heading_stack: list[tuple[int, str]] = []
    char_offset = 0

    for elem in elements:
        text = elem.get("text", "").strip()
        if not text:
            continue

        element_type = elem.get("element_type", "paragraph")
        level = elem.get("level") or 0

        text_len = len(text)
        start = char_offset
        end = char_offset + text_len

        if element_type == "heading":
            # Determine heading level (h1=1, h2=2, etc.)
            h_level = level if level and level > 0 else 1

            # Pop headings at same or deeper level
            while heading_stack and heading_stack[-1][0] >= h_level:
                heading_stack.pop()

            heading_stack.append((h_level, text))

            section_path = [h[1] for h in heading_stack]

            structured.append(StructuredElement(
                text=text,
                element_type="heading",
                section_path=section_path,
                level=h_level,
                char_offset_start=start,
                char_offset_end=end,
            ))
        else:
            # Non-heading element inherits current heading context
            section_path = [h[1] for h in heading_stack]

            # Normalize element_type
            if element_type not in ("heading", "paragraph", "list_item"):
                element_type = "paragraph"

            structured.append(StructuredElement(
                text=text,
                element_type=element_type,
                section_path=section_path,
                level=0,
                char_offset_start=start,
                char_offset_end=end,
            ))

        char_offset = end + 1  # +1 for implied separator

    return structured


class StructureParserStage(InsightsPipelineStage):
    """Resolve heading hierarchy from ingested document elements."""

    @property
    def name(self) -> str:
        return "structure_parser"

    async def execute(self, job: InsightsJob) -> InsightsJob:
        """For each ingested document, build structured elements with section_path.

        Reads from ``job.metadata["ingested"]`` and writes to
        ``job.metadata["structured"]``.
        """
        ingested = job.metadata.get("ingested", {})
        if not ingested:
            logger.warning("No ingested data found; skipping structure parsing")
            return job

        structured_output: dict[str, list[dict]] = {}
        total_elements = 0

        for file_key, data in ingested.items():
            elements = data.get("elements", [])
            if not elements:
                # If no structured elements, create a single paragraph
                # from the raw text
                text = data.get("text", "")
                if text:
                    structured_output[file_key] = [
                        StructuredElement(
                            text=text,
                            element_type="paragraph",
                            section_path=[],
                            level=0,
                            char_offset_start=0,
                            char_offset_end=len(text),
                        ).model_dump()
                    ]
                    total_elements += 1
                continue

            parsed = _build_structured_elements(elements)
            structured_output[file_key] = [e.model_dump() for e in parsed]
            total_elements += len(parsed)

        job.metadata["structured"] = structured_output
        job.metadata.setdefault("lineage", [])
        job.metadata["lineage"].append({
            "stage": "structure_parser",
            "action": "parse_structure",
            "detail": f"{total_elements} structured elements across {len(structured_output)} files",
        })

        logger.info(
            "Parsed structure: %d elements across %d files",
            total_elements, len(structured_output),
        )
        return job
