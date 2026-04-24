"""folio-insights polysemy — human-gated CLI for polysemy/distinguo spike.

PRINCIPLE-06: every disposition requires a keystroke. There is NO
``--auto``, ``--yes``, ``--batch``, or ``--accept-all`` flag anywhere in
this subgroup. The CliRunner tests in ``tests/polysemy/test_cli_review.py``
enforce this by asserting the absence of such flags in ``review.params``.

OQ-5 RESOLVED: a single ``--llm-provider MODEL_STRING`` flag controls
both provider family and model (e.g., 'claude-haiku-4-5', 'gpt-4o-mini',
'gemini-1.5-flash', 'ollama/llama3.2'). Default is 'claude-haiku-4-5'.
Provider family is resolved from the model-string prefix by
``detector._resolve_provider_family``.

Commands
--------
* ``folio-insights polysemy detect`` — runs the 4-rule detector gate on
  a fixture directory and prints the verdict table. No disposition is
  recorded.
* ``folio-insights polysemy review`` — interactive reviewer: renders the
  detector verdict, then prompts for ``accept|reject|modify``; ``modify``
  sub-prompts for the analogia triad (prime_analogate, proportional_relation,
  distinction_kind) and renders the proposed TTL before committing. All
  outcomes write exactly one ``DispositionRecord`` JSON line to the
  dispositions log via ``append_disposition()``.
* ``folio-insights polysemy audit`` — prints a count summary of recorded
  dispositions (no record mutation).

The dispositions log (default
``.planning/phases/01-polysemy-distinguo-spike/dispositions.jsonl``) is
append-only and is consumed by Plan 01-06 FP-audit via
``read_dispositions()``. Phase 15's polysemy-fork UI also binds to this
schema (schema_version='1').
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib

import click
from pyoxigraph import RdfFormat
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from folio_insights.polysemy.detector import detect_polysemy
from folio_insights.polysemy.dispositions import (
    DispositionRecord,
    ProposedFork,
    append_disposition,
)
from folio_insights.polysemy.distinguo import (
    ForkProposal,
    emit_fork_ttl,
    validate_fork_proposal_shape,
)
from folio_insights.polysemy.fixture_loader import (
    consideration_fixtures_to_ttl,
    load_consideration_fixtures,
)
from folio_insights.polysemy.prototype_cluster import build_prototype_cluster
from folio_insights.polysemy.reviewer import ensure_reviewer_did
from folio_insights.store.pyoxigraph_store import PyoxigraphStore

_DISPOSITIONS_PATH = pathlib.Path(
    ".planning/phases/01-polysemy-distinguo-spike/dispositions.jsonl"
)
_DEFAULT_FIXTURES = pathlib.Path(
    ".planning/phases/01-polysemy-distinguo-spike/fixtures/consideration"
)
_DISTINCTION_KINDS = [
    "realis",
    "rationis",
    "rationis_cum_fundamento_in_re",
    "analogica",
]

console = Console()


@click.group("polysemy")
def polysemy() -> None:
    """Polysemy / distinguo spike: detect, review, audit."""


# --------------------------- detect ---------------------------
@polysemy.command("detect")
@click.option(
    "--fixtures",
    type=click.Path(exists=True, path_type=pathlib.Path),
    default=_DEFAULT_FIXTURES,
    show_default=True,
    help="Directory of consideration fixture JSONs.",
)
@click.option(
    "--term",
    default="consideration",
    show_default=True,
    help="Term to cluster across frameworks.",
)
@click.option(
    "--llm-provider",
    default="claude-haiku-4-5",
    show_default=True,
    help=(
        "Model string (OQ-5 single-flag). "
        "Examples: 'claude-haiku-4-5', 'gpt-4o-mini', 'gemini-1.5-flash', "
        "'ollama/llama3.2'. Provider family resolved from prefix."
    ),
)
def detect_cmd(
    fixtures: pathlib.Path,
    term: str,
    llm_provider: str,
) -> None:
    """Run the 4-rule detector on a fixture directory (no disposition writes)."""
    shards = load_consideration_fixtures(fixtures)
    store = PyoxigraphStore(path=None)
    store.store.bulk_load(
        consideration_fixtures_to_ttl(shards).encode("utf-8"),
        RdfFormat.TURTLE,
    )
    cluster = build_prototype_cluster(shards)  # positional; B5 signature
    verdict = detect_polysemy(cluster, store, llm_provider=llm_provider)

    table = Table(title=f"Detector verdict for term '{term}'")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("decision", verdict.decision)
    table.add_row("kind", verdict.kind)
    table.add_row("matched_rules", ", ".join(verdict.matched_rules or ["-"]))
    table.add_row("evidence_score", f"{verdict.evidence_score:.3f}")
    console.print(table)


# --------------------------- review ---------------------------
@polysemy.command("review")
@click.option(
    "--fixtures",
    type=click.Path(exists=True, path_type=pathlib.Path),
    default=_DEFAULT_FIXTURES,
    show_default=True,
)
@click.option("--term", default="consideration", show_default=True)
@click.option(
    "--dispositions-path",
    type=click.Path(path_type=pathlib.Path),
    default=_DISPOSITIONS_PATH,
    show_default=True,
)
@click.option(
    "--llm-provider",
    default="claude-haiku-4-5",
    show_default=True,
    help="Model string (OQ-5 single-flag).",
)
def review_cmd(
    fixtures: pathlib.Path,
    term: str,
    dispositions_path: pathlib.Path,
    llm_provider: str,
) -> None:
    """Review detector verdicts one-at-a-time; every disposition requires a keystroke.

    PRINCIPLE-06 (no auto-apply) is enforced by the CliRunner test suite:
    no flag exists to skip the ``rich.prompt.Prompt.ask()`` gate.
    """
    reviewer_did = ensure_reviewer_did()
    shards = load_consideration_fixtures(fixtures)
    store = PyoxigraphStore(path=None)
    store.store.bulk_load(
        consideration_fixtures_to_ttl(shards).encode("utf-8"),
        RdfFormat.TURTLE,
    )
    cluster = build_prototype_cluster(shards)  # positional; B5 signature
    verdict = detect_polysemy(cluster, store, llm_provider=llm_provider)

    console.print(f"[bold]Term:[/bold] {term}")
    console.print(f"[bold]Cluster ID:[/bold] {cluster.cluster_id}")
    console.print(f"[bold]Verdict:[/bold] {verdict.decision}")
    console.print(f"[bold]Kind:[/bold] {verdict.kind}")
    console.print(
        f"[bold]Matched rules:[/bold] "
        f"{', '.join(verdict.matched_rules or ['-'])}"
    )
    console.print(f"[bold]Evidence score:[/bold] {verdict.evidence_score:.3f}")

    # REQUIRED keystroke — no default shortcut. Prompt.ask(choices=[...])
    # re-asks on invalid input; there is NO default= argument anywhere in
    # the review flow (Pitfall 6 / T-01-05-02).
    decision = Prompt.ask(
        "Disposition",
        choices=["accept", "reject", "modify"],
        show_choices=True,
    )

    frameworks = sorted({s.framework for s in shards})

    # Detector's *proposed* fork (pre-modification). Canonical DispositionRecord
    # requires ``proposed_fork: ProposedFork`` (not Optional). The accept path
    # commits it unchanged; reject annotates it; modify overrides it.
    detector_proposed_fork = ProposedFork(
        cluster_id=cluster.cluster_id,
        term=term,
        frameworks=frameworks,
        uses_analogousTo=False,
        distinction_kind=None,
    )
    proposed_fork: ProposedFork = detector_proposed_fork

    if decision == "modify":
        prime = Prompt.ask(
            "Prime analogate IRI (e.g. urn:folio:term/consideration#restatement)"
        )
        proportional = Prompt.ask("Proportional relation (short prose)")
        dkind = Prompt.ask(
            "Distinction kind",
            choices=_DISTINCTION_KINDS,
            show_choices=True,
        )
        fork = ForkProposal(
            term=term,
            cluster_id=cluster.cluster_id,
            uses_analogousTo=True,
            prime_analogate=prime,
            proportional_relation=proportional,
            distinction_kind=dkind,
            source_frameworks=tuple(frameworks),
            reviewer_did=reviewer_did,
            created_at_iso=_dt.datetime.now(_dt.UTC).isoformat(),
        )
        # Pitfall 5 defense-in-depth (T-01-05-08): explicitly re-validate
        # before we commit or render, in case a future refactor replaces
        # the pydantic validator with a weaker construction path.
        validate_fork_proposal_shape(fork)
        # Render the proposed TTL for reviewer confirmation (visual-only,
        # still requires a keystroke to commit).
        console.print("\n[bold]Proposed fork TTL:[/bold]")
        console.print(emit_fork_ttl(fork))
        confirm = Prompt.ask(
            "Commit this modification?",
            choices=["yes", "no"],
            show_choices=True,
        )
        if confirm != "yes":
            console.print("[yellow]Modification aborted by reviewer.[/yellow]")
            return
        proposed_fork = fork.to_proposed_fork()

    rationale = Prompt.ask("Rationale (press enter for empty)", default="")

    record = DispositionRecord(
        cluster_id=cluster.cluster_id,
        term=term,
        proposed_fork=proposed_fork,
        decision=decision,
        rationale=rationale,
        reviewer_did=reviewer_did,
        reviewed_at_iso=_dt.datetime.now(_dt.UTC).isoformat(),
        detector_verdict=verdict.model_dump(),  # full snapshot (B6)
    )
    dispositions_path.parent.mkdir(parents=True, exist_ok=True)
    append_disposition(record, dispositions_path)
    console.print(
        f"[green]Disposition recorded:[/green] {decision} -> {dispositions_path}"
    )


# --------------------------- audit ---------------------------
_AUDIT_REPORT_PATH = pathlib.Path(
    ".planning/phases/01-polysemy-distinguo-spike/fp-labeling-audit.md"
)


@polysemy.command("audit")
@click.option(
    "--dispositions-path",
    type=click.Path(exists=True, path_type=pathlib.Path),
    default=_DISPOSITIONS_PATH,
    show_default=True,
)
@click.option(
    "--emit-disagreements",
    is_flag=True,
    help=(
        "Invoke the LLM audit pass and emit a disagreements-only report "
        "(D-4 lock) to --report-path."
    ),
)
@click.option(
    "--report-path",
    type=click.Path(path_type=pathlib.Path),
    default=_AUDIT_REPORT_PATH,
    show_default=True,
    help="Destination for the disagreements-only audit report.",
)
@click.option(
    "--llm-provider",
    default="claude-haiku-4-5",
    show_default=True,
    help=(
        "Model string for the LLM audit pass (OQ-5 RESOLVED: family "
        "resolved via prefix — claude-*, gpt-*, gemini-*, ollama/*)."
    ),
)
def audit_cmd(
    dispositions_path: pathlib.Path,
    emit_disagreements: bool,
    report_path: pathlib.Path,
    llm_provider: str,
) -> None:
    """Print a summary table of recorded dispositions.

    With ``--emit-disagreements`` the audit additionally computes the Wilson
    CI-bounded FP rate and runs a second-reader LLM pass, writing only the
    disagreement rows to ``--report-path`` (D-4 lock; agreements are silently
    counted).
    """
    counts: dict[str, int] = {"accept": 0, "reject": 0, "modify": 0}
    total = 0
    with dispositions_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            counts[rec["decision"]] = counts.get(rec["decision"], 0) + 1
            total += 1
    table = Table(title=f"Dispositions summary ({total} total)")
    table.add_column("Decision")
    table.add_column("Count")
    for k, v in counts.items():
        table.add_row(k, str(v))
    console.print(table)

    if emit_disagreements:
        # Lazy import — keeps `folio-insights polysemy audit --help` snappy
        # and avoids paying the LLMBridge/instructor import cost for the
        # default count-summary path.
        from folio_insights.polysemy.fp_audit import (
            compute_fp_rate,
            run_llm_audit_pass,
        )
        fp = compute_fp_rate(dispositions_path)
        console.print(
            f"FP rate: {fp['fp_rate']:.1%} "
            f"(Wilson 95% CI: {fp['ci_lower']:.1%} - {fp['ci_upper']:.1%}); "
            f"kappa={fp['kappa']:.3f} (signal-only; {fp['kappa_caveat']})"
        )
        result = run_llm_audit_pass(
            dispositions_path,
            report_path,
            llm_provider=llm_provider,
        )
        console.print(
            f"Audit wrote {result['disagreements']} disagreements "
            f"(of {result['total']}) to {report_path}"
        )


__all__ = ["polysemy"]
