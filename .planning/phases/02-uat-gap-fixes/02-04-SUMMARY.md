---
phase: 02-uat-gap-fixes
plan: 04
subsystem: export-fixtures
tags: [uat, fixture, cli, export, seed-script]
requirements:
  - I-4
dependency_graph:
  requires:
    - api.db.models.SCHEMA_SQL (review.db schema)
    - src/folio_insights/cli.py (export command contract)
  provides:
    - output/demo/ (end-to-end-exercisable approved-task fixture)
    - scripts/seed_demo_corpus.py (deterministic regeneration path)
  affects:
    - .gitignore (whitelist !output/demo/)
    - future UAT tests 37-41 (now runnable with real artifacts)
tech_stack:
  added: []
  patterns:
    - Deterministic fixture seeding via fixed ISO-8601 timestamp
    - SCHEMA_SQL copy-paste-reuse (no duplicate schema definition)
    - Whitelist pattern in .gitignore matching output/default/ + output/test1/
key_files:
  created:
    - scripts/seed_demo_corpus.py
    - output/demo/corpus-meta.json
    - output/demo/extraction.json
    - output/demo/review.db
    - output/demo/sources/demo-advocacy.md
  modified:
    - .gitignore
decisions:
  - Seed script wipes output/demo/ before rebuild to guarantee byte-identical idempotency
  - Fixed timestamp 2026-04-19T12:00:00+00:00 so extraction.json / corpus-meta.json hashes are stable across re-seeds
  - Two approved tasks with parent/child relationship (task-demo-001 parent of task-demo-002) so the hierarchy exporter has a non-trivial tree to render
  - sources/demo-advocacy.md is a single-file hand-authored source that aligns with the two unit.source_section paths, keeping the fixture browsable
metrics:
  duration: "~8 min"
  completed_date: "2026-04-19"
  tasks_completed: 1
  files_changed: 6
  tests_passed: 199
  tests_baseline: 197
---

# Phase 02-uat-gap-fixes Plan 04: demo-corpus-fixture Summary

Add a minimal, deterministic `output/demo/` corpus fixture (2 approved tasks + 2 task_unit_links + 1 source file) plus a seed script that regenerates it idempotently — unblocks UAT tests 37-41 which previously had no corpus with approved tasks to validate the `folio-insights export` pipeline against.

## Objective Met

UAT Issue I-4: "no repo fixture has approved tasks, so tests 37-41 can't run end-to-end." All three bundled review.db files (output/default/, output/test1/) had `task_decisions` row count 0, so `folio-insights export <corpus>` correctly refused with "No tasks found to export." This plan ships a committed `output/demo/` fixture with 2 approved tasks + 2 unit links + an extraction.json with 2 units, plus a reproducible seed script, so the export pipeline can be exercised with real content.

## Tasks Completed

| Task | Name                                                                    | Commit   | Files                                                                                                          |
| ---- | ----------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------- |
| 1    | Create seed script, generate output/demo/ fixture, whitelist .gitignore | 293662a  | scripts/seed_demo_corpus.py, output/demo/{corpus-meta.json,extraction.json,review.db,sources/demo-advocacy.md}, .gitignore |

## Files Created

| File                                | Size     | Notes                                                                       |
| ----------------------------------- | -------- | --------------------------------------------------------------------------- |
| scripts/seed_demo_corpus.py         | 169 lines | Deterministic seed (fixed timestamp); wipes + rebuilds output/demo/         |
| output/demo/corpus-meta.json        | 82 B     | `{"id":"demo","name":"Demo","created_at":"2026-04-19T12:00:00+00:00"}`      |
| output/demo/extraction.json         | 1737 B   | 2 units (unit-demo-001, unit-demo-002) with folio_tags + original_span etc. |
| output/demo/review.db               | 122880 B | SQLite w/ 2 approved task_decisions + 2 task_unit_links                     |
| output/demo/sources/demo-advocacy.md | 475 B    | Hand-authored 2-chapter markdown matching the units' source_section paths   |

## Verification Evidence

**review.db integrity (post-seed):**

```
$ python -c "import sqlite3; c=sqlite3.connect('output/demo/review.db'); print('approved:', next(c.execute(\"SELECT COUNT(*) FROM task_decisions WHERE status='approved'\"))[0]); print('links:', next(c.execute('SELECT COUNT(*) FROM task_unit_links'))[0])"
approved: 2
links: 2
```

**Idempotency check:**

