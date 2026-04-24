---
phase: 01-polysemy-distinguo-spike
plan: 01
subsystem: testing

tags: [pytest, scaffolding, polysemy, pyoxigraph, cryptography, did-key, base58, red-state, xfail]

# Dependency graph
requires:
  - phase: 00-foundations-hard-gate
    provides: PyoxigraphStore wrapper (STORAGE-02) + session-scoped bench_store fixture pattern + pyproject.toml marker block
provides:
  - tests/polysemy/ package with 8 test files (17 xfail placeholders, one per 01-VALIDATION.md row)
  - session-scoped consideration_fixture_store fixture (empty in-memory PyoxigraphStore; Plan 01-02 will wire fixture loader)
  - polysemy_spike pytest marker registered in pyproject.toml
  - cryptography 46.0.7 + base58 2.1.1 installed (A1 + A2 resolved as "missing, newly added")
  - .gitignore exclusion of .folio-insights/ (T-01-01 mitigation against accidental private-key commit)
affects: [01-02-dispositions, 01-02-reviewer-did, 01-03-detector, 01-04-distinguo-emission, 01-05-cli-review, 01-06-fp-rate]

# Tech tracking
tech-stack:
  added: [cryptography>=41, base58>=2.1]
  patterns:
    - "Session-scoped PyoxigraphStore fixture (mirrors tests/bench/conftest.py::bench_store)"
    - "RED-state xfail scaffolding (strict=False) — tests collect cleanly, fail with known reason until downstream plans implement"
    - "One xfail test per 01-VALIDATION.md row — test command-suffixes map verbatim to pytest ::test_X"

key-files:
  created:
    - tests/polysemy/__init__.py
    - tests/polysemy/conftest.py
    - tests/polysemy/test_detector_rules.py
    - tests/polysemy/test_detector_llm_fallback.py
    - tests/polysemy/test_prototype_cluster.py
    - tests/polysemy/test_distinguo_emission.py
    - tests/polysemy/test_cli_review.py
    - tests/polysemy/test_dispositions_jsonl.py
    - tests/polysemy/test_fp_rate.py
    - tests/polysemy/test_reviewer_did.py
  modified:
    - pyproject.toml
    - .gitignore

key-decisions:
  - "A1 resolution: cryptography was missing from the venv (not transitively present); added explicit cryptography>=41 direct dep"
  - "A2 resolution: base58 was missing (expected per research note); added base58>=2.1 direct dep"
  - "xfail strict=False (not strict=True) so downstream plans can incrementally turn tests green without a mass-update to this SUMMARY"

patterns-established:
  - "Wave-0 scaffolding always precedes any src/folio_insights/<subsystem>/ module creation (matches Phase 0 Wave-0 pattern)"
  - "tests/polysemy/conftest.py::FIXTURE_DIR constant gives all 01-02..01-06 tests a single path-resolution entry point"

requirements-completed: []  # Wave-0 scaffold only — requirement IDs land in 01-02..01-06

# Metrics
duration: ~12min
completed: 2026-04-24
---

# Phase 01 Plan 01: Wave-0 Test Scaffold Summary

**tests/polysemy/ package with 8 RED-state test files, session-scoped PyoxigraphStore fixture, polysemy_spike marker, and newly-added cryptography + base58 deps — pytest collects 17 xfail placeholders cleanly, establishing the RED baseline for Plans 01-02..01-06.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-04-24T16:12:00Z (approx)
- **Completed:** 2026-04-24T16:24:39Z
- **Tasks:** 2
- **Files modified:** 12 (10 new test-tree files + pyproject.toml + .gitignore)

## Accomplishments

- Registered `polysemy_spike` pytest marker in pyproject.toml alongside existing integration/gate3/gate4/gate5/slow markers.
- Added `cryptography>=41` and `base58>=2.1` as explicit direct deps (A1 + A2 from 01-RESEARCH.md §Assumptions Log — both confirmed missing from the worktree venv, not transitively installed).
- Excluded `.folio-insights/` in `.gitignore` as belt-and-suspenders protection against accidental private-key commit (T-01-01 mitigation; real key lives at `$HOME/.folio-insights/` outside the repo).
- Created `tests/polysemy/` package with empty `__init__.py` and session-scoped `consideration_fixture_store` fixture wrapping an in-memory `PyoxigraphStore(path=None)` — ready for Plan 01-02 to wire the fixture JSON loader.
- Scaffolded all 8 Wave-0 test files from 01-VALIDATION.md with 17 xfail placeholders (one test function per VALIDATION.md row command-suffix). `strict=False` so downstream plans can flip tests green incrementally.
- `pytest tests/polysemy/ --collect-only -q` → 17 tests collected, zero import errors, zero warnings. Marker filter (`-m polysemy_spike`) returns the same 17.

## Task Commits

Each task committed atomically:

1. **Task 1: Register pytest marker + verify/add crypto deps + update .gitignore** — `7913316` (chore)
2. **Task 2: Scaffold tests/polysemy/ package with session-scoped fixture + empty RED test files** — `3fd38b1` (test)

_Metadata commit for this SUMMARY will be added separately after self-check._

## Files Created/Modified

