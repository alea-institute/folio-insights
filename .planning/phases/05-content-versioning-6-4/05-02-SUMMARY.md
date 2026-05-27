---
phase: 05-content-versioning-6-4
plan: 02
subsystem: database
tags: [pydantic, content-versioning, reverse-replay, async, store-seam, hypothesis, sha256, immutable-fields]

# Dependency graph
requires:
  - phase: 05-content-versioning-6-4 (Plan 01)
    provides: Enriched ContentEdit (dotted field_path, required rationale, AttestedSignature slot) + authoritative forward-only @model_validator on ShardEnvelope + conftest _content_edit builder
  - phase: 02-shard-envelope
    provides: ShardEnvelope (6 frozen identity fields, mutable Triple submodel), AttestedSignature stub, model_rebuild() forward-ref
  - phase: 04-iri-scheme-6-3
    provides: immutable hex32 shard IRIs (edits never change the IRI)
provides:
  - "Async store-backed edit_shard_content() write path matching the PRD §6.4 signature (D-01, D-03)"
  - "In-memory ShardStore protocol + InMemoryShardStore dict seam (D-02; Phase 13 swaps Oxigraph behind the same interface)"
  - "Dotted-path get_field/set_field helpers + central IMMUTABLE_FIELD_PATHS gate (10 paths; raises before any mutation, D-06)"
  - "Real deterministic canonical_content_hash() (sorted-key JSON SHA-256, D-05) + unsigned sign_attestation() stub (D-05)"
  - "validate_shard() post-edit re-validation hook (V5 — rejects silent wrong-type and back-dated chains)"
  - "get_shard_at() reverse-replay historical reconstruction on a deep copy (D-09; exit criterion 3)"
affects: [05-03 shacl-guard, 06-did-substrate, 07-governance, 10-arq-orchestration, 13-storage]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ShardStore Protocol seam (async get/put by IRI) — in-memory dict in Phase 5, Oxigraph in Phase 13, no caller churn"
    - "Reverse-replay reconstruction on model_copy(deep=True) — never mutate the stored shard; strict > undo keeps exact-t ties"
    - "Post-edit validate_shard() re-validation (model_validate(model_dump())) because validate_assignment is OFF"
    - "Transactional append+assign: roll the content_edits.append() back if set_field raises"

key-files:
  created:
    - src/folio_insights/revision/__init__.py
    - src/folio_insights/revision/store.py
    - src/folio_insights/revision/content_edit.py
    - tests/revision/__init__.py
    - tests/revision/conftest.py
    - tests/revision/test_immutable_gate.py
    - tests/revision/test_edit_shard_content.py
    - tests/revision/test_get_shard_at.py
    - tests/revision/test_get_shard_at_properties.py
  modified: []

key-decisions:
  - "[05-02] ShardStore is a runtime_checkable typing.Protocol over an in-memory dict (InMemoryShardStore._d); stdlib + Pydantic only, NO aiosqlite/pyoxigraph — Phase 13 fills the persistent backend behind the identical async interface (D-02)"
  - "[05-02] IMMUTABLE_FIELD_PATHS is a 10-member frozenset (6 frozen identity + triple.subject/.predicate + content_edits/signatures); the gate raises BEFORE any mutation; triple.object is deliberately editable (re-parenting, D-04)"
  - "[05-02] canonical_content_hash hashes the FULL pre-edit snapshot via model_dump(mode='json') + sorted-key json.dumps + sha256 (RESEARCH A2); Phase 6 swaps JCS into the single json.dumps line"
  - "[05-02] validate_shard re-runs full validation (model_validate(model_dump())) after every edit because validate_assignment is OFF — keeps the silent-wrong-type guard real, not faked (V5 / Pitfall 2)"
  - "[05-02] edit_shard_content appends then assigns transactionally, rolling the append back (content_edits.pop()) if set_field raises, so the audit chain never carries a failed edit"
  - "[05-02] get_shard_at returns None for unknown IRI and for t < extracted_at (D-09/A3 unambiguous choice); reconstructs on model_copy(deep=True); strict > undo keeps an edit at exactly t"

patterns-established:
  - "Async by-IRI store seam (Protocol + in-memory impl) as the Phase 13 swap point"
  - "Reverse-replay on a deep copy with strict-> undo + chain trimming"
  - "Hypothesis property test (1000 examples) for reconstruction invariants, matching Phase 2 minting-determinism rigor"

requirements-completed: [SHARD-09]

# Metrics
duration: 6 min
completed: 2026-05-27
---

# Phase 5 Plan 02: revision/ Write Path + Reverse-Replay Reconstruction Summary

