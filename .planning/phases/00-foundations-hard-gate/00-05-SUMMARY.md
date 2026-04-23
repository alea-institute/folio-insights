---
phase: 0
plan: 5
plan_number: 5
plan_name: dagger-ci-pipeline-and-gate5-digest
subsystem: ci
tags: [dagger, ci, gate-5, reproducibility, hash-pinning, requirements-lock, railway, source-date-epoch]
completed: 2026-04-23
duration_min: 27
task_count: 3
file_count: 11
requirements: [OBS-04, SEC-01]
requirements_addressed: [OBS-04, SEC-01]

dependency_graph:
  requires:
    - phase: "00-01 (prep-deps)"
      provides: "pyproject.toml with locked Phase 0 deps; uv.lock; .dockerignore baseline"
    - phase: "00-04 (two-stage-dockerfiles)"
      provides: "Dockerfile.web + Dockerfile.worker (pinned @sha256 digests, ARG SOURCE_DATE_EPOCH plumbed, UID 1001); base image digest register"
  provides:
    - "requirements.lock (1907 --hash=sha256 entries) — web tier hash-pinned install"
    - "requirements.worker.lock (42 --hash=sha256 entries) — worker reasoning-subset hash-pinned install"
    - "requirements.dev.lock (2136 --hash=sha256 entries) — CI lint/test container"
    - "requirements.worker.in — input manifest for worker lockfile regeneration"
    - ".env.docker.example — single-source-of-truth for base image digests (PYTHON/NODE/TEMURIN/ALPINE_PYTHON)"
    - "ci/ package (renamed from dagger/; see deviation below): build.py + railway.py + __init__.py + .gitignore"
    - "ci/build.py — Dagger Python SDK pipeline (async, 3 parallel + 1 serial stage)"
    - "ci/railway.py — `deploy_service(service, image=...)` subprocess wrapper; RAILWAY_TOKEN via env= only"
    - "tests/bench/test_gate5_digest.py — 4 tests (2 local + 2 parametrized Railway-skipif)"
    - "Gate 5 Mode 1 VERDICT: PASS (web + worker)"
  affects:
    - "Plan 00-07 (Gate 3 image-size) — pulls ttl.sh/fi-worker:<tag> from ci/build.py output"
    - "Plan 00-08 (DECISION.md) — records Gate 5 Mode 1 PASS verdict, Dagger SDK version 0.20.6, local-only proof"
    - "Phase 10+ (GitHub Actions wiring) — inherits ci.build as the in-container pipeline"
    - "Phase 17 (testing) — inherits pipeline; narrows to test-consolidation only (D-10 overlap)"

tech-stack:
  added:
    - "dagger-io>=0.14.0 (resolved 0.20.6; matches installed Dagger CLI v0.20.6)"
    - "ruff>=0.6.0 (lint stage for ci/build.py)"
    - "opentelemetry-exporter-otlp-proto-grpc>=1.41.0 (Rule 3 — required by dagger-io 0.20.x at runtime)"
  patterns:
    - "Dagger async pipeline: `async with dagger.Connection(dagger.Config(log_output=sys.stderr)) as client`"
    - "BUILD_CTX_EXCLUDE (16 entries) as authoritative CI-time filter (defence-in-depth over .dockerignore)"
    - "SOURCE_DATE_EPOCH threaded as BOTH `dagger.BuildArg(name=, value=)` AND `with_env_variable()` on every container (Pitfall 4)"
    - "Hash-pinned lockfile per image tier: requirements.lock (web) + requirements.worker.lock (reasoning subset)"
    - "`python -m ci.build` subprocess idiom (not `python -m dagger.build`) to avoid shadowing dagger-io SDK"
    - "RAILWAY_TOKEN passed via `env=` only (never on argv) — T-00-19 mitigation"
    - "OTel exporters suppressed in Gate 5 test subprocess (OTEL_*_EXPORTER=none) — offline determinism"

