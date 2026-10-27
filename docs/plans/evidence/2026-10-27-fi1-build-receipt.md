# fi-1 build receipt

Plan: `docs/plans/2026-10-27-0848-feat-fi1-corpus-trust-completion-plan.md`

Branch: `drawdown/fi-1`

Source base: `c2f3fa9`

Kind: planned

Reviewed implementation: `b60cc36` plus the simplification working diff

Review fixes: `3901583`; remaining simplification persisted in `a2bb673`

## Delivered

- Corpus-selected signature requirements, including direct proposal stores and all review/discovery routes; configured enforcement cannot be relaxed by an injected policy.
- Registered signatures for exact polysemy dispositions and reviewed-sample certificates, historical verification, locked nonce/retry handling and detached CLI preparation/submission.
- Signed administrator closure declarations in the existing ledger, bound to a main-journal prefix and a signed operation ID. The derived graph recovers across reopen/rebuild/restore; counts capture contracts, membership and facts together.
- Persisted P5 roll-up evidence and actual CORPUS-04 cluster-validator execution with explicit coverage, failure and unavailable statuses.

No viewer change, migration, authoritative data rewrite, vocabulary/package release, new service or deployed security-setting change. No real reviewer enrollment or certification. Synthetic validation does not establish real CORPUS-04 acceptance or pass the separate R9 quality gate.

## Verification

Completed test results below predate the five final review fixes. They establish the earlier implementation evidence, not a passing result for the final branch.

Commands below use `PYTHONPATH=src .venv/bin/python -m pytest` with isolated temporary directories. Counts are per run and overlap; they are not a combined suite total. Dependencies were installed with `uv sync --frozen --extra dev --python 3.12`; manifests and lockfiles are unchanged.

| Scope / pytest arguments | Completed evidence |
|---|---|
| `tests/proposals tests/test_signed_decisions_api.py tests/api -q` | Initial run: 582 passed, 117 skipped, 13 discovery-route failures. Corrected corpus propagation; all 38 tests in the affected API suite then passed. 595 unique passing tests across the two runs. |
| `tests/polysemy tests/proposals/test_signed_decisions.py -q` | 251 passed. |
| `tests/query tests/frameworks -q` | 103 passed. |
| `tests/bench/test_phase9_closure.py tests/storage/test_closure_projection.py -q` | 22 passed in 5.01 seconds before the final behavior-preserving simplification. Covers persisted/reopened P5, recovery, replacement, interleaving, isolation, exports and unchanged signed bytes. |
| `tests/bench/test_corpus04_harness.py tests/bench/test_corpus04_cluster_validation.py -q` | 20 passed with the actual validator and injected local backends. |
| Fresh-process query and atomic-projection checks | Query: 38 passed; atomic projection: 29 passed; corpus isolation: 1 passed. |

Starting-state failures were observed before implementation: corpus policy 16 failed/1 passed; three polysemy authority-boundary failures; missing closure module, followed by two raw-ledger integrity failures; absent persisted closure membership; CORPUS-04 18 failed/2 passed. The six fi-1 test files present when this build began retain their original bytes. Existing positive polysemy fixtures gained generated signatures without removing their assertions.

## Limits and remaining gate checks

The complete regression command `-m 'not gate5 and not slow' -q --maxfail=1` and broader storage runs were attempted but did not complete. Tests stalled in existing RocksDB bulk-load/update/flush and TBox-loading paths; process inspection also observed sandbox memory throttling. Fresh-process attempts did not eliminate the limitation: bulk-load and competing-writer files timed out, and the existing crash-process test exceeded its 25-second subprocess limit. Later retries of previously passing new closure tests also stalled before completing. An isolated confirmation using the archived starting source also exceeded the unchanged 30-second timeout while constructing the existing bulk-load fixtures (1 setup error in 31 seconds). These attempts are not passes, and the full regression suite is not green evidence.

