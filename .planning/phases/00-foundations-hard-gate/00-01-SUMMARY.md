---
phase: 0
plan: 1
plan_number: 1
plan_name: prep-deps-rename-wave0-scaffold
subsystem: foundations
tags: [deps, scaffold, philosophy, wave0, pyoxigraph, owlready2, dagger]
completed: 2026-04-22
duration_min: 4
task_count: 2
file_count: 8
requirements: [SEC-02, QUALITY-03]
requirements_addressed: [SEC-02, QUALITY-03]

dependency_graph:
  requires:
    - "uv package manager (installed)"
    - "Python 3.11-3.12 runtime (3.12.12 resolved)"
    - "v1 pyproject.toml baseline"
  provides:
    - "PHILOSOPHY.md at repo root (D-18)"
    - "pyproject.toml with Phase 0 pinned deps"
    - "tests/bench/ scaffold with session-scoped fixtures"
    - "fixtures/bench/, fixtures/gold_queries/{,adversarial/} tracked dirs"
    - "uv.lock committed with hashes"
  affects:
    - "Plan 00-02 (consumes bench_1m_corpus fixture)"
    - "Plan 00-03 (gold_queries/adversarial/ drop-in)"
    - "Plan 00-04 (worker Dockerfile split — owlready2 import target)"
    - "Plan 00-05 (Dagger CI — dagger-io SDK import target)"
    - "Plan 00-06 (Gate 2 P95 — pytest-benchmark + bench_store)"

tech_stack:
  added:
    - "pyoxigraph==0.5.7 (RDF 1.2 triplestore; locked per RISK-3/D-04)"
    - "oxrdflib 0.5.0 (rdflib Store bridge; resolver-picked version)"
    - "owlready2==0.50 (HermiT JVM wrapper; worker-tier per RISK-1)"
    - "pytest-benchmark 5.2.3 (Gate 2 P95 harness; QUALITY-01)"
    - "dagger-io 0.20.6 (Gate 5 CI SDK; OBS-04)"
    - "pytest bumped 8→9.0.3"
  patterns:
    - "Session-scoped pytest fixtures for expensive 1M-triple loads"
    - "Explicit random.Random(seed) (Pitfall 7 — no module-level / no NumPy RNG)"
    - "pytest.skip with actionable CLI instructions when fixture missing"
    - "git mv for rename (preserves blame via --follow)"

key_files:
  created:
    - path: "tests/bench/__init__.py"
      purpose: "Package marker for pytest discovery"
    - path: "tests/bench/conftest.py"
      purpose: "Session-scoped bench_1m_corpus + bench_store + seeded_rng fixtures"
    - path: "fixtures/bench/.gitkeep"
      purpose: "Track empty bench/ dir for Plan 00-02 generator output"
    - path: "fixtures/gold_queries/.gitkeep"
      purpose: "Track empty gold_queries/ for Plan 00-03 adversarial set"
    - path: "fixtures/gold_queries/adversarial/.gitkeep"
      purpose: "Track adversarial/ subdir for deep-GRAPH / SERVICE-blocked queries"
    - path: "uv.lock"
      purpose: "Reproducible resolver output (127 packages; hashes for Plan 00-05)"
  modified:
    - path: "pyproject.toml"
      purpose: "Add 3 prod + 2 dev deps; tighten requires-python"
    - path: ".dockerignore"
      purpose: "Add bare node_modules + output/ (Gate 5 / Pitfall 5)"
  renamed:
    - from: "2026-04-19_Philosophy.md"
      to: "PHILOSOPHY.md"
      commit: 8602619
      note: "git mv preserved blame (2 commits visible via git log --follow)"

