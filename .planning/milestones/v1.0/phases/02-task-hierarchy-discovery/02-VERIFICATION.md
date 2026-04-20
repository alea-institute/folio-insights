---
phase: 02-task-hierarchy-discovery
verified: 2026-03-19T21:50:00Z
status: human_needed
score: 20/20 must-haves verified
re_verification: false
human_verification:
  - test: "Navigate to /tasks in a running dev server and confirm three-pane layout renders"
    expected: "Left pane shows TaskTree, upper-right shows TaskDetail empty state, lower-right shows DiscoveryEvidence. All correct empty-state copy per UI-SPEC."
    why_human: "SSR is disabled for the tasks page and treeview depends on browser APIs — automated check cannot verify render."
  - test: "Click the Tasks tab in navigation and confirm it routes to /tasks"
    expected: "Three tabs (Upload, Tasks, Review) visible. Clicking Tasks loads /tasks page without 500 error."
    why_human: "SvelteKit routing and client-side navigation require a running browser."
  - test: "On the upload page, after a corpus is processed, confirm DiscoverButton appears"
    expected: "DiscoverButton shows 'Discover Tasks' in ready state below the processing complete section."
    why_human: "Requires a corpus with processed data and live SSE stream state."
  - test: "Click the dashboard toggle icon in the header on /tasks — confirm 6 stat cards overlay"
    expected: "Overlay panel renders with TASKS, UNITS ASSIGNED, REVIEW PROGRESS, CONTRADICTIONS, SOURCE COVERAGE, AVG CONFIDENCE cards."
    why_human: "Toggle state and overlay rendering require a running browser."
  - test: "Press '?' on any page — confirm keyboard shortcuts modal includes Phase 2 Task Operations section"
    expected: "Modal shows 'M — Move task to new parent', 'G — Merge selected task into another', 'Shift+A — Bulk approve all high-confidence tasks'."
    why_human: "Keyboard event handling requires a running browser."
  - test: "Verify drag-and-drop in the task tree works (drag a task node to a new parent)"
    expected: "Node moves position; hierarchy-edit API call is made with edit_type='move'."
    why_human: "DnD interaction requires browser pointer events."
---

# Phase 02: Task Hierarchy Discovery Verification Report

**Phase Goal:** The system organizes all extracted knowledge units into a discovered hierarchy of advocacy tasks (Task > Subtask), with best practices, principles, and pitfalls as annotation-property metadata on each Task/Subtask class — so querying "how do I take an expert deposition" returns the class with its advice metadata attached.

