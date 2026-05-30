---
phase: 07-governance-model-3-1
plan: 02
subsystem: rfc-linter
tags: [rfc, linter, git-history, ci-gate, gov-07, gov-08, d-22, d-02]
requirements_completed: [GOV-07, GOV-08]
requirements_deferred: [GOV-09, GOV-10]
dependency-graph:
  requires: []
  provides:
    - "folio_insights.rfc.lint:main (CI-runnable RFC lifecycle gate)"
    - "folio_insights.rfc.frontmatter:RFCFrontmatter (locked Pydantic schema)"
    - "folio_insights.rfc.frontmatter:_parse_frontmatter_raw (extra-key tolerant raw parser)"
    - "folio_insights.rfc.git_history:walk_history (subprocess git-log walker)"
    - ".planning/rfcs/RFC-TEMPLATE.md (golden fixture for Phase 18)"
  affects:
    - "CI pipelines (will gate RFC PRs once Phase 18 wires the pre-commit hook)"
tech-stack:
  added: []  # zero new pip dependencies; stdlib + Pydantic + subprocess only
  patterns:
    - "stdlib-only frontmatter parser (deliberate; no PyYAML / python-frontmatter)"
    - "subprocess.run + git log --follow --reverse (deliberate; no GitPython)"
    - "raw-dict-then-Pydantic two-layer parse (extra='forbid' on validated schema; unknown keys preserved in raw dict for body-only-edit heuristic)"
    - "GitHub-Actions-friendly ::error:: stderr output (same invocation works locally + in CI)"
key-files:
  created:
    - "src/folio_insights/rfc/__init__.py"
    - "src/folio_insights/rfc/__main__.py"
    - "src/folio_insights/rfc/lint.py"
    - "src/folio_insights/rfc/frontmatter.py"
    - "src/folio_insights/rfc/git_history.py"
    - ".planning/rfcs/RFC-TEMPLATE.md"
    - "tests/rfc/__init__.py"
    - "tests/rfc/conftest.py"
    - "tests/rfc/test_lint_frontmatter_schema.py"
    - "tests/rfc/test_lint_filename_monotonic.py"
    - "tests/rfc/test_lint_status_monotonic_across_history.py"
    - "tests/rfc/test_lint_body_only_edit_refused.py"
  modified:
    - "pyproject.toml (registered 'rfc' pytest marker; no dep changes)"
decisions:
  - "[07-02 D1] Raw-dict tolerance in walk_history(): the history walker reads `status` directly from `_parse_frontmatter_raw()` and skips full Pydantic validation. Earlier `parse_frontmatter()` calls were dropping commits whose frontmatter carried the optional `status_change_reason:` key (Pydantic `extra=\"forbid\"` rejects unknown keys) — which silently disabled the body-only-edit-refusal heuristic for exactly the commits it was supposed to authorize. The HEAD-validation pass in `validate_rfc_file()` still runs the full Pydantic schema, so the strict-schema discipline is preserved where it matters."
  - "[07-02 D2] Trailing-dash slugs are PERMITTED in `RFC_FILENAME_RE`. The regex `^(\\d{4})-[a-z0-9][a-z0-9-]*\\.md$` allows e.g. `0001-trailing-.md`. D-22 does not explicitly forbid trailing dashes; rejecting them would be surprise discipline outside the spec. Documented in the negative-case parametrize comment."
  - "[07-02 D3] No `from folio_insights.rfc.git_history import parse_frontmatter`. The walker now imports only `_parse_frontmatter_raw`, eliminating an unused symbol and clarifying the layering."
  - "[07-02 D4] CLI shim `python -m folio_insights.rfc` (via `__main__.py`) defaults to `.planning/rfcs/` if no path is supplied — matches the plan's contract example."
metrics:
  duration_min: ~25
  completed_date: "2026-05-30"
  tasks_completed: 2
  files_created: 12
  files_modified: 1
  commits: 3
  tests_added: 40
---

# Phase 07 Plan 02: RFC Lifecycle Linter (GOV-07) Summary

**One-liner:** Stdlib-only `python -m folio_insights.rfc.lint` ships as a CI-runnable gate enforcing the D-22 status DAG (`draft → discussion → {accepted, rejected} → implemented`) across full git history, with body-only-edit-refusal heuristic and `RFC-TEMPLATE.md` golden fixture — zero new pip deps.

## What Shipped

### `src/folio_insights/rfc/` (5 files, 5 modules)