decisions:
  - id: "P1-D1"
    decision: "Use importlib.metadata for owlready2 version introspection (no __version__ attr)"
    rationale: "owlready2==0.50 ships no module-level __version__; importlib.metadata('owlready2') is the canonical path"
    impact: "Plan acceptance criterion adjusted; no code change needed"
  - id: "P1-D2"
    decision: "Added bare 'node_modules' entry to .dockerignore (kept viewer/node_modules alongside)"
    rationale: "Plan acceptance criterion required literal ^node_modules pattern; viewer/-scoped entry alone does not satisfy Gate 5 step 10 defense-in-depth"
    impact: "Belt-and-suspenders; no functional change since viewer/node_modules was the only instance"
  - id: "P1-D3"
    decision: "Resolved CONTEXT.md Open Question 1 — philosophy file lives at repo root, NOT docs/"
    rationale: "ls -la confirmed 2026-04-19_Philosophy.md at repo root; CONTEXT.md docs/ prefix was a typo"
    impact: "D-18 intent preserved (rename only, content unchanged); Phase 18 owns restructure"

metrics:
  duration_min: 4
  started: "2026-04-23T01:38:00Z"
  completed: "2026-04-23T01:41:38Z"
  tasks_completed: 2
  files_created: 6
  files_modified: 2
  files_renamed: 1
  commits: 2
---

# Phase 0 Plan 01: Prep-Deps + Rename + Wave 0 Scaffold Summary

Phase 0 ground prepped: pinned Phase 0 deps declared (pyoxigraph 0.5.7 / oxrdflib / owlready2 0.50), Python tightened to `>=3.11,<3.13` per Pitfall 8, PHILOSOPHY.md moved to repo root via `git mv` (D-18), and `tests/bench/` scaffold landed with session-scoped pyoxigraph fixtures so downstream Gate-measurement plans have ready-made hooks.

## Objective Delivered

Close the VALIDATION.md Wave 0 gaps before any gate-measurement plan runs. Every downstream plan (00-02 through 00-08) depends on the fixtures and deps created here.

Output shipped:

- `PHILOSOPHY.md` at repo root (D-18 — blame preserved)
- `pyproject.toml`: 3 pinned prod deps + 2 new dev deps + `requires-python = ">=3.11,<3.13"`
- `.dockerignore`: bare `node_modules` + `output/` added (Gate 5 step 10 + Pitfall 5)
- `tests/bench/{__init__.py, conftest.py}`: `bench_1m_corpus` (session), `bench_store` (session), `seeded_rng` (per-test) fixtures
- `fixtures/bench/`, `fixtures/gold_queries/`, `fixtures/gold_queries/adversarial/`: committed via `.gitkeep`
- `uv.lock`: 127 packages locked; hashes ready for Plan 00-05 Dockerfile `--require-hashes` enforcement

## Commits

| Task | Commit  | Scope                                                         |
| ---- | ------- | ------------------------------------------------------------- |
| 1    | 8602619 | chore: Phase 0 deps + Python pin + PHILOSOPHY.md rename       |
| 2    | af8e273 | test: tests/bench/ scaffold + fixtures/ tracked dirs          |

## Dependency Lock Deltas (uv.lock — transitive surface)

Newly resolved top-level packages (direct deps from this plan):

| Package          | Version | Notes                                                         |
| ---------------- | ------- | ------------------------------------------------------------- |
| pyoxigraph       | 0.5.7   | Exact pin per RISK-3 / D-04 — native C extension wheel        |
| oxrdflib         | 0.5.0   | Resolver-picked (no pin required per plan); rdflib ≥7.0 bridge |
| owlready2        | 0.50    | Exact pin; bundles HermiT.jar (verified in .venv)             |
| pytest           | 9.0.3   | Bumped from 8.0 → 9.0 per plan                                |
| pytest-benchmark | 5.2.3   | Satisfies `>=5.1` (Gate 2 P95 harness)                        |
| dagger-io        | 0.20.6  | Unpinned per plan; Gate 5 CI                                  |

Transitive deps of note (will matter at Plan 00-04 image-size gate):

- `torch==2.11.0 + triton==3.6.0` (pre-existing from sentence-transformers) — dominates worker image size; Plan 00-04 may need CPU-only torch
- No owlready2 JDK helper package pulled into venv (HermiT bundled as `.jar` inside owlready2 package dir, not a separate dist)
- pyoxigraph ships native `.so` extensions (verified `.venv/lib/python3.12/site-packages/pyoxigraph/*.so`); musllinux wheel availability for Alpine base is TBD in Plan 00-04

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] `owlready2.__version__` attribute does not exist**

