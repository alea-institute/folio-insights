---
phase: 03-shard-subtypes
verified: 2026-04-25T00:00:00Z
status: passed
score: 12/12 must-haves verified
overrides_applied: 0
re_verification: false
---

# Phase 03: Shard Subtypes Verification Report

**Phase Goal:** Ship the 5 subtypes as discriminated-union variants of the envelope with schema + example round-trip coverage.
**Verified:** 2026-04-25
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | PRD A.1 (SimpleAssertion) round-trips via TypeAdapter(Shard) | VERIFIED | `TypeAdapter(Shard).validate_python(payload).model_dump(mode='json') == payload` confirmed programmatically; `test_a1_fixture_round_trips` passes |
| 2 | PRD A.2 (ConflictingAuthorities with all 8 reconciliation strategies enumerated) round-trips | VERIFIED | fixture contains `"reconciliation_strategy": "jurisdictional_scoping"`; `test_a2_fixture_round_trips` passes; `test_each_reconciliation_strategy_constructs` covers all 8 via parametrize |
| 3 | PRD A.3 (DisputedProposition) round-trips | VERIFIED | `TypeAdapter(Shard).validate_python(payload).model_dump(mode='json') == payload` confirmed programmatically; `test_a3_fixture_round_trips` passes |
| 4 | GlossShard parses and validates | VERIFIED | `test_each_gloss_kind_constructs` covers all 5 GlossKind values; IRI format, self-gloss rejection, and empty text rejection all tested; 23 tests pass |
| 5 | HypothesisShard parses and validates | VERIFIED | `test_each_generation_method_constructs` covers all 3 GenerationMethod values; ttl_days + citation_required default tests all pass; 18 tests pass |
| 6 | HypothesisShard ships `citation_required: bool = True` | VERIFIED | `HypothesisShard.model_fields['citation_required'].default is True` confirmed; `test_citation_required_defaults_true` passes; `test_citation_required_true_with_empty_deps_constructs` documents Phase-7-deferred gate |
| 7 | DisputedPropositionShard rejects epistemic_status outside {hypothesis, authority_only, contested, aporetic} | VERIFIED | `_DISPUTED_EPISTEMIC_STATUS_SUBSET = frozenset({"hypothesis", "authority_only", "contested", "aporetic"})` in subtypes.py; `test_out_of_subset_status_raises` parametrizes all 4 outside values |
| 8 | DisputedPropositionShard, ConflictingAuthoritiesShard, GlossShard, HypothesisShard validate with PRD §6.2 fields | VERIFIED | All 4 subtypes + nested models fully implemented; all 5 subtypes construct via `_sample_shard(cls)` without ValidationError |
| 9 | ConflictingAuthoritiesShard rejects a 9th reconciliation_strategy value | VERIFIED | `test_ninth_reconciliation_strategy_rejected` passes ("custom" rejected by Literal lock) |
| 10 | GlossShard rejects malformed IRI, self-glossing, empty gloss_text | VERIFIED | 7 invalid IRI shapes tested; self-glossing test passes; 3 blank gloss_text cases tested |
| 11 | subtypes.py imports zero of {pyoxigraph, rdflib, oxrdflib, owlready2} | VERIFIED | `grep -E 'pyoxigraph|...` returns empty; `test_dep_leak_guard.py` passes (1 test green) |
| 12 | `_sample_shard(cls)` constructs each of the 5 subtypes without TypeError or ValidationError | VERIFIED | All 5 subtypes confirmed via `[_sample_shard(cls) for _, cls in _SUBTYPE_TABLE]` |

