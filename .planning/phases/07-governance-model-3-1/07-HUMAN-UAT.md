---
status: passed
phase: 07-governance-model-3-1
source: [07-VERIFICATION.md]
started: 2026-05-30T23:50:00Z
updated: 2026-05-31T15:25:00Z
verified_by: programmatic (Click CliRunner + InMemoryShardStore monkey-patch via tests/governance/fixtures/cascade_corpora.py)
---

## Current Test

[both tests passed]

## Tests

### 1. Interactive retraction flow (D-17 default mode)
expected: Running `folio-insights governance retract <iri>` (without --preview or --apply) prints a grouped table of dependents classified as {auto_rederive, aporetic, review_needed} and prompts `Confirm retraction of N shards? [y/N]` before committing to the log. Pressing `n` exits 0 without committing; pressing `y` appends a `RetractionEvent` to the governance log.
result: passed

evidence:
- Seeded `seed_cascade_corpus(superseded=True)` from `tests/governance/fixtures/cascade_corpora.py` → 6 shards (1 retraction target + 2 auto_rederive + 1 aporetic + 2 review_needed dependents).
- TEST A (input='n'): rich.table.Table rendered with 3 columns named exactly `auto_rederive`, `aporetic`, `review_needed`; dependents `fi:shard:auto-1`/`auto-2` in column 1, `fi:shard:aporetic-1` in column 2, `fi:shard:review-1`/`review-2` in column 3. Prompt text: `Confirm retraction of 5 shards (auto_rederive: 2, aporetic: 1, review_needed: 2)? [y/N]:` — matches spec verbatim. On `n`: stderr `retraction aborted (operator did not confirm).`, exit 0, log shows 1 row (genesis only), 0 RetractionEvents.
- TEST B (input='y'): same table + prompt. On `y`: JSON of persisted event echoed with `action: "retract"`, `position: 1`, `cascade_preview_hash: 30ff7505...`, valid `signature` block. Log shows 2 rows. `verify_attestation` re-verifies the RetractionEvent signature OK. CR-04 invariant holds: `"position"` not in `signature_payload`.

### 2. did:key end-to-end sign→verify round-trip (CR-01 acceptability)
expected: A governance CLI command (e.g. `governance role-assert`) completes successfully with a real did:key keypair on disk: `sign_attestation` + `verify_attestation` both agree, and the event appends cleanly to the log. Exit code 0; the appended event passes `verify_attestation` when re-read from the log.
result: passed

evidence:
- Generated two did:key keypairs on disk via `folio-insights did generate`:
  - admin: `did:key:z6Mkh2gPRuVjbgYfkL6Dyhj5zmkJudYBEx4ZxJc87VSEiooz`
  - contributor: `did:key:z6MkvTAWA65KZZgiHfvSP8nk8Sv9df6hPue8inBaY1A2Ujga`
- `corpus init uat-corpus --admin-did <admin> --key-path <admin.jwk>` → exit 0, JSON output with `position: 0`, `role: "corpus_admin"`, `action: "role_assertion"`, `subject_did == signature.did == admin` (self-signed genesis row per D-10).
- `governance assert-role <contrib> --role reviewer --corpus uat-corpus --key-path <admin.jwk> --yes` → exit 0, JSON output with `position: 1`, `role: "reviewer"`, `action: "role_assertion"`, `subject_did = contrib`, `signature.did = admin` (admin signing for contributor — non-genesis path through CR-01 `_signing.sign_and_verify_event`).
- Independent re-verification with a fresh `InMemoryDidDocCache`: both rows pass `verify_attestation`.
- CR-04: `signature_payload()` on both events does not contain `"position"`.
- D-11: `governance revoke-role <admin> --revoked-role corpus_admin --corpus uat-corpus --yes` exits 1 with stderr `revocation would leave the corpus with 0 active corpus_admins; appoint a successor first`. Log unchanged after the refusal (still 2 rows).
- CR-03: `GENESIS_ACTION` constant imported and equal to `"corpus_init"`; corpus init path goes through the structural carve-out inside `authorize()`.

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
