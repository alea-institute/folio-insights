---
phase: 01-deploy-on-railway-as-dev-server
plan: 02
subsystem: deployment
tags: [deployment, railway, config]
requirements: []
dependency-graph:
  requires:
    - Plan 01 Dockerfile (DOCKERFILE builder target)
    - Plan 01 /health endpoint (api/main.py)
    - viewer/src/lib/api/client.ts using relative URLs
  provides:
    - railway.toml (Railway service config with pinned builder + healthcheck)
    - Verified-clean frontend API base (no hardcoded localhost URLs)
  affects:
    - Plan 03 (live Railway deploy consumes this config)
tech-stack:
  added: []
  patterns:
    - Railway config-as-code (toml) mirroring folio-mapper's deploy declarativity
key-files:
  created:
    - railway.toml
    - .planning/phases/01-deploy-on-railway-as-dev-server/01-02-SUMMARY.md
  modified:
    - viewer/src/lib/api/client.ts (docstring only — replaced stale 'localhost:8700' mention)
decisions:
  - "[01-02]: Replaced 'localhost:8700' port mention in client.ts docstring with neutral 'vite.config.ts proxy target' — the audit grep flags literal ':8700' even in comments, and the comment was also stale"
  - "[01-02]: railway.toml deliberately has no startCommand — the Dockerfile CMD expands \${PORT:-8000}; adding startCommand here would bypass that"
  - "[01-02]: healthcheckTimeout = 120s chosen to accommodate heavy image boot (torch + sentence-transformers lazy import on first /health request if not already warm)"
  - "[01-02]: restartPolicyMaxRetries = 3 — surface crash loops as deploy failures, don't restart forever"
metrics:
  duration: ~2 min
  tasks: 3
  files: 2
  completed: "2026-04-13"
---

# Phase 01 Plan 02: Railway Config + Frontend URL Audit Summary

Added `railway.toml` pinning the DOCKERFILE builder and `/health` healthcheck for the dev deploy, and verified `viewer/src/` contains zero hardcoded localhost URLs or dev ports (enforcing the `feedback_api-client-proxy.md` auto-memory rule).

## What Was Built

### Task 1: Frontend API client audit
- Read the auto-memory rule `feedback_api-client-proxy.md` (empty `API_BASE`, never hardcode ports).
- Ran `grep -rEn "http://localhost|http://127\.0\.0\.1|:(9925|9926|8700|5173)" viewer/src/ --include='*.ts' --include='*.svelte' --include='*.js'`.
- Single hit was a docstring comment in `viewer/src/lib/api/client.ts` referencing `localhost:8700` — not an executing URL, but it tripped the audit grep and was also stale (current dev setup uses whatever port Vite picks; bootup.json uses 9925/9926 per README). Replaced with neutral wording referencing `vite.config.ts`.
- Re-ran the grep: clean (exit 1).
- `grep -q "const API_BASE = ''"` on client.ts: pass (the constant on line 9 is unchanged — still `''`).
- `viewer/build/` exists locally but is gitignored; spot-checked for the same patterns — clean.

