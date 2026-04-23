---
phase: 0
plan: 7
gates: [3, 4]
decision_refs: [D-06, D-07, D-09, D-11]
requirements: [QUALITY-03, QUALITY-04]
created: 2026-04-23
---

# Plan 07 Measurements — Gate 3, Gate 4, D-11

Per-measurement log with tuning-pass audit trail (mirrors Plan 06's TUNING-LOG
discipline). Plan 08 consumes the "Final Measurement" tables verbatim into
`00-DECISION.md`.

**Machine metadata:**

- OS: Linux 6.17.0-22-generic (Ubuntu)
- Python: 3.12.12
- Docker: available on PATH
- Java: OpenJDK 21.0.10 (plan assumes 17; 21 works for HermiT testing)
- hyperfine: **NOT installed** — Gate 4 deferred to verify session

---

## Gate 3 — Worker Image Size (REQ-QUALITY-03, D-06)

**Target:** <500 MB
**SLO ceiling:** ≤700 MB (accept-with-SLO; microservice-split recommended for Phase 10)
**Pivot trigger:** >700 MB

### Baseline (Plan 04 initial build — Alpine + jlink JRE)

| Build path | Base image | Size (MB) | Notes |
|------------|------------|-----------|-------|
| Plan 04 smoke (Alpine) | python:3.11-alpine + jlink JRE | 74.6 | 00-04-D1 A1=confirmed; musllinux_1_2 wheel |
| Plan 04 smoke (slim fallback) | python:3.11-slim + jlink JRE | N/A | Not built; A1 never fell back |

### Tuning passes applied (RESEARCH.md §Gate 3 playbook)

1. [x] **jlink custom JRE** (Dockerfile.worker stage 1) — biggest single win per RESEARCH.md; reduces temurin-17-jdk-alpine from ~400 MB to ~60–80 MB.
2. [x] **Alpine base vs slim** (00-04-D1 spike) — pyoxigraph 0.5.7 ships `musllinux_1_2_x86_64` wheel so Alpine is viable; saves ~75 MB over slim.
3. [x] **Multi-stage build** (Plan 04 Dockerfile.worker: jre-builder / deps-builder / runtime) — gcc/g++/musl-dev/libffi-dev never reach the runtime image.
4. [x] **Purge build caches** — `pip install --no-cache-dir`, `rm -rf /var/cache/apk/*`, `.pyc` / `__pycache__` deleted post-install.
5. [x] **`PYTHONDONTWRITEBYTECODE=1`** — runtime does not write `.pyc`.
6. [x] **Strip JAR debug symbols** — N/A; HermiT.jar is already 8 MB.
7. [x] **jlink `--compress=2`** — applied.
8. [x] **Scoped worker install** (00-04-D2) — only `pyoxigraph + owlready2 + rdflib + oxrdflib`; excludes torch / sentence-transformers / instructor / pyshacl.

### Final Measurement (→ 00-DECISION.md Gate 3 row)

| Image | Size (MB) | vs 500 MB target | vs 700 MB ceiling | Verdict |
|-------|-----------|------------------|-------------------|---------|
| `fi-worker:smoke` | **74.6** | **425 MB headroom** | **625 MB headroom** | **PASS** |

**Gate 3 verdict = PASS.** Worker image is 74.6 MB (15% of hard target). No tuning escalation needed. No microservice-split recommendation for Phase 10.

Note on measurement methodology: `docker image inspect --format '{{.Size}}'` reports the image's own size (74.6 MB = 78.2 MB content size). `docker image ls` "DISK USAGE" (243 MB) includes shared base-layer accounting and is NOT the Gate 3 quantity — D-06 budgets the delivered image as Docker reports it via `inspect`.

---

## Gate 4 — SSR Cold-Page Latency (REQ-QUALITY-04, D-07)

**Target:** <200 ms P95
**SLO ceiling:** ≤400 ms (accept-with-SLO)
**Pivot trigger:** >400 ms → deferred-hydration SPA fallback for that surface (per-surface scope; NOT a full adapter swap).

