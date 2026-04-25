---
phase: 03-shard-subtypes
fixed_at: 2026-04-25T00:00:00Z
review_path: .planning/phases/03-shard-subtypes/03-REVIEW.md
iteration: 1
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-04-25
**Source review:** `.planning/phases/03-shard-subtypes/03-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 2 (Critical=0, Warning=2; Info=5 out of scope)
- Fixed: 2
- Skipped: 0
- Test suite: 129 passed in 1.23s (no regressions)

## Fixed Issues

### WR-01: Nested models lack non-empty/non-blank validation on string IRI/text fields

**Files modified:** `src/folio_insights/shards/subtypes.py`
**Commit:** d78a219
**Applied fix:** Added `Field(min_length=1)` to:
- `Objection.cites`, `Objection.argues`
- `Reply.argument`
- `AuthorityPosition.authority_iri`, `AuthorityPosition.position`, `AuthorityPosition.jurisdiction`

Updated docstrings to reference REVIEW WR-01 rationale and noted that
Pydantic `min_length` does not strip whitespace (the obvious empty-string
case is now caught; deeper whitespace-only validation is intentionally
deferred to downstream IRI parsers consistent with the format-only posture).
All existing tests and fixtures already use non-empty values, so no test
changes were required. 129/129 tests pass.

### WR-02: Hypothesis property test silently skips self-gloss collisions instead of using `assume()`

**Files modified:** `tests/shards/test_subtype_properties.py`
**Commit:** a4f6083
**Applied fix:** Imported `assume` from `hypothesis` and replaced the bare
`if iri == shard.shard_iri: return` with `assume(iri != shard.shard_iri)`
inside `test_gloss_constructs_round_trips`. Hypothesis now properly
discards self-gloss collision examples and generates replacements, so the
200-example budget reflects real round-trip coverage rather than silent
passes. 129/129 tests pass.

---

_Fixed: 2026-04-25_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
