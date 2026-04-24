---
phase: 02-shard-envelope
verified: 2026-04-24T21:30:00Z
status: passed
score: 8/8 must-haves verified
overrides_applied: 0
---

# Phase 2: Shard Envelope Verification Report

**Phase Goal:** Ship the 15-field Pydantic `Shard` envelope as the v2.0 core data model with round-trip and discriminated-union guarantees.
**Verified:** 2026-04-24T21:30:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| T1 | ShardEnvelope has 15 fields per PRD §6.1 (plus identity, bitemporal, supersession, contest groups) | VERIFIED | `envelope.py`: 15 numbered PRD §6.1 fields declared in grouped comments (field slots 1-15); 6 identity fields + bitemporal triplet + supersession pair + contest state also present. Field count defensible — see Human Verification note. |
| T2 | Round-trip passes for all 5 subtypes: `SubtypeCls(**shard.model_dump()) == shard` | VERIFIED | `test_envelope_roundtrip.py::test_shard_round_trip_model_dump` (5 parametrized) + `test_shard_round_trip_json` (5 parametrized) — 10 tests, all green. Manually re-verified at verification time. |
| T3 | Invalid discriminator raises `pydantic.ValidationError` with useful message | VERIFIED | `test_discriminated_union.py::test_invalid_shard_type_raises_validation_error` — green. Manual verification confirmed error message contains `discriminator`/literal-error language. |
| T4 | Bitemporal fields round-trip: null/bounded + tz-aware UTC `transaction_time` | VERIFIED | `test_envelope_roundtrip.py` bitemporal tests (4 tests: null unbounded, bounded start, bounded end, transaction_time default). ROADMAP EC-3 manually verified — `valid_time_start == start` and `valid_time_end is None` after JSON round-trip. |
| T5 | `mint_shard_iri` is deterministic across 1000 hypothesis-generated inputs | VERIFIED | `test_minting_determinism.py::test_mint_is_deterministic` — `@settings(max_examples=1000, deadline=None)` run, **1000 passing, 0 failing, 0 invalid**. |
| T6 | 6 identity fields are frozen; assignment raises `ValidationError(type="frozen_field")` | VERIFIED | `test_envelope_roundtrip.py::test_identity_fields_are_frozen` (6 parametrized). Runtime inspection confirmed: `ShardEnvelope.model_fields` shows exactly the 6 fields (`shard_iri`, `provenance_hash`, `source_uri`, `source_span`, `extracted_at`, `first_extractor_did`) with `frozen=True`. `grep -cE 'frozen=True' envelope.py` → `6`. |
| T7 | Dep-leak guard passes — no pyoxigraph/rdflib/oxrdflib/owlready2 imports in `src/folio_insights/shards/` | VERIFIED | `test_dep_leak_guard.py` (4 parametrized + 1 http-prefix guard) — all 5 green. `grep -rE 'import (pyoxigraph\|rdflib\|oxrdflib\|owlready2)' src/folio_insights/shards/` → no matches. |
| T8 | `ContentEdit` is frozen; `add_edit` appends correctly | VERIFIED | `test_audit_log.py` (7 tests): ContentEdit JSON round-trip + frozen-assignment-raises + extra=forbid + add_edit append+assign + old-value-captured-before-assign + add_edit-on-frozen-raises + forward-ref JSON round-trip. All green. |

