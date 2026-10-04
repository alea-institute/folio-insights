"""Substantive-input guard (B6): keep heading, contents and attribution lines out of
knowledge extraction.

Boundary detection can emit bare structural lines as candidate units: an enumerated
heading ("B. Synthetic Topic"), a table-of-contents entry, an epigraph attribution
("— A. Synthetic Author"), a page number or "N/A". Handing such a line to the
generative distiller invites it to invent substance, for example authority that the
source never cites, to fill the void. A verifiable anchor does not catch this: the
anchor faithfully points at the heading; the fabricated claim is the problem.

Two predicates, deliberately conservative:

* ``is_structural`` judges SHAPE only (heading, contents entry, attribution, no words).
  Boundary detection drops a boundary only on this, so short genuine advice ("Never lead
  on direct examination.") and enumerated tips ("1. Ask only leading questions on
  cross-examination", "a) Object to hearsay before the answer comes in") stay units.
* ``is_substantive`` adds a small length floor (``min_substantive_chars``, 20 by default)
  for the distiller, which skips the model call for anything below it.

A line with a structural prefix is still prose when its body reads like a clause: three or
more lowercase words ("Section 1983 claims require state action ...") or sentence
punctuation after the prefix. A title-cased line stays a heading ("Rule 403 Excludes
Unfairly Prejudicial Evidence").
"""

from __future__ import annotations

import re

# Default distiller floor; overridable with Settings.min_substantive_chars.
MIN_SUBSTANTIVE_CHARS = 20

# An enumerated heading or contents prefix: "A.", "1.", "IV.", "1.2", "2.3.1)", "a)", a
# structural word with an optional number ("Section 3", "Chapter 4", "Rule 403", "Part II"),
# or "§ 5".
_HEADING_PREFIX = re.compile(
    r"^\s*(?:"
    r"(?:[A-Za-z]|[IVXLCDM]{1,6}|\d{1,3}(?:\.\d{1,3})*)[.)]"
    r"|(?:section|chapter|part|article|appendix|title|clause|subsection|rule)\b"
    r"(?:\s+[\dIVXLCDM]+[\w.()-]*)?"
    r"|§+\s*\d[\w.()-]*"
    r")",
    re.IGNORECASE,
)

# An attribution line: a dash followed by a short capitalized name.
_ATTRIBUTION = re.compile(r"^\s*[—–-]\s*[A-Z][A-Za-z.\s]{1,40}$")

# A contents entry: dot leaders, or a title ending in a bare page number.
_CONTENTS = re.compile(r"\.{4,}|(?:\s|\t)\d{1,4}\s*$")

# Sentence punctuation that real prose usually carries.
_SENTENCE_PUNCT = re.compile(r"[.!?:;](?:[\"')\]]|\s|$)")

_WORD = re.compile(r"[A-Za-z]{2,}")


def is_structural(text: str) -> bool:
    """True iff ``text`` is shaped like a heading, contents entry or attribution line, or
    has no real words. Length alone never makes a line structural."""
    t = (text or "").strip()
    words = _WORD.findall(t)
    if len(words) < 3:
        return True
    if _ATTRIBUTION.match(t):
        return True

    # The prefix's own period ("IV.", "B.") is not sentence punctuation: look past it.
    prefix = _HEADING_PREFIX.match(t)
    body = t[prefix.end():] if prefix else t
    body_words = _WORD.findall(body)
    has_sentence_punct = bool(_SENTENCE_PUNCT.search(body))
    lowercase = sum(1 for w in body_words if w[0].islower())
    reads_like_clause = has_sentence_punct or lowercase >= 3

    if _CONTENTS.search(t) and not reads_like_clause:
        return True
    if prefix and not reads_like_clause and len(words) <= 10:
        return True
    if not has_sentence_punct and len(words) <= 8:
        capitalized = sum(1 for w in words if w[:1].isupper())
        if capitalized >= max(2, len(words) - 1):
            return True
    return False


def is_substantive(text: str, min_chars: int = MIN_SUBSTANTIVE_CHARS) -> bool:
    """True iff ``text`` is not structural and has at least ``min_chars`` characters (the
    distiller's floor)."""
    t = (text or "").strip()
    return len(t) >= min_chars and not is_structural(t)


__all__ = ["MIN_SUBSTANTIVE_CHARS", "is_structural", "is_substantive"]
