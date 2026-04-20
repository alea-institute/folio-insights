---
phase: 01-knowledge-extraction-pipeline
plan: 02
subsystem: pipeline
tags: [boundary-detection, sentence-transformers, instructor, folio-tagging, reconciliation, deduplication, novelty-scoring, classification, embedding]

# Dependency graph
requires:
  - phase: 01-01
    provides: "KnowledgeUnit models, InsightsJob, InsightsPipelineStage ABC, bridge adapters, StructuredElement"
provides:
  - "BoundaryDetectionStage: tiered split (structural/semantic/LLM) into one-idea-per-unit KnowledgeUnits"
  - "DistillerStage: LLM-driven text compression preserving tactical nuance"
  - "KnowledgeClassifierStage: 5-type classification + novelty scoring + citation detection"
  - "FolioTaggerStage: four-path FOLIO concept extraction (EntityRuler, LLM, Semantic, Heading Context)"
  - "DeduplicatorStage: exact hash + near-duplicate embedding dedup across documents"
  - "FourPathReconciler: extends folio-enrich 2-path to 4-path reconciliation"
  - "HeadingContextExtractor: document structure -> FOLIO concept mapping with proximity weighting"
  - "Prompt templates for boundary, distillation, classification, and novelty scoring"
affects: [01-03, 01-04]

# Tech tracking
tech-stack:
  added: [sentence-transformers, numpy]
  patterns: [tiered-boundary-detection, four-path-folio-extraction, proximity-weighted-heading-context, exact-and-near-dedup]

key-files:
  created:
    - src/folio_insights/services/boundary/__init__.py
    - src/folio_insights/services/boundary/structural.py
    - src/folio_insights/services/boundary/semantic.py
    - src/folio_insights/services/boundary/llm_refiner.py
    - src/folio_insights/pipeline/stages/boundary_detection.py
    - src/folio_insights/pipeline/stages/distiller.py
    - src/folio_insights/pipeline/stages/knowledge_classifier.py
    - src/folio_insights/pipeline/stages/folio_tagger.py
    - src/folio_insights/pipeline/stages/deduplicator.py
    - src/folio_insights/services/bridge/reconciliation_bridge.py
    - src/folio_insights/services/heading_context.py
    - src/folio_insights/services/prompts/__init__.py
    - src/folio_insights/services/prompts/boundary.py
    - src/folio_insights/services/prompts/classification.py
    - src/folio_insights/services/prompts/distillation.py
    - src/folio_insights/services/prompts/novelty.py
    - tests/test_extraction.py
    - tests/test_folio_tagging.py
    - tests/test_classification.py
    - tests/test_dedup.py
  modified: []

key-decisions:
  - "Tier 1 structural heuristics handle headings (conf 1.0), list items (0.9), paragraphs (0.7), transition words (0.8)"
  - "Tier 2 semantic segmentation uses all-MiniLM-L6-v2 with cosine similarity threshold 0.3"
  - "FourPathReconciler wraps folio-enrich Reconciler unmodified; adds semantic (+0.1 boost) and heading (+0.05 boost) on top"
  - "HeadingContextExtractor uses proximity weights: immediate=1.0, parent=0.7, chapter=0.4"
  - "Near dedup threshold set to cosine similarity > 0.85 based on folio-enrich's EMBEDDING_AUTO_RESOLVE_THRESHOLD"

patterns-established:
  - "Tiered boundary detection: structural -> semantic -> LLM fallback cascade"
  - "Four-path FOLIO extraction: EntityRuler + LLM + Semantic + Heading Context run independently then reconcile"
  - "Proximity-weighted heading context: most specific heading gets weight 1.0, parents decay"
  - "Exact + near dedup: content_hash for identical, embedding cosine for paraphrased duplicates"
  - "Prompt template pattern: module per task with string format placeholders {text}, {section_path}"

requirements-completed: [EXTRACT-01, EXTRACT-02, EXTRACT-03, EXTRACT-04, EXTRACT-05, EXTRACT-06, CLASS-01, CLASS-02, CLASS-03, FOLIO-01, FOLIO-02, FOLIO-03, FOLIO-04]

# Metrics
duration: 9min
completed: 2026-03-17
---

# Phase 1 Plan 02: Core Extraction Pipeline Summary

**Tiered boundary detection (structural/semantic/LLM), five-type knowledge classifier with novelty scoring, four-path FOLIO concept tagger with heading context, and cross-document deduplicator**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-17T21:10:06Z
- **Completed:** 2026-03-17T21:19:04Z
- **Tasks:** 3
- **Files modified:** 20