**Built the `revision/` package: the async store-backed `edit_shard_content()` write path (PRD §6.4 signature) over an in-memory `ShardStore` seam, the dotted-path field helpers + 10-member `IMMUTABLE_FIELD_PATHS` gate, a real deterministic `canonical_content_hash()`, the post-edit `validate_shard()` re-validation hook, and `get_shard_at()` reverse-replay historical reconstruction — verified across a 10-edit fixture and a 1000-example Hypothesis property suite (exit criterion 3).**

## Performance

- **Duration:** 6 min
- **Started:** 2026-05-27T16:50:50Z
- **Completed:** 2026-05-27T16:56:42Z
- **Tasks:** 2
- **Files created:** 9 (3 source modules + 6 test modules incl. package marker + conftest)

## Accomplishments

- `revision/store.py`: `ShardStore` runtime-checkable Protocol (async `get`/`put` by IRI) + `InMemoryShardStore` dict seam (D-02). Stdlib + Pydantic only — Phase 13 swaps Oxigraph behind the same interface with no caller churn.
- `revision/content_edit.py`: the async PRD §6.4 `edit_shard_content()` write path (D-01/D-03) orchestrating lookup → immutable gate → capture old_value + real pre-edit hash → build signed `ContentEdit` → transactional append+assign → post-edit re-validation → store.put → return. `signing_key` is the unused Phase 6 seam.
- `IMMUTABLE_FIELD_PATHS` (D-06): 10-member frozenset — gate raises BEFORE any mutation. `triple.subject`/`.predicate` are guarded ONLY by this gate (the `Triple` submodel is mutable); `triple.object` stays editable (re-parenting, D-04).
- `canonical_content_hash()` (D-05): real deterministic 64-hex SHA-256 over `model_dump(mode="json")` + sorted-key `json.dumps`, mirroring `shards/minting.py`. `sign_attestation()` returns an unmistakably unsigned `AttestedSignature` (`signature=""`, `action="content_edit"`).
- `validate_shard()` (V5/Pitfall 2): re-runs full validation via `model_validate(model_dump())` so a silent wrong-type `set_field` (validate_assignment is OFF) or a back-dated chain is rejected at edit time.
- `get_shard_at()` reverse-replay (D-09): reconstructs on `model_copy(deep=True)` (never mutates the stored shard), undoes edits with `edited_at > t` (strict `>` keeps exact-`t` ties), trims the chain to `edited_at <= t`; returns `None` for unknown IRI and `t < extracted_at`.
- Tests: 41 `tests/revision/` tests green (immutable gate, async write path, store round-trip, hash, sign stub, validate hook, 10-edit historical retrieval with exact-`t` tie + stored-shard-unchanged, 1000-example Hypothesis invariants). 188 combined `tests/shards` + `tests/revision` pass (Plan 01 schema unbroken).

## Task Commits

Each task was committed atomically:

1. **Task 1: ShardStore seam + content_edit module (helpers, gate, hash, sign, edit path)** - `9d05698` (feat) — TDD RED+GREEN in one commit (durable tests are the RED)
2. **Task 2: get_shard_at reverse-replay + 10-edit fixture + property tests** - `75befed` (test) — GREEN against the get_shard_at impl shipped in Task 1's content_edit.py

**Plan metadata:** committed separately with this SUMMARY.

_Note: `get_shard_at` was implemented in Task 1's `content_edit.py` so the package `__init__` exports cleanly; Task 2 ships its durable tests + the 10-edit fixture that exercise it (TDD GREEN). `model_copy(deep=True)` appears twice in the module (docstring + impl line), satisfying the ≥1 acceptance check._

## Files Created/Modified

