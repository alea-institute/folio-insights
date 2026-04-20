# Technology Stack

**Project:** FOLIO Insights (Legal Knowledge Extraction & Ontology Enrichment)
**Researched:** 2026-03-17

## Foundational Constraint: Extend folio-enrich

The existing `folio-enrich` pipeline (Python 3.13, FastAPI, spaCy, rdflib 7.6.0, FAISS, folio-python 0.2.0) is the foundation. All recommendations below are additive -- they extend the existing stack rather than replacing it. The existing codebase already provides:

- Three-path hybrid extraction (EntityRuler, LLM, semantic ruler)
- 5-stage confidence scoring pipeline
- Span-based annotation with full lineage tracking (Pydantic models)
- 13 export formats including RDF/Turtle, JSON-LD, HTML
- Per-task LLM routing with fallback modes
- W3C Open Annotation (OA) vocabulary for RDF export

---

## Recommended Stack

### 1. OWL/Ontology Manipulation

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **rdflib** | 7.6.0 | RDF graph construction, SPARQL queries, multi-format serialization | Already in folio-enrich. The standard Python RDF library with 15+ years of maturity. Active development (7.6.0 released Feb 2026, v8 alpha in progress). Handles Turtle, RDF/XML, JSON-LD, N-Triples. Built-in SKOS/OWL/RDFS namespace support. folio-enrich's RDF exporter already uses it for OA-based OWL/SKOS output. | HIGH |
| **owlrl** | 7.1.4 | OWL2 RL forward-chaining inference on rdflib Graphs | Lightweight OWL reasoning without Java. Expands graphs with inferred triples via forward chaining. Pure Python atop rdflib -- no external reasoner process needed. Use for consistency checking and materializing inferred class memberships when importing advice into FOLIO. | HIGH |
| **pySHACL** | 0.31.0 | SHACL constraint validation of produced RDF/OWL graphs | Validates output graphs conform to FOLIO's structural expectations before import. Catches malformed triples, missing required properties, cardinality violations. Part of the RDFLib ecosystem -- integrates seamlessly. Released Jan 2026. | HIGH |
| **folio-python** | 0.2.0 | FOLIO ontology access: concept lookup, hierarchy traversal, IRI resolution | Already in folio-enrich. Provides the ~18,000 concept index, 7-strategy label search, parent/child traversal, OWL XML export. Critical for mapping extracted knowledge to FOLIO IRIs. Uses lxml and httpx under the hood. | HIGH |

#### Decision: rdflib-only (NOT Owlready2) for OWL manipulation

Owlready2 (v0.50, Feb 2026) is the main alternative. It offers a Pythonic object-oriented interface and built-in HermiT/Pellet reasoning. A dual-library strategy (rdflib + Owlready2) was considered but rejected:

1. **folio-enrich already uses rdflib everywhere** -- the RDF exporter, JSON-LD exporter, concept detail service, and SPARQL queries all use rdflib's Graph API. Introducing Owlready2 creates two parallel graph systems that must be kept in sync.
2. **Owlready2 cannot handle punned entities** -- a documented limitation. FOLIO uses OWL classes that may also appear as individuals in certain contexts; this limitation could cause silent data loss.
3. **Owlready2 requires Java for reasoning** -- HermiT and Pellet are Java-based. This adds a JVM dependency to what is currently a pure-Python stack. owlrl provides sufficient OWL2 RL reasoning without Java.
4. **rdflib + owlrl covers our actual needs** -- we need graph construction, SPARQL queries, serialization, and basic inference. We do not need ontology-oriented programming (treating classes as Python objects), which is Owlready2's primary value proposition.
5. **Owlready2's SQLite quadstore adds storage complexity** -- we serialize to files (Turtle, RDF/XML), not databases. The quadstore is overhead we don't need.
6. **Performance gap is irrelevant** -- Owlready2's SPARQL is ~60x faster than rdflib's on large ontologies, but we're operating on subgraphs (per-document annotations), not querying the full 18,000-concept FOLIO graph via SPARQL at runtime. folio-python handles FOLIO lookups via its own index.