## Accomplishments
- Tiered boundary detection splits text into one-idea-per-unit knowledge units with structural heuristics handling ~70-80%, embedding segmentation ~15-20%, and LLM refinement ~5%
- DistillerStage compresses knowledge unit text to core insight while preserving tactical nuance via LLM
- KnowledgeClassifierStage classifies units into 5 types (advice, principle, citation, procedural_rule, pitfall) with eyecite citation override and novelty scoring 0.0-1.0
- FolioTaggerStage runs all four extraction paths (EntityRuler, LLM, Semantic, Heading Context) and reconciles via FourPathReconciler
- HeadingContextExtractor maps document headings to FOLIO concepts with proximity weighting (1.0/0.7/0.4)
- DeduplicatorStage catches exact duplicates (SHA-256 hash) and near-duplicates (embedding cosine > 0.85) across documents
- Full lineage trail on every unit tracking each processing stage
- 39 passing tests across all four test files

## Task Commits

Each task was committed atomically:

1. **Task 1: Tiered boundary detection and idea distillation** - `d1c3bc4` (feat)
2. **Task 2: FOLIO four-path tagging, heading context, and reconciliation bridge** - `14ad9ce` (feat)
3. **Task 3: Knowledge classification, novelty scoring, and deduplication** - `961fc36` (feat)

## Files Created/Modified
- `src/folio_insights/services/boundary/structural.py` - Tier 1: headings, bullets, paragraph breaks, transition words
- `src/folio_insights/services/boundary/semantic.py` - Tier 2: sentence-transformers cosine similarity topic shift detection
- `src/folio_insights/services/boundary/llm_refiner.py` - Tier 3: instructor-based LLM boundary refinement
- `src/folio_insights/pipeline/stages/boundary_detection.py` - BoundaryDetectionStage orchestrating all three tiers
- `src/folio_insights/pipeline/stages/distiller.py` - DistillerStage compressing text to core insight
- `src/folio_insights/pipeline/stages/knowledge_classifier.py` - KnowledgeClassifierStage with 5-type classification + novelty
- `src/folio_insights/pipeline/stages/folio_tagger.py` - FolioTaggerStage with four extraction paths
- `src/folio_insights/pipeline/stages/deduplicator.py` - DeduplicatorStage with exact + near dedup
- `src/folio_insights/services/bridge/reconciliation_bridge.py` - FourPathReconciler extending 2-path to 4-path
- `src/folio_insights/services/heading_context.py` - HeadingContextExtractor with proximity weighting
- `src/folio_insights/services/prompts/boundary.py` - Boundary refinement prompt with grounding rules
- `src/folio_insights/services/prompts/distillation.py` - Distillation prompt preserving tactical nuance
- `src/folio_insights/services/prompts/classification.py` - Classification prompt listing all 5 types
- `src/folio_insights/services/prompts/novelty.py` - Novelty scoring prompt with calibrated 0.0-1.0 scale
- `tests/test_extraction.py` - 10 tests: structural, semantic, distillation, lineage
- `tests/test_folio_tagging.py` - 10 tests: four-path, heading context, proximity, extraction path
- `tests/test_classification.py` - 12 tests: all types, novelty, citation, prompts
- `tests/test_dedup.py` - 7 tests: exact, near, cross-doc, confidence, lineage

## Decisions Made
- **Structural confidence tiers:** Headings get 1.0 (definite boundary), list items 0.9, paragraph breaks 0.7, transition words 0.8. These values reflect structural certainty.
- **Semantic threshold 0.3:** Conservative cosine similarity threshold for topic shift detection; lower values would over-split.
- **FourPathReconciler wraps base Reconciler:** The proven 2-path reconciliation is untouched. Semantic path adds +0.1 confidence boost to matching concepts; heading context adds +0.05. New concepts from either path are added as suggestions.
- **Proximity weights 1.0/0.7/0.4:** Immediate subheading is strongest signal, parent is medium, chapter title is weakest. Derived from the "unbake the cake" principle in CONTEXT.md.
- **Near dedup at 0.85:** Matches folio-enrich's EMBEDDING_AUTO_RESOLVE_THRESHOLD for consistency.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All five extraction pipeline stages are ready: BoundaryDetection -> Distiller -> KnowledgeClassifier -> FolioTagger -> Deduplicator
- Plan 01-03 (review viewer backend) can consume the pipeline output (KnowledgeUnit objects with folio_tags, confidence, surprise_score)
- Plan 01-04 (quality output) can read units from the pipeline
- No blockers for remaining Phase 1 plans

## Self-Check: PASSED

All 20 created files verified present on disk. All 3 task commits (d1c3bc4, 14ad9ce, 961fc36) verified in git log.

---
*Phase: 01-knowledge-extraction-pipeline*
*Completed: 2026-03-17*
