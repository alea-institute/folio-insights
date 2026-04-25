---
phase: 03
plan: 01
subsystem: shards
tags: [shards, subtypes, pydantic, validators, schema]
requires:
  - 02-shard-envelope (ShardEnvelope, ShardType, AttestedSignature, Triple)
  - mint_shard_iri (Phase 02)
provides:
  - 5 PRD §6.2-compliant shard subtypes with subtype-specific fields
  - 3 nested Pydantic models (Objection, Reply, AuthorityPosition)
  - 3 module-level Literal aliases (ReconciliationStrategy, GlossKind, GenerationMethod)
  - 4 @model_validator(mode='after') invariant blocks (D-02..D-06)
  - _SUBTYPE_DEFAULTS test fixture lookup so _sample_shard(cls) constructs every subtype
affects:
  - tests/shards/conftest.py (Wave 2 dependency)
tech-stack:
  added: []
  patterns:
    - Pydantic v2 @model_validator(mode='after') for cross-field invariants
    - frozenset for narrowed Literal-subset validation
    - module-level Literal aliases as canonical type names
    - inline nested BaseModels declared above their parent ShardEnvelope subclass
key-files:
  created: []
  modified:
    - src/folio_insights/shards/subtypes.py (+220 lines)
    - src/folio_insights/shards/__init__.py (+12 lines)
    - tests/shards/conftest.py (+71 lines)
decisions:
  - D-03 "attested" → "authority_only" substitution preserved (envelope ships no "attested" Literal)
  - 8-value ReconciliationStrategy lock — no 9th "custom" escape hatch
  - GlossShard format-only IRI validation — referential integrity deferred to Phase 5/13
  - HypothesisShard ships citation_required field but NO construction-time gate (Phase 7 owns promotion gate)
  - 4 validators (one per non-empty subtype); SimpleAssertionShard has none (D-01 empty subtype)
metrics:
  duration: 12 min
  completed: 2026-04-25
  tasks: 3
  files: 3
---

# Phase 03 Plan 01: Shard Subtype Field Expansion (PRD §6.2) Summary

**One-liner:** Expanded 5 Phase 02 shard stubs with PRD §6.2 fields, 3 nested Pydantic models, 3 Literal aliases, and 4 `@model_validator(mode='after')` invariant blocks; extended `tests/shards/conftest.py` with `_SUBTYPE_DEFAULTS` so `_sample_shard(cls)` constructs every subtype.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Expand subtypes.py with PRD §6.2 fields, nested models, Literal aliases, validators | `4eec371` | `src/folio_insights/shards/subtypes.py` |
| 2 | Re-export 6 new public names from shards package | `99df740` | `src/folio_insights/shards/__init__.py` |
| 3 | Extend conftest.py with `_SUBTYPE_DEFAULTS` for non-empty subtypes | `b81bc44` | `tests/shards/conftest.py` |

## What Was Built

### `src/folio_insights/shards/subtypes.py` (56 → 268 LOC)

- **5 subtype classes** with PRD §6.2-compliant fields:
  - `SimpleAssertionShard` — empty subtype (D-01); no validator
  - `DisputedPropositionShard` — utrum / objections / sed_contra / respondeo / uses_distinctions / replies (D-02)
  - `ConflictingAuthoritiesShard` — sic / non / reconciliation_strategy / reconciliation_note (D-04)
  - `GlossShard` — glosses / gloss_kind / gloss_text (D-05)
  - `HypothesisShard` — generation_method / promotion_requirements / ttl_days=90 / citation_required=True (D-06)
- **3 nested BaseModels** (extra="forbid"): `Objection`, `Reply`, `AuthorityPosition`
- **3 module-level Literal aliases**: `ReconciliationStrategy` (8 values), `GlossKind` (5), `GenerationMethod` (3)
- **4 `@model_validator(mode='after')` blocks** covering D-02/D-03/D-04/D-05/D-06 invariants
- **D-03 4-subset** implemented as `frozenset({"hypothesis", "authority_only", "contested", "aporetic"})` — `"attested"` does NOT appear anywhere
- **Discriminated `Shard` union unchanged** from Phase 02
- **`__all__`** alphabetical with 12 entries

### `src/folio_insights/shards/__init__.py` (33 → 45 LOC)

- 6 new public names re-exported: `AuthorityPosition`, `Objection`, `Reply`, `ReconciliationStrategy`, `GlossKind`, `GenerationMethod`
- `__all__` extended to **exactly 19 alphabetical entries**

### `tests/shards/conftest.py` (89 → 160 LOC)

- `_SUBTYPE_DEFAULTS: dict[type[ShardEnvelope], dict[str, Any]]` lookup table providing required subtype-specific fields for the 4 non-empty subtypes
- `_sample_shard` merge order: envelope defaults → `_SUBTYPE_DEFAULTS[cls]` → caller `**overrides`
- `GlossShard` default `glosses` IRI is `urn:folio:shard/0123456789abcdef` (distinct from minted fixture IRI so no-self-glossing check passes)

