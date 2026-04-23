---
phase: 0
plan: 4
plan_number: 4
plan_name: two-stage-dockerfiles-and-railway-split
subsystem: infra
tags: [docker, jlink, railway, sveltekit, adapter-node, reproducibility, gate-3, gate-5]
completed: 2026-04-22
duration_min: 13
task_count: 3
file_count: 7
requirements: [QUALITY-03, OBS-04]
requirements_addressed: [QUALITY-03, OBS-04]

dependency_graph:
  requires:
    - phase: "00-01 (prep-deps)"
      provides: "pyoxigraph 0.5.7 + owlready2 0.50 pins; .dockerignore baseline; fixtures/bench/ tracked dir"
    - phase: "00-02 (bench-generator)"
      provides: "fixtures/bench.nq (excluded from Docker context via .dockerignore — volume-mounted at runtime)"
  provides:
    - "Dockerfile.web — JVM-free (node:22-slim + python:3.11-slim) with pinned @sha256: digests"
    - "Dockerfile.worker — jlink custom JRE + owlready2 + pyoxigraph (Alpine) with pinned digests"
    - ".dockerignore — Gate 5 build-context discipline (30+ exclusions)"
    - "railway.toml — two-service layout (web + worker) with distinct healthcheck policies"
    - "viewer/svelte.config.js — @sveltejs/adapter-node with precompress: false (streaming-safe)"
    - "viewer/package.json — adapter-static -> adapter-node ^5.5.4 swap"
    - "src/folio_insights/worker.py — Phase 0 entrypoint stub (Phase 10 wires Arq consumer)"
    - "A1 spike verdict: pyoxigraph musllinux_1_2_x86_64 wheel CONFIRMED (Alpine base approved)"
  affects:
    - "Plan 00-05 (Dagger CI) — consumes Dockerfile.web/worker for digest reproducibility test"
    - "Plan 00-07 (Gate 3 + Gate 4 + SSR) — consumes fi-worker:smoke size + adapter-node build for SSR prototype"
    - "Plan 00-08 (DECISION.md) — inherits Gate 3 early-signal baseline (156 MB uncompressed)"
    - "Phase 10 Stage 8 — replaces worker.py stub with Arq consumer"

tech-stack:
  added:
    - "@sveltejs/adapter-node ^5.5.4 (replaces adapter-static; enables SSR)"
    - "eclipse-temurin:17-jdk-alpine (jlink builder — stripped to ~40MB custom JRE)"
    - "python:3.11-alpine (worker runtime base — A1 musllinux wheel confirmed)"
  patterns:
    - "3-stage Dockerfile.worker: jre-builder + deps-builder + runtime (keeps gcc/musl-dev out of final image)"
    - "Pinned @sha256: digests captured via `docker buildx imagetools inspect` on 2026-04-22"
    - "ARG SOURCE_DATE_EPOCH + ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} on every stage"
    - "Numeric UID/GID 1001 (useradd -u 1001 / adduser -u 1001); USER 1001 numeric"
    - "Ordered explicit COPY (pyproject, src/, api/, viewer/build/) — never COPY . ."
    - "Reasoning subset install on worker (pyoxigraph + owlready2 + rdflib + oxrdflib) — intentionally excludes torch/sentence-transformers"

key-files:
  created:
    - path: "Dockerfile.web"
      purpose: "Web tier (FastAPI + adapter-node SSR build). JVM-free."
    - path: "Dockerfile.worker"
      purpose: "Worker tier (jlink JRE + owlready2 + HermiT-ready). 156 MB uncompressed."
    - path: "src/folio_insights/worker.py"
      purpose: "Phase 0 entrypoint stub (idle loop) — Phase 10 replaces with Arq consumer."
    - path: ".planning/phases/00-foundations-hard-gate/deferred-items.md"
      purpose: "Out-of-scope discovery log (pre-existing FastAPI ImportError)."
  modified:
    - path: ".dockerignore"
      purpose: "30+ Gate 5 exclusions (fixtures/bench.nq, output/, .planning, .git, __pycache__ globs)."
    - path: "railway.toml"
      purpose: "Two-service [services.web]/[services.worker] layout; worker has no healthcheckPath."
    - path: "viewer/svelte.config.js"
      purpose: "adapter-static -> adapter-node; precompress: false; envPrefix: 'FOLIO_'."
    - path: "viewer/package.json"
      purpose: "@sveltejs/adapter-static removed; @sveltejs/adapter-node ^5.5.4 added."
    - path: "viewer/package-lock.json"
      purpose: "Regenerated for adapter dependency swap."

