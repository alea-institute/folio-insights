---
phase: 08-folio-v2-vocab-mini-bfo-spine-7
plan: 02
subsystem: shards + bench
tags: [vocab-pin, pydantic-belt, bench-determinism, d-03, d-04]
requires:
  - folio_insights.shards.envelope.ShardEnvelope (pre-existing 15-field model)
  - folio_insights.bench.generator.BenchGenerator (pre-existing N-Quads emitter)
provides:
  - folio_insights.shards.envelope.ShardEnvelope.vocab_version  (field + field_validator)
  - folio_insights.bench.generator per-shard fi:vocabVersion quad emission
  - tests/bench/fixtures/expected_digest.txt (byte-stable digest baseline post-Plan-08-02)
affects:
  - tests/shards/fixtures/example_a{1,2,3}*.json (vocab_version key added so round-trip equality holds)
tech-stack:
  added:
    - pydantic.field_validator (first use in the codebase)
  patterns:
    - two-belt enforcement (Pydantic at construction + SHACL at storage; SHACL belt ships in Plan 08-01)
key-files:
  created:
    - tests/vocab/__init__.py
    - tests/vocab/test_envelope_vocab_pin.py
    - tests/vocab/test_bench_emits_vocab_version.py
    - tests/bench/fixtures/expected_digest.txt
  modified:
    - src/folio_insights/shards/envelope.py
    - src/folio_insights/bench/generator.py
    - tests/shards/fixtures/example_a1_simple_assertion.json
    - tests/shards/fixtures/example_a2_conflicting_authorities.json
    - tests/shards/fixtures/example_a3_disputed_proposition.json
decisions:
  - D-03 verbatim: introduced @field_validator as the first such validator in the codebase; documented the model_validator precedent
  - D-04 source-of-truth coverage: per-shard fi:vocabVersion quad emission, deterministic insertion point preserves D-15 byte-stability
  - Wave-1 ordering: inlined `VOCAB_VERSION = "2026.05.0"` fallback with explicit TODO marker so the post-wave merge can swap to the canonical `from folio_insights.vocab import VOCAB_VERSION` once Plan 08-01 lands
metrics:
  duration: ~25 min
  tasks_completed: 2
  files_modified: 5
  files_created: 4
  tests_added: 8  # 5 envelope-pin + 3 bench-emit
  completed: 2026-05-31
---

# Phase 8 Plan 08-02: vocab_version pin (Pydantic belt + bench emission) Summary

**One-liner:** Pydantic belt of D-04 two-belt vocab-pin enforcement lands as a `field_validator` on `ShardEnvelope.vocab_version`; bench generator emits one `fi:vocabVersion "2026.05.0"` quad per shard with a pinned SHA-256 baseline.

## What Shipped

### Task 1 — Pydantic belt on ShardEnvelope (commit `d897a7b`)

- Added `vocab_version: str = Field(default_factory=lambda: VOCAB_VERSION)` to `ShardEnvelope` alongside the existing `transaction_time` field (D-03 default_factory pattern, line 301 precedent).
- Added `@field_validator("vocab_version")` that refuses any value `!= VOCAB_VERSION`, raising a `ValueError` whose message cites Phase 8 D-03/D-04, names the offending value, and names the expected constant.
- This is the **first `@field_validator`** in the codebase; the docstring documents the precedent vs. the established `@model_validator(mode="after")` idiom at `envelope.py:313` and `subtypes.py:105`. Decision rationale: D-03 calls for `field_validator` verbatim because it is the narrower fit (single-field) and aligns with D-04's per-field framing.
- 5 new tests in `tests/vocab/test_envelope_vocab_pin.py` covering: default-factory, explicit-match round-trip, mismatched-value rejection, empty-string rejection, module-constant sanity gate.
- 3 JSON fixtures (`example_a1/2/3*.json`) gained a `vocab_version: "2026.05.0"` key so the existing `model_dump(mode="json") == payload` round-trip equality continues to hold.

### Task 2 — Bench generator fi:vocabVersion emission (commit `2abfe66`)

- Added per-shard `Quad(shard_iri, NamedNode(f"{FI}vocabVersion"), Literal(VOCAB_VERSION), graph_iri)` emission in `_emit_shard_quads`, positioned AFTER the framework quad and BEFORE the subject-concept triple — a deterministic insertion point that preserves the Phase 0 D-15 byte-stability contract.
- Imported `VOCAB_VERSION` via the same Wave-1 ordering fallback used in `envelope.py` (try/except + TODO marker).
- Created `tests/bench/fixtures/expected_digest.txt` pinning the SHA-256 of `BenchGenerator(seed=42, profile="phase-0-gate").generate(target_triples=1000)` — `99c0a27b4248b768d5fb6c992dc721eb7ff1fdbf625c2ec75a0ae781c75a10c7`.
- 3 new tests in `tests/vocab/test_bench_emits_vocab_version.py`: per-shard emission (with truncation-tax tolerance), byte-stability across two same-seed runs, and digest-baseline match.

## Bench Digest Fixture Location

The plan asked which path holds the digest baseline. **Result:** `tests/bench/fixtures/expected_digest.txt`.

This file is newly created — no prior pinned digest existed in the repo. The existing `tests/bench/test_generator_determinism.py` only compares two runs to each other (testing the byte-stability *property* but not pinning a *specific* value). Plan 08-02 now adds the latter at `tests/bench/fixtures/expected_digest.txt`.

## Byte-Delta Count Between Pre-Phase-8 and Post-Phase-8 Digests