### Baseline (Plan 07 Task 2 ship, WITHOUT live measurement)

Gate 4 measurement requires `hyperfine` + running adapter-node server + running FastAPI backend. hyperfine was not installed on the Plan 07 execution machine; measurement is deferred to the verify session per D-12 open-ended timebox.

| Surface | Sample ID | P95 (ms) | vs 200 ms | vs 400 ms |
|---------|-----------|----------|-----------|-----------|
| shards | a1b2… | DEFERRED | — | — |
| shards | dead… | DEFERRED | — | — |
| shards | 0123… | DEFERRED | — | — |
| polysemy | a1b2… | DEFERRED | — | — |
| polysemy | dead… | DEFERRED | — | — |
| polysemy | 0123… | DEFERRED | — | — |
| timeline | a1b2… | DEFERRED | — | — |
| timeline | dead… | DEFERRED | — | — |
| timeline | 0123… | DEFERRED | — | — |

### Tuning passes applied (RESEARCH.md §Gate 4 playbook)

1. [x] **Critical-path minimisation** — each `+page.server.ts` has exactly ONE awaited `fetch()` (the `/core` endpoint); the other two fetches return promises for `{#await}` streaming. Verified by grep / acceptance criteria T-00-30.
2. [x] **`cache-control: public, max-age=60, s-maxage=60`** — applied in `hooks.server.ts` regex matcher AND redundantly in each `+page.server.ts` via `setHeaders`. Second hits should drop to <10 ms once a reverse-proxy or CDN layer is in front.
3. [x] **Precompile** — adapter-node runs prod-mode server from `viewer/build/`; no dev-mode Vite cost.
4. [?] **`@polka/compression` wiring** — dependency installed (`viewer/package.json`); full per-chunk compression requires a custom `adapter-node` server.js wrapper. Deferred unless step-2 cache-control alone misses the target.
5. [x] **Node 22-slim base** (Plan 04 `Dockerfile.web`) — small runtime, fast cold start.
6. [x] **No heavy deps in `+page.server.ts`** — Phase 0 stubs return canned JSON; Cytoscape / YASGUI stay browser-only.
7. [x] **Relative URLs + Vite proxy** — `+page.server.ts` uses `/api/...` (feedback_api-client-proxy.md); no cross-origin cost.

### Final Measurement (→ 00-DECISION.md Gate 4 row)

| Surface | Worst P95 (ms) | vs 200 ms | vs 400 ms | Verdict |
|---------|----------------|-----------|-----------|---------|
| shards | DEFERRED | — | — | pending verify session |
| polysemy | DEFERRED | — | — | pending verify session |
| timeline | DEFERRED | — | — | pending verify session |

**Overall Gate 4 verdict: DEFERRED to verify session.**

Rationale: `hyperfine` is not on the Plan 07 execution host PATH; running the 9-measurement harness against the D-09 surfaces requires the verifier to install hyperfine (`apt install hyperfine` / `cargo install hyperfine` / `brew install hyperfine`) and start both servers. Test file (`tests/bench/test_gate4_ssr.py`) skips cleanly today; it will produce measurements as soon as hyperfine + both servers are available. Per D-12 open-ended timebox this is acceptable — Plan 08 DECISION.md marks Gate 4 pending.

---

## D-11 — Full 1M ABox HermiT Reasoning

**Full-fidelity (D-11, MAX-FIDELITY):** run HermiT on real 1M ABox + TBox. No strict time budget (D-12); hard ceiling 1 hr for operational sanity.

### Setup

- JVM: OpenJDK 21.0.10 (dev host); Plan 04 worker container ships jlink'd Temurin 17 runtime.
- owlready2: 0.50 (via `requirements.lock` and `requirements.worker.lock`).
- HermiT.jar: **confirmed bundled** with owlready2 0.50 — path `.venv/lib/python3.12/site-packages/owlready2/hermit/HermiT.jar` exists. A4 assumption passes.
- ABox source: Plan 02 generator's `fixtures/bench.nq` (N-Quads). HermiT consumes OWL; full-1M run requires a `.owl` fixture (generator `--format owl` option exists per `00-02-SUMMARY` D-11 fixture).