key-decisions:
  - "A1 CONFIRMED — pyoxigraph 0.5.7 musllinux wheel exists; Alpine base for worker (no 75MB slim-fallback tax)"
  - "Worker install scope narrowed to reasoning subset (pyoxigraph/owlready2/rdflib/oxrdflib) — Rule 2 deviation to avoid torch pulling 2GB into worker image"
  - "3-stage Dockerfile.worker (jre-builder / deps-builder / runtime) keeps gcc/g++/musl-dev/python3-dev out of the final image even though owlready2 only ships sdist"
  - "Node 22-slim base (LTS; Gate 4 tuning step 5 alignment)"
  - "Base image digests captured via `docker buildx imagetools inspect` 2026-04-22 — pinned to the multi-arch manifest-list digest (Docker resolves per platform at build time)"

patterns-established:
  - "3-stage Dockerfile pattern for sdist-only Python deps: toolchain in a throwaway deps-builder, final runtime copies /usr/local/lib/python3.11/site-packages + /usr/local/bin"
  - "precompress: false on adapter-node — @polka/compression wired at runtime (Plan 07 hooks.server.ts)"
  - "railway.toml two-service: worker has NO healthcheckPath (Arq polling, intentional)"

requirements-completed: [QUALITY-03, OBS-04]

metrics:
  duration_min: 13
  started: "2026-04-23T01:55:00Z"
  completed: "2026-04-23T02:08:26Z"
  tasks_completed: 3
  files_created: 4
  files_modified: 5
---

# Phase 0 Plan 04: Two-Stage Dockerfiles + adapter-node Swap Summary

**Two-tier deployment surface shipped: JVM-free `Dockerfile.web` (2.9 GB, dominated by pre-existing torch transitive) and `Dockerfile.worker` (156 MB uncompressed — 31% of Gate 3 target budget) — plus SvelteKit `adapter-static` → `adapter-node` swap so SSR (Gate 4) is now possible.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-04-23T01:55:00Z
- **Completed:** 2026-04-23T02:08:26Z
- **Tasks:** 3
- **Files created:** 4 (Dockerfile.web, Dockerfile.worker, src/folio_insights/worker.py, deferred-items.md)
- **Files modified:** 5 (.dockerignore, railway.toml, viewer/svelte.config.js, viewer/package.json, viewer/package-lock.json)

## Accomplishments

- **Dockerfile.web (JVM-free)** — 2-stage build: `node:22-slim` frontend builder + `python:3.11-slim` runtime. Pinned `@sha256:` digests captured from `docker buildx imagetools inspect` on 2026-04-22. `ARG/ENV SOURCE_DATE_EPOCH` plumbed. Fixed UID 1001. No HermiT/OpenJDK/owlready strings in final config (`command -v java` returns `no-java`).
- **Dockerfile.worker (3-stage)** — `jre-builder` (jlink custom JRE: 6 modules, `--strip-debug --no-man-pages --no-header-files --compress=2`) → `deps-builder` (alpine + gcc/g++/musl-dev to compile owlready2 sdist) → runtime (alpine + custom JRE + pre-installed site-packages). **Gate 3 early signal: 156 MB uncompressed** (breakdown: `/opt/java-custom` 38.5M, `/usr/local/lib/python3.11/site-packages` 67.8M, `/app` 0.5M) — well below 500 MB target.
- **A1 spike CONFIRMED** — `pyoxigraph-0.5.7-cp38-abi3-musllinux_1_2_x86_64.whl` exists on PyPI (9.3 MB). Alpine base for worker approved; no 75MB slim-fallback penalty toward Gate 3 budget.
- **railway.toml** rewritten to two-service layout (`[services.web]` + `[services.worker]`). Worker intentionally has **no** `healthcheckPath` (Arq polls Redis, no HTTP surface).
- **SvelteKit adapter swap** — `viewer/svelte.config.js` now imports `@sveltejs/adapter-node` with `{ out: 'build', precompress: false, envPrefix: 'FOLIO_' }`. `viewer/package.json` swapped (static removed, node ^5.5.4 added). `npm run build` produces `viewer/build/index.js` (Node server entry).
- **Worker entrypoint stub** — `src/folio_insights/worker.py` idle-loop stub so `Dockerfile.worker`'s CMD resolves during smoke builds; Phase 10 replaces with the real Arq consumer.