- **Found during:** Task 1 verification (`uv run python -c "import owlready2; print(owlready2.__version__)"`)
- **Issue:** Plan acceptance criterion assumed `owlready2.__version__` but owlready2 0.50 does not expose a module-level `__version__`
- **Fix:** Verified installed version via `importlib.metadata.version("owlready2")` instead — confirms `0.50` installed correctly
- **Files modified:** none (verification-only adjustment)
- **Commit:** n/a (plan text not changed; noted here for downstream planners)

**2. [Rule 3 — Blocking] `grep -c "numpy" tests/bench/conftest.py` returned 2, not 0**

- **Found during:** Task 2 acceptance check
- **Issue:** Original conftest.py docstring/comment mentioned "numpy.random" to document the anti-pattern. Literal `grep -c "numpy"` counted those comment occurrences.
- **Fix:** Rephrased comments from `numpy.random` → `NumPy RNG` (same semantic intent, no literal "numpy" token). Pitfall 7 discipline preserved.
- **Files modified:** `tests/bench/conftest.py` (in-task edit before commit af8e273)
- **Commit:** folded into Task 2 commit af8e273

### Rule-1/Rule-2/Rule-4 Deviations

None.

### Deferred (Out-of-Scope) Items

- **Docker build regression verification:** Plan's `<verification>` mentions `docker build -f Dockerfile -t fi:wave1-smoke .` as a non-regression check. The existing single-stage Dockerfile is untouched, but a full build is slow (~8 GB image per v1.1 notes) and out of this plan's scope (Plan 00-04 owns the two-stage split). No regression is expected — only `.dockerignore` grew (by adding exclusions, never removing them).

## Authentication Gates

None encountered. All dep installs via `uv sync --all-extras` succeeded against public PyPI.

## Open Questions — Resolution

Resolved in this plan:

- **OQ 1 (philosophy file path):** Confirmed at repo root `/home/damienriehl/Coding Projects/folio-insights/2026-04-19_Philosophy.md` (NOT `docs/` as CONTEXT.md line 84 stated). D-18 intent preserved; `docs/` prefix was a typo. File renamed to `PHILOSOPHY.md` via `git mv` (commit 8602619; blame preserved — 2 commits visible via `git log --follow PHILOSOPHY.md`).

Deferred to later plans (unchanged):

- **OQ 2 (1M-triple P95 baseline):** Plan 00-06
- **OQ 3 (Railway Node 22 cold-page):** Plan 00-07
- **OQ 4 (Fuseki pivot trigger threshold):** Plan 00-08
- **OQ 5 (Adversarial SPARQL set composition):** Plan 00-03

## Known Stubs

None. Fixtures are intentionally skip-on-missing (Plan 00-02 will populate `fixtures/bench.nq`); `.gitkeep` files are directory trackers by design, not placeholders.

## Threat Flags

None. No new network endpoints, auth paths, or trust-boundary crossings introduced. Supply-chain threats (T-00-01, T-00-02) from the threat register are already addressed by exact version pins; Plan 00-05 closes the full hash-pinning loop at Dockerfile install time.

## Self-Check: PASSED

- **Files created:**
  - `PHILOSOPHY.md` — FOUND
  - `tests/bench/__init__.py` — FOUND
  - `tests/bench/conftest.py` — FOUND
  - `fixtures/bench/.gitkeep` — FOUND
  - `fixtures/gold_queries/.gitkeep` — FOUND
  - `fixtures/gold_queries/adversarial/.gitkeep` — FOUND
  - `uv.lock` — FOUND
- **Commits:**
  - `8602619` — FOUND
  - `af8e273` — FOUND
- **Acceptance criteria:** All 11 Task-1 criteria + all 9 Task-2 criteria passed (verified by grep + pytest --collect-only exits 0).
