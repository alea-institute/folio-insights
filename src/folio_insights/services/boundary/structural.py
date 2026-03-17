"""Tier 1: Structural heuristic boundary detection (FREE, handles ~70-80%).

Detects knowledge unit boundaries using document structure cues:
heading changes, bullet/numbered list items, paragraph breaks,
and transition words.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from folio_insights.pipeline.stages.structure_parser import StructuredElement


class Boundary(BaseModel):
    """A detected knowledge unit boundary in a document."""

    start: int
    end: int
    source_file: str
    text: str
    section_path: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    method: str = "structural"


# Transition words that signal a new idea at the start of a paragraph
_TRANSITION_PATTERNS = re.compile(
    r"^\s*(?:"
    r"However,|In contrast,|Alternatively,|Note that|Warning:|Tip:|"
    r"Important:|Caution:|But |On the other hand,|Conversely,|"
    r"Instead,|Nevertheless,|Nonetheless,|Rather,|"
    r"Be aware|Keep in mind|Remember that|Practice tip:"
    r")",
    re.IGNORECASE,
)


def detect_structural_boundaries(
    elements: list[StructuredElement],
    source_file: str = "",
) -> list[Boundary]:
    """Detect knowledge unit boundaries using structural heuristics.

    Rules (Tier 1):
      - Heading change = definite boundary (confidence 1.0)
      - Each bullet/numbered list item = separate boundary (confidence 0.9)
      - Double newline (paragraph break) = candidate boundary (confidence 0.7)
      - Transition words at paragraph start = candidate boundary (confidence 0.8)

    Each boundary carries its section_path from the StructuredElement.
    """
    boundaries: list[Boundary] = []

    for elem in elements:
        text = elem.text.strip()
        if not text:
            continue

        if elem.element_type == "heading":
            # Headings are boundaries themselves (they define structure)
            boundaries.append(
                Boundary(
                    start=elem.char_offset_start,
                    end=elem.char_offset_end,
                    source_file=source_file,
                    text=text,
                    section_path=list(elem.section_path),
                    confidence=1.0,
                    method="structural_heading",
                )
            )
            continue

        if elem.element_type == "list_item":
            # Each list item is a separate boundary
            boundaries.append(
                Boundary(
                    start=elem.char_offset_start,
                    end=elem.char_offset_end,
                    source_file=source_file,
                    text=text,
                    section_path=list(elem.section_path),
                    confidence=0.9,
                    method="structural_list_item",
                )
            )
            continue

        # Paragraphs: check for sub-paragraph splits
        sub_boundaries = _split_paragraph(
            text,
            elem.char_offset_start,
            source_file=source_file,
            section_path=list(elem.section_path),
        )

        if sub_boundaries:
            boundaries.extend(sub_boundaries)
        else:
            # Whole paragraph is one boundary
            confidence = 0.7  # default paragraph confidence
            if _TRANSITION_PATTERNS.match(text):
                confidence = 0.8

            boundaries.append(
                Boundary(
                    start=elem.char_offset_start,
                    end=elem.char_offset_end,
                    source_file=source_file,
                    text=text,
                    section_path=list(elem.section_path),
                    confidence=confidence,
                    method="structural_paragraph",
                )
            )

    return boundaries


def _split_paragraph(
    text: str,
    base_offset: int,
    source_file: str = "",
    section_path: list[str] | None = None,
) -> list[Boundary]:
    """Split a paragraph into sub-boundaries if double-newlines or transitions found.

    Returns an empty list if no sub-splits detected (paragraph stays whole).
    """
    if section_path is None:
        section_path = []

    # Check for double-newline paragraph breaks within the text
    parts = re.split(r"\n\s*\n", text)
    if len(parts) <= 1:
        return []

    boundaries: list[Boundary] = []
    offset = 0
    for part in parts:
        part_stripped = part.strip()
        if not part_stripped:
            continue

        # Find the actual position of this part in the original text
        part_start = text.find(part_stripped, offset)
        if part_start == -1:
            part_start = offset
        part_end = part_start + len(part_stripped)

        confidence = 0.7
        method = "structural_paragraph_break"
        if _TRANSITION_PATTERNS.match(part_stripped):
            confidence = 0.8
            method = "structural_transition"

        boundaries.append(
            Boundary(
                start=base_offset + part_start,
                end=base_offset + part_end,
                source_file=source_file,
                text=part_stripped,
                section_path=section_path,
                confidence=confidence,
                method=method,
            )
        )
        offset = part_end

    return boundaries if len(boundaries) > 1 else []