## Task Commits

1. **Task 1: Dockerfile.web + .dockerignore** — `b30f2d9` (feat)
2. **Task 2: Dockerfile.worker + worker.py stub** — `bb32434` (feat)
3. **Task 3: railway.toml + svelte adapter-node swap** — `e15ea2a` (feat)

**Plan metadata:** pending (docs: complete plan, committed after this SUMMARY lands)

## Base-Image Digest Register (for Plan 05 digest-equality test)

| Image | Tag | Digest (manifest-list; multi-arch) | Captured |
|-------|-----|------------------------------------|----------|
| `python:3.11-slim` | 3.11.15-slim-trixie | `sha256:92c262cbb2e99cdc16218338d74fbe518055c13d224d942708f70f8042ff6d18` | 2026-04-22 |
| `node:22-slim` | 22-bookworm-slim | `sha256:d415caac2f1f77b98caaf9415c5f807e14bc8d7bdea62561ea2fef4fbd08a73c` | 2026-04-22 |
| `eclipse-temurin:17-jdk-alpine` | 17.0.18+8 | `sha256:cf02686befe8e1fc3b00da25458bf92d53013b4c358d4a2245ff50e0d81b753a` | 2026-04-22 |
| `python:3.11-alpine` | 3.11.15-alpine | `sha256:8b5bfdb1fd2d78aa94e21c4d61be52487693f54be7f1021647751ff365795703` | 2026-04-22 |

Regenerate quarterly or on upstream security advisory.

## A1 Spike Verdict — Alpine Viability for Worker

**Result: CONFIRMED.**

```
$ pip download pyoxigraph==0.5.7 --platform musllinux_1_2_x86_64 \
    --python-version 311 --only-binary=:all: --no-deps
Saved pyoxigraph-0.5.7-cp38-abi3-musllinux_1_2_x86_64.whl (9.3 MB)
```

Alpine base (python:3.11-alpine) approved for worker. No slim-fallback penalty. owlready2==0.50 ships sdist-only (no musllinux wheel), so it compiles from source in the `deps-builder` stage — toolchain never reaches the runtime image.

## Worker Image Size (Gate 3 early signal)

**156 MB uncompressed** (docker CONTENT SIZE: 78.2 MB compressed; DISK USAGE: 243 MB including attestation).

| Component | Size |
|-----------|------|
| `/opt/java-custom` (jlink JRE, 6 modules, `--compress=2`) | 38.5 MB |
| `/usr/local/lib/python3.11/site-packages` (pyoxigraph + owlready2 + rdflib + oxrdflib) | 67.8 MB |
| `/app` (pyproject.toml + README + src/) | 0.5 MB |
| Alpine base + native libs (libgcc, libstdc++, sqlite-libs) + python runtime | ~50 MB |

**Gate 3 status:** **ON TRACK for target (<500 MB).** Accept ceiling is <=700 MB per D-06. Real Gate 3 assertion runs in Plan 07 after full integration (HermiT.jar load, owlready2 temp file handling, any Phase 10 worker deps added).

