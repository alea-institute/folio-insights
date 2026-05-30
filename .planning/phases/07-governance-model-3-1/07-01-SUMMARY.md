---
phase: 07-governance-model-3-1
plan: 01
subsystem: governance-substrate
tags: [governance, pydantic, discriminated-union, dep-leak-guard, shacl-skeleton]
requires:
  - "shards/envelope.SignedAction (12-value Phase 6 Literal)"
  - "shards/envelope.AttestedSignature (Phase 6 DID-signed attestation)"
provides:
  - "shards/envelope.SignedAction extended to 13 values (D-13 — role_revocation appended)"
  - "governance/events.GovernanceEvent (13-class Pydantic discriminated union over action)"
  - "governance/events: 13 distinct event classes — RoleAssertion, RoleRevocation, Extract, Promotion, Demotion, Contest, ContestResolution, Distinguo, Supersession, Retraction, ContentEdit, Reparent, Reconcile"
  - "governance/shape_validation.ValidationResult (dataclass mirrors revision/shape_validation.ValidationResult)"
  - "governance/shape_validation: 8 NotImplementedError-stubbed per-event SHACL validators (bodies land in 07-03 / 07-04a / 07-04b / 07-05a / 07-05b)"
  - "tests/governance/test_dep_leak_guard.py (D-04 boundary enforcement; exempts shape_validation.py)"
affects:
  - "shards/envelope.py (1-line append to SignedAction Literal — Phase 6 AttestedSignature unchanged)"
  - "pyproject.toml (registered 'governance' pytest marker)"
tech-stack:
  added: []
  patterns:
    - "Annotated[Union[...], Field(discriminator='action')] over Pydantic BaseModel subclasses (mirrors shards/subtypes.Shard)"
    - "Per-file source-scan dep-leak guard with single-file basename exemption (mirrors tests/shards/test_dep_leak_guard.py)"
    - "ValidationResult dataclass + per-event validate_*_shape skeleton (mirrors revision/shape_validation.py — NOT services/shacl_validator.py)"
    - "_BaseEvent with shared corpus / position / signature slots (D-16 — only AttestedSignature shared across events)"
key-files:
  created:
    - src/folio_insights/governance/__init__.py
    - src/folio_insights/governance/events.py
    - src/folio_insights/governance/shape_validation.py
    - src/folio_insights/governance/shapes/.gitkeep
    - tests/governance/__init__.py
    - tests/governance/conftest.py
    - tests/governance/test_signed_action_literal_13_values.py
    - tests/governance/test_role_revocation_distinct_event.py
    - tests/governance/test_dep_leak_guard.py
    - .planning/phases/07-governance-model-3-1/deferred-items.md
  modified:
    - src/folio_insights/shards/envelope.py
    - pyproject.toml
decisions:
  - "D-13: extend SignedAction Literal by exactly one (12 → 13) — role_revocation appended at the end so Phase 6 positional ordering stays stable for downstream serialization"
  - "D-13: RoleRevocationEvent is a structurally distinct Pydantic class from RoleAssertionEvent (different action Literal pin + revoked_role vs role field name) — closes F6 (revocation cannot be a flag)"
  - "D-06: GovernanceEvent dispatches via Annotated[Union[...], Field(discriminator='action')] — the per-class action: Literal['...'] pin enforces dispatch correctness; ConfigDict(extra='forbid') propagates"
  - "D-04: governance/ package boundary is enforced by tests/governance/test_dep_leak_guard.py over [aiosqlite, rdflib, pyoxigraph, oxrdflib]; shape_validation.py is the lone exempt module by basename — exemption is REAL (validated by positive sanity test that asserts the file actually imports rdflib)"
  - "D-16: _BaseEvent ships ONLY corpus + position + signature as shared slots — every other field is per-event-class; AttestedSignature is the only shared primitive type"
  - "D-20: PromotionEvent.cited_iris enforces Pydantic min_length=1 (a zero-citation promotion is a contradiction; would otherwise have to be caught downstream)"
metrics:
  duration_minutes: 25
  completed: 2026-05-30
---

# Phase 07 Plan 01: Governance Substrate Foundation Summary

Extended `SignedAction` Literal to 13 values (added `role_revocation` per D-13), shipped the 13-class `GovernanceEvent` Pydantic discriminated union, established the D-04 boundary discipline under `src/folio_insights/governance/` (no aiosqlite/rdflib/pyoxigraph/oxrdflib imports except in the single exempted `shape_validation.py`), and seeded the per-event SHACL validator skeleton (8 `NotImplementedError`-stubbed validators that 07-03 / 07-04a / 07-04b / 07-05a / 07-05b will populate).

## What Shipped

### 1. SignedAction Literal extension (D-13)

`src/folio_insights/shards/envelope.py:85-108` — appended `"role_revocation"` as the 13th value:
```python
SignedAction = Literal[
    # ...12 Phase 6 values...
    "resolve_contest",
    # ── Phase 7 D-13 extension (12 → 13) ──
    "role_revocation",
]
```