**Recommendation:** Use rdflib 7.6.0 as the single RDF/OWL library. Use owlrl for inference when needed. Do NOT add Owlready2.

---

### 2. Knowledge Extraction from Text

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **spaCy** | 3.8.11 | Sentence segmentation, dependency parsing, NER, tokenization | Already in folio-enrich. Provides the linguistic backbone for text processing. Use SentenceRecognizer for advice boundary detection base units. Use dependency parsing for clause-level analysis. | HIGH |
| **instructor** | 1.14.5 | Structured LLM output extraction with Pydantic validation and auto-retry | The standard library for getting reliable structured data from LLMs (3M+ monthly downloads, 11k GitHub stars). Validates LLM output against Pydantic models (which folio-enrich uses everywhere). Supports Anthropic Claude, OpenAI, and 15+ providers. Auto-retries when validation fails. Deep nesting support for hierarchical extraction. | HIGH |
| **httpx** | >=0.28.0 | Async HTTP client for LLM API calls | Already in folio-enrich. instructor uses it under the hood for API calls. | HIGH |
| **nupunkt** | >=0.1.0 | Legal-domain sentence boundary detection | Already in folio-enrich. Purpose-built for legal text where standard tokenizers fail on citations (e.g., "42 U.S.C. ss 1983") and abbreviations. Zero external dependencies. From ALEA Institute (same org as FOLIO). | HIGH |

#### How knowledge extraction works in this system

The extraction pipeline is fundamentally **LLM-driven, not NLP-driven**. spaCy provides structural analysis (sentence boundaries, dependency trees, POS tags) that feeds into LLM prompts as context. The actual intelligence -- identifying advice boundaries, distilling ideas, classifying knowledge types, discovering task hierarchies -- is done by the LLM through structured prompts validated by instructor.

`instructor` is the glue that turns LLM responses into validated Pydantic models. Without it, you're parsing JSON by hand and hoping the LLM didn't hallucinate a field. With it, you get:
- Automatic Pydantic validation of every LLM response
- Retry with feedback when the model returns invalid data
- Type-safe Python objects you can immediately use
- Support for deeply nested models (advice hierarchies, nested spans)

#### What NOT to use for extraction

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Gensim** | Topic modeling is not what we need. We extract structured knowledge units, not discover latent topics. | instructor + LLM structured extraction |
| **Hugging Face Transformers** (directly) | Overkill. We call hosted LLMs via API, not run local models. If local models were needed, spaCy's transformer pipelines would be the integration point. | instructor with hosted LLM APIs |
| **LangChain** | Too heavy. Massive dependency tree (100+ packages). We need structured extraction, not agent chains or RAG frameworks. instructor is narrower and better for our specific need. | instructor |
| **LlamaIndex** | Same problem as LangChain -- designed for RAG, not structured extraction from known text. | instructor |
| **spacy-llm** | Couples LLM calls to spaCy's pipeline in ways that conflict with folio-enrich's existing per-task LLM routing architecture (TaskLLMs). | instructor + folio-enrich's existing LLM routing |
| **PydanticAI** | Better for agentic workflows with tool use. This project needs extraction, not agents. instructor is more focused on the extraction use case. | instructor |

---

### 3. Hierarchical Knowledge Structuring & Taxonomy Building

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **rdflib + SKOS namespace** | 7.6.0 | Build SKOS concept schemes with broader/narrower hierarchy | SKOS is the W3C standard for taxonomies and thesauri. FOLIO itself uses SKOS (skos:prefLabel, skos:altLabel, skos:broader). rdflib has first-class SKOS namespace support (rdflib.namespace.SKOS). No additional library needed. | HIGH |
| **Skosify** | 2.0.1 | Validate and clean SKOS output | Checks for hierarchy cycles (and breaks them), duplicate prefLabels (and converts extras to altLabels), missing required SKOS properties. Low-maintenance but stable for its focused purpose. From the National Library of Finland. | MEDIUM |
| **networkx** | >=3.0 | In-memory graph operations on task hierarchies before RDF serialization | For building, traversing, and analyzing task trees (cycle detection, topological sort, subtree extraction, depth analysis) before converting to SKOS/OWL. Lightweight, well-understood, no RDF overhead for intermediate processing. | HIGH |

