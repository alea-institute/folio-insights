---
phase: 02-uat-gap-fixes
plan: 03
subsystem: pipeline/folio-tagging
tags: [uat, folio, tagging, iri-resolution, regression-tests, tdd]
requirements:
  - I-1
gap_closure: true
dependency_graph:
  requires:
    - FolioService.search_by_label from services.bridge.folio_bridge
    - ReconciledConcept from services.bridge.reconciliation_bridge
    - ConceptTag from models.knowledge_unit (unchanged)
  provides:
    - LLM-path label-to-IRI resolution at similarity >= 0.6
    - extraction_path='proposed_class' routing for unresolved labels
  affects:
    - quality/output_formatter.format_proposed_classes_report (populated correctly)
    - OWL exporter (resolved IRIs become owl:Class references)
tech_stack:
  added: []
  patterns:
    - class-level tunable constant (_FOLIO_LABEL_RESOLUTION_THRESHOLD)
    - fall-through path rewrite (primary_path → 'proposed_class' when iri=='')
key_files:
  created: []
  modified:
    - src/folio_insights/pipeline/stages/folio_tagger.py
    - tests/test_folio_tagging.py
decisions:
  - "02-03: Lowered FolioService label-match threshold from 0.7 to 0.6, exposed as class-level _FOLIO_LABEL_RESOLUTION_THRESHOLD constant for future tuning"
  - "02-03: Unresolved labels get extraction_path rewritten to 'proposed_class' rather than retaining their originating path ('llm'/'semantic'/etc.) — gives downstream consumers unambiguous routing without introducing new fields"
  - "02-03: Replaced silent `except Exception: pass` with logger.warning(exc_info=True) so genuine FolioService failures are observable without breaking the tag loop"
metrics:
  duration_minutes: 6
  tasks_completed: 2
  files_modified: 2
  tests_added: 4
  completed: 2026-04-19
---

# Phase 02 Plan 03: Fix LLM-Path FOLIO IRI Resolution (UAT I-1) Summary

## One-liner

Lower FolioService label-match threshold to 0.6 and route unresolved labels to `extraction_path='proposed_class'` so LLM-extracted FOLIO concepts resolve to canonical IRIs.

## What was shipped

- `src/folio_insights/pipeline/stages/folio_tagger.py` — replaced `_reconciled_to_tags` with a version that (a) reads a class-level constant `_FOLIO_LABEL_RESOLUTION_THRESHOLD = 0.6` (was a hardcoded 0.7), (b) rewrites `extraction_path` to `'proposed_class'` when the resolved IRI is empty, (c) logs `search_by_label` exceptions via `logger.warning(exc_info=True)` instead of silently swallowing them.
- `tests/test_folio_tagging.py` — appended 4 regression tests guarding the new behaviour (Test A: resolves at 0.65; Test B: no match → `proposed_class`; Test C: 0.92 still resolves; Test D: 0.4 match falls through to `proposed_class`).

## Diff summary

| Change | Before | After |
|---|---|---|
| Label-match threshold | hardcoded `0.7` inside `_reconciled_to_tags` | class constant `_FOLIO_LABEL_RESOLUTION_THRESHOLD = 0.6` |
| Unresolved `iri` handling | `ConceptTag(iri='', extraction_path='llm')` (or whichever path produced it) | `ConceptTag(iri='', extraction_path='proposed_class')` |
| `search_by_label` exceptions | `except Exception: pass` (silent) | `logger.warning(..., exc_info=True)` |
| Regression tests for I-1 | none | 4 new, all green |

## Before / after

### Before (Task 0 baseline)
```python
# folio_tagger.py — _reconciled_to_tags
if top_score >= 0.7:      # LLM labels rarely clear this
    iri = getattr(top_match, "iri", "")
# ...
tag = ConceptTag(iri=iri, label=rc.label, extraction_path=primary_path, ...)
# → ConceptTag(iri='', extraction_path='llm') for unresolved LLM labels
```

### After (Task 2)
```python
# folio_tagger.py — _reconciled_to_tags
if top_score >= self._FOLIO_LABEL_RESOLUTION_THRESHOLD:   # 0.6
    iri = getattr(top_match, "iri", "") or ""
# ...
if not iri:
    primary_path = "proposed_class"      # route unresolved concepts
tag = ConceptTag(iri=iri, label=rc.label, extraction_path=primary_path, ...)
# → ConceptTag(iri='', extraction_path='proposed_class') for unresolved labels
# → ConceptTag(iri='https://folio...', extraction_path='llm') for matches >= 0.6
```

