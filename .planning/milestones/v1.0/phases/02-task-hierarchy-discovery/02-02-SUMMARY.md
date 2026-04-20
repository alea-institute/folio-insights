---
phase: 02-task-hierarchy-discovery
plan: 02
subsystem: pipeline
tags: [cross-encoder, nli, contradiction-detection, hierarchy, merging, orchestrator, cli, aiosqlite]

# Dependency graph
requires:
  - phase: 02-task-hierarchy-discovery
    provides: TaskCandidate, DiscoveredTask, Contradiction, TaskHierarchy, DiscoveryJob models; DiscoveryStage ABC; HeadingAnalysisStage, FolioMappingStage, ContentClusteringStage; task_clustering service; LLM prompt templates
provides:
  - HierarchyConstructionStage building parent-child task tree from headings and FOLIO concepts
  - CrossSourceMergingStage consolidating duplicate tasks by IRI and embedding similarity
  - ContradictionDetectionStage with two-phase NLI + LLM screening
  - ContradictionDetector service with lazy-loaded cross-encoder/nli-deberta-v3-base
  - TaskDiscoveryOrchestrator chaining all 6 stages with checkpoint resume and decision persistence
  - DiscoveryCheckpoint for serializing/restoring DiscoveryJob state
  - CLI discover command with configurable thresholds
  - Diff computation for frontend DiffView (added/removed/changed tasks)
affects: [02-03, 02-04, 02-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-phase contradiction detection: fast NLI cross-encoder screening (0.7 threshold) then LLM deep analysis"
    - "Jurisdiction sensitivity detection via regex heuristic on unit texts"
    - "Orphan unit assignment by embedding similarity to task centroids"
    - "Cross-source merging: exact IRI match + fuzzy embedding similarity (0.85 threshold)"
    - "Decision persistence: load approved tasks from SQLite before pipeline, treat as locked"
    - "Diff computation: compare post-run hierarchy against pre-run approved state"
    - "DiscoveryCheckpoint: same pattern as PipelineCheckpoint but typed for DiscoveryJob"

key-files:
  created:
    - src/folio_insights/pipeline/discovery/stages/hierarchy_construction.py
    - src/folio_insights/pipeline/discovery/stages/cross_source_merging.py
    - src/folio_insights/pipeline/discovery/stages/contradiction_detection.py
    - src/folio_insights/pipeline/discovery/orchestrator.py
    - src/folio_insights/services/contradiction_detector.py
    - src/folio_insights/services/prompts/contradiction.py
  modified:
    - src/folio_insights/cli.py

key-decisions:
  - "HierarchyConstructionStage uses regex heuristic (not LLM) for jurisdiction sensitivity detection to avoid LLM calls per unit"
  - "Orphan units assigned by computing task centroids from linked unit embeddings, then cosine similarity to orphan"
  - "CrossSourceMergingStage requires different source_file for embedding merge to avoid merging same-file tasks"
  - "ContradictionDetector lazy-loads NLI model on first use to avoid heavy imports at startup"
  - "DiscoveryCheckpoint stored in separate discovery_checkpoints/ dir to avoid collision with extraction checkpoints"
  - "CLI discover command checks for review.db existence for optional decision persistence"

patterns-established:
  - "Locked task IDs: stages check job.metadata['locked_task_ids'] and skip those tasks"
  - "Diff computation: added/removed/changed entries comparing pre-run vs post-run task state"
  - "NLI batch prediction in groups of 64 pairs for cross-encoder efficiency"
  - "Two-strategy merging: exact IRI match first, then fuzzy embedding similarity"

requirements-completed: [TASK-02, TASK-03, TASK-04]

# Metrics
duration: 6min
completed: 2026-03-19
---

# Phase 02 Plan 02: Task Discovery Pipeline Stages 4-6, Orchestrator, and CLI Summary

**Full 6-stage discovery pipeline with hierarchy construction, cross-source merging, two-phase NLI+LLM contradiction detection, decision-persistent orchestrator, and CLI discover command**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-19T20:46:53Z
- **Completed:** 2026-03-19T20:53:16Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- HierarchyConstructionStage builds parent-child trees from heading paths and FOLIO concepts with procedural ordering, orphan assignment, jurisdiction detection, and unit type grouping
- CrossSourceMergingStage merges duplicate tasks across files via FOLIO IRI exact match and embedding similarity (>0.85 threshold)
- ContradictionDetectionStage uses two-phase approach: fast NLI cross-encoder screening at 0.7 threshold then LLM deep analysis for nuanced contradiction assessment
- TaskDiscoveryOrchestrator chains all 6 stages with checkpoint-based resume, loads approved decisions from SQLite, and computes diff for frontend DiffView
- CLI discover subcommand enables batch invocation with configurable cluster and contradiction thresholds

## Task Commits

Each task was committed atomically:

1. **Task 1: Hierarchy Construction, Cross-Source Merging, and Contradiction Detection stages** - `5589978` (feat)
2. **Task 2: TaskDiscoveryOrchestrator and CLI discover command** - `8dd5f59` (feat)

## Files Created/Modified
- `src/folio_insights/pipeline/discovery/stages/hierarchy_construction.py` - Stage 4: builds parent-child tree, assigns orphans, detects procedural ordering and jurisdiction sensitivity
- `src/folio_insights/pipeline/discovery/stages/cross_source_merging.py` - Stage 5: merges duplicate tasks by IRI and embedding similarity
- `src/folio_insights/pipeline/discovery/stages/contradiction_detection.py` - Stage 6: NLI screening + LLM deep analysis for contradictions
- `src/folio_insights/services/contradiction_detector.py` - Two-phase detector with lazy-loaded cross-encoder/nli-deberta-v3-base
- `src/folio_insights/services/prompts/contradiction.py` - CONTRADICTION_ANALYSIS_PROMPT template for LLM deep analysis
- `src/folio_insights/pipeline/discovery/orchestrator.py` - TaskDiscoveryOrchestrator with 6 stages, checkpoints, decision persistence, diff computation
- `src/folio_insights/cli.py` - Added discover subcommand with --cluster-threshold and --contradiction-threshold

## Decisions Made
- HierarchyConstructionStage uses regex heuristic for jurisdiction sensitivity detection instead of LLM calls per unit (faster, avoids LLM dependency for simple pattern matching)
- Orphan units assigned by computing task centroids from linked unit text embeddings (reuses existing SentenceTransformer singleton)
- CrossSourceMergingStage requires different source_file metadata for embedding merges to avoid false merges within the same document
- ContradictionDetector lazy-loads NLI model on first call to avoid heavy imports at CLI startup
- Discovery checkpoints stored in discovery_checkpoints/ subdirectory (separate from extraction checkpoints/)
- CLI discover command checks for review.db existence before passing db_path to orchestrator

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Full 6-stage discovery pipeline ready for end-to-end execution via CLI or programmatic invocation
- Orchestrator ready for Plan 02-03 (API endpoints: discovery trigger, task CRUD, review workflow)
- Decision persistence mechanism ready for Plan 02-03 (task_decisions SQLite table creation)
- Diff computation ready for Plan 02-05 (DiffView.svelte component)
- Task tree JSON output ready for Plan 02-04 (TaskTree.svelte viewer component)

## Self-Check: PASSED

All 7 created/modified files verified on disk. Both task commits (5589978, 8dd5f59) verified in git log.

---
*Phase: 02-task-hierarchy-discovery*
*Completed: 2026-03-19*
