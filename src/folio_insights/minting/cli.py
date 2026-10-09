"""``folio-insights mint`` (drain U8, R1-R5).

::

    folio-insights mint CORPUS --run extraction.json --sources DIR \\
        --source-visibility public|non-public [--signing-key PATH | --extractor-did DID] \\
        [--llm-provider P] [--llm-model M] [--framework ID] [--framework-default ID] \\
        (--oracle folio|PATH | --no-iri-oracle) [--field-floor F] \\
        [--support-floor F] [--nli-support [--nli-threshold F]] [--report out.json] [--dry-run]
    folio-insights mint CORPUS --mark-local-only

Mints the run's eligible units into CORPUS (``minting.minter.mint_run``) and
prints (or writes) the JSON run report. Exit status: 0 when the run completed
(refused units are normal outcomes, listed in the report), 1 when the whole run
was refused or its inputs could not be read, 2 for a usage error.

``--source-visibility`` is required: every run declares whether its sources are
public. A non-public run is refused, before any model call, unless CORPUS was
marked local-only with ``--mark-local-only`` (R5; Phase 13.5 private corpora do
not exist yet). The LLM route and keys follow ``extract``: the invoking user's
environment, ``--llm-provider`` / ``--llm-model``, per-task
``LLM_MINT_FIELDS_PROVIDER/MODEL`` overrides, and the cumulative spend cap.

``--oracle`` is required for a real mint: every carried FOLIO IRI must exist in the
branch its tag claims before anything is written. ``--no-iri-oracle`` mints without
that check and the report flags ``iri_unchecked``. Every unit's text must be supported
by its verified source slice (``minting.support``): its specifics must occur there and
its content-token recall must reach ``--support-floor`` (default 0.6);
``--nli-support`` adds an entailment check with the local NLI cross-encoder (the run is
refused, never silently downgraded, when that model cannot load).

``extract --mint`` is not wired: minting is a separate, gated post-pipeline step
that needs its own visibility declaration and signing identity, so it runs as
its own command over the run ``extract`` wrote.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from folio_insights.governance.cli._state import corpus_root_option, resolve_corpus_root


def _llm_options(func):  # noqa: ANN001, ANN202
    """The ``extract`` LLM flags (same names, meaning and defaults as ``cli._llm_options``;
    declared here so importing this module never imports the top-level CLI)."""
    from folio_insights.llm.providers import supported_providers

    func = click.option("--llm-model", default=None,
                        help="Model for every LLM task (default: settings or the provider's "
                             "default model).")(func)
    func = click.option("--max-spend-usd", default=None, type=float,
                        help="Spend cap in USD (default $FOLIO_INSIGHTS_LLM_MAX_SPEND_USD), "
                             "cumulative across runs of this corpus and --spend-window.")(func)
    func = click.option("--spend-window", default="default", show_default=True,
                        help="Name of the cumulative spend budget for this corpus.")(func)
    func = click.option("--llm-provider", default=None,
                        type=click.Choice(supported_providers(), case_sensitive=False),
                        help="LLM provider for every LLM task (default: "
                             "FOLIO_INSIGHTS_LLM_PROVIDER).")(func)
    return func


@click.command(name="mint")
@click.argument("corpus")
@click.option("--run", "run_path", type=click.Path(exists=True, path_type=Path), default=None,
              help="The extraction run (extraction.json, or the directory holding it).")
@click.option("--sources", "sources_dir", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="Directory of the ingested source texts the units anchor to.")
@click.option("--source-visibility", type=click.Choice(["public", "non-public"]), default=None,
              help="Required: are this run's sources public? Non-public sources mint only into "
                   "a corpus marked local-only.")
@click.option("--signing-key", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Ed25519 JWK of the extractor (needs the extractor role): signs each shard "
                   "and its ExtractEvent. Without it shards are unsigned and no ExtractEvent "
                   "is written.")
@click.option("--extractor-did", default=None,
              help="first_extractor_did for an unsigned run (with --signing-key it must be "
                   "the key's did:key, or omitted).")
@click.option("--framework", "framework_id", default=None,
              help="The sources' framework ID (v1 year-suffixed IDs are migrated, with a "
                   "warning in the report).")
@click.option("--framework-default", default=None,
              help="Corpus default framework ID, used when the source names none.")
@click.option("--oracle", default=None,
              help="FOLIO IRI oracle for BFO typing and RUB-EXTRACT-03: 'folio' (live "
                   "ontology) or a frozen oracle JSON file.")
@click.option("--no-iri-oracle", is_flag=True, default=False,
              help="Mint without an IRI oracle (carried IRIs are not checked to exist in "
                   "their claimed branch; the report flags iri_unchecked).")
@click.option("--field-floor", type=click.FloatRange(0.0, 1.0), default=None,
              help="Confidence floor for every inferred field (default 0.6).")
@click.option("--support-floor", type=click.FloatRange(0.0, 1.0), default=None,
              help="Content-token recall the unit text must reach against its verified "
                   "source slice (default 0.6).")
@click.option("--nli-support", is_flag=True, default=False,
              help="Also require NLI entailment of the unit text by its verified slice "
                   "(local cross-encoder; the run is refused if it cannot load).")
@click.option("--nli-threshold", type=click.FloatRange(0.0, 1.0), default=None,
              help="Entailment probability floor for --nli-support (default 0.5).")
@click.option("--run-id", default=None,
              help="Run ID in each op ID (default: derived from the extraction file's hash).")
@click.option("--source-namespace", default=None,
              help="Source URI namespace (default: the extraction run's corpus name).")
@click.option("--report", "report_path", type=click.Path(dir_okay=False, path_type=Path),
              default=None, help="Write the JSON report here (default: stdout).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Evaluate eligibility and identity only: no model call, no write.")
@click.option("--no-rubric", is_flag=True, default=False,
              help="Skip the deterministic rubric section of the report.")
@click.option("--mark-local-only", is_flag=True, default=False,
              help="Only declare CORPUS local-only (never dumped or exported) and exit.")
@_llm_options
@corpus_root_option
def mint_cmd(
    corpus: str,
    run_path: Path | None,
    sources_dir: Path | None,
    source_visibility: str | None,
    signing_key: Path | None,
    extractor_did: str | None,
    framework_id: str | None,
    framework_default: str | None,
    oracle: str | None,
    no_iri_oracle: bool,
    field_floor: float | None,
    support_floor: float | None,
    nli_support: bool,
    nli_threshold: float | None,
    run_id: str | None,
    source_namespace: str | None,
    report_path: Path | None,
    dry_run: bool,
    no_rubric: bool,
    mark_local_only: bool,
    llm_provider: str | None,
    llm_model: str | None,
    max_spend_usd: float | None,
    spend_window: str,
    corpus_root: Path | None,
) -> None:
    """Mint an extraction run's eligible units into CORPUS as hypothesis shards."""
    from folio_insights.minting.fields import FieldFloors
    from folio_insights.minting.minter import MintError, MintRefused, mint_run
    from folio_insights.minting.minter import mark_local_only as mark
    from folio_insights.minting.support import (
        DEFAULT_MIN_RECALL,
        DEFAULT_NLI_THRESHOLD,
        SupportPolicy,
    )

    root = resolve_corpus_root(corpus_root)
    if mark_local_only:
        if run_path is not None:
            raise click.UsageError("--mark-local-only only declares the corpus; run it alone")
        click.echo(f"marked local-only: {mark(root, corpus)}")
        return
    if run_path is None or sources_dir is None or source_visibility is None:
        raise click.UsageError("--run, --sources and --source-visibility are required")
    if oracle and no_iri_oracle:
        raise click.UsageError("--oracle and --no-iri-oracle contradict each other")
    if nli_threshold is not None and not nli_support:
        raise click.UsageError("--nli-threshold needs --nli-support")
    policy = SupportPolicy(
        min_recall=DEFAULT_MIN_RECALL if support_floor is None else support_floor,
        nli=nli_support,
        nli_threshold=DEFAULT_NLI_THRESHOLD if nli_threshold is None else nli_threshold,
    )

    sk = None
    if signing_key is not None:
        from folio_insights.identity.keys import load_signing_key

        try:
            sk = load_signing_key(signing_key)
        except FileNotFoundError:
            click.echo(f"mint error: no signing key at {signing_key}", err=True)
            sys.exit(1)
        except Exception as exc:  # noqa: BLE001 - never echo key material
            click.echo(f"mint error: the signing key could not be loaded ({type(exc).__name__})",
                       err=True)
            sys.exit(1)

    rubric_oracle = None
    if oracle:
        from folio_insights.rubric.oracle import OracleError, load_oracle

        try:
            rubric_oracle = load_oracle(oracle)
        except OracleError as exc:
            click.echo(f"mint error: {exc}", err=True)
            sys.exit(1)

    port = llm_ctx = None
    if not dry_run:
        from folio_insights.cli import _install_cli_llm_context
        from folio_insights.llm import get_default_port

        llm_ctx = _install_cli_llm_context(llm_provider, llm_model, max_spend_usd, corpus,
                                           spend_window)
        port = get_default_port()

    coro = mint_run(
        root, corpus, run_path,
        sources_dir=sources_dir, llm=port, source_visibility=source_visibility,
        signing_key=sk, extractor_did=extractor_did, llm_context=llm_ctx, run_id=run_id,
        source_namespace=source_namespace, framework_id=framework_id,
        framework_default=framework_default, oracle=rubric_oracle,
        field_floors=FieldFloors(default=field_floor) if field_floor is not None else None,
        dry_run=dry_run, score_rubric=not no_rubric, support=policy,
        require_iri_oracle=not no_iri_oracle,
    )
    if llm_ctx is not None:
        from folio_insights.cli import _closing

        coro = _closing(llm_ctx, coro)
    try:
        report = asyncio.run(coro)
    except (MintRefused, MintError) as exc:
        code = getattr(exc, "code", "input")
        click.echo(f"mint refused ({code}): {exc}", err=True)
        sys.exit(1)

    text = json.dumps(report.as_dict(), indent=2, sort_keys=False)
    if report_path is None:
        click.echo(text)
    else:
        report_path.write_text(text + "\n", encoding="utf-8")
        counts = report.counts()
        click.echo(f"{counts['by_status']} -> {report_path}")
    if llm_ctx is not None and report_path is not None:
        from folio_insights.cli import _echo_llm_usage

        _echo_llm_usage(llm_ctx)  # stdout carries the JSON report otherwise


__all__ = ["mint_cmd"]
