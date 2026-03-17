# Roadmap: Alea Advocate

## Overview

Alea Advocate delivers a batch pipeline that extracts structured advocacy knowledge from legal textbooks and maps it into the FOLIO ontology. The pipeline has strict stage dependencies: knowledge units must be extracted and FOLIO-tagged before task hierarchies can be discovered, and task hierarchies must exist before OWL output can be generated. This roadmap follows those natural data dependencies across three phases, progressing from raw MD input to validated ontology output.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Knowledge Extraction Pipeline** - Ingest MD files and produce typed, FOLIO-tagged knowledge units with confidence scores, lineage, and batch CLI execution
- [ ] **Phase 2: Task Hierarchy Discovery** - Discover advocacy tasks from extracted knowledge and build a validated hierarchical task tree across the corpus
- [ ] **Phase 3: Ontology Output and Delivery** - Generate validated OWL and companion files serving all three consumption modes, with incremental corpus support

## Phase Details

### Phase 1: Knowledge Extraction Pipeline
**Goal**: A practitioner can run the batch CLI against a directory of MD source files and receive typed, FOLIO-tagged knowledge units with confidence scores and full source lineage in human-reviewable JSON output
**Depends on**: Nothing (first phase)
**Requirements**: INGEST-01, INGEST-02, INGEST-03, EXTRACT-01, EXTRACT-02, EXTRACT-03, EXTRACT-04, EXTRACT-05, EXTRACT-06, CLASS-01, CLASS-02, CLASS-03, FOLIO-01, FOLIO-02, FOLIO-03, FOLIO-04, QUAL-01, QUAL-02, QUAL-03, PIPE-02
**Success Criteria** (what must be TRUE):
  1. Running the CLI against a directory of MD files produces JSON output containing extracted knowledge units -- each unit carries a type classification, one or more FOLIO concept mappings, a multi-stage confidence score, and a source lineage trail back to the originating file, chapter, and approximate location
  2. Knowledge units are distilled ideas (not quoted passages) that preserve all necessary nuance -- important principles appear even if "obvious," and counterintuitive insights are flagged as high-novelty
  3. Duplicate advice expressed differently across source files is detected and deduplicated in the output
  4. The JSON output is both human-readable for spot-checking and machine-parseable for downstream pipeline consumption, with high-confidence units auto-approved and low-confidence units flagged for review
  5. FOLIO concept mappings use the full ~18,000-concept ontology via three-path hybrid extraction with 5-stage confidence scoring, not a reduced subset
**Plans**: TBD

Plans:
- [ ] 01-01: Project scaffolding, folio-enrich bridge adapter, and MD ingestion
- [ ] 01-02: Knowledge unit extraction, classification, and FOLIO tagging
- [ ] 01-03: Quality output, confidence gating, and batch CLI

### Phase 2: Task Hierarchy Discovery
**Goal**: The system organizes all extracted knowledge units into a discovered hierarchy of advocacy tasks (Task > Subtask), with best practices, principles, and pitfalls as annotation-property metadata on each Task/Subtask class — so querying "how do I take an expert deposition" returns the class with its advice metadata attached
**Depends on**: Phase 1
**Requirements**: TASK-01, TASK-02, TASK-03, TASK-04
**Success Criteria** (what must be TRUE):
  1. The system discovers top-level advocacy tasks (depositions, opening statements, motions, cross-examination, etc.) from the source texts themselves rather than from a predefined list
  2. Each discovered task contains a hierarchical tree of subtasks, with best practices, principles, and pitfalls stored as annotation-property metadata on each Task/Subtask class (confidence and source metadata in companion SKOS file)
  3. Task hierarchy fragments discovered across multiple source files are merged into a single coherent tree without duplicates
  4. Contradictory advice from different sources on the same task is detected and flagged with both positions preserved
**Plans**: TBD

Plans:
- [ ] 02-01: Task discovery and hierarchical tree construction
- [ ] 02-02: Cross-source merging, deduplication, and contradiction detection

### Phase 3: Ontology Output and Delivery
**Goal**: The complete knowledge structure is serialized as a validated, FOLIO-compatible OWL module with companion files that serve SPARQL queries, LLM RAG retrieval, and human browsing -- and the pipeline supports incremental corpus growth
**Depends on**: Phase 2
**Requirements**: OWL-01, OWL-02, OWL-03, OWL-04, OWL-05, PIPE-01
**Success Criteria** (what must be TRUE):
  1. The system produces a valid standalone OWL module using FOLIO namespace conventions with deterministic IRIs generated via folio-python's WebProtege-compatible algorithm, and a companion SKOS/RDFS file linking detailed advice content to OWL IRIs
  2. All three consumption modes work: SPARQL queries return structured results, JSON-LD chunks are suitable for LLM RAG retrieval, and human-browsable output (HTML/MD) renders the knowledge hierarchy
  3. The OWL output passes validation (well-formed XML, valid RDF, no IRI collisions, referential integrity, namespace consistency) and includes annotated diffs and SHACL validation for FOLIO maintainer review
  4. Adding new source files to the corpus produces updated output without reprocessing previously processed files
**Plans**: TBD

Plans:
- [ ] 03-01: OWL and companion file generation with IRI strategy
- [ ] 03-02: Multi-consumer output formats, validation pipeline, and incremental processing

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Knowledge Extraction Pipeline | 0/3 | Not started | - |
| 2. Task Hierarchy Discovery | 0/2 | Not started | - |
| 3. Ontology Output and Delivery | 0/2 | Not started | - |
