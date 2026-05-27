---
phase: 05-content-versioning-6-4
plan: 03
subsystem: testing
tags: [pyshacl, rdflib, shacl, sh-sparql, content-versioning, forward-only, defense-in-depth, dep-leak-boundary]

# Dependency graph
requires:
  - phase: 05-content-versioning-6-4 (Plan 01)
    provides: Enriched ContentEdit (field_path, edited_at datetime, rationale, AttestedSignature) + authoritative forward-only @model_validator on ShardEnvelope + conftest _content_edit/_sample_shard builders
  - phase: 05-content-versioning-6-4 (Plan 02)
    provides: revision/ package (with __init__ that deliberately does NOT re-export validate_content_edit_shape) + tests/revision/ package marker + conftest fixtures
  - phase: 01-polysemy
    provides: validate_*_shape() defense-in-depth idiom (distinguo.py)
  - phase: v1 services
    provides: pyshacl load/validate pattern + ValidationResult dataclass (services/shacl_validator.py)
provides:
  - "Real pyshacl TTL shape (content_edit_shape.ttl) enforcing forward-only monotonic edited_at via a sh:sparql self-join over the rdf:List edit chain (D-07.2; exit criterion 2)"
  - "validate_content_edit_shape(shard) -> ValidationResult — model->RDF->pyshacl defense-in-depth guard living in revision/ (outside the shards/ dep-leak boundary)"
  - "Both-polarity SHACL forward-only test (ordered conforms=True / back-dated conforms=False) — exit criterion 2 green"
  - "Independent confirmation that the Plan-01 Pydantic @model_validator is the authoritative forward-only gate (D-07.1)"
affects: [06-did-substrate, 07-governance, 11-shacl-hybrid, 13-storage]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-layer forward-only enforcement: Pydantic @model_validator (authoritative, always-on) + pyshacl sh:sparql shape (defense-in-depth, catches model_construct bypass)"
    - "Minimal local RDF mapping (shard -> fi:Shard node -> fi:contentEdits rdf:List of edit nodes carrying fi:editedAt + integer fi:seq) feeding pyshacl without pulling the Phase-13 store forward"
    - "sh:sparql self-join matching the BAD condition (FILTER(?ct < ?pt)) so a violation fires when the SELECT returns >=1 row — load-bearing polarity"

key-files:
  created:
    - src/folio_insights/revision/content_edit_shape.ttl
    - src/folio_insights/revision/shape_validation.py
    - tests/revision/test_shacl_forward_only.py
    - tests/revision/test_forward_only_validator.py
  modified: []

key-decisions:
  - "[05-03] The SHACL shape lives in revision/ (NOT shards/) — rdflib/pyshacl imports are safe there; tests/shards/test_dep_leak_guard.py forbids them only under shards/. Confirmed green."
  - "[05-03] Negative polarity is exercised via SimpleAssertionShard.model_construct (bypassing the authoritative Pydantic validator) — exactly the out-of-band-record case the defense-in-depth shape exists to catch; the validator would otherwise reject the back-dated chain at construction."
  - "[05-03] SHACL enforces ONLY the forward-only half (monotonic edited_at). Immutability of past entries (D-08a) is stateless-over-one-snapshot and NOT SHACL-enforceable (RESEARCH L115-124); it is carried by ContentEdit frozen=True + the IMMUTABLE_FIELD_PATHS gate (Plan 01/02). Documented in code and tests; not a gap."
  - "[05-03] _build_edit_graph uses rdflib.collection.Collection to wire the rdf:first/rdf:rest/rdf:nil list the shape's property path traverses, and an integer fi:seq per edit so the self-join can match adjacent pairs (?cs = ?ps + 1)."

patterns-established:
  - "model->RDF->pyshacl defense-in-depth validate_*_shape() with a real pyshacl.validate run (not a Python-level re-check like distinguo)"
  - "Both-polarity SHACL test (positive conforms + negative violation) guarding sh:sparql constraint-polarity regressions"