## Verification

```bash
$ pytest tests/shards/ -q
...............................................                          [100%]
47 passed in 0.67s
```

All 47 Phase 02 shard tests remain green:
- `test_envelope_roundtrip.py` (round-trip + frozen identity)
- `test_discriminated_union.py` (discriminator dispatch)
- `test_minting_determinism.py` (1000-example hypothesis property test)
- `test_dep_leak_guard.py` (no pyoxigraph/rdflib/oxrdflib/owlready2 imports — including in subtypes.py)
- `test_audit_log.py` (ContentEdit pattern)

Targeted construction check:
```bash
$ python -c "from tests.shards.conftest import _sample_shard, _SUBTYPE_TABLE; [_sample_shard(cls) for _, cls in _SUBTYPE_TABLE]; print('OK')"
OK
```

All 5 subtypes construct without `ValidationError` or `TypeError`.

## Key Decisions

1. **D-03 substitution preserved**: `"authority_only"` substitutes for the PRD's `"attested"` because the envelope ships no `"attested"` Literal value. Documented inline at the `_DISPUTED_EPISTEMIC_STATUS_SUBSET` frozenset and in the module docstring.
2. **No `model_rebuild()` at module bottom**: All nested models are inline-declared above their parent subtype, so no forward-string-refs require resolution.
3. **No `import re` leak**: `re` is stdlib and `_GLOSS_URN_RE`/`_GLOSS_HTTP_RE` are module-private compiled patterns (leading underscore).
4. **`HypothesisShard.citation_required=True` ships as field, NOT gate**: Phase 3 documents in the validator docstring that the construction-time gate is intentionally absent — Phase 7 governance owns the promotion-time enforcement.
5. **`extra="forbid"` inherited** from `ShardEnvelope` — subtype classes do NOT redeclare `model_config`. Nested `BaseModel` subclasses (Objection/Reply/AuthorityPosition) declare it explicitly.

## Deviations from Plan

None — plan executed exactly as written. The plan's resolution of CONTEXT D-03 (substituting `"authority_only"` for `"attested"`) was implemented verbatim.

## Threat Model Compliance

All Phase 3 threat-register dispositions from the plan's `<threat_model>` section were honored:
- **T-03-01** (Information disclosure via validator messages): all `ValueError` messages name only field + constraint + canonicalized value (`f"got {self.epistemic_status!r}"`); no full payload echo.
- **T-03-02** (DoS via deeply-nested validation): nested models contain only scalar fields (no recursive self-reference); `_disputed_invariants` is O(len(objections) + len(replies)).
- **T-03-03** (Tampering via discriminator): the `Shard` discriminated-union shape is unchanged — Phase 02's `test_invalid_shard_type_raises_validation_error` still applies.
- **T-03-04** (GlossShard.glosses referential integrity): explicitly format-only per CONTEXT D-05; risk transferred to Phase 5/13 as planned.
- **T-03-05** (HypothesisShard citation gate): explicitly construction-permissive per CONTEXT D-06; risk transferred to Phase 7 as planned.
- **T-03-06** (AuthorityPosition.authority_iri spoofing): explicitly out of scope; Phase 6 DID-substrate owns signature verification.

## Metrics

- **Duration:** ~12 min (3 sequential tasks, all auto)
- **Tasks:** 3 / 3 completed
- **Files:** 3 modified (no new files)
- **LOC delta:**
  - `subtypes.py`: 56 → 268 (+212)
  - `__init__.py`: 33 → 45 (+12)
  - `conftest.py`: 89 → 160 (+71)
  - **Total:** +295 LOC across 3 files
- **`subtypes.py::__all__`:** 12 entries (alphabetical) — confirmed
- **`shards/__init__.py::__all__`:** 19 entries (alphabetical) — confirmed
- **`@model_validator(mode='after')` count in subtypes.py:** 4 (DisputedProp, ConflictingAuthorities, Gloss, Hypothesis)
- **D-03 4-subset substring `"hypothesis", "authority_only", "contested", "aporetic"` present:** yes
- **`"attested"` substring in subtypes.py:** absent (verified by `! grep -q '"attested"'`)
- **Phase 02 tests:** 47 / 47 green (no regression)

## Self-Check: PASSED

- `src/folio_insights/shards/subtypes.py` — FOUND (268 LOC)
- `src/folio_insights/shards/__init__.py` — FOUND (45 LOC)
- `tests/shards/conftest.py` — FOUND (160 LOC)
- Commit `4eec371` (Task 1) — FOUND
- Commit `99df740` (Task 2) — FOUND
- Commit `b81bc44` (Task 3) — FOUND
