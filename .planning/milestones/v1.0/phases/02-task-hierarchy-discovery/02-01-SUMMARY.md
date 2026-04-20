---
phase: 02-task-hierarchy-discovery
plan: 01
subsystem: pipeline
tags: [pydantic, agglomerative-clustering, sentence-transformers, folio, llm, task-discovery]

# Dependency graph
requires:
  - phase: 01-knowledge-extraction-pipeline
    provides: KnowledgeUnit model, InsightsPipelineStage ABC, PipelineOrchestrator pattern, HeadingContextExtractor, LLMBridge, DeduplicatorStage
provides:
  - TaskCandidate, DiscoveredTask, Contradiction, TaskHierarchy, DiscoveryJob Pydantic models
  - DiscoveryStage ABC for second-pass pipeline
  - HeadingAnalysisStage (Stage 1) extracting task candidates from heading hierarchy
  - FolioMappingStage (Stage 2) resolving candidates to FOLIO concepts with weighted blend
  - ContentClusteringStage (Stage 3) discovering implicit tasks via embedding clustering
  - cluster_units_for_task_discovery agglomerative clustering function
  - LLM prompt templates for task discovery, ordering, jurisdiction detection
  - Wave 0 test scaffolds for TASK-01 through TASK-04
affects: [02-02, 02-03, 02-04, 02-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DiscoveryStage ABC: same contract as InsightsPipelineStage but typed for DiscoveryJob"
    - "Weighted confidence blend: 70% FOLIO + 30% heading for task assignment"
    - "Heading depth confidence: top-level=1.0, sub-heading=0.7, deep=0.4"
    - "Content clustering with agglomerative clustering, cosine affinity, average linkage"
    - "LLM fallback: graceful degradation when LLMBridge unavailable"

key-files:
  created:
    - src/folio_insights/models/task.py
    - src/folio_insights/pipeline/discovery/stages/base.py
    - src/folio_insights/pipeline/discovery/stages/heading_analysis.py
    - src/folio_insights/pipeline/discovery/stages/folio_mapping.py
    - src/folio_insights/pipeline/discovery/stages/content_clustering.py
    - src/folio_insights/services/task_clustering.py
    - src/folio_insights/services/prompts/task_discovery.py
    - tests/test_task_discovery.py
    - tests/test_hierarchy.py
    - tests/test_merging.py
    - tests/test_contradictions.py
  modified:
    - src/folio_insights/services/bridge/llm_bridge.py

key-decisions:
  - "DiscoveryStage ABC mirrors InsightsPipelineStage but uses DiscoveryJob to keep pipelines independent"
  - "Heading paths with < 2 knowledge units filtered out as too sparse for task candidates"
  - "FolioMappingStage marks unmapped candidates as proposed_siblings in job metadata"
  - "ContentClusteringStage skips clusters with > 70% overlap with existing heading candidates"
  - "LLM labeling gracefully degrades to word-based fallback when LLMBridge is unavailable"
  - "SentenceTransformer model loaded as lazy singleton to avoid repeated initialization"

patterns-established:
  - "DiscoveryStage ABC: name property + async execute(DiscoveryJob) -> DiscoveryJob"
  - "Weighted blend: compute_task_confidence(folio, heading, 0.7, 0.3)"
  - "Pipeline stages use lazy imports for external services (FolioService, LLMBridge)"
  - "Prompt templates use {placeholder} format with JSON output specification"

requirements-completed: [TASK-01]

# Metrics
duration: 4min
completed: 2026-03-19
---

# Phase 02 Plan 01: Task Discovery Models and Pipeline Stages Summary

**5 Pydantic data models, 3 discovery pipeline stages (heading analysis, FOLIO mapping, content clustering), agglomerative clustering service, and Wave 0 test scaffolds for all 4 phase requirements**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-19T20:38:59Z
- **Completed:** 2026-03-19T20:43:38Z
- **Tasks:** 2
- **Files modified:** 14

## Accomplishments
- All Phase 2 data models defined: TaskCandidate, DiscoveredTask, Contradiction, TaskHierarchy, DiscoveryJob with full field specs
- HeadingAnalysisStage groups units by source_section with depth-weighted confidence (1.0/0.7/0.4)
- FolioMappingStage resolves candidates to deepest FOLIO concept with weighted blend (70% FOLIO, 30% heading)
- ContentClusteringStage discovers implicit cross-cutting tasks via agglomerative clustering + LLM labeling
- LLMBridge extended with 4 new task names for Phase 2 pipeline
- 15 test stubs across 4 test files covering all Phase 2 requirements

## Task Commits

Each task was committed atomically:

1. **Task 1: Data models and discovery pipeline base** - `83a77fe` (feat)
2. **Task 2: Heading Analysis, FOLIO Mapping, and Content Clustering stages** - `bf806f6` (feat)

## Files Created/Modified
- `src/folio_insights/models/task.py` - TaskCandidate, DiscoveredTask, Contradiction, TaskHierarchy, DiscoveryJob models + compute_task_confidence
- `src/folio_insights/pipeline/discovery/__init__.py` - Package init for discovery pipeline
- `src/folio_insights/pipeline/discovery/stages/__init__.py` - Package init for discovery stages
- `src/folio_insights/pipeline/discovery/stages/base.py` - DiscoveryStage ABC typed for DiscoveryJob
- `src/folio_insights/pipeline/discovery/stages/heading_analysis.py` - Stage 1: heading-to-task extraction
- `src/folio_insights/pipeline/discovery/stages/folio_mapping.py` - Stage 2: FOLIO concept resolution with weighted blend
- `src/folio_insights/pipeline/discovery/stages/content_clustering.py` - Stage 3: implicit task discovery via clustering + LLM
- `src/folio_insights/services/task_clustering.py` - Agglomerative clustering with cosine affinity
- `src/folio_insights/services/prompts/task_discovery.py` - Task discovery, ordering, jurisdiction detection prompts
- `src/folio_insights/services/bridge/llm_bridge.py` - Extended INSIGHTS_TASKS with 4 Phase 2 task names
- `tests/test_task_discovery.py` - 5 test stubs for TASK-01
- `tests/test_hierarchy.py` - 4 test stubs for TASK-02
- `tests/test_merging.py` - 3 test stubs for TASK-03
- `tests/test_contradictions.py` - 3 test stubs for TASK-04

## Decisions Made
- DiscoveryStage ABC mirrors InsightsPipelineStage but uses DiscoveryJob to keep extraction and discovery pipelines independent
- Heading paths with fewer than 2 knowledge units filtered as too sparse for task candidates
- FolioMappingStage marks unmapped candidates as proposed_siblings in job metadata (not on TaskCandidate, which has no metadata field)
- ContentClusteringStage skips clusters with >70% overlap with existing heading candidates to avoid duplicates
- LLM labeling degrades gracefully to word-based fallback when LLMBridge is unavailable
- SentenceTransformer model loaded as lazy singleton to avoid repeated initialization cost

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Data models ready for Plans 02-04 (hierarchy construction, cross-source merging, contradiction detection)
- 3 of 6 pipeline stages implemented; remaining 3 stages in Plan 02-02
- Test scaffolds ready for Wave 0 -> Wave 1 promotion
- LLMBridge pre-extended with all Phase 2 task names

## Self-Check: PASSED

All 13 created files verified on disk. Both task commits (83a77fe, bf806f6) verified in git log.

---
*Phase: 02-task-hierarchy-discovery*
*Completed: 2026-03-19*
