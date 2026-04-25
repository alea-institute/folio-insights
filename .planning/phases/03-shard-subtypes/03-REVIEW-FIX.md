---
phase: 03-shard-subtypes
fixed_at: 2026-04-25T00:00:00Z
review_path: .planning/phases/03-shard-subtypes/03-REVIEW.md
iteration: 2
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-04-25
**Source review:** `.planning/phases/03-shard-subtypes/03-REVIEW.md`
**Iteration:** 2 (cumulative — includes prior iteration 1 warning fixes)

**Summary:**
- Findings in scope: 7 (Critical=0, Warning=2, Info=5; fix_scope=all)
- Fixed: 7 (2 from iteration 1, 5 new in iteration 2)
- Skipped: 0
- Test suite: 130 passed in 1.27s (was 129 before iteration 2;
  test_invalid_glosses_iri_rejected gained a boundary case under IN-02)

## Fixed Issues

### WR-01: Nested models lack non-empty/non-blank validation on string IRI/text fields

**Files modified:** `src/folio_insights/shards/subtypes.py`
**Commit:** `d78a219` (iteration 1)
**Applied fix:** Added `Field(min_length=1)` to:
- `Objection.cites`, `Objection.argues`
- `Reply.argument`
- `AuthorityPosition.authority_iri`, `AuthorityPosition.position`, `AuthorityPosition.jurisdiction`

Updated docstrings to reference REVIEW WR-01 rationale and noted that
Pydantic `min_length` does not strip whitespace (the obvious empty-string
case is now caught; deeper whitespace-only validation is intentionally
deferred to downstream IRI parsers consistent with the format-only posture).
All existing tests and fixtures already use non-empty values, so no test
changes were required.

### WR-02: Hypothesis property test silently skips self-gloss collisions instead of using `assume()`

**Files modified:** `tests/shards/test_subtype_properties.py`
**Commit:** `a4f6083` (iteration 1)
**Applied fix:** Imported `assume` from `hypothesis` and replaced the bare
`if iri == shard.shard_iri: return` with `assume(iri != shard.shard_iri)`
inside `test_gloss_constructs_round_trips`. Hypothesis now properly
discards self-gloss collision examples and generates replacements, so the
200-example budget reflects real round-trip coverage rather than silent
passes.

### IN-01: `_sample_shard` re-mints `mint_shard_iri` on every call

**Files modified:** `tests/shards/conftest.py`
**Commit:** `ac3122b`
**Applied fix:** Mints `(_FIXTURE_IRI, _FIXTURE_HASH)` once at module scope
via `mint_shard_iri("urn:x:fixture", "sample span")` and reuses the pair
across all `_sample_shard()` invocations. Eliminates ~1000 redundant
deterministic mint calls across the Hypothesis property-test budget. No
behavior change (mint is pure per Phase 02 D-02). Updated docstring to
point at the new module-scope cache.

### IN-02: `_GLOSS_HTTP_RE` is intentionally permissive — undocumented

**Files modified:** `src/folio_insights/shards/subtypes.py`,
`tests/shards/test_subtype_gloss.py`
**Commit:** `2df20be`
**Applied fix:** Added an explicit comment block above `_GLOSS_HTTP_RE`
enumerating the intentional permissiveness — documents that `http://x`,
`https://!@#`, etc. are accepted by design (RFC 3986 / referential integrity
are Phase 5 SHACL or Phase 13 storage scope) and that `https://` (no
trailing chars), `http:// space`, `ftp://...`, `shard/...` all reject.
Added `"https://"` to the `test_invalid_glosses_iri_rejected` parametrize
table to lock the `[^\s]+` ≥1-trailing-char boundary (test count: 129 -> 130).

### IN-03: Literal-mirror lists duplicated as hand-typed constants in tests

**Files modified:**
- `src/folio_insights/shards/subtypes.py`
- `src/folio_insights/shards/__init__.py`
- `tests/shards/test_subtype_disputed_proposition.py`
- `tests/shards/test_subtype_conflicting_authorities.py`
- `tests/shards/test_subtype_gloss.py`
- `tests/shards/test_subtype_hypothesis.py`
- `tests/shards/test_subtype_properties.py`

**Commit:** `3c14066`
**Applied fix:** Eliminated hand-typed Literal mirrors across 5 test modules:
- Promoted `_DISPUTED_EPISTEMIC_STATUS_SUBSET` to public
  `DISPUTED_EPISTEMIC_STATUS_SUBSET` in `subtypes.py` (with a backwards-
  compatible private alias) and re-exported it through `shards/__init__.py`.
- Replaced hand-typed `_RECONCILIATION_STRATEGIES`, `_GLOSS_KINDS`, and
  `_GENERATION_METHODS` lists with `typing.get_args(...)` over the public
  `ReconciliationStrategy` / `GlossKind` / `GenerationMethod` Literal aliases
  (which were already exported in iteration 1).
- `_DISPUTED_EPISTEMIC_STATUS` test list and `_IN_SUBSET` Hypothesis sampler
  now derived via `sorted(DISPUTED_EPISTEMIC_STATUS_SUBSET)` for stable
  parametrize / shrink ordering.
- `_AUTHORITY_WEIGHTS` left hand-typed: `AuthorityPosition.weight` is an
  inline `Literal[4]` on the nested model with no public alias — out of
  IN-03 scope per the review's enumerated targets.

`subtypes.py` is now the single source of truth: any future change to a
Literal value automatically propagates to all parametrize and Hypothesis
`sampled_from` strategies.

### IN-04: `test_disputed_proposition_constructs_round_trips` uses one strength for all objections

**Files modified:** `tests/shards/test_subtype_properties.py`
**Commit:** `5712416`
**Applied fix:** Replaced the single `objection_strength` `@given` parameter
(applied homogeneously to all `n_objections` Objection instances) with
`st.data()` plus an in-body `data.draw(st.lists(st.floats(...),
size=n_objections))` to draw an INDEPENDENT strength per Objection. Future
invariants depending on cross-objection strength variation
(e.g., "≥1 strength > 0.5") are now exercisable by this property test.

### IN-05: `test_self_glossing_rejected` relies on deterministic mint to produce IRI collision

**Files modified:** `tests/shards/test_subtype_gloss.py`
**Commit:** `e316f0e`
**Applied fix:** Made the dependency explicit by passing
`shard_iri=iri, glosses=iri` on the second `_sample_shard()` call, so the
no-self-glossing invariant fires deterministically regardless of whether
two `mint_shard_iri()` calls happen to produce the same IRI. Tightened
the assertion from `"self" in msg.lower() or "glosses" in msg` to
`"self" in msg.lower()` alone — narrows the captured error to the intended
branch so a future conftest seed change cannot silently route through the
IRI-format regex branch and pass for the wrong reason. Added a docstring
note explaining the explicit pin.

---

_Fixed: 2026-04-25_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2 (cumulative)_
