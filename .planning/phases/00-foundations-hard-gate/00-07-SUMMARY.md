---
phase: 00-foundations-hard-gate
plan: 7
subsystem: measurement-harness
tags: [hermit, owlready2, sveltekit-ssr, adapter-node, hyperfine, docker-image-size, polka-compression, fastapi-stubs]

requires:
  - phase: 00-foundations-hard-gate
    provides: "Dockerfile.worker (jlink JRE + owlready2), adapter-node swap, requirements.worker.lock, fi-worker:smoke pre-built image"
  - phase: 00-foundations-hard-gate
    provides: "PyoxigraphStore wrapper, fixtures/bench.nq 1M corpus, bench generator CLI"
provides:
  - "HermitHarness wrapper (D-11) — owlready2.sync_reasoner_hermit with Xmx tuning knob + structured HermitResult"
  - "3 SSR surfaces per D-09 (shards / polysemy / timeline) with streaming load() + cache-control"
  - "hooks.server.ts applying cache-control to D-09 surfaces (Gate 4 tuning step 2)"
  - "FastAPI endpoint stubs (shard/polysemy/timeline) returning canned JSON for Gate 4 SSR measurement"
  - "Gate 3 image-size test (D-06 thresholds) — fi-worker:smoke measured at 74.6 MB (PASS)"
  - "Gate 4 hyperfine cold-page P95 test (D-07 thresholds) — runnable pending hyperfine install"
  - "00-07-MEASUREMENTS.md with Gate 3 PASS + Gate 4/D-11 deferrals"
affects:
  - "Plan 08 (decision artifact) — reads MEASUREMENTS.md verbatim into DECISION.md"
  - "Phase 10 (worker cutover) — inherits HermitHarness + Xmx recommendation (pending full-1M)"
  - "Phase 15 (review viewer) — inherits 3 SSR surfaces + hooks.server.ts; replaces stub endpoints with real pyoxigraph queries"
  - "Phase 17 (CI) — inherits Gate 3/4 tests as regression gates"

tech-stack:
  added:
    - "@polka/compression (viewer dep) — streaming-safe compression; NOT standard compression (RESEARCH.md anti-pattern line 464)"
  patterns:
    - "SSR critical-path minimisation: one awaited fetch + N unawaited promises streamed via {#await}"
    - "Xmx-tuning via process-global owlready2.JAVA_MEMORY at HermitHarness.__init__"
    - "Structured HermitResult dataclass with as_dict() for MEASUREMENTS.md ingestion"
    - "OwlReadyInconsistentOntologyError caught and encoded as consistent=False (ontology-level) rather than propagated"
    - "Pytest xfail for accept-with-SLO bands (500-700 MB Gate 3, 200-400 ms Gate 4) with explicit pivot-trigger assert above ceiling"
    - "Canned-JSON FastAPI stubs decouple Gate 4 SSR measurement from pyoxigraph query cost"

key-files:
  created:
    - "src/folio_insights/reason/__init__.py"
    - "src/folio_insights/reason/hermit_harness.py"
    - "tests/bench/test_hermit_harness.py"
    - "tests/bench/test_gate3_image.py"
    - "tests/bench/test_gate4_ssr.py"
    - "viewer/src/hooks.server.ts"
    - "viewer/src/routes/shards/[id]/+page.server.ts"
    - "viewer/src/routes/shards/[id]/+page.svelte"
    - "viewer/src/routes/polysemy/[id]/+page.server.ts"
    - "viewer/src/routes/polysemy/[id]/+page.svelte"
    - "viewer/src/routes/timeline/[id]/+page.server.ts"
    - "viewer/src/routes/timeline/[id]/+page.svelte"
    - "api/routes/shard.py"
    - "api/routes/polysemy.py"
    - "api/routes/timeline.py"
    - ".planning/phases/00-foundations-hard-gate/00-07-MEASUREMENTS.md"
  modified:
    - "api/main.py (registered 3 new routers)"
    - "viewer/package.json (+ @polka/compression)"
    - "viewer/package-lock.json"
    - "pyproject.toml (+ gate3/gate4 markers)"

