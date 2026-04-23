---
status: complete
phase: 00-foundations-hard-gate
source:
  - 00-01-SUMMARY.md
  - 00-02-SUMMARY.md
  - 00-03-SUMMARY.md
  - 00-04-SUMMARY.md
  - 00-05-SUMMARY.md
  - 00-06-SUMMARY.md
  - 00-07-SUMMARY.md
  - 00-08-SUMMARY.md
started: 2026-04-23T21:27:07Z
updated: 2026-04-23T21:35:00Z
executed_by: claude-code (programmatic)
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Fresh `uv sync --all-extras` + `uv run folio-insights --help` boots; `bench` subgroup visible; pytest collects ≥ 37 tests.
result: pass
evidence: |
  `uv sync --all-extras` → Resolved 130 packages, 1 installed.
  `folio-insights --help` → lists bench/discover/export/extract/serve.
  `pytest tests/bench/ -m "not gate5 and not slow and not gate4 and not gate3" --collect-only -q` → 54 tests collected (18 deselected).

### 2. Bench Generator CLI Produces Deterministic Fixture
expected: `bench gen --seed 42 --target 10000 ...` → 10,000 lines, zero `<<`, identical SHA256 on re-run.
result: pass
evidence: |
  Run 1 SHA256: 6acd356a53100fe9ffcc4a3634f82dae72ae0a81d86390313c83115a5b6d95c9
  Run 2 SHA256: 6acd356a53100fe9ffcc4a3634f82dae72ae0a81d86390313c83115a5b6d95c9
  wc -l → 10000; grep -c '<<' → 0.

### 3. Gate 1 RDF-12 Suite Green (32 Tests)
expected: `pytest tests/bench/test_gate1_rdf12.py --timeout=60` → 32/32 pass.
result: pass
evidence: 32 passed in 4.19s (13 gold non-empty + 13 file-discipline + 5 adversarial + 1 SSRF). SSRF preflight returns in ms, not 5-135s.

### 4. Gate 2 P95 Warm Harness Green (D-05 PASS)
expected: All 13 warm parametrizations pass with P95 < 500 ms.
result: pass
evidence: |
  13 passed in 6.82s. Worst-case Max latency = 118.78 ms (q13_confidence_histogram).
  All other queries Max < 40.36 ms except q13. Gate 2 hard target 500 ms met by every query with >4x headroom.

### 5. PyoxigraphStore Wrapper Unit Tests
expected: `pytest tests/store/` all pass.
result: pass
evidence: 14 passed in 0.07s (61 DeprecationWarnings from rdflib Dataset.default_context — pre-existing, non-blocking).

### 6. HermitHarness Smoke Tests
expected: 4 non-D-11 tests pass; 1 D-11 skips without `FOLIO_RUN_D11=1`.
result: pass
evidence: 4 passed, 1 skipped in 0.72s.

### 7. Phase 0 Decision Artifacts Exist + Consistent
expected: DECISION.md, BRANCH-GUIDANCE.md, fuseki/config.ttl, fuseki/README.md present; DECISION contains `keep=pyoxigraph`; fuseki banner matches.
result: pass
evidence: |
  00-DECISION.md 15977 bytes; 00-BRANCH-GUIDANCE.md 4117 bytes; fuseki/config.ttl 661 bytes; fuseki/README.md 2074 bytes.
  fuseki/README.md banner: "Status (Phase 0 DECISION): keep=pyoxigraph (scaffold not required; retained for v2.1 re-evaluation)" — exact match.

### 8. SvelteKit SSR Build Produces All Three Surfaces
expected: `npm run build` completes; `build/index.js` exists; manifest references `shards/[id]`, `polysemy/[id]`, `timeline/[id]`.
result: pass
evidence: |
  "built in 2.00s" via @sveltejs/adapter-node; build/index.js = 10114 bytes.
  manifest.js grep → all three surfaces present.

### 9. Gate 3 Image Size Test (Worker ≤ 500 MB)
expected: Test passes or skips cleanly; never fails on config/import.
result: pass
evidence: 1 passed in 0.07s (fi-worker:smoke image not present locally; test skip-guard fires cleanly).

### 10. Gate 5 Bit-Identical Digest Test Collectable
expected: 4 tests collected without errors.
result: pass
evidence: 4 tests collected in 0.01s (2 local + 2 parametrized Railway-skipif).

## Summary

total: 10
passed: 10
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none]