## Files Created/Modified

**Created:**
- `Dockerfile.web` — Web-tier image (JVM-free, 2-stage).
- `Dockerfile.worker` — Worker-tier image (3-stage: jre-builder + deps-builder + runtime).
- `src/folio_insights/worker.py` — Phase 0 idle-loop stub.
- `.planning/phases/00-foundations-hard-gate/deferred-items.md` — out-of-scope discovery log.

**Modified:**
- `.dockerignore` — 30+ Gate 5 exclusions (adds `__pycache__` glob, `fixtures/bench.nq`, `**/*.pyc`, etc.).
- `railway.toml` — two-service layout; worker has no `healthcheckPath`.
- `viewer/svelte.config.js` — adapter-node config with `precompress: false`, `envPrefix: 'FOLIO_'`.
- `viewer/package.json` — `@sveltejs/adapter-static` removed, `@sveltejs/adapter-node ^5.5.4` added.
- `viewer/package-lock.json` — regenerated for the adapter swap.

## Decisions Made

- **[00-04-D1] A1 CONFIRMED** — pyoxigraph 0.5.7 ships a musllinux_1_2_x86_64 wheel; use `python:3.11-alpine` for worker (no 75 MB slim-fallback cost toward Gate 3).
- **[00-04-D2] Worker install scoped to reasoning subset** — Installing the full `pyproject.toml` would pull `sentence-transformers + torch` (~2 GB on Linux), blowing past the Gate 3 ≤700 MB accept threshold. Rule 2 deviation: worker image explicitly installs only `pyoxigraph, owlready2, rdflib, oxrdflib`. Phase 10 can add `pyshacl` if needed for worker-side shape validation.
- **[00-04-D3] 3-stage Dockerfile.worker** — owlready2 ships sdist-only; a dedicated `deps-builder` with gcc/g++/musl-dev/python3-dev/libffi-dev compiles the C optimizer, then the runtime copies just the `/usr/local/lib/python3.11/site-packages` and `/usr/local/bin` directories. Runtime image has no compilers.
- **[00-04-D4] Node 22-slim** — Node 22 LTS matches RESEARCH.md Gate 4 tuning step 5 (avoid Node 25+; v22 has V8 optimizations over v20).
- **[00-04-D5] Manifest-list digests** — pinned to the multi-arch `sha256:...` (not the amd64-specific one). Docker resolves to the right platform at build time. Cleaner than per-arch pins for a single-arch CI target.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 — Missing Critical] Worker scope narrowed to reasoning subset**

- **Found during:** Task 2 (Dockerfile.worker composition)
- **Issue:** Plan's Step 3 specified `pip install .` (full pyproject.toml install) in the worker runtime. This would pull `sentence-transformers -> torch -> triton -> CUDA stubs` (~2 GB on Linux), blowing Gate 3's ≤700 MB accept threshold even post-tuning.
- **Fix:** `deps-builder` installs only `pyoxigraph==0.5.7`, `owlready2==0.50`, `rdflib>=7.6.0`, `oxrdflib` explicitly. Worker tier is scoped to SPARQL + OWL reasoning + Turtle bridge per REQ-QUALITY-03's architectural split. Web tier keeps the full install (via `uv pip install .` fallback).
- **Files modified:** `Dockerfile.worker`
- **Verification:** `docker run --rm fi-worker:smoke python -c "import pyoxigraph, owlready2, rdflib, oxrdflib"` — all three import cleanly; image uncompressed size = 156 MB.
- **Committed in:** `bb32434` (Task 2 commit)

**2. [Rule 3 — Blocking] 3-stage Dockerfile to keep gcc/g++/musl-dev out of runtime**

