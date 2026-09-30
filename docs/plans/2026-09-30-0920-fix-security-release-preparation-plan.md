---
title: Security Release and History Scrub Preparation - Plan
type: fix
date: 2026-09-30
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Security Release and History Scrub Preparation - Plan

## Goal Capsule

- Objective: Deliver the confined-source fix and book removal without publishing contaminated data or restarting the vulnerable image.
- Authority: U12 authorizes local preparation only. Existing publication authorization belongs to the orchestrator; no renewed routine approval is needed.
- Stop conditions: Failed current-head checks, unknown scrub scope, unverified backup or unsafe rollback image blocks its dependent release step.
- Delivery: Security changes belong on default `master` independently of the migration documentation. The orchestrator cherry-picks the focused security commit; this worker does not rebase or publish.

## Product Contract

### Summary

Close the confirmed upload traversal gap, verify the existing source confinement, and prepare the remaining merge/scrub/deploy gates with truthful evidence.

### Problem Frame

The September 27 handoff calls PR #2 merge-ready but also reports digest drift, a bridge import failure and unavailable source panels for external CLI inputs. The local checkout cannot establish remote delivery. Its Gate-5 test publishes images despite a comment describing it as offline.

### Requirements

- R1. Source reads remain confined to the output root and uploads cannot escape their sources directory via path components or existing symlinks.
- R2. Release proof covers the current PR head and image, including tree/content inventory; absence of known book paths alone is insufficient.
- R3. History scrub requires exact authorized refs/paths, a verified readable backup and a rehearsed restoration procedure.
- R4. Redeploy only a validated patched image; rollback uses a separately verified safe image or leaves the app stopped.

## Planning Contract

- KTD1. Use component-aware resolved-path containment for ZIP members and direct upload destinations; direct upload filenames must be basenames. Governs R1.
- KTD2. Run synthetic offline ASGI tests and the bundled-corpus guard. Gate 5 remains outside this lane because `ci.build._build_image` calls `container.publish`, and `_load_digests` reads env files. Governs R2.
- KTD3. Treat local refs as stale evidence until the orchestrator fetches and validates PR #2. Do not infer a completed merge, scrub or deployment from source commits. Governs R2–R4.

## Implementation Units

### U1. Close and verify upload/source containment

- Requirements: R1. Dependencies: none. Files: `api/routes/upload.py`, `tests/test_upload_api.py`, `tests/test_source_confinement_async.py`.
- Approach: KTD1; retain the source API boundary already on the migration branch.
- Test scenarios: ZIP sibling-prefix escape, ordinary traversal, direct path-style filenames, symlink overwrite, source absolute/sibling/symlink escape, and a valid source span. Existing nested ZIP extraction remains supported.
- Local evidence: five new upload regressions failed before the fix. Upload, source ASGI and build-guard suites pass together: 23 tests.

### U2. Revalidate release blockers at the current head

- Requirements: R2. Dependencies: U1. Files: `ci/build.py`, Dockerfiles, bridge integration and ingestion/source code.
- Approach: Orchestrator obtains PR #2 head, reviews and required-check results; integrate U1 and rerun checks. Keep these unresolved gates explicit:
  - Gate-5 digest drift remains unverified. `Dockerfile.web` uses `uv:latest`, mutable apt repositories and non-hash-locked runtime installation; these are investigation leads, not a proven complete root cause. Build/publish only after corpus inventory and safe staging approval in the authorized lane.
  - Bridge integration was rerun offline and fails with `ModuleNotFoundError: folio_propositions` from sibling `app/models/job.py:7`. It must pass against the actual pinned sibling/runtime package set. Do not solve an import failure by quietly changing the sibling checkout or reading its configuration.
  - External CLI source panels remain unavailable: ingestion records absolute original paths outside the output root, which source confinement intentionally refuses. Resolve availability through a reviewed corpus-local normalized-source snapshot and reference migration, preserving original provenance and span offsets. Do not broaden the source allowlist. Existing corpora require explicit import/mapping; never copy historical book material as a fixture. This remains a release acceptance gap until synthetic CLI-to-viewer coverage passes.
  - Known book/manuscript path metadata is absent from the current tracked tree. Default/demo still bundle five tracked artifacts; their content provenance and the actual image inventory must be independently verified before publication. No image was built or inspected in U12.
- Verification: Current-head required checks, source/import regression, bridge test and two reproducible builds pass; retain exact image digest and clean inventory evidence.

### U3. Perform authorized delivery and record receipts

- Requirements: R2–R4. Dependencies: U2 and verified backup/scope.
- Approach: Orchestrator inspects `gh pr view 2 --repo alea-institute/folio-insights --json headRefOid,mergeStateStatus,reviewDecision,statusCheckRollup`, then merges only the validated current head using repository protections. Fetch and inventory affected refs before rewrite. Verify the reported mirror and rehearsal rather than repeating a completed purge; determine exact authorized manuscript paths and ref coverage before `git filter-repo --invert-paths`. Force-push only explicitly approved refs with leases bound to verified pre-rewrite tips. Tags, backup refs and archive refs require scope reconciliation; GitHub-owned PR refs require GitHub Support.
- Deployment: Use the authorized Coolify lane with the verified patched digest. Verify `/health` returns 200, `/api/v1/source?file=/etc/hostname` returns `found: false`, and `/api/v1/corpora` has no `test1`. Capture current image identity and final inventory. Never start the known-vulnerable old image.
- Verification: Record actual merge SHA, rewrite ref map, backup reference, clean-image digest, safe rollback reference and completion evidence. None is invented here.

## Verification Contract

Local command: run `python -m pytest tests/test_upload_api.py tests/test_source_confinement_async.py tests/test_ci_bundled_corpora.py -q` in an environment with dotenv and network access disabled and a disposable test root. `git diff --check` must pass. Gate 5, remote refs, PR checks, image inspection and health endpoints are orchestrator-only checks in this lane.

## Definition of Done

U1's local tests pass; U2/U3 remain release prerequisites until their evidence exists. Ordinary code rollback reverts the integrated commit. History rollback uses a verified pre-rewrite mirror and explicit ref restoration, not `git revert`, and must not republish book data. Deployment rollback uses a known-safe image; without one, leave the service stopped. No secrets or source prose enter receipts.