No test was deleted, newly skipped, weakened or given a longer configured timeout to accommodate this environment. The controller must rerun the incomplete suites in a provisioned environment before the campaign merge gate accepts them. Real benchmark inputs and actual human certification remain the plan's separate, deferred acceptance inputs.

The full roll-up/validation command `tests/bench/test_phase9_rollup.py tests/validation -q --maxfail=1` was also attempted: two generator checks completed, but the integration run did not finish within its bounded run. Later validation files were not reached. The focused persisted P5 test above remains separate evidence, not a substitute claim that all seven principles passed together.

## Review and final checks

Simplification completed all five review lenses. Export graph selection now reuses `corpus_graphs`; unchanged closure projections avoid allocating a membership list. Signing-policy documentation was corrected. No tests changed during simplification. Production-file Ruff passed before the final review fixes. The post-fix Ruff process could not finish under the same sandbox resource pressure, so final lint status is unverified. Repository-wide Ruff reports 77 issues unchanged by simplification; the only one in this branch's changed files is an unused fixture import in a protected starting test. No typechecker is configured.

The full review completed nine lenses and independent finding validation. It returned five confirmed findings, all addressed in `3901583`:

| Finding | Change | Added regression coverage |
|---|---|---|
| A formally checked cluster could mask skipped textual consistency checks. | Require measured NLI execution for every eligible cluster; capped or disabled screening is incomplete. | `tests/bench/test_corpus04_text_coverage.py` |
| Signed fork approval omitted emitted metadata. | Bind the complete fork digest, including grouping, labels, framework, jurisdiction and provenance; legacy records lacking this binding cannot release a fork. | `tests/polysemy/test_complete_fork_binding.py` |
| A clock rollback could admit a declaration that replay immediately rejected. | Floor the ledger commit timestamp against the captured main prefix before authorization and append. | `tests/storage/test_closure_review_regressions.py` |
| Repeated reads rebuilt historical membership for unchanged prefixes. | Cache verified declarations by both complete prefixes, checking main and ledger integrity before reuse and clearing on lifecycle changes. | `tests/storage/test_closure_review_regressions.py` |
| Nightly dumps omitted closure membership. | Include the optional closure graph and persist its empty state after invalidation. | `tests/storage/test_closure_review_regressions.py` |

A bounded source follow-up confirmed all five fixes and found no new defect. The three new files add 13 cases. Their initial red attempt produced no result before its 60-second bound. The final focused run below also produced no result before its 90-second bound; these are unverified tests, not passes:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \
  timeout 90s .venv/bin/python -m pytest -p pytest_asyncio.plugin -p pytest_timeout \
  tests/polysemy/test_complete_fork_binding.py \
  tests/bench/test_corpus04_text_coverage.py \
  tests/storage/test_closure_review_regressions.py \
  tests/polysemy/test_signed_dispositions.py \
  tests/query/test_closure_integrity.py \
  tests/storage/test_closure_projection.py -x -q
```

Syntax compilation of changed Python files passed after the fixes. No configured per-test timeout was lengthened and no existing test assertion was changed for the review fixes. The controller must run these focused checks, final lint, the plan's affected suites and full regression gate before merge. Local review does not replace the campaign's Astra and Fable reviews.

The browser-test skill ran in pipeline mode through scope mapping: zero changed rendered routes, zero pages exercised, result **Skip — backend/library/CLI changes only; viewer unchanged**. No server or browser was started and no screenshot is required. No additional learning document was created because the reasoning is carried by this receipt, the plan, code and regression tests.

`git diff --check`, the six starting-test hash checks and the public-safe diff inspection passed. The net diff leaves parked milestone continuity metadata unchanged; automatic checkpoint copies remain in Git history. The viewer is unchanged; browser testing and a screenshot do not apply to this backend-only scope. The configured remote list is empty. Work is committed locally for controller publication; no push, PR, credential discovery or deployment was attempted.