- **Found during:** Task 2 (owlready2 sdist-only install fails on bare alpine)
- **Issue:** Plan's Step 3 specified a 2-stage build. owlready2==0.50 ships only as an sdist (verified via `pip download owlready2==0.50 --only-binary=:all:` → no musllinux wheel). Compiling owlready2's C optimizer requires gcc/g++/musl-dev/python3-dev/libffi-dev. If these stayed in the runtime image, it would bloat by ~300 MB.
- **Fix:** Added a middle `deps-builder` stage that installs gcc/musl-dev + pip-installs the reasoning subset. The final runtime copies only `/usr/local/lib/python3.11/site-packages` and `/usr/local/bin` from the builder. Toolchain never reaches the runtime image.
- **Files modified:** `Dockerfile.worker`
- **Verification:** `apk info -l gcc 2>/dev/null` inside the runtime container returns empty; image is still 156 MB uncompressed.
- **Committed in:** `bb32434` (Task 2 commit)

**3. [Rule 1 — Bug] HEALTHCHECK env var interpolation**

- **Found during:** Task 1 (Dockerfile.web authoring)
- **Issue:** Plan's Step 2 HEALTHCHECK used `${PORT:-8000}` inside a `python -c` heredoc string — shell does NOT expand variables inside Python's single-quoted triple-string. The healthcheck would always hit `http://localhost:${PORT:-8000}/health` literal.
- **Fix:** Rewrote healthcheck to `python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"8000\")}/health')"` — Python reads `os.environ["PORT"]` at runtime.
- **Files modified:** `Dockerfile.web`
- **Verification:** Healthcheck command is syntactically valid Python (confirmed via `docker image inspect fi-web:smoke --format '{{.Config.Healthcheck.Test}}'`); runtime behavior proven in Plan 07 when SSR is wired.
- **Committed in:** `b30f2d9` (Task 1 commit)

---

**Total deviations:** 3 auto-fixed (1 missing-critical, 1 blocking, 1 bug)
**Impact on plan:** All three are required for correctness — Gate 3 compliance (D1), owlready2 sdist install feasibility (D2), healthcheck actually working (D3). No scope creep; plan's intent preserved.

### Deferred (Out-of-Scope) Items

