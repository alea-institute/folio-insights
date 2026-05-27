---
phase: 05-content-versioning-6-4
verified: 2026-05-27T18:00:00Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
---

# Phase 5: Content Versioning (§6.4) Verification Report

**Phase Goal:** Ship the append-only `ContentEdit` chain and `get_shard_at(iri, t)` historical retrieval under immutable shard IRIs.
**Verified:** 2026-05-27T18:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `tests/shards/test_content_edit_audit_append_only.py` is green (exit criterion 1) | VERIFIED | `uv run pytest tests/shards/test_content_edit_audit_append_only.py -q` → 4 passed |
| 2 | SHACL guard rejects edits to past versions — `validate_content_edit_shape()` + `test_shacl_forward_only.py` both-polarity test passes (exit criterion 2) | VERIFIED | `uv run pytest tests/revision/test_shacl_forward_only.py -q` → 3 passed; ordered chain conforms=True, back-dated chain conforms=False confirmed |
| 3 | `get_shard_at(iri, t)` returns correct historical state across a 10-edit fixture (exit criterion 3) | VERIFIED | `uv run pytest tests/revision/test_get_shard_at.py -q` → 9 passed including exact-t tie and stored-shard-unchanged assertions |
| 4 | `shards/` package imports zero RDF/storage libs (dep-leak guard green) | VERIFIED | `uv run pytest tests/shards/test_dep_leak_guard.py -q` → 5 passed |
| 5 | All 218 combined `tests/shards` + `tests/revision` tests pass | VERIFIED | `uv run pytest tests/shards tests/revision -q` → 218 passed, 1 warning (benign Pydantic serializer warning from deliberate wrong-type test) |
| 6 | Code-review critical and warning findings (CR-01, CR-02, WR-01, WR-02, WR-03) fixed with regression tests | VERIFIED | Commits 97ee055 (CR-02), 616a576 (WR-02), d87f5c6 (CR-01+WR-03), 327d082 (WR-01) all present in git log; fixes confirmed in source |
| 7 | SHARD-09 requirement satisfied: ContentEdit chain, SHACL guard, `get_shard_at` all delivered | VERIFIED | All three acceptance-column tests from REQUIREMENTS.md SHARD-09 pass; three plan files all declare `requirements: [SHARD-09]` |

