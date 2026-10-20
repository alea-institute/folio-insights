"""Polysemy and distinguo (PRINCIPLE-06; Phase 1 spike, productionized in Phase 9 U6).

Detector inputs come from P1 clusters and P2 frameworks (``candidates``); Rule 1
asks a reasoner about TBox disjointness (``tbox``); similarity stays in
``similarity_query`` (KTD10); thresholds live in ``whitelists`` and the typed,
empty-by-default ``thresholds``; forks render only against a human disposition
(``distinguo``); the FP gate reads the Wilson upper bound (``fp_audit``,
``labeled_set``).
"""
from folio_insights.polysemy.cli import polysemy as polysemy_cli_group
from folio_insights.polysemy.dispositions import (
    DispositionRecord,
    ProposedFork,
    append_disposition,
    read_dispositions,
)
from folio_insights.polysemy.reviewer import ensure_reviewer_did
from folio_insights.polysemy.whitelists import (
    DEFAULT_DISTINGUO_THRESHOLD,
    HOMONYMS,
    TERMS_OF_ART,
    TERMS_OF_ART_THRESHOLD,
)

__all__ = [
    "DispositionRecord",
    "ProposedFork",
    "append_disposition",
    "read_dispositions",
    "ensure_reviewer_did",
    "TERMS_OF_ART",
    "HOMONYMS",
    "DEFAULT_DISTINGUO_THRESHOLD",
    "TERMS_OF_ART_THRESHOLD",
    "polysemy_cli_group",
]