requirements-completed: [SHARD-09]

# Metrics
duration: 2 min
completed: 2026-05-27
---

# Phase 5 Plan 03: SHACL Forward-Only Guard Summary

**Shipped the literal "SHACL guard" (exit criterion 2): a real pyshacl TTL shape (`content_edit_shape.ttl`) enforcing forward-only monotonic `edited_at` via a `sh:sparql` self-join over the `rdf:List` edit chain, plus `validate_content_edit_shape(shard)` that builds a minimal local RDF graph and runs pyshacl against it — defense-in-depth beside the authoritative Pydantic validator, living in `revision/` so the `shards/` dep-leak boundary stays green.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-27T17:00:25Z
- **Completed:** 2026-05-27T17:02:13Z
- **Tasks:** 2
- **Files created:** 4 (2 source: TTL shape + validator module; 2 test modules)

## Accomplishments

- `content_edit_shape.ttl`: the VERIFIED forward-only `sh:sparql` NodeShape from RESEARCH L83-103 copied verbatim — a self-join over `fi:contentEdits`/`rdf:rest*`/`rdf:first` matching the BAD (back-dated) condition `FILTER(?ct < ?pt)` over adjacent `fi:seq` pairs. Polarity is load-bearing; a violation fires when the SELECT returns ≥1 row.
- `shape_validation.py`: `validate_content_edit_shape(shard)` — lazy-parses the TTL, builds the data graph via `_build_edit_graph` (each edit → `fi:editedAt` `xsd:dateTime` literal + integer `fi:seq`, wired into an `rdf:List` via `rdflib.collection.Collection`), runs `pyshacl.validate(..., inference="none", abort_on_first=False)` exactly mirroring `services/shacl_validator.py`, and parses violations into a `ValidationResult`. Module docstring documents the CAN/CANNOT division explicitly.
- Both-polarity SHACL test (`test_shacl_forward_only.py`): ordered chain `conforms is True`, back-dated chain `conforms is False` with a forward-only violation message (negative polarity built via `model_construct` to bypass the authoritative Pydantic gate). Empty chain trivially conforms.
- Validator-confirmation test (`test_forward_only_validator.py`): independently asserts the Plan-01 Pydantic `@model_validator` is authoritative — an ordered chain re-validates, a back-dated chain raises on `model_validate` (D-07.1).
- `revision/` stays the home for all RDF code; `tests/shards/test_dep_leak_guard.py` green (no rdflib leak into `shards/`). 51 combined `tests/revision` + dep-leak tests pass.

## Task Commits

Each task was committed atomically:

1. **Task 1: content_edit_shape.ttl + validate_content_edit_shape() (model→RDF→pyshacl)** - `c27e092` (feat)
2. **Task 2: SHACL forward-only test (both polarities) + validator confirmation test** - `d38bb64` (test)

**Plan metadata:** committed separately with this SUMMARY.

## Files Created/Modified

- `src/folio_insights/revision/content_edit_shape.ttl` (created) - Forward-only `sh:sparql` NodeShape over the `rdf:List` edit chain; `FILTER(?ct < ?pt)` load-bearing polarity; CAN/CANNOT division in header comments.
- `src/folio_insights/revision/shape_validation.py` (created) - `validate_content_edit_shape(shard) -> ValidationResult` + `_build_edit_graph` minimal RDF mapping + a local `ValidationResult` dataclass mirroring `shacl_validator.py`.
- `tests/revision/test_shacl_forward_only.py` (created) - Exit-criterion-2 both-polarity SHACL guard test (3 tests: ordered, back-dated, empty).
- `tests/revision/test_forward_only_validator.py` (created) - Authoritative Pydantic validator confirmation (2 tests: ordered validates, non-monotonic rejected).

## Decisions Made