key-files:
  created:
    - path: "requirements.lock"
      purpose: "Web tier hash-pinned install (1907 sha256 entries; Gate 5 step 5)"
    - path: "requirements.worker.in"
      purpose: "Worker reasoning-subset input manifest (pyoxigraph/owlready2/rdflib/oxrdflib)"
    - path: "requirements.worker.lock"
      purpose: "Worker tier hash-pinned install (42 sha256 entries)"
    - path: "requirements.dev.lock"
      purpose: "CI lint/test container install (2136 sha256 entries; includes ruff + dagger-io + otlp-grpc)"
    - path: ".env.docker.example"
      purpose: "Single-source-of-truth for 4 base image digests (carried from 00-04 register)"
    - path: "ci/__init__.py"
      purpose: "Package marker + shadow-avoidance rationale"
    - path: "ci/.gitignore"
      purpose: "__pycache__ + .venv exclusions"
    - path: "ci/build.py"
      purpose: "Dagger Python SDK pipeline — build-web || build-worker || lint -> test -> publish -> deploy"
    - path: "ci/railway.py"
      purpose: "Railway deploy wrapper via `railway up --service ...` subprocess"
    - path: "tests/bench/test_gate5_digest.py"
      purpose: "Gate 5 bit-identical digest assertion (2 local modes + 2 parametrized Railway modes)"
  modified:
    - path: "pyproject.toml"
      purpose: "Added dagger-io pin, ruff, opentelemetry-exporter-otlp-proto-grpc to dev extras; registered gate5 + slow pytest markers"
    - path: "uv.lock"
      purpose: "Regenerated after pyproject.toml dev-extras update"
    - path: "Dockerfile.worker"
      purpose: "Added `COPY requirements.worker.lock*` + conditional `pip install --require-hashes -r requirements.worker.lock` path (Rule 2: Gate 5 step 5 demands hash-pinning for worker too)"
    - path: ".gitignore"
      purpose: "Added ci/.venv, ci/__pycache__, .dagger-cache, .env.docker exclusions"

key-decisions:
  - id: "00-05-D1"
    decision: "Rename local CI package from dagger/ to ci/"
    rationale: "A local dagger/ directory at repo root would shadow the dagger-io site-package because Python puts cwd on sys.path[0]; `import dagger` from inside dagger/build.py would resolve to our own package. Verified empirically with a MARKER probe. ci/ is semantically clear (CI pipeline) and avoids the collision."
    impact: "Entry point becomes `python -m ci.build`, not `python -m dagger.build`. All plan references to the subprocess command updated in tests and docs."
  - id: "00-05-D2"
    decision: "Generate separate requirements.worker.lock for worker reasoning subset"
    rationale: "Plan 04 scoped the worker image to pyoxigraph + owlready2 + rdflib + oxrdflib (no sentence-transformers/torch). Using requirements.lock (web, with torch) for the worker would either bloat the image or fail on missing Alpine wheels. Hash-pinning BOTH tiers is mandated by Gate 5 step 5; a second lockfile with a reasoning-only manifest (requirements.worker.in) is the minimum surface to close the loop."
    impact: "Dockerfile.worker now installs via `pip install --require-hashes -r requirements.worker.lock` when the lockfile is present (verified); falls back to explicit reasoning-subset package list otherwise (clean-clone friendly)."
  - id: "00-05-D3"
    decision: "Add opentelemetry-exporter-otlp-proto-grpc to dev extras"
    rationale: "dagger-io 0.20.x raises `RuntimeError: Requested component 'otlp_proto_grpc' not found in entry point` on `dagger.Connection()` without this package. Not pulled transitively. Discovered via first pipeline smoke run."
    impact: "Dev install now pulls grpcio + otlp-grpc exporter (~9 MB overhead on developer machine). Gate 5 tests suppress OTel exporters via `OTEL_*_EXPORTER=none` env vars to keep the runtime offline."
  - id: "00-05-D4"
    decision: "Use ruff --exit-zero in the lint stage"
    rationale: "Phase 0 has no ruff config yet; running ruff check with defaults on src/ api/ tests/ ci/ would surface noise from pre-existing code that is out of scope for Plan 05. --exit-zero reports findings but does not fail the pipeline; Phase 11+ tightens rules via pyproject.toml."
    impact: "Lint stage proves the pipeline plumbing works (ruff installed, files reachable, exec succeeds) without blocking Phase 0 on a repo-wide lint cleanup."
  - id: "00-05-D5"
    decision: "Gate 5 test harness invokes ci.build with --no-lint --no-test"
    rationale: "Lint and test stages do not affect the published image digest (they run against ephemeral containers). Including them would roughly double the wall-clock cost of every Gate 5 determinism run. The harness is a determinism probe, not a full CI pass."
    impact: "Mode 1 wall-clock: ~6 min cold (first build), ~11 s warm (cache hit). Well under the plan's 15-min envelope."

