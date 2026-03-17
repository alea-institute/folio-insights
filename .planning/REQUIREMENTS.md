# Requirements: Alea Advocate

**Defined:** 2026-03-17
**Core Value:** Every piece of actionable legal advocacy knowledge must be discoverable by task, mapped to FOLIO concepts, and structured for practitioners, AI systems, and developers.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Ingestion

- [ ] **INGEST-01**: System can ingest a directory of MD files containing mixed chapter extracts and synthesized notes
- [ ] **INGEST-02**: System preserves document structure (headings, paragraphs, lists) during parsing
- [ ] **INGEST-03**: System handles variable-length source files (single pages to full chapters)

### Extraction

- [ ] **EXTRACT-01**: System detects advice unit boundaries using LLM-driven semantic segmentation, from sentence-level to multi-paragraph
- [ ] **EXTRACT-02**: System distills ideas (not expressions) — extracts underlying concepts/techniques rather than quoting passages
- [ ] **EXTRACT-03**: Each distilled idea is as simple as possible but no simpler — includes all necessary detail and nuance
- [ ] **EXTRACT-04**: System extracts important advocacy principles even if "obvious" — these serve as structured reminders
- [ ] **EXTRACT-05**: System flags counterintuitive or non-obvious insights unlikely to be in LLM training data as high-novelty
- [ ] **EXTRACT-06**: System deduplicates identical advice expressed differently across multiple source documents

### Classification

- [ ] **CLASS-01**: System classifies each knowledge unit by type using FOLIO ontology classes (not a custom taxonomy)
- [ ] **CLASS-02**: Knowledge types include at minimum: actionable advice, legal principles, case citations, procedural rules, and common pitfalls
- [ ] **CLASS-03**: Each classification carries a confidence score

### FOLIO Tagging

- [ ] **FOLIO-01**: System maps each knowledge unit to one or more FOLIO concepts using folio-enrich's three-path hybrid extraction (EntityRuler + LLM + semantic)
- [ ] **FOLIO-02**: System applies folio-enrich's 5-stage confidence scoring to all FOLIO concept mappings
- [ ] **FOLIO-03**: System tags against the full FOLIO ontology (~18,000 concepts), not a subset
- [ ] **FOLIO-04**: Each tagged unit carries full lineage: source file, chapter, approximate location, extraction method, and confidence at each stage

### Quality

- [ ] **QUAL-01**: System produces human-reviewable enriched output (JSON with spans/nested spans) for spot-checking
- [ ] **QUAL-02**: High-confidence extractions (above threshold) auto-approve; low-confidence units flagged for review
- [ ] **QUAL-03**: Enriched output is both human-readable and machine-parseable for downstream pipeline consumption

### Task Structure

- [ ] **TASK-01**: System discovers top-level advocacy tasks from the texts themselves (e.g., depositions, opening statements, motions, cross-examination)
- [ ] **TASK-02**: System builds hierarchical task trees: Task > Subtask > Best Practice / Principle / Pitfall
- [ ] **TASK-03**: System merges task hierarchy fragments discovered across multiple source files into a single coherent tree
- [ ] **TASK-04**: System detects and flags contradictory advice from different sources on the same task

### Ontology Output

- [ ] **OWL-01**: System produces valid OWL with core structural mappings (classes, properties, cross-references) compatible with FOLIO
- [ ] **OWL-02**: System produces a companion SKOS/RDFS file for detailed advice content linked to OWL via IRIs
- [ ] **OWL-03**: System supports multiple consumption modes: SPARQL/API queries, LLM RAG retrieval (JSON-LD chunks), and human browsing (HTML/MD)
- [ ] **OWL-04**: System produces a FOLIO-incorporation-ready format — standalone OWL module using FOLIO namespace conventions, with annotated diffs and SHACL validation, so FOLIO maintainers can review and merge additions
- [ ] **OWL-05**: System generates new FOLIO IRIs using folio-python's WebProtege-compatible algorithm (UUID4 → base64 → alphanumeric filter → `https://folio.openlegalstandard.org/{token}`)

### Pipeline

- [ ] **PIPE-01**: System handles incremental corpus growth — new files processed without reprocessing entire corpus
- [ ] **PIPE-02**: Pipeline runs as batch process (CLI or script-triggered)

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
| INGEST-01 | — | Pending |
| INGEST-02 | — | Pending |
| INGEST-03 | — | Pending |
| EXTRACT-01 | — | Pending |
| EXTRACT-02 | — | Pending |
| EXTRACT-03 | — | Pending |
| EXTRACT-04 | — | Pending |
| EXTRACT-05 | — | Pending |
| EXTRACT-06 | — | Pending |
| CLASS-01 | — | Pending |
| CLASS-02 | — | Pending |
| CLASS-03 | — | Pending |
| FOLIO-01 | — | Pending |
| FOLIO-02 | — | Pending |
| FOLIO-03 | — | Pending |
| FOLIO-04 | — | Pending |
| QUAL-01 | — | Pending |
| QUAL-02 | — | Pending |
| QUAL-03 | — | Pending |
| TASK-01 | — | Pending |
| TASK-02 | — | Pending |
| TASK-03 | — | Pending |
| TASK-04 | — | Pending |
| OWL-01 | — | Pending |
| OWL-02 | — | Pending |
| OWL-03 | — | Pending |
| OWL-04 | — | Pending |
| OWL-05 | — | Pending |
| PIPE-01 | — | Pending |
| PIPE-02 | — | Pending |

**Coverage:**
- v1 requirements: 30 total
- Mapped to phases: 0
- Unmapped: 30 ⚠️

---
*Requirements defined: 2026-03-17*
*Last updated: 2026-03-17 after initial definition*
