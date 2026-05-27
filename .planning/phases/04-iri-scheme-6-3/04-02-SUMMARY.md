---
phase: 04-iri-scheme-6-3
plan: 02
subsystem: shards
tags: [shards, iri, collision-detection, content-addressed, aiosqlite, cli, verify-iris, fail-closed]

# Dependency graph
requires:
  - phase: 04-iri-scheme-6-3
    plan: 01
    provides: hex32 mint_shard_iri(source_uri, source_span) -> (iri, full_64hex_hash); _IRI_PREFIX
provides:
  - global content-addressed shard_iri_registry (aiosqlite, self-bootstrapping) with idempotent register + fail-closed ShardIRICollision (D-03/D-04)
  - SHARD-08 collision detector exercised at 100K synthetic shards, zero hex32 collisions (D-05)
  - folio-insights verify-iris CLI — nightly re-hash guard, non-zero exit on any mismatch, never auto-quarantines (D-06/D-07)
affects: [05-content-versioning, 13-triplestore-storage]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Registry self-bootstraps its global DB schema (CREATE TABLE IF NOT EXISTS on every connect) — it OWNS the file, unlike iri_manager which assumes a pre-existing table"
    - "Fail-closed collision: same hex32 body + different full hash -> raise + log both hashes, NEVER UPDATE/overwrite the existing provenance row (D-03)"
    - "iri_body TEXT NOT NULL UNIQUE makes the duplicate-body insert atomic at the DB layer (T-04-06 race guard)"
    - "CLI lazy-import discipline: ShardIRIRegistry + mint_shard_iri imported inside the verify-iris body, not at cli.py module top"

key-files:
  created:
    - src/folio_insights/shards/iri_registry.py
    - tests/shards/test_iri_collision.py
    - tests/shards/test_verify_iris_cli.py
  modified:
    - src/folio_insights/shards/__init__.py
    - src/folio_insights/cli.py

key-decisions:
  - "Global registry DB default at $HOME/.folio-insights/shard_iri_registry.db (D-04 global, NOT per-corpus review.db); CLI --db overrides"
  - "ShardIRICollision carries the (uri, span) pair + both full hashes so the halt+flag log AND the raised error both surface enough for human review (D-03)"
  - "_seed_row() test/seed helper (bypasses minting) lets collision + drift scenarios be constructed deterministically without reaching into SQL from tests"
  - "verify-iris is surface-only (report + non-zero exit + log) — no UPDATE/DELETE/quarantine on the registry (D-07)"

requirements-completed: [SHARD-07, SHARD-08]

# Metrics
duration: 18min
completed: 2026-05-26
---

# Phase 04 Plan 02: IRI Collision Registry + verify-iris Summary

**Shipped a global content-addressed `shard_iri_registry` (aiosqlite, self-bootstrapping) with idempotent re-mint and a fail-closed `ShardIRICollision` halt, proven collision-free at 100K synthetic shards, plus the `folio-insights verify-iris` nightly re-hash guard that exits non-zero on any stored-IRI drift without auto-quarantining.**

## Performance

- **Duration:** ~18 min
- **Tasks:** 2 completed (both TDD)
- **Files:** 3 created, 2 modified
- **Tests:** 139 shards tests pass (132 prior + 7 new); slow 100K test in 0.37s

## Accomplishments