#### How taxonomy building works

1. **LLM extracts task mentions** from text (e.g., "taking a deposition", "challenging expert testimony")
2. **LLM groups and hierarchizes** tasks into a tree (parent tasks, sub-tasks, techniques) via instructor-validated Pydantic models
3. **networkx represents** the in-memory tree for structural validation (no cycles, consistent depth, no orphans)
4. **rdflib serializes** the validated tree as SKOS concepts with skos:broader/skos:narrower relationships within a skos:ConceptScheme
5. **Skosify validates** the SKOS output against best practices (label uniqueness, hierarchy soundness)
6. **Task hierarchy links to FOLIO** via custom owl:AnnotationProperty or skos:related relationships to FOLIO concept IRIs

---

### 4. RDF/OWL Serialization and Import

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **rdflib** | 7.6.0 | Serialize to Turtle, RDF/XML, JSON-LD, N-Triples | Already covered above. folio-enrich's RDF exporter already demonstrates Turtle serialization with OA vocabulary. Extend for OWL class/individual creation. | HIGH |
| **folio-python** | 0.2.0 | Access FOLIO OWL structure for compatible import | Provides concept lookup and OWL XML export of individual concepts. Understanding FOLIO's structure ensures additions are compatible. | HIGH |
| **lxml** | >=5.0 | OWL/XML parsing for precise manipulation | Already a folio-python dependency. For low-level XML manipulation of OWL files when rdflib's graph abstraction is insufficient (e.g., preserving FOLIO's existing XML structure, namespace declarations, and comment blocks during merging). | HIGH |

#### Serialization strategy

The project has a key architectural decision: "Core mappings in OWL + detailed advice in companion file." This means two output artifacts:

1. **FOLIO OWL additions** (via rdflib): New OWL classes/individuals representing advocacy task concepts. Minimal, structural. Serialized as OWL/XML to be compatible with FOLIO.owl's format.
2. **Companion advice file** (via rdflib): Rich SKOS concept scheme with advice units linked to FOLIO IRIs. Serialized as Turtle for human readability and as JSON-LD for machine consumption.
3. **Structured JSON** (via Pydantic .model_dump()): The full extraction output for downstream consumers (LLM retrieval, API, UI browsing).

---

### 5. Span-Based Annotation Format

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **W3C Web Annotation (OA) vocabulary** | W3C Rec | Annotation data model for spans, targets, bodies | folio-enrich already uses OA (oa:Annotation, oa:hasTarget, oa:hasBody, oa:start, oa:end, oa:exact) in its RDF exporter. W3C standard with rdflib namespace support. Extending for nested spans uses existing OA mechanisms (SpecificResource, selector refinement). | HIGH |
| **Pydantic models** (custom, extending folio-enrich) | >=2.7.0 | In-memory representation of nested span annotations | folio-enrich's existing Annotation/Span/ConceptMatch models are the foundation. Extend with nesting support and knowledge-type classification. | HIGH |

#### Nested span strategy

The existing folio-enrich Span model is flat (start, end, text). For advice extraction, we need nesting:

```
Chapter span (entire chapter)
  Section span (topic area)
    Advice unit span (multi-sentence advice)
      Citation span (embedded case reference)
      Concept span (FOLIO concept mention)
```

