"""Substantive-input guard (B6): keep heading, contents and attribution lines out of
knowledge extraction.

Boundary detection can emit bare structural lines as candidate units: an enumerated
heading ("B. Synthetic Topic"), a table-of-contents entry, an epigraph attribution
("— A. Synthetic Author"), a page number or "N/A". Handing such a line to the
generative distiller invites it to invent substance, for example authority that the
source never cites, to fill the void. A verifiable anchor does not catch this: the
anchor faithfully points at the heading; the fabricated claim is the problem.

``is_substantive`` is the single predicate that boundary detection (drop the
boundary) and the distiller (skip the model call) both consult, so the guard holds
at the source and again in depth. It is deliberately conservative: a genuine
one-sentence rule that clears the length floor and reads like a sentence is kept.
"""

from __future__ import annotations

import re

# Default floor; overridable with Settings.min_substantive_chars.
MIN_SUBSTANTIVE_CHARS = 40

# An enumerated heading or contents prefix: "A.", "1.", "IV.", "1.2", "2.3.1)", a
# structural word ("Section 3", "Chapter 4", "Part II", "Appendix B"), or "§ 5".
_HEADING_PREFIX = re.compile(
    r"^\s*(?:"
    r"(?:[A-Za-z]|[IVXLCDM]{1,6}|\d{1,3}(?:\.\d{1,3})*)[.)]"
    r"|(?:section|chapter|part|article|appendix|title|clause|subsection)\b"
    r"|§+\s*\d"
    r")",
    re.IGNORECASE,
)

# An attribution line: a dash followed by a short capitalized name.
_ATTRIBUTION = re.compile(r"^\s*[—–-]\s*[A-Z][A-Za-z.\s]{1,40}$")

# Sentence punctuation that real prose usually carries.
_SENTENCE_PUNCT = re.compile(r"[.!?:;](?:[\"')\]]|\s|$)")

_WORD = re.compile(r"[A-Za-z]{2,}")


def is_substantive(text: str, min_chars: int = MIN_SUBSTANTIVE_CHARS) -> bool:
    """Return True iff ``text`` carries enough substance to distill safely.

    False for:

    - text shorter than ``min_chars``;
    - fewer than three alphabetic words (page numbers, dividers, "N/A");
    - an attribution line (a dash and a name);
    - a heading-shaped line: an enumerated or structural prefix, no sentence
      punctuation after the prefix and at most ten words;
    - a title-case line with no sentence punctuation and at most eight words.
    """
    t = (text or "").strip()
    if len(t) < min_chars:
        return False

    words = _WORD.findall(t)
    if len(words) < 3:
        return False

    if _ATTRIBUTION.match(t):
        return False

    # The prefix's own period ("IV.", "B.") is not sentence punctuation: look past it.
    prefix = _HEADING_PREFIX.match(t)
    body = t[prefix.end():] if prefix else t
    has_sentence_punct = bool(_SENTENCE_PUNCT.search(body))

    if prefix and not has_sentence_punct and len(words) <= 10:
        return False

    if not has_sentence_punct and len(words) <= 8:
        capitalized = sum(1 for w in words if w[:1].isupper())
        if capitalized >= max(2, len(words) - 1):
            return False

    return True


__all__ = ["MIN_SUBSTANTIVE_CHARS", "is_substantive"]