- **Global shard IRI registry (D-04):** `ShardIRIRegistry` (aiosqlite direct-SQL, no ORM) keyed on the hex32 IRI body, storing the full 64-hex hash for collision comparison. Self-bootstraps `shard_iri_registry` (`CREATE TABLE IF NOT EXISTS` + `idx_shard_iri_body`) on every connect — it owns its global DB file, unlike the separate per-corpus `iri_manager`.
- **Idempotent register + fail-closed collision (D-03):** `register()` returns the existing IRI on a same-body/same-hash re-mint (no write); on same-body/**different**-hash it logs both full hashes + the `(uri, span)` pair and raises `ShardIRICollision` — never overwriting the existing provenance row.
- **SHARD-08 at 100K (D-05):** `test_no_collision_at_100k` mints 100K synthetic shards with zero hex32-body collisions and 100K distinct bodies (marked `slow`).
- **verify-iris CLI (D-06/D-07):** re-mints every stored shard IRI from its stored `source_uri`/`source_span`, compares to the stored body, reports each mismatch (stored/reminted/source_uri), logs it, and exits non-zero. Clean corpora exit 0. Surface-only — no auto-quarantine or registry mutation.

## Task Commits

1. **Task 1 (RED):** failing collision/idempotent/bootstrap tests — `78579e6` (test)
2. **Task 1 (GREEN):** `ShardIRIRegistry` + `ShardIRICollision` + `__init__` exports — `2d4e309` (feat)
3. **Task 2 (RED):** failing verify-iris CliRunner tests — `0f38f2d` (test)
4. **Task 2 (GREEN):** `verify-iris` Click command — `81a6b7c` (feat)

_Both TDD tasks produced test -> feat commits; no refactor commit needed (implementations were minimal and clean)._

## Files Created/Modified

- `src/folio_insights/shards/iri_registry.py` (created) — `ShardIRIRegistry` (register, all_records, _seed_row, _bootstrap), `ShardIRICollision`, `DEFAULT_REGISTRY_PATH`. Parametrized `?` SQL throughout; `iri_body UNIQUE` race guard.
- `src/folio_insights/shards/__init__.py` (modified) — re-export `ShardIRIRegistry` + `ShardIRICollision` (added to `__all__`).
- `src/folio_insights/cli.py` (modified) — inline `@cli.command("verify-iris")` with `--db`/`--verbose`, lazy imports inside the body, `asyncio.run(registry.all_records())` bridge, non-zero exit on mismatch.
- `tests/shards/test_iri_collision.py` (created) — idempotent, fail-closed collision, self-bootstrapping-table, 100K no-collision (slow).
- `tests/shards/test_verify_iris_cli.py` (created) — CliRunner: mismatch non-zero, all-match zero, `--help` exit 0.

## Decisions Made

None beyond the plan — followed D-03/D-04/D-05/D-06/D-07 as specified. Discretion exercised on the global DB default path (`$HOME/.folio-insights/shard_iri_registry.db`, matching the project's existing `$HOME/.folio-insights/` convention; CLI `--db` overrides) and on adding a `_seed_row` helper for deterministic test scenario construction.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] aiosqlite connection used as both awaited result AND context manager**
- **Found during:** Task 1 GREEN (first test run)
- **Issue:** The initial `_connect()` helper did `db = await aiosqlite.connect(...)` then `async with await self._connect() as db:` re-entered the connection's `__aenter__`, double-starting its worker thread → `RuntimeError: threads can only be started once`. All three non-slow tests failed.
- **Fix:** Removed the awaited-connection helper; inlined `async with aiosqlite.connect(str(self._db_path)) as db:` at each call site (matching `iri_manager.py`), with a `_bootstrap(db)` helper that runs the idempotent DDL on the live connection.
- **Files modified:** `src/folio_insights/shards/iri_registry.py`
- **Verification:** non-slow + slow collision tests pass; full shards suite 139 passed.
- **Committed in:** `2d4e309` (Task 1 GREEN — caught and fixed within the GREEN phase before commit).

**Total deviations:** 1 auto-fixed (1x Rule 1 — connection-lifecycle bug). No scope creep.

## Threat Model Compliance

- **T-04-04 (Tampering, collision branch) — mitigated:** same body + different hash raises `ShardIRICollision`, logs both hashes, no UPDATE/overwrite (grep-confirmed: no `UPDATE`/`REPLACE` in `iri_registry.py`).
- **T-04-05 (Tampering, SQL) — mitigated:** all registry SQL parametrized `?` (grep-confirmed: no f-string/`%` SQL).
- **T-04-06 (Race, concurrent collision) — mitigated:** `iri_body TEXT NOT NULL UNIQUE` makes duplicate-body insert atomic at the DB layer.
- **T-04-07 (Repudiation, verify-iris) — mitigated:** verify-iris re-hashes, non-zero exit + logged report on drift, no destructive action (grep-confirmed: no registry writes in the command body).
- **T-04-08 (DoS, 100K scan) — accepted:** offline nightly batch; 100K mint runs in 0.37s.

## Issues Encountered

- **No venv in worktree:** ran tests via the main repo's `.venv/bin/python` with `PYTHONPATH=<worktree>/src` so the worktree source takes precedence (verified `folio_insights.__file__` resolves to the worktree). Same approach as Plan 04-01. No source changes needed.

## Known Stubs

None — no placeholder values, mock data, or unwired data sources introduced.

## Threat Flags

None — no new security surface beyond the plan's `<threat_model>`.

## Self-Check: PASSED

- `src/folio_insights/shards/iri_registry.py` — FOUND
- `tests/shards/test_iri_collision.py` — FOUND
- `tests/shards/test_verify_iris_cli.py` — FOUND
- Commits `78579e6`, `2d4e309`, `0f38f2d`, `81a6b7c` — all present in git log.

---
*Phase: 04-iri-scheme-6-3*
*Completed: 2026-05-26*
