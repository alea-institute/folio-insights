---
phase: 01-knowledge-extraction-pipeline
plan: 01
subsystem: pipeline
tags: [pydantic, folio-enrich, bridge-adapter, ingestion, markdown, pdf, xml, corpus-registry, lxml]

# Dependency graph
requires: []
provides:
  - "folio-insights Python package (installable via pip install -e .)"
  - "KnowledgeUnit, KnowledgeType, ConceptTag, Span, StageEvent data models"
  - "InsightsJob and InsightsPipelineStage ABC for pipeline stages"
  - "Bridge adapters: FolioService (27K+ labels), EmbeddingService, normalizer, ingestion, LLM, mapper"
  - "CorpusRegistry for tracking processed files by SHA-256 content hash"
  - "IngestionStage supporting 14 file formats (MD, TXT, DOCX, PDF, HTML, RTF, EML, MSG, XML, CSV, XLSX, TSV, WPD)"
  - "StructureParserStage preserving heading hierarchy as section_path metadata"
affects: [01-02, 01-03, 01-04]

# Tech tracking
tech-stack:
  added: [pydantic, pydantic-settings, hatchling, lxml, sentence-transformers, instructor, click, aiosqlite, folio-python, httpx, rdflib]
  patterns: [bridge-adapter-via-sys-path, importlib-based-module-loading, pydantic-settings-singleton, corpus-manifest-json, pipeline-stage-abc]

key-files:
  created:
    - pyproject.toml
    - src/folio_insights/config.py
    - src/folio_insights/models/knowledge_unit.py
    - src/folio_insights/models/corpus.py
    - src/folio_insights/models/review.py
    - src/folio_insights/pipeline/stages/base.py
    - src/folio_insights/pipeline/stages/ingestion.py
    - src/folio_insights/pipeline/stages/structure_parser.py
    - src/folio_insights/services/bridge/folio_bridge.py
    - src/folio_insights/services/bridge/ingestion_bridge.py
    - src/folio_insights/services/bridge/llm_bridge.py
    - src/folio_insights/services/bridge/mapper_bridge.py
    - src/folio_insights/services/corpus_registry.py
    - tests/test_bridge.py
    - tests/test_ingestion.py
  modified: []

key-decisions:
  - "Used importlib for folio-mapper bridge to avoid sys.path namespace conflict with folio-enrich's app package"
  - "Added local markdown element parser to supplement folio-enrich's MarkdownIngestor which strips headings without returning structural elements"
  - "folio-python added as direct dependency for FolioService singleton access"

patterns-established:
  - "Bridge adapter: import folio-enrich services via sys.path manipulation, keep folio-enrich unmodified"
  - "importlib module loading: use importlib.util.spec_from_file_location for folio-mapper to avoid app package conflicts"
  - "Pipeline stage ABC: InsightsPipelineStage with name property + async execute(InsightsJob)"
  - "Corpus manifest: JSON persistence with SHA-256 content hash tracking"
  - "Element supplementation: when bridge ingestors return no structural elements, fall back to local parsers"

requirements-completed: [INGEST-01, INGEST-02, INGEST-03]

# Metrics
duration: 16min
completed: 2026-03-17
---

# Phase 1 Plan 01: Project Scaffolding and Ingestion Summary

**Greenfield folio-insights package with bridge adapters importing 27K+ FOLIO labels from folio-enrich, multi-format ingestion (14 extensions), and heading-hierarchy-aware structure parser**

## Performance

- **Duration:** 16 min
- **Started:** 2026-03-17T20:33:58Z
- **Completed:** 2026-03-17T20:50:06Z
- **Tasks:** 3
- **Files modified:** 32

## Accomplishments
- Installable folio-insights Python package with pyproject.toml, hatchling build, and all core dependencies
- Complete data model layer: KnowledgeUnit with 12 fields, KnowledgeType enum (5 types), ConceptTag, Span, StageEvent, CorpusDocument, CorpusManifest, ReviewDecision
- Bridge adapters successfully importing FolioService (27,770 labels), EmbeddingService, normalizer (nupunkt sentence splitting), AhoCorasickMatcher, CitationExtractor, and LLM registry from folio-enrich
- Multi-format ingestion stage handling 14 file extensions routed through folio-enrich bridge (7 formats), folio-mapper bridge (3 formats), lxml XML parser, and Doctor WPD converter
- Structure parser that builds heading hierarchy tree and attaches section_path to every element (e.g., ["Chapter 8", "Expert Witnesses", "Methodology Challenges"])
- Corpus registry tracking processed files by SHA-256 content hash, skipping unchanged files on re-run
- 10 passing tests: 3 bridge integration tests + 7 ingestion/structure tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Project scaffolding, data models, and pipeline base** - `d2671bd` (feat)
2. **Task 2: Bridge adapters, corpus registry, and tests** - `9cfb092` (feat)
3. **Task 3: Multi-format ingestion stage with document structure preservation** - `4559343` (feat)