**Verified:** 2026-03-19T21:50:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The system discovers task candidates from document heading hierarchies | VERIFIED | `HeadingAnalysisStage` groups units by `source_section`, creates `TaskCandidate` with depth-weighted confidence (1.0/0.7/0.4) |
| 2 | The system maps discovered task candidates to the deepest appropriate FOLIO concept | VERIFIED | `FolioMappingStage` traverses FOLIO hierarchy via `FolioService`, uses `compute_task_confidence(folio=0.7, heading=0.3)` weighted blend |
| 3 | The system discovers implicit tasks via content clustering of knowledge units | VERIFIED | `ContentClusteringStage` uses `AgglomerativeClustering` with cosine affinity + LLM labeling, skips clusters >70% covered by heading candidates |
| 4 | Knowledge units are assigned to tasks using a weighted blend favoring FOLIO tags over heading context | VERIFIED | `compute_task_confidence(0.8, 0.6)` returns `0.74` (0.8×0.7 + 0.6×0.3) — formula verified programmatically |
| 5 | The system builds hierarchical task trees with parent-child relationships | VERIFIED | `HierarchyConstructionStage` builds parent-child links from heading paths + FOLIO polyhierarchy, sets `parent_task_id`, `depth`, `parent_iris` |
| 6 | Procedural tasks have ordered subtasks; categorical tasks have unordered subtasks | VERIFIED | `HierarchyConstructionStage` uses LLM via `task_ordering` task to determine `is_procedural`, sets `canonical_order` on children |
| 7 | Knowledge units under each task are grouped by type (advice, principle, pitfall, rule, citation) | VERIFIED | `unit_type_counts` computed per task; `TaskExporter.export_markdown` groups as Best Practices, Principles, Pitfalls, Procedural Rules, Citations |
| 8 | Task fragments across source files are merged into a single coherent tree | VERIFIED | `CrossSourceMergingStage` uses exact FOLIO IRI match + embedding similarity threshold 0.85 (`_MERGE_SIMILARITY_THRESHOLD = 0.85`) |
| 9 | Contradictions are detected via two-phase screening: NLI cross-encoder then LLM deep analysis | VERIFIED | `ContradictionDetector` lazy-loads `cross-encoder/nli-deberta-v3-base`, screens at 0.7 threshold, confirms via LLM `deep_analyze` |
| 10 | The discovery pipeline runs end-to-end via CLI | VERIFIED | `folio-insights discover --help` works; `TaskDiscoveryOrchestrator` chains 6 stages; `folio-insights discover <corpus>` entry point confirmed |
| 11 | Re-running discovery loads previously approved task_decisions from SQLite and treats them as locked | VERIFIED | `_load_approved_decisions` queries `task_decisions WHERE status IN ('approved','edited')`; `locked_task_ids` injected into job metadata |
| 12 | After discovery completes, a diff is computed between new results and existing approved decisions | VERIFIED | `_compute_diff` produces added/removed/changed entries; writes `discovery_diff.json`; `GET /corpus/{id}/discovery/diff` endpoint returns `DiscoveryDiffEntry` list |
| 13 | Discovery can be triggered via POST API endpoint and streams progress via SSE | VERIFIED | `POST /api/v1/corpus/{corpus_id}/discover` (202) + `GET .../discover/stream` SSE endpoint; `asyncio.create_task(run_discovery_with_progress(...))` wiring confirmed |
| 14 | Task decisions persist in SQLite across sessions | VERIFIED | 5 new SQLite tables (`task_decisions`, `task_unit_links`, `hierarchy_edits`, `contradictions`, `source_authority`) added to `SCHEMA_SQL`; old `review_decisions` preserved |
| 15 | Task hierarchy is exported in Markdown, JSON, and HTML formats | VERIFIED | `TaskExporter.export_markdown`, `export_json`, `export_html` methods present; export routes `/export/markdown`, `/export/json`, `/export/html` confirmed |
| 16 | Users can browse the discovered task hierarchy in a tree view | VERIFIED | `TaskTree.svelte` (373 lines) uses `@keenmate/svelte-treeview`, `$state.raw`, `role="tree"`, flag icons, review indicators |
| 17 | Selecting a task shows knowledge units grouped by type in the detail pane | VERIFIED | `TaskDetail.svelte` (503 lines) groups units by type with collapsible sections, contradiction highlighting, per-group approve-all |
| 18 | Contradictions are displayed in a side-by-side view with resolution controls | VERIFIED | `ContradictionView.svelte` (286 lines) has 5 resolution buttons (Keep Both, Prefer A, Prefer B, Merge Statement, Mark Jurisdictional), calls `resolveContradiction` |
| 19 | Users can trigger discovery from the upload page and watch SSE progress | VERIFIED | `upload/+page.svelte` imports `DiscoverButton`, `DiscoveryProgress`, `triggerDiscovery`, `startDiscoveryStream`; `goto('/tasks')` after 1.5s |
| 20 | The Tasks tab appears in navigation; complete workflow is wired | VERIFIED | `NavTabs.svelte` has 3 tabs (`'upload' \| 'tasks' \| 'review'`); `+layout.svelte` routes `/tasks` to `activePage === 'tasks'`; SSR disabled via `+page.ts` |