| File | Role |
|------|------|
| `__init__.py` | Package marker citing D-22 + D-02 + stdlib-only discipline |
| `frontmatter.py` | `RFCFrontmatter` Pydantic model (extra="forbid", rfc≥1, 5-Literal status, DID-string authors, ISO-date string, optional `superseded_by`) + `_parse_frontmatter_raw()` (extra-key tolerant) + `parse_frontmatter()` (Pydantic-validating wrapper) |
| `git_history.py` | `walk_history()` — subprocess `git log --follow --reverse` walker; returns `list[dict[sha, subject, body, status, frontmatter_dict]]` oldest-first; tolerant of unknown frontmatter keys (preserves `status_change_reason`) |
| `lint.py` | `RFC_FILENAME_RE`, `ALLOWED_TRANSITIONS` DAG, `_has_rationale()` heuristic, `validate_rfc_file()`, `main()` — directory walker with template-skip, duplicate-number gate, `::error::` stderr output |
| `__main__.py` | `python -m folio_insights.rfc` shim defaulting to `.planning/rfcs/` |

### `.planning/rfcs/RFC-TEMPLATE.md` (golden fixture, D-02)

Frontmatter dump:
```yaml
---
rfc: 0
title: Template — Replace With Your RFC Title
status: draft
authors:
  - did:key:z6Mk... (replace with your DID — see `folio-insights did generate`)
created: 2026-05-30
---
```

Body sections (per Phase 18 contributor reference): Summary, Motivation, Detailed Design,
Drawbacks, Alternatives Considered, Unresolved Questions, Prior Art, + Lifecycle Lint Cheat Sheet.

### `tests/rfc/` (6 files, 40 tests — all passing)

| File | Tests | Coverage |
|------|-------|----------|
| `__init__.py` | — | Package marker |
| `conftest.py` | — | `rfcs_dir_factory` + `make_rfc_file` fixtures + `pytestmark = pytest.mark.rfc` |
| `test_lint_frontmatter_schema.py` | 12 | positive + negative for `RFCFrontmatter` (extra=forbid, 5 Literal statuses, missing field, rfc≥1, raw-dict parser) |
| `test_lint_filename_monotonic.py` | 20 | filename pattern (positive/negative parametrized), template filename doesn't match, gaps-allowed, duplicate-number-fails, template-only directory, empty directory |
| `test_lint_status_monotonic_across_history.py` | 4 | happy path; forbidden downgrade `accepted → draft`; terminal `rejected → accepted`; skip-stage `draft → accepted` |
| `test_lint_body_only_edit_refused.py` | 4 | no rationale → fail; `Reason:` trailer → pass; `status_change_reason:` frontmatter → pass; only un-rationalized commit flagged in mixed run |

## Verification

- `uv run pytest tests/rfc/ -x -q` → **40 passed** in 0.24s
- `ruff check src/folio_insights/rfc/ tests/rfc/` → clean
- `grep -rEn "import yaml|from yaml|import frontmatter|from frontmatter" src/folio_insights/rfc/` → empty (stdlib-only discipline)
- `grep -rEn "^(import|from) git( |$)" src/folio_insights/rfc/` → empty (no GitPython)
- `grep -rn "subprocess.run.*git" tests/rfc/` → 10 hits (subprocess discipline confirmed)
- `python -m folio_insights.rfc.lint .planning/rfcs/` → **exit 0** (only `RFC-TEMPLATE.md` present, skipped by filename)
- Live binding probe: `from folio_insights.rfc.{frontmatter,git_history,lint} import RFCFrontmatter, parse_frontmatter, _parse_frontmatter_raw, walk_history, main, validate_rfc_file, ALLOWED_TRANSITIONS, RFC_FILENAME_RE` → ok

## Commits (3)

| # | Hash | Type | Description |
|---|------|------|-------------|
| 1 | `463a6ec` | test | RED — failing tests for frontmatter schema + filename monotonic |
| 2 | `b7f73aa` | feat | GREEN Task 1 — rfc/ package + RFC-TEMPLATE.md golden fixture |
| 3 | `dd13849` | test | Task 2 — git-history DAG + body-only-edit-refusal tests; Rule 1 fix in walk_history |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `walk_history()` was silently dropping commits with `status_change_reason:`**

