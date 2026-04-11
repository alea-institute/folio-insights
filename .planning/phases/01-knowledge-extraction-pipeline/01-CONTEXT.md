# Phase 1: Knowledge Extraction Pipeline - Context

**Gathered:** 2026-03-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Ingest source files (multi-format) and produce typed, FOLIO-tagged knowledge units with confidence scores, full source lineage, and human-reviewable output. Includes project rename to folio-insights, a full interactive review viewer for validating all extractions before OWL generation. Task hierarchy discovery and OWL generation are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Project Identity
- Renamed from "Alea Advocate" to **FOLIO Insights** (`folio-insights`) — done in Plan 01-01 (scaffolding). pyproject.toml, package name, CLI entry point, and all references use `folio-insights`
- Reflects broader applicability beyond advocacy (transactional, bankruptcy, advisory, regulatory)

### Source Ingestion (Multi-Format)
- **Supported input formats**: Markdown (.md), DOCX, PDF, plain text (.txt), HTML, RTF, XML, CSV, Excel (.xlsx), WordPerfect (.wpd), Email (EML/MSG)
- **Reuse folio-enrich ingestors** for formats it already handles: PDF (PyMuPDF), DOCX (python-docx), HTML (BeautifulSoup4), Markdown (regex-based), plain text, RTF (striprtf), Email (extract-msg)
- **Reuse folio-mapper** file_parser for: Excel (openpyxl), CSV, TSV
- **Add new parsers** for: XML (lxml, already a folio-enrich dep), WordPerfect (via Free Law Project's Doctor microservice)
- Best tool for each file format — no single universal parser

### Boundary Detection (Symbolic AI First)
- **Tiered approach — minimize LLM usage for boundary detection:**
  - **Tier 1: Structural heuristics** (pure code, instant) — headings, bullets, numbered lists, paragraph breaks. Handles ~70-80% of boundaries. FREE.
  - **Tier 2: Embedding-based semantic segmentation** (CPU-friendly) — sentence-transformers to detect topic shifts within paragraphs via cosine similarity drops. Handles ~15-20%. CHEAP.
  - **Tier 3: LLM refinement** (expensive, only for ambiguity) — only for truly ambiguous cases where code can't determine boundaries. ~5%. Per-call cost.
- **Reuse folio-enrich's existing tools**: nupunkt for legal-domain sentence splitting, spaCy for NLP/NER, Aho-Corasick for pattern matching, sentence-boundary-aware text chunking
- **Leverage mjbommar / 273v ecosystem**: Kelvin patterns for legal document chunking, LMSS for supplementary legal taxonomy, LogiLLM for structured LLM fallback calls
- **Leverage Free Law Project**: eyecite (already in folio-enrich!) for citation extraction, Doctor for legacy format conversion (WPD)

### Extraction Granularity
- One idea per knowledge unit — each unit captures exactly one technique, principle, or warning
- A paragraph with 3 tips becomes 3 separate units
- Tight distillation: compress to core insight, keep tactical nuance (e.g., "Lock expert into reviewed-document list during deposition — prevents expanding opinion basis at trial")
- Extract everything regardless of obviousness; use novelty scoring to distinguish surprising from expected
- Always split by knowledge type (advice, principle, citation, rule, pitfall), with cross-references linking related pairs from the same source passage

### LLM Strategy
- **Provider agnostic** — support OpenAI, Anthropic, Google (Gemini), xAI (Grok), local models, etc. User configurable, following folio-enrich's per-task LLM routing pattern
- **Right model for the job** — tiered model selection per task:
  - Light models (Haiku-class): heading → FOLIO concept mapping, simple classification
  - Medium models (Sonnet-class): knowledge type classification, boundary detection (Tier 3 fallback)
  - Large models (Opus-class): idea distillation, surprise scoring, branch judge reconciliation
- **Preference toward local models** where possible (embedding models, sentence-transformers), with cloud LLM APIs for tasks requiring large context or high reasoning
- All model assignments user-configurable with sensible defaults

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

### Review Viewer (folio-insights UI)
- Standalone SvelteKit frontend + FastAPI backend + SQLite database
- Three-pane layout:
  - Left: **FOLIO concept tree** (filtered to show only concepts with tagged knowledge units) — the FOLIO ontology IS the browsing structure in Phase 1
  - Upper-right: FOLIO class detail view (matching folio-mapper/folio-enrich detail view) with extracted insights as metadata
  - Lower-right: Source text context for validation ("trust but verify")
- Color-coded badges: green for new individuals, orange for proposed new classes, no badge for existing FOLIO concepts
- Full review workflow: approve/reject/edit for both proposed classes AND individual knowledge units
- Review decisions persist in SQLite across sessions and pipeline re-runs
- **Review gates output**: nothing enters OWL until reviewed and approved
- Tree view AND list view for rapid review
- Inline text editing for distilled knowledge units
- Phase 2 adds a second tree tab (advocacy task hierarchy) alongside the FOLIO concept tree

### Document Structure as Fourth Extraction Path
- Chapter, heading, and subheading context is a **fourth extraction path** alongside EntityRuler, LLM concept identification, and semantic similarity
- This is an independent signal, NOT baked into the confidence score — the branch judge evaluates it separately so you can always see what came from document structure vs. text analysis ("unbake the cake" principle)
- **All heading levels contribute, weighted by proximity**:
  - Immediate subheading = strongest signal (e.g., "Methodology Challenges")
  - Parent heading = medium signal (e.g., "Cross-Examination")
  - Chapter title = weakest but still present signal (e.g., "Experts")
- **Tiered signal strength based on FOLIO mapping quality**:
  - Heading maps to FOLIO concept with confidence >= 0.7 → strong signal (boosts AND suggests FOLIO tags)
  - Heading maps below 0.7 → weaker signal, fall back to parent headings as supplementary evidence
  - Clear heading-to-FOLIO mappings get strong boosts; ambiguous headings contribute proportionally less
- **Visible in review viewer as distinct source**: Each FOLIO tag shows its extraction path (EntityRuler, LLM, Semantic, or Heading Context) so the reviewer can trace why each tag was assigned
- **Reconciliation**: The four-path results merge in the existing reconciliation stage, then the branch judge weighs all four signals to produce the final confidence score

### Confidence Scoring
- Reuse folio-enrich's 5-stage confidence scoring pipeline, extended with the fourth path (document structure)
- Visual triage with toggleable confidence filter tabs in the reviewer
- Default threshold bands: >=0.8 (high/green, quick-approve), 0.5-0.8 (medium/yellow, careful review), <0.5 (low/red, deep review)
- Final composite score shown prominently, with expandable per-stage breakdown for diagnosis
- Thresholds configurable in both pipeline config AND viewer settings panel

### Multi-Project Support
- Shared folio-insights instance with separate named corpora (advocacy, transactional, etc.)
- Each corpus has its own source files and review state
- All corpora share the same FOLIO base and merge into one OWL output

### Claude's Discretion
- Technical architecture decisions (pipeline internals, stage implementation)
- Performance optimization
- Specific LLM prompts for extraction, classification, distillation
- Loading skeleton and error state design in the viewer
- Which specific sentence-transformers model to use for Tier 2 boundary detection

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### FOLIO Ontology
- `~/Coding Projects/folio-python/folio/graph.py` — Authoritative IRI generation method (`FOLIO.generate_iri()`: UUID4 -> base64 -> alphanumeric filter)
- FOLIO GitHub (alea-institute/FOLIO) — Full ~18,000 concept ontology with IRIs, branches, labels

### folio-enrich Integration (CRITICAL — reuse extensively)
- `~/Coding Projects/folio-enrich/backend/app/services/folio/folio_service.py` — FolioService singleton: `get_all_labels()`, `search_by_label()`, `get_concept()`
- `~/Coding Projects/folio-enrich/backend/app/services/embedding/service.py` — EmbeddingService: FAISS-backed similarity search
- `~/Coding Projects/folio-enrich/backend/app/services/concept/llm_concept_identifier.py` — LLM concept identification
- `~/Coding Projects/folio-enrich/backend/app/services/reconciliation/` — Dual-path merge logic (extend to four-path)
- `~/Coding Projects/folio-enrich/backend/app/pipeline/stages/resolution_stage.py` — Concept text to FOLIO IRI resolution
- `~/Coding Projects/folio-enrich/backend/app/pipeline/stages/base.py` — PipelineStage ABC: `name` property + `execute(job)` method
- `~/Coding Projects/folio-enrich/backend/app/services/ingestion/` — Multi-format ingestors (PDF, DOCX, HTML, MD, TXT, RTF, EML/MSG)
- `~/Coding Projects/folio-enrich/backend/app/services/normalization/normalizer.py` — Sentence splitting (nupunkt), text chunking
- `~/Coding Projects/folio-enrich/backend/app/services/individual/citation_extractor.py` — eyecite + citeurl citation parsing (ALREADY INTEGRATED)
- `~/Coding Projects/folio-enrich/backend/app/services/dependency/parser.py` — spaCy SVO triple extraction

### folio-mapper Integration
- `~/Coding Projects/folio-mapper/backend/app/services/file_parser.py` — Excel/CSV/TSV ingestion
- `~/Coding Projects/folio-mapper/backend/app/services/text_parser.py` — Text/markdown/hierarchy detection

### Legal NLP Ecosystem
- https://github.com/mjbommar — Legal NLP tools (Kelvin patterns, LMSS taxonomy, LogiLLM)
- https://github.com/273v/python-lmss — Legal Matter Standard Specification (10K+ legal tags)
- https://github.com/273v/kelvin-public-examples — Kelvin Legal Data OS patterns
- https://github.com/mjbommar/logillm — Structured LLM programming framework
- https://github.com/freelawproject/eyecite — Legal citation extraction (already in folio-enrich)
- https://github.com/freelawproject/doctor — Document conversion microservice (handles WPD, legacy formats)

### Architecture Research
- `.planning/research/ARCHITECTURE.md` — Full 4-stage pipeline architecture, component boundaries, data flow, bridge pattern, project structure (NOTE: update to four-path extraction, tiered boundary detection, expanded input formats per decisions above)
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

### Reusable Assets (folio-enrich — import via bridge adapter)
- **Ingestion registry** (7 formats): PDF, DOCX, HTML, Markdown, plain text, RTF, Email — with format auto-detection
- **FolioService**: Lazy-init singleton providing full FOLIO ontology access — no adaptation needed
- **EmbeddingService**: FAISS-backed semantic similarity search over 18K concept labels — no adaptation needed
- **EntityRulerStage**: Pattern matching against FOLIO labels — import service layer
- **LLMConceptIdentifier**: LLM-driven concept identification — modify prompts for legal text context
- **ReconciliationStage**: Multi-path merge for concept extraction results — extend from 3 to 4 paths
- **AhoCorasickMatcher**: Fast multi-pattern string matching — no changes needed
- **5-stage confidence scoring**: Proven confidence pipeline — extend with document structure path
- **nupunkt**: Legal-domain sentence splitting (handles "42 U.S.C. § 1983", case numbers correctly)
- **CitationExtractor**: eyecite + citeurl — battle-tested on 55M+ legal citations, ALREADY INTEGRATED
- **DependencyParser**: spaCy SVO triple extraction
- **Text chunking**: Sentence-boundary-aware, configurable chunk size and overlap

### Reusable Assets (folio-mapper)
- **FileParser**: Excel (openpyxl), CSV, TSV ingestion with header detection and size limits
- **TextParser**: Hierarchy detection from indentation/nesting
- **HierarchyDetector**: Detects hierarchical structures from tabular data

### Established Patterns
- **Bridge adapter pattern**: Import folio-enrich services as a library, don't modify folio-enrich's pipeline
- **PipelineStage ABC**: Same interface (`name` + `execute(job)`) for all stages
- **Per-task LLM routing**: folio-enrich's TaskLLMs pattern — provider agnostic, user configurable
- **Tree component**: folio-mapper and folio-api have existing tree browsing patterns to match in the viewer
- **Format auto-detection**: folio-enrich's registry.py pattern (extension → base64 prefix → content pattern)

### Integration Points
- **folio-enrich services**: Import FolioService, EmbeddingService, LLM registry, ingestors, normalizers, citation extractor
- **folio-mapper services**: Import FileParser for Excel/CSV/TSV
- **folio-python**: IRI generation for new individuals
- **FOLIO OWL GitHub**: Output feeds to FOLIO GitHub, consumed by folio-enrich and folio-mapper
- **Free Law Project Doctor**: WPD and legacy format conversion
- **Source files**: .docx and .pdf files in `sources/` subdirectories (3 textbooks currently)

</code_context>

<specifics>
## Specific Ideas

- Distillation style: "Lock expert into reviewed-document list during deposition — prevents expanding opinion basis at trial" (tight compression, keeps tactical nuance)
- HTML viewer should match the look/feel of existing folio-mapper and folio-enrich tree + detail views — consistent FOLIO ecosystem UX
- "Trust but verify" — source text pane lets reviewer validate that the distilled idea faithfully represents the source
- Review should be fast — bulk operations, keyboard shortcuts, skim-approve for high-confidence items
- Phase 1 viewer tree is organized by FOLIO concept hierarchy (not source files) — knowledge units browsable via the ontology from day one
- Boundary detection should prefer cheap symbolic AI (code + embeddings) over expensive LLM calls — LLM only for ambiguity
- Use nupunkt (already in folio-enrich) for legal-domain-aware sentence splitting as the foundation

</specifics>

<deferred>
## Deferred Ideas

- Multi-reviewer support (multiple users reviewing the same corpus) — future enhancement to SQLite schema
- Phase 2 adds a second tree tab (advocacy task hierarchy) alongside the FOLIO concept tree in the viewer

</deferred>

---

*Phase: 01-knowledge-extraction-pipeline*
*Context gathered: 2026-03-17*
