---
phase: 03-shard-subtypes
reviewed: 2026-04-25T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - src/folio_insights/shards/subtypes.py
  - src/folio_insights/shards/__init__.py
  - tests/shards/conftest.py
  - tests/shards/fixtures/example_a1_simple_assertion.json
  - tests/shards/fixtures/example_a2_conflicting_authorities.json
  - tests/shards/fixtures/example_a3_disputed_proposition.json
  - tests/shards/test_subtype_simple_assertion.py
  - tests/shards/test_subtype_disputed_proposition.py
  - tests/shards/test_subtype_conflicting_authorities.py
  - tests/shards/test_subtype_gloss.py
  - tests/shards/test_subtype_hypothesis.py
  - tests/shards/test_subtype_properties.py
findings:
  critical: 0
  warning: 2
  info: 5
  total: 7
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-04-25
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Phase 03 implements the 5 §6.2 shard subtypes as a discriminated union (`Shard`)
on top of the Phase 02 `ShardEnvelope`, with 3 nested models, 3 module-level
`Literal` aliases, and per-subtype `@model_validator(mode="after")` invariants
matching the locked CONTEXT decisions D-01..D-07. Quality is high: validators
are concise and correctly reference envelope fields (e.g., `shard_iri`,
`epistemic_status`), error messages cite the controlling CONTEXT IDs,
`ConfigDict(extra="forbid")` is inherited consistently, and the test suite
covers fixture round-trips, Literal-lock enumeration, invariant rejection,
and Hypothesis property tests with a budget that matches the D-09 lock
(100+300+200+200+200 = 1000 examples).

No critical issues. Two warnings concern incomplete validation on nested
models and a Hypothesis test that silently skips rather than rejects examples.
Five info items relate to redundant work, a permissive regex, and minor
test-quality observations.

## Warnings

### WR-01: Nested models lack non-empty/non-blank validation on string IRI/text fields

**File:** `src/folio_insights/shards/subtypes.py:45-66, 115-123`
**Issue:** `Objection.cites`, `Objection.argues`, `Reply.argument`, and
`AuthorityPosition.authority_iri` / `position` / `jurisdiction` are typed
`str` with no `Field(min_length=1)` and no whitespace check. Construction
succeeds with `Objection(cites="", argues="", strength=0.5)` and similarly
for empty `AuthorityPosition` fields. The shard-level validators only check
collection cardinality (`len(self.objections) < 1`, `len(self.sic) < 1`),
not the contents of nested elements — so a `DisputedPropositionShard` or
`ConflictingAuthoritiesShard` can be constructed with empty-string nested
identifiers, defeating downstream consumers that assume a non-empty IRI.
This is inconsistent with the GlossShard treatment (which DOES check
`gloss_text.strip()` non-blank, subtypes.py:205-209) and with the
ConflictingAuthoritiesShard treatment of `reconciliation_note`
(subtypes.py:160-164).
**Fix:** Add `Field(min_length=1)` (or a model_validator stripping whitespace)
to the string fields on `Objection`, `Reply`, and `AuthorityPosition`. Example:
```python
class Objection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cites: str = Field(min_length=1)
    argues: str = Field(min_length=1)
    strength: float = Field(ge=0.0, le=1.0)
```
If by-design (e.g., placeholder support during extraction is intentional),
add a docstring note explicitly disclaiming non-empty enforcement so
reviewers/consumers don't assume it.

### WR-02: Hypothesis property test silently skips self-gloss collisions instead of using `assume()`

**File:** `tests/shards/test_subtype_properties.py:145-154`
**Issue:** The Gloss property test uses bare `return` to skip cases where
`iri == shard.shard_iri`:
```python
if iri == shard.shard_iri:
    return
```
A plain `return` in a Hypothesis-generated test passes the example (it is
counted toward the 200-example budget AND counted as success), which can
mask shrink-driven failures and inflates effective coverage on paper.
The idiomatic primitive is `hypothesis.assume(...)` which marks the example
as discarded so Hypothesis generates a replacement. Although the practical
collision probability is ~2^-64 (negligible), shrinking explores edge
inputs and may find this collision deterministically.
**Fix:**
```python
from hypothesis import assume
...
assume(iri != shard.shard_iri)
rehydrated = GlossShard.model_validate(shard.model_dump())
assert rehydrated == shard
```

## Info

### IN-01: `_sample_shard` re-mints `mint_shard_iri` on every call (per-test cost)

