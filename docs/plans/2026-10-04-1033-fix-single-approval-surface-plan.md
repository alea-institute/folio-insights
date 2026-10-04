---
title: Single Approval Surface for Proposed Classes - Plan
type: fix
date: 2026-10-04
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Single Approval Surface for Proposed Classes - Plan

## Goal Capsule

- Objective: Make the append-only proposal ledger (`ctx.proposals`) the only store of proposed-class decisions. The API route `POST /api/v1/proposed-classes/{label}/review` records through `ProposalStore.record_decisions`, the viewer-facing reads come from the ledger, and the `review.db` table `proposed_class_decisions` becomes read-only legacy with an explicit, idempotent import.
- Authority: the governance plan's follow-up "A second approval surface" (`docs/plans/2026-09-30-0914-feat-proposed-class-governance-plan.md`, Follow-ups), assigned by the orchestrator on 2026-10-04.
- Stop conditions: an existing API or governance test regresses; a decision can reach the ledger without the reviewer, status, unknown-ID and PII checks; the legacy table loses rows.
- Delivery: branch `fix/single-approval-surface` from `origin/master` `5a92df3`. No push from this worker; the orchestrator owns review and integration.

## Product Contract

### Problem Frame

Two surfaces record proposed-class approvals and they disagree:

- `api/routes/review.py` upserts `proposed_class_decisions` in the per-corpus `review.db`, keyed by label, with no reviewer identity, no PII gate and an in-place overwrite.
- The governance pipeline records decisions in the append-only proposal ledger, keyed by proposal ID, with a named `human:<handle>` reviewer, whole-batch validation, the PII gate and decision history. The approved-only backlog (`proposals/export.py`) reads only the ledger.

A decision made through the API therefore never reaches the backlog, and the two stores can hold different answers for one proposal.

### Requirements

- R1. The API write path records through `ProposalStore.record_decisions` with an explicit op_id, a `human:<handle>` `decided_by` from the configured reviewer (refused when none is configured), the same validation and the PII gate.
- R2. The route stays keyed by label. The label resolves to a proposal ID through the corpus registry; an unknown label is refused with a clear 4xx and nothing is written.
- R3. Reads of proposal decisions for the UI come from the ledger.
- R4. `proposed_class_decisions` is read-only legacy: no code path writes or deletes it, and the database refuses writes. An explicit, idempotent import copies its decided rows into the ledger as decisions by `human:legacy-review-db`, with the original timestamps in provenance. Nothing migrates on startup and the table is never dropped.
- R5. The API corpus ID maps to exactly one ledger corpus under one storage root, documented, and never to another corpus.

### Scope Boundaries

No viewer change (no viewer code calls this route today; `grep -rn proposed viewer/src` finds only unit-review stores). No authentication layer: the API has none, so the reviewer is server configuration. No signed decisions (still a follow-up). Unit review (`review_decisions`) and task review are untouched.

## Planning Contract

### Key Technical Decisions