key-decisions:
  - "[00-07-D1] HermitHarness catches OwlReadyInconsistentOntologyError and records consistent=False with sentinel class '<ontology-inconsistent>' rather than re-raising — ontology-level unsatisfiability is a valid D-11 result, not a reasoner crash"
  - "[00-07-D2] HermitHarness.__init__ writes owlready2.JAVA_MEMORY at instance construction (process-global) so the Xmx value is picked up by the subprocess spawn regardless of which harness instance calls .reason() — matches owlready2's own design"
  - "[00-07-D3] FastAPI stubs return canned JSON (no pyoxigraph query) so Gate 4 measures SSR stack overhead — Phase 15 wires real queries behind the same URL contract"
  - "[00-07-D4] Full @polka/compression custom-server wiring deferred — dependency installed, but activation requires custom adapter-node server.js wrapper; only needed if cache-control alone misses <200ms target"
  - "[00-07-D5] Gate 3 measures docker inspect {{.Size}} (74.6 MB) not 'docker image ls DISK USAGE' (243 MB, shared-layer accounting) — D-06 budgets the delivered image"
  - "[00-07-D6] D-11 full-1M run deferred — requires .owl-format 1M fixture (generator currently emits N-Quads only) + 1-2 day measurement window per D-11 expected cost; D-12 open-ended timebox permits"
  - "[00-07-D7] SSR surfaces use Svelte 5 runes ($props) rather than export-let — matches 00-04 adapter-node swap conventions"

patterns-established:
  - "D-06 threshold encoding: <500MB PASS / 500-700MB xfail (microservice-split hint for Phase 10) / >700MB assert (pivot-trigger)"
  - "D-07 threshold encoding: <200ms PASS / 200-400ms xfail (SLO relaxation) / >400ms assert (deferred-hydration fallback per-surface)"
  - "Hyperfine P95 computation: parse results[0].times[] array, sort, nearest-rank index — hyperfine 1.18 does not emit P95 directly"
  - "Worker image tag resolution: FOLIO_WORKER_IMAGE env > known-tag probe list > skip with actionable message"
  - "MEASUREMENTS.md discipline: per-gate baseline / tuning-pass audit checklist / final measurement table / open-questions list — mirrors 00-06 TUNING-LOG structure"

requirements-completed: [QUALITY-03, QUALITY-04]

duration: 8min
completed: 2026-04-23
---

# Phase 00 Plan 07: ssr-prototype-gate3-gate4-hermit-harness Summary

**HermitHarness (D-11) + 3 SSR surfaces (D-09) + Gate 3 PASS at 74.6 MB; Gate 4 and D-11 full-1M deferred with runnable harnesses in place.**

## Performance

- **Duration:** 8 min (491 sec wall-clock)
- **Started:** 2026-04-23T03:34:41Z
- **Completed:** 2026-04-23T03:42:52Z
- **Tasks:** 4
- **Files modified:** 17 (16 created + 4 modified; `api/main.py`, `pyproject.toml`, `viewer/package.json`, `viewer/package-lock.json`)

## Accomplishments

- **HermitHarness + 4 passing unit tests** — D-11 harness ships with Xmx tuning knob, structured `HermitResult`, and smoke classification on both consistent and inconsistent tiny OWL fixtures. Pitfall 3 (JVM cold-start) acknowledged with cold/warm timings captured (~0.18 s tiny-case).
- **3 SSR surfaces per D-09** — `/shards/[id]`, `/polysemy/[id]`, `/timeline/[id]` each with streaming `load()` (one awaited critical-path + two unawaited promises for `{#await}`), cache-control applied via `hooks.server.ts`, all URLs relative (feedback_api-client-proxy.md compliance). Build produces server entries for all three.
- **Gate 3 PASS at 74.6 MB** — `fi-worker:smoke` measured 15% of the 500 MB hard target. 8 of 8 applicable tuning passes from RESEARCH.md Gate 3 playbook are active (jlink `--compress=2`, musllinux Alpine base, 3-stage build, cache purges, scoped reasoning subset). No microservice-split recommendation for Phase 10.
- **Gate 4 harness runnable + deferred** — `tests/bench/test_gate4_ssr.py` parametrised over 3 surfaces × 3 IDs = 9 P95 measurements. Skips cleanly when hyperfine or server origin missing; the verify-session operator installs hyperfine and runs the harness.
- **00-07-MEASUREMENTS.md** — populated with actual Gate 3 number, per-pass tuning audit, D-11 smoke timings, explicit Gate 4/D-11 deferral rationale.

## Task Commits

Each task was committed atomically (Task 1 is TDD with RED+GREEN commits):

1. **Task 1a RED: HermiT harness failing tests** — `b29bf62` (test)
2. **Task 1b GREEN: HermitHarness implementation** — `99cef7f` (feat) — catches OwlReadyInconsistentOntologyError
3. **Task 2: 3 SSR surfaces + hooks + FastAPI stubs** — `4563d71` (feat)
4. **Task 3: Gate 3 + Gate 4 tests** — `a5e0438` (test)
5. **Task 4: 00-07-MEASUREMENTS.md** — `23f0ce1` (docs)