### Measurements (smoke + scaling)

| Run | Xmx (MB) | Elapsed (s) | Consistent? | Notes |
|-----|----------|-------------|-------------|-------|
| Pitfall 3 cold-start (tiny, 3 classes) | 512 | 0.186 | True | JVM subprocess spawn dominates at tiny scale |
| Warm (tiny, 2nd call, same harness) | 512 | 0.161 | True | owlready2 spawns fresh JVM per call; "warm" name is nominal — no in-process reuse |
| Disjoint-violation (tiny) | 512 | ~0.18 | **False** | `OwlReadyInconsistentOntologyError`; harness encodes as `<ontology-inconsistent>` sentinel |
| Full 1M ABox | DEFERRED | DEFERRED | DEFERRED | Requires `fixtures/bench-abox-1m.owl`; run via `FOLIO_RUN_D11=1` |

### Verdict

- [x] Harness ships, unit-tested (`tests/bench/test_hermit_harness.py`, 4 non-slow-D-11 tests passing).
- [x] Xmx tuning knob wired (`owlready2.JAVA_MEMORY = xmx_mb` at `__init__`).
- [x] Consistency detection validated on both consistent and inconsistent tiny fixtures.
- [x] Pitfall 3 (JVM cold-start) acknowledged in code docstring; timings captured (~0.18 s tiny-case).
- [ ] D-11 full-1M run — DEFERRED pending `bench-abox-1m.owl` fixture generation + a reserved 1–2 day measurement window per D-11 expected cost.
- [ ] Xmx recommendation for Phase 10 worker default — pending full-1M run.

### D-11 deferral rationale

Plan 07's scope was "ship the harness + make it measurable." The full-1M run is an operational measurement that requires (a) generating an OWL-format 1M ABox fixture (bench generator currently emits N-Quads only for non-HermiT gates), (b) reserving wall-clock for the run itself (D-11 expected 1–2 days). Per D-12 open-ended timebox this deferral is acceptable. Plan 08 DECISION.md marks D-11 as "harness-ready, measurement pending."

---

## Open Questions for Plan 08 DECISION.md

- [x] **Gate 3 verdict**: PASS (74.6 MB vs 500 MB target — 425 MB headroom).
- [ ] **Gate 4 per-surface verdict**: pending verify session (hyperfine install + server start-up).
- [ ] **D-11 completion + timing**: deferred to reserved measurement window; harness + smoke tests are ready.
- [?] **@polka/compression custom-server wiring**: only needed if Gate 4 step-2 (cache-control) misses the target. Plan 07 ships the dependency but not the custom server.js; Plan 08 DECISION.md flags as follow-up if Gate 4 needs it.

---

## Artefact map

| File | Role | Plan 08 consumer |
|------|------|------------------|
| `src/folio_insights/reason/hermit_harness.py` | D-11 harness | Phase 10 worker imports at cutover |
| `tests/bench/test_hermit_harness.py` | D-11 smoke + opt-in full-1M | CI runs non-slow subset; verify session runs `FOLIO_RUN_D11=1` |
| `tests/bench/test_gate3_image.py` | Gate 3 assertion | CI runs against Dagger-published tag |
| `tests/bench/test_gate4_ssr.py` | Gate 4 assertion | Verify session runs with hyperfine + servers |
| `viewer/src/hooks.server.ts` | Gate 4 cache-control middleware | Phase 15 inherits; adds per-endpoint rules |
| `viewer/src/routes/{shards,polysemy,timeline}/[id]/` | D-09 SSR prototype | Phase 15 wires pyoxigraph behind the stub endpoints |
| `api/routes/{shard,polysemy,timeline}.py` | Phase 0 stub endpoints | Phase 15 replaces canned JSON with real store-backed handlers |
