# Project Research Summary

**Project:** Alea Advocate — Legal Knowledge Extraction & Ontology Enrichment
**Domain:** Legal NLP / Ontology engineering / Knowledge graph construction
**Researched:** 2026-03-17
**Confidence:** HIGH

## Executive Summary

Alea Advocate is a specialized batch pipeline that extracts structured advocacy knowledge from legal textbooks (in Markdown format) and enriches the FOLIO ontology with a hierarchical task-centric knowledge structure. It is not a general-purpose NLP tool — it is a purpose-built extension on top of the existing `folio-enrich` system, which already handles FOLIO concept tagging, confidence scoring, and RDF serialization. The recommended approach is to build a **separate batch orchestrator** that imports `folio-enrich` services as a library via a bridge adapter rather than modifying its internals, adding exactly four new Python packages (`instructor`, `owlrl`, `pySHACL`, `networkx`) on top of the existing stack. The entire product value rests on a four-stage pipeline: (1) extract and classify knowledge units from MD source files with FOLIO concept tags, (2) discover and build a hierarchical advocacy task tree across the corpus, (3) generate OWL and companion JSON-LD output, and (4) validate the standalone ontology module before delivery.

The critical architectural decision is the "core in OWL, details in companion file" split — formal class hierarchy in a standalone `advocacy-knowledge.owl` module that references FOLIO via `rdfs:seeAlso` rather than physically merging with the 293,603-line FOLIO.owl, and detailed advice content in a linked `advocacy-companion.jsonld` file. This keeps FOLIO interoperable and upgradeable while allowing rich annotation. The system serves three output consumers that must be designed for from day one: SPARQL queries, LLM RAG retrieval, and human browsing. Designing for one and retrofitting the others is a documented high-cost failure mode — the data model must accommodate all three from the initial `KnowledgeUnit` design.

The two highest risks are (1) advice boundary detection granularity — if segmentation into knowledge units is wrong, every downstream stage inherits the error with no recovery short of full re-extraction — and (2) LLM hallucination, which is particularly dangerous because the "ideas not expressions" extraction philosophy actively encourages rephrasing that can drift from source material. Both must be addressed in Phase 1 with gold-standard validation sets and source grounding verification, not deferred. FOLIO concept mapping recall collapse (80%+ of extractions concentrating on 50 generic concepts) and task hierarchy over/under-splitting are Phase 2 risks requiring vocabulary bridging and minimum evidence thresholds respectively.

---

## Key Findings

### Recommended Stack

The existing `folio-enrich` stack (Python 3.13, FastAPI, spaCy 3.8.11, rdflib 7.6.0, FAISS, folio-python 0.2.0) is the foundation — all new work is additive. Only four genuinely new production dependencies are needed: `instructor` for structured LLM output with Pydantic auto-retry, `owlrl` for OWL2 RL reasoning without a JVM dependency, `pySHACL` for SHACL constraint validation of generated RDF, and `networkx` for in-memory task tree operations before RDF serialization. A dual-library strategy including Owlready2 was evaluated and explicitly rejected because it cannot handle punned entities (a documented limitation that would cause silent data loss with FOLIO classes that appear as individuals in some contexts), requires Java for its HermiT/Pellet reasoner, and would introduce a parallel graph system conflicting with folio-enrich's existing rdflib-based architecture.

**Core technologies:**
- **rdflib 7.6.0** — OWL/RDF graph construction, SPARQL, multi-format serialization — already in folio-enrich; handles FOLIO.owl's RDF/XML format natively
- **instructor 1.14.5** — structured LLM output with Pydantic validation and auto-retry — replaces fragile JSON parsing; type-safe objects for every extraction; supports Anthropic, OpenAI, and 15+ providers
- **folio-python 0.2.0** — FOLIO ontology access, 18K concept index, 7-strategy label search, IRI resolution — already in folio-enrich; critical for concept mapping
- **owlrl 7.1.4** — OWL2 RL forward-chaining inference — pure Python, no JVM; sufficient for consistency checking without Owlready2
- **pySHACL 0.31.0** — SHACL constraint validation of generated OWL output before delivery
- **networkx 3.0+** — in-memory task tree graph operations (cycle detection, topological sort, subtree extraction) before SKOS serialization
- **spaCy 3.8.11** — sentence segmentation, dependency parsing; structural pre-pass to feed into LLM extraction prompts
- **markdown-it-py** — MD AST parsing for heading hierarchy and section boundary extraction from source files
- **Skosify 2.0.1** (optional) — SKOS hierarchy validation (cycle breaking, duplicate label detection) on companion file output

