---
phase: 02-shard-envelope
plan: 02
subsystem: data-model
tags: [shards, audit, content-edit, pydantic, frozen-submodel, model-rebuild, forward-ref, hypothesis, pytest-marker, pyproject]

# Dependency graph
requires:
  - phase: 02-shard-envelope
    plan: 01
    provides: ShardEnvelope 15-field model with content_edits forward-string-ref list["ContentEdit"], Triple, AttestedSignature, ShardType, 5 subtype stubs, mint_shard_iri, shards/__init__.py 11-symbol surface
  - phase: 01-polysemy-distinguo-spike
    provides: Pydantic ConfigDict(frozen=True, extra='forbid') pattern from distinguo.ForkProposal — the direct template for ContentEdit's end-to-end immutability config
provides:
  - ContentEdit frozen Pydantic sub-model (D-08 — 5 fields: field_name, old_value, new_value, edited_at, editor_did; model_config frozen=True + extra=forbid; audit records immutable once written)
  - add_edit(shard, field_name, new_value, editor_did) helper — D-08 get-then-append-then-setattr sequence; raises pydantic.ValidationError with type="frozen_field" on the 6 D-07 frozen identity fields
  - ShardEnvelope.model_rebuild() wire-up at audit.py module bottom — resolves Plan 02-01's forward string-ref list["ContentEdit"] so ShardEnvelope.model_fields['content_edits'].annotation.__args__[0] is the real ContentEdit class
  - shards/__init__.py 13-symbol public surface (Plan 02-01's 11 + ContentEdit + add_edit, alphabetical __all__)
  - pyproject.toml [project.optional-dependencies].dev gains hypothesis>=6.100 (first hypothesis adopter in the repo; Plan 02-03 consumes)
  - pyproject.toml [tool.pytest.ini_options].markers gains "shards: Phase 2 v2.0 Shard envelope tests" (Plan 02-03 declares pytestmark = pytest.mark.shards)
affects:
  - 02-03 (tests — round-trip/discriminated-union/frozen-assignment/bitemporal/audit-append/hypothesis-determinism/grep-guard all run against this surface; pytestmark = pytest.mark.shards requires the marker registered here)
  - Phase 5 (ContentEdit forward-only gate — extends add_edit with edited_at >= transaction_time validator + SHACL shape; hardens add_edit to transactional semantics so a frozen-field setattr raise rolls back the append)
  - Phase 6 (DID substrate — adds AttestedSignature signing over the ContentEdit's canonical hash, replacing the Phase 2 "editor_did as typed-string" stub)
  - Phase 11 (SHACL hybrid validation — generates base shapes over ContentEdit + append-only content_edits invariant)
  - Phase 13 (Oxigraph storage — serializes content_edits chain through RDF-12; bitemporal --as-of queries read the chain for point-in-time replay)

# Tech tracking
tech-stack:
  added:
    - "hypothesis>=6.100 (dev-only — installed hypothesis==6.152.2 + sortedcontainers==2.4.0 transitive; first hypothesis adopter in the repo per PATTERNS.md)"
  patterns:
    - "End-to-end frozen sub-model — ConfigDict(frozen=True, extra='forbid') mirrors Phase 1 distinguo.ForkProposal; distinct from ShardEnvelope's per-field Field(frozen=True) selective immutability"
    - "ShardEnvelope.model_rebuild() at audit.py module bottom (AFTER __all__) — resolves forward string-ref from envelope.py without circular import at package-load time"
    - "Helper-by-convention for mutable-with-audit writes (add_edit) — no override of __setattr__ on ShardEnvelope; callers are expected to go through the helper; Phase 5 adds SHACL enforcement"
    - "pytest-marker registration in pyproject.toml preserves chronological phase ordering (shards added AFTER polysemy_spike, not inserted alphabetically) — matches Phase 1 → Phase 2 reading order"

key-files:
  created:
    - src/folio_insights/shards/audit.py
  modified:
    - src/folio_insights/shards/__init__.py
    - pyproject.toml

key-decisions:
  - "ContentEdit.model_config is frozen=True at the MODEL level (not per-field) — audit records are wholly immutable once constructed, matching distinguo.ForkProposal. This is a deliberate contrast with ShardEnvelope's D-07 per-field freeze, which lets mutable-with-audit fields stay assignable for add_edit's setattr step."
  - "add_edit captures old_value via getattr BEFORE constructing the ContentEdit and BEFORE setattr — so the audit record is self-contained even if setattr raises. Phase 5 will harden this to full transactional semantics (roll back the append on setattr failure); Phase 2 ships the read-first sequence as the invariant carrier."
  - "ShardEnvelope.model_rebuild() placed AFTER `__all__` (module bottom) rather than inside a `if __name__ == ...` guard or a function — import-time side effect is intentional so any consumer that imports audit.py (directly or via shards/__init__.py) triggers the rebuild."
  - "hypothesis grouped with pytest-family deps in pyproject.toml (after pytest-benchmark, before dagger-io) rather than alphabetically inserted — readability-over-style; hypothesis is a testing-strategy tool, same family as pytest-timeout/benchmark/asyncio."
  - "shards pytest marker placed AFTER polysemy_spike (chronological phase order), not alphabetically — keeps the markers list easy to scan by project timeline."

patterns-established:
  - "Forward-ref + model_rebuild split across plans — Plan N declares list['T'] in envelope with a forward string-ref, Plan N+1 defines T and calls Parent.model_rebuild() at its own module bottom. Enables topological-order plan parallelism (planner/executor agents don't fight over envelope.py)."
  - "Module docstring brevity when acceptance is grep-based — Plan 02-01 learned this for 'Field(frozen=True)' and 'import pyoxigraph' grep-guards; Plan 02-02 reapplies for 'from __future__ at head -5' and 'field_name:/new_value:/editor_did: at ^\\s+ at 4-space indent only'. One-line module docstring + extended prose in block comments below keeps acceptance greps clean."
  - "Single-line def signature for multi-param helpers when per-param ^\\s+name: grep-count matters — def add_edit(shard, field_name, new_value, editor_did) -> None in one line avoids collision with ContentEdit's class-field grep."

requirements-completed: [SHARD-01]

# Metrics
duration: ~15min
completed: 2026-04-24
---

# Phase 02 Plan 02: ContentEdit + add_edit + model_rebuild Summary

**Frozen ContentEdit Pydantic sub-model + minimal add_edit(shard, field, new, did) helper + ShardEnvelope.model_rebuild() wire-up that resolves Plan 02-01's forward string-ref to ContentEdit, closing the Phase 2 production-code surface and unlocking Plan 02-03's test battery via the hypothesis dev dep + shards pytest marker.**

## Performance

- **Duration:** ~15 min (worktree base-reset + 4 file reads + 1 new file + 2 file edits + 2 atomic commits + SUMMARY)
- **Started:** 2026-04-24T20:50Z (approx. — executor spawn)
- **Completed:** 2026-04-24T21:04Z
- **Tasks:** 2 / 2 complete
- **Files created:** 1 (audit.py, 97 LOC)
- **Files modified:** 2 (__init__.py +3 LOC, pyproject.toml +2 LOC)

## Accomplishments

- **ContentEdit frozen sub-model (audit.py, 97 LOC)** — `class ContentEdit(BaseModel)` with `model_config = ConfigDict(frozen=True, extra="forbid")` and exactly the 5 D-08 fields (field_name, old_value, new_value: Any, edited_at: datetime, editor_did). Round-trips via `model_dump_json` / `model_validate_json`; assignment after construction raises `pydantic.ValidationError`; extra fields rejected at construction.
- **add_edit helper** — single-line def `add_edit(shard: ShardEnvelope, field_name: str, new_value: Any, editor_did: str) -> None` implementing the D-08 sequence: (1) capture `old_value = getattr(shard, field_name)`, (2) construct `ContentEdit(edited_at=datetime.now(UTC), ...)`, (3) append to `shard.content_edits`, (4) `setattr(shard, field_name, new_value)`. When `field_name` is one of the 6 D-07 frozen identity fields, step (4) raises `pydantic.ValidationError` with `type="frozen_field"` — the correct signal to the caller that edits to identity fields require a new shard via the supersedes-chain.
- **ShardEnvelope.model_rebuild() wire-up** — called at audit.py module bottom AFTER `__all__`. Resolves the forward string-ref `list["ContentEdit"]` that Plan 02-01 declared in envelope.py. Verified post-rebuild: `ShardEnvelope.model_fields['content_edits'].annotation.__args__[0] is ContentEdit` (not `ForwardRef("list['ContentEdit']")` anymore). **This is the "ref-ok" smoke check — passing.**
- **shards/__init__.py updated** — now re-exports `ContentEdit` + `add_edit` alongside Plan 02-01's 11 symbols; `__all__` contains exactly the 13 symbols in the approved alphabetical order.
- **pyproject.toml updated (+2 lines)** — `[project.optional-dependencies].dev` gains `"hypothesis>=6.100"` (grouped with pytest-family deps); `[tool.pytest.ini_options].markers` gains `"shards: Phase 2 v2.0 Shard envelope tests"` after `polysemy_spike` (chronological phase order). No other edits: runtime `[project].dependencies` untouched (pyoxigraph==0.5.7 still the single pin), requires-python `>=3.11,<3.13` unchanged, build-system / testpaths / other markers untouched.
- **hypothesis installed in project venv** — `hypothesis==6.152.2` (satisfies `>=6.100`) + `sortedcontainers==2.4.0` transitive. `./.venv/bin/pytest --markers` reports `@pytest.mark.shards: Phase 2 v2.0 Shard envelope tests` and all 6 pre-existing markers.
- **Phase-13 dep-leak boundary preserved** — `grep -rE 'import (pyoxigraph|rdflib|oxrdflib|owlready2)' src/folio_insights/shards/` still returns no hits.

## Task Commits

Each task was committed atomically on the worktree branch with `--no-verify` (parallel-executor hook contention avoidance):

1. **Task 1: ContentEdit + add_edit + model_rebuild wire-up + __init__.py 13-symbol surface** — `00a1d67` (feat)
2. **Task 2: pyproject.toml — hypothesis>=6.100 dev dep + shards pytest marker** — `2ec8739` (chore)

(No SUMMARY metadata commit — orchestrator owns the final wave-level commit per parallel-executor protocol.)

## Files Created/Modified

- `src/folio_insights/shards/audit.py` **(created, 97 lines)** — One-line module docstring + `from __future__ import annotations` (top-5 lines per grep acceptance) + block-comment D-08 design / Phase 5 deferrals / Phase 6 deferrals + `ContentEdit` frozen sub-model (5 fields) + `add_edit` single-line def + `__all__ = ["ContentEdit", "add_edit"]` + `ShardEnvelope.model_rebuild()` at module bottom.
- `src/folio_insights/shards/__init__.py` **(modified, 30 → 33 lines)** — Added `from folio_insights.shards.audit import ContentEdit, add_edit` import line; added `"add_edit"` and `"ContentEdit"` entries to `__all__` (alphabetical with lowercase-first convention). Now 13 symbols total.
- `pyproject.toml` **(modified, 62 → 63 lines visible; 2 insertions)** — `[project.optional-dependencies].dev` list gains `"hypothesis>=6.100",` after `"pytest-benchmark>=5.1",`; `[tool.pytest.ini_options].markers` list gains `"shards: Phase 2 v2.0 Shard envelope tests",` after `"polysemy_spike: Phase 1 polysemy-distinguo spike tests",`.

**LOC total added:** 102 lines of new/modified content (97 audit.py + 3 __init__.py + 2 pyproject.toml).

## Decisions Made

None new — plan executed exactly as written. All semantics flowed from locked CONTEXT D-07 / D-08 / D-09 / D-10 / D-11 / D-12 and from the plan's explicit `<interfaces>` block.

Style choices that followed the plan's "Claude's discretion" permissions:

- **Docstring layout:** One-line module docstring with extended D-08/Phase 5/Phase 6 commentary as block comments below `from __future__` — chosen to satisfy `head -5 audit.py | grep -F 'from __future__'` acceptance gate.
- **add_edit signature:** Single-line `def add_edit(shard, field_name, new_value, editor_did) -> None:` — chosen to avoid mechanical grep collision with ContentEdit's class-body field declarations on `^\s+name:` pattern.
- **model_rebuild placement:** Module bottom (after `__all__`) rather than at file-top-after-imports — matches the plan's `<interfaces>` template exactly and keeps the side-effect visible to reviewers.
- **hypothesis list position:** Grouped with pytest-family deps (after `pytest-benchmark>=5.1`, before `dagger-io>=0.14.0`) rather than alphabetically inserted — the plan explicitly permitted this ("grouping it with the other pytest-family deps is more readable than alphabetical insertion"), and it matches the chronological reading order of the `dev` list.
- **shards marker position:** AFTER `polysemy_spike` (chronological) rather than alphabetically inserted — plan-approved.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Long module docstring + multi-line `def add_edit` signature broke mechanical grep acceptance**

- **Found during:** Task 1 (initial acceptance-criteria run)
- **Issue:** My first draft had a ~30-line module docstring (literally the interfaces template's docstring prose) plus a multi-line `def add_edit(\n    shard: ShardEnvelope,\n    field_name: str,\n    ...\n)` signature. Two grep acceptance gates failed:
  - `head -5 src/folio_insights/shards/audit.py | grep -F 'from __future__ import annotations'` — FAILED because `from __future__` appeared on line 32, outside the first 5 lines.
  - `grep -cE '^\s+(field_name|old_value|new_value|edited_at|editor_did):' audit.py` returned **8** (expected 5) because the 4-space-indented multi-line function params `    field_name: str,\n    new_value: Any,\n    editor_did: str,` matched the same `^\s+name:` pattern as the ContentEdit class fields.
- **Fix:** (a) Shortened module docstring to a single-line summary; moved the extended D-08 / Phase 5 / Phase 6 commentary into a block comment (leading `#`) below the imports — this puts `from __future__ import annotations` on line 2 of the file (within head -5). (b) Collapsed the `def add_edit(...)` signature to a single line so none of the 5 field-name tokens appear at 4-space indent in the function body — only the 5 ContentEdit class fields match now.
- **Files modified:** `src/folio_insights/shards/audit.py` (pre-commit rewrite before Task 1's commit)
- **Verification:** `head -5 audit.py | grep -F 'from __future__'` → matches line 2. `grep -cE '^\s+(field_name|old_value|new_value|edited_at|editor_did):' audit.py` → `5` (exactly the 5 class fields at lines 49-53).
- **Committed in:** `00a1d67` (Task 1 commit, pre-commit fix-up during task execution — same flow Wave 1 documented for its own docstring-vs-grep collisions)
- **Semantics unchanged:** behavior smoke test (ContentEdit round-trip + frozen + extra-forbid + add_edit append+assign + add_edit-on-frozen-raises + forward-ref-resolved) passes identically before and after the docstring/signature reshape.

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking acceptance grep; docstring length + multi-line def signature vs mechanical grep matchers).
**Impact on plan:** No scope change, no behavioral change. Fix is a layout adjustment that satisfies the plan's mechanical grep acceptance gates while preserving D-08 semantics byte-for-byte. Lesson consistent with Wave 1's precedent: for plans whose acceptance is grep-based (fixed-string, bounded-head, or regex-without-context), file layout must avoid grep-pattern-colliding substrings — even benign ones like function-parameter annotations that happen to match the class-field pattern.

## Issues Encountered

- **Worktree base commit mismatch at executor startup** — the worktree branch was based on `3719d3dc` (master HEAD) rather than the Wave 1 merge `eab1e513`. Hard-reset per the worktree_branch_check protocol; no files lost (fresh worktree, no user changes).
- **No .venv in worktree** — as in Wave 1, the worktree doesn't ship its own `.venv`. Resolved by using `/home/damienriehl/Coding Projects/folio-insights/.venv/bin/python` with `PYTHONPATH=src` prefix pointing to the worktree's `src/` (preempts the project-root editable install's Wave-0 version).
- **project venv had no pip** — attempted `./.venv/bin/python -m pip install 'hypothesis>=6.100'` returned `No module named pip`. Fell back to `uv pip install --python ./.venv/bin/python 'hypothesis>=6.100'` which succeeded (installed `hypothesis==6.152.2` + `sortedcontainers==2.4.0`). The pyproject.toml declaration is the authoritative dep source either way — Plan 02-03 executor (fresh venv or reinstall) will pick up hypothesis via `uv pip install -e '.[dev]'`.

## Known Stubs

Plan 02-02 intentionally ships minimal audit semantics that Phase 5 and Phase 6 will harden. These are tracked so the verifier does not flag them as missing functionality:

| Stub | File | Reason | Resolved by |
|------|------|--------|-------------|
| `add_edit` append-then-setattr sequence is non-transactional | `audit.py:L70-81` | Phase 2 scope per plan: "Phase 5 will... make the append+setattr sequence transactional (rollback the append on setattr failure)". When `field_name` is a D-07 frozen field, the ContentEdit is appended BEFORE the setattr raises — leaving a dangling audit record with no corresponding value change. Plan 02-03 regression test asserts the raise behavior; hardening is Phase 5. | Phase 5 (forward-only SHACL gate + transactional add_edit wrapper) |
| `old_value: Any`, `new_value: Any` — no per-field type validation in ContentEdit | `audit.py:L49-53` | A ContentEdit can record edits to any envelope field type. Tightening to per-field-type Union / dispatch-by-field_name is Phase 5 scope. | Phase 5 (field_name ∈ ShardEnvelope.model_fields pre-flight + per-field old/new type validation) |
| `editor_did: str` — typed string, no DID signature verification | `audit.py:L53` | Phase 2 explicitly defers DID signing to Phase 6 per CONTEXT D-08 ("Phase 5 wires the full validator + forward-only SHACL gate; Phase 6 adds DID signature capture"). Malicious local actor can construct ContentEdits with any `editor_did` — threat T-02-02-04 accepted for Phase 2. | Phase 6 (DID substrate + AttestedSignature over canonical ContentEdit hash) |
| No `@model_validator` on ContentEdit (no edited_at monotonicity gate) | `audit.py:L37-53` | Plan explicitly instructs "DO NOT add a `@model_validator` on ContentEdit (no cross-field invariants at Phase 2; Phase 5 adds them)". | Phase 5 (forward-only @model_validator: edited_at >= transaction_time) |
| No `validate_content_edit_shape()` defense-in-depth function | `audit.py` (not present) | Plan explicitly instructs "DO NOT add a `validate_content_edit_shape()` function (Phase 5 ships the defense-in-depth helper mirroring validate_fork_proposal_shape)". | Phase 5 (mirrors distinguo's validate_fork_proposal_shape pattern) |
| No `shard.content_edits.append` length cap (unbounded audit chain) | `envelope.py:L187` + `audit.py:L70` | Threat T-02-02-07 accepted for Phase 2: "Phase 5 will add a per-shard edit-count gate + SHACL shape". | Phase 5 (bounded-chain SHACL policy) |

None of these stubs prevents Plan 02-02 from meeting its stated goal (lock ContentEdit shape + add_edit helper + forward-ref wire-up + Plan 02-03 infrastructure prerequisites).

## User Setup Required

None — no external service configuration required. Phase 2 is pure in-memory Pydantic + stdlib. `hypothesis==6.152.2` was installed into the project venv during this plan's execution; Plan 02-03 executor can re-sync via `uv pip install -e '.[dev]'` if the venv is reset.

## Next Phase Readiness

**Ready for Plan 02-03** (wave 3): Round-trip + discriminated-union + frozen-assignment + bitemporal + audit-append + hypothesis determinism + grep-guard dep-leak regression tests. All 13 symbols (`AttestedSignature`, `ConflictingAuthoritiesShard`, `ContentEdit`, `DisputedPropositionShard`, `GlossShard`, `HypothesisShard`, `mint_shard_iri`, `Shard`, `ShardEnvelope`, `ShardType`, `SimpleAssertionShard`, `Triple`, `add_edit`) are importable today, the forward-ref is resolved, `hypothesis>=6.100` is declared + installed, and `@pytest.mark.shards` is registered. Plan 02-03's `pytestmark = pytest.mark.shards` + `@given(...)` property test harness can start without further setup.

**Ready for Phase 5** (content versioning SHACL gate): The `add_edit` helper's behavior at frozen fields (raises ValidationError) is the exact hook Phase 5 will wrap with transactional rollback. The `ContentEdit.model_config = ConfigDict(frozen=True)` guarantees audit records themselves stay immutable across the SHACL hardening work.

**Ready for Phase 6** (DID substrate): `ContentEdit.editor_did: str` is the field Phase 6 will wrap with `AttestedSignature` over the ContentEdit's canonical hash. No shape change required — the signature adds alongside, not replacing.

**No blockers.** Orchestrator owns STATE.md / ROADMAP.md updates for the wave.

## 13 Public Symbols Re-exported (Plan 02-01 + Plan 02-02)

Alphabetical (`__all__` order in `shards/__init__.py`):

1. `add_edit` — **(new in 02-02)**
2. `AttestedSignature`
3. `ConflictingAuthoritiesShard`
4. `ContentEdit` — **(new in 02-02)**
5. `DisputedPropositionShard`
6. `GlossShard`
7. `HypothesisShard`
8. `mint_shard_iri`
9. `Shard`
10. `ShardEnvelope`
11. `ShardType`
12. `SimpleAssertionShard`
13. `Triple`

## Self-Check

Verifying all files, commits, and success criteria before returning to the orchestrator:

- [x] `src/folio_insights/shards/audit.py` — FOUND (97 lines)
- [x] `src/folio_insights/shards/__init__.py` — FOUND (33 lines, updated)
- [x] `pyproject.toml` — FOUND (+2 lines: hypothesis>=6.100 dev dep + shards marker)
- [x] Task 1 commit `00a1d67` — FOUND in git log (`feat(02-02): add ContentEdit frozen sub-model + add_edit helper + model_rebuild wire-up`)
- [x] Task 2 commit `2ec8739` — FOUND in git log (`chore(02-02): add hypothesis>=6.100 dev dep + shards pytest marker`)
- [x] `grep -cE 'ConfigDict\(frozen=True' src/folio_insights/shards/audit.py` == 1 — VERIFIED
- [x] `grep -cE '^\s+(field_name|old_value|new_value|edited_at|editor_did):' audit.py` == 5 — VERIFIED (5 class fields at lines 49-53 only)
- [x] `head -5 audit.py | grep -F 'from __future__ import annotations'` matches — VERIFIED (line 2)
- [x] `grep -F 'ShardEnvelope.model_rebuild()' audit.py` — VERIFIED (module bottom, line 96)
- [x] No `pyoxigraph|rdflib|oxrdflib|owlready2` imports under `src/folio_insights/shards/` — VERIFIED
- [x] `grep -F '"hypothesis>=6.100"' pyproject.toml` — VERIFIED (under [project.optional-dependencies].dev)
- [x] `grep -F '"shards: Phase 2 v2.0 Shard envelope tests"' pyproject.toml` — VERIFIED (under [tool.pytest.ini_options].markers)
- [x] 13-symbol `from folio_insights.shards import ...` works — VERIFIED (`all-13-imports-ok`)
- [x] `ShardEnvelope.model_fields['content_edits'].annotation.__args__[0] is ContentEdit` — VERIFIED (`ref-ok`)
- [x] `hypothesis.__version__ == 6.152.2` (satisfies >=6.100) — VERIFIED
- [x] `pytest --markers | grep 'shards: Phase 2'` matches — VERIFIED (`@pytest.mark.shards: Phase 2 v2.0 Shard envelope tests`)
- [x] `tomllib.loads(open('pyproject.toml').read())` parses — VERIFIED (`toml-ok`)
- [x] ContentEdit round-trip (model_dump_json → model_validate_json) — VERIFIED
- [x] ContentEdit is frozen (assignment raises pydantic.ValidationError) — VERIFIED
- [x] ContentEdit extra=forbid (bogus field raises pydantic.ValidationError) — VERIFIED
- [x] add_edit appends a real ContentEdit instance + mutates shard field in place — VERIFIED
- [x] add_edit on D-07 frozen field (shard_iri) raises pydantic.ValidationError — VERIFIED

## Self-Check: PASSED

---
*Phase: 02-shard-envelope*
*Plan: 02 (wave 2)*
*Completed: 2026-04-24*
