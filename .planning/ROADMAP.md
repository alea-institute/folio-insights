# Roadmap: Alea Advocate

## Overview

Alea Advocate delivers a batch pipeline that extracts structured advocacy knowledge from legal textbooks and maps it into the FOLIO ontology. The pipeline has strict stage dependencies: knowledge units must be extracted and FOLIO-tagged before task hierarchies can be discovered, and task hierarchies must exist before OWL output can be generated. This roadmap follows those natural data dependencies across three phases, progressing from raw MD input to validated ontology output.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Knowledge Extraction Pipeline** - Ingest multi-format source files and produce typed, FOLIO-tagged knowledge units with confidence scores, lineage, batch CLI execution, and interactive review viewer (completed 2026-03-17)
- [x] **Phase 1.1: Upload & Processing UI** - Document upload, corpus management, and real-time pipeline processing in the web UI (INSERTED) (completed 2026-03-18)
- [x] **Phase 2: Task Hierarchy Discovery** - Discover advocacy tasks from extracted knowledge and build a validated hierarchical task tree across the corpus (completed 2026-03-19)
- [x] **Phase 3: Ontology Output and Delivery** - Generate validated OWL and companion files serving all three consumption modes, with incremental corpus support (completed 2026-04-04)
- [ ] **Phase 3.1: Export UI Integration Fixes & Tech Debt** - Fix blocking UI export wiring, CLI serve stub, and cross-phase tech debt (INSERTED — gap closure)

## Phase Details

### Phase 1: Knowledge Extraction Pipeline
**Goal**: A practitioner can run the batch CLI against a directory of multi-format source files and receive typed, FOLIO-tagged knowledge units with confidence scores and full source lineage -- then review, approve, reject, or edit those units in an interactive viewer before anything enters OWL
**Depends on**: Nothing (first phase)
**Requirements**: INGEST-01, INGEST-02, INGEST-03, EXTRACT-01, EXTRACT-02, EXTRACT-03, EXTRACT-04, EXTRACT-05, EXTRACT-06, CLASS-01, CLASS-02, CLASS-03, FOLIO-01, FOLIO-02, FOLIO-03, FOLIO-04, QUAL-01, QUAL-02, QUAL-03, PIPE-02
**Success Criteria** (what must be TRUE):
  1. Running the CLI against a directory of MD files produces JSON output containing extracted knowledge units -- each unit carries a type classification, one or more FOLIO concept mappings, a multi-stage confidence score, and a source lineage trail back to the originating file, chapter, and approximate location
  2. Knowledge units are distilled ideas (not quoted passages) that preserve all necessary nuance -- important principles appear even if "obvious," and counterintuitive insights are flagged as high-novelty
  3. Duplicate advice expressed differently across source files is detected and deduplicated in the output
  4. The JSON output is both human-readable for spot-checking and machine-parseable for downstream pipeline consumption, with high-confidence units auto-approved and low-confidence units flagged for review
  5. FOLIO concept mappings use the full ~18,000-concept ontology via four-path hybrid extraction (EntityRuler + LLM + Semantic + Heading Context) with 5-stage confidence scoring, not a reduced subset
  6. An interactive review viewer allows browsing by FOLIO concept tree, approving/rejecting/editing units, with decisions persisting in SQLite across sessions
**Plans**: 4 plans

Plans:
- [x] 01-01-PLAN.md -- Project scaffolding, folio-enrich bridge adapter, and multi-format ingestion
- [x] 01-02-PLAN.md -- Tiered boundary detection, distillation, classification, FOLIO four-path tagging, and deduplication
- [x] 01-03-PLAN.md -- Quality output (confidence gating, JSON formatting), pipeline orchestrator, and batch CLI
- [x] 01-04-PLAN.md -- Interactive review viewer (FastAPI backend + SvelteKit frontend with three-pane layout)

### Phase 01.1: Upload & Processing UI (INSERTED)
**Goal**: Users can upload documents (individual files, zip archives, or folders) through the web UI, manage named corpora, trigger pipeline processing with a button, watch real-time stage-by-stage progress via SSE with an activity log, and auto-navigate to the review viewer when processing completes — matching folio-enrich's upload/processing UX pattern
**Depends on**: Phase 1
**Requirements**: TBD
**Success Criteria** (what must be TRUE):
  1. Drag-and-drop zone and file picker accept individual files and bulk uploads (zip archives and folder selection) in all 14 supported formats
  2. Users can create, name, and delete corpora; each corpus stores its uploaded files and extraction results independently
  3. A "Process" button triggers pipeline processing on all unprocessed files in the corpus; the corpus registry skips already-processed files by SHA-256 hash
  4. Real-time SSE progress shows stage-by-stage pipeline advancement (progress bar with stage pills) plus a collapsible activity log with timestamped messages
  5. On processing completion, the UI auto-navigates to the review viewer with the processed corpus selected
**Plans**: 4 plans

Plans:
- [x] 01.1-01-PLAN.md -- Backend corpus CRUD API, file upload with ZIP extraction, Pydantic models
- [x] 01.1-02-PLAN.md -- Backend pipeline processing trigger, job manager, SSE streaming endpoint
- [x] 01.1-03-PLAN.md -- Frontend routing, navigation tabs, corpus store, API client, corpus sidebar with dialogs
- [x] 01.1-04-PLAN.md -- Frontend upload zone, file list, process button, progress display, activity log, auto-navigation

