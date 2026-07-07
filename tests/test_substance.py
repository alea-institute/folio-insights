"""Unit tests for the B6 substantive-input guard (services/substance.py)."""

from __future__ import annotations

import pytest

from folio_insights.services.substance import is_substantive

# The exact shapes that produced fabricated authority in book-UAT
# (docs/solutions/heading-as-unit-fabrication.md) plus common heading/TOC noise.
NON_SUBSTANTIVE = [
    "A. Litigation",
    "C. Character Traits",
    "—T.S. Eliot",
    "— Justice Oliver Wendell Holmes",
    "N/A",
    "IV. Cross-Examination",
    "1.2 Opening Statements",
    "Chapter 3",
    "Section 5",
    "The Art Of Cross Examination",
    "TABLE OF CONTENTS",
    "42",
    "",
    "   ",
]

# Genuine one-sentence advocacy insights that must survive the guard.
SUBSTANTIVE = [
    "Always establish the witness's bias before impeaching with a prior inconsistent statement.",
    "Never ask a question on cross-examination unless you already know the answer.",
    "A leading question suggests the answer and is permitted on cross but not on direct.",
    "File the motion for summary judgment before the discovery deadline expires.",
    "The witness must be prepared for cross-examination well before trial begins.",
]


@pytest.mark.parametrize("text", NON_SUBSTANTIVE)
def test_headings_and_toc_dropped(text: str) -> None:
    assert is_substantive(text) is False, f"leaked non-substantive: {text!r}"


@pytest.mark.parametrize("text", SUBSTANTIVE)
def test_real_prose_kept(text: str) -> None:
    assert is_substantive(text) is True, f"false-dropped real prose: {text!r}"


def test_min_chars_is_configurable() -> None:
    short_but_real = "Object to leading questions."  # 28 chars
    assert is_substantive(short_but_real, min_chars=40) is False
    assert is_substantive(short_but_real, min_chars=10) is True
