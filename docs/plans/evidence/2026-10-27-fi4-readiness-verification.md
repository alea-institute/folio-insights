# fi-4 pipeline readiness verification

Plan: `docs/plans/2026-10-27-2212-feat-fi4-pipeline-readiness-plan.md`.
Branch: `drawdown/fi-4`. Kind: expansion. Scope: U1-U4 only.

## Delivered behavior

`folio-insights readiness` inspects explicitly selected extraction JSON,
disposition JSONL and optional labeled-set JSON. Text and JSON expose the same
fixed aggregate fields. Missing values remain unknown, fractions name emitted
units as their denominator, and full-source coverage remains unknown.

Saved dispositions use the existing R9 calculation after complete log and case
pairing checks. The report identifies recorded evidence and self-asserted
certification; it does not evaluate the current detector or combine separate
artifacts into a pipeline pass. Input errors preserve independently usable
sections. Output contains no source content, identifiers, paths or raw errors.

The command does not open referenced sources, initialize pipeline state, load
settings or credentials, execute models/providers, or make network requests.
A guarded fresh-process test exercises the root CLI and verifies exactly one
open per selected artifact, unchanged evidence bytes/mtimes/directory entries,
and no application writes.

## Starting state and environment

The build started clean at plan commit `0b5f3d2`, with implementation base
`99c3f6d`. No repository AGENTS.md or CLAUDE.md was present. Current formatter,
disposition, labeled-set and gate contracts matched the plan. The chief
campaign plan and common mandate were unavailable in this clone; the authority
limitation recorded in the plan remains for controller reconciliation.

The initial dependency cache was empty. Dependencies were restored from the
existing lock without changing dependency files. The first environment omitted
Torch and CUDA packages; its baseline failures all traced to missing Torch.
Installing CPU Torch `2.11.0+cpu` and caching the public
`sentence-transformers/all-MiniLM-L6-v2` model anonymously allowed the
model-dependent focused checks to pass offline. No provider keys were used.

## Verification

| Check | Result |
|---|---|
| Initial focused regression baseline | 72 passed, 1 failed, 3 errors; all failures/errors required missing Torch. |
| Initial quick baseline, excluding the new readiness tests | 4,162 passed, 159 skipped, 20 failed, 3 errors, 38 deselected; all failures/errors traced to missing Torch. |
| Final focused selection at `c8f14c7` | 150 passed, including 69 readiness tests. |
| Full quick suite at `c8f14c7` | 4,257 passed, 156 skipped, 38 deselected; one existing Pydantic serializer warning. Duration: 1,004.06 seconds. |
| Independent review-fix recheck | 7 passed for path failures and sanitized usage errors. |
| New report, CLI adapter and readiness test lint | Passed. |
| Project-wide Ruff | 64 pre-existing findings. The five findings in the changed root CLI match the base revision exactly; all other findings are in unchanged files. No configured typecheck was found. |
| Browser scope | No affected web route or frontend change; screenshot not applicable. |

Focused command:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m pytest -q \
  tests/readiness tests/test_cli.py tests/test_output.py \
  tests/polysemy/test_fp_gate.py tests/polysemy/test_dispositions_jsonl.py \
  tests/polysemy/test_labeled_set.py tests/polysemy/test_review_fixes.py \
  tests/polysemy/test_no_auto_apply.py
```

Quick-suite command:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m pytest -q \
  -m 'not gate5 and not slow and not integration' --durations=15
```

Proof before implementation: extraction tests failed before the adapter existed;
19 R9 tests failed before disposition options existed; 11 CLI tests failed before
registration. Boundary tests then characterized the read-only and privacy
contracts. Full collection exposed a duplicate `test_cli` module name; adding
`tests/readiness/__init__.py` resolved it without changing existing tests.

## Review and correction

Five simplification lenses completed without a required code change. The
optional registration-comment deletion was declined to retain the surrounding
CLI convention. All proof tests were retained.

Eight review lenses covered correctness, testing, maintainability, security,
reliability, API contract, adversarial cases and repository learnings. They
retained one P2 finding: Click's default path readability check returned a usage
error before the artifact reader could render the remaining usable sections.
Security and adversarial reviewers independently reproduced it, and a separate
validator confirmed it. Cross-model review was disabled by checkout
configuration; this receipt does not claim the controller's Astra/Fable reviews.

Commit `c8f14c7` replaces filesystem-checking Click path types with `Path`
conversion for all three artifact options. An entry-point regression failed with
exit 2 before the fix and passes with exit 1 afterward, retaining extraction
coverage and a fixed unreadable-input diagnostic. The review owner rechecked the
fix and confirmed it. No actionable review findings remain.

## Public-safe and scope checks

`check_exclusions.py --history 99c3f6d --json` reports zero strong tree findings
and 17 distinct inherited prose patterns from pre-existing synthetic examples
in `README.md`. Every `(rule, detail digest)` pair matches the base README; no
new pattern was introduced. Each changed README blob repeats those historical
findings, including the navigation-link update. The historical scan evaluates whole modified blobs,
which accounts for its nonzero result. The book-overlap check was not run because
no source book was supplied.

Existing tests, the review viewer, detector rules, signing stack, manifests and
dependency files were unchanged. No migration, data rewrite, release or outside
service was added. Publication and campaign merge checks belong to the
controller; this clone has no remote and all commits remain local.