## Files Created/Modified
- `pyproject.toml` - Package config with folio-insights name, hatchling build, all deps
- `.env.example` - Bridge paths, LLM config, confidence thresholds
- `.gitignore` - Python, venv, IDE, output exclusions
- `src/folio_insights/__init__.py` - Package root with version
- `src/folio_insights/config.py` - Settings via pydantic-settings with .env support, singleton cache
- `src/folio_insights/models/knowledge_unit.py` - KnowledgeUnit, KnowledgeType, ConceptTag, Span, StageEvent
- `src/folio_insights/models/corpus.py` - CorpusDocument, CorpusManifest
- `src/folio_insights/models/review.py` - ReviewStatus, ReviewDecision
- `src/folio_insights/pipeline/stages/base.py` - InsightsJob, InsightsPipelineStage ABC, record_lineage
- `src/folio_insights/pipeline/stages/ingestion.py` - IngestionStage with 14-format routing
- `src/folio_insights/pipeline/stages/structure_parser.py` - StructureParserStage, StructuredElement
- `src/folio_insights/services/bridge/folio_bridge.py` - FolioService, EmbeddingService, normalizer, citation extractor bridge
- `src/folio_insights/services/bridge/ingestion_bridge.py` - Multi-format file ingestion via folio-enrich
- `src/folio_insights/services/bridge/llm_bridge.py` - Per-task LLM routing with env var overrides
- `src/folio_insights/services/bridge/mapper_bridge.py` - Excel/CSV/TSV via importlib-loaded folio-mapper
- `src/folio_insights/services/corpus_registry.py` - SHA-256 hash tracking with JSON manifest
- `tests/conftest.py` - Shared fixtures (sample elements, knowledge unit, temp dirs, mock FolioService)
- `tests/test_bridge.py` - FolioService import, normalizer, settings isolation tests
- `tests/test_ingestion.py` - Directory ingestion, structure preservation, variable length, skip processed, XML, unknown format, structured elements tests

## Decisions Made
- **importlib for mapper bridge:** folio-mapper shares the `app` package name with folio-enrich. Using sys.path for both causes Python to resolve `app.models.document` from the wrong package. Solved by using importlib.util.spec_from_file_location for folio-mapper, keeping folio-enrich on sys.path as the canonical `app` package.
- **Local markdown parser:** folio-enrich's MarkdownIngestor only implements `ingest()` (returns stripped text), not `ingest_with_elements()`. Added `_parse_markdown_elements()` that reads raw markdown to extract heading levels and paragraph/list structure when the bridge returns no elements.
- **folio-python as direct dependency:** Added `folio-python>=0.1.5` to pyproject.toml since FolioService depends on it for FOLIO ontology access.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] sys.path conflict between folio-enrich and folio-mapper app packages**
- **Found during:** Task 3 (ingestion tests)
- **Issue:** Both folio-enrich and folio-mapper have `app/` packages. MapperBridge's `sys.path.insert(0, mapper_path)` caused Python to resolve `from app.models.document` from folio-mapper instead of folio-enrich.
- **Fix:** Replaced sys.path manipulation in mapper_bridge.py with importlib.util.spec_from_file_location to load folio-mapper modules directly from disk without polluting the namespace.
- **Files modified:** src/folio_insights/services/bridge/mapper_bridge.py
- **Verification:** All 10 tests pass; bridge tests confirm FolioService import works alongside mapper bridge.
- **Committed in:** 4559343 (Task 3 commit)

**2. [Rule 2 - Missing Critical] folio-enrich MarkdownIngestor lacks structural element output**
- **Found during:** Task 3 (structure preservation test)
- **Issue:** folio-enrich's MarkdownIngestor strips heading markers (`#`) and returns plain text without structural elements, making it impossible for StructureParserStage to build heading hierarchy.
- **Fix:** Added `_parse_markdown_elements()` in ingestion.py that reads raw markdown to extract heading levels and paragraph/list structure when the bridge returns no elements. Also added `_parse_plaintext_elements()` as fallback for other formats.
- **Files modified:** src/folio_insights/pipeline/stages/ingestion.py
- **Verification:** test_preserve_structure passes with correct section_path hierarchy.
- **Committed in:** 4559343 (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing critical)
**Impact on plan:** Both fixes essential for correct operation. No scope creep -- both address plan requirements that couldn't work with the upstream code as-is.

## Issues Encountered
- pytest-asyncio 1.3.0 was installed (newer than the 0.25.0 minimum in pyproject.toml) but works correctly with `asyncio_mode = "auto"` configuration.

## User Setup Required
None - no external service configuration required. The package uses default paths to folio-enrich and folio-mapper.

## Next Phase Readiness
- All data models defined and importable for Plan 01-02 (boundary detection)
- Bridge adapter proven: FolioService, EmbeddingService, normalizer, and ingestors all accessible
- IngestionStage and StructureParserStage ready to feed into downstream pipeline stages
- InsightsJob carries ingested data and structured elements through the pipeline
- No blockers for Plan 01-02

## Self-Check: PASSED

All 16 created files verified present on disk. All 3 task commits (d2671bd, 9cfb092, 4559343) verified in git log.

---
*Phase: 01-knowledge-extraction-pipeline*
*Completed: 2026-03-17*
