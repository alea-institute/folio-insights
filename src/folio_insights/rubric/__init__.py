"""Deterministic extraction-quality rubric harness (Phase 10 U6; RUB-EXTRACT v1.0).

Scores a v1 unit run (``extraction.json`` + sources) or a v2 shard corpus against the
locked rubric ``docs/rubrics/extraction-quality-v1.md``:

* ``adapters`` - ``UnitRun`` and ``ShardCorpus`` build one ``RubricArtifact`` view;
* ``oracle`` - ``IriOracle`` with a frozen ``FixtureOracle`` and the live
  ``FolioResolveOracle``;
* ``criteria`` - the 14-criterion catalogue and the five [DET] scorers (-03, -05, -09,
  -10, -11), pure functions;
* ``harness`` - ``score(artifact, oracle, judged)``: gates, weights and the pass rule;
  without judged scores a run is never ``publishable``;
* ``gold`` - the synthetic books gold set and the mapping-gold check;
* ``cli`` - ``folio-insights rubric score`` / ``rubric gold``.
"""

from folio_insights.rubric.adapters import (
    AdapterError,
    RubricArtifact,
    RubricUnit,
    ShardCorpus,
    UnitRun,
)
from folio_insights.rubric.criteria import (
    CATALOGUE,
    DET_CRITERIA,
    JUDGED_CRITERIA,
    RUBRIC_VERSION,
    CriterionResult,
)
from folio_insights.rubric.harness import (
    JudgedScores,
    JudgedScoresError,
    RubricReport,
    load_judged,
    parse_judged,
    score,
)
from folio_insights.rubric.oracle import (
    FixtureOracle,
    FolioResolveOracle,
    IriOracle,
    OracleError,
    load_oracle,
)

__all__ = [
    "CATALOGUE",
    "DET_CRITERIA",
    "JUDGED_CRITERIA",
    "RUBRIC_VERSION",
    "AdapterError",
    "CriterionResult",
    "FixtureOracle",
    "FolioResolveOracle",
    "IriOracle",
    "JudgedScores",
    "JudgedScoresError",
    "OracleError",
    "RubricArtifact",
    "RubricReport",
    "RubricUnit",
    "ShardCorpus",
    "UnitRun",
    "load_judged",
    "load_oracle",
    "parse_judged",
    "score",
]
