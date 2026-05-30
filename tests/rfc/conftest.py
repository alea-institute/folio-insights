"""Shared fixtures for the RFC linter test suite (Phase 7, D-22)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

# Apply the `rfc` marker to every test in this package (D-22 grouping).
pytestmark = pytest.mark.rfc


_VALID_FRONTMATTER_TEMPLATE = """\
---
rfc: {rfc}
title: {title}
status: {status}
authors:
{authors_block}
created: {created}
---
{body}
"""


def _authors_block(authors: list[str]) -> str:
    return "\n".join(f"  - {did}" for did in authors)


@pytest.fixture
def rfcs_dir_factory(tmp_path: Path) -> Callable[..., Path]:
    """Create an isolated `.planning/rfcs/`-shaped tmp dir for the linter under test.

    Returns a factory ``make(*, include_template: bool = True) -> Path`` that
    creates ``tmp_path / "rfcs"`` and (by default) drops a minimal valid
    RFC-TEMPLATE.md into it so callers can verify the template-skip behavior.
    """
    def _make(*, include_template: bool = True) -> Path:
        rfcs_dir = tmp_path / "rfcs"
        rfcs_dir.mkdir(parents=True, exist_ok=True)
        if include_template:
            (rfcs_dir / "RFC-TEMPLATE.md").write_text(
                _VALID_FRONTMATTER_TEMPLATE.format(
                    rfc=0,
                    title="Template — Replace With Your RFC Title",
                    status="draft",
                    authors_block=_authors_block(["did:key:z6MkTemplate"]),
                    created="2026-05-30",
                    body="Template body — not lint-checked.",
                ),
                encoding="utf-8",
            )
        return rfcs_dir

    return _make


@pytest.fixture
def make_rfc_file() -> Callable[..., Path]:
    """Write a valid NNNN-<slug>.md file with the given frontmatter.

    Signature::

        make_rfc_file(
            rfcs_dir: Path,
            number: int,
            title_slug: str,
            status: str = "draft",
            authors: list[str] | None = None,
            created: str = "2026-05-30",
            title: str | None = None,
            body: str = "",
            extra_frontmatter_lines: list[str] | None = None,
        ) -> Path
    """
    def _write(
        rfcs_dir: Path,
        number: int,
        title_slug: str,
        status: str = "draft",
        authors: list[str] | None = None,
        created: str = "2026-05-30",
        title: str | None = None,
        body: str = "",
        extra_frontmatter_lines: list[str] | None = None,
    ) -> Path:
        authors = authors or ["did:key:z6MkTestAuthor"]
        title = title or title_slug.replace("-", " ").title()
        extra_lines = "\n".join(extra_frontmatter_lines or [])
        # Build the frontmatter directly so callers can inject extra keys
        # (e.g. status_change_reason) without breaking the parser.
        lines = [
            "---",
            f"rfc: {number}",
            f"title: {title}",
            f"status: {status}",
            "authors:",
            *(f"  - {did}" for did in authors),
            f"created: {created}",
        ]
        if extra_lines:
            lines.append(extra_lines)
        lines.append("---")
        lines.append(body)
        content = "\n".join(lines) + "\n"
        fname = f"{number:04d}-{title_slug}.md"
        path = rfcs_dir / fname
        path.write_text(content, encoding="utf-8")
        return path

    return _write
