# Alea Advocate

## What This Is

A knowledge extraction and ontology enrichment system that processes legal advocacy textbooks (pretrial, trial, and appellate) to extract structured advice, legal principles, case citations, procedural rules, and common pitfalls — then maps all extracted knowledge into the FOLIO legal ontology. The system extends the existing `folio-enrich` pipeline with new stages for advice boundary detection, hierarchical task structuring, and OWL ontology import.

## Core Value

Every piece of actionable legal advocacy knowledge from these texts must be discoverable by task — so that any practitioner, AI system, or developer querying "how do I take an expert deposition" gets a structured, hierarchical set of techniques, principles, and warnings mapped to formal FOLIO concepts.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Ingest mixed MD source files (chapter extracts + synthesized notes) of variable length
- [ ] Detect advice unit boundaries (sentence-level to multi-paragraph) using LLM intelligence
- [ ] Tag all extracted knowledge units against full FOLIO ontology (~18,000 concepts)
- [ ] Reuse folio-enrich's EntityRuler + LLM dual-path extraction and 5-stage confidence scoring
- [ ] Produce enriched output with spans/nested spans that is both human-reviewable and machine-parseable
- [ ] Discover top-level advocacy tasks from texts (depositions, opening statements, motions, etc.)
- [ ] Build hierarchical task trees with sub-tasks and best practices under each
- [ ] Extract all knowledge types: advice, principles, citations, procedural rules, pitfalls
- [ ] Map extracted advice into FOLIO OWL with core mappings in OWL and detailed advice in companion file
- [ ] Import structured advice into the FOLIO OWL file
- [ ] Support multiple consumption modes: SPARQL/API, LLM-powered legal AI, direct UI browsing
- [ ] Automated quality-first approach — minimize manual review with spot-checking

### Out of Scope

- Building a user-facing legal advice UI (consumers build their own on top of the ontology)
- Rewriting or paraphrasing source texts (extract and structure, don't rewrite)
- Substantive legal analysis (we extract what the books say, not evaluate correctness)
- Real-time processing (batch pipeline, not interactive)

## Context

**Source Material:** Mixed collection of MD files — some are chapter-by-chapter extracts from published advocacy textbooks, others are synthesized notes. Covers pretrial, trial, and appellate advocacy. The corpus starts small but will grow as more source material is added over time.

**Existing Tooling:** The `folio-enrich` project (at `~/Coding Projects/folio-enrich`) provides a mature enrichment pipeline with:
- Three-path hybrid extraction: EntityRuler (exact pattern matching), LLM concept extraction, and semantic entity ruler
- 5-stage confidence scoring: initial extraction → reconciliation → resolution with embedding blending → contextual reranking → branch judge
- Span-based annotation model with full lineage tracking
- 13 export formats (JSON, JSON-LD, RDF/Turtle, HTML, etc.)
- Per-task LLM routing with fallback modes

**FOLIO Ontology:** The Functional Ontology for Legal Information Objects (from alea-institute/FOLIO on GitHub) provides ~18,000 standardized legal concepts with IRIs, branch categories, preferred/alternative labels, and definitions. To be fetched from GitHub.

**folio-python:** The `folio-python` library (at `~/Coding Projects/folio-python`) provides the authoritative IRI generation method (`FOLIO.generate_iri()` in `folio/graph.py`) using a WebProtege-compatible algorithm: UUID4 → base64 → alphanumeric-only filter → `https://folio.openlegalstandard.org/{token}`. This must be used for all new IRI generation.

**Knowledge Types to Extract:**
1. **Actionable advice** — techniques, strategies, tips (e.g., "always pin down the expert's methodology before challenging conclusions")
2. **Legal principles** — foundational rules that govern advocacy (e.g., "the rule of completeness")
3. **Case citations** — referenced cases that illustrate or support points
4. **Procedural rules** — required steps, filing deadlines, court procedures
5. **Common pitfalls** — mistakes to avoid, warnings, anti-patterns

**Extraction Philosophy:**
- **Ideas, not expressions.** Extract the underlying concept/technique, not the author's specific wording. The output should be distilled knowledge, not quoted passages.
- **Important reminders matter.** Even if an advocacy principle is "obvious" or likely in an LLM's training data, extract it if it's important. These serve as structured reminders — the value is in the organized, task-linked, FOLIO-mapped form, not novelty.
- **Surprising insights get priority.** Flag knowledge that is counterintuitive, non-obvious, or unlikely to be in model weights. These are the highest-value extractions.
- **As simple as possible, but no simpler.** Each distilled idea should be expressed in the minimum words needed to fully convey the concept. Include all necessary detail and nuance — but strip away filler, hedging, and redundancy.

**Architecture Decision:** Extend folio-enrich pipeline rather than building new tooling. Add new pipeline stages for advice boundary detection and knowledge type classification.

## Constraints

- **Ontology format**: Must output valid OWL (and companion SKOS/RDFS) compatible with existing FOLIO structure
- **Pipeline reuse**: Must build on folio-enrich's existing architecture — not duplicate it
- **Growing corpus**: Architecture must handle incremental additions without reprocessing everything
- **Multi-consumer**: Output must serve SPARQL queries, LLM retrieval, and human browsing

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Extend folio-enrich rather than build new pipeline | Avoid duplicating proven extraction/scoring logic; leverage existing 13 export formats | — Pending |
| Full FOLIO ontology coverage (not subset) | Advocacy texts touch procedural, evidentiary, and substantive law — limiting branches would miss connections | — Pending |
| Discover task hierarchy from texts (not predefined) | Source material may reveal task structures the user hasn't considered; more robust than manual taxonomy | — Pending |
| Core mappings in OWL + detailed advice in companion file | Keeps FOLIO OWL clean while allowing rich advice structure in a linked artifact | — Pending |
| Automated quality with spot-checking | Corpus will grow — manual review doesn't scale; invest in confidence scoring instead | — Pending |
| Both human-reviewable and machine-parseable enriched output | Enables validation workflow while feeding Stage 2 structuring | — Pending |
| Advice as annotation properties on Task/Subtask classes | Simplest model — advice "goes with the class." Confidence/source metadata lives in companion SKOS file, not OWL. | — Pending |
| Use folio-python's IRI generation for all new IRIs | WebProtege-compatible algorithm ensures compatibility with FOLIO's existing IRI patterns | — Pending |

---
*Last updated: 2026-03-17 after initialization*
