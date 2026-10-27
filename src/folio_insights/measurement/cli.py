"""Measurement and corpus commands for evaluator custody.

Run ``python -m folio_insights.measurement --help`` for all commands.
Live acquisition and subscription judges are invoked only by operators.
"""
from __future__ import annotations

import asyncio
import json
import signal
import threading
from pathlib import Path

import click
import httpx
from pydantic import ValidationError

from folio_insights.measurement.annotations import AnnotationStore
from folio_insights.measurement.corpus import (
    DEFAULT_ROOT, DEFAULT_THROTTLE_STATE, CorpusError, DocumentRequest, HttpFetcher, collect, load_manifest,
    load_policy, seal, verify,
)
from folio_insights.measurement.gold import load_gold, load_ontology
from folio_insights.measurement.judges import ClaudeJudge, CodexJudge
from folio_insights.measurement.matching import EquivalenceInputs
from folio_insights.measurement.runs import MeasurementCoordinator, PipelineExtraction
from folio_insights.measurement.schema import EvaluationInputs
from folio_insights.measurement.store import RunStore


@click.group(name="measurement")
def measurement_group() -> None:
    """Validate gold, coordinate measurement runs, and collect or verify corpora."""


# Both existing import names expose the same parser and command registry.
cli = measurement_group


@measurement_group.command("validate-gold")
@click.option("--gold", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--ontology", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def validate_gold_cmd(gold: Path | None, ontology: Path | None) -> None:
    """Validate source digests, spans, links and deterministic tag resolution."""
    try:
        suite = load_gold(gold, ontology=load_ontology(ontology))
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({"suite": suite.suite_id, "gold_revision": suite.gold_revision,
                           "documents": len(suite.documents), "status": "valid"}))