- KTD1. **Reviewer identity is server configuration, never request input.** `api.main.configure(reviewer=...)`, else `$FOLIO_INSIGHTS_REVIEWER`. A bare handle becomes `human:<handle>`; the result must pass `validate_decided_by`. With none, or an invalid one, the write is refused with 403. The request body forbids extra fields, so a client cannot send `decided_by`. When an authentication layer lands, the reviewer comes from the authenticated principal. Governs R1.
- KTD2. **Explicit op_ids, two forms.** A client idempotency key (`op_id` in the body, `[A-Za-z0-9][A-Za-z0-9._:-]{0,99}`) becomes `api:review:key:<key>`, so a retry replays exactly and reuse for a different request is a 409. Without one, the server derives `api:review:auto:<digest>` over corpus, reviewer, decision and the current ledger head, the same rule as `apply_approvals.py`'s default: a retry before commit replays, and a repeat after the ledger moved is a no-op batch that keeps the original `decided_at`. Governs R1.
- KTD3. **Corpus mapping (conservative).** The ledger corpus is the API corpus ID verbatim (the `output/<corpus>/` directory name, the same name `judge_proposals.py --corpus` must use). It must match `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`, else 400. The storage root is `configure(corpus_root=...)`, else `$FOLIO_INSIGHTS_CORPUS_ROOT`, else `~/.folio-insights/corpora`, the CLI's resolution. The API never creates a storage root: with no `journal.sqlite3` the ledger reads as empty and every label is unknown. A root inside the served output directory is refused (503). Proposal IDs hash the corpus, so a mismatched name fails closed (404) and can never decide another corpus's proposal. Governs R5.
- KTD4. **Status mapping.** The route accepts every status `validate_decision` accepts (`approve`/`approved`, `reject`/`rejected`, `merge`/`merged` with `merge_into`, `needs_work`); the response reports the stored form, so the legacy `approved`/`rejected` contract is unchanged. Invalid status is 400 before storage is opened. Governs R1.
- KTD5. **Legacy provenance on decision items.** `record_decisions` gains an optional `provenance` map (per proposal ID; a few short scalar fields, validated). Items carry it only when given, so existing batches and op digests are unchanged. The fold carries it onto the decision record, the backlog row shows it, and `decision_core` ignores it. Governs R4.
- KTD6. **Legacy import rules.** Read `review.db` read-only. Per row of the corpus: `pending` rows are skipped; invalid rows (unknown status, over-long note) and labels that resolve to no proposal are reported by legacy row ID (never by label or note); several rows resolving to one proposal keep the latest `reviewed_at`; a row already imported (same row digest found in ledger provenance) is skipped; a proposal that already has a ledger decision is never overridden; a row that trips the PII gate is reported and skipped. The rest is one batch, op_id `legacy-review-db:<digest>`, `decided_by` `human:legacy-review-db`, provenance `{source, legacy_row_id, legacy_reviewed_at, legacy_row_digest}`. A second run imports nothing. Exposed as `apply_approvals.py import-legacy` with `--dry-run`. Governs R4.
- KTD7. **Read-only legacy table.** No code writes `proposed_class_decisions`; `/review/reset` no longer deletes it (and never touches the ledger, which is append-only). `BEFORE INSERT/UPDATE/DELETE` triggers that abort (`LEGACY_READ_ONLY_TRIGGERS_SQL`) are installed only in a review.db this code creates and by the explicit `import-legacy --seal`, never on an ordinary open, so read-only and tracked review.db files are never written by being opened (revised after review, P2-3). Governs R4.
- KTD8. **Access posture (added after review, P1).** The API has no authentication, so the proposed-class routes are off unless the operator sets `FOLIO_INSIGHTS_ALLOW_UNAUTHENTICATED_DECISIONS=1`, and even then answer only a loopback client whose `Host` is `localhost`/`127.0.0.1`/`::1` (DNS rebinding is refused). `serve()` defaults to `127.0.0.1`; containers bind `0.0.0.0` explicitly and their clients are not loopback. Reads use a read-only SQLite connection to the journal, never a storage context (P2-4).

## Implementation Units

### U1. Ledger provenance and legacy import

- Files: `src/folio_insights/proposals/decisions.py`, `store.py`, `registry.py`, `export.py`, new `src/folio_insights/proposals/legacy.py`, `src/folio_insights/persistence/review_db.py`, `scripts/apply_approvals.py`.
- Test scenarios: import keeps `reviewed_at` in provenance and is idempotent; pending/invalid/unresolved/other-corpus rows are reported and skipped; an existing ledger decision is not overridden; dry run writes nothing; the legacy table refuses writes after the schema runs.

### U2. API route through the ledger

- Files: new `api/services/proposals.py`, `api/routes/review.py`, `api/main.py`.
- Test scenarios: an API approval appears in the approved-only backlog; unknown label 404 with nothing written; invalid status 400, missing or invalid reviewer 403, `decided_by` in the body 422, all writing nothing; client op_id replay returns the original result and a conflicting reuse is 409; a repeat without op_id keeps `decided_at`; PII in the note is 422; GET reads come from the ledger; reset leaves legacy rows and the ledger alone.

### U3. Docs

- Files: `docs/storage-operations.md`, the governance plan's Follow-ups, this plan's Execution Evidence.

## Verification Contract

Focused: `pytest tests/proposals tests/storage tests/governance tests/test_review_api.py tests/test_task_review_api.py` plus the new API tests. Full: `-m "not gate5 and not slow" --benchmark-skip -p no:cacheprovider` (baseline 1522 passed). Ruff on changed files, `scripts/check_exclusions.py --history origin/master`, and `git status --short --ignored output data` clean. Every run sets `FOLIO_INSIGHTS_CORPUS_ROOT` to a temp directory; fixtures are synthetic.

## Definition of Done

