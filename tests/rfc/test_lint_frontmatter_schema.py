"""RFC frontmatter schema tests — Pydantic positive + negative polarity (D-22)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from folio_insights.rfc.frontmatter import (
    RFCFrontmatter,
    _parse_frontmatter_raw,
    parse_frontmatter,
)

pytestmark = pytest.mark.rfc


# ─────────────────────── positive ───────────────────────
def test_full_valid_frontmatter_parses() -> None:
    text = (
        "---\n"
        "rfc: 1\n"
        "title: Add SHACL shape for X\n"
        "status: draft\n"
        "authors:\n"
        "  - did:key:z6MkAlice\n"
        "  - did:key:z6MkBob\n"
        "created: 2026-05-30\n"
        "---\n"
        "Body content here.\n"
    )
    fm = parse_frontmatter(text)
    assert isinstance(fm, RFCFrontmatter)
    assert fm.rfc == 1
    assert fm.title == "Add SHACL shape for X"
    assert fm.status == "draft"
    assert fm.authors == ["did:key:z6MkAlice", "did:key:z6MkBob"]
    assert fm.created == "2026-05-30"
    assert fm.superseded_by is None


@pytest.mark.parametrize(
    "status",
    ["draft", "discussion", "accepted", "rejected", "implemented"],
)
def test_each_allowed_status_accepted(status: str) -> None:
    fm = RFCFrontmatter(
        rfc=1, title="T", status=status,  # type: ignore[arg-type]
        authors=["did:key:z6Mk"], created="2026-05-30",
    )
    assert fm.status == status


def test_optional_superseded_by_int_accepted() -> None:
    fm = RFCFrontmatter(
        rfc=2, title="T", status="implemented",
        authors=["did:key:z6Mk"], created="2026-05-30",
        superseded_by=1,
    )
    assert fm.superseded_by == 1


# ─────────────────────── negative ───────────────────────
def test_missing_required_field_raises() -> None:
    with pytest.raises(ValidationError):
        RFCFrontmatter(  # type: ignore[call-arg]
            rfc=1, title="T", status="draft",
            authors=["did:key:z6Mk"],
            # created intentionally omitted
        )


def test_extra_forbid_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        RFCFrontmatter.model_validate({
            "rfc": 1, "title": "T", "status": "draft",
            "authors": ["did:key:z6Mk"], "created": "2026-05-30",
            "unknown_extra_field": "x",
        })


def test_unknown_status_value_rejected() -> None:
    with pytest.raises(ValidationError):
        RFCFrontmatter.model_validate({
            "rfc": 1, "title": "T", "status": "approved",  # not in Literal
            "authors": ["did:key:z6Mk"], "created": "2026-05-30",
        })


def test_rfc_zero_rejected_by_ge_constraint() -> None:
    # rfc: int = Field(ge=1) — Templates use rfc:0 but the linter skips them
    # by FILENAME, not by parse — so the schema itself still refuses rfc<1
    # to keep "0" as a clear "this is a template" tombstone.
    with pytest.raises(ValidationError):
        RFCFrontmatter.model_validate({
            "rfc": 0, "title": "T", "status": "draft",
            "authors": ["did:key:z6Mk"], "created": "2026-05-30",
        })


def test_parse_frontmatter_missing_block_raises_value_error() -> None:
    with pytest.raises(ValueError, match="frontmatter"):
        parse_frontmatter("no frontmatter here\njust body\n")


# ───────────────────── raw-dict parser ─────────────────────
def test_parse_frontmatter_raw_returns_unknown_keys() -> None:
    """`_parse_frontmatter_raw` keeps unknown keys (used by body-only-edit check)."""
    text = (
        "---\n"
        "rfc: 1\n"
        "title: T\n"
        "status: discussion\n"
        "authors:\n"
        "  - did:key:z6Mk\n"
        "created: 2026-05-30\n"
        "status_change_reason: discussion period opened\n"
        "---\n"
        "body\n"
    )
    raw = _parse_frontmatter_raw(text)
    assert raw["status"] == "discussion"
    assert raw["status_change_reason"] == "discussion period opened"
    assert raw["authors"] == ["did:key:z6Mk"]


def test_parse_frontmatter_raw_missing_block_returns_empty_or_raises() -> None:
    # Either raise or return empty — but never silently lose the body.
    # We follow `parse_frontmatter`'s convention and raise.
    with pytest.raises(ValueError):
        _parse_frontmatter_raw("no frontmatter\n")