### Expected Features

All four research files converge on the same feature prioritization. The pipeline delivers no value until advice unit boundary detection and FOLIO concept tagging both work end-to-end — these are co-dependencies that gate everything downstream.

**Must have (table stakes — P1):**
- MD source ingestion with heading hierarchy preservation
- Advice unit boundary detection with "ideas not expressions" distillation embedded in extraction prompts
- Knowledge type classification (advice / principle / citation / procedural rule / pitfall — five types)
- FOLIO concept tagging via folio-enrich's three-path hybrid extraction (EntityRuler + LLM + semantic ruler)
- Multi-stage confidence scoring (reuse folio-enrich's 5-stage pipeline)
- Task hierarchy discovery from corpus — LLM-driven induction, not from a predefined list (this is an explicit PROJECT.md key decision)
- Hierarchical task tree construction (Task > Sub-task > Best Practice / Principle / Pitfall)
- OWL output generation as standalone module with ADV-prefixed IRIs
- Companion JSON-LD file for detailed advice content linked to OWL IRIs
- Extraction provenance and lineage tracking for every knowledge unit
- Human-reviewable JSON intermediate output for quality spot-checking
- Batch CLI execution (no real-time interactive mode — explicitly out of scope)

**Should have (competitive differentiators — P2):**
- Surprise/novelty flagging for counterintuitive insights (contrastive LLM prompting)
- Cross-document advice deduplication (embedding similarity + LLM judge for ambiguous pairs)
- Confidence-gated auto-approval (≥0.80 auto-approve, 0.60–0.80 spot-check, <0.60 exclude and log)
- Idempotent re-runnable pipeline with content-hash-based change detection
- Multi-consumer output formats (SPARQL-optimized RDF, RAG-optimized JSON chunks, browsable HTML/MD)

**Defer (v2+ — P3):**
- Cross-source task tree merging (only valuable with substantial multi-book corpus overlap)
- Conflict detection across sources (requires cross-source merging)
- Incremental corpus growth without full reprocessing (only needed when corpus is large enough)
- SPARQL query optimization of RDF schema after initial query patterns are validated
- FOLIO candidate concept reporting for unmatched knowledge units
- Importance-aware extraction ranking beyond novelty/confidence

**Anti-features (explicitly out of scope per PROJECT.md):**
- User-facing legal advice UI
- Substantive legal correctness evaluation
- Real-time / interactive processing mode
- Automatic FOLIO ontology extension (governance concern)
- Full source text preservation (copyright risk)
- Multi-language support (English-only source corpus)

### Architecture Approach

The system is a four-stage batch pipeline that builds on top of folio-enrich without modifying it. The key structural insight verified by direct folio-enrich codebase inspection is that folio-enrich is a general-purpose document enrichment tool with 586 tests across 45 files — adding advocacy-specific stages to its orchestrator would pollute its architecture and risk breaking its test suite. Instead, folio-enrich services (`FolioService`, `EmbeddingService`, LLM registry) are imported as a library via a `FolioEnrichBridgeStage` adapter. The alea-advocate orchestrator runs its own four-stage pipeline with checkpointing (each stage writes JSON to disk before the next stage begins, enabling resume from the last checkpoint on failure).

**Major components:**
1. **MD Ingestion** — parse source files into heading hierarchy, sections, paragraphs with structural metadata (`section_path: list[str]`)
2. **Stage 1: FOLIO Tagger** — two-pass knowledge unit boundary detection (structural heuristics then LLM refinement), type classification, FOLIO concept tagging via bridge to folio-enrich services, surprise scoring, distillation; produces `KnowledgeUnit` objects with full lineage trail
3. **Stage 2: Task Tree Builder** — two-pass LLM-driven task discovery (task identification across corpus, then per-task hierarchical organization), cross-reference assignment, near-duplicate detection; produces validated `TaskTree` JSON
4. **Stage 3: OWL Mapper** — task tree to OWL axioms with deterministic ADV-prefixed IRI generation (BLAKE2b hash of task path), companion JSON-LD with full knowledge unit content; produces `advocacy-knowledge.owl` + `advocacy-companion.jsonld`
5. **Stage 4: OWL Validator** — 7-step validation pipeline (XML well-formedness, RDF parse, IRI collision check, referential integrity, namespace consistency, companion link integrity, roundtrip parse test)
6. **Corpus Registry** — content-hash-based tracking of processed files for incremental processing
7. **Quality Gate** — confidence-gated output filtering at Stage 1→2 boundary and Stage 3 output

**Key patterns to follow:**
- Bridge pattern for folio-enrich services (import specific services: EntityRuler, EmbeddingService, LLM concepts, reconciliation — do NOT run the full 16-stage pipeline per knowledge unit)
- Batch orchestrator with per-stage JSON checkpointing for resumability
- Deterministic IRI generation (same corpus always produces same IRIs; idempotent re-runs)
- Per-document extraction results stored separately from merged corpus output (enables corpus-level reconciliation re-runs without full reprocessing)
- Standalone OWL module with `rdfs:seeAlso` links to FOLIO (no physical merge into 293K-line FOLIO.owl)

### Critical Pitfalls

1. **Advice boundary detection granularity mismatch** — LLMs produce inconsistent segmentation; legal advocacy prose interleaves multiple techniques without explicit delimiters; deep hierarchies in textbooks are an unsolved problem for state-of-the-art LLMs. Prevention: gold-standard validation set of 50–100 manually annotated boundaries from representative source material; precision/recall metrics against this set before scaling; two-pass detection (structural heuristics handle 70–80% cheaply; LLM resolves ambiguous cases).

2. **LLM hallucination in knowledge extraction** — the "ideas not expressions" mandate encourages rephrasing that opens the door to semantic drift, fabricated citations, and advice that is generically true but not in the source text. LLMs assign consistently high confidence to their own fabrications, so confidence scoring alone cannot catch this. Prevention: source grounding verification for every extraction (identify the specific source span; flag if none found), citations treated as near-verbatim extraction, LLM temperature set to 0 for extraction, explicit negative instructions ("do not include anything not in the provided text").

3. **FOLIO concept mapping recall collapse** — naive matching concentrates 80%+ of mappings on 50 generic FOLIO concepts while thousands of specific appropriate concepts go unused, because advocacy textbooks use practitioner language that doesn't match formal ontology preferred labels. Prevention: vocabulary bridge using `skos:altLabel` and concept definitions (not just preferred labels), pre-filtering FOLIO concepts by branch relevance to reduce search space per extraction, monitoring concept distribution statistics (flag when top 20 concepts account for >70% of all mappings).

4. **Task hierarchy over/under-splitting** — LLMs confidently produce hierarchies whether or not the underlying structure supports them; no ground truth exists for what the "right" task hierarchy looks like. Prevention: seed taxonomy from source material tables of contents as structural prior (not fixed taxonomy), minimum evidence threshold (at least 5 distinct advice units per task node before promotion to confirmed), human review checkpoint specifically for top-level task structure.

5. **OWL ontology corruption during import** — programmatic OWL generation introduces silent structural errors (polysemous elements, missing disjointness, namespace collisions, class/instance confusion) that corrupt SPARQL results without immediate visible failures; OOPS! catalogue documents 40+ such pitfalls. Prevention: OOPS! pitfall scanner on every generated OWL output as CI check, never use string manipulation for OWL serialization, always use rdflib's graph API, keep generated content in standalone module (not merged into FOLIO.owl).

---

## Implications for Roadmap

Architecture research identifies clear stage data dependencies: Stage 1 must produce knowledge units before Stage 2 can build task trees; Stage 2 must produce task trees before Stage 3 can generate OWL; Stage 4 validates Stage 3's output. This dictates a natural four-phase structure aligned with the four pipeline stages. The pitfalls research adds a critical cross-cutting constraint: multi-consumer output design must be addressed at the data model level in Phase 1, not deferred to the export phase — the `KnowledgeUnit` model must support SPARQL, RAG retrieval, and human browsing from initial design.

### Phase 1: Foundation + Core Extraction Pipeline

**Rationale:** Everything depends on Stage 1. If boundary detection is wrong, every downstream stage inherits the error — and the two highest-risk pitfalls (boundary granularity, hallucination) must be solved here, not discovered later. folio-enrich integration via the bridge pattern must also be established before any FOLIO tagging is possible. The multi-consumer data model must be designed correctly from the start.
**Delivers:** Working extraction of typed, FOLIO-tagged knowledge units from MD source files; human-reviewable JSON output with full lineage; gold-standard boundary validation set with measurable precision/recall; source grounding coverage metric above threshold.
**Addresses (FEATURES.md P1):** MD source ingestion, advice unit boundary detection, "ideas not expressions" distillation, knowledge type classification, FOLIO concept tagging, multi-stage confidence scoring, lineage tracking, human-reviewable output.
**Avoids (PITFALLS.md):** Advice boundary granularity mismatch (gold standard + two-pass detection), LLM hallucination (source grounding verification, temperature 0, negative instructions in prompts), multi-consumer data model afterthought (`KnowledgeUnit` model designed for all three consumers from day one).
**Stack:** spaCy (structural pre-pass), instructor (structured LLM output), FolioEnrichBridgeStage (imports folio-enrich services), markdown-it-py (MD AST parsing), rdflib + Pydantic (data models).
**Research flag:** Needs deeper research on prompt engineering for legal advocacy text segmentation and gold-standard validation set construction methodology before implementation begins.

### Phase 2: Task Hierarchy Discovery and Structuring

**Rationale:** Task tree building has strict data dependency on Phase 1 output. The hierarchy IS the product's organizational backbone — "any practitioner querying 'how do I take an expert deposition' gets a structured, hierarchical set of techniques, principles, and warnings" (PROJECT.md). The vocabulary bridge for FOLIO mapping recall should also be built here, using real Phase 1 mapping output to identify where the practitioner-to-formal-label gap is widest.
**Delivers:** Validated hierarchical task tree across corpus; cross-references for multi-task knowledge units; near-duplicate detection and deduplication; vocabulary bridge improving FOLIO concept recall; surprise/novelty scoring on knowledge units.
**Addresses (FEATURES.md P1/P2):** Task hierarchy discovery (LLM-driven, not predefined), hierarchical task tree construction, cross-document advice deduplication, surprise/novelty flagging.
**Avoids (PITFALLS.md):** Task hierarchy over/under-splitting (seed taxonomy prior, minimum evidence threshold of 5 units per node, human review checkpoint for top-level structure), FOLIO concept mapping recall collapse (vocabulary bridge with altLabel matching, branch pre-filtering, concept distribution monitoring).
**Stack:** networkx (in-memory tree operations, cycle detection, topological sort), instructor (LLM-driven task discovery structured output), FAISS (near-duplicate detection via embedding cosine similarity ~0.85 threshold).
**Research flag:** Needs research on task hierarchy merging strategies across source files; prompt engineering for two-pass task discovery; vocabulary bridge construction approach against actual source material.

### Phase 3: OWL Output Generation and Companion File

**Rationale:** OWL generation depends on a validated task tree from Phase 2. This phase is structurally more mechanical than Phases 1 and 2 once mapping rules are defined, but OWL corruption risks are high and the companion file must serve all three consumer modes. The standalone module strategy (not physical merge into FOLIO.owl) is non-negotiable for maintainability.
**Delivers:** `advocacy-knowledge.owl` standalone module with ADV-prefixed deterministic IRIs, `rdfs:subClassOf` hierarchy mirroring task tree, `rdfs:seeAlso` links to FOLIO; `advocacy-companion.jsonld` with full advice content, confidence scores, source citations; validated output passing OOPS! scanner and OWL consistency check; all three consumer modes (SPARQL, RAG chunks, human-browsable HTML/MD) tested with realistic queries.
**Addresses (FEATURES.md P1/P2):** OWL output generation, companion file generation, SPARQL-optimized knowledge structure, multi-consumer output formats.
**Avoids (PITFALLS.md):** OWL ontology corruption (OOPS! scanner as CI check, 7-step validation pipeline, no physical FOLIO.owl merge), multi-consumer output mismatch (all three consumption modes tested before declaring phase complete).
**Stack:** rdflib 7.6.0 (OWL/SKOS serialization, JSON-LD), owlrl (OWL2 RL consistency checking), pySHACL (SHACL constraint validation), lxml (XML well-formedness), Skosify (SKOS hierarchy validation), folio-python (IRI collision checking against FOLIO concept space).
**Research flag:** IRI generation strategy (ADV-prefixed BLAKE2b hash) needs validation against FOLIO's actual IRI format conventions to confirm no unforeseen collision patterns. Standard OWL generation patterns are well-documented; no other deep research needed.

### Phase 4: Pipeline Quality and Incremental Processing

**Rationale:** Cross-cutting concerns that wrap the pipeline — confidence-gated output, idempotent re-runs, corpus registry, spot-check tooling — are essential before iterating on extraction quality with a growing corpus. The key architectural requirement is designing incremental processing as a document-level vs. corpus-level reconciliation split, not just hash-based file tracking, to avoid the "inconsistent state" pitfall when new source material restructures the task hierarchy.
**Delivers:** Idempotent, re-runnable pipeline (reprocessing a processed document produces no duplicates); confidence-gated auto-approval with configurable thresholds calibrated against real extraction output; corpus registry tracking processed files with content hashes; spot-check sampling tooling for manual review of flagged units; hierarchy health check after new document additions.
**Addresses (FEATURES.md P2):** Confidence-gated auto-approval, idempotent pipeline, incremental corpus growth foundation.
**Avoids (PITFALLS.md):** Incremental processing creating inconsistent state (document-level vs. corpus-level reconciliation split; per-document results stored separately; hierarchy health check on each new batch; deduplication at corpus reconciliation time, not document processing time).
**Stack:** Pydantic (CorpusManifest model), FAISS (incremental embedding deduplication across corpus), SHA-256 content-hash-based file change detection.
**Research flag:** Standard patterns; no deep research needed. Implementation should follow the document-level vs. corpus-level split documented in PITFALLS.md.

### Phase Ordering Rationale

- Stage data dependencies (Stage 1 → 2 → 3 → 4) map directly to phases — there is no viable alternative ordering without producing unusable intermediate output.
- The two highest-risk pitfalls (boundary detection granularity, LLM hallucination) both occur in Phase 1 and have the highest recovery cost if discovered late; front-loading gold-standard validation is not optional for project health.
- The vocabulary bridge (FOLIO concept mapping recall collapse) belongs in Phase 2 rather than Phase 1 because it requires seeing real mapping output to identify where practitioner-vs-formal-label gaps are most severe.
- OWL generation in Phase 3 is structurally simpler than Phases 1 and 2 but requires rigorous validation; the standalone module approach deliberately avoids touching FOLIO.owl and its associated risk.
- Cross-cutting quality concerns (Phase 4) must be formalized before the corpus grows but depend on real confidence distributions from Phases 1–3 to calibrate thresholds correctly.
- Architecture research (ARCHITECTURE.md) explicitly confirms this build order under "Suggested Build Order" with the same rationale.

### Research Flags

Phases needing deeper research during planning:

- **Phase 1:** Prompt engineering for advice boundary detection in legal advocacy text has no established best practice — needs research into instructor-based document segmentation patterns, optimal context window strategies for long chapters, and validation set construction methodology before implementation.
- **Phase 2:** Task hierarchy discovery via LLM across a corpus is an active research area with known failure modes; the two-pass discovery strategy needs prompt engineering research. Vocabulary bridge construction requires analyzing actual source material vocabulary against FOLIO labels/altLabels — cannot be completed without access to source materials.
- **Phase 3 (partial):** ADV-prefix IRI generation strategy needs validation against FOLIO's actual IRI format conventions before implementation to confirm no unforeseen collision or format incompatibility risks.

Phases with standard, well-documented patterns (skip research-phase):

- **Phase 3 (OWL generation):** rdflib OWL generation, SKOS companion file structure, pySHACL validation, OOPS! scanner integration are all well-documented. The companion-file architecture pattern is from W3C guidance.
- **Phase 4 (incremental processing):** Content-hash change detection, corpus registry, and document-level vs. corpus-level reconciliation split are straightforward engineering patterns with clear implementation guidance from ARCHITECTURE.md.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified on PyPI and GitHub with release dates. folio-enrich dependency list inspected directly from `backend/pyproject.toml`. Owlready2 rejection backed by documented punned-entity limitation in independent benchmark. All 4 new dependencies are actively maintained (latest releases 2025–2026). |
| Features | HIGH | Feature landscape derives directly from explicit PROJECT.md requirements and key decisions. Feature dependencies verified against folio-enrich's actual codebase. Academic research confirms LLM-based segmentation patterns and multi-consumer design requirements. |
| Architecture | HIGH | Bridge pattern recommendation backed by direct folio-enrich codebase inspection: `PipelineStage` ABC, `FolioService` singleton, `EmbeddingService`, `RDFExporter`, `OWLUpdateManager` all directly examined. FOLIO.owl format confirmed from 293K-line disk cache. All integration points are concrete, not speculative. |
| Pitfalls | HIGH | Each pitfall backed by multiple authoritative sources: legal NLP surveys, OOPS! catalogue (40+ catalogued OWL pitfalls), LLM confidence calibration research, OWL reasoner comparison papers, taxonomy construction research. Pitfall-to-phase mapping provides actionable prevention with concrete metrics. |

**Overall confidence:** HIGH

### Gaps to Address

- **Source material vocabulary analysis:** The vocabulary bridge for FOLIO concept mapping (addressing recall collapse) requires analyzing actual advocacy textbook terminology against FOLIO's 18K concept labels, alternative labels, and definitions. This can only be done with access to the source materials and cannot be completed from research alone. Must be the first task in Phase 2.
- **Confidence threshold calibration:** The thresholds in the confidence gate (0.80 auto-approve, 0.60–0.80 spot-check, <0.60 exclude) are initial estimates based on folio-enrich's existing pipeline patterns. Actual thresholds must be calibrated against real extraction output from Phase 1 before Phase 4 implementation. Do not treat these as fixed values.
- **Gold-standard boundary validation set construction:** Research confirms this is essential for Phase 1 success, but constructing it requires manual annotation of 50–100 advice boundaries from actual source material. This is a human task that must be scoped into Phase 1 effort estimates.
- **Task hierarchy seed taxonomy:** A seed taxonomy of top-level advocacy tasks (derived from source material tables of contents) should be established before Phase 2 task discovery begins. This requires examining the actual source materials, not general research.
- **LLM provider selection for extraction tasks:** instructor supports 15+ providers. The optimal provider for legal text extraction (Anthropic Claude vs. OpenAI) at temperature 0 has not been benchmarked against advocacy textbook content specifically. folio-enrich's per-task LLM routing infrastructure supports provider switching, but routing configuration for new task types needs to be defined during Phase 1 setup.
- **folio-python 0.2.0 LLM search capabilities:** The library's LLM-powered search features (mentioned in FOLIO April 2025 release notes) have not been fully evaluated for advocacy concept matching. May reduce the need for custom vocabulary bridging — investigate during Phase 2.

---

## Sources

### Primary (HIGH confidence — verified against official sources or direct codebase inspection)

- **folio-enrich codebase** (directly inspected): `pipeline/orchestrator.py`, `pipeline/stages/base.py`, `services/export/rdf_exporter.py`, `services/folio/folio_service.py`, `services/folio/owl_updater.py`, `services/folio/owl_cache.py`, `models/annotation.py`, `backend/pyproject.toml`
- **FOLIO.owl** (disk cache at `~/.folio/cache/github/*.owl`, 293,603 lines): OWL Class structure with `rdfs:subClassOf`, `rdfs:label`, `skos:prefLabel`, `skos:definition`, `skos:altLabel`, `skos:example` annotations; Object Properties with `rdfs:domain`, `rdfs:range`, `owl:inverseOf`; IRI patterns confirmed
- [rdflib PyPI](https://pypi.org/project/rdflib/) — v7.6.0, Feb 13, 2026
- [instructor PyPI](https://pypi.org/project/instructor/) — v1.14.5, Jan 29, 2026
- [pySHACL GitHub](https://github.com/RDFLib/pySHACL/releases) — v0.31.0, Jan 16, 2026
- [OWL-RL GitHub](https://github.com/RDFLib/OWL-RL) — v7.1.4
- [folio-python GitHub](https://github.com/alea-institute/folio-python) — v0.2.0
- [FOLIO GitHub](https://github.com/alea-institute/FOLIO) — ~18K concepts, structure confirmed
- [W3C Web Annotation Data Model](https://www.w3.org/TR/annotation-model/) — W3C Recommendation
- [W3C: Using OWL and SKOS](https://www.w3.org/2006/07/SWD/SKOS/skos-and-owl/master.html) — OWL/SKOS integration patterns for companion files

### Secondary (MEDIUM confidence — community consensus, multiple sources agree)

- [Comparing Python ontology libraries (2025)](https://incenp.org/notes/2025/comparing-python-ontology-libraries.html) — rdflib vs. Owlready2 benchmark; punned entity limitation confirmed; rdflib recommended for RDF/XML manipulation
- [OOPS! OntOlogy Pitfall Scanner Catalogue](https://oops.linkeddata.es/catalogue.jsp) — 40+ catalogued OWL ontology development pitfalls
- [LLM-Enhanced Semantic Text Segmentation (MDPI, 2025)](https://www.mdpi.com/2076-3417/15/19/10849) — LLM embeddings significantly improve semantic text segmentation accuracy
- [Automated Taxonomy Construction Using LLMs (MDPI, 2025)](https://www.mdpi.com/2673-4117/6/11/283) — taxonomy induction strategies; general term boundary problems
- [A Language Model based Framework for New Concept Placement in Ontologies](https://arxiv.org/html/2402.17897) — concept placement challenges; "edges are over 3.5x the number of concepts" — search space complexity
- [Knowledge Graphs, LLMs, and Hallucinations (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S1570826824000301) — KG-RAG hallucination mitigation; confidence score limitations
- [Survey on legal information extraction](https://link.springer.com/article/10.1007/s10115-025-02600-5) — comprehensive survey of NLP challenges in legal domain
- [Leveraging LLMs for legal terms extraction](https://link.springer.com/article/10.1007/s10506-025-09448-8) — boundary annotation discrepancies between experts and LLMs
- [FOLIO April 2025 Updates](https://openlegalstandard.org/april-2025-folio-updates/) — folio-python v0.2.0 release notes
- [Ontology enrichment using a large language model (ScienceDirect, 2025)](https://www.sciencedirect.com/science/article/pii/S1532046425000942) — automated concept placement evaluation; "zero-shot LLM prompting is still not adequate"

### Tertiary (LOW confidence — single source or inference)

- [From LLMs to Knowledge Graphs: Production-Ready Systems (2025)](https://medium.com/@claudiubranzan/from-llms-to-knowledge-graphs-building-production-ready-graph-systems-in-2025-2b4aff1ec99a) — production KG construction patterns; single source, needs validation
- [TaxoGen: Unsupervised Topic Taxonomy Construction](https://arxiv.org/pdf/1812.09551) — general term boundary problems in taxonomy construction; academic, needs domain validation for legal advocacy context
- [Incremental Ontology Population and Enrichment through Semantic-based Text Mining](https://www.researchgate.net/publication/292139184_Incremental_Ontology_Population_and_Enrichment_through_Semantic-based_Text_Mining) — incremental enrichment challenges; older research, patterns may have evolved

---
*Research completed: 2026-03-17*
*Ready for roadmap: yes*