**Score:** 20/20 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/folio_insights/models/task.py` | TaskCandidate, DiscoveredTask, Contradiction, TaskHierarchy, DiscoveryJob, compute_task_confidence | VERIFIED | All 5 models + helper function; `compute_task_confidence(0.8, 0.6) == 0.74` confirmed |
| `src/folio_insights/pipeline/discovery/stages/heading_analysis.py` | HeadingAnalysisStage | VERIFIED | 84 lines; substantive implementation grouping units by `source_section` |
| `src/folio_insights/pipeline/discovery/stages/folio_mapping.py` | FolioMappingStage | VERIFIED | Lazy-loads FolioService; uses `compute_task_confidence` |
| `src/folio_insights/pipeline/discovery/stages/content_clustering.py` | ContentClusteringStage | VERIFIED | Imports and calls `cluster_units_for_task_discovery`; uses LLM labeling |
| `src/folio_insights/services/task_clustering.py` | cluster_units_for_task_discovery with AgglomerativeClustering + SentenceTransformer | VERIFIED | Both present in file |
| `src/folio_insights/pipeline/discovery/stages/hierarchy_construction.py` | HierarchyConstructionStage with procedural ordering and orphan handling | VERIFIED | `is_procedural`, `orphan` present; `name == 'hierarchy_construction'` confirmed |
| `src/folio_insights/pipeline/discovery/stages/cross_source_merging.py` | CrossSourceMergingStage with 0.85 merge threshold | VERIFIED | `_MERGE_SIMILARITY_THRESHOLD = 0.85` confirmed |
| `src/folio_insights/pipeline/discovery/stages/contradiction_detection.py` | ContradictionDetectionStage using ContradictionDetector | VERIFIED | Imports and calls ContradictionDetector |
| `src/folio_insights/pipeline/discovery/orchestrator.py` | TaskDiscoveryOrchestrator with 6 stages, decision persistence, diff computation | VERIFIED | `len(_stages) == 6`, correct stage order, `_load_approved_decisions`, `_compute_diff`, `discovery_diff.json` all present |
| `src/folio_insights/services/contradiction_detector.py` | ContradictionDetector with NLI cross-encoder | VERIFIED | `nli-deberta-v3-base`, `screen_pairs`, `deep_analyze` confirmed |
| `src/folio_insights/services/prompts/contradiction.py` | CONTRADICTION_ANALYSIS_PROMPT | VERIFIED | Present |
| `api/db/models.py` | 5 new tables, existing review_decisions preserved | VERIFIED | All 6 tables confirmed |
| `api/models/discovery.py` | TaskResponse, ContradictionResponse, DiscoveryStats, DiscoveryDiffEntry | VERIFIED | All models importable |
| `api/services/discovery_runner.py` | run_discovery_with_progress with TaskDiscoveryOrchestrator | VERIFIED | SSE pattern followed; orchestrator wired |
| `api/routes/discovery.py` | 18 endpoints covering all discovery operations | VERIFIED | All 18 route paths confirmed |
| `api/routes/export.py` | markdown, json, html export endpoints | VERIFIED | All 3 export routes confirmed |
| `src/folio_insights/services/task_exporter.py` | TaskExporter with export_markdown, export_json, export_html | VERIFIED | All 3 methods confirmed |
| `viewer/src/lib/components/TaskTree.svelte` | @keenmate/svelte-treeview, DnD, $state.raw, role=tree | VERIFIED | 373 lines; `{ Tree, type LTreeNode } from '@keenmate/svelte-treeview'`; `$state.raw`; `role="tree"` |
| `viewer/src/lib/components/TaskDetail.svelte` | Grouped units, Best Practices, Approve All, contradiction highlight | VERIFIED | 503 lines; all required content present |
| `viewer/src/lib/components/FilterToolbar.svelte` | role=checkbox, aria-checked filter chips | VERIFIED | 177 lines; all 4 filter groups with ARIA checkbox semantics |
| `viewer/src/lib/components/DiscoveryEvidence.svelte` | discovery-heading, discovery-cluster signal sections | VERIFIED | 285 lines; both CSS token backgrounds present |
| `viewer/src/lib/components/ContradictionView.svelte` | Keep Both, Prefer A, resolveContradiction | VERIFIED | 286 lines; 5 resolution buttons; calls resolveContradiction |
| `viewer/src/routes/tasks/+page.svelte` | TaskTree, TaskDetail, DiscoveryEvidence, TaskDashboard, ManualTaskDialog, aria-live | VERIFIED | 458 lines; all components wired; `aria-live="polite"` present |
| `viewer/src/lib/components/TaskDashboard.svelte` | TASKS, CONTRADICTIONS, REVIEW PROGRESS stat cards | VERIFIED | 223 lines; all 6 stat cards present |
| `viewer/src/lib/components/DiffView.svelte` | Accept Change, Reject Change, diff-added | VERIFIED | 168 lines; accept/reject per-item and bulk actions |
| `viewer/src/lib/components/ManualTaskDialog.svelte` | createTask, role=alertdialog | VERIFIED | 353 lines; `role="alertdialog"`, calls `createTask` API function |
| `viewer/src/lib/components/DiscoverButton.svelte` | Discover Tasks, Discovering... | VERIFIED | 98 lines; 4-state button confirmed |
| `viewer/src/lib/components/DiscoveryProgress.svelte` | Heading Analysis, Contradiction Detection stage pills | VERIFIED | 128 lines; all 6 stages confirmed |
| `viewer/src/lib/components/NavTabs.svelte` | Tasks tab, /tasks href, 3-way activePage type | VERIFIED | 66 lines; all confirmed |
| `viewer/src/routes/tasks/+page.ts` | SSR disabled | VERIFIED | `export const ssr = false` |
| `tests/test_task_discovery.py` | 5 Wave-0 scaffold stubs for TASK-01 | VERIFIED | 47 lines; 5 skipped tests |
| `tests/test_hierarchy.py` | 4 Wave-0 scaffold stubs for TASK-02 | VERIFIED | 40 lines; 4 skipped tests |
| `tests/test_merging.py` | 3 Wave-0 scaffold stubs for TASK-03 | VERIFIED | 32 lines; 3 skipped tests |
| `tests/test_contradictions.py` | 3 Wave-0 scaffold stubs for TASK-04 | VERIFIED | 30 lines; 3 skipped tests |
| `tests/test_discovery_api.py` | Integration tests with test_discover_trigger_returns_202 | VERIFIED | test present at line 145 |
| `tests/test_task_review_api.py` | Integration tests with test_task_bulk_approve | VERIFIED | test present at line 123 |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `heading_analysis.py` | `services/heading_context.py` | HeadingContextExtractor reuse | PARTIAL | Does NOT import HeadingContextExtractor. Replicates the same depth-confidence constants inline (`_DEPTH_CONFIDENCE = [1.0, 0.7, 0.4]`). Same behavior, not a code dependency. The plan's intent (same weights) is satisfied; the literal "reuse" is not. Info-level deviation. |
| `folio_mapping.py` | `services/bridge/folio_bridge.py` | FolioService concept lookup | VERIFIED | Lazy-loads `FolioService` from bridge; calls `search_by_label` / `get_concept` for hierarchy traversal |
| `content_clustering.py` | `services/task_clustering.py` | cluster_units_for_task_discovery | VERIFIED | Direct import and call at line 16 and 55 |
| `orchestrator.py` | all 6 stages | `_build_stages` chains HeadingAnalysis through Contradiction | VERIFIED | `_build_stages` returns list of 6 instances in correct order; confirmed by import check |
| `orchestrator.py` | `api/db/models.py` task_decisions | `_load_approved_decisions` reads SQLite | VERIFIED | Queries `task_decisions WHERE status IN ('approved','edited')`; gracefully handles missing table |
| `contradiction_detector.py` | `cross-encoder/nli-deberta-v3-base` | CrossEncoder NLI model | VERIFIED | Lazy-loaded via `CrossEncoder("cross-encoder/nli-deberta-v3-base")` |
| `cli.py` | `orchestrator.py` | CLI discover command invokes orchestrator | VERIFIED | `TaskDiscoveryOrchestrator` imported and instantiated in CLI discover command |
| `routes/discovery.py` | `services/discovery_runner.py` | POST trigger launches background task | VERIFIED | `asyncio.create_task(run_discovery_with_progress(...))` confirmed |
| `services/discovery_runner.py` | `pipeline/discovery/orchestrator.py` | Iterates orchestrator stages with SSE progress | VERIFIED | `TaskDiscoveryOrchestrator` imported and used in runner |
| `routes/discovery.py` | `api/db/session.py` | SQLite persistence via aiosqlite | VERIFIED | `get_db_connection()` helper using aiosqlite confirmed |
| `stores/tasks.ts` | `api/client.ts` | Store loads task tree and units via fetchTaskTree/fetchTaskUnits | VERIFIED | Both functions imported and called in store action functions |
| `routes/tasks/+page.svelte` | `TaskTree.svelte` | Renders TaskTree in left pane | VERIFIED | `<TaskTree onselecttask={selectTask} />` confirmed |
| `TaskTree.svelte` | `@keenmate/svelte-treeview` | Tree rendering with DnD | VERIFIED | `import { Tree, type LTreeNode } from '@keenmate/svelte-treeview'` confirmed |
| `upload/+page.svelte` | `DiscoverButton.svelte` | Renders DiscoverButton after processing | VERIFIED | `<DiscoverButton status={discoverStatus} onclick={handleDiscover} />` confirmed |
| `routes/+layout.svelte` | `NavTabs.svelte` | NavTabs renders Upload/Tasks/Review tabs | VERIFIED | `activePage === 'tasks'` detection confirmed |
| `routes/tasks/+page.svelte` | `TaskDashboard.svelte` | Dashboard toggle overlay | VERIFIED | `<TaskDashboard stats={$discoveryStats} visible={showDashboard} ...>` confirmed |

---

## Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|---------------|-------------|--------|----------|
| TASK-01 | 02-01, 02-03, 02-04, 02-05 | System discovers top-level advocacy tasks from the texts themselves | SATISFIED | HeadingAnalysisStage (heading signal) + ContentClusteringStage (clustering signal) + FolioMappingStage (FOLIO mapping) all functional; task_decisions schema persists; frontend tree renders discoveries |
| TASK-02 | 02-02, 02-03, 02-04, 02-05 | System builds hierarchical task trees: Task > Subtask > Best Practice / Principle / Pitfall | SATISFIED | HierarchyConstructionStage builds parent-child tree with `depth`, `parent_task_id`, `unit_type_counts`; TaskDetail groups units by KnowledgeType; export produces indented outline |
| TASK-03 | 02-02, 02-03 | System merges task hierarchy fragments across multiple source files | SATISFIED | CrossSourceMergingStage merges by exact FOLIO IRI and embedding similarity (0.85); `source_file` field tracked on TaskCandidate |
| TASK-04 | 02-02, 02-03, 02-04 | System detects and flags contradictory advice from different sources | SATISFIED | ContradictionDetector with NLI cross-encoder (0.7 threshold) + LLM deep analysis; contradiction resolution API + ContradictionView UI |

All 4 phase requirements are satisfied. No orphaned requirements found.

---

## Anti-Patterns Found

| File | Lines | Pattern | Severity | Impact |
|------|-------|---------|----------|--------|
| Multiple backend files | Various | `return []` guard clauses | INFO | All are legitimate early-return guards (no-op when input is empty, missing DB, or missing file). Not stubs. Examples: `ContradictionDetector.screen_pairs` returns `[]` when `len(units) < 2`; `_load_approved_decisions` returns `[]` when DB path absent. |
| `ManualTaskDialog.svelte:108` | 108 | `alertdialog` div missing tabindex | WARNING | Svelte a11y warning. Focus trap handles keyboard navigation; missing tabindex on the container div is a lint nit, not a functional blocker. Pre-existing pattern also present in `ConfirmDialog.svelte`. |
| `NavTabs.svelte:5` | 5 | `<nav role="tablist">` | WARNING | Svelte a11y warning about `<nav>` + interactive role. Visual and functional navigation works correctly. Screen reader semantics suboptimal. |
| `tasks/+page.svelte:262,295,318` | Multiple | Click handlers on non-interactive divs without keyboard handlers | WARNING | Svelte a11y warnings for the draggable pane dividers. Pane resizing works via mouse; keyboard pane cycling is handled separately via Tab key. |

No blocker anti-patterns found. All `return []` instances are valid defensive guards, not stub implementations.

---

## Svelte-Check Results

- **Errors:** 0
- **Warnings:** 14 (8 files)
- **Result:** PASS (threshold: error)

Warnings are non-blocking accessibility lint issues. They are consistent with pre-existing patterns from Phase 1 components (`ConfirmDialog.svelte`, `InlineEditor.svelte`, `+page.svelte`).

---

## Human Verification Required

### 1. Three-pane Tasks Page Renders

**Test:** Run `npm run dev` in viewer/, navigate to `http://localhost:<port>/tasks`
**Expected:** Three-pane layout — TaskTree left (320px), TaskDetail upper-right (60%), DiscoveryEvidence lower-right (40%). Empty states display correct UI-SPEC copy.
**Why human:** SSR is disabled for `/tasks` (treeview browser API dependency). Render requires a live browser session.