Position is load-bearing: the new value is at the END, so Phase 6 positional ordering stays stable. `AttestedSignature` is **unchanged** (Phase 6 lock preserved).

### 2. GovernanceEvent discriminated union (D-06, D-16)

`src/folio_insights/governance/events.py` ships:

- `_BaseEvent(BaseModel)` — shared `corpus: str`, `position: int = -1`, `signature: AttestedSignature` slots (D-16: only `AttestedSignature` is shared across events).
- **13 event classes**, each pinning its own `action: Literal["<value>"] = "<value>"`:

  1. `RoleAssertionEvent` — `subject_did`, `role`
  2. `RoleRevocationEvent` — `subject_did`, `revoked_role` (distinct class per D-13 — closes F6)
  3. `ExtractEvent` — `shard_iri`, `extractor_model`
  4. `PromotionEvent` — `shard_iri`, `new_status`, `cited_iris` (min_length=1 per D-20)
  5. `DemotionEvent` — `shard_iri`, `new_status: Literal["hypothesis"]`
  6. `ContestEvent` — `shard_iri`, `voter_did`, `position_text`
  7. `ContestResolutionEvent` — `shard_iri`, `resolution_path` (GOV-05: arbiter/distinguo/aporetic — no majority-vote)
  8. `DistinguoEvent` — `shard_iri`, `prime_analogate_iri`, `distinction_kind`
  9. `SupersessionEvent` — `old_shard_iri`, `new_shard_iri`
  10. `RetractionEvent` — `shard_iri`, `cascade_preview_hash`
  11. `ContentEditEvent` — `shard_iri`, `field_path`, `rationale`
  12. `ReparentEvent` — `shard_iri`, `new_parent_iri`
  13. `ReconcileEvent` — `shard_iri`, `strategy`

- `GovernanceEvent = Annotated[Union[...all 13...], Field(discriminator="action")]` — Pydantic dispatches by `action` tag.

### 3. governance/__init__.py barrel re-export

D-04 boundary docstring + re-exports the 13 event classes + `GovernanceEvent` + shared aliases (`RoleName`, `PromotionStatus`, `ContestResolutionPath`) + `ValidationResult`. Mirrors `identity/__init__.py` re-export discipline.

### 4. governance/shape_validation.py skeleton (D-04 exempt)

Mirrors `revision/shape_validation.py:1-139` structure verbatim:
- Module docstring lists the 8 shapes + the T-7-12 exemption rationale.
- `@dataclass class ValidationResult(conforms, violations, results_text)` (signature copied from `revision/shape_validation.py`).
- `_SHAPES_DIR = Path(__file__).parent / "shapes"` (with `.gitkeep` placeholder; TTL files ship in later plans).
- `_load_shape_graph(filename)` — loads TTL, raises `FileNotFoundError` if not yet shipped (no silent "pass" if a shape is missing).
- `_build_event_graph(event)` — emits universal `fi:GovernanceEvent` triples for the three `_BaseEvent` slots; later plans extend with event-specific predicates.
- 8 `validate_*_shape` stubs raising `NotImplementedError("filled by 07-NN")` — explicit about which plan owns each shape.

### 5. tests/governance/

- `__init__.py` (marker).
- `conftest.py` — `genesis_did` constant + `attested_signature_factory` callable + `sample_role_assertion` factory.
- `test_signed_action_literal_13_values.py` — 4 tests: count==13, role_revocation present, role_revocation last (positional), Phase 6 values preserved.
- `test_role_revocation_distinct_event.py` — 6 tests: distinct classes + discriminated-union dispatch both directions + unknown-action rejected + `extra="forbid"` propagation + JSON round-trip.
- `test_dep_leak_guard.py` — parametrized over `[aiosqlite, rdflib, pyoxigraph, oxrdflib]`; `rglob` walks `governance/` and refuses `import X` / `from X` substrings; exempts `shape_validation.py` by basename; a positive sanity test asserts the exemption is REAL (`shape_validation.py` does in fact import `rdflib` — exemption is not vacuous).

## Test Counts

| Suite                                  | Tests Added | Status |
| -------------------------------------- | ----------- | ------ |
| tests/governance (this plan total)     | 15          | 15/15 passing |
| tests/governance/test_signed_action_literal_13_values | 4 | passing |
| tests/governance/test_role_revocation_distinct_event  | 6 | passing |
| tests/governance/test_dep_leak_guard                  | 5 (4 parametrized + 1 sanity) | passing |
| tests/shards (regression)              | 0 added     | 148/148 passing (no regression) |

## Acceptance Criteria