- **SHACL code lives in `revision/`, never `shards/`.** rdflib/pyshacl imports are safe in `revision/` (outside the dep-leak boundary); `tests/shards/test_dep_leak_guard.py` forbids them only under `shards/`. Verified green.
- **Negative polarity uses `model_construct` to bypass the authoritative validator.** The Plan-01 `@model_validator` would reject a back-dated chain at construction, so the SHACL guard's negative case is exercised on a bypassed record — exactly the out-of-band-load scenario defense-in-depth exists to catch.
- **SHACL enforces only the forward-only half.** Immutability of past entries (D-08a) is not SHACL-enforceable over a single snapshot (RESEARCH L115-124); that half is carried structurally by `ContentEdit` frozen + the `IMMUTABLE_FIELD_PATHS` gate (Plan 01/02). Documented in the module docstring and both test modules; not a gap.
- **`_build_edit_graph` wires an explicit integer `fi:seq` per edit** so the self-join matches adjacent pairs (`?cs = ?ps + 1`), and uses `rdflib.collection.Collection` to emit the `rdf:first`/`rdf:rest`/`rdf:nil` list the shape's property path traverses.

## Deviations from Plan

None - plan executed exactly as written.

The verified `sh:sparql` shape from RESEARCH was copied verbatim and the pyshacl load/run call mirrors `services/shacl_validator.py` exactly. The only implementation choice within the plan's latitude was using `rdflib.collection.Collection` (vs. manual `rdf:first`/`rdf:rest` BNodes) to build the `rdf:List` — the plan explicitly permitted either.

## Issues Encountered

- **Pre-existing, out-of-scope collection error (carried from 05-01/05-02):** `tests/test_*_api.py` fail to import `fastapi` (dev dep absent in this environment), which would block a bare `uv run pytest` collection. Per the phase constraint and scope-boundary rule, NOT fixed; verification was scoped to `tests/revision` + `tests/shards/test_dep_leak_guard.py` (51 passed). Logged for visibility; no action required for this plan.
- **Benign Pydantic serializer warning** surfaces from Plan 02's `test_validate_shard_rejects_silent_wrong_type` (a deliberate wrong-type round-trip), not from this plan's code. No action.

## User Setup Required

None - no external service configuration required. RESEARCH Package Legitimacy Audit confirms pyshacl 0.31.0 / rdflib 7.6.0 are pre-existing pinned core deps; no install task in this plan.

## Next Phase Readiness

- **Exit criterion 2 is green** — the SHACL guard rejects edits to past versions (back-dated insert → `conforms=False`) and an ordered chain conforms. Phase 5 now satisfies all three exit criteria (1: append-only audit, 2: SHACL guard, 3: `get_shard_at` reverse-replay) across Plans 01/02/03.
- **Phase 11 seam open:** the full SHACL-Hybrid shape suite + Pydantic-to-SHACL generator is deferred; this plan ships the one focused content-edit shape Phase 5 needs.
- **Accepted threats (unchanged):** T-05-13 (immutability of past entries is not SHACL-enforceable — carried by frozen + gate, documented division, not a gap).

## Self-Check: PASSED

- Created files exist: `content_edit_shape.ttl`, `shape_validation.py`, `tests/revision/test_shacl_forward_only.py`, `tests/revision/test_forward_only_validator.py` — all FOUND
- Task commits exist: `c27e092`, `d38bb64` — both FOUND in git log
- Plan verification: `uv run pytest tests/revision tests/shards/test_dep_leak_guard.py -q` → 51 passed; TTL parses as valid turtle; `validate_content_edit_shape` import resolves
- Acceptance criteria: Task 1 (TTL has `sh:sparql` + `FILTER(?ct < ?pt)`, `def validate_content_edit_shape(` + `pyshacl.validate(` present, no `export/shapes.ttl` reference, under `revision/`, dep-leak guard exit 0, import + parse exit 0) and Task 2 (both polarities asserted, validator rejects non-monotonic chain, both test files exit 0) — all verified PASS

---
*Phase: 05-content-versioning-6-4*
*Completed: 2026-05-27*
