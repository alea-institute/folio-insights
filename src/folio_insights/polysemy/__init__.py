"""Phase 1 polysemy-distinguo spike (PRINCIPLE-06 scoping + VOCAB-02 first-use)."""
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
