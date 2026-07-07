"""Resolve a verbatim source snippet to a verified char-span in the source text.

Implements the HYBRID-STRICT anchoring the locked rubric (RUB-EXTRACT-05) requires:
a knowledge unit may paraphrase, but it must prove which passage it came from via
either (a) a real character-span whose sliced text is non-empty, or (b) an exact
quoted snippet that fuzzy-matches the source >= 0.85. This module locates a
candidate substring in the raw source and returns a real span + match score, so
the pipeline stores a *verifiable* anchor rather than synthetic running offsets.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

MIN_ANCHOR_SCORE = 0.85


@dataclass
class AnchorResult:
    """A resolved anchor: a real span into the source plus its match quality."""

    start: int
    end: int
    snippet: str  # the exact source substring actually stored
    score: float  # 1.0 if exact match, else rapidfuzz ratio / 100
    verified: bool  # True iff score >= threshold


def resolve_anchor(
    candidate: str,
    source_text: str,
    threshold: float = MIN_ANCHOR_SCORE,
) -> AnchorResult | None:
    """Locate ``candidate`` in ``source_text``, returning a real char-span.

    1. Exact substring search -> score 1.0, verified.
    2. Else a sliding-window ``rapidfuzz.fuzz.ratio`` scan for the best-matching
       window of ~len(candidate) characters. If the best window scores
       >= ``threshold`` it is returned verified; otherwise the best-effort window
       is returned with ``verified=False`` so the judge can fail the unit.

    Returns ``None`` only when no anchor could be located at all (empty inputs).
    """
    candidate = (candidate or "").strip()
    if not candidate or not source_text:
        return None

    # 1. Exact match. Prefer the occurrence nearest a hint if the caller gives
    #    one; otherwise the first occurrence.
    idx = source_text.find(candidate)
    if idx != -1:
        return AnchorResult(idx, idx + len(candidate), candidate, 1.0, True)

    # 2. Fuzzy: partial_ratio_alignment finds the optimal aligned window inside
    #    the source AND its score in one pass — accurate span (dest_start/end
    #    are always valid indices into source_text) with no sampling gap.
    alignment = fuzz.partial_ratio_alignment(candidate, source_text)
    if alignment is None:
        return None
    score = alignment.score / 100.0
    start = alignment.dest_start
    end = alignment.dest_end
    # Guard: keep the span within bounds (alignment is already in-bounds, but be
    # defensive) and keep snippet/span consistent.
    start = max(0, min(start, len(source_text)))
    end = max(start, min(end, len(source_text)))
    matched = source_text[start:end]
    return AnchorResult(start, end, matched, score, score >= threshold)