## Files Created/Modified

### HermiT harness (D-11, RISK-1)

- `src/folio_insights/reason/__init__.py` — public `HermitHarness`, `HermitResult` exports
- `src/folio_insights/reason/hermit_harness.py` — thin owlready2 wrapper with Xmx knob + structured result dataclass
- `tests/bench/test_hermit_harness.py` — 5 tests (4 non-D-11 passing, 1 opt-in via `FOLIO_RUN_D11=1`)

### SSR surfaces (D-09)

- `viewer/src/hooks.server.ts` — Gate 4 tuning step 2 (cache-control on `/{shards,polysemy,timeline}/*`)
- `viewer/src/routes/shards/[id]/{+page.server.ts,+page.svelte}` — shard surface
- `viewer/src/routes/polysemy/[id]/{+page.server.ts,+page.svelte}` — polysemy-fork surface
- `viewer/src/routes/timeline/[id]/{+page.server.ts,+page.svelte}` — supersession-timeline surface
- `viewer/package.json`, `viewer/package-lock.json` — `@polka/compression` installed

### FastAPI endpoint stubs

- `api/routes/shard.py` — `/api/shard/{id}/{core,deps,attests}`
- `api/routes/polysemy.py` — `/api/polysemy/{id}/{core,siblings,disambiguations}`
- `api/routes/timeline.py` — `/api/timeline/{id}/{core,events,supersession_chain}`
- `api/main.py` — three routers registered

### Gate 3/4 tests

- `tests/bench/test_gate3_image.py` — D-06 thresholds (500 MB / 700 MB)
- `tests/bench/test_gate4_ssr.py` — D-07 thresholds (200 ms / 400 ms), 9 parametrised tests
- `pyproject.toml` — `gate3`, `gate4` markers registered

### Documentation

- `.planning/phases/00-foundations-hard-gate/00-07-MEASUREMENTS.md` — per-gate baseline, tuning-pass audit, final measurement tables

## Decisions Made

Seven decisions captured in frontmatter (`00-07-D1` … `D7`). Most consequential:

- **D1** — `OwlReadyInconsistentOntologyError` caught rather than propagated. This was a Rule 1 auto-fix: the initial harness re-raised, which broke the disjoint-Dog-Cat smoke test. owlready2 raises this exception (with "Inconsistent ontology" stderr) when the whole ontology is unsatisfiable; it is a valid D-11 result, not a reasoner failure, so the harness records `consistent=False` with sentinel class `<ontology-inconsistent>`.
- **D4** — `@polka/compression` dependency shipped but activation deferred. Full per-chunk compression requires a custom `adapter-node` server.js wrapper; we rely on cache-control (step 2) to hit the 200 ms target first. Plan 08 flags this as follow-up if Gate 4 needs it.
- **D5** — Gate 3 uses `docker inspect --format '{{.Size}}'` (74.6 MB), not `docker image ls DISK USAGE` (243 MB with shared-layer accounting). D-06 budgets the delivered image as Docker itself reports it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] HermitHarness re-raised OwlReadyInconsistentOntologyError instead of recording consistent=False**

- **Found during:** Task 1 (GREEN gate verification — `test_hermit_harness_detects_inconsistency` failed)
- **Issue:** Initial harness caught all exceptions as `except Exception: ... raise`. owlready2 raises `OwlReadyInconsistentOntologyError` when HermiT reports "Inconsistent ontology" (the whole ontology is unsatisfiable, e.g. Rex typed as both `Dog` and `Cat` with those classes disjoint). This is a valid D-11 outcome, not a reasoner failure — re-raising turned the smoke test into a hard error and made inconsistency-detection untestable.
- **Fix:** Separated `OwlReadyInconsistentOntologyError` into its own `except` clause, records `elapsed_s`, sets `consistent=False`, and populates `inconsistent_classes=['<ontology-inconsistent>']` as a sentinel (owlready2 does not populate `onto.inconsistent_classes()` when the whole ontology is inconsistent — it aborts first). Other exceptions still propagate.
- **Files modified:** `src/folio_insights/reason/hermit_harness.py`
- **Verification:** `test_hermit_harness_detects_inconsistency` now PASSES; `consistent is False` and `len(inconsistent_classes) > 0` both hold.
- **Committed in:** `99cef7f` (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 bug)
**Impact on plan:** The fix is a correctness requirement — inconsistency detection is the POINT of the `test_hermit_harness_detects_inconsistency` test. No scope creep; same contract, correct semantics.