- `src/folio_insights/revision/store.py` (created) - `ShardStore` Protocol + `InMemoryShardStore` dict seam (D-02).
- `src/folio_insights/revision/content_edit.py` (created) - `edit_shard_content`, `get_shard_at`, `get_field`, `set_field`, `IMMUTABLE_FIELD_PATHS`, `canonical_content_hash`, `sign_attestation`, `validate_shard`.
- `src/folio_insights/revision/__init__.py` (created) - public re-exports + `__all__`; comment notes `validate_content_edit_shape` is Plan 03's (not re-exported here).
- `tests/revision/__init__.py` (created) - test package marker (so Plan 03's sibling test files have a package).
- `tests/revision/conftest.py` (created) - `store`/`sample_shard`/`stored_shard` fixtures + the `ten_edit_history` 10-edit fixture (reuses `tests/shards` `_sample_shard`/`_content_edit`).
- `tests/revision/test_immutable_gate.py` (created) - gate membership + raises-before-mutation + triple.subject-blocked/object-allowed.
- `tests/revision/test_edit_shard_content.py` (created) - store round-trip, dotted helpers, hash, sign stub, async write path, validate_shard wrong-type rejection.
- `tests/revision/test_get_shard_at.py` (created) - exit criterion 3: 10-edit historical retrieval, exact-`t` tie, stored-shard-unchanged, repeatable reconstruction.
- `tests/revision/test_get_shard_at_properties.py` (created) - Hypothesis 1000-example reverse-replay invariants.

## Decisions Made

- **ShardStore as a `runtime_checkable` `typing.Protocol`** over a plain dict — the minimal D-02 seam; Phase 13 supplies a persistent implementation behind the identical async signature.
- **`canonical_content_hash` hashes the full snapshot** (including `transaction_time`), per RESEARCH A2 / D-05 "over the pre-edit shard" — content-only exclusion is a trivial future `exclude=` change if ever wanted.
- **`get_shard_at` returns `None`** (not a raise) for unknown IRI and `t < extracted_at` — the unambiguous D-09/A3 choice.
- **Transactional append+assign with rollback** in `edit_shard_content` so a `set_field` failure (e.g. an attempt at a frozen leaf that slipped the gate) never leaves a dangling audit record.

## Deviations from Plan

None - plan executed exactly as written.

The only mechanical note: `get_shard_at` (named in Task 2) was defined in Task 1's `content_edit.py` so the package `__init__` could export both write-path and read-path functions without a lazy import — exactly as the plan's Task 1 action permitted ("define both functions in content_edit.py so the export works"). Task 2's commit is therefore `test(...)` (durable tests + fixture for the already-shipped impl), consistent with the plan's TDD structure.

## Issues Encountered

- **Fixture checkpoint expectation corrected during Task 2 GREEN (test-data only, not a logic bug):** my first `ten_edit_history` "between edit 5 and 6" checkpoint used `edit_times[5].replace(day=15)` (July 15), which lands *after* edit 6 (July 1), so `get_shard_at` correctly returned the post-edit-6 value while the expectation table still claimed the pre-edit-6 value. The reconstruction was right; the checkpoint `t` was wrong. Fixed by using explicit between-edit dates (June 15 between edits 5/6; Aug 15 between edits 7/8). No change to `get_shard_at`.
- **Hypothesis property test event-loop conflict:** the `@given` test function must be sync (Hypothesis requirement), so driving async `store.put` via `asyncio.get_event_loop().run_until_complete()` inside the builder collided with a running loop. Resolved by populating the in-memory store synchronously (`store._d[iri] = shard`) in the loop-agnostic builder and owning a single fresh `asyncio.new_event_loop()` (closed in `finally`) for the assertion block. 1000 examples pass.
- **Pre-existing, out-of-scope collection error (carried from 05-01):** `tests/test_*_api.py` fail to import `fastapi` (dev dep absent), which blocks the bare `uv run pytest -m shards` collection. Per the scope-boundary rule and the phase constraint, NOT fixed; verification was scoped to `tests/shards tests/revision` (188 passed). Logged for visibility.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **Ready for Plan 05-03** (SHACL guard): `revision/__init__.py` deliberately does NOT re-export `validate_content_edit_shape` and `tests/revision/__init__.py` + `conftest.py` exist, so Plan 03 can drop `revision/shape_validation.py` + `revision/content_edit_shape.ttl` + `tests/revision/test_forward_only_validator.py` + `tests/revision/test_shacl_forward_only.py` in place with no edits to this plan's files.
- **Phase 6 seams open:** `sign_attestation` (unsigned stub) + `canonical_content_hash` (the JCS swap point) + the unused `signing_key` parameter are ready for real ed25519/JCS. `editor_did` is captured but not verified (V4 partial — documented deferred gap, T-05-10 accepted).
- **Phase 13 seam open:** `ShardStore` Protocol + `InMemoryShardStore` is the by-IRI persistence seam Oxigraph fills.
- **Deferred (accepted threats):** T-05-08 (unbounded reverse-replay chain — in-memory, single-process; Phase 13 re-evaluates), T-05-09 (placeholder signature — Phase 6), T-05-10 (unverified editor_did — Phase 6).

## Self-Check: PASSED

- Created files exist: all 9 (`revision/__init__.py`, `store.py`, `content_edit.py`; `tests/revision/__init__.py`, `conftest.py`, `test_immutable_gate.py`, `test_edit_shard_content.py`, `test_get_shard_at.py`, `test_get_shard_at_properties.py`) — FOUND
- Task commits exist: `9d05698`, `75befed` — both FOUND in git log
- Plan verification: `uv run pytest tests/revision -q` → 41 passed; `uv run pytest tests/shards tests/revision -q` → 188 passed; `uv run python -c "import folio_insights.revision"` → exit 0
- Acceptance criteria: Task 1 (edit_shard_content def, IMMUTABLE_FIELD_PATHS membership, InMemoryShardStore class, no storage-lib imports, gate + write-path tests green) and Task 2 (get_shard_at + model_copy(deep=True) present, 10-edit fixture test green, 1000-example property test green) — all verified PASS

---
*Phase: 05-content-versioning-6-4*
*Completed: 2026-05-27*
