---
phase: 01-deploy-on-railway-as-dev-server
plan: 01
subsystem: deployment
tags: [deployment, docker, fastapi, sveltekit, railway]
requirements: []
dependency-graph:
  requires:
    - viewer (SvelteKit adapter-static build)
    - api.main:app (FastAPI ASGI entry)
    - output/ (bundled extraction dataset, 3.8 MB)
  provides:
    - folio-insights:plan-01 Docker image (single-service, non-root, $PORT-aware)
    - /health liveness endpoint
  affects:
    - All future Railway deploys (Plan 02 railway config, Plan 03 deploy)
tech-stack:
  added:
    - Docker multi-stage build pattern (Node 20 → Python 3.11-slim)
    - uv (via ghcr.io/astral-sh/uv:latest) for deterministic Python installs in image
  patterns:
    - Mirrors folio-enrich Dockerfile non-root-user block
    - Mirrors folio-mapper multi-stage + uv + SPA pattern
    - CMD sh -c "... ${PORT:-8000}" for Railway PORT injection
key-files:
  created:
    - Dockerfile
    - .dockerignore
    - .planning/phases/01-deploy-on-railway-as-dev-server/01-01-SUMMARY.md
  modified:
    - api/main.py (added /health route)
decisions:
  - Used npm (not pnpm) for viewer — viewer/package-lock.json exists, no pnpm-lock.yaml
  - Belt-and-suspenders install of fastapi + uvicorn[standard] + python-multipart on top of `uv pip install .` because pyproject.toml does not declare fastapi/uvicorn as direct deps (they come in transitively via sse-starlette in current env); explicit install prevents future transitive-dep breakage
  - Bundled output/ (3.8 MB) into the image rather than using a Railway volume — simplest dev path, matches CONTEXT.md decision
  - HEALTHCHECK path /health (single endpoint) — no /api/health duplicate
  - Single Dockerfile, no railway.toml — defer until Plan 02 determines if explicit healthcheck path or watch-path config is needed
metrics:
  duration: ~9 min
  tasks: 3
  files: 3
  completed: "2026-04-13"
---

# Phase 01 Plan 01: Dockerize FOLIO Insights Summary

Multi-stage Dockerfile (Node 20 builder → Python 3.11-slim runtime) bundles SvelteKit viewer, FastAPI API, and 3.8 MB extraction dataset into a single non-root image serving the app on $PORT.

## What Was Built

### Task 1: /health endpoint
Added `@app.get("/health")` returning `{"status": "ok"}` in `api/main.py`, placed between `app = FastAPI(...)` and CORS middleware — registered before the catch-all StaticFiles mount at `/` so the explicit route wins.

### Task 2: .dockerignore
Excludes `.venv`, `viewer/node_modules`, `viewer/build`, `viewer/.svelte-kit`, `.git`, `__pycache__`, `.planning`, `.claude`, IDE dirs, `.env*` (except `.env.example`). Deliberately does NOT exclude `output/` — it must be bundled into the image.

