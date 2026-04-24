---
phase: 02-shard-envelope
plan: 01
subsystem: data-model
tags: [shards, envelope, pydantic, bitemporal, discriminated-union, provenance-hash, nfc, sha256, rfc3986, urn]

# Dependency graph
requires:
  - phase: 00-foundations-hard-gate
    provides: pyoxigraph 0.5.7 pin, RDF 1.2 substrate decision, pydantic 2.7+ version floor
  - phase: 01-polysemy-distinguo-spike
    provides: Pydantic ConfigDict(extra="forbid") + Literal-tag sibling-class patterns (from dispositions.py + distinguo.py + detector.py)
provides:
  - 15-field ShardEnvelope Pydantic model (PRD §6.1)
  - 6 per-field frozen identity-and-origin fields (D-07)
  - Bitemporal triplet (valid_time_start / valid_time_end / transaction_time) with tz-aware UTC defaults (D-03 / D-04 / D-12)
  - 5 subtype stub classes (SimpleAssertion, DisputedProposition, ConflictingAuthorities, Gloss, Hypothesis)
  - Shard discriminated-union TypeAlias (D-05)
  - Pure deterministic mint_shard_iri(source_uri, source_span) function (D-01 / D-02)
  - urn:folio:shard/ IRI prefix constant (supersedes PRD §6.3 draft https:// form)
  - AttestedSignature permissive Phase 6 stub + Triple model
  - shards/__init__.py public surface (11 symbols)
affects:
  - 02-02 (ContentEdit — will model_rebuild() the forward string-ref to ContentEdit on ShardEnvelope)
  - 02-03 (tests — round-trip, discriminated-union routing, frozen-assignment regression, hypothesis determinism property, grep-guard dep-leak regression)
  - Phase 3 (Shard subtypes — each subtype stub gets its PRD §6.2 fields added)
  - Phase 4 (IRI collision detection — re-hash verification job imports mint_shard_iri and compares full 64-hex provenance_hash)
  - Phase 5 (forward-only ContentEdit SHACL gate — extends add_edit with edited_at >= transaction_time)
  - Phase 6 (DID substrate — replaces AttestedSignature stub)
  - Phase 7 (supersession governance — supersedes / superseded_by chain enforcement)
  - Phase 11 (SHACL hybrid validation — Pydantic-generated base shapes + hand-written advanced)
  - Phase 13 (Oxigraph storage — bitemporal SPARQL semantics treats null_start as −∞ and null_end as +∞)

# Tech tracking
tech-stack:
  added: []  # pure-Pydantic + stdlib; no new project dependencies introduced
  patterns:
    - "Per-field Field(frozen=True) for selective immutability (Pydantic 2.7+; raises ValidationError with type='frozen_field' on assignment)"
    - "Annotated[Union[...], Field(discriminator='...')] discriminated-union TypeAlias for sibling-class routing"
    - "Pinned-Literal-default subtype pattern (shard_type: Literal['tag'] = 'tag') — sibling-class Literal-tag sibling to detector.py's RuleVerdict / LLMVerdict"
    - "Deterministic pure-function minting with NFC + LF + trim + RFC 3986 normalization"
    - "Forward-string-ref for cross-module circular-import avoidance (list['ContentEdit'] resolved by Plan 02-02's model_rebuild())"
    - "urn: scheme for location-independent identifiers (urn:folio:shard/<hex16>)"

key-files:
  created:
    - src/folio_insights/shards/__init__.py
    - src/folio_insights/shards/envelope.py
    - src/folio_insights/shards/subtypes.py
    - src/folio_insights/shards/minting.py
  modified: []

key-decisions:
  - "ShardType Literal declared once in envelope.py and re-exported via __init__.py; downstream code imports the alias rather than re-declaring string literals (drift prevention)"
  - "ShardEnvelope uses per-field Field(frozen=True) on exactly 6 identity fields (D-07), not model-level ConfigDict(frozen=True); mutable-with-audit fields stay assignable so Plan 02-02's add_edit() helper can run without per-call model_copy ceremony"
  - "AttestedSignature shipped with ConfigDict(extra='allow') — Phase 6 will replace the model, and permissive construction keeps Plan 02-03 round-trip tests green against the future Phase 6 shape"
  - "content_edits declared as list['ContentEdit'] forward string-ref; Plan 02-02 audit.py calls ShardEnvelope.model_rebuild() at module bottom to wire the reference (avoids circular import at shards package load time)"
  - "urn:folio:shard/ prefix (D-02) chosen over PRD §6.3 draft https:// form; URN scheme is location-independent and survives infrastructure moves without breaking provenance-hash identity"
  - "mint_shard_iri shipped as a module-level standalone function (not a classmethod on ShardEnvelope) — mirrors polysemy/reviewer.py ensure_reviewer_did pattern and lets Phase 4's re-hash job call it without needing a ShardEnvelope instance"

patterns-established:
  - "shards/ package-per-subsystem layout (mirrors polysemy/) — 4 files: __init__.py + envelope.py + subtypes.py + minting.py, no flat core/shards.py"
  - "Grep-verifiable acceptance: plan acceptance criteria are mechanical (grep counts, grep-F literal matches, regex backrefs) rather than semantic — catches regressions at CI time without needing Pydantic introspection"
  - "Docstring discipline: plain-prose references to storage-library names (pyoxigraph, rdflib) are rephrased so they never match the `^import (...)` grep — prevents docstring mentions from tripping Phase 13 dep-leak guards"
  - "`from __future__ import annotations` at top of every module (D-10) — required by Pydantic 2.x forward-ref resolution for the content_edits string-ref and the discriminated-union Annotated[Union[...]] wiring"

requirements-completed: [SHARD-01, SHARD-10]

# Metrics
duration: ~15min
completed: 2026-04-24
---

# Phase 02 Plan 01: Shard Envelope Core Summary

**15-field ShardEnvelope Pydantic model + 5 subtype stubs with discriminated-union Shard alias + deterministic urn:folio:shard/ minter — locks the v2.0 core data-model contract every downstream phase (3–16) binds against.**

## Performance

- **Duration:** ~15 min (base-reset + 4 file reads + 3 files written + 3 atomic commits; commit-span alone was ~2.5 min)
- **Started:** 2026-04-24T20:42Z (approx. — executor spawn)
- **Completed:** 2026-04-24T20:56Z
- **Tasks:** 3 / 3 complete
- **Files created:** 4 (envelope.py, subtypes.py, minting.py, __init__.py)
- **Files modified:** 0

## Accomplishments

- **ShardEnvelope (envelope.py, 218 lines)** — 15 PRD §6.1 fields + 6 per-field-frozen identity fields + bitemporal triplet + supersession link pair + contest state, all with ConfigDict(extra="forbid"). ShardType Literal alias, AttestedSignature Phase 6 stub, Triple sub-model all shipped.
- **5 subtype stubs + Shard discriminated union (subtypes.py, 55 lines)** — SimpleAssertionShard / DisputedPropositionShard / ConflictingAuthoritiesShard / GlossShard / HypothesisShard, each pinning its Literal default on shard_type. Shard = Annotated[Union[...], Field(discriminator="shard_type")] constructs cleanly via TypeAdapter.
- **mint_shard_iri (minting.py, 68 lines)** — deterministic pure function implementing the D-02 recipe: NFC(rfc3986(uri)) + "\n" + NFC(span).strip() → SHA-256 → urn:folio:shard/<hex16>. Smoke tests verify determinism, NFC vs NFD equivalence, RFC 3986 case/trailing-slash normalization, CRLF trim, and exact IRI/hash sizes.
- **Package surface (__init__.py, 30 lines)** — 11 public symbols re-exported in alphabetical __all__ order. `from folio_insights.shards import ShardEnvelope, Shard, mint_shard_iri, ...` works.
- **Phase-13 dep-leak boundary established** — no pyoxigraph / rdflib / oxrdflib / owlready2 imports anywhere under src/folio_insights/shards/. Plan 02-03 will ship a grep-guard regression test to keep it that way.

## Task Commits

Each task was committed atomically on the worktree branch:

1. **Task 1: ShardEnvelope 15-field model + package init** — `8982d8c` (feat)
2. **Task 2: 5 Shard subtype stubs + discriminated-union alias** — `2649dc3` (feat)
3. **Task 3: Deterministic mint_shard_iri() provenance-hash minter** — `00defe7` (feat)

(No SUMMARY metadata commit — orchestrator owns the final wave-level commit per parallel-executor protocol.)

## Files Created/Modified

- `src/folio_insights/shards/__init__.py` (30 lines) — package marker + public re-exports: AttestedSignature, ConflictingAuthoritiesShard, DisputedPropositionShard, GlossShard, HypothesisShard, mint_shard_iri, Shard, ShardEnvelope, ShardType, SimpleAssertionShard, Triple (11 symbols, alphabetical __all__).
- `src/folio_insights/shards/envelope.py` (218 lines) — ShardEnvelope (15 §6.1 fields + 6 identity + bitemporal + supersession + contest), ShardType Literal alias, AttestedSignature Phase 6 stub (extra="allow"), Triple (extra="forbid"). Per-field frozen on shard_iri, provenance_hash, source_uri, source_span, extracted_at, first_extractor_did (exactly 6).
- `src/folio_insights/shards/subtypes.py` (55 lines) — 5 subtype classes inheriting ShardEnvelope, each with shard_type: Literal["<tag>"] = "<tag>". Shard = Annotated[Union[...5...], Field(discriminator="shard_type")]. No subtype-specific fields (Phase 3 scope).
- `src/folio_insights/shards/minting.py` (68 lines) — mint_shard_iri(source_uri, source_span) → tuple[str, str]; private _normalize_uri (RFC 3986) and _normalize_span (NFC + strip) helpers; _IRI_PREFIX = "urn:folio:shard/" and _IRI_HEX_LEN = 16 constants.

**LOC total:** 371 lines (within plan estimate of 200-260; overshoot is from generous module-header docstrings explaining locked decisions — acceptable).

## Decisions Made

None new — plan executed exactly as written. All decisions flowed from locked CONTEXT D-01..D-12.

Implementation choices that followed the plan's "Claude's discretion" permissions:
- Module layout: `src/folio_insights/shards/` package (per 02-PATTERNS.md), not `core/shards.py`.
- `mint_shard_iri` as a module-level standalone function (per 02-PATTERNS.md), not a classmethod.
- Subtype classes declared in PRD §6.2 order (SimpleAssertion → Hypothesis); `__all__` alphabetical per 02-PATTERNS.md.
- No `@model_validator` in Plan 02-01 — cross-field invariants (e.g., `supersedes != shard_iri`) deferred to Plan 02-03 tests or Phase 5.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Module docstring text broke acceptance grep**
- **Found during:** Task 1 (ShardEnvelope + envelope.py smoke test)
- **Issue:** My initial docstring contained the literal phrases "use per-field `Field(frozen=True)`" (in 2 places) and "Phase 2 does NOT import pyoxigraph, rdflib, oxrdflib, or owlready2". The first broke the plan's strict acceptance `grep -cE 'frozen=True' envelope.py == 6` (returned 8 with docstring hits). The second broke `! grep -E 'import (pyoxigraph|rdflib|oxrdflib|owlready2)' envelope.py` because the substring "import pyoxigraph" appeared inside the prose "NOT import pyoxigraph".
- **Fix:** Rephrased docstring prose to avoid the exact tokens: "per-field freeze via `Field(frozen=...)`" instead of "`Field(frozen=True)`"; "This module is pure-Pydantic + stdlib: no storage-layer libraries are pulled in at Phase 2" instead of listing the storage library names after the word "import". Field declarations themselves kept the exact `Field(frozen=True)` syntax. Semantics unchanged; grep acceptance now passes at exactly 6 matches and clean on storage-imports.
- **Files modified:** `src/folio_insights/shards/envelope.py`
- **Verification:** `grep -cE 'frozen=True' envelope.py` → `6`; `grep -E 'import (pyoxigraph|rdflib|oxrdflib|owlready2)' envelope.py` → exit 1 (no match).
- **Committed in:** `8982d8c` (Task 1 commit, pre-commit fix-up during task execution)

**2. [Rule 3 - Blocking] Legacy PRD prefix mentioned in minting.py docstring tripped cross-cutting grep guard**
- **Found during:** Task 3 (minting.py post-write verification)
- **Issue:** My first-draft docstring included the literal substring `https://folio-insights.aleainstitute.ai/shard/<hex16>` as a pointer to the superseded PRD §6.3 prefix. The plan's cross-cutting verification `! grep -F 'folio-insights.aleainstitute.ai/shard' src/folio_insights/shards/` is a fixed-string search that matches docstring prose, not just IRI-generating code.
- **Fix:** Rephrased the deprecation note to describe the prefix without the literal domain substring: "PRD §6.3 L547-551 originally specified an `https://` (aleainstitute domain) prefix ... CONTEXT D-02 supersedes that with `urn:folio:shard/`". Semantically equivalent — reviewers still see that the PRD form is superseded; grep guard now passes.
- **Files modified:** `src/folio_insights/shards/minting.py`
- **Verification:** `grep -rF 'folio-insights.aleainstitute.ai/shard' src/folio_insights/shards/` → exit 1 (no match).
- **Committed in:** `00defe7` (Task 3 commit, pre-commit fix-up during task execution)

---

**Total deviations:** 2 auto-fixed (both Rule 3 — blocking acceptance grep; docstring prose vs. mechanical literal-string matchers).
**Impact on plan:** No scope change, no behavioral change. Both fixes are docstring wording adjustments that preserve semantics while satisfying the plan's mechanical grep acceptance gates. Lesson carried forward: for plans whose acceptance is grep-based (fixed-string or regex-without-context), docstring prose must avoid the exact-token sequences the acceptance patterns search for.

## Issues Encountered

- **Worktree base commit mismatch at executor startup** — the worktree branch was based on `3719d3dc` (master HEAD) rather than the wave base `475bc14f`. Hard-reset to `475bc14f` per the worktree_branch_check protocol; no files lost (fresh worktree, no user changes).
- **No .venv in worktree** — the worktree doesn't ship its own `.venv`. Resolved by using `/home/damienriehl/Coding Projects/folio-insights/.venv/bin/python` with `PYTHONPATH=src` prefix pointing to the worktree's `src/` to preempt the project-root editable install. Pydantic 2.13.3 + Python 3.12.12 confirmed (both satisfy the D-09 `pydantic>=2.7.0` + project `>=3.11,<3.13` requirements).
- **`__init__.py` imports minting and subtypes (not yet written) during Task 1** — Task 1's `<files>` includes both envelope.py AND __init__.py, but __init__.py can't be imported until Tasks 2+3 also land. Resolved by using `importlib.util.spec_from_file_location` to load envelope.py directly for Task 1 smoke testing, and running the full package-level import verification after all 3 tasks committed. The plan itself anticipates this: Task 1's `acceptance_criteria` for the package-level __all__ check explicitly notes "this runs AFTER Task 2 and Task 3 land".

## Known Stubs

Plan 02-01 intentionally ships stubs that will be wired up in later plans/phases. These are tracked so the verifier does not flag them as missing functionality:

| Stub | File | Reason | Resolved by |
|------|------|--------|-------------|
| `list["ContentEdit"]` forward string-ref | `envelope.py:L187` | Avoids circular import at package load; real `ContentEdit` model lives in Plan 02-02 `shards/audit.py` | Plan 02-02 (same phase, Wave 2); Plan 02-02 calls `ShardEnvelope.model_rebuild()` at its module bottom |
| 5 subtype classes have no subtype-specific fields | `subtypes.py:L11-35` | Plan 02-01 ships stubs for the discriminated-union topology only; PRD §6.2 subtype bodies are Phase 3 scope | Phase 3 (Shard Subtypes — utrum / objections / sed_contra / sic / non / glosses / generation_method / ttl_days per PRD §6.2.1-6.2.5) |
| `AttestedSignature` permissive placeholder (`ConfigDict(extra="allow")`) | `envelope.py:L48-65` | Phase 6 DID substrate will REPLACE (not extend) this model with signature-verification machinery | Phase 6 (DID substrate + signature verification + `did_doc_snapshot_at` archival) |
| No forward-only edit-gate / SHACL validation on `content_edits` | `envelope.py:L187` | D-08 explicitly defers: "Phase 5 wires the forward-only SHACL gate"; Plan 02-01 leaves `content_edits` mutable append-only | Plan 02-03 (round-trip/frozen tests); Phase 5 (forward-only SHACL validator) |
| No collision detection / re-hash verification on `mint_shard_iri` | `minting.py:L49-66` | D-01 locks: "Phase 4 narrows to collision detection + nightly re-hash verification job" | Phase 4 (IRI Scheme — reads `provenance_hash` full 64-hex and compares on first-16 prefix collisions) |
| No hypothesis property test over `mint_shard_iri` | n/a | Plan 02-01 ships smoke tests inline (via `python -c`); the 1000-example hypothesis property test is Plan 02-03's `test_minting_determinism.py` | Plan 02-03 (same phase, Wave 3) — adds `hypothesis>=6.100` to `[dev]` deps + property test |

None of these stubs prevents Plan 02-01 from meeting its stated goal (lock the envelope + subtype topology + minting recipe).

## User Setup Required

None — no external service configuration required. Phase 2 is pure in-memory Pydantic + stdlib.

## Next Phase Readiness

**Ready for Plan 02-02** (wave 2): `ContentEdit` sub-model + `add_edit(shard, field_name, new_value, editor_did)` helper + `ShardEnvelope.model_rebuild()` at audit.py module bottom to wire the forward string-ref. Plan 02-02 will also update `shards/__init__.py` to append `ContentEdit` and `add_edit` to the re-exports and `__all__`. The frozen-field contract from D-07 means `add_edit` will raise `ValidationError(type="frozen_field")` if called on one of the 6 identity fields — Plan 02-02's behavior, guaranteed today by envelope.py.

**Ready for Plan 02-03** (wave 3): Round-trip + discriminated-union + frozen-assignment + bitemporal + audit-append + `hypothesis` determinism + grep-guard dep-leak regression tests. All 11 symbols in the `shards/` public surface are importable today.

**Ready for Phase 3** (Shard subtypes): Each of the 5 subtype stubs is the extension point where PRD §6.2 subtype-specific fields attach. The `shard_type: Literal["..."] = "..."` pin stays — Phase 3 adds fields underneath without touching the Literal.

**Ready for Phase 4** (IRI collision detection): `mint_shard_iri` is a pure function (no I/O, no wall-clock, no platform-dependent line endings); Phase 4's nightly re-hash job imports and re-invokes for verification. The full 64-hex `provenance_hash` is stored on `ShardEnvelope` so Phase 4 can detect 16-hex-prefix collisions by comparing full hashes.

**No blockers.** Orchestrator owns STATE.md / ROADMAP.md updates for the wave.

## 11 Public Symbols Re-exported (Plan 02-01)

For Plan 02-02's follow-on `__init__.py` update (appends `ContentEdit` + `add_edit` → 13 symbols):

1. `AttestedSignature`
2. `ConflictingAuthoritiesShard`
3. `DisputedPropositionShard`
4. `GlossShard`
5. `HypothesisShard`
6. `mint_shard_iri`
7. `Shard`
8. `ShardEnvelope`
9. `ShardType`
10. `SimpleAssertionShard`
11. `Triple`

## Self-Check

Verifying all files and commits exist before returning to the orchestrator:

- [x] `src/folio_insights/shards/__init__.py` — FOUND (30 lines)
- [x] `src/folio_insights/shards/envelope.py` — FOUND (218 lines)
- [x] `src/folio_insights/shards/subtypes.py` — FOUND (55 lines)
- [x] `src/folio_insights/shards/minting.py` — FOUND (68 lines)
- [x] Task 1 commit `8982d8c` — FOUND in git log
- [x] Task 2 commit `2649dc3` — FOUND in git log
- [x] Task 3 commit `00defe7` — FOUND in git log
- [x] `grep -cE 'frozen=True' envelope.py` == 6 — VERIFIED
- [x] `TypeAdapter(Shard)` constructs — VERIFIED
- [x] `mint_shard_iri('urn:x:1','hello') == mint_shard_iri('urn:x:1','hello')` — VERIFIED
- [x] NFC vs NFD equivalence — VERIFIED
- [x] RFC 3986 case + trailing-slash normalization — VERIFIED
- [x] No `pyoxigraph|rdflib|oxrdflib|owlready2` imports under `shards/` — VERIFIED
- [x] No `folio-insights.aleainstitute.ai/shard` literal under `shards/` — VERIFIED

## Self-Check: PASSED

---
*Phase: 02-shard-envelope*
*Plan: 01 (wave 1)*
*Completed: 2026-04-24*
