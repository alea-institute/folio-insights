# Requirements: Alea Advocate

**Defined:** 2026-03-17
**Core Value:** Every piece of actionable legal advocacy knowledge must be discoverable by task, mapped to FOLIO concepts, and structured for practitioners, AI systems, and developers.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Ingestion

- [x] **INGEST-01**: System can ingest a directory of MD files containing mixed chapter extracts and synthesized notes
- [x] **INGEST-02**: System preserves document structure (headings, paragraphs, lists) during parsing
- [x] **INGEST-03**: System handles variable-length source files (single pages to full chapters)

### Extraction

- [x] **EXTRACT-01**: System detects advice unit boundaries using LLM-driven semantic segmentation, from sentence-level to multi-paragraph
- [x] **EXTRACT-02**: System distills ideas (not expressions) — extracts underlying concepts/techniques rather than quoting passages
- [x] **EXTRACT-03**: Each distilled idea is as simple as possible but no simpler — includes all necessary detail and nuance
- [x] **EXTRACT-04**: System extracts important advocacy principles even if "obvious" — these serve as structured reminders
- [x] **EXTRACT-05**: System flags counterintuitive or non-obvious insights unlikely to be in LLM training data as high-novelty
- [x] **EXTRACT-06**: System deduplicates identical advice expressed differently across multiple source documents

### Classification

- [x] **CLASS-01**: System classifies each knowledge unit by type using FOLIO ontology classes (not a custom taxonomy)
- [x] **CLASS-02**: Knowledge types include at minimum: actionable advice, legal principles, case citations, procedural rules, and common pitfalls
- [x] **CLASS-03**: Each classification carries a confidence score

### FOLIO Tagging

- [x] **FOLIO-01**: System maps each knowledge unit to one or more FOLIO concepts using folio-enrich's three-path hybrid extraction (EntityRuler + LLM + semantic)
- [x] **FOLIO-02**: System applies folio-enrich's 5-stage confidence scoring to all FOLIO concept mappings
- [x] **FOLIO-03**: System tags against the full FOLIO ontology (~18,000 concepts), not a subset
- [x] **FOLIO-04**: Each tagged unit carries full lineage: source file, chapter, approximate location, extraction method, and confidence at each stage

### Quality

- [x] **QUAL-01**: System produces human-reviewable enriched output (JSON with spans/nested spans) for spot-checking
- [x] **QUAL-02**: High-confidence extractions (above threshold) auto-approve; low-confidence units flagged for review
- [x] **QUAL-03**: Enriched output is both human-readable and machine-parseable for downstream pipeline consumption

### Task Structure

- [x] **TASK-01**: System discovers top-level advocacy tasks from the texts themselves (e.g., depositions, opening statements, motions, cross-examination)
- [x] **TASK-02**: System builds hierarchical task trees: Task > Subtask > Best Practice / Principle / Pitfall
- [x] **TASK-03**: System merges task hierarchy fragments discovered across multiple source files into a single coherent tree
- [x] **TASK-04**: System detects and flags contradictory advice from different sources on the same task

### Ontology Output

- [ ] **OWL-01**: System produces valid OWL with core structural mappings (classes, properties, cross-references) compatible with FOLIO
- [x] **OWL-02**: System produces a companion SKOS/RDFS file for detailed advice content linked to OWL via IRIs
- [ ] **OWL-03**: System supports multiple consumption modes: SPARQL/API queries, LLM RAG retrieval (JSON-LD chunks), and human browsing (HTML/MD)
- [x] **OWL-04**: System produces a FOLIO-incorporation-ready format — standalone OWL module using FOLIO namespace conventions, with annotated diffs and SHACL validation, so FOLIO maintainers can review and merge additions
- [x] **OWL-05**: System generates new FOLIO IRIs using folio-python's WebProtege-compatible algorithm (UUID4 → base64 → alphanumeric filter → `https://folio.openlegalstandard.org/{token}`)

### Pipeline

- [ ] **PIPE-01**: System handles incremental corpus growth — new files processed without reprocessing entire corpus
- [x] **PIPE-02**: Pipeline runs as batch process (CLI or script-triggered)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Quality Refinement

- **QUAL-04**: Idempotent re-runnable pipeline with hash-based deduplication
- **QUAL-05**: Importance-aware extraction with two-tier scoring (novelty + significance)

### Optimization

- **OPT-01**: SPARQL-optimized RDF schema with named graphs for provenance
- **OPT-02**: RAG-optimized chunk structure for LLM retrieval
- **OPT-03**: FOLIO candidate concept reporting for unmapped knowledge units

## Out of Scope

| Feature | Reason |
|---------|--------|
| User-facing legal advice UI | Consumers build their own on top of the ontology |
| Substantive legal analysis / correctness evaluation | System extracts what books say, not evaluates legal merit |
| Real-time / interactive processing | Batch pipeline; interactive mode would compromise quality |
| Predefined task taxonomy | Key decision: discover from texts for robustness |
| Source text rewriting / paraphrasing | "Ideas not expressions" means distill, not rewrite |
| Full source text preservation | Copyright risk; store references not passages |
| Automatic FOLIO ontology extension | FOLIO has its own governance; propose through proper channels |
| Multi-language support | English corpus; leverage FOLIO's existing multilingual labels passively |
| Citation verification / link resolution | Requires legal database access; extract citations as-is |
| Fine-grained manual review of every extraction | Doesn't scale; invest in confidence scoring instead |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INGEST-01 | Phase 1 | Complete |
| INGEST-02 | Phase 1 | Complete |
| INGEST-03 | Phase 1 | Complete |
| EXTRACT-01 | Phase 1 | Complete |
| EXTRACT-02 | Phase 1 | Complete |
| EXTRACT-03 | Phase 1 | Complete |
| EXTRACT-04 | Phase 1 | Complete |
| EXTRACT-05 | Phase 1 | Complete |
| EXTRACT-06 | Phase 1 | Complete |
| CLASS-01 | Phase 1 | Complete |
| CLASS-02 | Phase 1 | Complete |
| CLASS-03 | Phase 1 | Complete |
| FOLIO-01 | Phase 1 | Complete |
| FOLIO-02 | Phase 1 | Complete |
| FOLIO-03 | Phase 1 | Complete |
| FOLIO-04 | Phase 1 | Complete |
| QUAL-01 | Phase 1 | Complete |
| QUAL-02 | Phase 1 | Complete |
| QUAL-03 | Phase 1 | Complete |
| PIPE-02 | Phase 1 | Complete |
| TASK-01 | Phase 2 | Complete |
| TASK-02 | Phase 2 | Complete |
| TASK-03 | Phase 2 | Complete |
| TASK-04 | Phase 2 | Complete |
| OWL-01 | Phase 3 → Phase 3.1 (UI fix) | Pending |
| OWL-02 | Phase 3 | Complete |
| OWL-03 | Phase 3 → Phase 3.1 (UI fix) | Pending |
| OWL-04 | Phase 3 | Complete |
| OWL-05 | Phase 3 | Complete |
| PIPE-01 | Phase 3 → Phase 3.1 (UI fix) | Pending |

**Coverage:**
- v1 requirements: 30 total
- Mapped to phases: 30
- Unmapped: 0

---
*Requirements defined: 2026-03-17*
*Last updated: 2026-04-04 — OWL-01, OWL-03, PIPE-01 reset to Pending for Phase 3.1 gap closure*