### Task 3: Multi-stage Dockerfile
- **Stage 1 (frontend-builder):** `node:20-slim`, `npm ci` then `npm run build` produces `viewer/build/` static site.
- **Stage 2 (runtime):** `python:3.11-slim` + `uv` pulled from `ghcr.io/astral-sh/uv:latest`. Installs project via `uv pip install --system --no-cache .` plus explicit `fastapi "uvicorn[standard]" python-multipart` to guard against pyproject transitive-dep drift.
- Copies built viewer to `/app/viewer/build/` (matches `api/main.py`'s `Path(__file__).resolve().parent.parent / "viewer" / "build"` resolution).
- Bundles `output/` as `/app/output/`.
- Non-root `appuser` owns `/app` + `/home/appuser/.folio-insights`.
- `HEALTHCHECK` hits `/health`. `CMD` expands `${PORT:-8000}`.

## Verification Results

Docker is available on this host (Docker 29.4.0) — all automated verification ran successfully.

| Check                                         | Result                                                                |
| --------------------------------------------- | --------------------------------------------------------------------- |
| `docker build -t folio-insights:plan-01 .`    | PASS (exit 0, ~2m including ~108s export layer)                       |
| Container boots & stays up                    | PASS (`Up 8 seconds (health: starting)`)                              |
| `curl /health`                                | PASS — `{"status":"ok"}`, HTTP 200                                    |
| `curl -I /`                                   | PASS — HTTP 200, `content-type: text/html`                            |
| `curl /api/v1/corpora`                        | PASS — HTTP 200, returned existing `test1` corpus from bundled output |
| Container user                                | PASS — `appuser`                                                      |
| `node_modules` absent                         | PASS — `/app/viewer/node_modules` does not exist                      |
| `output/default` present                      | PASS — directory exists with bundled data                             |
| PORT env override (ran with `-e PORT=9090`)   | PASS — `/health` responded on mapped port                             |

Host port 8000 was occupied by an unrelated container on this machine, so the smoke tests mapped host `8765 → container 8000` and host `9091 → container 9090`. The container itself binds to the requested `PORT`, which is what Railway will exercise.

## Verification Notes

- **Image size: 8.67 GB** — substantially over the 2.5 GB soft target noted in the plan. Dominated by `torch==2.11.0` + NVIDIA CUDA runtime libraries (`nvidia-cu13-*`, `triton`, `nvshmem`) pulled in transitively by `sentence-transformers==5.4.0`. This is a runtime-only concern:
  - Railway charges by RAM/CPU, not image size, so this should still deploy.
  - If image pull time becomes a problem, a follow-up plan can switch to CPU-only torch via `--index-strategy unsafe-best-match` + `--extra-index-url https://download.pytorch.org/whl/cpu` or pin `torch` with CUDA-less markers. Deferred, not blocking.
- **Base image choice:** stuck with `python:3.11-slim`. `3.13-slim` (what folio-enrich uses) would work too; 3.11 was chosen because `pyproject.toml` declares `requires-python = ">=3.11"` and the existing dev env targets 3.11.
- **No pyproject.toml changes needed.** The belt-and-suspenders `uv pip install fastapi uvicorn[standard] python-multipart` in the Dockerfile keeps the runtime working even though these are not declared as direct project deps. A follow-up hardening task could promote them to `dependencies` in `pyproject.toml`; that is a semantics question (are fastapi/uvicorn truly folio-insights' deps, or only the server's?) and is intentionally left for later discussion.
- **pyshacl + sentence-transformers** installed cleanly on the slim base thanks to `build-essential` in the system-deps layer — no native-compile issues encountered.

## Deviations from Plan

### Auto-fixed Issues

None — all three tasks executed as specified. Minor environment adaptations (using `.venv/bin/python` because `python` is not on PATH in this shell; using host port 8765 instead of 8000 because the default was occupied) did not require plan modification and are not deviations from the plan's artifacts.

### Authentication Gates

None.

### Deferred Issues

- **Image-size reduction (8.67 GB → ~2 GB target)** via CPU-only torch. Not blocking Railway deploy; revisit if cold-start pull time hurts during Plan 03.
- **Promote fastapi/uvicorn/python-multipart from Dockerfile belt-and-suspenders line into `pyproject.toml` dependencies.** Optional hardening.

## Commits

| Hash      | Task | Message                                          |
| --------- | ---- | ------------------------------------------------ |
| `e2bb83c` | 1    | feat(01-01): add /health endpoint to FastAPI app |
| `227bc2e` | 2    | chore(01-01): add .dockerignore                  |
| `9f185ca` | 3    | feat(01-01): add multi-stage Dockerfile for Railway deploy |

## Self-Check: PASSED

- FOUND: Dockerfile
- FOUND: .dockerignore
- FOUND: api/main.py (`/health` route present)
- FOUND: e2bb83c
- FOUND: 227bc2e
- FOUND: 9f185ca