**Created (10):**
- `tests/polysemy/__init__.py` — empty package marker
- `tests/polysemy/conftest.py` — `consideration_fixture_dir` + `consideration_fixture_store` session fixtures (PyoxigraphStore path=None; fixture-dir path-resolution constant)
- `tests/polysemy/test_detector_rules.py` — 4 xfail tests (Rule 1 axioms, Rule 2 N≥3, Rule 3 whitelist threshold, Rule 4 homonym flag) targeting 01-03
- `tests/polysemy/test_detector_llm_fallback.py` — 1 xfail test (discriminated-union verdict) targeting 01-03
- `tests/polysemy/test_prototype_cluster.py` — 1 xfail test (centroid per framework) targeting 01-03
- `tests/polysemy/test_distinguo_emission.py` — 3 xfail tests (analogousTo sub-properties, distinctionKind enum, TTL roundtrip) targeting 01-04
- `tests/polysemy/test_cli_review.py` — 2 xfail tests (no auto-apply path, accept/reject/modify paths) targeting 01-05
- `tests/polysemy/test_dispositions_jsonl.py` — 2 xfail tests (Phase 15 schema match, append-only) targeting 01-02
- `tests/polysemy/test_fp_rate.py` — 3 xfail tests (FP-rate within target, Wilson CI, audit-disagreements-only) targeting 01-06
- `tests/polysemy/test_reviewer_did.py` — 1 xfail test (first-invocation real did:key) targeting 01-02

**Modified (2):**
- `pyproject.toml` — added `polysemy_spike` marker; added `cryptography>=41` + `base58>=2.1` to `[project].dependencies`
- `.gitignore` — appended `.folio-insights/` exclusion

## Decisions Made

- **A1 (cryptography) resolution:** `uv pip show cryptography` returned "Package(s) not found" — cryptography was not transitively installed via instructor, httpx, or any other declared dep. Added `cryptography>=41` as an explicit direct dep. Post-install version: 46.0.7.
- **A2 (base58) resolution:** `uv pip show base58` returned "Package(s) not found" — base58 was not a current project dep (expected per research). Added `base58>=2.1` as an explicit direct dep. Post-install version: 2.1.1.
- **xfail `strict=False`:** chosen so that when downstream plans (01-02..01-06) implement a test and it flips from xfail→xpass, the suite stays green rather than failing with `[XPASS(strict)]`. This trades a small amount of RED-discipline for incremental-landing ergonomics. Acceptable for scaffold purposes; future impl plans can tighten to `strict=True` once they deliberately wire the behavior.
- **`FIXTURE_DIR` module constant** instead of a pytest fixture for the path itself: keeps the path resolution cheap, grep-able, and usable from `conftest.py` in the body of `consideration_fixture_store` without fixture dependency-chain overhead.
- **Empty `__init__.py`** rather than namespace package: explicit package boundary is clearer for grep/tooling, and matches `tests/bench/__init__.py` convention already in the repo.

## Deviations from Plan

None — plan executed exactly as written. Both assumption mitigations (A1 add-if-missing, A2 add-if-missing) triggered the add path as predicted in 01-RESEARCH.md.

## Issues Encountered

- Worktree had no `.venv`. First `uv run` in the worktree auto-created a fresh venv and installed the base dependencies (~98 packages). A second `uv pip install -e '.[dev]'` after editing pyproject.toml pulled in cryptography + base58 + pycparser + cffi. Not a blocker — standard uv behavior in a freshly-created git worktree.

## Wave-0 Verification Output

```
$ ./.venv/bin/pytest tests/polysemy/ --collect-only -q
[... 17 test IDs ...]
17 tests collected in 0.01s

$ ./.venv/bin/pytest --markers | grep polysemy_spike
@pytest.mark.polysemy_spike: Phase 1 polysemy-distinguo spike tests

$ uv pip show cryptography base58 | grep -E '^(Name|Version):'
Name: base58
Version: 2.1.1
Name: cryptography
Version: 46.0.7

$ grep folio-insights .gitignore
.folio-insights/
```

All four verification commands pass.

## User Setup Required

None — no external service configuration required. `uv pip install -e '.[dev]'` refreshes the venv when cryptography/base58 land for other developers.

## Next Phase Readiness

- Plan 01-02 can now:
  - Wire `dispositions.jsonl` writer + test_dispositions_jsonl tests turn green
  - Wire real did:key generation using newly-available cryptography + base58 deps + test_reviewer_did turns green
  - Populate `.planning/phases/01-polysemy-distinguo-spike/fixtures/consideration/*.json` — conftest's `consideration_fixture_dir` already points at the right location
- Plan 01-03 can now drive detector rules + LLM fallback + prototype cluster tests red→green
- Plan 01-04 can now drive distinguo TTL emission tests red→green (round-trip uses `consideration_fixture_store` fixture)
- Plan 01-05 can now implement CLI and drive test_cli_review tests red→green
- Plan 01-06 can now implement FP-rate harness and drive test_fp_rate tests red→green

**Blockers for downstream:** None. RED state is intentional and expected.

## Self-Check

- [x] tests/polysemy/__init__.py exists
- [x] tests/polysemy/conftest.py exists (contains consideration_fixture_store + PyoxigraphStore)
- [x] 8 test files in tests/polysemy/ (ls tests/polysemy/test_*.py | wc -l = 8)
- [x] pyproject.toml contains polysemy_spike marker
- [x] pyproject.toml contains cryptography>=41 and base58>=2.1
- [x] .gitignore excludes .folio-insights/
- [x] Commit 7913316 (Task 1) on master branch
- [x] Commit 3fd38b1 (Task 2) on master branch
- [x] pytest tests/polysemy/ --collect-only exits 0 with 17 tests collected

## Self-Check: PASSED

All 10 created files verified on disk, both task commits verified in git log, and `pytest tests/polysemy/ --collect-only` exits 0 with 17 collected items.

---
*Phase: 01-polysemy-distinguo-spike*
*Completed: 2026-04-24*