### Phase 2: Task Hierarchy Discovery
**Goal**: The system organizes all extracted knowledge units into a discovered hierarchy of advocacy tasks (Task > Subtask), with best practices, principles, and pitfalls as annotation-property metadata on each Task/Subtask class — so querying "how do I take an expert deposition" returns the class with its advice metadata attached
**Depends on**: Phase 1
**Requirements**: TASK-01, TASK-02, TASK-03, TASK-04
**Success Criteria** (what must be TRUE):
  1. The system discovers top-level advocacy tasks (depositions, opening statements, motions, cross-examination, etc.) from the source texts themselves rather than from a predefined list
  2. Each discovered task contains a hierarchical tree of subtasks, with best practices, principles, and pitfalls stored as annotation-property metadata on each Task/Subtask class (confidence and source metadata in companion SKOS file)
  3. Task hierarchy fragments discovered across multiple source files are merged into a single coherent tree without duplicates
  4. Contradictory advice from different sources on the same task is detected and flagged with both positions preserved
**Plans**: 5 plans

Plans:
- [x] 02-01-PLAN.md -- Data models, test scaffolds, and discovery stages 1-3 (heading analysis, FOLIO mapping, content clustering)
- [x] 02-02-PLAN.md -- Discovery stages 4-6 (hierarchy construction, cross-source merging, contradiction detection), orchestrator, and CLI
- [x] 02-03-PLAN.md -- SQLite schema extension, API endpoints (discovery trigger, task review, contradiction resolution, export)
- [x] 02-04-PLAN.md -- Frontend stores, API client, and core task viewer components (TaskTree, TaskDetail, FilterToolbar, ContradictionView)
- [x] 02-05-PLAN.md -- Frontend dashboard, discovery trigger on upload page, navigation routing, keyboard shortcuts, visual verification

### Phase 3: Ontology Output and Delivery
**Goal**: The complete knowledge structure is serialized as a validated, FOLIO-compatible OWL module with companion files that serve SPARQL queries, LLM RAG retrieval, and human browsing -- and the pipeline supports incremental corpus growth
**Depends on**: Phase 2
**Requirements**: OWL-01, OWL-02, OWL-03, OWL-04, OWL-05, PIPE-01
**Success Criteria** (what must be TRUE):
  1. The system produces a valid standalone OWL module using FOLIO namespace conventions with deterministic IRIs generated via folio-python's WebProtege-compatible algorithm, and a companion SKOS/RDFS file linking detailed advice content to OWL IRIs
  2. All three consumption modes work: SPARQL queries return structured results, JSON-LD chunks are suitable for LLM RAG retrieval, and human-browsable output (HTML/MD) renders the knowledge hierarchy
  3. The OWL output passes validation (well-formed XML, valid RDF, no IRI collisions, referential integrity, namespace consistency) and includes annotated diffs and SHACL validation for FOLIO maintainer review
  4. Adding new source files to the corpus produces updated output without reprocessing previously processed files
**Plans**: 2 plans

Plans:
- [x] 03-01-PLAN.md -- Core OWL serialization engine: IRI manager, graph builder, SHACL validator, changelog generator, JSON-LD RAG chunks
- [x] 03-02-PLAN.md -- Multi-consumer delivery: extend TaskExporter, CLI export command, API endpoints, ExportDialog UI with validation display

### Phase 03.1: Export UI Integration Fixes & Tech Debt (INSERTED — gap closure)
**Goal**: Fix the 2 blocking UI export integration breaks so the full Upload→Export user journey works in the browser, wire the CLI serve command, and clean up cross-phase tech debt
**Depends on**: Phase 3
**Requirements**: OWL-01, OWL-03, PIPE-01, QUAL-01, QUAL-03, TASK-02
**Gap Closure**: Closes gaps from v1.0-MILESTONE-AUDIT.md
**Success Criteria** (what must be TRUE):
  1. ExportDialog enables the "Export Ontology" button when approved tasks exist (hasApprovedTasks derived correctly from API response)
  2. Clicking "Export Ontology" successfully triggers the backend export and displays ValidationSummary with PASS/WARN/FAIL badges (no JSON parse error on ZIP response)
  3. Download links work for individual formats and bundled ZIP
  4. `folio-insights serve` starts the FastAPI server (no longer a stub)
  5. TaskTreeNode type matches API response (path/sortOrder either returned by API or removed from type)
  6. HeadingAnalysisStage imports HeadingContextExtractor constants instead of duplicating
  7. Wave-0 scaffold test stubs are either implemented or removed
  8. Deduplicator uses bridge embedding service or the standalone model choice is documented as intentional
**Plans**: TBD (created by /gsd:plan-phase 03.1)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 1.1 -> 2 -> 3 -> 3.1

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Knowledge Extraction Pipeline | 4/4 | Complete   | 2026-03-17 |
| 1.1 Upload & Processing UI | 4/4 | Complete | 2026-03-18 |
| 2. Task Hierarchy Discovery | 5/5 | Complete | 2026-03-19 |
| 3. Ontology Output and Delivery | 2/2 | Complete | 2026-04-04 |
| 3.1 Export UI Integration Fixes & Tech Debt | 0/1 | Not started | - |