```
$ python scripts/seed_demo_corpus.py && md5sum output/demo/extraction.json > /tmp/a
$ python scripts/seed_demo_corpus.py && md5sum output/demo/extraction.json > /tmp/b
$ diff /tmp/a /tmp/b
# (no diff — byte-identical)
c42227f49c079c43e58b367818636814  output/demo/extraction.json
12a3a47ab57080e92420d7d2d219056d  output/demo/corpus-meta.json
cf8cf754840aae6887ab444c8520b6a0  output/demo/sources/demo-advocacy.md
```

**Gitignore diff:**

```diff
 output/*
 !output/default/
 !output/test1/
+!output/demo/
```

**CLI smoke-test (Markdown path):**

```
$ .venv/bin/folio-insights export demo --format md --output ./output --no-validate
Exporting corpus: demo
Formats: md
Tasks: 2 (approved only)

--- Export Summary ---
  task-hierarchy.md
Output: .../output/demo/
# exit 0
```

Generated `output/demo/task-hierarchy.md` (421 B) renders the two-task hierarchy with a parent/child relationship and unit text:

```markdown
# Task Hierarchy

- **Witness Preparation** (procedural -- ordered steps)
  - *Best Practices*:
    - Always prepare witnesses thoroughly before direct examination. (confidence: 0.92)
  - **Cross-Examine Expert Witness** (procedural -- ordered steps)
    - *Advice*:
      - Counsel may use cross-examination to impeach an expert witness for bias, lack of foundation, or prior inconsistent statements. (confidence: 0.90)
```

The `task-hierarchy.md` artifact is generated output (not part of the committed fixture) — the seed script rebuilds the fixture without it.

**pytest suite:**

```
$ FOLIO_INSIGHTS_FOLIO_ENRICH_PATH=.../folio-enrich/backend .venv/bin/pytest tests/ -q
199 passed, 7 warnings in 5.93s
```

199 passed ≥ 197 baseline — no regression.

## Acceptance Criteria Check

| Criterion                                                               | Status |
| ----------------------------------------------------------------------- | ------ |
| All four fixture files exist after seed                                 | PASS   |
| `task_decisions WHERE status='approved'` count ≥ 1 (actual: 2)          | PASS   |
| `task_unit_links` count ≥ 1 (actual: 2)                                 | PASS   |
| `extraction.json` has ≥ 1 unit, first id is `unit-demo-001`             | PASS   |
| `.gitignore` whitelists `!output/demo/`                                 | PASS   |
| `.gitignore` preserves `!output/default/` and `!output/test1/`          | PASS   |
| `scripts/seed_demo_corpus.py` ≥ 50 lines (actual: 169)                  | PASS   |
| pytest ≥ 197 passed (actual: 199)                                       | PASS   |
| Seed script is idempotent (byte-identical outputs across runs)          | PASS   |
| CLI `export demo --format md --no-validate` exits 0                     | PASS   |

## Deviations from Plan

**None substantive.** Plan executed exactly as written, with one minor environment note:

- **pytest cwd-resolution note (not a code change):** The default `folio_enrich_path` setting is the relative path `../folio-enrich/backend`, which resolves correctly when running pytest from the main repo but NOT from a worktree under `.claude/worktrees/`. The worktree test run required `FOLIO_INSIGHTS_FOLIO_ENRICH_PATH=/home/damienriehl/Coding Projects/folio-enrich/backend` to be passed as an env var. This is an environment/config issue unrelated to Plan 02-04 (pre-existing) — did not touch it per scope boundary. Logged here for awareness; a follow-up env-setup fix for worktrees would be a separate chore.

## Follow-ups / Known Gaps

Per the plan's `<output>` section, the minimum shipped in this plan is the Markdown export path + fixture existence. Full coverage for UAT tests 37-41 requires validating the other formats in a follow-up UAT sweep:

- **owl / ttl / jsonld** — depend on the FOLIO service (folio-enrich bridge) being configured; may fail in environments without the FOLIO ontology cache
- **html** — depends on template assets; needs a separate smoke test
- **--validate** (SHACL) — requires a healthy OWL export first; deferred

None of these are code defects in this plan — they're environment/service dependencies that the fixture now makes testable.

## Self-Check: PASSED

- scripts/seed_demo_corpus.py — FOUND
- output/demo/corpus-meta.json — FOUND
- output/demo/extraction.json — FOUND
- output/demo/review.db — FOUND
- output/demo/sources/demo-advocacy.md — FOUND
- .gitignore whitelist `!output/demo/` — FOUND
- Commit 293662a — FOUND (`feat(02-04): add output/demo/ approved-task fixture + seed script — UAT I-4`)