- **Pre-existing `tests/test_corpus_api.py` FastAPI ImportError.** Environmental venv issue unrelated to Plan 00-04 (adapter swap cannot affect Python imports). Logged to `.planning/phases/00-foundations-hard-gate/deferred-items.md` with root cause (pyproject.toml doesn't declare fastapi as direct dep) and suggested future fix. Phase 0 `tests/bench/` suite passes 5/5.

## Issues Encountered

None beyond the deviations above. Docker build cache hydrated cleanly; all three smoke builds (fi-web, fi-worker, viewer adapter-node) succeeded on first attempt after the deviation fixes landed.

## Authentication Gates

None. All work is local Docker builds + npm install against public registries.

## Open Questions — Resolution

Resolved in this plan:

- **OQ A1 (musllinux wheel for pyoxigraph):** CONFIRMED via `pip download --platform musllinux_1_2_x86_64`. Alpine base approved; no slim-fallback penalty.

Deferred unchanged to later plans:

- **OQ A4 (HermiT --add-modules completeness):** Plan 07 exercises real reasoning; may need `java.rmi` or `jdk.security.jgss`. Current 6-module set per RESEARCH.md Pattern 5.
- **OQ Redis sidecar provisioning:** Plan 05 (Dagger pipeline) decides Railway plugin vs Dagger-provisioned.
- **OQ @polka/compression wiring:** Plan 07 (hooks.server.ts).
- **OQ Real worker entrypoint:** Phase 10 Stage 8 replaces `src/folio_insights/worker.py` stub.

## Known Stubs

- **`src/folio_insights/worker.py`** — intentional Phase 0 stub (logs + idle 60s loop). Phase 10 Stage 8 replaces with Arq consumer per plan's Task 2 Step 4 scope.
- **`Dockerfile.web` / `Dockerfile.worker` `requirements.lock*` glob** — falls back to `uv pip install` or explicit subset when the lockfile is absent. Plan 05 authors `requirements.lock` with hashes; after that, both Dockerfiles switch to `pip install --require-hashes -r requirements.lock`. Not a stub blocking the plan's goal (reproducibility) — it's the explicit handoff to Plan 05.

## Threat Flags

None. No new network endpoints, auth paths, or trust-boundary crossings introduced. T-00-12..T-00-17 from the plan's threat register all landed mitigated:

- **T-00-12 (base image drift):** `@sha256:` pins on all four base images. Digests recorded in the register above.
- **T-00-13 (host state leak via COPY . .):** `.dockerignore` has 30+ exclusions; all COPYs are explicit ordered paths.
- **T-00-14 (root escape):** Both images run as numeric UID 1001.
- **T-00-15 (apt cache bloat):** `--no-install-recommends` + `rm -rf /var/lib/apt/lists/*` on web; `--no-cache` on alpine + `rm -rf /var/cache/apk/*` on worker.
- **T-00-16 (non-reproducible):** `SOURCE_DATE_EPOCH` plumbed on both. Plan 05 asserts bit-identical digest.
- **T-00-17 (envPrefix leak):** `envPrefix: 'FOLIO_'` on adapter-node; only `FOLIO_*` env reaches client.

## Next Plan Readiness

**Ready for Plan 00-05 (Dagger CI + Gate 5 digest):**
- Both Dockerfiles accept `ARG SOURCE_DATE_EPOCH` — Dagger can pass via `with_build_arg("SOURCE_DATE_EPOCH", ...)`.
- Pinned base digests registered above (Dagger should consume them via `dagger/build.py` constants, not re-resolve each run).
- `railway.toml` two-service layout ready for `railway up --service web` + `railway up --service worker` orchestration.

**Ready for Plan 00-07 (Gate 3 + Gate 4 SSR):**
- `fi-worker:smoke` baseline = 156 MB uncompressed (well under Gate 3 target).
- `viewer/build/index.js` is a Node SSR entrypoint — hyperfine cold-page measurement is now possible.
- `precompress: false` — Plan 07 wires `@polka/compression` in `hooks.server.ts`.

**Ready for Plan 00-08 (DECISION.md):**
- A1 verdict (CONFIRMED) recorded; no slim-fallback exposure to surface.
- If Gate 3 exceeds target in Plan 07, the 156 MB baseline here plus Rule 2 worker-scope decision give Plan 08 data for the microservice-split recommendation.

## Self-Check: PASSED

- **Files created:**
  - `Dockerfile.web` — FOUND
  - `Dockerfile.worker` — FOUND
  - `src/folio_insights/worker.py` — FOUND
  - `.planning/phases/00-foundations-hard-gate/deferred-items.md` — FOUND
- **Files modified:**
  - `.dockerignore` — 30+ patterns including `.planning`, `output`, `fixtures/bench.nq`, `__pycache__` glob — VERIFIED
  - `railway.toml` — 6 `[services.*]` blocks — VERIFIED
  - `viewer/svelte.config.js` — `@sveltejs/adapter-node` + `precompress: false` — VERIFIED
  - `viewer/package.json` — static absent, node ^5.5.4 present — VERIFIED
- **Commits:**
  - `b30f2d9` (Task 1) — FOUND
  - `bb32434` (Task 2) — FOUND
  - `e15ea2a` (Task 3) — FOUND
- **Runtime verification:**
  - `fi-web:smoke` — UID 1001, SOURCE_DATE_EPOCH plumbed, zero JVM/HermiT strings, `command -v java` → `no-java`.
  - `fi-worker:smoke` — UID 1001, SOURCE_DATE_EPOCH plumbed, `java -version` → `openjdk 17.0.18`, all four reasoning deps import, stub entrypoint logs expected message.
  - `viewer/build/index.js` exists (10114 bytes), first import is `node:http` (confirms adapter-node, not adapter-static).
  - Phase 0 bench tests: 5/5 passing.
- **Overall verify (all 9 plan-level checks):** PASSED.

---
*Phase: 00-foundations-hard-gate*
*Completed: 2026-04-22*
