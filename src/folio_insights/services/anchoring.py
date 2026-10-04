"""Resolve a unit's text to a verifiable character span in its source (RUB-EXTRACT-05).

A knowledge unit may paraphrase, but it must prove which passage it came from. This
module locates the unit text in the ingested source text and returns a real span, the
exact source substring at that span and a match score, so the pipeline stores a
verifiable anchor instead of synthetic running offsets:

1. An exact substring match scores 1.0 and is verified.
2. Otherwise ``rapidfuzz.fuzz.partial_ratio_alignment`` finds the best-aligned window
   of the source. It is verified when its score reaches the threshold (0.85); below
   that it is still returned, unverified, so a reviewer or judge can fail the unit.

The snippet is always ``source_text[start:end]``, so span and snippet never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

MIN_ANCHOR_SCORE = 0.85


@dataclass(frozen=True)
class AnchorResult:
    """A resolved anchor: a real span into the source plus its match quality."""

    start: int
    end: int
    snippet: str  # source_text[start:end]
    score: float  # 1.0 for an exact match, else the rapidfuzz score / 100
    verified: bool  # score >= threshold


def resolve_anchor(
    candidate: str,
    source_text: str,
    threshold: float = MIN_ANCHOR_SCORE,
) -> AnchorResult | None:
    """Locate ``candidate`` in ``source_text``. ``None`` only for empty input."""
    candidate = (candidate or "").strip()
    if not candidate or not source_text:
        return None

    idx = source_text.find(candidate)
    if idx != -1:
        return AnchorResult(idx, idx + len(candidate), candidate, 1.0, True)

    alignment = fuzz.partial_ratio_alignment(candidate, source_text)
    if alignment is None:
        return None
    score = alignment.score / 100.0
    start = max(0, min(alignment.dest_start, len(source_text)))
    end = max(start, min(alignment.dest_end, len(source_text)))
    return AnchorResult(start, end, source_text[start:end], score, score >= threshold)


__all__ = ["MIN_ANCHOR_SCORE", "AnchorResult", "resolve_anchor"]