**Score:** 12/12 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/folio_insights/shards/subtypes.py` | 5 subtype classes + 3 nested models + 3 Literal aliases + 4 validators + Shard union | VERIFIED | 268 LOC; all 12 public names in `__all__`; 4 `@model_validator(mode="after")` blocks confirmed |
| `src/folio_insights/shards/__init__.py` | 19 public names in `__all__` | VERIFIED | Exact 19-entry match confirmed programmatically; all 6 new names (AuthorityPosition, Objection, Reply, ReconciliationStrategy, GlossKind, GenerationMethod) present |
| `tests/shards/conftest.py` | `_SUBTYPE_DEFAULTS` lookup for 4 non-empty subtypes | VERIFIED | `_SUBTYPE_DEFAULTS` dict present; merge order `envelope → subtype-specific → caller overrides` confirmed |
| `tests/shards/fixtures/example_a1_simple_assertion.json` | Verbatim PRD §6.2.1 A.1 fixture | VERIFIED | `shard_type: "simple_assertion"`, all 22 required envelope fields, round-trips cleanly |
| `tests/shards/fixtures/example_a2_conflicting_authorities.json` | Verbatim PRD §6.2.3 A.2 fixture | VERIFIED | `shard_type: "conflicting_authorities"`, sic/non/reconciliation_strategy/reconciliation_note populated, round-trips cleanly |
| `tests/shards/fixtures/example_a3_disputed_proposition.json` | Verbatim PRD §6.2.2 A.3 fixture | VERIFIED | `shard_type: "disputed_proposition"`, utrum/objections/sed_contra/respondeo/replies all present, `epistemic_status: "contested"` (in D-03 4-subset), round-trips cleanly |
| `tests/shards/test_subtype_simple_assertion.py` | A.1 round-trip + extra=forbid regression | VERIFIED | 3 tests; `test_a1_fixture_round_trips` present |
| `tests/shards/test_subtype_disputed_proposition.py` | A.3 round-trip + 4-subset + empty-objections + out-of-range reply | VERIFIED | 13 tests; `_DISPUTED_EPISTEMIC_STATUS` list present; no `"attested"` in test data |
| `tests/shards/test_subtype_conflicting_authorities.py` | A.2 round-trip + 8-strategy parametrize + 9th rejected + sic/non non-empty + blank note | VERIFIED | 20 tests; `test_each_reconciliation_strategy_constructs` and `test_ninth_reconciliation_strategy_rejected` present |
| `tests/shards/test_subtype_gloss.py` | 5 GlossKind values + IRI edges + self-glossing + empty text | VERIFIED | 23 tests; `test_each_gloss_kind_constructs` and `test_self_glossing_rejected` present |
| `tests/shards/test_subtype_hypothesis.py` | 3 GenerationMethod values + ttl_days boundaries + citation_required default + Phase-7-deferred no-gate | VERIFIED | 18 tests; `test_citation_required_defaults_true` and `test_citation_required_true_with_empty_deps_constructs` present |
| `tests/shards/test_subtype_properties.py` | 5 property tests with D-09 budget (100+300+200+200+200=1000) | VERIFIED | 5 @settings decorators; exactly 5 `@settings(max_examples=...)` entries; `deadline=None` on all; total runtime 0.63s (well under 2s target) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/folio_insights/shards/__init__.py` | `src/folio_insights/shards/subtypes.py` | `from folio_insights.shards.subtypes import (...)` | WIRED | Import block confirmed; all 12 subtypes names imported |
| `tests/shards/conftest.py` | `src/folio_insights/shards/subtypes.py` | `_SUBTYPE_DEFAULTS` table + `defaults.update(_SUBTYPE_DEFAULTS.get(cls, {}))` | WIRED | Both pattern and merge call confirmed in conftest.py |
| `tests/shards/test_subtype_simple_assertion.py` | `tests/shards/fixtures/example_a1_simple_assertion.json` | `Path(__file__).parent / 'fixtures' / 'example_a1_simple_assertion.json'` | WIRED | Pattern `example_a1_simple_assertion.json` confirmed in test file |
| `tests/shards/test_subtype_disputed_proposition.py` | `tests/shards/conftest.py::_sample_shard` | `_sample_shard(DisputedPropositionShard, **overrides)` | WIRED | Usage pattern confirmed |
| `tests/shards/test_subtype_conflicting_authorities.py` | `tests/shards/conftest.py::_sample_shard` | `_sample_shard(ConflictingAuthoritiesShard, **overrides)` | WIRED | Usage pattern confirmed |

### Data-Flow Trace (Level 4)

