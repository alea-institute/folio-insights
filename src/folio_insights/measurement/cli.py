"""Measurement corpus commands; execute acquisition in evaluator custody only.

Until U5 installs the package entry point, use
``python -m folio_insights.measurement.cli corpus --help``.
"""
from __future__ import annotations

import json
from pathlib import Path

import click
import httpx
from pydantic import ValidationError

from folio_insights.measurement.corpus import (
    DEFAULT_ROOT, CorpusError, DocumentRequest, HttpFetcher, collect, load_manifest,
    load_policy, seal, verify,
)


@click.group()
def cli() -> None:
    """Offline measurement verification and orchestrator acquisition tools."""


@cli.group()
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
                               HttpFetcher(client, user_agent=user_agent), seed=seed)
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


if __name__ == "__main__":
    cli()
