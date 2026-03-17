---
phase: 01-knowledge-extraction-pipeline
plan: 03
subsystem: pipeline
tags: [confidence-gating, json-output, pipeline-orchestrator, cli, click, checkpointing, batch-processing]

# Dependency graph
requires:
  - phase: 01-01
    provides: "InsightsJob, InsightsPipelineStage ABC, IngestionStage, StructureParserStage"
  - phase: 01-02
    provides: "BoundaryDetectionStage, DistillerStage, KnowledgeClassifierStage, FolioTaggerStage, DeduplicatorStage"
provides:
  - "ConfidenceGate: partitions units by band (high/medium/low) with auto-approve for >=0.8"
  - "OutputFormatter: produces extraction.json, review.json, proposed_classes.json"
  - "PipelineOrchestrator: chains all 7 stages with checkpoint-based resume"
  - "PipelineCheckpoint: save/load/has/invalidate for stage-level resume"
  - "folio-insights extract <dir> CLI command: end-to-end batch extraction"
  - "folio-insights serve CLI placeholder for Plan 01-04"
affects: [01-04]

# Tech tracking
tech-stack:
  added: [click]
  patterns: [confidence-band-gating, checkpoint-resume, cli-with-click-group]

key-files:
  created:
    - src/folio_insights/quality/__init__.py
    - src/folio_insights/quality/confidence_gate.py
    - src/folio_insights/quality/output_formatter.py
    - src/folio_insights/pipeline/orchestrator.py
    - src/folio_insights/cli.py
    - tests/test_output.py
    - tests/test_cli.py
  modified:
    - src/folio_insights/__init__.py
    - pyproject.toml

key-decisions:
  - "PipelineCheckpoint uses static methods (not Pydantic model) for simpler save/load API"
  - "CLI validates source_dir existence and emptiness before invoking orchestrator"
  - "Output writes three separate JSON files: extraction.json (main), review.json (review report), proposed_classes.json (new FOLIO classes)"

patterns-established:
  - "Confidence band gating: high (>=0.8), medium (0.5-0.8), low (<0.5) with configurable thresholds"
  - "Checkpoint resume: JSON files per stage in {corpus}/checkpoints/ directory"
  - "CLI pattern: Click group with subcommands, local imports for lazy loading"

requirements-completed: [QUAL-01, QUAL-02, QUAL-03, PIPE-02]

# Metrics
duration: 6min
completed: 2026-03-17
---

# Phase 1 Plan 03: Quality Output and Pipeline Orchestration Summary

**Confidence-gated output layer with 3-file JSON output, 7-stage pipeline orchestrator with checkpoint resume, and `folio-insights extract` batch CLI**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-17T21:26:09Z
- **Completed:** 2026-03-17T21:32:28Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- ConfidenceGate partitions units into high/medium/low bands with auto-approve for high-confidence units (>=0.8) and flagging low-confidence (<0.5) for review
- OutputFormatter produces three JSON output files: extraction.json (full results with summary stats), review.json (auto-approved/needs-review/spot-check), proposed_classes.json (FOLIO tags lacking existing IRIs)
- PipelineOrchestrator chains all 7 extraction stages in order with checkpoint-based resume from last completed stage
- Click-based CLI with `folio-insights extract <dir>` command providing corpus name, output dir, confidence thresholds, resume, and verbose options
- CLI prints extraction summary with file count, unit count, and confidence breakdown
- 25 new tests (11 output + 14 CLI) all passing; full suite of 84 tests green

## Task Commits

Each task was committed atomically:

1. **Task 1: Quality output layer -- confidence gating and JSON formatting** - `dcc12a9` (feat)
2. **Task 2: Pipeline orchestrator and batch CLI** - `58c28de` (feat)

## Files Created/Modified
- `src/folio_insights/quality/__init__.py` - Quality module exposing ConfidenceGate and OutputFormatter
- `src/folio_insights/quality/confidence_gate.py` - Confidence-based filtering with configurable thresholds
- `src/folio_insights/quality/output_formatter.py` - JSON formatting for extraction, review, and proposed classes output
- `src/folio_insights/pipeline/orchestrator.py` - Pipeline orchestrator chaining 7 stages with checkpoint resume
- `src/folio_insights/cli.py` - Click CLI with extract and serve commands
- `src/folio_insights/__init__.py` - Updated main() to delegate to CLI
- `pyproject.toml` - Entry point updated to folio_insights.cli:cli
- `tests/test_output.py` - 11 tests for confidence gating and output formatting
- `tests/test_cli.py` - 14 tests for CLI, orchestrator, checkpoints, and end-to-end

## Decisions Made
- **PipelineCheckpoint as plain class:** Used static methods instead of Pydantic BaseModel for PipelineCheckpoint. The checkpoint data is serialized manually to JSON (with job.model_dump()), keeping the API simpler and avoiding a required `stage` field on construction.
- **Three separate output files:** Extraction results, review report, and proposed classes are written as separate JSON files rather than a single monolithic output. This supports different downstream consumers (review viewer reads extraction.json, reviewer reads review.json, FOLIO committee reads proposed_classes.json).
- **Local imports in CLI:** PipelineOrchestrator and Settings are imported inside the `extract()` function to avoid loading heavy bridge dependencies when only running `--help`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] PipelineCheckpoint was Pydantic BaseModel with required `stage` field**
- **Found during:** Task 2 (checkpoint tests)
- **Issue:** PipelineCheckpoint defined as BaseModel with `stage: str` required field, making `PipelineCheckpoint()` fail without arguments. The save/load/has/invalidate methods should be stateless.
- **Fix:** Converted PipelineCheckpoint from Pydantic BaseModel to plain class with static methods. Removed BaseModel/Field imports from orchestrator.
- **Files modified:** src/folio_insights/pipeline/orchestrator.py
- **Verification:** All 14 CLI tests pass including checkpoint save/load round-trip.
- **Committed in:** 58c28de (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Trivial design fix. No scope creep.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. The CLI uses default settings and discovers source files from the provided directory argument.

## Next Phase Readiness
- Full extraction pipeline is end-to-end operational: `folio-insights extract <dir>` runs all 7 stages and produces JSON output
- Plan 01-04 (review viewer) can consume extraction.json, review.json, and proposed_classes.json
- `folio-insights serve` placeholder is ready for Plan 01-04 to implement
- Confidence gating provides the auto-approve/needs-review split needed by the review viewer
- No blockers for Plan 01-04

## Self-Check: PASSED

All 7 created files verified present on disk. Both task commits (dcc12a9, 58c28de) verified in git log.

---
*Phase: 01-knowledge-extraction-pipeline*
*Completed: 2026-03-17*
