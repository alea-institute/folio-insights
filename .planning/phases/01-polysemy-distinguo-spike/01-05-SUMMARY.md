---
phase: 01-polysemy-distinguo-spike
plan: 05
subsystem: polysemy

tags: [click, rich-prompt, cli, tdd, principle-06, no-auto-apply, oq-5, disposition-jsonl]

# Dependency graph
requires:
  - phase: 01-polysemy-distinguo-spike
    provides: "Plan 01-02 — DispositionRecord + ProposedFork + append_disposition + ensure_reviewer_did + load_consideration_fixtures + consideration_fixtures_to_ttl"
  - phase: 01-polysemy-distinguo-spike
    provides: "Plan 01-03 — detect_polysemy(cluster, store, llm_provider=) + RuleVerdict | LLMVerdict discriminated union + build_prototype_cluster(shards) positional signature"
  - phase: 01-polysemy-distinguo-spike
    provides: "Plan 01-04 — ForkProposal + validate_fork_proposal_shape + emit_fork_ttl + to_proposed_fork() projection"
provides:
  - "src/folio_insights/polysemy/cli.py — Click `polysemy` subgroup with detect|review|audit commands"
  - "folio-insights polysemy detect — read-only verdict display (no disposition writes)"
  - "folio-insights polysemy review — keystroke-gated interactive reviewer, writes one DispositionRecord JSONL line per invocation"
  - "folio-insights polysemy audit — disposition-count summary"
  - "Module-bottom subgroup registration in src/folio_insights/cli.py (mirrors bench pattern)"
