"""RFC frontmatter Pydantic model + stdlib-only YAML-subset parser (D-22).

We deliberately do NOT depend on PyYAML, python-frontmatter, or any other
YAML/Jekyll-style frontmatter library: the parser handles the exact 6-field
shape an RFC needs and nothing more (no anchors, no folded scalars, no
multi-line strings, no comments). See
`.planning/phases/07-governance-model-3-1/07-RESEARCH.md` §"Don't Hand-Roll"
for the dep-rejection rationale.

The body-only-edit-refusal check in `lint.py` reads the *raw* dict via
`_parse_frontmatter_raw` BEFORE Pydantic validation, so it can look for the
optional `status_change_reason:` field — `RFCFrontmatter`'s
`extra="forbid"` would otherwise reject it.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


class RFCFrontmatter(BaseModel):
    """Locked frontmatter schema for an RFC under `.planning/rfcs/`.

    Field choices follow D-22:
      * ``rfc`` — int ≥ 1 (the template uses ``rfc: 0`` as a tombstone; the
        linter skips it by filename, not by parse).
      * ``status`` — closed Literal of 5 values; the ALLOWED_TRANSITIONS DAG
        lives in `lint.py`.
      * ``created`` — ISO date *string*, NOT a ``date`` type. Keeping it a
        string avoids dragging in a date parser and lets the cheap stdlib
        line-splitter stay ≤30 LOC.
      * ``superseded_by`` — optional pointer to the RFC number that
        replaced this one (linked-list across phases).
    """
    model_config = ConfigDict(extra="forbid")

    rfc: int = Field(ge=1)
    title: str
    status: Literal["draft", "discussion", "accepted", "rejected", "implemented"]
    authors: list[str]  # list of DID strings (did:key / did:web / did:plc)
    created: str        # ISO date string (no `date` type — keeps parser simple)
    superseded_by: int | None = None


def _parse_frontmatter_raw(text: str) -> dict[str, Any]:
    """Return the raw key/value/list dict from the leading `---`-fenced block.

    Unknown keys are preserved (callers — specifically the body-only-edit
    check in `lint.py` — need to see `status_change_reason:` even though
    it's not on the Pydantic model). Use ``parse_frontmatter`` instead if
    you want schema validation.

    Raises ``ValueError`` if no frontmatter block is found.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("missing frontmatter block (no leading '---' fence)")
    body = match.group(1)

    data: dict[str, Any] = {}
    current_list_key: str | None = None
    for line in body.splitlines():
        # List-continuation line (`  - did:key:z...`)
        stripped = line.lstrip()
        if stripped.startswith("- ") and current_list_key is not None:
            data[current_list_key].append(stripped[2:].strip())
            continue
        # Once we hit a non-list line, the list ends.
        current_list_key = None
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not value:
            # Empty value → next lines may be a list
            data[key] = []
            current_list_key = key
        elif value.lstrip("-").isdigit():
            # Negative numbers and plain integers
            try:
                data[key] = int(value)
            except ValueError:
                data[key] = value
        else:
            data[key] = value
    return data


def parse_frontmatter(text: str) -> RFCFrontmatter:
    """Parse + Pydantic-validate the leading frontmatter block.

    Raises ``ValueError`` for missing frontmatter; ``pydantic.ValidationError``
    for schema violations.
    """
    return RFCFrontmatter.model_validate(_parse_frontmatter_raw(text))