- **Found during:** Task 2 (first run of `test_status_change_with_frontmatter_reason_is_accepted`)
- **Issue:** `walk_history()` called `parse_frontmatter()` (Pydantic-validated) on every historical commit. Because `RFCFrontmatter.model_config = ConfigDict(extra="forbid")`, any commit whose frontmatter carried the optional `status_change_reason:` key raised `ValidationError` and was discarded entirely. That silently disabled the body-only-edit-refusal acceptance path — exactly the scenario D-22 says should pass.
- **Fix:** Switched `walk_history()` to call `_parse_frontmatter_raw()` only, pulling `status` directly from the raw dict. Strict Pydantic validation still runs at the HEAD level in `validate_rfc_file()`, where it matters. Removed unused `parse_frontmatter` and `ValidationError` imports.
- **Files modified:** `src/folio_insights/rfc/git_history.py`
- **Commit:** `dd13849`

**2. [Rule 1 - Bug] `test_filename_pattern_negative[0001-trailing-.md]` was inconsistent with its own docstring**

- **Found during:** Task 1 (first GREEN run)
- **Issue:** The parametrized negative case included `"0001-trailing-.md"`, but the regex `^(\d{4})-[a-z0-9][a-z0-9-]*\.md$` permits trailing dashes by construction (the slug class is `[a-z0-9-]*`), and the test's own docstring acknowledged that. D-22 doesn't forbid trailing dashes either.
- **Fix:** Dropped the `"0001-trailing-.md"` case; added `"0001 spaces.md"` and `"0001-bad.txt"` as cleaner negative cases. Documented in the parametrize comment that trailing dashes are deliberately permitted.
- **Files modified:** `tests/rfc/test_lint_filename_monotonic.py`
- **Commit:** `b7f73aa` (bundled with the Task 1 GREEN commit since it was a test fix landed during the GREEN pass)

### Authentication Gates

None.

### Rule 4 (Architectural Decisions)

None requested; plan executed within scope.

## Known Stubs

None. The linter is wired end-to-end; `python -m folio_insights.rfc.lint` is the real CI gate.

The `RFC-TEMPLATE.md` placeholder DID string (`did:key:z6Mk...`) is intentional — it is documentation guiding contributors to substitute their own DID. The template is skipped by filename so the placeholder never reaches Pydantic validation.

## Threat Flags

None. Surfaces match the plan's `<threat_model>` exactly:

- T-7-08 (Tampering, history walk): mitigated via `ALLOWED_TRANSITIONS` DAG + monotonic-history check in `validate_rfc_file()`.
- T-7-09 (Tampering, body-only edit): mitigated via `_has_rationale()` heuristic checking `Reason:` trailer OR `status_change_reason:` frontmatter line.
- T-7-SC (Tampering, new pip dep): grep gate `grep -rEn "import yaml|from yaml|import frontmatter|from frontmatter|import git( |$)" src/folio_insights/rfc/` returns empty.

## TDD Gate Compliance

Per-task TDD cycle:

- Task 1: RED commit `463a6ec` (test, fails with `ModuleNotFoundError: No module named 'folio_insights.rfc'`) → GREEN commit `b7f73aa` (feat, 32 tests pass).
- Task 2: tests + Rule 1 fix landed in single commit `dd13849` — the negative test (`test_status_change_with_frontmatter_reason_is_accepted`) failed first, exposing the walker bug, and the same commit carries both the new tests and the fix that makes them pass. This is acceptable for test-driven *exploration*: the bug was discovered THROUGH the test, and the test+fix pair is atomic in history.

40 total tests; 0 failures; 0 skipped (git CLI was present).

## Self-Check

Files created exist:
- `src/folio_insights/rfc/__init__.py` — FOUND
- `src/folio_insights/rfc/__main__.py` — FOUND
- `src/folio_insights/rfc/lint.py` — FOUND
- `src/folio_insights/rfc/frontmatter.py` — FOUND
- `src/folio_insights/rfc/git_history.py` — FOUND
- `.planning/rfcs/RFC-TEMPLATE.md` — FOUND
- `tests/rfc/__init__.py` — FOUND
- `tests/rfc/conftest.py` — FOUND
- `tests/rfc/test_lint_frontmatter_schema.py` — FOUND
- `tests/rfc/test_lint_filename_monotonic.py` — FOUND
- `tests/rfc/test_lint_status_monotonic_across_history.py` — FOUND
- `tests/rfc/test_lint_body_only_edit_refused.py` — FOUND

Commits exist on `worktree-agent-adff48b576ce122cc`:
- `463a6ec` — FOUND (RED)
- `b7f73aa` — FOUND (Task 1 GREEN)
- `dd13849` — FOUND (Task 2)

## Self-Check: PASSED