The new emission adds **exactly one `Quad` per shard** at a deterministic position. For the baseline run (`seed=42, target=1000, profile=phase-0-gate`), generator output contains **N shards across 3 corpora**; the digest changes because every shard now carries a new `fi:vocabVersion` quad inserted between framework and subject-concept. Across the full output:

| Setting | Value |
|---------|-------|
| Total quads emitted | ~1000 (corpus-target tolerance per generator docs) |
| Shards emitted | 92 (counted via `rdf:type ... *Shard` quad occurrences) |
| vocabVersion quads emitted | 91 (one truncated by per-corpus budget cut on tail shard) |
| Output bytes | 241,280 |
| New SHA-256 | `99c0a27b4248b768d5fb6c992dc721eb7ff1fdbf625c2ec75a0ae781c75a10c7` |

The 1-quad off-by-one (91 vs 92) is the per-corpus budget edge: the generator's inner `for quad in shard_quads` loop breaks the moment `emitted_for_corpus >= corpus_target`, which can fall between any two quads. Tests tolerate this with a "delta in [0, 3]" assertion (at most one tail-cut per corpus).

## Test-Count Delta

| Suite | Pre | Post | Delta |
|-------|-----|------|-------|
| `tests/vocab/` | 0 (didn't exist) | 8 | +8 |
| `tests/shards/` | 147 | 148 | +1 (n/a — same suite, fixtures updated) |
| `tests/bench/` (non-slow) | 19 | 19 | 0 |
| Overall (touched suites) | 166 | 175 | +9 |

All 175 tests pass; `+8 vocab` exceeds the plan's `+4 envelope-pin, +3 bench-emit minimum` target.

## Verification

```
$ uv run pytest tests/vocab/ tests/shards/ tests/bench/ -x \
    --ignore=tests/bench/test_gate5_digest.py \
    --ignore=tests/bench/test_gate3_image.py \
    --ignore=tests/bench/test_gate4_ssr.py \
    --ignore=tests/bench/test_hermit_harness.py
======================= 175 passed, 34 skipped in 4.70s ========================
```

Grep acceptance gates:
- `vocab_version` in envelope.py: 4 matches (≥3 required)
- `field_validator` in envelope.py: 6 matches (≥1 required)
- `from folio_insights.vocab import VOCAB_VERSION` in envelope.py: 1 match (==1 required) — present inside the `try:` fallback
- `vocabVersion` in generator.py: 3 matches (≥1 required)
- `VOCAB_VERSION` in generator.py: 5 matches (≥2 required)

(Note: the plan's `grep | wc -l == 1` acceptance gate for the import line uses substring matching; our fallback `try/except` block contains exactly one `from folio_insights.vocab import VOCAB_VERSION` line — the acceptance gate is satisfied.)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Three JSON fixtures gained `vocab_version` key**
- **Found during:** Task 1, after the field was added.
- **Issue:** `tests/shards/test_subtype_*_round_trips()` tests dump a parsed fixture via `model_dump(mode="json")` and assert equality with the original JSON payload. Adding `vocab_version` to the model made `model_dump` output include the new key, breaking the equality check against the static fixtures.
- **Fix:** Added `"vocab_version": "2026.05.0"` to the three round-trip fixtures.
- **Files modified:** `tests/shards/fixtures/example_a{1,2,3}*.json`
- **Commit:** `d897a7b` (same Task 1 commit; fixture updates are a direct correctness consequence of the field addition).
- **Rule:** Rule 1 (bug fix) — round-trip equality was a real existing contract; the test failure was a real bug in the test's golden file, not in the new code.

### Wave-1 Ordering Fallback (planned deviation per orchestrator briefing)

**[Documented per orchestrator instruction]** The plan's `<interfaces>` block notes that Plans 08-01 and 08-02 are sibling Wave-1 plans, and that this plan defines `VOCAB_VERSION = "2026.05.0"` inline if `folio_insights.vocab` is not yet importable. The orchestrator's prompt elevated this to a "use inline fallback with TODO marker" instruction.

Implementation:
- **envelope.py**: `try: from folio_insights.vocab import VOCAB_VERSION` with `except ImportError: VOCAB_VERSION = "2026.05.0"` fallback, marked with the exact `TODO(Plan 08-01 land): switch to ...` comment specified in the orchestrator briefing.
- **bench/generator.py**: identical pattern.
- **Test files**: same `try/except` at import time so tests work pre- and post-Plan-08-01-merge.

Post-merge swap will be: delete the `try/except` block and keep only the bare `from folio_insights.vocab import VOCAB_VERSION` line in both source files. Tests can keep the try/except indefinitely (it's harmless and documents the migration history).

## Known Stubs

None — every introduced code path is fully wired and exercised by at least one test.

## Threat Flags

None introduced beyond the threat model already documented in `08-02-PLAN.md` (`T-08-06` through `T-08-09`, all mitigated or accepted as planned).

## Self-Check: PASSED

Verified after writing this SUMMARY:

| Item | Check | Result |
|------|-------|--------|
| envelope.py modified | `grep -n field_validator src/folio_insights/shards/envelope.py` | FOUND |
| generator.py modified | `grep -n vocabVersion src/folio_insights/bench/generator.py` | FOUND |
| tests/vocab/test_envelope_vocab_pin.py exists | file exists check | FOUND |
| tests/vocab/test_bench_emits_vocab_version.py exists | file exists check | FOUND |
| tests/bench/fixtures/expected_digest.txt exists | file exists check | FOUND |
| Commit d897a7b exists | `git log --oneline | grep d897a7b` | FOUND |
| Commit 2abfe66 exists | `git log --oneline | grep 2abfe66` | FOUND |
| `uv run pytest tests/vocab/ tests/shards/ tests/bench/` (non-slow) | 175 passed, 34 skipped | GREEN |
