---
status: partial
phase: 07-governance-model-3-1
source: [07-VERIFICATION.md]
started: 2026-05-30T23:50:00Z
updated: 2026-05-30T23:50:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Interactive retraction flow (D-17 default mode)
expected: Running `folio-insights governance retract <iri>` (without --preview or --apply) prints a grouped table of dependents classified as {auto_rederive, aporetic, review_needed} and prompts `Confirm retraction of N shards? [y/N]` before committing to the log. Pressing `n` exits 0 without committing; pressing `y` appends a `RetractionEvent` to the governance log.
result: [pending]

### 2. did:key end-to-end sign→verify round-trip (CR-01 acceptability)
expected: A governance CLI command (e.g. `governance role-assert`) completes successfully with a real did:key keypair on disk: `sign_attestation` + `verify_attestation` both agree, and the event appends cleanly to the log. Exit code 0; the appended event passes `verify_attestation` when re-read from the log.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
