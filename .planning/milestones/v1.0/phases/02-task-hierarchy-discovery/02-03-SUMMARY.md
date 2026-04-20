---
phase: 02-task-hierarchy-discovery
plan: 03
subsystem: api
tags: [fastapi, aiosqlite, sse, pydantic, discovery-api, task-crud, contradictions, export, markdown, json, html]

# Dependency graph
requires:
  - phase: 02-task-hierarchy-discovery
    provides: TaskDiscoveryOrchestrator, DiscoveryStage ABC, all 6 pipeline stages, DiscoveredTask/TaskHierarchy/Contradiction models, CLI discover command
provides:
  - Extended SQLite schema with 5 new tables (task_decisions, task_unit_links, hierarchy_edits, contradictions, source_authority) and 6 indexes
  - Discovery trigger API with SSE progress streaming (mirrors processing.py pattern)
  - Task tree endpoint returning nested hierarchy from SQLite
  - Task CRUD endpoints (create manual, delete with orphaning)
  - Task review endpoints (single review, bulk approve by IDs or confidence)
  - Contradiction list/detail/resolve endpoints
  - Hierarchy edit endpoint (move, merge operations)
  - Source authority management (list, upsert)
  - Discovery statistics endpoint
  - Discovery diff endpoint for DiffView frontend
  - Multi-format export (Markdown outline, structured JSON, dark-theme HTML report)
  - TaskExporter service with group_units_by_type helper
  - Pydantic models for all API request/response types
  - Discovery runner with per-stage SSE updates and SQLite persistence
affects: [02-04, 02-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Discovery job key: {corpus_id}_discovery to distinguish from extraction jobs in same JobManager"
    - "TaskExporter produces three output formats from same SQLite data source"
    - "Discovery runner persists tasks, unit links, and contradictions to SQLite after pipeline completion"
    - "Separate discovery_job_manager singleton paralleling processing's job_manager pattern"

key-files:
  created:
    - api/db/models.py (extended with 5 tables)
    - api/models/discovery.py
    - api/services/discovery_runner.py
    - api/routes/discovery.py
    - api/routes/export.py
    - src/folio_insights/services/task_exporter.py
    - tests/test_discovery_api.py
    - tests/test_task_review_api.py
  modified:
    - api/main.py

key-decisions:
  - "Discovery jobs use {corpus_id}_discovery key in same JobManager to coexist with extraction jobs"
  - "Task tree built from SQLite queries (task_decisions + task_unit_links) rather than reading JSON files"
  - "Bulk approve by confidence reads task_tree.json for confidence scores not stored in SQLite"
  - "Hierarchy merge operation uses UPDATE OR IGNORE for unit links then deletes conflicting duplicates"
  - "HTML export uses inline dark-theme CSS matching app.css variables for consistent visual identity"

patterns-established:
  - "Discovery API follows same prefix/pattern as processing API: trigger returns 202, SSE polls job file"
  - "All discovery endpoints scoped by corpus_id in URL path for multi-corpus support"
  - "Task review follows same approve/reject/edit pattern as unit review from Phase 1"

requirements-completed: [TASK-01, TASK-02, TASK-03, TASK-04]

# Metrics
duration: 7min
completed: 2026-03-19
---

# Phase 02 Plan 03: Discovery API Layer Summary

**Complete backend API for task discovery with SSE progress, task CRUD, review workflow, contradiction resolution, hierarchy editing, source authority, and multi-format export**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-19T20:57:14Z
- **Completed:** 2026-03-19T21:04:56Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- Extended SQLite schema with 5 new tables and 6 indexes for task decisions, unit links, hierarchy edits, contradictions, and source authority
- Created 18 API endpoints covering discovery trigger/SSE, task tree, task CRUD, review (single + bulk), contradiction management, hierarchy edits, source authority, stats, diff, and export
- TaskExporter produces Markdown outline (indented with unit groupings), structured JSON (nested tree with metadata), and dark-theme HTML report (collapsible sections, unit tables, contradiction highlights)
- 14 integration tests covering all endpoint categories, 127/127 full suite passes with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: SQLite schema extension, Pydantic models, and discovery runner** - `9639651` (feat)
2. **Task 2: Discovery, task review, and export API endpoints** - `1175be2` (feat)

## Files Created/Modified
- `api/db/models.py` - Extended SCHEMA_SQL with task_decisions, task_unit_links, hierarchy_edits, contradictions, source_authority tables and 6 indexes
- `api/models/discovery.py` - Pydantic models: TaskResponse, TaskTreeNode, TaskReviewRequest, TaskCreateRequest, TaskBulkApproveRequest, ContradictionResponse, ContradictionResolveRequest, HierarchyEditRequest, SourceAuthorityRequest, DiscoveryStats, DiscoveryDiffEntry, DiscoveryJob
- `api/services/discovery_runner.py` - run_discovery_with_progress following pipeline_runner pattern with per-stage SSE updates and _persist_discovery_to_sqlite
- `api/routes/discovery.py` - 18 endpoints: discovery trigger/stream/job/diff, task tree/detail/units/review/bulk-approve/create/delete, hierarchy-edit, contradictions list/get/resolve, source-authority list/upsert, stats
- `api/routes/export.py` - Export endpoints for markdown, JSON, HTML formats
- `src/folio_insights/services/task_exporter.py` - TaskExporter with export_markdown, export_json, export_html methods and group_units_by_type helper
- `api/main.py` - Registered discovery and export routers
- `tests/test_discovery_api.py` - 9 integration tests for discovery trigger, tree, review, contradictions, export, stats
- `tests/test_task_review_api.py` - 5 integration tests for bulk approve, task create, delete, hierarchy edit, source authority

## Decisions Made
- Discovery jobs use `{corpus_id}_discovery` key in the same JobManager directory to coexist with extraction jobs without requiring a separate persistence layer
- Task tree built from SQLite queries (task_decisions JOIN task_unit_links) for real-time accuracy rather than reading static JSON files
- Bulk approve by confidence reads task_tree.json for confidence scores since confidence is computed by the pipeline but not stored in task_decisions table
- Hierarchy merge operation uses UPDATE OR IGNORE for unit link reassignment, then deletes remaining conflicting duplicate links
- HTML export uses inline dark-theme CSS matching the app.css design system variables for consistent visual identity

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Test for discover trigger patched the wrong module path (patched route module but function is imported at call time from services module); fixed by patching `api.services.discovery_runner.run_discovery_with_progress` instead

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 18 API endpoints ready for Plan 02-04 (SvelteKit task viewer frontend)
- Task tree endpoint returns nested JSON matching TaskTreeNode model expected by TaskTree.svelte
- Export endpoints ready for export UI buttons in Plan 02-05
- Discovery trigger + SSE stream ready for "Discover Tasks" button integration
- Contradiction endpoints ready for ContradictionPanel.svelte component
- Statistics endpoint ready for summary dashboard widget

## Self-Check: PASSED

All 9 created/modified files verified on disk. Both task commits (9639651, 1175be2) verified in git log.

---
*Phase: 02-task-hierarchy-discovery*
*Completed: 2026-03-19*