**File:** `tests/shards/conftest.py:113`
**Issue:** Every invocation of `_sample_shard` calls
`mint_shard_iri("urn:x:fixture", "sample span")`. Because the inputs are
constants and minting is deterministic (per Phase 02 D-02), this returns
the same `(iri, h)` tuple every time, so the cost is wasted across the
~1000-example Hypothesis budget. Not a correctness bug — `mint_shard_iri`
is pure — but the comment at line 110-111 ("downstream tests that re-mint
will get matching values") implies determinism, so caching is safe.
**Fix:** Cache at module scope:
```python
_FIXTURE_IRI, _FIXTURE_HASH = mint_shard_iri("urn:x:fixture", "sample span")
def _sample_shard(...):
    defaults = {"shard_iri": _FIXTURE_IRI, "provenance_hash": _FIXTURE_HASH, ...}
```

### IN-02: `_GLOSS_HTTP_RE` is intentionally permissive — consider documenting examples of accepted/rejected

**File:** `src/folio_insights/shards/subtypes.py:181`
**Issue:** `^https?://[^\s]+$` accepts `http://x`, `https://!@#`, and other
strings that are technically syntactically-loose URLs. The leading docstring
notes "format-only check; referential integrity is Phase 5 SHACL or Phase 13
storage scope" (subtypes.py:178-179), which is the correct posture, but
the looseness may surprise reviewers comparing against RFC 3986. The
test at `tests/shards/test_subtype_gloss.py:34-44` covers good cases but
not borderline ones (e.g., `http://x`, `http:// space`).
**Fix:** Either add a comment immediately above `_GLOSS_HTTP_RE` enumerating
the *intentional* permissiveness, or add a single negative-case parametrize
entry like `"https://"` (which currently *would* fail because `[^\s]+`
requires ≥1 trailing char) to lock the boundary.

### IN-03: `_DISPUTED_EPISTEMIC_STATUS_SUBSET` duplicated as a list literal in tests

**File:** `tests/shards/test_subtype_disputed_proposition.py:32`,
`tests/shards/test_subtype_properties.py:53`
**Issue:** `_DISPUTED_EPISTEMIC_STATUS` is hand-typed in both test modules
and must stay in lockstep with `_DISPUTED_EPISTEMIC_STATUS_SUBSET` in
`subtypes.py:71-73`. A future change to the 4-subset that updates one
constant but not the others will produce confusing test failures (or
worse, false-positive test passes).
**Fix:** Either import the source constant in tests:
```python
from folio_insights.shards.subtypes import _DISPUTED_EPISTEMIC_STATUS_SUBSET
_IN_SUBSET = sorted(_DISPUTED_EPISTEMIC_STATUS_SUBSET)
```
or expose it as a public module-level alias (e.g.,
`DISPUTED_EPISTEMIC_STATUS = Literal[...]`) and `typing.get_args` it.
The same applies to `_RECONCILIATION_STRATEGIES` and `_GLOSS_KINDS` and
`_GENERATION_METHODS` redefined in 4+ test files.

### IN-04: `test_disputed_proposition_constructs_round_trips` uses one strength for all objections

**File:** `tests/shards/test_subtype_properties.py:62, 73-75`
**Issue:** The test takes a single `objection_strength` from Hypothesis
and applies it to all `n_objections` Objection instances. With
`max_examples=300` and `n_objections ∈ [1,5]`, this still gives good
diversity per-example, but each example tests a homogeneous strength
distribution. Not a bug — the round-trip property is value-agnostic —
but if future invariants depend on cross-objection strength variation
(e.g., "at least one strength > 0.5"), this strategy will not catch
violations.
**Fix:** Optional. Use `st.lists(st.floats(...), min_size=n, max_size=n)`
inside the body to draw heterogeneous strengths, or `st.builds(Objection, ...)`
to generate full Objection instances directly.

### IN-05: `test_self_glossing_rejected` relies on deterministic mint to produce IRI collision

**File:** `tests/shards/test_subtype_gloss.py:64-72`
**Issue:** The test calls `_sample_shard(GlossShard)` twice and assumes
the second call produces a shard with the *same* `shard_iri` as the first
(so passing `glosses=iri` triggers the no-self-gloss error). This holds
because `mint_shard_iri("urn:x:fixture", "sample span")` is deterministic
(Phase 02 D-02), but the test is brittle to a future conftest change that
randomizes the fixture seed. The assertion would silently pass (wrong-error
path) if the IRIs diverge, since the IRI-format regex would then catch the
mismatch instead of the self-gloss invariant.
**Fix:** Make the dependency explicit:
```python
def test_self_glossing_rejected() -> None:
    shard = _sample_shard(GlossShard)
    iri = shard.shard_iri
    with pytest.raises(ValidationError) as exc_info:
        # Force same shard_iri so we hit the self-gloss branch, not IRI-format.
        _sample_shard(GlossShard, shard_iri=iri, glosses=iri)
    msg = str(exc_info.value).lower()
    assert "self" in msg  # narrower assertion locks the intended branch
```

---

_Reviewed: 2026-04-25_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