- [x] `grep -c '"role_revocation"' src/folio_insights/shards/envelope.py` → 1
- [x] `len(get_args(SignedAction)) == 13` AND `'role_revocation' in get_args(SignedAction)` → True
- [x] `from folio_insights.governance.events import GovernanceEvent, RoleRevocationEvent, ...` → ok
- [x] `TypeAdapter(GovernanceEvent)` compiles → ok
- [x] `uv run pytest tests/governance -x -q` → 15/15 pass
- [x] `grep -rn "import aiosqlite|import rdflib|import pyoxigraph|import oxrdflib" src/folio_insights/governance/` outside `shape_validation.py` → empty
- [x] `ValidationResult(conforms=True, violations=[], results_text="")` instantiates → ok
- [x] `validate_governance_log_shape(<any>)` → `NotImplementedError` raised
- [x] Negative-polarity smoke: temporarily inject `import aiosqlite` into `events.py` → dep-leak guard fails as expected; revert restores green
- [x] `uv run ruff check src/folio_insights/governance/ src/folio_insights/shards/envelope.py` → clean
- [x] `from folio_insights.governance import GovernanceEvent, RoleRevocationEvent, ValidationResult` → ok (barrel re-export wiring works)

## TDD Gate Compliance

This plan ships under `tdd="true"` on Task 1. RED → GREEN sequence captured in git log:

| Phase  | Commit  | Description |
| ------ | ------- | ----------- |
| RED    | 28284a5 | `test(07-01): add failing tests for SignedAction 13 values + RoleRevocationEvent` (tests fail because SignedAction has 12 values and `governance.events` doesn't exist) |
| GREEN  | c69900f | `feat(07-01): extend SignedAction to 13 values + GovernanceEvent discriminated union` (10/10 Task 1 tests pass) |
| Task 2 | 1bc33c6 | `feat(07-01): shape_validation.py skeleton + governance/ dep-leak guard (D-04)` (5/5 additional tests pass) |

REFACTOR phase: not needed (the GREEN implementation matches the plan's PATTERNS-mandated structure; no clean-up pass yielded behavior-preserving improvements worth a separate commit).

## Deviations from Plan

None. The plan was executed exactly as written.

A handful of plan-level minor enhancements (NOT deviations — all explicitly suggested in the plan or its referenced PATTERNS / RESEARCH):
- Added a positive sanity test in `test_dep_leak_guard.py` (`test_shape_validation_is_exempt`) that asserts the exemption is REAL — i.e. `shape_validation.py` actually imports `rdflib`. This catches a silent regression where someone renames the file or removes the rdflib import while leaving the exemption in place.
- Promoted three repeated Literal vocabularies to module-level aliases in `events.py`: `RoleName`, `PromotionStatus`, `ContestResolutionPath`. The plan describes these vocabularies inline on each event class; centralizing them makes future additions (e.g., a new role) a one-line change. Both `RoleAssertionEvent.role` and `RoleRevocationEvent.revoked_role` now reference `RoleName`. This is structural housekeeping aligned with PATTERNS.md's spirit but not explicitly mandated.

## Known Stubs

The 8 `validate_*_shape` functions in `governance/shape_validation.py` raise `NotImplementedError` by design — they are stubs filled by later plans (07-03 / 07-04a / 07-04b / 07-05a / 07-05b). This is explicit, plan-mandated, and documented in each stub's error message. The plan calls these out as the "07-03 / 07-04a / 07-04b / 07-05a / 07-05b will populate" placeholders.

The `governance/shapes/` TTL files don't exist yet (only a `.gitkeep` placeholder); the loader (`_load_shape_graph`) raises `FileNotFoundError` if called before the TTL ships. This is honest about the state — no silent "passed" validation.

## Deferred Issues (out of scope)

Pre-existing environment failures unrelated to Phase 7 (see `.planning/phases/07-governance-model-3-1/deferred-items.md`):
- 7 `test_*_api.py` files cannot collect due to missing `fastapi` dep.
- 5 `test_ingestion.py` tests fail due to missing `folio-enrich/backend/` directory.

Both predate Plan 07-01 (reproduce on the worktree base commit before any change in this plan).

## Self-Check: PASSED

**Files created (existence verified):**
- src/folio_insights/governance/__init__.py — FOUND
- src/folio_insights/governance/events.py — FOUND
- src/folio_insights/governance/shape_validation.py — FOUND
- src/folio_insights/governance/shapes/.gitkeep — FOUND
- tests/governance/__init__.py — FOUND
- tests/governance/conftest.py — FOUND
- tests/governance/test_signed_action_literal_13_values.py — FOUND
- tests/governance/test_role_revocation_distinct_event.py — FOUND
- tests/governance/test_dep_leak_guard.py — FOUND
- .planning/phases/07-governance-model-3-1/deferred-items.md — FOUND

**Commits (existence verified via `git log`):**
- 28284a5 — FOUND (RED tests)
- c69900f — FOUND (GREEN: SignedAction + GovernanceEvent)
- 1bc33c6 — FOUND (Task 2: shape_validation skeleton + dep-leak guard)
