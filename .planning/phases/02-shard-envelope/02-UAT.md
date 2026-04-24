---
status: complete
phase: 02-shard-envelope
source:
  - 02-01-SUMMARY.md
  - 02-02-SUMMARY.md
  - 02-03-SUMMARY.md
  - 02-VERIFICATION.md
started: 2026-04-24T21:50:51Z
updated: 2026-04-24T21:50:51Z
---

## Current Test

[testing complete]

## Tests

### 1. Import sanity — all 13 public symbols
expected: |
  `from folio_insights.shards import (add_edit, AttestedSignature, ConflictingAuthoritiesShard, ContentEdit, DisputedPropositionShard, GlossShard, HypothesisShard, mint_shard_iri, Shard, ShardEnvelope, ShardType, SimpleAssertionShard, Triple)` — no ImportError.
result: pass
observed: All 13 symbols imported successfully.

### 2. ShardEnvelope instantiation + round-trip (model_dump + JSON)
expected: |
  Build a `SimpleAssertionShard` with all 22 required fields + a minted IRI. `Shard(**shard.model_dump()) == shard` holds. `SimpleAssertionShard.model_validate_json(shard.model_dump_json()) == shard` holds.
result: pass
observed: Both round-trips (model_dump and model_dump_json) produce equal objects.

### 3. Minting determinism (smoke)
expected: |
  `mint_shard_iri("http://example.org/doc", "hello world")` called twice returns identical (iri, hash). IRI prefix is `urn:folio:shard/`. Hash is 64 hex chars. IRI suffix is 16 hex chars.
result: pass
observed: `urn:folio:shard/2c264b471f1f74bf`, hash prefix `2c264b471f1f74bf`, lengths correct.

### 4. Discriminated-union dispatch via TypeAdapter (all 5 subtypes)
expected: |
  `pydantic.TypeAdapter(Shard).validate_python({"shard_type": X, ...})` returns the correct subtype class for X ∈ {simple_assertion, disputed_proposition, conflicting_authorities, gloss, hypothesis}.
result: pass
observed: All 5 tags dispatched to their expected subtype classes.

### 5. Invalid shard_type raises ValidationError
expected: Invalid tag ("not_a_real_tag") via TypeAdapter raises `pydantic.ValidationError` with a useful message (mentions the bad tag or "discriminator").
result: pass
observed: ValidationError raised; message contains tag or discriminator reference.

### 6. Frozen identity fields (6 fields)
expected: |
  Assignment to any of shard_iri, provenance_hash, source_uri, source_span, extracted_at, first_extractor_did raises `pydantic.ValidationError` with `errors()[0]['type'] == 'frozen_field'` (Pydantic v2 behavior).
result: pass
observed: All 6 fields raise ValidationError(type='frozen_field') on assignment.

### 7. ContentEdit append via add_edit + frozen-field guard
expected: |
  (a) `add_edit(shard, "contested", True, "did:key:...")` appends a ContentEdit with correct field_name/old_value/new_value/edited_at (tz-aware UTC)/editor_did. Underlying field is mutated.
  (b) `add_edit(shard, "shard_iri", "fake", "did:key:...")` on a frozen field raises ValidationError(type='frozen_field').
result: pass
observed: |
  Append worked; `contested` mutated to True; edit.editor_did recorded verbatim; edit.edited_at tz-aware. Attempting to add_edit on shard_iri correctly raised ValidationError.

### 8. Bitemporal nullability + tz-aware UTC defaults
expected: |
  `valid_time_start`, `valid_time_end` default to None (nullable unbounded). `transaction_time` defaults to tz-aware `datetime.now(UTC)`. Bounded intervals round-trip through model_dump/model_validate unchanged.
result: pass
observed: |
  Defaults: start=None, end=None, transaction_time tz-aware. Bounded shard with 2023-01-01→2024-12-31 round-trips with datetimes preserved.

### 9. Full shards test suite
expected: `pytest tests/shards/ -q` exits 0 with 47 passed.
result: pass
observed: 47 passed in 0.66s.

### 10. Phase 1 regression gate (combined suite)
expected: `pytest tests/shards/ tests/polysemy/ -q` exits 0 with 96 passed.
result: pass
observed: 96 passed in 5.56s — no Phase 1 regression.

### 11. Pytest `shards` marker filter
expected: `pytest -m shards tests/shards/ -q` exits 0 with 47 passed (marker registered in pyproject.toml).
result: pass
observed: 47 passed in 0.66s with marker filter active.

### 12. Hypothesis 1000-example property test (minting determinism)
expected: |
  `pytest tests/shards/test_minting_determinism.py::test_mint_is_deterministic --hypothesis-show-statistics` — 1000 passing examples, 0 failing.
result: pass
observed: |
  1000 passing examples, 0 failing, 1 invalid (invalid = filter-retry; does NOT count against the 1000 passing). Typical runtime < 1ms per example.

## Summary

total: 12
passed: 12
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none — all tests pass]

## Human-Needed Gates (from 02-VERIFICATION.md)

These are intentional interpretation/design notes from the verifier. Non-blocking — surfaced here for reviewer awareness, not as UAT failures:

1. **"15 fields" PRD §6.1 interpretation** — The PRD groups ~30 atomic fields into ~15 conceptual slot-groups (e.g., slot 11 = `depends_on_axioms` + `depends_on_definitions` + `depends_on_precedents` + `depends_on_shards` counted as one "explicit dependencies" slot). The implementation follows the plan's explicit `<interfaces>` template, which treats slot-groups as the "15 fields." Reviewer may want to confirm this reading is acceptable or request a stricter atomic-count interpretation.

2. **Subtype stubs (5 classes with no subtype-specific fields)** — Intentional per CONTEXT D-05: Phase 2 ships the discriminator wiring; Phase 3 (Shard Subtypes §6.2) adds each subtype's specific fields (utrum, objections, generation_method, ttl_days, etc.). Not a gap.

3. **`AttestedSignature` permissive placeholder** — Phase 2 ships `AttestedSignature` with `ConfigDict(extra="allow")` as a DID-signature stub. Phase 6 replaces the model entirely. Threat T-02-01-04 (accepted disposition in 02-01-PLAN.md) explicitly notes that adversarial field addition is possible in Phase 2 but moot because there is no untrusted ingest path yet — Phase 6 hardens with real ed25519 verification.
