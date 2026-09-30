# U12 execution — folio-insights — 2026-09-30

Branch: `chore/u12-exec-20260930`. Base: `refactor/v2-gsd-to-ce-migration`; locally `origin/master` is 0 ahead / 15 behind that base. No fetch, push, branch creation/switch, merge, history rewrite, deployment, installation or send occurred. Existing untracked `agents/tasks/u12-exec-20260930.md` is preserved and not committed.

The review packet was read fully. Its older needs-Damien classification is superseded only by the supplied dated answer: confirm R18 as drafted, plan Phase 13 next, governance after Phase 13. Per the task contract, older ON SHEET cards are skipped individually; the confirmed combined card owns the local work. No decision-sheet state or other repository was modified.

| Title | Outcome | Commits | Verification (command + result) | Exact next step |
| --- | --- | --- | --- | --- |
| Ship security fix, book removal and v2.0 archive branch | NEEDS-NETWORK | `3f0643a` | T1: 23 passed; T2: missing `folio_propositions`; `git diff --check`: pass | Orchestrator resolves bridge/source-panel/digest gates, validates current PR #2 head, then merges, verifies backup and scrub scope, rewrites authorized refs and redeploys a verified clean image. |
| Record v2.0 R18 disposition — older ON SHEET card | SKIPPED | — | `git show 20eb997 --stat`: local confirmation exists under combined card | Reconcile this duplicate card through its owner; do not repeat the confirmation ask. |
| Candidate Phase 13 storage — older ON SHEET card | SKIPPED | — | `git show 3fddaab --stat`: plan exists under combined card | Reconcile the card; implementation follows separately dispatched U17 and storage canary. |
| Candidate proposed-class governance — older ON SHEET card | SKIPPED | — | `git show 72dd26b --stat`: plan exists under combined card | Reconcile the card; implementation follows completed Phase 13 on an orchestrator-prepared clean base. |
| Candidate shard-envelope migration U17 — ON SHEET | SKIPPED | — | `rg -n 'U17' docs/plans/2026-09-30-0913-feat-phase13-storage-plan.md`: prerequisite explicitly sized | Owner supplies U17 scope dispatch; migrate accepted/revised R18 boundaries before persistent schema implementation. |
| Candidates Phases 9–12, 13.5, 14–20 — Later | SKIPPED | — | Migration-plan U7–U13 retain explicit scope gates; no blanket authorization found in supplied answer | Keep Later; owner selects individual scope. Phase 10 needs re-planning, 14/15 re-scoping, 20 Coolify retargeting. |
| Confirm R18, then plan Phase 13, then governance — dated answer | DONE-LOCAL | `20eb997`, `3fddaab`, `72dd26b` | D1: ten R18 groups, PRD pointer and CE structure pass; CE review: two corrections applied, none retained | Orchestrator synchronizes upstream R18 record, integrates these plans and dispatches prerequisites in order. Storage/governance implementation is not claimed. |

## Integration placement

- `3f0643a` belongs on default `master` independently of the migration documentation. Cherry-pick/integrate its security patch and tests after current-head review; source containment itself was already present in base commit `c53dec4`. It also carries the local release-preparation plan and offline test harness. The worker did not rebase.
- `20eb997`, `3fddaab`, `72dd26b` follow the migration documentation base. R18's local record and PRD pointer can be integrated independently if needed, but the migration-plan edits and new plan links must remain coherent. Upstream `folio-propositions/docs/review-disposition-v2.0.md` remains untouched and locally still says DRAFT. The local record preserves all ten group dispositions and hashes the inspected source draft; it does not assert an upstream merge.
- This report is the final focused commit. Its own SHA is intentionally not self-embedded.

## Verification commands and output

Use the existing Python 3.12 dependency environment read-only, with `-B` to prevent writes there. The committed harness disables dotenv reading and blocks Python network connection/name-resolution events and recognizable prohibited credential paths. It is an additional guard, not an OS security boundary. Tests use synthetic fixtures and disposable directories. No credential files were intentionally opened or copied.

T1 (final security verification):

```bash
PYTHONDONTWRITEBYTECODE=1 '/home/damienriehl/Coding Projects/folio-insights/.venv/bin/python' -B agents/run-notes/u12-folio-offline-tests.py tests/test_upload_api.py tests/test_source_confinement_async.py tests/test_ci_bundled_corpora.py -q --disable-warnings --basetemp=/tmp/u12-folio-security-receipt
```

```text
.......................                                                  [100%]
23 passed in 0.76s
```

Before the fix, the five newly added upload cases all failed:

