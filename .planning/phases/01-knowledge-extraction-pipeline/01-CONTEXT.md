# Phase 1: Knowledge Extraction Pipeline - Context

**Gathered:** 2026-03-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Ingest source files and produce typed, FOLIO-tagged knowledge units with confidence scores, full source lineage, and human-reviewable output. Includes a full interactive review viewer (folio-insights) for validating all extractions before OWL generation. Task hierarchy discovery and OWL generation are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Extraction Granularity
- One idea per knowledge unit — each unit captures exactly one technique, principle, or warning
- A paragraph with 3 tips becomes 3 separate units
- Tight distillation: compress to core insight, keep tactical nuance (e.g., "Lock expert into reviewed-document list during deposition — prevents expanding opinion basis at trial")
- Extract everything regardless of obviousness; use novelty scoring to distinguish surprising from expected
- Always split by knowledge type (advice, principle, citation, rule, pitfall), with cross-references linking related pairs from the same source passage

### OWL Modeling
- Tasks are OWL **classes** — always map to existing FOLIO concept IRIs (e.g., `Cross-Examination of Witness` → `https://folio.openlegalstandard.org/RCz1SYWoNDDTDvPr0kSJBq`)
- Knowledge units (techniques, principles, pitfalls) are **individuals** — new IRIs generated via folio-python
- Citations are **individuals** (e.g., `Daubert v. Merrell Dow`) linked to principle individuals via standard properties
- Use `folio:` namespace for all new properties — no separate `advocate:` or `alea:` namespace
- Dedup: one canonical individual per technique, linked to multiple task classes via `skos:broader`; context-specific notes in companion file per task-technique pair

### Standards Reuse
- Maximize existing ontology standards over custom properties:
  - **SKOS**: `skos:broader`/`skos:narrower` (hierarchy), `skos:related` (cross-refs), `skos:definition` (distilled text), `skos:note`/`skos:example`/`skos:editorialNote` (annotations)
  - **PROV-O**: `prov:wasDerivedFrom` (source lineage), `prov:wasGeneratedBy` (extraction method)
  - **Dublin Core**: `dc:source`, `dc:bibliographicCitation`, `dc:type`
  - **CITO**: `cito:isSupportedBy` (citation-principle links)
  - **Web Annotation**: `oa:hasTarget` + `oa:TextPositionSelector` (source spans)
- Custom `folio:` properties only where no standard exists: `folio:confidence`, `folio:noveltyScore`

### IRI Policy
- ALWAYS map extracted concepts to existing FOLIO IRIs — never recreate what FOLIO already defines
- Very conservative new class creation — only when FOLIO genuinely lacks the concept
- Every proposed new class must be surfaced for user review before IRI generation
- New individuals (knowledge units, citations): greenfield, create as many as useful, with dedup

### Output Format
- Dual output: JSON + interactive HTML viewer
- JSON organized by knowledge type with rich metadata, plus a flat array export option
- JSON stores source references only (file path, chapter, section, character span) — no original text copied (copyright safety)
- Proposed new FOLIO classes: both flagged in main output AND a separate summary report

### Review Viewer (folio-insights)
- Standalone SvelteKit frontend + FastAPI backend + SQLite database
- Three-pane layout:
  - Left: Task-organized tree (matching folio-mapper/folio-api tree patterns)
  - Upper-right: FOLIO class detail view (matching folio-mapper/folio-enrich detail view) with extracted insights as metadata
  - Lower-right: Source text context for validation ("trust but verify")
- Color-coded badges: green for new individuals, orange for proposed new classes, no badge for existing FOLIO concepts
- Full review workflow: approve/reject/edit for both proposed classes AND individual knowledge units
- Review decisions persist in SQLite across sessions and pipeline re-runs
- **Review gates output**: nothing enters OWL until reviewed and approved
- Tree view AND list view for rapid review
- Inline text editing for distilled knowledge units

### Confidence Scoring
- Reuse folio-enrich's 5-stage confidence scoring pipeline
- Visual triage with toggleable confidence filter tabs in the reviewer
- Default threshold bands: >=0.8 (high/green, quick-approve), 0.5-0.8 (medium/yellow, careful review), <0.5 (low/red, deep review)
- Final composite score shown prominently, with expandable per-stage breakdown for diagnosis
- Thresholds configurable in both pipeline config AND viewer settings panel

### Multi-Project Support
- Shared folio-insights instance with separate named corpora (advocacy, transactional, etc.)
- Each corpus has its own source files and review state
- All corpora share the same FOLIO base and merge into one OWL output

