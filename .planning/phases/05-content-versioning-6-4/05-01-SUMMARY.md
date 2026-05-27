---
phase: 05-content-versioning-6-4
plan: 01
subsystem: database
tags: [pydantic, content-versioning, audit-log, model-validator, append-only, shard-envelope]

# Dependency graph
requires:
  - phase: 02-shard-envelope
    provides: ContentEdit frozen sub-model + add_edit helper + AttestedSignature stub + 6 frozen identity fields + ShardEnvelope.model_rebuild() forward-ref
  - phase: 04-iri-scheme-6-3
    provides: immutable hex32 shard IRIs (edits never change the IRI)
provides:
  - "Enriched ContentEdit (dotted field_path, required rationale, AttestedSignature slot) — full PRD §6.4 shape (D-04, D-05)"
  - "Authoritative forward-only/append-only @model_validator on ShardEnvelope (D-07.1, D-08b)"
  - "add_edit migrated to a thin sync wrapper on the enriched shape (capture-before-assign preserved)"
  - "Exit-criterion-1 acceptance test (test_content_edit_audit_append_only.py)"
  - "conftest _content_edit() enriched-ContentEdit builder for downstream test modules"
affects: [05-02 revision-write-path, 05-03 shacl-guard, 06-did-substrate, 07-governance, 13-storage]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-layer enforcement: Pydantic @model_validator (authoritative) + pyshacl shape (defense-in-depth, Plan 03)"
    - "@model_validator(mode='after') raise-on-violation with CONTEXT-citing message (shards house style)"
    - "Append-only audit chain: frozen entries + monotonic-edited_at gate; immutability half carried structurally"

key-files:
  created:
    - tests/shards/test_content_edit_audit_append_only.py
  modified:
    - src/folio_insights/shards/audit.py
    - src/folio_insights/shards/envelope.py
    - tests/shards/test_audit_log.py
    - tests/shards/conftest.py

key-decisions:
  - "[05-01] ContentEdit.signature is an unsigned AttestedSignature stub (signature='', action='content_edit') — real ed25519/JCS deferred to Phase 6 (D-05 seam)"
  - "[05-01] add_edit kept as a thin SYNC wrapper (flat top-level fields); dotted nested paths (triple.object) are the Plan 02 set_field/edit_shard_content path (RESEARCH OQ2)"
  - "[05-01] Forward-only validator uses strict < (equal adjacent edited_at allowed, ties broken by append order — D-09); only the monotonicity half lives here, immutability half is structural (frozen + IMMUTABLE_FIELD_PATHS)"

patterns-established:
  - "Pydantic @model_validator(mode='after') forward-only gate over an append-only list"
  - "conftest enriched-record builder (_content_edit) to spare downstream modules signature/rationale ceremony"

requirements-completed: [SHARD-09]

# Metrics
duration: 4 min
completed: 2026-05-27
---

# Phase 5 Plan 01: ContentEdit Enrichment + Forward-Only Validator Summary

**Enriched the Phase-2 ContentEdit audit record to the full PRD §6.4 shape (dotted `field_path`, required `rationale`, reused `AttestedSignature` slot) and added the authoritative forward-only/append-only `@model_validator` on `ShardEnvelope` — the pure-Pydantic schema foundation that Plans 02 (write path) and 03 (SHACL guard) build on, with `shards/` kept RDF-free.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-27T16:43:09Z
- **Completed:** 2026-05-27T16:47:21Z
- **Tasks:** 3
- **Files modified:** 4 created/modified (1 created, 3 modified; 2 temporary RED tests created then removed)

## Accomplishments

- `ContentEdit` enriched to the PRD §6.4 shape: `field_name`→`field_path` (dotted), required `rationale`, `signature: AttestedSignature` reused from `envelope.py` (D-04, D-05). `frozen=True` + `extra="forbid"` preserved; `ShardEnvelope.model_rebuild()` preserved.
- `add_edit` migrated to a thin sync wrapper on the new shape, taking `rationale` as its 5th argument, stubbing an unsigned `AttestedSignature` (`action="content_edit"`, `signature=""`); capture-before-assign order preserved.
- `_content_edits_forward_only` `@model_validator(mode="after")` added to `ShardEnvelope`: rejects non-monotonic `edited_at` chains with a `D-08b`-citing `ValueError`; equal adjacent timestamps allowed (strict `<` only).
- `test_audit_log.py` migrated (no `field_name` left, required `rationale`/`signature` everywhere) and green; new exit-criterion-1 `test_content_edit_audit_append_only.py` green (4 tests: append-revalidate, frozen entry, back-dated reject, reorder reject).
- All 147 `tests/shards/` tests pass; dep-leak guard green (`shards/` imports zero RDF/storage libs).

## Task Commits

Each task was committed atomically:

1. **Task 1: Enrich ContentEdit + migrate add_edit (audit.py)** - `efeb527` (feat) — TDD: RED test + GREEN implementation in one commit
2. **Task 2: Forward-only @model_validator on ShardEnvelope (envelope.py)** - `0f6e9bf` (feat) — TDD: RED test + GREEN implementation in one commit
3. **Task 3: Migrate test_audit_log + extend conftest + exit-criterion-1 test** - `13ee1bb` (test)

**Plan metadata:** committed separately with this SUMMARY.

_Note: Tasks 1 & 2 (tdd="true") used a temporary RED test committed alongside the GREEN implementation, then removed in Task 3 once the durable migrated/new tests covered the same behavior._

## Files Created/Modified

- `src/folio_insights/shards/audit.py` (modified) - Enriched `ContentEdit` (field_path/rationale/signature), migrated `add_edit` sync wrapper, preserved `model_rebuild()`; refreshed module docstring to Phase-5 scope.
- `src/folio_insights/shards/envelope.py` (modified) - Added `_content_edits_forward_only` `@model_validator`; imported `model_validator` from pydantic.
- `tests/shards/test_audit_log.py` (modified) - Migrated to `field_path` + required `rationale`/`signature`; added rationale-required regression; asserts the unsigned-stub signature.
- `tests/shards/conftest.py` (modified) - Added `_content_edit()` enriched-ContentEdit builder; imported `AttestedSignature` + `ContentEdit`.
- `tests/shards/test_content_edit_audit_append_only.py` (created) - Exit-criterion-1 acceptance test (4 tests).

## Decisions Made

- **ContentEdit.signature is an unsigned stub** — empty `AttestedSignature` with `action="content_edit"`, `signature=""`. Real ed25519/JCS signing is the Phase 6 seam (D-05, threat T-05-03 accepted). Tests assert `signature == ""` so an empty signature cannot read as "verified".
- **add_edit stays a thin sync wrapper for flat top-level fields.** Dotted nested paths (`triple.object`) are intentionally the Plan 02 `set_field`/`edit_shard_content` path, not `add_edit` (RESEARCH Open Question 2).
- **Forward-only validator uses strict `<`** — equal adjacent `edited_at` is allowed (ties broken by append order, D-09). Only the monotonicity half (D-08b) lives in the validator; the immutability half (D-08a) is structural (`ContentEdit` frozen + Plan 02 `IMMUTABLE_FIELD_PATHS`), documented in the validator docstring because a stateless validator cannot detect deletions over a single snapshot.

## Deviations from Plan

None - plan executed exactly as written.

The only departure is mechanical and was anticipated by the plan's TDD structure: Tasks 1 & 2 are `tdd="true"` but the durable tests live in Task 3, so each used a temporary RED test (`test_content_edit_enriched_red.py`, `test_forward_only_red.py`) to prove RED→GREEN, then removed in Task 3. The deletions are intentional, not lost work.

## Issues Encountered

- **Pre-existing, out-of-scope collection error:** `tests/test_corpus_api.py` fails to import (`ModuleNotFoundError: No module named 'fastapi'`) — the `fastapi` dev dependency is not installed in this environment. This is unrelated to this plan (it predates these changes and lives outside `tests/shards/`). Per the scope-boundary rule, it was NOT fixed. All verification was scoped to `tests/shards/`, which is the plan's domain. Logged here for visibility; no action required for this plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **Ready for Plan 05-02** (revision/ async write path): the enriched `ContentEdit` and the authoritative `@model_validator` are in place. Plan 02 builds `edit_shard_content`, `get_shard_at`, `IMMUTABLE_FIELD_PATHS`, `get_field`/`set_field`, `canonical_content_hash`, `sign_attestation`, and the in-memory `ShardStore` in the new `revision/` package.
- **Ready for Plan 05-03** (SHACL guard): the forward-only invariant is now enforced authoritatively; Plan 03 adds the pyshacl `sh:sparql` shape as defense-in-depth in `revision/` (NOT `shards/`, per the dep-leak boundary).
- **Phase 6 seams open:** `ContentEdit.signature` is an unsigned slot ready for real ed25519/JCS. `editor_did` is captured but not verified (V4 partial — documented deferred gap, T-05-04 accepted).

## Self-Check: PASSED

- Created file exists: `tests/shards/test_content_edit_audit_append_only.py` — FOUND
- Task commits exist: `efeb527`, `0f6e9bf`, `13ee1bb` — all FOUND in git log
- Plan verification: `uv run pytest tests/shards/ -q` → 147 passed; dep-leak guard → 5 passed; exit criterion 1 → 4 passed
- All acceptance criteria for Tasks 1, 2, 3 verified PASS

---
*Phase: 05-content-versioning-6-4*
*Completed: 2026-05-27*
