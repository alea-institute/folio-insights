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
  outcomes write a ``DispositionRecord`` JSON line via ``append_disposition()``.
  ``--prepare`` saves the exact record and signing input without approval;
  ``--prepared-record`` with ``--signed-decision`` verifies and displays that
  same payload before an explicit confirmation. Signed retries append once.
* ``folio-insights polysemy audit`` — prints a count summary of recorded
  dispositions (no record mutation).
* ``folio-insights polysemy gate`` — runs the detector over a labeled set and
  reports the PRINCIPLE-06 FP gate (Wilson upper bound; ``provisional`` until
  a human certifies the set). Read-only.

Phase 9 U6: Rule 1 reads the TBox disjointness seeds (``tbox_seeds.ttl``); a
``reject`` needs a non-empty rationale (KTD9) and is refused otherwise; every
review records ``labeler: "human"``; only a registered signature establishes
review authority. The ``modify`` path renders a Pattern-2
PREVIEW of the reviewer's analogia triad (``distinguo.emit_fork_ttl``) to the
terminal before asking for confirmation; it writes it to no graph. No command
renders the TBox-bound PRD fork (``distinguo.emit_distinguo_fork_ttl``, which
needs a logged human disposition of that exact fork) or applies any fork to a
TBox.

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
from folio_insights.polysemy.tbox import load_tbox_seeds
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


def _spike_store(shards: list) -> PyoxigraphStore:
    """The fixtures' shard TTL plus the Rule 1 TBox seeds (``tbox_seeds.ttl``)."""
    store = PyoxigraphStore(path=None)
    store.store.bulk_load(
        consideration_fixtures_to_ttl(shards).encode("utf-8"),
        RdfFormat.TURTLE,
    )
    load_tbox_seeds(store)
    return store


@click.group("polysemy")
def polysemy() -> None:
    """Polysemy / distinguo spike: detect, review, audit."""
    # The LLM fallback and FP audit run on the invoking user's own keys (their environment).
    from folio_insights.llm import Credentials, LLMRunContext, use_context

    click.get_current_context().with_resource(
        use_context(LLMRunContext(credentials=Credentials.from_env()))
    )


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
    store = _spike_store(shards)
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
@click.option("--corpus", help="Corpus ID; required for signed review and preparation.")
@click.option("--reviewer-did", help="Public signer DID for preparation (no private key is read).")
@click.option("--prepare", type=click.Path(path_type=pathlib.Path),
              help="Save the reviewed record and a sibling .decision.json signing input; append nothing.")
@click.option("--prepared-record", type=click.Path(exists=True, path_type=pathlib.Path),
              help="Exact reviewed record previously saved by --prepare.")
