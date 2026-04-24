"""Phase 1 polysemy detector whitelists and thresholds.

Values locked by CONTEXT.md D-2 + .planning/research/PITFALLS.md L651-652.
Extension requires CONTEXT.md revision, not a silent edit.
"""
from __future__ import annotations

TERMS_OF_ART: frozenset[str] = frozenset(
    {
        "consideration",
        "notice",
        "reasonable",
        "material",
        "person",
        "holding",
        "negligence",
        "good faith",
    }
)
HOMONYMS: frozenset[str] = frozenset(
    {
        "bar",
        "interest",
        "execute",
        "party",
        "serve",
    }
)

DEFAULT_DISTINGUO_THRESHOLD: float = 0.6  # PRD §16 R2
TERMS_OF_ART_THRESHOLD: float = 0.8  # PITFALLS L652