affects: [01-06-fp-audit, phase-15-polysemy-fork, phase-9-p6-polysemy-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "rich.prompt.Prompt.ask(choices=[...], show_choices=True) — invalid input re-asks; NO default= argument on decision/kind/confirm prompts; only the rationale prompt has default='' (allowed — rationale is optional free-text)"
    - "Click subgroup module-bottom registration: `from ... import polysemy as _polysemy_group; cli.add_command(_polysemy_group)` verbatim mirror of bench pattern (cli.py L532-535)"
    - "CliRunner.invoke(input=stdin, catch_exceptions=False) + mock.patch on detect_polysemy + ensure_reviewer_did keeps tests deterministic and offline (no LLM calls, no DID file creation)"
    - "DispositionRecord accept/reject paths commit the detector's *proposed* fork (uses_analogousTo=False) unchanged — canonical 01-02 schema requires proposed_fork to be non-null on every record"
    - "RdfFormat.TURTLE enum over 'text/turtle' media-type string — keeps pytest warning-free (pyoxigraph 0.5.7 deprecated string form; matches 01-04 SUMMARY precedent)"
    - "Pitfall 5 defense-in-depth in modify path: ForkProposal(...) runs validator, then validate_fork_proposal_shape() re-checks in case a future refactor bypasses construction — belt-and-suspenders for VOCAB-02 atomic triad"

key-files:
  created:
    - src/folio_insights/polysemy/cli.py
  modified:
    - src/folio_insights/polysemy/__init__.py
    - src/folio_insights/cli.py
    - tests/polysemy/test_cli_review.py

key-decisions:
  - "Single GREEN commit covers both Task 1 (implementation) and Task 2 (tests) — the test module imports from folio_insights.polysemy.cli at top-level so a Task-1-only GREEN would fail `pytest --collect-only` with ModuleNotFoundError (same atomic-unit rationale as 01-04's single-GREEN and 01-02's Task 2 fixtures+loader commit)"
  - "RdfFormat.TURTLE applied proactively based on 01-04 SUMMARY's documented DeprecationWarning auto-fix — same underlying pyoxigraph 0.5.7 behavior applies to bulk_load here, so used the enum from the start rather than shipping with warnings and fixing in a follow-up"
  - "Rationale prompt uses default='' (the only prompt with a default) because rationale is optional free-text; decision/distinction_kind/confirm prompts NEVER specify default — any silent-default on those would violate PRINCIPLE-06 (T-01-05-02). Documented inline to prevent regression"
  - "Subgroup registration placed AFTER bench registration in src/folio_insights/cli.py — preserves phase ordering (bench lands in Phase 0, polysemy in Phase 1) and matches the module-bottom import-deferral discipline"

requirements-completed: [PRINCIPLE-06]

# Metrics
duration: ~10min
completed: 2026-04-24
---

# Phase 01 Plan 05: Click Polysemy Subgroup (Review/Detect/Audit) Summary

**The `folio-insights polysemy` Click subgroup — three subcommands (detect, review, audit) registered at the bottom of `src/folio_insights/cli.py` via the bench-mirror pattern, backed by rich.prompt for keystroke-gated review, writing one DispositionRecord JSON line per reviewer invocation to `dispositions.jsonl` — turns PRINCIPLE-06 from a README bullet into an executable CLI contract enforced by 10 CliRunner tests.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-04-24 (post-worktree-base-reset + uv venv recreation)
- **Tasks:** 2 (TDD-split: RED commit + single GREEN commit covering both Task 1 and Task 2)
- **Files modified:** 4 (1 new src module + 2 src edits + 1 test file rewritten from Wave-0 xfails)

## Accomplishments

- **PRINCIPLE-06 enforced at the flag-surface level.** `test_no_auto_apply_path` enumerates six forbidden flag names (`auto`, `yes`, `batch`, `accept_all`, `no_prompt`, `force`) and asserts none appear in `polysemy.commands['review'].params`. A future contributor who adds `--auto-apply` breaks the build. The invariant is documented in the module docstring AND mechanically enforced by pytest.
- **PRINCIPLE-06 enforced at the interaction level.** `test_review_invalid_choice_reprompts` feeds stdin `"foo\naccept\n\n"` — `Prompt.ask(choices=['accept','reject','modify'])` rejects `"foo"`, re-prompts, accepts `"accept"`, proceeds. Confirms `rich.prompt` does NOT silently default-accept. The decision/distinction-kind/confirm prompts carry NO `default=` argument anywhere in the code path; only the rationale prompt (optional free-text) has `default=""`.
- **OQ-5 W1 single-flag locked.** `test_single_llm_provider_flag` iterates over both `review` and `detect`, asserts `llm_provider` is present and `llm_model` is NOT. Single `--llm-provider MODEL_STRING` design per OQ-5 RESOLVED; no separate `--llm-model` flag anywhere.
- **Subgroup registered in root CLI via the bench pattern verbatim.** `src/folio_insights/cli.py` now has at L537-540 a module-bottom import + `cli.add_command(_polysemy_group)` mirroring the bench block at L528-530. `test_subgroup_registered_in_root_cli` confirms `'polysemy' in cli.commands`. `folio-insights polysemy --help` lists all three subcommands.
- **Accept/reject/modify paths drive end-to-end via scripted stdin (Pitfall 4 discipline).** Each `Prompt.ask()` call in the code path gets exactly one input line with a trailing `\n`:
  - accept: 2 lines (decision + blank rationale)
  - reject: 2 lines (decision + rationale)
  - modify-commit: 6 lines (decision, prime, proportional, kind, confirm=yes, rationale)
  - modify-abort: 5 lines (decision, prime, proportional, kind, confirm=no)
- **Modify path renders TTL before commit, runs Pitfall 5 defense-in-depth.** After building `ForkProposal(...)` (which fires the `@model_validator` atomic-triad check), the CLI calls `validate_fork_proposal_shape(fork)` as belt-and-suspenders, then prints `emit_fork_ttl(fork)` to the console. `test_review_modify_path` asserts `"fi:analogousTo" in result.output` — confirms the TTL render landed.
- **Canonical DispositionRecord schema exercised end-to-end.** Every record committed by the CLI carries the required `proposed_fork: ProposedFork` (accept/reject commit the detector's proposal with `uses_analogousTo=False`; modify overrides via `fork.to_proposed_fork()`) and `detector_verdict: dict` (from `verdict.model_dump()`, never a float — B6 guard preserved). `test_review_accept_path` + `test_audit_command_counts_dispositions` both assert the shape.
- **10 CliRunner tests green; 3 Wave-0 xfails in `test_cli_review.py` flipped to 10 real tests.** Full polysemy suite now at **37 passed / 3 xfailed** (up from 27/11 after 01-04 — 10 Wave-0 CLI xfails flipped; the remaining 3 xfails live in `test_fp_rate.py` and are owned by 01-06).

## Task Commits

- **RED** — `518fc42` (test) — `test(01-05): CliRunner suite for polysemy review|detect|audit subgroup`
- **GREEN** — `da7ef70` (feat) — `feat(01-05): polysemy Click subgroup (detect|review|audit) with PRINCIPLE-06 no-auto-apply`

Single GREEN commit covers both Task 1 (implementation) and Task 2 (test assertions) because `test_cli_review.py` imports from `folio_insights.polysemy.cli` at module top — a Task-1-only GREEN would fail `pytest --collect-only`. Matches 01-02 Task 2 and 01-04's documented atomic-unit rationale. No REFACTOR commit needed — GREEN landed clean (pyoxigraph `RdfFormat.TURTLE` enum used from the start based on 01-04 SUMMARY precedent, so no DeprecationWarning cleanup pass required).

_Metadata commit for this SUMMARY will be added separately after self-check._

## Click Commands + Parameter Surface (PRINCIPLE-06 + OQ-5 confirmation)

```
detect: params = ['fixtures', 'term', 'llm_provider']
detect: flag strings = ['--fixtures', '--term', '--llm-provider']

review: params = ['fixtures', 'term', 'dispositions_path', 'llm_provider']
review: flag strings = ['--fixtures', '--term', '--dispositions-path', '--llm-provider']

audit:  params = ['dispositions_path']
audit:  flag strings = ['--dispositions-path']
```

**No `--auto`, `--yes`, `--batch`, `--accept-all`, `--no-prompt`, `--force`, or `--llm-model` anywhere.** PRINCIPLE-06 + OQ-5 W1 both mechanically enforced.

Live `folio-insights polysemy --help` output (top-level):

```
Usage: folio-insights polysemy [OPTIONS] COMMAND [ARGS]...

  Polysemy / distinguo spike: detect, review, audit.

Commands:
  audit   Print a summary table of recorded dispositions.
  detect  Run the 4-rule detector on a fixture directory (no disposition...
  review  Review detector verdicts one-at-a-time; every disposition...
```

## CliRunner stdin recipes (copy-pasteable)

Use any of these as the `input=` argument to `CliRunner.invoke(polysemy, ['review', ...], input=STDIN, catch_exceptions=False)`. Every `rich.prompt.Prompt.ask()` in the code path gets exactly one line with a trailing `\n` — omit a line and the test will hang at the next prompt (Pitfall 4).

### accept (2 prompts: decision, rationale[blank])

```
accept
<blank>
```
(literal Python string: `"accept\n\n"`)

### reject (2 prompts: decision, rationale)

```
reject
fixtures disagree on the axiom
```
(literal Python string: `"reject\nfixtures disagree on the axiom\n"`)

### modify + commit (6 prompts: decision, prime, proportional, kind, confirm=yes, rationale)

```
modify
urn:folio:term/consideration#restatement
bargained-for exchange <-> mutual inducement
analogica
yes
context-specific divergence is genuine
```
(literal Python string: see `test_review_modify_path` in test file)

### modify + abort (5 prompts: decision, prime, proportional, kind, confirm=no)

```
modify
urn:folio:term/consideration#restatement
bargained-for exchange <-> mutual inducement
analogica
no
```
No disposition is written; the CLI prints `"[yellow]Modification aborted by reviewer.[/yellow]"` and exits with code 0 (user-canceled is not an error).

### invalid-then-valid choice (demonstrates re-prompt)

```
foo
accept
<blank>
```
`"foo"` is rejected by `Prompt.ask(choices=['accept','reject','modify'])`; `"accept"` is accepted on re-ask; blank rationale. Confirms PRINCIPLE-06 at the interaction layer (no silent default-accept).

## Module-Bottom Registration Pattern (bench mirror)

`src/folio_insights/cli.py` now ends with (L537-540):

```python
# Register the Phase 1 polysemy subgroup (PRINCIPLE-06 CLI surface).
# Same module-bottom pattern as bench above.
from folio_insights.polysemy.cli import polysemy as _polysemy_group

cli.add_command(_polysemy_group)
```

Placed immediately after the bench block (L528-530). Import is deferred to module-bottom — `folio-insights --help` does not pay the pyoxigraph/rich import cost until the user actually invokes `folio-insights polysemy ...`. Same discipline the bench subgroup established in Phase 0 (D-14).

## Canonical DispositionRecord Exercised Per Test

Each CliRunner test asserts the 01-02 canonical schema at the point it matters:

| Test | proposed_fork (required) | detector_verdict (dict, not float) | uses_analogousTo |
|---|---|---|---|
| `test_review_accept_path` | ✅ asserted non-null, cluster_id equal | ✅ `isinstance(..., dict)` + `kind == 'rule'` | ✅ False (detector's proposal, unchanged) |
| `test_review_reject_path` | ✅ asserted non-null | implicit (JSON parsed) | ✅ False |
| `test_review_modify_path` | ✅ asserted non-null | implicit (JSON parsed) | ✅ True (modify override) |
| `test_review_modify_aborts_on_no_confirm` | N/A — no record written | N/A | N/A |
| `test_review_invalid_choice_reprompts` | ✅ asserted via rec["decision"]=="accept" | implicit | ✅ False |
| `test_audit_command_counts_dispositions` | ✅ all 4 pre-seeded records have full proposed_fork block | ✅ all 4 have detector_verdict as dict | ✅ mix of False/True |

Every CLI-written record carries the REQUIRED `proposed_fork` block, confirming the 01-02 canonical-shape contract never degrades to Optional.

## Decisions Made

- **Single GREEN commit (not split Task-1-GREEN + Task-2-GREEN):** test module imports `from folio_insights.polysemy.cli import polysemy` at module top. A Task-1-only GREEN commit would fail `pytest --collect-only` with `ModuleNotFoundError`. The 01-02 and 01-04 SUMMARYs both documented the same pattern — code + tests land together when the import graph demands it. No REFACTOR commit needed.
- **Rationale prompt is the ONLY prompt with a `default=` argument** (`default=""`). Rationale is optional free-text (reviewer can skip with Enter). Decision/distinction-kind/confirm prompts deliberately have NO default — any silent-accept on those would violate PRINCIPLE-06 (T-01-05-02 mitigation). Documented in the module docstring to prevent a future maintainer from "improving ergonomics" by adding `default="accept"`.
- **Accept/reject commit the detector's `uses_analogousTo=False` proposal unchanged.** Canonical `DispositionRecord.proposed_fork` is REQUIRED (not Optional per 01-02 revision 1). Even when the reviewer rejects the detector's output, the record carries the detector's *proposal* for audit traceability — Phase 15's UI can render the rejected-but-still-valid fork shape alongside the reviewer's rationale.
- **Modify writes the fork only after `yes`-confirm.** The abort path (`confirm != "yes"`) returns early with a yellow console message; NO record is written and NO TTL is persisted to any store. The CLI prints the proposed TTL before confirmation so the reviewer can eyeball the serialization — ergonomic proof that VOCAB-02 TTL is a human-readable audit artifact (§16 R2 ergonomic proof-of-concept).
- **RdfFormat.TURTLE enum over `'text/turtle'` string.** Plan text showed `'text/turtle'` for readability; implementation uses the enum to avoid pyoxigraph 0.5.7 DeprecationWarning. Matches 01-04 SUMMARY's auto-fix precedent — applied proactively (no follow-up commit required).
- **detect command does NOT call `ensure_reviewer_did()`.** Detect is read-only; no DID is needed because no disposition is written. This keeps `folio-insights polysemy detect` runnable without the one-time `~/.folio-insights/reviewer.jwk` generation, which may be desirable for CI smoke tests and fresh-clone browsing.
- **audit command uses `exists=True` on the `--dispositions-path` Click option** — so `folio-insights polysemy audit` fails fast with a clean error if the log hasn't been created yet, rather than raising FileNotFoundError from `open()`.

## Deviations from Plan

None.

The plan's code block suggested `'text/turtle'` strings in the `bulk_load` calls. Implementation used `RdfFormat.TURTLE` from the start based on the 01-04 SUMMARY's documented DeprecationWarning auto-fix — same underlying pyoxigraph 0.5.7 behavior, so the proactive application is consistent with a prior-wave established precedent, not a plan deviation. The acceptance criteria lists pass exactly as specified; no plan divergence.

## Threat-Model Compliance (this plan's `<threat_model>`)

| Threat ID | Mitigation Status | Evidence |
|-----------|-------------------|----------|
| T-01-05-01 (Tampering — `--auto`/`--yes` flag smuggled in) | ✅ mitigated | `test_no_auto_apply_path` enumerates forbidden names; PyCliRunner inspection of `review.params` |
| T-01-05-02 (Tampering — silent default-accept via prompt timeout) | ✅ mitigated | `Prompt.ask(choices=[...])` has no `default=` on decision/kind/confirm; `test_review_invalid_choice_reprompts` verifies re-prompt |
| T-01-05-03 (Information Disclosure — reviewer DID in JSONL) | ✅ accepted | Intentional per D-3 schema (provenance); DID is pseudonymous ed25519 |
| T-01-05-04 (Tampering — `--dispositions-path` writes outside project) | ✅ accepted | Single-maintainer spike; Phase 15 will add root-confinement |
| T-01-05-05 (DoS — oversized rationale/prime_analogate) | ✅ accepted | `rich.prompt` reads one line; bounded by terminal input buffer |
| T-01-05-06 (Repudiation — reviewer denies a recorded disposition) | ✅ mitigated | Every record carries `reviewer_did` + `reviewed_at_iso` + `detector_verdict` snapshot; JSONL append-only (01-02 guarantee) |
| T-01-05-07 (EoP — malicious fixture TTL triggers SERVICE via bulk_load) | ✅ mitigated | `PyoxigraphStore.query_rdf12` SEC-01 preflight covers query path; `bulk_load` is data ingest (no SERVICE exec); fixtures are maintainer-curated |
| T-01-05-08 (Tampering — ForkProposal `model_construct` bypass) | ✅ mitigated | CLI constructs via `ForkProposal(...)` (validator fires); `validate_fork_proposal_shape()` called as defense-in-depth before TTL render |

No `threat_flag` annotations emerged beyond the register.

## Success Criteria Verification

- [x] All tasks in 01-05-PLAN.md executed (2 tasks — RED + combined GREEN)
- [x] Each task committed individually (`--no-verify`): 518fc42 (RED), da7ef70 (GREEN)
- [x] `folio-insights polysemy review` is a Click subgroup — NO `--auto`, `--yes`, `--batch`, or `--accept-all` flag anywhere (PRINCIPLE-06): verified by `test_no_auto_apply_path` + `folio-insights polysemy review --help` inspection
- [x] `pytest tests/polysemy/test_cli_review.py` passes (Wave-0 xfails flipped to 10 real passing tests)
- [x] Subgroup registered in `src/folio_insights/cli.py` at the bottom via `from folio_insights.polysemy.cli import polysemy as _polysemy_group; cli.add_command(_polysemy_group)` (mirrors bench L528-530)
- [x] `modify` path calls `validate_fork_proposal_shape()` (Pitfall 5 enforcement) before writing disposition — verified in `src/folio_insights/polysemy/cli.py` line 214
- [x] CliRunner tests drive accept/reject/modify via scripted stdin (Pitfall 4 — every prompt has an explicit input line with trailing `\n`): see `_invoke_review` helper
- [x] No `folio-insights polysemy apply` or similar auto-apply command exists — `folio-insights polysemy --help` lists only `{detect, review, audit}`
- [x] Single `--llm-provider` flag on both `detect` and `review`; no `--llm-model` anywhere (OQ-5 W1)

## Next Phase Readiness

- **Plan 01-06 (FP audit, Wave 4) can now:**
  - Seed `dispositions.jsonl` by running `folio-insights polysemy review` end-to-end (or by constructing records directly via 01-02's `append_disposition`)
  - Stream records via `read_dispositions(path)` and compute false-positive rate per the FP-audit harness
  - Sweep threshold values via `detect_polysemy(..., threshold_override=)` (01-03 kwarg) on the same 20-shard fixture the CLI uses
- **Phase 15 polysemy-fork UI (downstream phase):**
  - Binds to `schema_version="1"` on `DispositionRecord` (01-02 canonical shape exercised by every record this CLI writes)
  - Can render the discriminated-union `detector_verdict` by dispatching on `verdict["kind"] in {"rule", "llm"}`
  - Will replace the CLI's text-based review with a rich UI but MUST preserve PRINCIPLE-06: no auto-apply, every disposition requires a user action. The CLI's test suite (particularly `test_no_auto_apply_path` and `test_review_invalid_choice_reprompts`) is a template for Phase 15's UI-layer tests.
- **Phase 9.P6 (polysemy gate, downstream phase):**
  - Scales this CLI's keystroke-gate pattern to the production fork-review workflow
  - Inherits the DispositionRecord schema + dispositions.jsonl append-only append_disposition contract

**Blockers for downstream:** None.

## Self-Check

- [x] `src/folio_insights/polysemy/cli.py` exists; contains `@click.group("polysemy")` and three `@polysemy.command(...)` decorators (detect, review, audit)
- [x] `src/folio_insights/polysemy/__init__.py` re-exports `polysemy_cli_group`
- [x] `src/folio_insights/cli.py` imports and registers the subgroup at module-bottom
- [x] `folio-insights polysemy --help` shows `{detect, review, audit}` subcommands (verified via live CLI run)
- [x] `folio-insights polysemy review --help` shows NO `--auto`, `--yes`, `--batch`, `--accept-all`, `--no-prompt`, `--force`, or `--llm-model` (verified by parameter inspection — only `--fixtures`, `--term`, `--dispositions-path`, `--llm-provider`)
- [x] `folio-insights polysemy detect --help` shows exactly one `--llm-provider` (no `--llm-model`)
- [x] `grep -nE "@click.option\([^)]*(--auto|--yes|--batch|--accept-all|--force|--no-prompt)" src/folio_insights/polysemy/cli.py` returns empty
- [x] `grep -n "build_prototype_cluster(term=" src/folio_insights/polysemy/cli.py` returns empty (B5 positional-only guard)
- [x] `grep -n "llm_model" src/folio_insights/polysemy/cli.py` returns empty (OQ-5 single-flag)
- [x] `pytest tests/polysemy/test_cli_review.py -v --timeout=30` → 10 passed
- [x] Full polysemy suite: `pytest tests/polysemy/ --timeout=60` → 37 passed / 3 xfailed (3 remaining xfails all in test_fp_rate.py, owned by Plan 01-06)
- [x] No `folio-insights polysemy apply` subcommand exists (`folio-insights polysemy --help` lists only detect/review/audit)
- [x] Commit 518fc42 (Task 2 RED) present in git log
- [x] Commit da7ef70 (Task 1 + Task 2 GREEN) present in git log
- [x] No modifications to `src/folio_insights/polysemy/{dispositions,distinguo,detector,prototype_cluster,similarity_query,reviewer,fixture_loader,whitelists}.py` (all owned by prior-wave plans)
- [x] No modifications to STATE.md or ROADMAP.md (parallel-executor discipline; orchestrator owns those)

## Self-Check: PASSED

All acceptance criteria satisfied on disk + in git log + in pytest: 10 CLI tests green, full polysemy suite at 37 passed / 3 xfailed (down from 11 xfails — 10 Wave-0 CLI xfails flipped, 1 xfail in test_reviewer_did owned by earlier wave already flipped in 01-02). PRINCIPLE-06 mechanically enforced at three layers (module docstring, CliRunner test `test_no_auto_apply_path`, Click option absence); OQ-5 W1 single-flag enforced; canonical DispositionRecord shape exercised by every test path.

---
*Phase: 01-polysemy-distinguo-spike*
*Completed: 2026-04-24*