## Tasks & commits

| # | Task | Commit | Files |
|---|---|---|---|
| 1 | RED — add 4 failing regression tests | `ef4ff2b` | `tests/test_folio_tagging.py` |
| 2 | GREEN — fix `_reconciled_to_tags`; threshold 0.7 → 0.6; route unresolved to `proposed_class` | `a05de28` | `src/folio_insights/pipeline/stages/folio_tagger.py` |

## Verification

- `tests/test_folio_tagging.py`: **14/14 passed** (10 pre-existing + 4 new I-1 regressions).
- Full suite (`pytest tests/`): **203 passed, 0 failed** (baseline from `master` was 199 passed; +4 new tests from this plan = 203).
- RED phase proof (current code, before fix): Test A/B/D fail with assertion on `iri`/`extraction_path`; Test C passes (regression guard). Captured during Task 1 verification.
- GREEN phase proof (after fix): all 14 tests green; `grep -c "_FOLIO_LABEL_RESOLUTION_THRESHOLD = 0.6" src/folio_insights/pipeline/stages/folio_tagger.py` → `1`; `grep -c "proposed_class" src/folio_insights/pipeline/stages/folio_tagger.py` → `3`.

### Note on full-suite baseline count
Plan acceptance criterion reads `>= 201 passed` / ">= 204 after 02-02 lands". The worktree is based on commit `e681a25` (post-02-02 merge), and the pre-02-03 baseline on that commit is 199 passed (not 201 as the plan estimated). Adding the 4 I-1 tests produces 203. No regressions; the numeric baseline differs by 2 from the plan's estimate, but all pre-existing tests remain green and this plan contributes exactly the 4 tests it said it would.

### Note on existing folio-tagging test count
Plan frontmatter and narrative reference "8 pre-existing tests" in `tests/test_folio_tagging.py`. Actual count on disk before this plan was 10 (4 reconciler tests + 3 heading-context tests + 1 path-recording test + 1 lineage test + 1 stage-name test). All 10 still pass after the fix. The plan's "8 + 4 = 12" bookkeeping resolves as "10 + 4 = 14" in reality; no tests were removed or altered.

## Deviations from Plan

None — plan executed exactly as written. The `_reconciled_to_tags` replacement, threshold constant, and 4 regression tests all match the plan's code blocks verbatim.

Two pre-existing non-issues worth logging (not deviations, just observations):
- The worktree cannot run the bridge-dependent tests (`test_bridge.py`, `test_ingestion.py`) without `FOLIO_INSIGHTS_FOLIO_ENRICH_PATH` set, because the default `../folio-enrich/backend` resolves relative to the worktree root where there is no sibling `folio-enrich` checkout. For verification I exported `FOLIO_INSIGHTS_FOLIO_ENRICH_PATH=/home/damienriehl/Coding Projects/folio-enrich/backend` so the full 203-test suite ran. Main repo users are unaffected.
- The editable install in `.venv` points at the main repo's `src/`, not the worktree's. I ran pytest with `PYTHONPATH=<worktree>/src` so imports resolved to the edited files. Acceptance-criteria greps and `git diff --name-only` were both run from within the worktree and verified the expected change set.

## Self-Check

- [x] `src/folio_insights/pipeline/stages/folio_tagger.py` modified — FOUND (`_FOLIO_LABEL_RESOLUTION_THRESHOLD = 0.6` at line 50; fixed `_reconciled_to_tags` at lines 247-301).
- [x] `tests/test_folio_tagging.py` modified — FOUND (4 new tests after `test_folio_tagger_stage_name`).
- [x] Task 1 commit `ef4ff2b` — FOUND.
- [x] Task 2 commit `a05de28` — FOUND.
- [x] `pytest tests/test_folio_tagging.py` = 14 passed — FOUND.
- [x] `pytest tests/` = 203 passed — FOUND.

## Self-Check: PASSED

## Follow-ups

- Real-corpus UAT re-run against `/api/v1/units` is deferred to the follow-up UAT sweep per the plan's `<output>` block. Expected behaviour after this fix: a corpus containing "cross-examination" / "expert witness" / "bias" produces a mix of non-empty IRIs (resolved FOLIO concepts) and empty IRIs with `extraction_path='proposed_class'` for novel concepts.
- `_FOLIO_LABEL_RESOLUTION_THRESHOLD` now lives as a class attribute — future tuning (e.g. different thresholds per branch or per extraction path) can subclass `FolioTaggerStage` or override via config without touching the core resolution logic.
