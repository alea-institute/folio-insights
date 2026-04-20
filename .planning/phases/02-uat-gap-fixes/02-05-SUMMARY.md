---
phase: 02-uat-gap-fixes
plan: 05
subsystem: deploy/railway
tags: [uat, railway, dockerignore, deploy, wave-2]
requirements:
  - I-5
gap_closure: true
dependency_graph:
  requires:
    - output/demo/ fixture from Plan 02-04 (ships alongside this deploy)
    - api/routes/corpus.py::_read_corpus_info extraction.json → "completed" fallback (unchanged, line ~74-76)
  provides:
    - Build-context exclusion of output/.jobs/ (stale per-corpus job state never ships)
    - Live Railway processing_status=completed for bundled corpora (test1, demo)
  affects:
    - Future Railway builds (permanent exclusion; one-line .dockerignore rule)
tech_stack:
  added: []
  patterns:
    - Minimal blast-radius fix via .dockerignore rather than touching Dockerfile or runtime code
key_files:
  created: []
  modified:
    - .dockerignore
decisions:
  - "02-05: Fix stale processing_status via build-context exclusion, not runtime code change — keeps Dockerfile/railway.toml/api invariants from Phase 01 untouched"
  - "02-05: Detected during verification that Railway service.source was null — GitHub autodeploy was not wired; reconnecting the source resumed autodeploys for commit 7a34bce and is the durable fix"
metrics:
  duration_minutes: 12
  tasks_completed: 2
  files_modified: 1
  tests_added: 0
  completed: 2026-04-20
---

# Phase 02 Plan 05: Exclude output/.jobs/ from Docker context (UAT I-5) Summary

## One-liner

Add `output/.jobs/` to `.dockerignore` so Railway never ships stale per-corpus job state; bundled corpora with `extraction.json` fall through to `processing_status="completed"`.

## What was shipped

- `.dockerignore` — appended a new trailing block excluding `output/.jobs` and `output/.jobs/**` from the Docker build context. No other file modified.
- Live Railway redeploy (deploy `a80bcb75…`, commit `7a34bce`) picked up the fix. `/api/v1/corpora` now returns bundled corpora with `processing_status="completed"` instead of the stale `"failed"`.

## Diff summary

| Change | Before | After |
|---|---|---|
| `output/.jobs/` in image | present (bundled via `COPY output/ ./output/`) | absent (build-context excluded) |
| `GET /api/v1/corpora` for `test1` | `processing_status: "failed"` (stale job JSON) | `processing_status: "completed"` (extraction.json fallback) |
| `GET /api/v1/corpora` for `demo` | *not present* (demo fixture never made it to prod) | `processing_status: "completed"` |
| Dockerfile | unchanged | unchanged |
| `railway.toml` | unchanged | unchanged |
| `api/routes/corpus.py` | unchanged | unchanged |

## .dockerignore diff

```diff
 # Test artifacts
 tests/fixtures/large
+
+# Per-corpus job state (output/.jobs/) — excluded so Railway never ships
+# stale or failed-state job JSON. Bundled corpora with extraction.json
+# fall back to processing_status='completed' via api/routes/corpus.py
+# line ~74-76. Fixes UAT Issue I-5.
+output/.jobs
+output/.jobs/**
```

## Invariants preserved

`git diff --stat` for Task 1 touched only `.dockerignore`. All Phase 01 Railway invariants intact:

- Dockerfile multi-stage build (node:20-slim → python:3.11-slim) — unchanged
- `USER appuser` non-root runtime — unchanged
- `HEALTHCHECK` on `/health` — unchanged
- `CMD` with `${PORT:-8000}` substitution — unchanged
- `COPY output/ ./output/` bundling step — unchanged (`default/`, `test1/`, `demo/` still copied)
- `railway.toml` — unchanged

## Tasks & commits

| # | Task | Commit | Files |
|---|---|---|---|
| 1 | Add `output/.jobs` exclusion to `.dockerignore` | `7a34bce` | `.dockerignore` |
| 2 | Human checkpoint: push + Railway redeploy + live curl verification | — | — (deploy `a80bcb75-…`) |

## Verification evidence

### Live API — `/api/v1/corpora` (post-deploy 2026-04-20T21:34Z)

```
$ curl -s https://folio-insights-production.up.railway.app/api/v1/corpora | jq '.[] | {id, processing_status}'
{
  "id": "demo",
  "processing_status": "completed"
}
{
  "id": "test1",
  "processing_status": "completed"
}
```

### Live health + root

```
$ curl -s -o /dev/null -w "%{http_code}\n" https://folio-insights-production.up.railway.app/health
200
$ curl -s -o /dev/null -w "%{http_code}\n" https://folio-insights-production.up.railway.app/
200
```

### Railway deploy metadata (via GraphQL API)

```
deploy id:   a80bcb75-…
commit:      7a34bced27…   (= fix(02-05): exclude output/.jobs/ …)
status:      SUCCESS
createdAt:   2026-04-20T21:24:49Z
buildTime:   ~7 min  (BUILDING 21:24 → DEPLOYING 21:32 → SUCCESS 21:34)
```

## Deviations from Plan

1. **Local `docker build` verification skipped** — Task 1's optional local build step wasn't run; Railway's managed build served as the verification path. No impact on correctness.
2. **Additional blocker surfaced during Task 2** — Railway's `serviceInstance.source` was `null`; GitHub autodeploy had become disconnected and no pushes since 2026-04-13 were deploying. User reconnected `alea-institute/folio-insights` on `master` mid-checkpoint. First autodeploy after reconnection picked up `7a34bce` and shipped the fix. Recorded as a separate learning — the plan's I-5 scope (the .dockerignore change) was unchanged.

## Operational notes

- Local dev is unaffected: `output/.jobs/` continues to exist in the working tree and is used by the local FastAPI process; only the Docker build context filters it out.
- The exclusion is permanent — future Railway builds will never bundle per-corpus job state again, closing this class of "stale-state leaks into deploy" issue.
- The autodeploy reconnection (found during verification) is the durable fix for Wave 3+ and should be captured as a Phase-level learning.

## Self-Check

- [x] `.dockerignore` exclusion present — `grep -c "output/.jobs" .dockerignore` → 2 (two exclusion lines)
- [x] Dockerfile invariants intact — multi-stage, `USER appuser`, `HEALTHCHECK`, `PORT:-8000`, `COPY output/ ./output/` all grep-verified
- [x] `railway.toml` untouched — not in commit 7a34bce diff
- [x] Live `/api/v1/corpora` returns `test1.processing_status=="completed"` — confirmed
- [x] Live `/api/v1/corpora` returns `demo.processing_status=="completed"` — confirmed
- [x] Live `/health` returns 200 — confirmed
- [x] Live `/` returns 200 — confirmed

## Self-Check: PASSED

## Follow-ups

- None for UAT Issue I-5. Phase 02 now closes with all 5 UAT issues (I-1 through I-5) resolved.
- Ancillary: capture the autodeploy-reconnection learning in Phase 01 or a new operational note so the "is the service wired to a source?" check is part of future Railway deploy plans.