```text
FAILED test_zip_rejects_sibling_prefix_escape
FAILED test_upload_rejects_path_filenames[../escaped.txt]
FAILED test_upload_rejects_path_filenames[nested/escaped.txt]
FAILED test_upload_rejects_path_filenames[..\\escaped.txt]
FAILED test_upload_rejects_symlink_destination
5 failed, 9 passed in 0.89s
```

T2 (bridge revalidation; same harness was at `/tmp/u12-folio-offline-tests.py` for this run):

```bash
FOLIO_INSIGHTS_FOLIO_ENRICH_PATH='/home/damienriehl/Coding Projects/folio-enrich/backend' PYTHONDONTWRITEBYTECODE=1 '/home/damienriehl/Coding Projects/folio-insights/.venv/bin/python' -B agents/run-notes/u12-folio-offline-tests.py tests/test_bridge.py::test_normalizer_import -q --disable-warnings --basetemp=/tmp/u12-folio-bridge
```

```text
folio-enrich/backend/app/models/job.py:7:
    from folio_propositions import Proposition, migrate_record
E   ModuleNotFoundError: No module named 'folio_propositions'
1 failed in 0.16s
```

No package install or sibling modification was attempted. The normalizer failure remains a release gate, not a passing or nonblocking test.

D1: Python assertions checked both new feature plans for all six CE headings, unique U-IDs, `ce-unified-plan/v1`, and no bracketed placeholders. The R18 disposition table contains exactly ten rows and no recommended-state markers; the PRD starts with the confirmed-record pointer. `git diff --check` passed. No runtime tests were invented for documentation-only changes.

```text
Phase 13 plan: required sections, unique units, no placeholders PASS
Governance plan: required sections, unique units, no placeholders PASS
R18: ten confirmed groups and PRD pointer PASS
```

Verification limitations: an initial harness guard overmatched stdlib cookie module source names; narrowed to distinguish code from cookie data before successful runs. A combined run including synchronous `tests/test_review_api.py` did not complete with a test summary in this sandbox (output stopped after the upload cases). The successful source proof uses new async ASGI tests. There is no full-suite pass claim. Gate 1/2 storage benchmarks are future implementation prerequisites, not run during planning. Gate 5 was not run because its build path publishes to ttl.sh and reads env files.

## Review receipt

CE document review covered coherence, feasibility, scope, security and adversarial lenses on the two feature plans. Two grounded Phase 13 omissions were corrected: pre-journal PII rejection and nightly TTL dumps with local Git commits. The final plan also names all eight inherited export formats and rdflib's adapter-only boundary. Governance had no retained findings. Cross-model review and external research were skipped under the explicit no-network restriction; reused reviewer processes are not independent corroboration. Planning is complete locally, with U17/Phase 13/clean-base launch prerequisites still explicit.

## Release facts and exact remaining work

The old “merge-ready” label is not supported by this lane. See `docs/plans/2026-09-30-0920-fix-security-release-preparation-plan.md` for the bounded release sequence and rollback contract.

1. Revalidate PR #2 using `gh pr view 2 --repo alea-institute/folio-insights --json headRefOid,mergeStateStatus,reviewDecision,statusCheckRollup`; fetch current refs and verify protections. Integrate this patch, resolve the reproduced bridge failure, and prove source-panel availability safely for external CLI inputs. Do not widen source filesystem access to make the UI pass.
2. Diagnose web/worker reproducibility against the exact current head. Mutable `uv:latest`, apt inputs and unpinned runtime installs are source-level leads only. `ci.build._build_image` publishes before `_run_pipeline` finishes its tests; do not mistake the Gate-5 “offline” comment for a network-free check.
3. `git ls-files 'output/test1/**' '*Ch01*' '*ch01*'` returned no paths. This is only known-path tree evidence. Five default/demo tracked artifacts remain bundled; their content provenance and built image must still be inspected. No clean-image or history-purge receipt is claimed.
4. Before scrub, recover and verify the reported mirror backup, exact path list and ref scope. Do not infer that tag `v1.1`, backup refs, build refs or archive refs are all covered. Never rerun a completed purge just to create new evidence. The orchestrator owns any missing destructive-scope reconciliation and GitHub-owned PR-ref removal.
5. After checks pass, merge through protections, scrub only authorized refs with a verified restore procedure and lease-bound publication, then use the authorized Coolify lane for the validated image. Capture health/source/corpus checks, actual merge SHA, backup reference, rewrite ref map, image digest and safe rollback reference. Leave the vulnerable old image stopped.

Heartbeat writes initially hit the read-only sandbox and then succeeded through narrowly scoped escalation. Git commits likewise required escalation for this worktree's shared Git metadata, without modifying main-checkout files. Stop-name checks found no request files at safe boundaries. Final worker state is set to `review_ready` after this report's commit.
