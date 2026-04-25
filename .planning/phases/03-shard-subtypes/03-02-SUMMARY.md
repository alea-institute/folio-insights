---
phase: 03
plan: 02
subsystem: shards
tags: [shards, subtypes, tests, fixtures, hypothesis, prd-§6.2]
requires:
  - 03-01 (subtypes.py expansion + _SUBTYPE_DEFAULTS in conftest)
  - mint_shard_iri (Phase 02; used to compute deterministic fixture IRIs)
  - PRD §6.2 examples A.1, A.2, A.3 (verbatim source-of-truth)
provides:
  - 3 verbatim PRD §6.2 JSON fixtures (A.1, A.2, A.3) with deterministic minted IRIs
  - 5 per-subtype unit test modules covering positive + validator-raises tests
  - 1 per-subtype hypothesis property-test module honoring D-09 1000-example budget
  - 82 new tests on top of Phase 02's 47 (full tests/shards/ = 129 green)
  - Exit criteria 1-3 closed for Phase 03 (A.1/A.2/A.3 round-trip; Gloss + Hypothesis parse/validate; citation_required ships)
affects: []
tech-stack:
  added: []
  patterns:
    - JSON test fixtures committed under tests/shards/fixtures/ (first in repo)
    - TypeAdapter(Shard).validate_python(payload).model_dump(mode='json') == payload round-trip
    - per-subtype hypothesis @settings(max_examples=N, deadline=None) per D-09 budget
    - parametrize over Literal enum values + parametrize over outside-subset for validator coverage
key-files:
  created:
    - tests/shards/fixtures/example_a1_simple_assertion.json
    - tests/shards/fixtures/example_a2_conflicting_authorities.json
    - tests/shards/fixtures/example_a3_disputed_proposition.json
    - tests/shards/test_subtype_simple_assertion.py
    - tests/shards/test_subtype_disputed_proposition.py
    - tests/shards/test_subtype_conflicting_authorities.py
    - tests/shards/test_subtype_gloss.py
    - tests/shards/test_subtype_hypothesis.py
    - tests/shards/test_subtype_properties.py
  modified: []
decisions:
  - Fixture round-trip uses model_dump(mode='json') so datetime → ISO string aligns with the JSON 'Z'-suffixed transaction_time
  - Property-test gloss generator skips collision when generated IRI matches the fixture's own shard_iri (rare; would trip self-glossing validator)
  - All 3 fixtures populate every required envelope field beyond the PRD's body so TypeAdapter dispatch + bidirectional round-trip succeed
metrics:
  duration: ~10 min
  completed: 2026-04-25
  tasks: 2
  files: 9
---

# Phase 03 Plan 02: Per-Subtype Tests + PRD §6.2 Fixtures Summary

**One-liner:** Shipped 3 verbatim PRD §6.2 JSON fixtures (A.1, A.2, A.3), 5 per-subtype unit test modules, and 1 hypothesis property-test module — adding 82 new tests on top of Phase 02's 47 (full `tests/shards/` suite = **129 green** in 1.22s).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | A.1/A.2/A.3 fixtures + SimpleAssertion/Disputed/ConflictingAuthorities tests | `1fef45c` | 6 (3 JSON + 3 test modules) |
| 2 | Gloss + Hypothesis tests + per-subtype property tests | `27b371e` | 3 test modules |

## What Was Built

### `tests/shards/fixtures/example_a1_simple_assertion.json`

Verbatim PRD §6.2.1 Example A.1 transcribed with all 22 required envelope fields populated. Deterministic minted IRI: `urn:folio:shard/9c462655207f3bbd` (provenance hash `9c462655207f3bbd2db05164b573d930d48987e7bde164f9c4496430d0589a7f`). Round-trips through `TypeAdapter(Shard).validate_python().model_dump(mode='json') == payload` cleanly.

### `tests/shards/fixtures/example_a2_conflicting_authorities.json`

Verbatim PRD §6.2.3 Example A.2 with `sic` (2 positions: binding, majority), `non` (1 position: binding), `reconciliation_strategy: "jurisdictional_scoping"` (1 of 8), and a non-blank `reconciliation_note`. Deterministic minted IRI: `urn:folio:shard/5209ecb1ed57f37c`.

### `tests/shards/fixtures/example_a3_disputed_proposition.json`

Verbatim PRD §6.2.2 Example A.3 with `utrum`, 2 `objections`, `sed_contra`, `respondeo`, 2 `replies` (objection_index 0 and 1, both within range). Uses `epistemic_status: "contested"` (in the D-03 4-subset). Deterministic minted IRI: `urn:folio:shard/b6747d6d8771a48d`.

### `tests/shards/test_subtype_simple_assertion.py` — 3 tests

A.1 fixture round-trip + envelope-only construction via `_sample_shard` + `extra="forbid"` regression guard.