### Claude's Discretion
- Source format handling (docx/pdf conversion strategy — actual sources are .docx and .pdf, not .md)
- Technical architecture decisions (pipeline internals, stage implementation)
- Performance optimization
- Specific LLM prompts for extraction, classification, distillation
- Loading skeleton and error state design in the viewer

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### FOLIO Ontology
- `~/Coding Projects/folio-python/folio/graph.py` — Authoritative IRI generation method (`FOLIO.generate_iri()`: UUID4 -> base64 -> alphanumeric filter)
- FOLIO GitHub (alea-institute/FOLIO) — Full ~18,000 concept ontology with IRIs, branches, labels

### folio-enrich Integration
- `~/Coding Projects/folio-enrich/backend/services/folio/folio_service.py` — FolioService singleton: `get_all_labels()`, `search_by_label()`, `get_concept()`
- `~/Coding Projects/folio-enrich/backend/services/embedding/service.py` — EmbeddingService: FAISS-backed similarity search
- `~/Coding Projects/folio-enrich/backend/services/concept/llm_concept_identifier.py` — LLM concept identification
- `~/Coding Projects/folio-enrich/backend/services/reconciliation/` — Dual-path merge logic
- `~/Coding Projects/folio-enrich/backend/pipeline/stages/resolution_stage.py` — Concept text to FOLIO IRI resolution
- `~/Coding Projects/folio-enrich/backend/pipeline/stages/base.py` — PipelineStage ABC: `name` property + `execute(job)` method

### Architecture Research
- `.planning/research/ARCHITECTURE.md` — Full 4-stage pipeline architecture, component boundaries, data flow, bridge pattern, project structure
- `.planning/research/FEATURES.md` — Feature landscape: table stakes, differentiators, anti-features

### Standards
- W3C SKOS — Knowledge organization (broader/narrower, definitions, notes)
- W3C PROV-O — Provenance ontology (derivation, generation)
- Dublin Core — Metadata (source, bibliographic citation, type)
- CITO — Citation Typing Ontology (supports/cites relationships)
- W3C Web Annotation — Text position selectors for source spans

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **FolioService** (folio-enrich): Lazy-init singleton providing full FOLIO ontology access — no adaptation needed
- **EmbeddingService** (folio-enrich): FAISS-backed semantic similarity search over 18K concept labels — no adaptation needed
- **EntityRulerStage** (folio-enrich): Pattern matching against FOLIO labels — import service layer, run against knowledge units
- **LLMConceptIdentifier** (folio-enrich): LLM-driven concept identification — modify prompts for advocacy text context
- **ReconciliationStage** (folio-enrich): Dual-path merge for concept extraction results — same logic, different input shape
- **AhoCorasickMatcher** (folio-enrich): Fast multi-pattern string matching — no changes needed
- **5-stage confidence scoring** (folio-enrich): Proven confidence pipeline across reconciliation, resolution, rerank, branch judge stages

### Established Patterns
- **Bridge adapter pattern**: Import folio-enrich services as a library, don't modify folio-enrich's pipeline
- **PipelineStage ABC**: Same interface (`name` + `execute(job)`) for all stages
- **Per-task LLM routing**: folio-enrich's TaskLLMs pattern for routing different tasks to different LLM providers
- **Tree component**: folio-mapper and folio-api have existing tree browsing patterns to match in the viewer

### Integration Points
- **folio-enrich services**: Import FolioService, EmbeddingService, LLM registry as libraries
- **folio-python**: IRI generation for new individuals
- **FOLIO OWL GitHub**: Output feeds to FOLIO GitHub, consumed by folio-enrich and folio-mapper
- **Source files**: .docx and .pdf files in `sources/` subdirectories (3 textbooks currently)

</code_context>

<specifics>
## Specific Ideas

- Distillation style: "Lock expert into reviewed-document list during deposition — prevents expanding opinion basis at trial" (tight compression, keeps tactical nuance)
- HTML viewer should match the look/feel of existing folio-mapper and folio-enrich tree + detail views — consistent FOLIO ecosystem UX
- "Trust but verify" — source text pane lets reviewer validate that the distilled idea faithfully represents the source
- Review should be fast — bulk operations, keyboard shortcuts, skim-approve for high-confidence items
- Project rename from "Alea Advocate" to "folio-insights" — reflects broader applicability beyond advocacy

</specifics>

<deferred>
## Deferred Ideas

- Project rename execution (updating repo name, package name, etc.) — can happen anytime, doesn't block Phase 1 implementation
- Multi-reviewer support (multiple users reviewing the same corpus) — future enhancement to SQLite schema

</deferred>

---

*Phase: 01-knowledge-extraction-pipeline*
*Context gathered: 2026-03-17*