@measurement_group.command("run")
@click.option("--inputs", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Frozen EvaluationInputs JSON, including exact CLI identities.")
@click.option("--extractions", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="JSON object mapping source IDs to completed single-source extraction.json files.")
@click.option("--gold", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--ontology", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", default="output/measurement", type=click.Path(file_okay=False, path_type=Path))
@click.option("--annotations-db", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--equivalences", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Authored semantic edges frozen against the adapted extraction outputs.")
@click.option("--split-id")
@click.option("--batch-size", default=20, type=click.IntRange(min=1), show_default=True)
def run_cmd(inputs: Path, extractions: Path, gold: Path | None, ontology: Path | None,
            output: Path, annotations_db: Path | None, equivalences: Path | None,
            split_id: str | None, batch_size: int) -> None:
    """Judge, score and checkpoint; repeat identical inputs to resume missing work.

    Run only in evaluator custody. Extract upstream in a separate source-only
    candidate workspace; this command never starts the API-backed pipeline.
    """
    cancelled = threading.Event()
    previous = signal.getsignal(signal.SIGINT)
    try:
        pins = EvaluationInputs.model_validate_json(inputs.read_text())
        paths = json.loads(extractions.read_text())
        if not isinstance(paths, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                  for k, v in paths.items()):
            raise ValueError("extractions must map source IDs to paths")
        adapter = PipelineExtraction({sid: extractions.parent / path for sid, path in paths.items()})
        pinned_ontology = load_ontology(ontology)
        suite = load_gold(gold, ontology=pinned_ontology)
        edges = EquivalenceInputs.model_validate_json(equivalences.read_text()) if equivalences else None
        coordinator = MeasurementCoordinator(RunStore(output),
            AnnotationStore(annotations_db or output / "review.db"), batch_size=batch_size)
        signal.signal(signal.SIGINT, lambda *_: cancelled.set())
        report = asyncio.run(coordinator.run(
            suite, pins, extractor=adapter, ontology=pinned_ontology,
            codex=CodexJudge(model=pins.judge_identities["codex"].model),
            claude=ClaudeJudge(model=pins.judge_identities["claude"].model),
            split_id=split_id, cancelled=cancelled, equivalences=edges))
    except (ValueError, OSError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        signal.signal(signal.SIGINT, previous)
    # Detailed reasons and labels remain in evaluator storage, not stdout receipts.
    click.echo(json.dumps({"run_id": report.run_id, "status": report.status,
                           "stage": report.stage, "errors": report.errors,
                           "scores": report.scores,
                           "adjudication_count": len(report.adjudication)}, ensure_ascii=False))
    if report.status != "complete":
        raise click.exceptions.Exit(2)


@measurement_group.group("annotations")
def annotations_group() -> None:
    """Read authored history or export partition-filtered tuning annotations."""


@annotations_group.command("export-tuning")
@click.option("--db", required=True, type=click.Path(dir_okay=False, path_type=Path))
def export_tuning_cmd(db: Path) -> None:
    """Export tuning and retired-split annotations, excluding active held-out data."""
    rows = asyncio.run(AnnotationStore(db).export_tuning())
    click.echo(json.dumps([row.model_dump(mode="json") for row in rows], ensure_ascii=False))


@annotations_group.command("history")
@click.option("--db", required=True, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--run-id", required=True)
def history_cmd(db: Path, run_id: str) -> None:
    """Read a run's complete history in evaluator custody."""
    rows = asyncio.run(AnnotationStore(db).history(run_id=run_id))
    click.echo(json.dumps([row.model_dump(mode="json") for row in rows], ensure_ascii=False))


@measurement_group.group("corpus")
def corpus() -> None:
    """Collect, verify and seal public corpus cells in evaluator custody."""


def _root_option(function):
    return click.option("--evaluator-root", type=click.Path(path_type=Path),
                        help="Cell directory; default: output/measurement/sealed/<jurisdiction>/<genre>.")(function)


@corpus.command("collect")
@click.option("--requests", "requests_path", required=True,
              type=click.Path(exists=True, path_type=Path, dir_okay=False),
              help="JSON array of document metadata, rights proof and selection offsets.")
@click.option("--policy", "policy_path", type=click.Path(exists=True, path_type=Path))
@click.option("--user-agent", required=True, help="Identify research client and contact.")
@click.option("--seed", default=0, type=click.IntRange(min=0))
@_root_option
def collect_command(requests_path: Path, policy_path: Path | None,
                    user_agent: str, seed: int, evaluator_root: Path | None) -> None:
    """Fetch at most eight documents; report missing rights/access as incomplete."""
    try:
        requests = [DocumentRequest.model_validate(row)
                    for row in json.loads(requests_path.read_bytes())]
        if not requests:
            raise CorpusError("collection requires document requests")
        evaluator_root = _cell_root(evaluator_root, requests[0].jurisdiction, requests[0].genre)
        with httpx.Client() as client:
            manifest = collect(requests, load_policy(policy_path), evaluator_root,
                               HttpFetcher(client, user_agent=user_agent,
                                           state_path=DEFAULT_THROTTLE_STATE), seed=seed)
        _print_verification(verify(manifest, evaluator_root))
    except (OSError, ValueError, TypeError, ValidationError) as exc:
        _fail(exc)


@corpus.command("verify")
@click.option("--jurisdiction", type=click.Choice(["federal", "MN", "TX", "CA", "NY", "FL", "IL"]))
@click.option("--genre", type=click.Choice(["opinions", "statutes-regulations", "briefs"]))
@click.option("--require-documents", default=8, type=int)
@_root_option
def verify_command(jurisdiction: str | None, genre: str | None,
                   require_documents: int, evaluator_root: Path | None) -> None:
    """Verify acquired bytes, rights, grounding and split without HTTP requests."""
    try:
        evaluator_root = _cell_root(evaluator_root, jurisdiction, genre)
        result = verify(load_manifest(evaluator_root / "manifest.json"), evaluator_root,
                        jurisdiction=jurisdiction, genre=genre, require_documents=require_documents)
        _print_verification(result)
    except (OSError, ValueError, ValidationError) as exc:
        _fail(exc)


@corpus.command("seal")
@click.option("--tuning-output", required=True, type=click.Path(path_type=Path))
@click.option("--jurisdiction", type=click.Choice(["federal", "MN", "TX", "CA", "NY", "FL", "IL"]))
@click.option("--genre", type=click.Choice(["opinions", "statutes-regulations", "briefs"]))
@_root_option
def seal_command(tuning_output: Path, evaluator_root: Path | None,
                 jurisdiction: str | None, genre: str | None) -> None:
    """Seal a complete cell; export only tuning data to a new directory."""
    try:
        evaluator_root = _cell_root(evaluator_root, jurisdiction, genre)
        digest = seal(load_manifest(evaluator_root / "manifest.json"), evaluator_root, tuning_output)
        click.echo(json.dumps({"sealed_sha256": digest, "score_label": "judge agreement, unanchored"}))
    except (OSError, ValueError, ValidationError) as exc:
        _fail(exc)


def _cell_root(root: Path | None, jurisdiction: str | None, genre: str | None) -> Path:
    if root is not None:
        return root
    if jurisdiction is None or genre is None:
        raise CorpusError("select --jurisdiction and --genre, or pass --evaluator-root")
    return DEFAULT_ROOT / jurisdiction / genre


def _print_verification(result) -> None:
    click.echo(result.model_dump_json())
    if not result.complete:
        raise click.ClickException("corpus cell is incomplete")


def _fail(exc: Exception) -> None:
    # Pydantic and JSON errors can contain input values: never echo those values.
    reason = str(exc) if type(exc) is CorpusError else "invalid or unavailable corpus artifact"
    raise click.ClickException(reason) from None



def _unavailable(name: str, unit: str) -> click.Command:
    @click.command(name, context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
    def command():
        raise click.ClickException(f"{name} unavailable until {unit} is implemented")
    return command


for _name, _unit in (("baseline", "U6/U9"), ("compare", "U6"), ("readme", "U7/U8")):
    measurement_group.add_command(_unavailable(_name, _unit))