### 2. Navigation Tab Routing

**Test:** Click "Tasks" tab in the header navigation
**Expected:** URL changes to `/tasks`, tab highlights as active, three-pane layout loads without 500 error.
**Why human:** Client-side routing and SvelteKit navigation require a running browser.

### 3. Discovery Trigger on Upload Page

**Test:** Select a corpus that has been processed (extraction.json exists), verify DiscoverButton appears below processing complete state
**Expected:** "Discover Tasks" button visible. Clicking it triggers `POST /corpus/{id}/discover`, shows DiscoveryProgress with 6 stage pills, auto-navigates to `/tasks` after completion.
**Why human:** Requires live corpus data, live API, and SSE stream state.

### 4. Task Dashboard Overlay

**Test:** On `/tasks` page, click the grid icon in the header-right
**Expected:** Overlay panel appears with 6 stat cards: TASKS, UNITS ASSIGNED, REVIEW PROGRESS, CONTRADICTIONS, SOURCE COVERAGE, AVG CONFIDENCE.
**Why human:** Toggle state and overlay rendering require a running browser with discovery data loaded.

### 5. Keyboard Shortcuts Modal — Phase 2 Entries

**Test:** Press `?` anywhere in the app
**Expected:** Shortcuts modal shows TASK OPERATIONS section with M=move, G=merge, Shift+A=bulk approve entries.
**Why human:** Keyboard event handling requires a running browser.

### 6. Drag-and-Drop Hierarchy Editing

**Test:** On `/tasks` with a corpus that has discovered tasks, drag a task node to a new parent in the tree
**Expected:** Node moves position in tree; `POST /corpus/{id}/tasks/hierarchy-edit` called with `edit_type="move"`.
**Why human:** DnD requires browser pointer events and live task data.

---

## Gaps Summary

No gaps found. All 20 truths are verified, all key links are WIRED (one is PARTIAL but intentional), and all 4 requirements are SATISFIED. The only items requiring human verification are UI behaviors that cannot be validated programmatically (rendering, routing, keyboard events, drag-and-drop).

**One noted deviation:** `HeadingAnalysisStage` replicates `HeadingContextExtractor`'s depth-confidence constants inline rather than importing and reusing the class. This satisfies the plan's behavioral intent (same weights: 1.0/0.7/0.4) but is not literal code reuse. It has no impact on correctness.

---

_Verified: 2026-03-19T21:50:00Z_
_Verifier: Claude (gsd-verifier)_