### Task 2: railway.toml created
File at repo root, 20 lines. Sections:
- `[build]` — `builder = "DOCKERFILE"`, `dockerfilePath = "Dockerfile"`. Pins to the multi-stage Dockerfile from Plan 01.
- `[deploy]` — `healthcheckPath = "/health"` (endpoint added in Plan 01 Task 1), `healthcheckTimeout = 120`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3`.
- No `startCommand` (defers to Dockerfile `CMD` so `${PORT:-8000}` substitution works).
- No `numReplicas` (Railway default = 1 for dev).
- No watch paths (default: redeploy on any push to linked branch).

TOML validity confirmed with Python's `tomllib.loads`.

### Task 3: Rebuild + regression smoke test
Docker 29.4.0 available on host. Full Plan 01 smoke sequence re-run against the post-Plan-02 tree:

| Check                                          | Result                                                           |
| ---------------------------------------------- | ---------------------------------------------------------------- |
| `docker build -t folio-insights:plan-02 .`     | PASS — all layers cached from Plan 01 (no plan changes affect build context) |
| Container boots & stays up                     | PASS — `Up 8 seconds (health: starting)`                        |
| `curl /health`                                 | PASS — `{"status":"ok"}` on HTTP 200                            |
| `curl -I /`                                    | PASS — HTTP 200, `content-type: text/html; charset=utf-8`       |
| `curl /api/v1/corpora`                         | PASS — HTTP 200, returned bundled `test1` corpus                |
| Container cleanup                              | PASS — `docker stop && docker rm` succeeded, no dangling containers |

Host port 8000 was again occupied by an unrelated service (same condition Plan 01 encountered), so the smoke test used host `8765 → container 8000`. The container still binds `--port ${PORT:-8000}` internally, which is what Railway exercises.

## Verification Results

All four plan-level verification checks pass:

1. `viewer/src/` has zero hardcoded localhost URLs or dev-port numbers — confirmed.
2. `viewer/src/lib/api/client.ts` still uses `const API_BASE = ''` — confirmed.
3. `railway.toml` exists with DOCKERFILE builder and `/health` healthcheck — confirmed.
4. Docker build + run smoke test passes identically to Plan 01 — confirmed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Stale port reference in client.ts docstring**
- **Found during:** Task 1 audit
- **Issue:** The docstring at the top of `viewer/src/lib/api/client.ts` mentioned "localhost:8700" — a hardcoded port reference. While it was only a comment and did not affect runtime behavior, it (a) was stale (dev ports are 9925/9926 per README and bootup.json) and (b) tripped the task's own grep audit for the `:8700` pattern.
- **Fix:** Replaced the specific port mention with a neutral "see viewer/vite.config.ts for the proxy target" reference. No runtime impact.
- **Files modified:** `viewer/src/lib/api/client.ts` (lines 1-7 docstring only)
- **Commit:** `0b2de1c`

### Authentication Gates

None.

### Deferred Issues

None — all three tasks completed cleanly.

## Verification Notes

- **No viewer/build/ deletion needed.** The directory exists locally (gitignored) and contained no hardcoded URLs. It gets regenerated inside the Docker frontend-builder stage anyway, so the shipped image is unaffected by local build artifacts either way.
- **Cached Docker build.** The build completed in seconds because Plan 02 changes nothing in the Docker build context (only `railway.toml` and a comment in a file that lives outside the build context for the frontend-builder stage — and `viewer/src/lib/api/client.ts` IS in the frontend-builder context, so the `COPY viewer/ ./` layer was invalidated and re-run; subsequent layers still cached). Image output matches Plan 01's working build.
- **Host port conflict.** Same as Plan 01: host 8000 is in use by another service on this machine. The smoke test mapped host 8765 → container 8000. This is an environment quirk of the build host, not a deployment concern — Railway will bind the container to its injected `$PORT` and front it with Railway's edge.
- **Railway docs checked:** https://docs.railway.com/reference/config-as-code — the `[build]` and `[deploy]` section keys used here (`builder`, `dockerfilePath`, `healthcheckPath`, `healthcheckTimeout`, `restartPolicyType`, `restartPolicyMaxRetries`) all match current Railway config-as-code schema.

## Commits

| Hash      | Task | Message                                                                    |
| --------- | ---- | -------------------------------------------------------------------------- |
| `0b2de1c` | 1    | chore(01-02): audit API client and fix port-specific comment               |
| `7636dc2` | 2    | feat(01-02): add railway.toml service configuration                        |
| *(none)*  | 3    | Regression smoke test only — no file changes, no commit (per plan spec)    |

## Self-Check: PASSED

- FOUND: railway.toml
- FOUND: viewer/src/lib/api/client.ts (const API_BASE = '' preserved)
- FOUND: commit 0b2de1c
- FOUND: commit 7636dc2
- FOUND: .planning/phases/01-deploy-on-railway-as-dev-server/01-02-SUMMARY.md