**Approach:** Extend existing Pydantic Span/Annotation models with:
- `parent_id: str | None` -- links to containing annotation
- `children: list[str]` -- IDs of contained annotations
- `depth: int` -- nesting level (0 = top-level)
- `knowledge_type: str` -- "advice" | "principle" | "citation" | "procedural_rule" | "pitfall"
- `distilled_idea: str` -- the extracted, distilled concept (not the source text)
- `surprise_score: float` -- how counterintuitive/non-obvious (per PROJECT.md's extraction philosophy)

**For RDF serialization**, OA SpecificResource with TextPositionSelector handles nested targeting. The RDF exporter already outputs flat OA annotations -- extending to nested spans means adding oa:refinedBy selector chains.

**For human review**, the JSON format (via Pydantic .model_dump()) is the primary review format. The existing HTML exporter can be extended to render nested spans with visual indentation and knowledge-type color coding.

#### What NOT to use for annotations

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **STAM** (Stand-off Text Annotation Model, v0.12.1) | Interesting project with Rust-backed Python bindings, but it introduces an entirely separate annotation ecosystem with its own JSON/CSV serialization formats. folio-enrich already has a mature OA-based annotation model with 13 export formats. STAM would require porting everything to a new system for marginal benefit. | W3C OA + Pydantic (already in folio-enrich) |
| **Prodigy/Label Studio formats** | These are annotation tool I/O formats, not data models. If human annotation tooling is needed later, export to their formats from our OA model. | W3C OA internally, export to tool formats as needed |
| **BRAT standoff format** | Legacy format, limited nesting support, no RDF alignment. | W3C OA |
| **Custom JSON schema** | OA gives us RDF interoperability for free; a custom schema would be a dead end for semantic web consumers. | W3C OA vocabulary |

---

## Supporting Libraries (Carried from folio-enrich)

| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| **pyahocorasick** | >=2.0.0 | Fast multi-pattern string matching | Reuse for fast advice-keyword detection as pre-filter before LLM extraction |
| **faiss-cpu** | >=1.8 | Vector similarity search | Reuse for semantic matching of advice to FOLIO concepts and for advice deduplication |
| **markdown-it-py** | >=3.0.0 | Parse MD source files | Critical -- all source material is MD. Produces token stream for heading hierarchy and section boundary extraction |
| **eyecite** | >=2.7 | Legal citation extraction | Extracts case citations -- one of the five knowledge types |
| **citeurl** | >=12.0 | Legal citation URL normalization | Resolves citations to canonical URLs |
| **FastAPI** | >=0.115.0 | API layer | Already in folio-enrich; reuse for pipeline orchestration endpoints |
| **Pydantic** | >=2.0 | Data model validation | Foundation for instructor; defines extraction schemas; pervasive in folio-enrich |
| **pydantic-settings** | >=2.7.0 | Configuration management | Already in folio-enrich; type-safe config with .env support |
| **uvicorn** | >=0.34.0 | ASGI server | Already in folio-enrich |

---

## New Dependencies (Beyond folio-enrich)

```bash
# New production dependencies (only 4 new packages)
pip install "instructor>=1.14.0" "owlrl>=7.1.0" "pyshacl>=0.31.0" "networkx>=3.0"

# Optional: SKOS validation
pip install "skosify>=2.0.0"

# All other dependencies are already in folio-enrich
```

**Total genuinely new dependencies: 4-5** (plus their transitive deps). This is minimal because folio-enrich already provides the heavy infrastructure.

---

## Version Compatibility Matrix

| Library | Min Version | Current Version | Python Req | Status |
|---------|-------------|-----------------|------------|--------|
| rdflib | 7.0.0 | 7.6.0 | >=3.8.1 | Already in folio-enrich |
| spaCy | 3.7.0 | 3.8.11 | >=3.9 | Already in folio-enrich |
| folio-python | 0.2.0 | 0.2.0 | >=3.11 | Already in folio-enrich |
| instructor | 1.14.0 | 1.14.5 | >=3.9 | **NEW** |
| owlrl | 7.1.0 | 7.1.4 | >=3.5 | **NEW** |
| pySHACL | 0.31.0 | 0.31.0 | >=3.8 | **NEW** |
| networkx | 3.0 | 3.4+ | >=3.10 | **NEW** |
| Skosify | 2.0.0 | 2.0.1 | >=3.6 | **NEW** (optional) |

All compatible with Python 3.13 (folio-enrich's runtime).

---

## Key Integration Points with folio-enrich

| folio-enrich Component | Path | Reuse Strategy |
|------------------------|------|----------------|
| `PipelineStage` (ABC) | `pipeline/stages/base.py` | Subclass for: AdviceBoundaryStage, KnowledgeExtractionStage, TaskTreeStage, OWLImportStage |
| `record_lineage()` | `pipeline/stages/base.py` | Track extraction provenance through all new stages |
| `Span`, `Annotation`, `ConceptMatch` | `models/annotation.py` | Extend for nested spans and knowledge-type classification |
| `RDFExporter` | `services/export/rdf_exporter.py` | Extend for OWL class/individual creation and SKOS annotation |
| `FolioService` | `services/folio/folio_service.py` | Reuse concept lookup, label search, hierarchy traversal |
| `EntityRulerStage` | `pipeline/stages/entity_ruler_stage.py` | Reuse for FOLIO concept matching against extracted knowledge units |
| `EmbeddingService` + FAISS | `services/embedding/service.py` | Reuse for semantic similarity when matching advice to FOLIO concepts |
| `OWLUpdateManager` | `services/folio/owl_updater.py` | Model for how to safely update OWL files with pipeline coordination |
| LLM routing | `services/llm/` | Add new task types for advice extraction, task discovery, knowledge classification |

---

## Sources

### Verified with Official Docs/PyPI (HIGH confidence)
- [rdflib PyPI](https://pypi.org/project/rdflib/) -- v7.6.0, Feb 13, 2026
- [rdflib GitHub](https://github.com/RDFLib/rdflib) -- v8 alpha on main branch
- [Owlready2 PyPI](https://pypi.org/project/owlready2/) -- v0.50, Feb 5, 2026 (evaluated and rejected)
- [spaCy PyPI](https://pypi.org/project/spacy/) -- v3.8.11, Nov 17, 2025
- [instructor PyPI](https://pypi.org/project/instructor/) -- v1.14.5, Jan 29, 2026
- [pySHACL GitHub Releases](https://github.com/RDFLib/pySHACL/releases) -- v0.31.0, Jan 16, 2026
- [OWL-RL GitHub](https://github.com/RDFLib/OWL-RL) -- v7.1.4
- [STAM PyPI](https://pypi.org/project/stam/) -- v0.12.1, Jan 5, 2026 (evaluated and rejected)
- [Skosify GitHub](https://github.com/NatLibFi/Skosify) -- v2.0.1
- [folio-python GitHub](https://github.com/alea-institute/folio-python) -- v0.2.0
- [FOLIO GitHub](https://github.com/alea-institute/FOLIO) -- ~18,000 concepts
- [W3C Web Annotation Data Model](https://www.w3.org/TR/annotation-model/) -- W3C Recommendation
- [instructor docs](https://python.useinstructor.com/) -- multi-provider support confirmed

### Comparative Research (MEDIUM confidence)
- [Comparing Python Ontology Libraries (2025)](https://incenp.org/notes/2025/comparing-python-ontology-libraries.html) -- detailed benchmarks of rdflib, Owlready2, py-horned-owl, Pronto, FunOWL, OAK, and others. Key finding: Owlready2 cannot handle punned entities; rdflib works with all tested ontologies.
- [FOLIO April 2025 Updates](https://openlegalstandard.org/april-2025-folio-updates/) -- folio-python v0.2.0 release notes

### folio-enrich Codebase (Directly Verified)
- `backend/pyproject.toml` -- current dependency versions and Python 3.11+ requirement
- `backend/app/services/export/rdf_exporter.py` -- existing OA/RDF export using rdflib Graph, SKOS, OWL namespaces
- `backend/app/models/annotation.py` -- existing Span/Annotation/ConceptMatch Pydantic models
- `backend/app/services/folio/owl_updater.py` -- existing OWL update lifecycle pattern
- `backend/app/services/folio/folio_service.py` -- FOLIOConcept dataclass, label search, hierarchy
- `backend/app/pipeline/stages/base.py` -- PipelineStage ABC and record_lineage() utility