### `tests/shards/test_subtype_disputed_proposition.py` — 13 tests

A.3 fixture round-trip + parametrize over 4 in-subset epistemic_status values (4 tests) + parametrize over 4 outside-subset values (4 tests, all expected to raise) + empty-objections + out-of-range Reply.objection_index + Objection.strength bounds + Reply.replies_via Literal[4].

### `tests/shards/test_subtype_conflicting_authorities.py` — 20 tests

A.2 fixture round-trip + parametrize over all 8 ReconciliationStrategy values (8 tests) + 9th-rejected + parametrize over 4 AuthorityPosition.weight values (4 tests) + invalid weight + empty sic/non + parametrize over 3 blank reconciliation_note inputs (3 tests).

### `tests/shards/test_subtype_gloss.py` — 23 tests

5 GlossKind values (5 tests) + invalid kind + 5 valid IRI shapes (5 tests) + 7 invalid IRI shapes (7 tests) + self-glossing rejection + 3 empty/whitespace gloss_text rejections (3 tests) + round-trip.

### `tests/shards/test_subtype_hypothesis.py` — 18 tests

3 GenerationMethod values (3 tests) + invalid method + ttl_days default (90) + citation_required default (True) + promotion_requirements default ([]) + 6 positive ttl_days values (6 tests) + 3 zero/negative ttl_days values (3 tests) + Phase-7-deferred no-gate construction test + round-trip.

### `tests/shards/test_subtype_properties.py` — 5 tests (≤1000 hypothesis examples total)

Per-subtype @settings(max_examples=N, deadline=None) property tests honoring CONTEXT D-09 budget exactly:

| Subtype | max_examples | Strategies covered |
|---------|--------------|--------------------|
| SimpleAssertion | 100 | sense, confidence |
| DisputedProposition | 300 | utrum, n_objections (1-5), respondeo, epistemic_status sampled from 4-subset, objection_strength |
| ConflictingAuthorities | 200 | strategy sampled from 8, weight_a/weight_b sampled from 4, non-blank note |
| Gloss | 200 | kind sampled from 5, 16-hex IRI body, non-blank gloss_text |
| Hypothesis | 200 | method sampled from 3, ttl 1-10000, citation_required boolean |
| **Total** | **1000** | **5 subtypes covered** |

## Verification

```bash
$ uv run pytest tests/shards/ -q
............................................................ [100%]
129 passed in 1.22s
```

```bash
$ uv run pytest tests/shards/ -q --durations=10
============================= slowest 10 durations =============================
0.54s call     tests/shards/test_minting_determinism.py::test_mint_is_deterministic
0.17s call     tests/shards/test_subtype_properties.py::test_disputed_proposition_constructs_round_trips
0.13s call     tests/shards/test_subtype_properties.py::test_gloss_constructs_round_trips
0.10s call     tests/shards/test_subtype_properties.py::test_conflicting_authorities_constructs_round_trips
0.08s call     tests/shards/test_subtype_properties.py::test_hypothesis_constructs_round_trips
0.04s call     tests/shards/test_subtype_properties.py::test_simple_assertion_constructs_round_trips
129 passed in 1.22s
```

Property-test module total runtime **0.54s** — well under the D-09 2s target with **3.7× headroom**.

```bash
$ uv run pytest tests/shards/test_dep_leak_guard.py -q
1 passed in 0.04s
```

Phase 02 dep-leak guard remains green — no `pyoxigraph` / `rdflib` / `oxrdflib` / `owlready2` imports introduced.

## Per-Module Test Counts

| Module | Tests |
|--------|-------|
| `test_subtype_simple_assertion.py` | 3 |
| `test_subtype_disputed_proposition.py` | 13 |
| `test_subtype_conflicting_authorities.py` | 20 |
| `test_subtype_gloss.py` | 23 |
| `test_subtype_hypothesis.py` | 18 |
| `test_subtype_properties.py` | 5 (≤1000 hypothesis examples) |
| **Phase 03 new** | **82** |
| Phase 02 carry-forward | 47 |
| **Full `tests/shards/` suite** | **129** |

## PRD §6.2 Coverage Confirmation

- **Example A.1 (SimpleAssertion):** round-trips via `TypeAdapter(Shard).validate_python(payload).model_dump(mode='json') == payload`
- **Example A.2 (ConflictingAuthorities):** round-trips; `reconciliation_strategy="jurisdictional_scoping"` (1 of 8)
- **Example A.3 (DisputedProposition):** round-trips; 2 objections + 2 replies (objection_index 0, 1 both in range)
- **All 8 ReconciliationStrategy values** parametrized + each constructs successfully
- **All 5 GlossKind values** parametrized + each constructs successfully
- **All 3 GenerationMethod values** parametrized + each constructs successfully
- **D-03 4-subset** `{"hypothesis", "authority_only", "contested", "aporetic"}` — `"attested"` absent from all test code (verified by `! grep -q '"attested"'`)
- **HypothesisShard.citation_required = True** ships as field; Phase-7-deferred no-gate behavior covered by `test_citation_required_true_with_empty_deps_constructs`