**Score:** 8/8 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/folio_insights/shards/__init__.py` | Package marker + 13-symbol public exports | VERIFIED | 33 lines; `__all__` = 13 symbols; imports from audit, envelope, minting, subtypes all wired. |
| `src/folio_insights/shards/envelope.py` | ShardEnvelope + ShardType + AttestedSignature + Triple | VERIFIED | 219 lines; `class ShardEnvelope` with `ConfigDict(extra="forbid")`, exactly 6 `Field(frozen=True)` declarations, bitemporal triplet, `content_edits: list["ContentEdit"]` forward-ref. |
| `src/folio_insights/shards/subtypes.py` | 5 subtype classes + Shard discriminated-union | VERIFIED | 56 lines; `class [5 subtypes](ShardEnvelope)` each pinning `shard_type: Literal["..."] = "..."`. `Shard = Annotated[Union[...], Field(discriminator="shard_type")]`. |
| `src/folio_insights/shards/minting.py` | `mint_shard_iri(source_uri, source_span) -> tuple[str, str]` + private helpers | VERIFIED | 69 lines; `def mint_shard_iri`, `def _normalize_uri`, `def _normalize_span`; `_IRI_PREFIX = "urn:folio:shard/"`, `_IRI_HEX_LEN = 16`. |
| `src/folio_insights/shards/audit.py` | `ContentEdit` frozen sub-model + `add_edit` + `ShardEnvelope.model_rebuild()` | VERIFIED | 98 lines; `model_config = ConfigDict(frozen=True, extra="forbid")` on ContentEdit; 5 fields; `ShardEnvelope.model_rebuild()` at module bottom (line 97). |
| `tests/shards/__init__.py` | Test package marker | VERIFIED | 1 line. |
| `tests/shards/conftest.py` | `_sample_shard` fixture-builder + `_SUBTYPE_TABLE` | VERIFIED | 87 lines; `def _sample_shard(cls, **overrides)` present; `_SUBTYPE_TABLE` with 5 (tag, cls) tuples. |
| `tests/shards/test_envelope_roundtrip.py` | Round-trip + bitemporal + frozen-field regression | VERIFIED | 127 lines; 21 tests; `def test_shard_round_trip_model_dump`, bitemporal tests, frozen-field parametrized tests. |
| `tests/shards/test_discriminated_union.py` | TypeAdapter dispatch + invalid-tag rejection | VERIFIED | 53 lines; 7 tests; `def test_invalid_shard_type_raises_validation_error` present. |
| `tests/shards/test_minting_determinism.py` | Hypothesis 1000-example property test + directed vectors | VERIFIED | 103 lines; 7 tests; `from hypothesis import given` present. |
| `tests/shards/test_audit_log.py` | ContentEdit frozen + add_edit append + frozen-field interaction | VERIFIED | 107 lines; 7 tests; `def test_add_edit_appends_content_edit_record` present. |
| `tests/shards/test_dep_leak_guard.py` | Grep-guard regression tests | VERIFIED | 51 lines; 5 tests; `def test_no_storage_import_in_phase2_shards` + `def test_no_http_iri_prefix_regression`. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `subtypes.py` | `envelope.py` | Each subtype inherits `ShardEnvelope` | VERIFIED | `grep -cE 'class [A-Z][A-Za-z]+Shard\(ShardEnvelope\)' subtypes.py` → 5 |
| `audit.py` | `envelope.py` | `ShardEnvelope.model_rebuild()` at module bottom | VERIFIED | Line 97 of audit.py; `ShardEnvelope.model_fields['content_edits'].annotation.__args__[0] is ContentEdit` confirmed True at runtime. |
| `__init__.py` | `audit.py` | `from folio_insights.shards.audit import ContentEdit, add_edit` | VERIFIED | Line 2 of `__init__.py`. |
| `minting.py` | SHA-256 D-02 recipe | `NFC(rfc3986(uri)) + "\n" + NFC(span).strip()` → `sha256` → `urn:folio:shard/<hex16>` | VERIFIED | Lines 60-65 of `minting.py`. RFC 3986 + NFC + LF separator + sha256 all present. |

---

### Data-Flow Trace (Level 4)

Not applicable — Phase 2 ships pure in-memory Pydantic models with no rendering layer. All data flows through Pydantic construction and are tested directly.

---

### Behavioral Spot-Checks

| Behavior | Result | Status |
|----------|--------|--------|
| ROADMAP EC-1: `Shard(**shard.model_dump()) == shard` for all subtypes | Round-trip equality confirmed for SimpleAssertionShard | PASS |
| ROADMAP EC-2: invalid discriminator raises ValidationError | ValidationError raised; message contains discriminator language | PASS |
| ROADMAP EC-3: bitemporal fields round-trip with tz-aware UTC | `valid_time_start`, `valid_time_end`, `transaction_time` all round-trip correctly | PASS |
| D-02: `mint_shard_iri` deterministic, 1000-example hypothesis run | 1000 passing, 0 failing, 0 invalid | PASS |
| D-07: exactly 6 frozen identity fields | Runtime inspection + grep both confirm 6 | PASS |
| Dep-leak: no storage-library imports in shards/ | grep returns no matches | PASS |

---

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|----------------|-------------|--------|----------|
| SHARD-01 | 02-01, 02-02, 02-03 | Shard envelope with discriminated-union dispatch | SATISFIED | ShardEnvelope + 5 subtypes + Shard alias + 47 passing tests covering round-trip, discriminator, frozen fields, audit chain |
| SHARD-10 | 02-01, 02-03 | Bitemporal fields (`valid_time_start`, `valid_time_end`, `transaction_time`) | SATISFIED | `valid_time_start`/`valid_time_end: datetime \| None = None`; `transaction_time` uses `Field(default_factory=lambda: datetime.now(UTC))`; 4 bitemporal tests in `test_envelope_roundtrip.py` green |

---

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `audit.py` L70-81 | `add_edit` append-then-setattr is non-transactional: ContentEdit appended before setattr; if setattr raises on a frozen field, a dangling audit record is left | Info | Intentional Phase 2 scope; explicitly documented in Plan 02-02 SUMMARY "Known Stubs" and phase threat register (T-02-02-02, accepted). Phase 5 hardens to transactional semantics. |
| `subtypes.py` | 5 subtype classes have no subtype-specific fields — pure stubs | Info | Intentional Phase 2 scope per D-06 and plan design. Phase 3 adds PRD §6.2 fields. No impact on Phase 2 exit criteria. |
| `envelope.py` L49-66 | `AttestedSignature` is a permissive placeholder (`ConfigDict(extra="allow")`) | Info | Intentional Phase 2 stub (D-08/threat T-02-01-04 accepted). Phase 6 DID substrate replaces the model. No impact on Phase 2 exit criteria. |

No blockers found. All flagged items are intentional, documented stubs tracked to specific future phases.

---

### Human Verification Required

#### 1. 15-field count interpretation

**Test:** Review the PRD §6.1 field groupings vs. the Phase 2 implementation to confirm the executor's "15 fields" interpretation is correct.

**Expected:** PRD §6.1 lists ~30 conceptual atomic fields grouped into ~15 PRD-numbered slots. The Phase 2 plan's `<interfaces>` block lists them as 15 numbered slot-groups (e.g., slot 11 covers `depends_on_axioms + depends_on_definitions + depends_on_precedents + depends_on_shards` as four list fields under one "Explicit dependencies" slot). The implementation follows this grouping faithfully. The count is defensible as "15 conceptual fields per PRD §6.1" — not 15 atomic Python attributes.

**Why human:** The PRD §6.1 field count is an interpretation judgment (slots vs. atomic attrs). The implementation aligns with the plan's explicit `<interfaces>` template which is the authoritative source for Phase 2. No programmatic gate can resolve the intent without reviewing the PRD directly. This is informational — it does not block Phase 2 closure.

---

### Gaps Summary

No gaps found. All 3 ROADMAP exit criteria are verified by executable tests:

1. `Shard(**shard.model_dump()) == shard` round-trips for every subtype — 10 parametrized tests green.
2. Discriminated-union rejects invalid subtype tag with useful ValidationError — 1 test green.
3. Bitemporal fields round-trip and serialize deterministically — 4 tests green.

All 8 observable truths verified. 47 tests pass. No regressions against Phase 1 (96 combined tests pass). Dep-leak boundary enforced mechanically. D-01 through D-12 locked decisions implemented as specified.

---

_Verified: 2026-04-24T21:30:00Z_
_Verifier: Claude (gsd-verifier)_