@click.option("--signed-decision", type=click.Path(exists=True, path_type=pathlib.Path),
              help="Detached result of proposals sign-decision for --prepared-record.")
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
    corpus: str | None,
    reviewer_did: str | None,
    prepare: pathlib.Path | None,
    prepared_record: pathlib.Path | None,
    signed_decision: pathlib.Path | None,
) -> None:
    """Review detector verdicts one-at-a-time; every disposition requires a keystroke.

    PRINCIPLE-06 (no auto-apply) is enforced by the CliRunner test suite:
    no flag exists to skip the ``rich.prompt.Prompt.ask()`` gate.
    """
    from folio_insights.polysemy.signing import disposition_fields, verify_disposition
    from folio_insights.proposals.signed_decisions import (
        DecisionPolicyMisconfigured, parse_signed_decision, validate_corpus_id,
    )

    if prepare is not None and (prepared_record is not None or signed_decision is not None):
        raise click.UsageError("--prepare cannot be combined with signed submission")
    if (prepare is not None or prepared_record is not None or signed_decision is not None) and not corpus:
        raise click.UsageError("--corpus is required for preparation and signed submission")
    try:
        corpus = validate_corpus_id(corpus or "default")
        if prepared_record is not None or signed_decision is not None:
            if prepared_record is None or signed_decision is None:
                raise click.UsageError("--prepared-record and --signed-decision are both required")
            record = DispositionRecord.model_validate_json(prepared_record.read_text(encoding="utf-8"))
            if record.corpus != corpus:
                raise ValueError("the prepared record is not for the selected corpus")
            evidence = parse_signed_decision(json.loads(signed_decision.read_text(encoding="utf-8")))
            record = record.model_copy(update={"signed_decision": evidence})
            verify_disposition(record)
            console.print_json(json.dumps(record.model_dump(mode="json")))
            if Prompt.ask("Record this signed disposition?", choices=["yes", "no"], show_choices=True) != "yes":
                console.print("Signed disposition aborted by reviewer.")
                return
            append_disposition(record, dispositions_path)
            console.print("Signed disposition recorded.")
            return
        if prepare is not None and not reviewer_did:
            raise click.UsageError("--reviewer-did is required with --prepare")
    except (ValueError, DecisionPolicyMisconfigured) as exc:
        raise click.ClickException(f"review refused; nothing was recorded: {exc}") from None

    reviewer_did = reviewer_did or ensure_reviewer_did()
    shards = load_consideration_fixtures(fixtures)
    store = _spike_store(shards)
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
        try:
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
        except ValueError as exc:  # pydantic ValidationError is a ValueError
            raise click.ClickException(
                f"invalid modification (nothing was recorded): {exc}"
            ) from exc
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

    if decision == "reject":
        # KTD9: a reject is the false-positive signal, so it must say why the
        # detector's call is wrong. No default: an empty answer is refused and
        # nothing is recorded.
        rationale = Prompt.ask("Rationale (required for reject: why is the detector wrong?)")
        if not rationale.strip():
            raise click.ClickException(
                "a reject needs a rationale; nothing was recorded (re-run review to dispose)"
            )
    else:
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
        labeler="human",  # a keystroke at this prompt; the only human-labeler path
        corpus=corpus,
    )
    if prepare is not None:
        signing_input = prepare.with_name(prepare.name + ".decision.json")
        # Never replace a prior reviewed payload: preparation is reproducible evidence.
        if prepare.exists() or signing_input.exists():
            raise click.ClickException("preparation destination already exists; nothing was recorded")
        fields = disposition_fields(record)
        prepare.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
        signing_input.write_text(json.dumps(fields, indent=2) + "\n", encoding="utf-8")
        console.print_json(json.dumps(fields))
        console.print(f"Prepared {prepare}; sign {signing_input} with proposals sign-decision. No approval recorded.")
        return
    try:
        append_disposition(record, dispositions_path)
    except (ValueError, DecisionPolicyMisconfigured) as exc:
        raise click.ClickException(f"review refused; nothing was recorded: {exc}") from None
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
            f"FP rate: {fp['fp_rate']:.1%} over {fp['total']} valid dispositions "
            f"(Wilson 95% CI: {fp['ci_lower']:.1%} - {fp['ci_upper']:.1%}; the gate reads "
            f"the upper bound); gate status: {fp['status']}; "
            f"invalid (reject without rationale): {fp['invalid_dispositions']}; "
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


# --------------------------- gate ---------------------------
_LABELED_SET_PATH = pathlib.Path("tests/polysemy/fixtures/labeled_set.json")


@polysemy.command("gate")
@click.option(
    "--labeled-set",
    type=click.Path(exists=True, path_type=pathlib.Path),
    default=_LABELED_SET_PATH,
    show_default=True,
    help="Labeled-set JSON (format folio-insights/polysemy-labeled-set/v1).",
)
def gate_cmd(labeled_set: pathlib.Path) -> None:
    """Run the detector over a labeled set and report the PRINCIPLE-06 FP gate.

    Read-only: it records no disposition and applies nothing. Rule 4 (known
    homonyms) runs against a pessimistic fake that always answers polysemy, so
    no provider is called and the bound does not depend on a live model. The
    status is ``pass`` only with a human certification of this exact set.
    """
    from folio_insights.polysemy.labeled_set import evaluate_labeled_set, load_labeled_set

    evaluation = evaluate_labeled_set(load_labeled_set(labeled_set))
    report = evaluation.report
    table = Table(title=f"Polysemy FP gate ({labeled_set.name})")
    table.add_column("Figure")
    table.add_column("Value")
    table.add_row("N (valid dispositions)", str(report.n))
    table.add_row("false positives", str(report.false_positives))
    table.add_row("FP rate", f"{report.fp_rate:.1%}")
    table.add_row("Wilson 95% upper bound (gate)", f"{report.ci_upper:.1%}")
    table.add_row("threshold", f"{report.threshold:.0%}")
    table.add_row("status", report.status)
    table.add_row("certification", "valid" if report.certified else str(report.certification_problem))
    table.add_row("detector positives", str(report.detector_positives))
    table.add_row("false discovery rate", f"{report.false_discovery_rate:.1%}")
    table.add_row("false negatives", str(evaluation.false_negatives))
    table.add_row("Rule 4 LLM", evaluation.llm_label)
    table.add_row("cases sha256", evaluation.cases_sha256)
    console.print(table)


__all__ = ["polysemy"]
