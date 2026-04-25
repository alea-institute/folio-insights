# Phase 03: Shard Subtypes — Discussion Log

> **Audit trail only.** Decisions are captured in CONTEXT.md.

**Date:** 2026-04-25
**Phase:** 03-shard-subtypes
**Areas discussed:** SimpleAssertion shape, Reconciliation enum, citation_required gate, dispute_state field, GlossShard validation, Round-trip test mix, File layout

---

## Round 1 (4 questions)

### Q1. SimpleAssertionShard — true empty subtype, or add a placeholder field?

| Option | Selected |
|--------|----------|
| Empty — no new fields (Recommended) | ✓ |
| Add `assertion_confidence: float \| None = None` | |
| Add `assertion_qualifiers: list[str] = Field(default_factory=list)` | |

**User's choice:** Empty (recommended).

### Q2. ConflictingAuthoritiesShard reconciliation_strategy — hard 8-value Literal, escape hatch, or open string?

| Option | Selected |
|--------|----------|
| Hard 8-value Literal (Recommended) | ✓ |
| 8 Literal values + `"custom"` + `custom_note` | |
| Free string + SHACL validation | |

**User's choice:** Hard 8-value Literal (recommended).

### Q3. HypothesisShard `citation_required=True` promotion gate — Phase 3 or Phase 7?

| Option | Selected |
|--------|----------|
| Phase 3: field only; Phase 7 enforces (Recommended) | ✓ |
| Phase 3: `@model_validator` enforces at construction | |
| Phase 3: enforce at promotion via `promote()` helper | |

**User's choice:** Phase 3 ships the field; Phase 7 enforces (recommended).

### Q4. DisputedPropositionShard dispute state — new `dispute_state` field or reuse envelope `epistemic_status`?

| Option | Selected |
|--------|----------|
| Reuse envelope `epistemic_status` (Recommended) | ✓ |
| Add separate `dispute_state` field | |

**User's choice:** Reuse `epistemic_status` (recommended). DisputedPropositionShard adds a `@model_validator` constraining `epistemic_status` to the 4-value subset {hypothesis, attested, contested, aporetic}.

---

## Round 2 (3 questions)

### Q5. GlossShard `glosses: str` referential integrity — where enforced?

| Option | Selected |
|--------|----------|
| Phase 3: format-only validation (Recommended) | ✓ |
| Phase 3: format + class-level coexistence check (no self-glossing) | |
| Defer all validation to Phase 5 | |

**User's choice:** Phase 3 format-only (recommended). Existence checked at Phase 5 SHACL or Phase 13 storage. **Note:** the implementation in CONTEXT.md D-05 ALSO includes the no-self-glossing check (`glosses != self.shard_iri`) as a cheap class-level guard alongside the format regex — this is an editorial enhancement on top of "format-only" since the cost is trivial and the bug is obvious.

### Q6. Round-trip test coverage — verbatim PRD fixtures only, hypothesis property tests, or both?

| Option | Selected |
|--------|----------|
| Both: 3 verbatim + hypothesis 100–500/subtype (Recommended) | ✓ |
| Verbatim PRD fixtures only | |
| Hypothesis only | |

**User's choice:** Both (recommended). Test budget: ≤1000 hypothesis examples total across 5 subtypes; CI runtime budget < 2s.

### Q7. Subtype file layout — single `subtypes.py`, sub-package, or split nested models?

| Option | Selected |
|--------|----------|
| Keep single `subtypes.py` (Recommended) | ✓ |
| Split into `subtypes/` package | |
| Split nested models out into `subtype_models.py` | |

**User's choice:** Single file (recommended). Estimated 250–350 LOC; nested models declared above their parent subtype class.

---

## Claude's Discretion

Four implementation details deferred to the planner:
- Exact regex for `glosses` IRI validation (re-use Phase 02's `_IRI_PREFIX` constant)
- Hypothesis strategies for nested model field-value generation (boundary values for `strength`, `objection_index`, `weight`)
- `@model_validator(mode='after')` vs `@model_validator(mode='before')` choice
- Test fixture file format (JSON files vs inline Python dict constants — JSON aligns better with audit story)

## Deferred Ideas

- 9th `"custom"` reconciliation strategy with free-text note → Phase 7 RFC if needed
- Promotion workflow + citation_required gate enforcement → Phase 7 governance
- GlossShard target-shard existence → Phase 5 SHACL or Phase 13 storage
- `generation_method` post-hoc audit → Phase 9.P2 framework detector
- Subtype splitting into sub-package → revisit if `subtypes.py` exceeds ~600 LOC
- Separate `dispute_state` field → rejected; reuse envelope `epistemic_status` (DRY)
- Per-extraction-path required/optional field split → Phase 7 governance + Phase 10 Stage 8 Shard Minter
