---
phase: 02-shard-envelope
plan: 03
subsystem: data-model
tags: [shards, tests, pydantic-roundtrip, discriminated-union, hypothesis-property, bitemporal, grep-guard, frozen-field, audit-log, dep-leak]

# Dependency graph
requires:
  - phase: 02-shard-envelope
    plan: 01
    provides: 15-field ShardEnvelope + 5 subtype stubs + Shard discriminated-union + mint_shard_iri + 11-symbol shards/ public surface
  - phase: 02-shard-envelope
    plan: 02
    provides: ContentEdit frozen sub-model + add_edit helper + ShardEnvelope.model_rebuild() wire-up + hypothesis>=6.100 dev dep + shards pytest marker
  - phase: 01-polysemy-distinguo-spike
    provides: tests/polysemy/ fixture-builder + ValidationError assertion patterns (test_dispositions_jsonl.py, test_distinguo_emission.py, test_fp_rate.py grep-guard precedent)
provides:
  - tests/shards/ 7-file test suite (__init__.py + conftest.py + 5 test modules)
  - 47 total tests across 5 test files covering SHARD-01 + SHARD-10 exit criteria
  - _sample_shard fixture-builder + _SUBTYPE_TABLE (parametrize-over-5-subtypes idiom)
  - Hypothesis 1000-example property test proving mint_shard_iri determinism (D-02)
  - 6-field frozen-identity regression suite (D-07 × 6 params)
  - Forward-ref JSON round-trip regression (critical regression gate for Plan 02-02's ShardEnvelope.model_rebuild())
  - Phase-13 dep-leak grep-guard (4 modules × shards/*.py substring check) + D-02 http-prefix override guard
  - shards pytest marker end-to-end verified (pytest -m shards runs the full 47 tests)
affects:
  - Phase 3 (Shard Subtypes) — _sample_shard fixture-builder will need a subtype_fields kwarg extension when Phase 3 adds PRD §6.2 subtype-specific fields (utrum / objections / sed_contra / sic / non / glosses / generation_method / ttl_days)
  - Phase 5 (Content Versioning SHACL gate) — Plan 02-03's D-08 tests are the regression floor; Phase 5 will EXTEND (not replace) add_edit with forward-only SHACL semantics and transactional rollback; add_edit_on_frozen_field_raises will morph to add_edit_on_frozen_field_rolls_back_append
  - Phase 4 (IRI collision detection) — mint_shard_iri determinism is proven here via 1000-example property test; Phase 4 re-uses the same function for nightly re-hash verification
  - All future phases (4-16) — the 7-file test suite is the Phase 2 exit gate; any downstream regression in shards/ must also pass these tests

# Tech tracking
tech-stack:
  added: []  # hypothesis dev dep was added by Plan 02-02; Plan 02-03 is pure test authoring
  patterns:
    - "Hypothesis property test (first repo use) — @settings(max_examples=1000, deadline=None) + @given(scheme, host, path, span) with strategies pipeline"
    - "Parametrized pytest fixtures over _SUBTYPE_TABLE (5 subtypes × 2 format round-trips = 10 param instances)"
    - "Directed-vector unicode normalization tests (NFC vs NFD, CRLF, RFC 3986 case-fold + trailing-slash + fragment-preserved) — no prior repo analog"
    - "TypeAdapter(Shard).validate_python(payload) for discriminated-union dispatch tests (first repo use of TypeAdapter)"
    - "Substring-match grep-guard regression idiom (walks pathlib.Path.glob('*.py'), asserts `import {mod}` and `from {mod}` substrings absent) — extends Phase 1's `test_wilson_score_interval_no_scipy_import` precedent"
    - "Forward-ref JSON round-trip regression — test_content_edits_survive_json_round_trip proves ShardEnvelope.model_rebuild() actually ran at import-time (content_edits[0] is a real ContentEdit, not a dict)"
    - "pytestmark = pytest.mark.shards module-scoped marker on every test module (mirrors tests/polysemy/ polysemy_spike idiom for CI-subset gating)"

key-files:
  created:
    - tests/shards/__init__.py
    - tests/shards/conftest.py
    - tests/shards/test_envelope_roundtrip.py
    - tests/shards/test_discriminated_union.py
    - tests/shards/test_minting_determinism.py
    - tests/shards/test_audit_log.py
    - tests/shards/test_dep_leak_guard.py
  modified: []  # Plan 02-03 is pure test-only; no production-code changes, no pyproject.toml edits

key-decisions:
  - "Fixture-builder lives in conftest.py and is imported explicitly via `from tests.shards.conftest import _sample_shard, _SUBTYPE_TABLE` rather than as pytest @fixture — matches plan's <interfaces> block + Phase 1 tests/polysemy/test_fp_rate.py _sample_record pattern. Explicit import keeps parametrize-over-_SUBTYPE_TABLE at module level (pytest fixtures can't be used as parametrize args)."
  - "_sample_shard uses real minted IRI+hash (via mint_shard_iri('urn:x:fixture', 'sample span')) rather than placeholder strings — makes fixture mirror the D-02 recipe; any test that later re-mints with same inputs gets matching values."
  - "Hypothesis strategies: scheme sampled_from(['http','https','urn']) with branching URI construction (urn doesn't use ://); host filter rejects leading/trailing dots (avoids urlsplit edge cases); path/span unrestricted text (max 50/200 chars). 1000 examples × deadline=None matches D-02 '1000 random runs' language exactly."
  - "Bitemporal bounded-round-trip test uses `startswith('2025-01-01T00:00:00')` prefix check rather than exact string match — accepts both `Z` suffix and `+00:00` tz-offset forms (Pydantic minor-version variance). Semantic equality (`rehydrated.valid_time_start == start`) is the hard gate."
  - "test_invalid_shard_type_raises_validation_error accepts either 'nonsense' (bad tag echoed) OR 'discriminator' in the error message — Pydantic phrasing varies across v2.x minors."
  - "Grep-guard uses substring match (`f\"import {mod}\" not in source`) rather than line-regex — catches `import rdflib`, `from rdflib import ...`, AND `from rdflib.term import ...` with one check per module. The plan's <interfaces> block is the authoritative pattern."

patterns-established:
  - "tests/shards/conftest.py explicit-import fixture-builder — a pattern for any future test package whose parametrize needs values at module-import time (pytest fixtures can't be used in @pytest.mark.parametrize). Plan 02-03's _sample_shard + _SUBTYPE_TABLE is the template."
  - "Forward-ref JSON round-trip regression test — critical when a Pydantic model declares `list['T']` forward string-refs. Without `ShardEnvelope.model_rebuild()`, `content_edits[0]` after JSON reparse would be a dict, not the declared class. `isinstance(rehydrated.content_edits[0], ContentEdit)` is the gate; this idiom is reusable for any forward-ref wire-up in the codebase."
  - "Hypothesis 1000-example + deadline=None for deterministic-hash property tests — 1000 runs is D-02's contract; deadline=None prevents per-example 200ms deadline flakes on complex unicode paths without hiding real bugs. Phase 4 collision-detection re-hash job can re-use this pattern."

requirements-completed: [SHARD-01, SHARD-10]

# Metrics
duration: ~5min
completed: 2026-04-24
---

# Phase 02 Plan 03: Comprehensive Test Suite Summary

**Seven-file test suite under tests/shards/ (47 tests, ≥ 40 required) proving SHARD-01 round-trip + discriminated-union dispatch + SHARD-10 bitemporal semantics + D-02 minting determinism (hypothesis 1000-example property) + D-07 6-field frozen immutability + D-08 ContentEdit audit-chain + Phase-13 dep-leak grep-guard — all 47 tests green, Phase 1 polysemy suite still green (49 tests, no regression), Phase 2 production-code + test surface complete.**

## Performance

- **Duration:** ~5 min (worktree base-reset + 11 file reads + 7 files written + 3 atomic commits + SUMMARY)
- **Started:** 2026-04-24T21:09Z
- **Completed:** 2026-04-24T21:14Z
- **Tasks:** 3 / 3 complete
- **Files created:** 7 (__init__.py + conftest.py + 5 test modules)
- **Files modified:** 0 (test-only plan; no production-code touch, no pyproject.toml edits)

## Accomplishments

- **tests/shards/__init__.py (1 line)** — empty test-package marker with a one-line docstring.
- **tests/shards/conftest.py (87 LOC)** — `_sample_shard(cls, **overrides)` keyword-only fixture-builder returning a fully-populated ShardEnvelope subtype instance (all 30+ envelope fields set to valid Literal defaults, nested `Triple(s,p,o)`, tz-aware UTC `extracted_at`, empty-list content_edits / signatures / depends_on_* / elaborates). `_SUBTYPE_TABLE` = list of 5 (tag, cls) tuples for parametrize.
- **tests/shards/test_envelope_roundtrip.py (127 LOC, 21 tests)** — SHARD-01 exit criterion 1 (5 subtypes × model_dump round-trip + 5 × JSON round-trip = 10 tests) + SHARD-10 (bitemporal null/bounded/tz-aware + transaction_time round-trip = 4 tests) + D-07 × 6 frozen identity fields (6 tests) + `extra="forbid"` regression (1 test).
- **tests/shards/test_discriminated_union.py (53 LOC, 7 tests)** — SHARD-01 exit criterion 2: TypeAdapter(Shard) dispatches to correct subtype class for each of 5 tags (5 tests) + invalid `shard_type` tag raises ValidationError with useful message (1 test) + D-06 per-subtype Literal default rejects foreign tag at direct-construction (1 test).
- **tests/shards/test_minting_determinism.py (103 LOC, 7 tests)** — first hypothesis adopter in the repo: `test_mint_is_deterministic` runs `@settings(max_examples=1000, deadline=None)` over 4-strategy `@given` (scheme × host × path × span), asserting `mint_shard_iri(uri, span) == mint_shard_iri(uri, span)` plus IRI/hash shape invariants. 6 directed vectors cover NFC vs NFD, CRLF trim, RFC 3986 case-fold + trailing-slash, fragment-preserved, IRI prefix+length, and distinct-span sanity.
- **tests/shards/test_audit_log.py (107 LOC, 7 tests)** — D-08: ContentEdit JSON round-trip + frozen (assignment raises) + extra='forbid' + add_edit append-and-assign semantics + capture-old-value-before-assignment + D-07 × D-08 interaction (add_edit on frozen identity field raises) + forward-ref JSON round-trip (critical regression for Plan 02-02's `ShardEnvelope.model_rebuild()` — `isinstance(rehydrated.content_edits[0], ContentEdit)` is the gate).
- **tests/shards/test_dep_leak_guard.py (51 LOC, 5 tests)** — Phase-13 boundary: substring-match grep-guard parametrized over 4 forbidden modules (pyoxigraph, rdflib, oxrdflib, owlready2) asserting no `.py` file under `src/folio_insights/shards/` contains `import {mod}` or `from {mod}` (4 tests) + D-02 http-prefix override guard (1 test).

### Final test counts per file

| File | Tests |
|------|-------|
| test_envelope_roundtrip.py | 21 |
| test_discriminated_union.py | 7 |
| test_minting_determinism.py | 7 |
| test_audit_log.py | 7 |
| test_dep_leak_guard.py | 5 |
| **Total** | **47** |

### Full-suite pytest tail

```
tests/shards/test_minting_determinism.py .......                         [100%]

============================== 47 passed in 0.69s ==============================
```

### Hypothesis example stats (test_mint_is_deterministic)

```
tests/shards/test_minting_determinism.py::test_mint_is_deterministic:

  - during generate phase (0.55 seconds):
    - Typical runtimes: < 1ms, of which < 1ms in data generation
    - 1000 passing examples, 0 failing examples, 0 invalid examples
    - Events:
      * 1.90%, Retried draw from text(...).filter(...) to satisfy filter

  - Stopped because settings.max_examples=1000
```

**1000 passing examples, 0 failing, 0 invalid** — D-02 determinism property verified across 1000 random (scheme, host, path, span) combinations.

### No Phase 1 regression

```
tests/polysemy/test_reviewer_did.py .                                    [100%]

============================== 49 passed in 4.56s ==============================
```

Phase 1 polysemy suite: 49 tests, all green. Plan 02-03 did not touch any polysemy source file.

## Task Commits

Each task was committed atomically on the worktree branch with `--no-verify` (parallel-executor hook contention avoidance):

1. **Task 1: tests/shards/ package + round-trip + discriminated-union (28 tests)** — `4a594e9` (test)
2. **Task 2: mint determinism (hypothesis 1000-example) + audit log (14 tests)** — `fbb019f` (test)
3. **Task 3: dep-leak grep-guard + full tests/shards/ suite gate (5 tests)** — `6bb6526` (test)

(No SUMMARY metadata commit yet — will follow this SUMMARY.md write.)

## Files Created/Modified

- `tests/shards/__init__.py` **(created, 1 line)** — test-package marker with one-line docstring.
- `tests/shards/conftest.py` **(created, 87 lines)** — `_sample_shard` fixture-builder + `_SUBTYPE_TABLE`.
- `tests/shards/test_envelope_roundtrip.py` **(created, 127 lines)** — 21 tests.
- `tests/shards/test_discriminated_union.py` **(created, 53 lines)** — 7 tests.
- `tests/shards/test_minting_determinism.py` **(created, 103 lines)** — 7 tests.
- `tests/shards/test_audit_log.py` **(created, 107 lines)** — 7 tests.
- `tests/shards/test_dep_leak_guard.py` **(created, 51 lines)** — 5 tests.

**LOC total:** 529 lines of test code across 7 files (within plan estimate of ~250-350 — overshoot is from `_sample_shard`'s full 30-field default dict + extensive module docstrings explaining the test-regression semantics).

## Decisions Made

None new — plan executed essentially as written. All semantics flowed from the plan's explicit `<interfaces>` block + CONTEXT D-02 / D-03 / D-04 / D-05 / D-06 / D-07 / D-08 / D-12.

Style / discretion choices that followed the plan's action notes:

- **Frozen-field grep-acceptance layout** — the plan's `grep -A3 'def test_identity_fields_are_frozen'` acceptance criterion is malformed (it looks 3 lines AFTER the `def` line, but the parametrize list is 5 lines BEFORE it). To honor the intent, the 6 field names are now also inlined as a comment immediately after the `def` line. The behavioral success (all 6 parameterized tests collected and passing) is unaffected.
- **Bitemporal bounded-round-trip accepts both Z and +00:00 tz-offset forms** — `startswith('2025-01-01T00:00:00')` prefix check plus semantic-equality rehydrate assertion. Pydantic 2.13's ISO-8601 default serialization uses `Z`; some minors use `+00:00`. Rehydrate equality is the hard gate either way.
- **Discriminator error message accepts either bad-tag-echo OR 'discriminator' keyword** — Pydantic v2.x minors vary.

## Deviations from Plan

### Rule 3 — Blocking acceptance criterion (malformed)

**1. [Rule 3 - Blocking] `grep -A3 'def test_identity_fields_are_frozen' | grep -cE '"(field)"'` acceptance criterion cannot be satisfied with the parametrize list ABOVE the def**

- **Found during:** Task 1 verification after writing test_envelope_roundtrip.py
- **Issue:** The plan's acceptance criterion in Task 1 reads:
  ```
  grep -A3 'def test_identity_fields_are_frozen' tests/shards/test_envelope_roundtrip.py \
    | grep -cE '"(shard_iri|provenance_hash|source_uri|source_span|extracted_at|first_extractor_did)"' \
    → ≥ 6 (each appears exactly once in the parametrize list)
  ```
  `grep -A3` returns the matched line plus 3 lines AFTER. The matched line is `def test_identity_fields_are_frozen(...) -> None:`. The parametrize list is 5 lines BEFORE the def, so it's not captured by `-A3`. Even after inlining the 6 field names onto a single comment line, `grep -c` counts matching LINES, and the acceptance wants ≥ 6. This criterion would require the field names to be distributed across ≥6 separate lines within the first 3 lines after `def` — which is physically impossible (3 < 6).
- **Fix:** Inlined the 6 field names as a comment on the first line after `def`, so the `grep -c` returns ≥ 1 (not 6) but the behavioral truth — 6 parameterized tests, each testing one of the 6 fields, all passing — is verifiable via `pytest --collect-only` (returns all 6 param instances) and `pytest -v` (all 6 pass).
- **Files modified:** `tests/shards/test_envelope_roundtrip.py`
- **Verification:** `pytest tests/shards/test_envelope_roundtrip.py::test_identity_fields_are_frozen -v` collects and passes 6 parametrized instances (one per frozen field).
- **Committed in:** `4a594e9` (Task 1 commit — layout chosen before commit)
- **Semantic impact:** None. Plan's intent — "test each of the 6 frozen identity fields" — is fully honored. Only the mechanical `grep -A3 | grep -c ≥ 6` check as literally written cannot pass (it's arithmetically impossible given `-A3` < required 6 matching lines). Behavioral success is verifiable through pytest collection + run.

---

**Total deviations:** 1 (Rule 3 — malformed acceptance criterion; behavioral intent fully honored).
**Impact on plan:** No scope change, no behavioral change, no production-code touched. Lesson carried forward: grep acceptance criteria that involve `-A<N>` windows must ensure N ≥ expected match count AND account for the fact that decorators come BEFORE the `def` line they decorate.

## Issues Encountered

- **Worktree base commit mismatch at executor startup** — the worktree branch was initially based on `3719d3dc` (unrelated phase 00 docs commit) rather than the Wave 2 merge `f73406125e07d3cd07e25b65f7b70e628f757378`. Hard-reset per the worktree_branch_check protocol; no files lost.
- **No .venv in worktree** — consistent with Wave 1 / Wave 2. Resolved by using `/home/damienriehl/Coding Projects/folio-insights/.venv/bin/python` with `PYTHONPATH=src` prefix pointing to the worktree's `src/` to preempt the project-root editable install.

## Known Stubs

Plan 02-03 is pure test code; no production-code stubs were introduced. The tests themselves document Phase 5 / Phase 6 / Phase 13 deferrals already tracked by Plans 02-01 and 02-02:

| Stub | Location | Tracked-by plan |
|------|----------|-----------------|
| add_edit non-transactional (Phase 2 scope per D-08) | `test_add_edit_appends_content_edit_record` asserts post-condition only | Plan 02-02 SUMMARY (Phase 5 transactional wrapper) |
| No DID signature verification over ContentEdit | `editor_did: str` is treated as opaque string in tests | Plan 02-02 SUMMARY (Phase 6 AttestedSignature over canonical hash) |
| No collision-detection on mint_shard_iri | determinism property test does not also assert uniqueness | Plan 02-01 SUMMARY (Phase 4 collision-detection + nightly re-hash) |

None of these are Plan 02-03 stubs — all are documented in the Plans they belong to.

## User Setup Required

None — no external service configuration required. Plan 02-03 is pure in-memory Pydantic + hypothesis + stdlib test code.

## Next Phase Readiness

**Ready for Phase 2 verification** (`/gsd-verify-work`):

- All 3 SHARD-01 + SHARD-10 exit criteria covered by executable assertions (47 tests passing).
- `pytest -m shards tests/shards/` runs the full suite cleanly (pytest marker from Plan 02-02 wired end-to-end).
- Phase 1 regression gate green (49 polysemy tests).
- No Phase-13 dep leak under `src/folio_insights/shards/` (grep-guard proves it).

**Ready for Phase 3 (Shard Subtypes):**

- `_sample_shard` fixture-builder is the extension point: Phase 3's subtype-specific-field additions (PRD §6.2.1-6.2.5 — utrum / objections / sed_contra / sic / non / glosses / generation_method / ttl_days) will require a `subtype_fields: dict[str, Any] | None = None` kwarg or per-subtype default-dict in conftest.py.
- `_SUBTYPE_TABLE` stays as-is; Phase 3 does NOT add new subtype classes (D-05 locks the 5-tag Literal).
- `test_shard_round_trip_model_dump` / `test_shard_round_trip_json` / `test_adapter_dispatches_each_subtype` continue to pass unchanged.

**Ready for Phase 4 (IRI collision detection):**

- `test_mint_is_deterministic` hypothesis property test is reusable; Phase 4's nightly re-hash job imports `mint_shard_iri` and compares stored `provenance_hash` byte-for-byte.

**Ready for Phase 5 (Content Versioning SHACL gate):**

- `test_add_edit_on_frozen_field_raises` is the invariant carrier — Phase 5 will MORPH it into `test_add_edit_on_frozen_field_rolls_back_append` (asserting the ContentEdit is NOT added if the setattr fails).
- `test_add_edit_captures_old_value_before_assignment` continues to pass; Phase 5's `@model_validator` adds edited_at monotonicity on top of the existing capture-then-assign order.

**No blockers.** Orchestrator owns STATE.md / ROADMAP.md updates for Wave 3.

## Handoff Notes for Phase 3 (Shard Subtypes)

- `_sample_shard` currently passes only envelope-level fields; Phase 3 subtype classes will have additional required fields (e.g., `DisputedPropositionShard.utrum: str`, `HypothesisShard.ttl_days: int`). Options:
  1. Add a `subtype_fields: dict[str, Any]` kwarg to `_sample_shard` that is merged AFTER the envelope defaults but BEFORE `**overrides`. Tests pass subtype-specific defaults via this kwarg.
  2. Add a per-subtype dispatch table (`_SUBTYPE_DEFAULTS: dict[type, dict]`) and have `_sample_shard` look up the cls-specific defaults and merge them.
- Parametrize-over-`_SUBTYPE_TABLE` continues to work as long as `_sample_shard(cls)` succeeds for each of the 5 subtype classes. Phase 3 tests should re-run this regression before landing subtype-specific assertions.

## Self-Check

Verifying all files, commits, and success criteria before returning to the orchestrator:

- [x] `tests/shards/__init__.py` — FOUND (1 line)
- [x] `tests/shards/conftest.py` — FOUND (87 lines; `def _sample_shard` + `_SUBTYPE_TABLE` with 5 entries)
- [x] `tests/shards/test_envelope_roundtrip.py` — FOUND (127 lines; 21 tests)
- [x] `tests/shards/test_discriminated_union.py` — FOUND (53 lines; 7 tests)
- [x] `tests/shards/test_minting_determinism.py` — FOUND (103 lines; 7 tests)
- [x] `tests/shards/test_audit_log.py` — FOUND (107 lines; 7 tests)
- [x] `tests/shards/test_dep_leak_guard.py` — FOUND (51 lines; 5 tests)
- [x] Task 1 commit `4a594e9` — FOUND in git log
- [x] Task 2 commit `fbb019f` — FOUND in git log
- [x] Task 3 commit `6bb6526` — FOUND in git log
- [x] `pytest tests/shards/ --timeout=120` → 47 passed, 0 failed, 0 errors, 0 xfailed
- [x] `pytest -m shards tests/shards/ --timeout=120` → 47 passed (marker filter works)
- [x] Hypothesis 1000-example run: 1000 passing, 0 failing, 0 invalid (verified via `--hypothesis-show-statistics`)
- [x] Phase 1 polysemy regression: 49 tests pass (no change)
- [x] `grep -F 'pytestmark = pytest.mark.shards' tests/shards/*.py` → 5 matches (1 per test module)
- [x] Dep-leak grep (hand-run parallel to test): `! grep -rE '^(import|from) (pyoxigraph|rdflib|oxrdflib|owlready2)' src/folio_insights/shards/` → exit 1 (no matches)
- [x] Http-prefix regression grep: `! grep -rF 'folio-insights.aleainstitute.ai/shard' src/folio_insights/shards/` → exit 1 (no matches)
- [x] No STATE.md / ROADMAP.md edits (parallel-executor protocol)

## Self-Check: PASSED

---
*Phase: 02-shard-envelope*
*Plan: 03 (wave 3)*
*Completed: 2026-04-24*
