"""Substantive-input guard (B6): keep heading/TOC/attribution lines out of
knowledge extraction.

Boundary detection can emit bare headings, table-of-contents entries, and
attribution lines (``A. Litigation``, ``C. Character Traits``, ``—T.S. Eliot``,
``N/A``) as candidate units. Feeding those to a generative distiller makes it
*invent* legal authority to fill the void — fabricated citations like
``Rule 56(c)`` / ``FRE 404(a)(1)`` absent from the source. That trips the
locked rubric's zero-tolerance fabrication gate (RUB-EXTRACT-06) and the
verifiable-anchor oracle does NOT catch it (the snippet faithfully copies the
heading; the *claim* is what invents). See docs/solutions/
heading-as-unit-fabrication.md.

``is_substantive`` is the single predicate both the boundary stage (drop the
unit) and the distiller (skip the LLM call) consult, so the guard is enforced
at the source and defended in depth.
"""

from __future__ import annotations

import re

# Default floor; overridable via Settings.min_substantive_chars.
MIN_SUBSTANTIVE_CHARS = 40

# Enumerated heading / TOC prefixes: "A.", "1.", "IV.", "1.2", "1.2.3",
# "Section 3", "Chapter 4", "Part II", "Article V", "§ 5".
_HEADING_PREFIX = re.compile(
    r"^\s*(?:"
    r"(?:[A-Za-z]|[IVXLCDM]{1,6}|\d{1,3}(?:\.\d{1,3})*)[.)]"  # A.  1.  IV.  1.2)
    r"|(?:section|chapter|part|article|appendix|title|clause|subsection)\b"
    r"|§+\s*\d"
    r")",
    re.IGNORECASE,
)

# Attribution line: an em/en dash or hyphen followed by a capitalized name,
# e.g. "—T.S. Eliot", "– Justice Holmes", "- John Doe".
_ATTRIBUTION = re.compile(r"^\s*[—–-]\s*[A-Z][A-Za-z.\s]{1,40}$")

# Sentence-terminal punctuation — real prose usually carries it.
_SENTENCE_PUNCT = re.compile(r"[.!?:;](?:[\"')\]]|\s|$)")

_WORD = re.compile(r"[A-Za-z]{2,}")


def is_substantive(text: str, min_chars: int = MIN_SUBSTANTIVE_CHARS) -> bool:
    """Return True iff ``text`` carries enough substance to distill safely.

    Rejects (returns False) for content that a generative distiller would
    hallucinate authority from:

    - shorter than ``min_chars`` (headings, TOC entries, ``N/A``, page numbers,
      attributions are almost always short);
    - attribution lines (dash + name);
    - heading/TOC-shaped lines: an enumerated prefix (``A.``/``1.2``/``Chapter
      3``) with no sentence-terminal punctuation and few words;
    - lines with essentially no alphabetic words (page numbers, ``N/A``,
      dividers).

    Deliberately conservative: a genuine one-sentence rule or warning that
    clears ``min_chars`` and reads like a sentence is kept.
    """
    t = (text or "").strip()
    if len(t) < min_chars:
        return False

    words = _WORD.findall(t)
    if len(words) < 3:
        # Too few real words to be an insight (numbers, dividers, "N/A").
        return False

    if _ATTRIBUTION.match(t):
        return False

    has_terminal_punct = bool(_SENTENCE_PUNCT.search(t))

    # Heading/TOC-shaped: enumerated prefix, no sentence punctuation, short.
    if _HEADING_PREFIX.match(t) and not has_terminal_punct and len(words) <= 10:
        return False

    # Title-case header with no sentence punctuation and few words (e.g.
    # "The Art Of Cross Examination"): most tokens start uppercase and the
    # line reads like a heading, not a clause.
    if not has_terminal_punct and len(words) <= 8:
        capitalized = sum(1 for w in words if w[:1].isupper())
        if capitalized >= max(2, len(words) - 1):
            return False

    return True
