"""The gated shard minter (drain U8, Phase 10 U5).

Turns an extraction run's KnowledgeUnits into source-grounded ``hypothesis``
``SimpleAssertionShard``s, refusing every unit whose evidence does not hold up:

* :mod:`.eligibility` -- per-unit checks and refusal codes (no LLM, no writes);
* :mod:`.fields` -- the ``mint.fields.v1`` field-inference call, framework and BFO;
* :mod:`.mapper` -- unit -> shard field mapping, identity and prompt hashes;
* :mod:`.minter` -- ``mint_run``: the run, storage writes and ExtractEvents;
* :mod:`.report` -- the run report (with the deterministic rubric section);
* :mod:`.cli` -- ``folio-insights mint``.
"""
from folio_insights.minting.eligibility import (
    REFUSAL_CODES,
    Eligible,
    Refused,
    RunEvidence,
    evaluate,
)
from folio_insights.minting.minter import (
    MintError,
    MintRefused,
    is_local_only,
    mark_local_only,
    mint_run,
)
from folio_insights.minting.report import MintReport, UnitOutcome

__all__ = [
    "REFUSAL_CODES",
    "Eligible",
    "MintError",
    "MintRefused",
    "MintReport",
    "Refused",
    "RunEvidence",
    "UnitOutcome",
    "evaluate",
    "is_local_only",
    "mark_local_only",
    "mint_run",
]