Not applicable — Phase 03 is pure Pydantic schema + test code. No components render dynamic data from a data store. All artifacts are validators, type definitions, and test fixtures.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 3 PRD fixtures round-trip via TypeAdapter | `TypeAdapter(Shard).validate_python(payload).model_dump(mode='json') == payload` for A.1/A.2/A.3 | All 3 asserted equal | PASS |
| All 5 subtypes construct via _sample_shard | `[_sample_shard(cls) for _, cls in _SUBTYPE_TABLE]` | OK — no ValidationError or TypeError | PASS |
| HypothesisShard.citation_required defaults True | `HypothesisShard.model_fields['citation_required'].default is True` | True | PASS |
| HypothesisShard.ttl_days defaults 90 | `HypothesisShard.model_fields['ttl_days'].default == 90` | 90 | PASS |
| Full test suite (129 tests) | `uv run python -m pytest tests/shards -q` | 129 passed in 1.23s | PASS |
| Property test runtime | `pytest tests/shards/test_subtype_properties.py --durations=10 -q` | 0.63s total (D-09 target: 2s) | PASS |

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SHARD-02 | 03-01, 03-02 | `SimpleAssertionShard` subtype; example A.1 round-trips | SATISFIED | `test_a1_fixture_round_trips` passes; 3 tests cover SimpleAssertion |
| SHARD-03 | 03-01, 03-02 | `DisputedPropositionShard` with dispute_state subset; A.3 round-trips | SATISFIED | D-03 substitution: `"authority_only"` replaces PRD's `"attested"` (planner-resolved 2026-04-25; documented in CONTEXT D-03); validator enforces 4-subset; 13 tests pass |
| SHARD-04 | 03-01, 03-02 | `ConflictingAuthoritiesShard` with 8 reconciliation strategies; A.2 round-trips | SATISFIED | All 8 strategies in `ReconciliationStrategy` Literal; parametrize tests cover each; 9th "custom" rejected; 20 tests pass |
| SHARD-05 | 03-01, 03-02 | `GlossShard` subtype; schema + validator pass | SATISFIED | 5 GlossKind values, IRI format validation, self-gloss rejection, empty-text rejection; 23 tests pass |
| SHARD-06 | 03-01, 03-02 | `HypothesisShard` with `citation_required: bool = True` | SATISFIED | Field confirmed present with default=True; Phase-7-deferred gate explicitly tested as non-blocking at construction time; 18 tests pass |

All 5 requirement IDs declared in PLAN frontmatter accounted for. No REQUIREMENTS.md entries for Phase 3 remain orphaned — SHARD-02 through SHARD-06 are all covered by this phase.

**SHARD-03 note:** REQUIREMENTS.md text says `dispute_state ∈ {hypothesis, attested, contested, aporetic}`. CONTEXT D-03 (planner-resolved 2026-04-25) records that the envelope ships no `"attested"` Literal value; `"authority_only"` substitutes semantically. This is a deliberate, documented substitution — not a gap.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tests/shards/test_subtype_properties.py` | 145-148 | `if iri == shard.shard_iri: return` instead of `hypothesis.assume(...)` | Info | Collision probability ~2^-64; no correctness impact. Noted in REVIEW.md WR-02. |
| `tests/shards/conftest.py` | 113 | `mint_shard_iri` called on every `_sample_shard` invocation (pure function, deterministic, cached result discarded) | Info | No correctness impact; minor per-call overhead across 1000 hypothesis examples. Noted in REVIEW.md IN-01. |

No blocker or warning-level anti-patterns found in source files. The REVIEW.md documents 2 warnings (WR-01: nested model string fields lack min_length; WR-02: bare return instead of assume) and 5 info items — none block phase goal achievement. WR-01 is a hardening concern deferred by design (format-only validation; the discriminated union does not depend on non-empty nested strings for type safety).

### Human Verification Required

None. All exit criteria are programmatically verifiable:

1. A.1/A.2/A.3 round-trips — verified by `TypeAdapter(Shard).validate_python(payload).model_dump(mode='json') == payload` assertion (all 3 passed)
2. Gloss + Hypothesis parse and validate — verified by 23 + 18 passing unit tests covering positive construction and invariant rejection
3. `HypothesisShard` ships `citation_required: bool = True` — verified by `HypothesisShard.model_fields` introspection and `test_citation_required_defaults_true`

---

## Gaps Summary

No gaps. All 12 must-haves verified. All 5 requirement IDs satisfied. Full test suite (129 tests) passes in 1.23s. The D-03 `"authority_only"` substitution for the PRD's `"attested"` is a pre-resolved planner decision documented in 03-CONTEXT.md and confirmed as correct behavior in the verification instructions — it is not flagged as a gap.

---

_Verified: 2026-04-25_
_Verifier: Claude (gsd-verifier)_