One store of record for proposal decisions (the ledger); the API writes and reads it; the legacy table is read-only with a tested idempotent import; docs describe the mapping, the reviewer configuration and the import; the follow-up is marked done.

## Execution Evidence

- **Branch.** `fix/single-approval-surface` from `origin/master` `5a92df3`. Commits: plan `dd4f2bf`; U1 `8843060` (ledger provenance, read-only legacy table, `import-legacy`); U2 `5cd6019` (API through the ledger); U3 is the docs commit that follows.
- **Viewer.** No viewer code calls the proposed-class routes (`grep -rn proposed viewer/src` finds only unit-review stores), so no viewer change and no `npm run check`.
- **Tests (synthetic only, temp corpus roots).**
  - `tests/proposals/test_legacy_import.py` (14): import with original timestamps in provenance and into the backlog; idempotent second run (head unchanged); a ledger decision is never overridden; dry run writes nothing; the legacy file's bytes are unchanged; the table refuses INSERT, UPDATE and DELETE once the schema runs; the `import-legacy` CLI; bad provenance refused by `record_decisions` and ignored by the fold.
  - `tests/test_proposed_class_review_api.py` (25): an API decision appears in the approved-only backlog; unknown label 404, invalid status 400, missing or invalid reviewer 403, `decided_by` in the body 422, PII 422, bad corpus 400, each leaving the ledger head unchanged; client op_id replay and 409 on reuse; repeat without op_id keeps `decided_at`; reads come from the ledger; reset keeps legacy rows and ledger decisions; no storage root is created; a root inside served output is 503. With the pre-change `api/routes/review.py` restored, 21 of the 25 fail.
  - **Focused:** `tests/proposals tests/storage tests/governance` plus `test_review_api`, `test_task_review_api`, `test_proposed_class_review_api`, `test_discovery_api`, `test_discovery_persistence`, `test_export_api`: 581 passed.
  - **Full** (`-m "not gate5 and not slow" --benchmark-skip -p no:cacheprovider`): 1561 passed, 34 skipped, 18 deselected (baseline 1522; +39 new).
- **Ruff:** clean on every changed Python file.
- **Exclusion check:** `scripts/check_exclusions.py --history origin/master`: 0 tree findings, 0 history findings; 168 advisory shape findings, the same count as `--rev origin/master`.
- **Ignored output:** `git status --short --ignored output data` is empty.

### Review fixes (2026-10-04)

An independent review found one latent P1 and four P2s; each fix has a regression test that failed on the pre-fix code (27 tests: with `src/`, `api/` and `scripts/` at `6a6aacc` and the new tests' new-only imports stubbed, 25 failed, plus the 2 P2-3 tests once their fixture modelled a trigger-free pre-change file).

- **P1, a single env var armed anonymous "human" decisions.** Every proposed-class route now needs `FOLIO_INSIGHTS_ALLOW_UNAUTHENTICATED_DECISIONS=1` plus a loopback client and a loopback `Host` (rebinding refused); the 403 explains the risk instead of naming the variable; `api.main.serve` defaults to `127.0.0.1`; the GETs sit behind the same guard.
- **P2-1, import race.** `record_decisions(expected_head=...)` (default `None`, unchanged behaviour); the import passes the head it evaluated at, retries once from a fresh load on `JournalStateChanged`, then raises `LegacyImportConflict`.
- **P2-2, reversed legacy decisions.** Every row of the corpus is grouped by resolved proposal before anything else; when the latest row is pending, invalid, unorderable or PII-refused, the whole proposal is skipped and the older rows are reported as superseded.
- **P2-3, read-only pre-change review.db.** The triggers left `SCHEMA_SQL` (now identical to `origin/master`); they go into new review.db files and through `import-legacy --seal` only. Opening an existing review.db leaves its bytes unchanged.
- **P2-4, GET churn.** The GETs fold the ledger from `read_ledger_entries_readonly` (a `mode=ro` SQLite connection) and never open the projection.
- **Nits.** KTD2 text fixed; `configure(reviewer=None)` / `configure(corpus_root=None)` clear; any storage-open failure (not only `StorageError`) and an unreadable ledger are 503.

## Follow-ups

- **Authentication for the review API.** The proposed-class routes are local-only behind an explicit opt-in because the API has no authentication. Real authentication, with `decided_by` taken from the authenticated principal (and ideally signed decisions), would let them serve remote reviewers.
