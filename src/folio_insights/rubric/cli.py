"""``folio-insights rubric``: score extraction quality against RUB-EXTRACT v1.0.

* ``rubric score TARGET`` - score a v1 unit run or a v2 shard corpus. TARGET is an
  ``extraction.json`` file or a directory holding one (a unit run), else the name of a
  corpus under the storage root (``--corpus-root``, else ``$FOLIO_INSIGHTS_CORPUS_ROOT``).
  ``--run FILE`` scores that extraction file as a unit run whatever TARGET is (TARGET is
  then only a label). The five [DET] criteria are computed; the nine judged criteria
  are ``not_scored`` unless ``--judged FILE`` supplies them, and the run is
  ``publishable`` only when the rubric's whole pass rule holds.
* ``rubric gold`` - score the committed books gold set and the mapping-gold check;
  exits 1 on any drift from the recorded expectations.

Exit status of ``score``: 0 when scoring succeeded (whatever the verdict), 1 on unusable
input, 3 with ``--strict`` when the result is not publishable.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from folio_insights.governance.cli._state import corpus_root_option, resolve_corpus_root


@click.group(name="rubric")
def rubric_group() -> None:
    """Deterministic extraction-quality rubric (RUB-EXTRACT v1.0)."""


@rubric_group.command(name="score")
@click.argument("target")
@click.option("--run", "run_file", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="extraction.json to score as a unit run (TARGET is then only a label).")
@click.option("--sources", "sources_dir", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="Directory of source texts for the anchor checks.")
@click.option("--oracle", "oracle_spec", default=None,
              help="IRI oracle: a fixture JSON file, or 'folio' for the live ontology.")
@click.option("--judged", "judged_file", type=click.Path(dir_okay=False, path_type=Path),
              default=None, help="Judged scores for the LLM / MCP / taste criteria.")
@click.option("--json", "as_json", is_flag=True, help="Print the full report as JSON.")
@click.option("--strict", is_flag=True, help="Exit 3 when the result is not publishable.")
@corpus_root_option
def score_cmd(
    target: str,
    run_file: Path | None,
    sources_dir: Path | None,
    oracle_spec: str | None,
    judged_file: Path | None,
    as_json: bool,
    strict: bool,
    corpus_root: Path | None,
) -> None:
    """Score TARGET (an extraction.json, its directory, or a corpus name)."""
    from folio_insights.rubric.adapters import AdapterError, ShardCorpus, UnitRun
    from folio_insights.rubric.harness import JudgedScoresError, load_judged, score
    from folio_insights.rubric.oracle import OracleError, load_oracle

    try:
        oracle = load_oracle(oracle_spec)
        judged = load_judged(judged_file) if judged_file is not None else None
        target_path = Path(target)
        if run_file is not None:
            artifact = UnitRun.load(run_file, sources_dir)
        elif target_path.is_file() or (target_path / "extraction.json").is_file():
            artifact = UnitRun.load(target_path, sources_dir)
        else:
            artifact = asyncio.run(
                ShardCorpus.load(resolve_corpus_root(corpus_root), target, sources_dir)
            )
        report = score(artifact, oracle=oracle, judged=judged)
    except (AdapterError, OracleError, JudgedScoresError) as exc:
        click.echo(f"rubric error: {exc}", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(report.as_dict(), indent=2, default=str))
    else:
        click.echo(report.render_text())
    if strict and not report.publishable:
        sys.exit(3)


@rubric_group.command(name="gold")
@click.option("--gold-dir", type=click.Path(file_okay=False, path_type=Path), default=None,
              help="Gold set directory (default: tests/rubric/fixtures/books_gold).")
@click.option("--oracle", "oracle_path", type=click.Path(dir_okay=False, path_type=Path),
              default=None, help="Fixture oracle (default: tests/rubric/fixtures/folio_oracle.json).")
@click.option("--corrections", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Human mapping corrections (default: the books evidence gold file).")
@click.option("--mapping-expected", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Recorded mapping-gold baseline.")
@click.option("--json", "as_json", is_flag=True, help="Print the full result as JSON.")
def gold_cmd(
    gold_dir: Path | None,
    oracle_path: Path | None,
    corrections: Path | None,
    mapping_expected: Path | None,
    as_json: bool,
) -> None:
    """Score the books gold set; exit 1 if any score drifts from its expectation."""
    from folio_insights.rubric.adapters import AdapterError
    from folio_insights.rubric.gold import GoldSetError, run_gold
    from folio_insights.rubric.harness import JudgedScoresError
    from folio_insights.rubric.oracle import OracleError

    try:
        result = run_gold(gold_dir, oracle_path=oracle_path, corrections_path=corrections,
                          mapping_expected_path=mapping_expected)
    except (AdapterError, OracleError, JudgedScoresError, GoldSetError) as exc:
        click.echo(f"rubric gold error: {exc}", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(result.as_dict(), indent=2, default=str))
    else:
        for case in result.cases:
            mark = "ok   " if not case.drift else "DRIFT"
            click.echo(f"{mark} {case.case}  publishable={str(case.report.publishable).lower()}")
            for line in case.drift:
                click.echo(f"      {line}")
        m = result.mapping
        mark = "ok   " if not result.mapping_drift else "DRIFT"
        click.echo(f"{mark} mapping-gold  agreement {m.get('agree')}/{m.get('corrections')} "
                   f"= {m.get('agreement_rate')}")
        for line in result.mapping_drift:
            click.echo(f"      {line}")
        click.echo(f"{len(result.cases)} case(s), {len(result.drift)} drift finding(s)")
    if not result.ok:
        sys.exit(1)


__all__ = ["rubric_group"]