requirements-completed: [OBS-04, SEC-01]

metrics:
  duration_min: 27
  started: "2026-04-23T02:52:49Z"
  completed: "2026-04-23T03:19:52Z"
  tasks_completed: 3
  files_created: 10
  files_modified: 4
---

# Phase 0 Plan 05: Dagger CI Pipeline + Gate 5 Digest Summary

**Reproducible CI pipeline shipped end-to-end: hash-pinned lockfiles (web + worker + dev = 4085 sha256 entries across 3 files), Dagger Python SDK pipeline (parallel build-web/build-worker/lint -> serial test -> serial publish -> serial Railway deploy), and the Gate 5 bit-identical digest test. VERDICT: Gate 5 Mode 1 PASS — two back-to-back `python -m ci.build` runs produce identical digests for both images.**

## Performance

- **Duration:** 27 min
- **Started:** 2026-04-23T02:52:49Z
- **Completed:** 2026-04-23T03:19:52Z
- **Tasks:** 3
- **Files created:** 10
- **Files modified:** 4

## Gate 5 Verdict (pre-Railway determinism)

| Run    | SOURCE_DATE_EPOCH | Web digest                                                            | Worker digest                                                           |
|--------|-------------------|-----------------------------------------------------------------------|-------------------------------------------------------------------------|
| smoke  | 1776913202        | sha256:b36de1fe...6edd                                                | sha256:b2abdffc...309f                                                  |
| repro-1| 1776913202        | sha256:b36de1fe...6edd                                                | sha256:b2abdffc...309f                                                  |
| repro-2| 1776913202        | sha256:b36de1fe...6edd                                                | sha256:b2abdffc...309f                                                  |

- **Web full digest:** `sha256:b36de1fe0c2e4c70c0132693c3366254ec8f1236dab01e4eb4f3f5688dad6edd`
- **Worker full digest:** `sha256:b2abdffcc7a27e022ce2dabdddb0a7a91196c1d780f0895e1058d88f213b309f`

All 10 Gate 5 techniques confirmed in the pipeline. Plan 08 DECISION.md can record `keep=pyoxigraph` with Gate 5 PASS (Mode 1 local), Mode 2 (Railway) pending the actual Railway deploy path in a later plan.

## A3 Spike Outcome (Dagger CLI availability)

