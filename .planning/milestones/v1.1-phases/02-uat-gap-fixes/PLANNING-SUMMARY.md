# Phase 02 — UAT Gap Fixes: Planning Summary

**Planned:** 2026-04-19
**Mode:** `--gaps` (gap_closure)
**Source of gaps:** `.planning/phases/COMPREHENSIVE-UAT.md` (Issues I-1 through I-5)

## Plans Created

| Plan | Issue | Wave | Autonomous | Files Modified |
|------|-------|------|------------|----------------|
| [02-01](02-01-PLAN.md) | **I-3** Vite proxy 8700 → 9925 | 1 | yes | `viewer/vite.config.ts` |
| [02-02](02-02-PLAN.md) | **I-2** Bundle export 422 → 404 parity | 1 | yes | `api/routes/export.py`, `tests/test_export_api.py` |
| [02-03](02-03-PLAN.md) | **I-1** LLM-path FOLIO IRI resolution | 1 | yes | `src/folio_insights/pipeline/stages/folio_tagger.py`, `tests/test_folio_tagging.py` |
| [02-04](02-04-PLAN.md) | **I-4** Seed `output/demo/` export fixture | 1 | yes | `scripts/seed_demo_corpus.py`, `output/demo/*`, `.gitignore` |
| [02-05](02-05-PLAN.md) | **I-5** Railway `processing_status=failed` cleanup | 2 | no (Railway deploy checkpoint) | `.dockerignore` |

## Issue → Plan Mapping (canonical)

- **I-1 · Empty FOLIO IRIs on LLM-path tags** (major) → `02-03-PLAN.md`
  - Root: `_reconciled_to_tags` used threshold 0.7 — rejected legit LLM-path label matches
  - Fix: lower to 0.6; route unresolved to `extraction_path='proposed_class'`; 4 new regression tests
- **I-2 · Bundle export returns 422 not 404** (minor) → `02-02-PLAN.md`
  - Root: Pydantic body validation fires before the 404 check
  - Fix: `body: BundleRequest | None = None` + 3 new parity regression tests
- **I-3 · Vite proxy hardcoded to :8700** (blocker for viewer dev) → `02-01-PLAN.md`
  - Root: 1-line wrong port
  - Fix: 9925 + inline comment citing the `feedback_api-client-proxy.md` auto-memory rule
- **I-4 · No approved-task fixture for export** (major gap for UAT tests 37-41) → `02-04-PLAN.md`
  - Root: no committed fixture
  - Fix: deterministic seed script + committed `output/demo/` with 2 approved tasks, 2 task_unit_links, 2 units
- **I-5 · Railway test1 shows `processing_status=failed`** (minor) → `02-05-PLAN.md`
  - Root: `output/.jobs/` directory bundled into Docker image; stale/failed state leaks
  - Fix: add `output/.jobs` to `.dockerignore`; fallback in `api/routes/corpus.py` shows `completed`

## Wave Structure & Parallelism

- **Wave 1 (four plans run in parallel — zero `files_modified` overlap):**
  - 02-01 touches `viewer/vite.config.ts`
  - 02-02 touches `api/routes/export.py` + `tests/test_export_api.py`
  - 02-03 touches `src/folio_insights/pipeline/stages/folio_tagger.py` + `tests/test_folio_tagging.py`
  - 02-04 touches `scripts/seed_demo_corpus.py`, `output/demo/*`, `.gitignore`

- **Wave 2 (one plan, depends on 02-04 to ensure output/demo/ is bundled in next Railway image):**
  - 02-05 touches `.dockerignore`; includes a `checkpoint:human-verify` for the user to push + curl-verify the live Railway URL

## Regression Safety Net

All plans must leave `.venv/bin/pytest tests/ -q` green. Baseline is 197 tests. After this phase:

- 02-02 adds 3 tests → 200
- 02-03 adds 4 tests → 204
- 02-01, 02-04, 02-05 add 0 tests

**Expected final pytest count after phase 02 executes:** `>= 204 passed`.

## Railway Safety Invariants (from Phase 01)

Plan 02-05 is the only plan that touches Docker-adjacent infra. It explicitly protects:
- Dockerfile multi-stage build (node:20-slim → python:3.11-slim) — unchanged
- USER appuser (non-root) — unchanged
- HEALTHCHECK CMD on /health — unchanged
- CMD `${PORT:-8000}` substitution — unchanged
- `COPY output/ ./output/` bundling of `output/default/` and `output/test1/` — unchanged (new fixture `output/demo/` from 02-04 also copied)
- railway.toml — unchanged

## Deferred (out of scope per CONTEXT.md)

- Full UAT re-run (belongs to `/gsd-verify-work 2` after this phase executes)
- Migrating vite proxy to `VITE_API_URL` env var (deferred — only the proxy target changes here)
- Gold-standard boundary validation set (Phase 1 blocker, separate effort)
- LLM provider benchmarking (Phase 1 blocker, separate effort)
- Observability/logging improvements

## Next Step

Execute with: `/gsd-execute-phase 2`

After execution, re-run the comprehensive UAT against the live Railway URL to confirm tests 14–15, 19, 24–28, 30, 33–36, 37–41, and 47 transition from `issue`/`skipped` to `pass`.