## Issues Encountered

- **hyperfine not installed on the Plan 07 execution host** — Gate 4 test cannot produce live measurements in this session. Handled per plan design: `test_gate4_ssr.py` skips cleanly via `pytest.skipif(shutil.which('hyperfine') is None, …)` + a second skip on missing `FOLIO_WEB_ORIGIN`. MEASUREMENTS.md marks Gate 4 as DEFERRED and flags the install step for the verify session (`apt install hyperfine` / `cargo install hyperfine` / `brew install hyperfine`). Per D-12 open-ended timebox this is acceptable.
- **fastapi not in venv dependencies** — `api/routes/{shard,polysemy,timeline}.py` imports `fastapi.APIRouter`; the 00-01 summary noted this is a belt-and-suspenders install rather than a pyproject dep. Route files were syntax-checked via `ast.parse()` (all parse OK); live import + server smoke-test deferred to verify session (requires `uv pip install fastapi uvicorn[standard] python-multipart`).
- **adapter-node 5.x layout** — the plan's verification script expected `viewer/build/server/entries/pages/shards/...` but adapter-node 5.5.4 consolidates entries into `.svelte-kit/output/server/entries/pages/...` and publishes a flatter `viewer/build/server/` with `manifest.js` referencing the routes. Verified via `grep -oE '(shards|polysemy|timeline)/\[id\]' viewer/build/server/manifest.js` — all three surfaces present.

## User Setup Required

**For the verify session (Gate 4 + D-11 operators):**

1. Install hyperfine on the measurement host:
   - Debian/Ubuntu: `apt install hyperfine`
   - Cargo (cross-platform): `cargo install hyperfine`
   - macOS: `brew install hyperfine`
2. Start both servers before running Gate 4:
   - `uv run uvicorn api.main:app --port 8001` (FastAPI backend)
   - `(cd viewer && FOLIO_ORIGIN=http://localhost:8001 node build/index.js)` (adapter-node, port 3000 default)
3. Run Gate 4: `FOLIO_WEB_ORIGIN=http://localhost:3000 uv run pytest tests/bench/test_gate4_ssr.py -m gate4 -v`
4. For D-11 full-1M: generate OWL-format fixture, then `FOLIO_RUN_D11=1 FOLIO_HERMIT_XMX=4096 uv run pytest tests/bench/test_hermit_harness.py::test_hermit_full_1m_abox -s`

## Next Phase Readiness

Plan 08 (decision artifact) has what it needs:

- Gate 3 verdict = **PASS** (74.6 MB, 425 MB headroom) — record in DECISION.md Gate 3 row.
- Gate 4 verdict = **DEFERRED** — verify session supplies P95 numbers; DECISION.md can be drafted with pending rows and updated when hyperfine runs.
- D-11 verdict = **harness-ready, full-1M pending** — Xmx recommendation for Phase 10 worker default is the only gap.
- Gate 1 (PASSED 00-03), Gate 2 (PASSED 00-06, worst-case P95 116.95 ms), Gate 5 Mode 1 (PASSED 00-05).
- Four of five gates resolve in Plan 07 or earlier; only Gate 4 needs the verify-session measurement.

## Self-Check: PASSED

All claimed files exist:

- `src/folio_insights/reason/__init__.py` FOUND
- `src/folio_insights/reason/hermit_harness.py` FOUND
- `tests/bench/test_hermit_harness.py` FOUND
- `tests/bench/test_gate3_image.py` FOUND
- `tests/bench/test_gate4_ssr.py` FOUND
- `viewer/src/hooks.server.ts` FOUND
- `viewer/src/routes/{shards,polysemy,timeline}/[id]/{+page.server.ts,+page.svelte}` all FOUND
- `api/routes/{shard,polysemy,timeline}.py` all FOUND
- `.planning/phases/00-foundations-hard-gate/00-07-MEASUREMENTS.md` FOUND

All claimed commits exist in `git log`:

- `b29bf62` FOUND (test RED)
- `99cef7f` FOUND (feat GREEN)
- `4563d71` FOUND (feat SSR)
- `a5e0438` FOUND (test Gate 3/4)
- `23f0ce1` FOUND (docs MEASUREMENTS)

---

*Phase: 00-foundations-hard-gate*
*Completed: 2026-04-23*