## Key Decisions

1. **`model_dump(mode='json')` for fixture round-trip:** Pydantic v2 serializes tz-aware UTC datetimes with the `Z` suffix when input was `Z`-suffixed, so `mode='json'` keeps fixture/redump byte-equality. `mode='python'` would yield raw `datetime` objects that wouldn't compare equal to the JSON string.
2. **Deterministic fixture IRIs:** Each fixture IRI was minted via `mint_shard_iri("urn:x:fixture-aN", "<span>")` and hard-coded into the JSON. The `_sample_shard` factory's default IRI uses a different (uri, span) pair, so the GlossShard's default `glosses="urn:folio:shard/0123456789abcdef"` does not collide with any fixture or sample IRI.
3. **Gloss property-test collision skip:** Hypothesis can theoretically shrink to a generated IRI that equals the fixture's `shard_iri` (very rare with 16 random hex chars). The test guards with `if iri == shard.shard_iri: return` rather than expecting the validator to raise — Plan-aligned (the property test exercises round-trip success, not the self-gloss invariant which has a dedicated unit test).
4. **JSON fixtures populate every envelope field:** PRD §6.2 examples in the prose only show subtype-specific bodies. To make TypeAdapter(Shard) dispatch + round-trip work, every required envelope field is filled with values that match `_sample_shard`'s defaults (alphabetical: `bfo_category="continuant_dependent"`, `confidence=0.95/0.85/0.8`, `extractor_model="claude-opus-4-7"`, etc.). All deviations are conscious envelope completions, not PRD-body changes.

## Deviations from Plan

None — plan executed exactly as written. The plan's pre-resolved D-03 substitution (`"authority_only"` for the PRD's `"attested"`) was honored everywhere: in test parametrize lists, in property-test sampled_from, and in fixture A.3's `epistemic_status: "contested"` choice.

## Threat Model Compliance

All Phase 03 plan-level threat-register dispositions honored:

- **T-03-07 (Tampering of fixtures):** mitigate — fixtures committed to git; loaded via `Path(__file__).parent / "fixtures" / "..."` (no path-traversal surface, `Path` from `__file__` not external input). Round-trip assertion `parsed.model_dump(mode='json') == payload` detects any silent fixture corruption.
- **T-03-08 (DoS via hypothesis-generated inputs):** mitigate — D-09 budget capped at exactly 1000 (100+300+200+200+200). All strategies bounded (`min_size`/`max_size` on text, `min_value`/`max_value` on integers, `allow_nan=False` on floats). `deadline=None` prevents per-example timing flakes; pytest global timeout still applies.
- **T-03-09 (Information disclosure via failure messages):** accept — test-only path; CI logs are repo-internal. Validator messages from Plan 01's `subtypes.py` already constrain disclosure to field names + canonicalized values (T-03-01 mitigation transitively bounds test logs).

No network I/O, subprocess, auth, cryptography, or SQL touched.

## Metrics

- **Duration:** ~10 min (2 sequential tasks, both autonomous)
- **Tasks:** 2 / 2 completed
- **Files:** 9 created (3 JSON + 6 Python), 0 modified
- **LOC delta:**
  - Task 1: 6 files, +459 lines
  - Task 2: 3 files, +364 lines
  - **Total:** +823 LOC
- **Test count delta:** +82 (47 → 129 in `tests/shards/`)
- **Hypothesis examples:** 1000 total (D-09 budget hit exactly)
- **Property-test runtime:** 0.54s (D-09 target 2s; 3.7× headroom)
- **Phase 02 carry-forward suite:** 47 / 47 still green (no regression)
- **Dep-leak guard:** still green (no forbidden imports in `src/folio_insights/shards/*.py`)

## Self-Check: PASSED

- `tests/shards/fixtures/example_a1_simple_assertion.json` — FOUND
- `tests/shards/fixtures/example_a2_conflicting_authorities.json` — FOUND
- `tests/shards/fixtures/example_a3_disputed_proposition.json` — FOUND
- `tests/shards/test_subtype_simple_assertion.py` — FOUND
- `tests/shards/test_subtype_disputed_proposition.py` — FOUND
- `tests/shards/test_subtype_conflicting_authorities.py` — FOUND
- `tests/shards/test_subtype_gloss.py` — FOUND
- `tests/shards/test_subtype_hypothesis.py` — FOUND
- `tests/shards/test_subtype_properties.py` — FOUND
- Commit `1fef45c` (Task 1) — FOUND
- Commit `27b371e` (Task 2) — FOUND
- Full `tests/shards/` suite: 129 green in 1.22s — VERIFIED