**Score:** 7/7 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/folio_insights/shards/audit.py` | Enriched ContentEdit (field_path/rationale/signature) + migrated add_edit with WR-01 rollback | VERIFIED | `field_path: str`, `rationale: str`, `signature: AttestedSignature` present; `frozen=True`+`extra="forbid"` preserved; WR-01 try/except rollback at line 140-143 |
| `src/folio_insights/shards/envelope.py` | Forward-only @model_validator on ShardEnvelope | VERIFIED | `@model_validator(mode="after")` + `_content_edits_forward_only` at lines 212-213; strict `<` comparison, equal timestamps allowed |
| `tests/shards/test_content_edit_audit_append_only.py` | Exit-criterion-1 acceptance test (4+ tests) | VERIFIED | File exists; `pytestmark = pytest.mark.shards`; 4 tests (append-revalidate, frozen entry, back-dated reject, reorder reject) |
| `src/folio_insights/revision/content_edit.py` | `edit_shard_content`, `get_shard_at`, `get_field`, `set_field`, `IMMUTABLE_FIELD_PATHS`, `canonical_content_hash`, `sign_attestation`, `validate_shard` | VERIFIED | All 8 symbols present and exported; `async def edit_shard_content(` and `async def get_shard_at(` confirmed; 10-member `IMMUTABLE_FIELD_PATHS` frozenset confirmed; `model_copy(deep=True)` in both `edit_shard_content` (CR-01) and `get_shard_at` |
| `src/folio_insights/revision/store.py` | `ShardStore` Protocol + `InMemoryShardStore` | VERIFIED | `class InMemoryShardStore` present; stdlib+Pydantic only (no aiosqlite/pyoxigraph) |
| `src/folio_insights/revision/__init__.py` | Public re-exports + `__all__` | VERIFIED | File exists; all required symbols re-exported |
| `src/folio_insights/revision/content_edit_shape.ttl` | Forward-only sh:sparql NodeShape with FILTER(?ct < ?pt) | VERIFIED | File exists; `sh:sparql` present; `FILTER(?ct < ?pt)` load-bearing polarity confirmed; full SPARQL self-join over adjacent fi:seq pairs |
| `src/folio_insights/revision/shape_validation.py` | `validate_content_edit_shape()` with `pyshacl.validate(` | VERIFIED | `def validate_content_edit_shape(` and `pyshacl.validate(` present; `_build_edit_graph` emits minimal local RDF (no Phase-13 store dependency); `ValidationResult` dataclass mirroring `shacl_validator.py` |
| `tests/revision/test_get_shard_at.py` | 10-edit fixture historical-retrieval test (exit criterion 3) | VERIFIED | File exists; `pytestmark = pytest.mark.shards`; 9 tests green including exact-t tie and stored-shard-unchanged |
| `tests/revision/test_shacl_forward_only.py` | Both-polarity SHACL guard test (exit criterion 2) | VERIFIED | 3 tests: ordered conforms=True, back-dated conforms=False, empty chain conforms; negative polarity uses `model_construct` to bypass Pydantic validator (correct — tests the out-of-band-record case) |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `revision/content_edit.py` | `ShardStore.get` / `.put` | `await store.get(shard_iri)` / `await store.put(shard_iri, validated)` | WIRED | Lines 280, 326 confirmed; working copy pattern (CR-01 fix) routes PUT to validated result (WR-03 fix) |
| `revision/content_edit.py` | stored shard isolation in `get_shard_at` | `model_copy(deep=True)` | WIRED | Line 365 confirmed; reversed-edit loop operates on `working` not the stored object |
| `revision/content_edit.py` | `ContentEdit` (enriched) | `from folio_insights.shards import AttestedSignature, ContentEdit, ShardEnvelope` | WIRED | Import at line 36 confirmed |
| `revision/shape_validation.py` | `pyshacl.validate` | `pyshacl.validate(data_graph, shacl_graph=shapes, inference="none", abort_on_first=False)` | WIRED | Line 116-121 confirmed; mirrors `services/shacl_validator.py` call exactly |
| `revision/shape_validation.py` | `content_edit_shape.ttl` | `Graph().parse(..., format="turtle")` | WIRED | `_SHAPE_PATH = Path(__file__).parent / "content_edit_shape.ttl"` at line 54; `shapes.parse(str(_SHAPE_PATH), format="turtle")` at line 112 |
| `envelope.py` | `content_edits` monotonicity | `@model_validator(mode="after")` | WIRED | Validator at line 212 iterates `zip(self.content_edits, self.content_edits[1:])` and raises on strict `<` |
| `audit.py` | `ShardEnvelope.content_edits` forward-ref | `ShardEnvelope.model_rebuild()` | WIRED | Preserved at line 155 as required |

---

### Data-Flow Trace (Level 4)

These are logic/algorithmic modules, not UI components rendering dynamic data — Level 4 not applicable.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `canonical_content_hash` is deterministic (CR-02 fix) | Regression tests in `test_edit_shard_content.py` (two instances identical content → same hash) | 70 revision tests pass | PASS |
| Store not corrupted after post-edit validation failure (CR-01 fix) | Regression tests in `test_edit_shard_content.py` | 70 revision tests pass | PASS |
| `add_edit` leaves no phantom entry on frozen-field failure (WR-01 fix) | Regression tests in `test_audit_log.py` | 148 shards tests pass | PASS |
| `get_field`/`set_field` reject non-declared paths (WR-02 fix) | Regression tests in `test_edit_shard_content.py` | 70 revision tests pass | PASS |
| `IMMUTABLE_FIELD_PATHS` membership (10 members, triple.object absent) | `uv run python -c "from folio_insights.revision import IMMUTABLE_FIELD_PATHS as S; assert {'triple.subject','triple.predicate','content_edits','signatures','shard_iri','provenance_hash','source_uri','source_span','extracted_at','first_extractor_did'} <= S and 'triple.object' not in S"` | exit 0 | PASS |

---

### Probe Execution

No explicit probes declared; exit criteria verified directly via pytest.

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| Exit criterion 1 | `uv run pytest tests/shards/test_content_edit_audit_append_only.py -q` | 4 passed | PASS |
| Exit criterion 2 | `uv run pytest tests/revision/test_shacl_forward_only.py -q` | 3 passed | PASS |
| Exit criterion 3 | `uv run pytest tests/revision/test_get_shard_at.py -q` | 9 passed | PASS |
| Dep-leak guard | `uv run pytest tests/shards/test_dep_leak_guard.py -q` | 5 passed | PASS |
| Combined suite | `uv run pytest tests/shards tests/revision -q` | 218 passed | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SHARD-09 | Plans 05-01, 05-02, 05-03 | Content versioning via append-only `ContentEdit` chain under immutable shard IRI; `get_shard_at(iri, t)` retrieves historical state | SATISFIED | All three REQUIREMENTS.md acceptance criteria met: (1) `test_content_edit_audit_append_only.py` green, (2) SHACL guard rejects edits to past versions, (3) `get_shard_at` correct across 10-edit fixture |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `revision/content_edit.py` | 208 | `"placeholder"` in docstring | Info | Expected — this is the accepted D-05 stub for Phase 6 ed25519 signing. `signature=""` is unmistakably unsigned; tests assert it. Not a blocker. |

No `TBD`, `FIXME`, or `XXX` markers found in any Phase 5 modified file. The one "placeholder" mention is in the docstring of `sign_attestation` describing the intentionally-accepted Phase-6 stub, which is documented in the threat model (T-05-03 accepted) and tested to be obviously unsigned.

---

### Code-Review Finding Closure

The code review (05-REVIEW.md) identified 2 Critical + 3 Warning findings. All five are confirmed fixed:

| Finding | Commit | Fix Description | Regression Test |
|---------|--------|-----------------|-----------------|
| CR-01: store corruption when `validate_shard` raises after `set_field` | d87f5c6 | `edit_shard_content` now operates on `model_copy(deep=True)` of the stored shard; `store.put` only reached on full success | `test_edit_shard_content.py`: failed validation leaves stored shard unmutated with zero new edits |
| CR-02: `canonical_content_hash` non-deterministic across instances (`transaction_time` leaked) | 97ee055 | `_HASH_EXCLUDED_FIELDS` frozenset excludes `transaction_time`, `valid_time_start`, `valid_time_end`, `content_edits`, `signatures` | `test_edit_shard_content.py`: two instances from identical content at different wall-clock times hash identically |
| WR-01: phantom audit entry in `add_edit` when `setattr` raises | 327d082 | `add_edit` wraps `setattr` in try/except; pops the just-appended edit on failure | `test_audit_log.py`: failed `add_edit` on frozen field leaves `content_edits` unchanged |
| WR-02: `get_field`/`set_field` accept arbitrary attribute paths | 616a576 | `_validate_field_path` validates each dotted-path segment against `model_fields` BEFORE any attribute access | `test_edit_shard_content.py`: non-declared paths (`__class__`, `model_fields`) raise with no audit record written |
| WR-03: `validate_shard` return value discarded | d87f5c6 | `validated = validate_shard(working)` captured; `store.put(shard_iri, validated)` stores the validated copy | `test_edit_shard_content.py`: successful edit stores a fresh validated copy, not the original reference |

---

### Human Verification Required

None. All phase-5 behaviors are programmatically verifiable (append-only logic, SHACL guard, reverse-replay algorithm, store isolation). No visual, real-time, or external-service behavior to assess.

---

### Gaps Summary

No gaps found. All three exit criteria pass, all PLAN must-haves are VERIFIED, SHARD-09 is satisfied, all code-review findings are fixed with regression tests, and the dep-leak boundary is clean.

**Intentionally deferred items (not gaps):**
- Real ed25519/JCS signing — Phase 6 (DID Substrate); `sign_attestation` returns an accepted placeholder stub
- Persistent Oxigraph storage — Phase 13; `InMemoryShardStore` is the correct Phase 5 seam
- Full SHACL-Hybrid shape suite + Pydantic-to-SHACL generator — Phase 11; Phase 5 ships the one focused content-edit shape its exit criterion requires

---

_Verified: 2026-05-27T18:00:00Z_
_Verifier: Claude (gsd-verifier)_