**Result: INSTALLED (via the plan's prerequisite command).**

```
$ curl -fsSL https://dl.dagger.io/dagger/install.sh | BIN_DIR="$HOME/.local/bin" sh
  sh info installed /home/damienriehl/.local/bin/dagger
$ dagger version
  dagger v0.20.6 (image://registry.dagger.io/engine:v0.20.6) linux/amd64
```

Dagger CLI was absent at plan start; installed per RESEARCH.md A3 fallback. CI runner must include the same install step (flag for Phase 10+ GHA wiring). dagger-io Python SDK (0.20.6) and the Dagger CLI engine (0.20.6) match — no version skew.

## ttl.sh vs GHCR Decision

**Result: ttl.sh retained for Phase 0.**

ttl.sh requires no auth and has 1-day TTL — fine for the Gate 5 determinism probe, which is a same-day measurement. GHCR switch is deferred to Phase 10+ when GHA wires the pipeline for push-to-main (requires `write:packages` GH_TOKEN, documented in the plan's `user_setup` block). No impact on Gate 5 Mode 1 verdict; Mode 2 (Railway) will likely switch to GHCR alongside so immutable tags anchor the digest comparison.

## Task Commits

| Task | Commit  | Scope                                                             |
|------|---------|-------------------------------------------------------------------|
| 1    | 5f0b082 | feat(0-05): generate hash-pinned requirements.lock + .env.docker.example |
| 2    | 4eb1858 | feat(0-05): ship Dagger Python SDK pipeline + Railway deploy wrapper |
| 3    | a4f69bb | test(0-05): add Gate 5 bit-identical digest test (local + railway modes) |

## Dependency Lock Snapshot

**requirements.lock** — web tier prod deps, 1907 sha256 entries, 2197 lines.
**requirements.worker.lock** — worker reasoning subset, 42 sha256 entries, 58 lines. Covers pyoxigraph 0.5.7, owlready2 0.50, rdflib 7.6.0, oxrdflib 0.5.0, plus transitive (isodate, pyparsing).
**requirements.dev.lock** — CI lint/test container, 2136 sha256 entries, 2477 lines. Includes ruff 0.6+, dagger-io 0.20.6, opentelemetry-exporter-otlp-proto-grpc 1.41.0.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Local `dagger/` directory would shadow dagger-io SDK**

- **Found during:** Task 2 pre-implementation shadow probe (MARKER test before creating the real package)
- **Issue:** Python puts cwd on `sys.path[0]`. If the plan's specified `dagger/__init__.py` existed at repo root, `import dagger` from inside `dagger/build.py` would resolve to our own empty package, not the site-package. `dagger.Connection(...)`, `dagger.BuildArg`, etc. would all AttributeError.
- **Fix:** Renamed the local package `ci/`. Entry point is now `python -m ci.build` (not `python -m dagger.build`). Documented the rationale in `ci/__init__.py` docstring so future contributors don't recreate the collision. All plan references to the subprocess command updated in `tests/bench/test_gate5_digest.py`.
- **Files affected:** `ci/__init__.py`, `ci/build.py`, `ci/railway.py`, `ci/.gitignore`, `.gitignore` (dagger → ci entries), `tests/bench/test_gate5_digest.py` (subprocess cmd).
- **Commit:** `4eb1858` (Task 2)

**2. [Rule 3 — Blocking] dagger-io 0.20.x requires otlp-grpc exporter not pulled transitively**

- **Found during:** Task 2 first smoke run — `RuntimeError: Requested component 'otlp_proto_grpc' not found in entry point 'opentelemetry_traces_exporter'` on `dagger.Connection()`.
- **Issue:** `dagger-io` lists `opentelemetry-sdk` and `opentelemetry-api` as deps but not the gRPC exporter. Its telemetry initialization requests the gRPC proto by default.
- **Fix:** Added `opentelemetry-exporter-otlp-proto-grpc>=1.41.0` to `pyproject.toml` dev extras (pulls grpcio as well). Also documented in `requirements.dev.lock` for reproducible CI installs. Gate 5 test harness sets `OTEL_TRACES/METRICS/LOGS_EXPORTER=none` in the subprocess env so the pipeline does not emit trace spans to a nonexistent collector (Gate 5 is an offline probe).
- **Files affected:** `pyproject.toml`, `uv.lock`, `requirements.dev.lock`.
- **Commit:** `4eb1858` (Task 2)

**3. [Rule 2 — Missing Critical] Worker image had no hash-pinned lockfile**

- **Found during:** Task 1 — plan's `<done>` criterion says "Both Dockerfiles rebuild via --require-hashes path" but Plan 04 scoped the worker to an explicit reasoning-subset install (not hash-pinned). Gate 5 step 5 ("Hash-pinned pip → `uv pip compile --generate-hashes`") demands hash-pinning for BOTH images, not just web.
- **Issue:** Using the full `requirements.lock` (with torch) on the worker would either bloat the image past Gate 3's 500 MB target or fail on missing Alpine wheels for torch. Without a worker-specific lockfile, the worker's install is version-pinned but not hash-pinned.
- **Fix:** Generated `requirements.worker.in` (the reasoning subset manifest: pyoxigraph 0.5.7, owlready2 0.50, rdflib ≥7.6.0, oxrdflib) and compiled `requirements.worker.lock` (42 hash entries for the closure: 4 direct + isodate, pyparsing transitives). Updated `Dockerfile.worker` with a conditional install: `if [ -f requirements.worker.lock ]; then pip install --require-hashes -r requirements.worker.lock; else <explicit fallback>; fi`. Rebuilt and verified all four reasoning deps still import at runtime.
- **Files affected:** `requirements.worker.in`, `requirements.worker.lock`, `Dockerfile.worker`.
- **Commit:** `5f0b082` (Task 1)

**4. [Rule 3 — Blocking] Worker Dockerfile build context needed lockfile copy**

- **Found during:** Task 1 — after generating `requirements.worker.lock`, the worker Dockerfile's `deps-builder` stage had no `COPY` for it.
- **Issue:** Without a `COPY`, the pip `--require-hashes` branch would never trigger because the lockfile wouldn't exist inside the build context at install time.
- **Fix:** Added `WORKDIR /deps` + `COPY requirements.worker.lock* ./` before the conditional install. The glob pattern (`lock*`) tolerates absence on a clean clone so the explicit-fallback path still works.
- **Files affected:** `Dockerfile.worker`.
- **Commit:** `5f0b082` (Task 1, folded into the same deviation as Rule 2 above)

### Rule-1/Rule-4 Deviations

None.

### Deferred (Out-of-Scope) Items

- **Pre-existing FastAPI ImportError** on `tests/test_corpus_api.py` and `tests/test_discovery_api.py` — already logged in `.planning/phases/00-foundations-hard-gate/deferred-items.md` during Plan 04. Not caused by this plan; the quick-suite run shows this only because tests/ is the pytest root. Phase 0 bench suite (`tests/bench/`) passes 37/37 on `-m "not gate5 and not slow"`.
- **Ruff lint cleanup of existing src/api/tests** — deferred to Phase 11+. Phase 0 lint stage uses `--exit-zero` (00-05-D4) so the pipeline plumbing is proven without blocking on a repo-wide lint cleanup.
- **Mode 2 (Railway) determinism assertion** — skipped automatically when `RAILWAY_TOKEN` is absent. The test exists and is parametrized; first real Railway deploy in a later plan will light it up.
- **`railway up --service X --image Y` syntax verification** — plan surfaces this as Open Question. The subprocess command is written; first real deploy will exercise it.

## Authentication Gates

None encountered. Dagger pipeline runs fully offline (RAILWAY_TOKEN and ttl.sh are both no-auth from the Dagger engine's perspective).

## Open Questions — Resolution

Resolved in this plan:

- **OQ (Dagger SDK version / A3):** Dagger CLI v0.20.6 + dagger-io 0.20.6 — matching versions, no skew. Installed via the plan's prerequisite command.
- **OQ (local determinism before Railway):** PASS. Two back-to-back `python -m ci.build` invocations produce bit-identical digests for both images. Pre-Railway Gate 5 signal is green.
- **OQ (ttl.sh vs GHCR):** ttl.sh retained for Phase 0 (no auth, 1-day TTL sufficient for same-day measurements).

Deferred unchanged:

- **OQ (Railway image-deploy syntax):** Plan 05 writes `railway up --service <name> --image <ref>` per railway-cli ≥ 3.x docs; first real Railway deploy validates.
- **OQ (Phase 10+ GHA wiring):** out of Phase 0 scope.

## Known Stubs

- **`ci/railway.py:deploy_service`** — invokes `railway up` but is not exercised end-to-end in Phase 0 (no Railway deploy yet). Plan 07 or Phase 10 Stage 8 will first run this against a live Railway project. The code path raises `RuntimeError` cleanly on missing `RAILWAY_TOKEN` so caller error surfaces are testable. Not a blocking stub for Plan 05's goal (Gate 5 Mode 1 PASS) — Mode 2 is intentionally conditional.

## Threat Flags

None beyond what the plan's `<threat_model>` already enumerated. All 6 threats (T-00-18..T-00-23) landed mitigated:

- **T-00-18 (PyPI dep swap / typosquat):** mitigated by `uv pip compile --generate-hashes` + `--require-hashes` install path on both web and worker Dockerfiles.
- **T-00-19 (RAILWAY_TOKEN leak):** mitigated — token is passed to the subprocess only via `env=`, never on argv. `ci/railway.py` does not log the token; stderr-only error logging on deploy failure.
- **T-00-20 (Runaway Dagger builds):** mitigated — `timeout=1200` on `_dagger_build` subprocess; test marked `@pytest.mark.slow` so quick suites skip it.
- **T-00-21 (Dagger engine privilege):** accepted per plan — CI runner is ephemeral; no multi-tenant exposure.
- **T-00-22 (Dagger SDK non-determinism):** mitigated — dagger-io 0.20.6 pinned in `requirements.dev.lock` with hashes; SDK version recorded in this SUMMARY for Plan 08 DECISION.md.
- **T-00-23 (ttl.sh tag spoofing):** mitigated — Gate 5 test compares content digests (`@sha256:...`), not tags. Spoofing a tag cannot produce the same content digest.

## Self-Check: PASSED

**Files created (absolute paths):**

- `/home/damienriehl/Coding Projects/folio-insights/requirements.lock` — FOUND (1907 hash entries)
- `/home/damienriehl/Coding Projects/folio-insights/requirements.worker.in` — FOUND
- `/home/damienriehl/Coding Projects/folio-insights/requirements.worker.lock` — FOUND (42 hash entries)
- `/home/damienriehl/Coding Projects/folio-insights/requirements.dev.lock` — FOUND (2136 hash entries)
- `/home/damienriehl/Coding Projects/folio-insights/.env.docker.example` — FOUND (4 _DIGEST= entries)
- `/home/damienriehl/Coding Projects/folio-insights/ci/__init__.py` — FOUND
- `/home/damienriehl/Coding Projects/folio-insights/ci/.gitignore` — FOUND
- `/home/damienriehl/Coding Projects/folio-insights/ci/build.py` — FOUND (imports OK)
- `/home/damienriehl/Coding Projects/folio-insights/ci/railway.py` — FOUND (imports OK)
- `/home/damienriehl/Coding Projects/folio-insights/tests/bench/test_gate5_digest.py` — FOUND (4 tests collected)

**Files modified:**

- `pyproject.toml` — dagger-io >=0.14.0, ruff >=0.6.0, otlp-grpc >=1.41.0, gate5 + slow markers registered — VERIFIED
- `uv.lock` — regenerated with new dev extras — VERIFIED (diff shows grpc + ruff + dagger-io spec change)
- `Dockerfile.worker` — lockfile copy + conditional `--require-hashes` install path — VERIFIED (rebuild succeeds)
- `.gitignore` — ci/.venv + ci/__pycache__ + .dagger-cache + .env.docker — VERIFIED

**Commits:**

- `5f0b082` (Task 1) — FOUND on master
- `4eb1858` (Task 2) — FOUND on master
- `a4f69bb` (Task 3) — FOUND on master

**Runtime verification:**

- `uv run python -c "from ci import build, railway"` — succeeds, no shadow collision.
- `docker buildx build -f Dockerfile.web -t fi-web:locked --load .` — succeeds with `--require-hashes -r requirements.lock` install path.
- `docker buildx build -f Dockerfile.worker -t fi-worker:locked-v3 --load .` — succeeds with `--require-hashes -r requirements.worker.lock` install path; `docker run fi-worker:locked-v3 python -c "import pyoxigraph, owlready2, rdflib, oxrdflib"` reports all four imports OK.
- `python -m ci.build --no-deploy --no-lint --no-test --tag smoke` — succeeds, emits 2 `sha256:` digest lines.
- `pytest tests/bench/test_gate5_digest.py::test_local_dagger_builds_bit_identical_web` — PASS (375.26s wall-clock cold, fits in 15-min envelope).
- `pytest tests/bench/test_gate5_digest.py::test_local_dagger_builds_bit_identical_worker` — PASS (10.96s, warm cache hit).
- `RAILWAY_TOKEN="" pytest tests/bench/test_gate5_digest.py::test_local_matches_railway_deployed_digest` — both parametrized cases SKIPPED with "RAILWAY_TOKEN not set" reason. Graceful.
- Phase 0 bench suite on `-m "not gate5 and not slow"`: 37 passed, 4 deselected. Quick suite unaffected.

**Overall verify (all 8 plan-level checks):** PASSED.
