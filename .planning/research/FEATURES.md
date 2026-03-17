# Feature Research

**Domain:** Legal knowledge extraction and ontology enrichment (advocacy textbooks to FOLIO OWL)
**Researched:** 2026-03-17
**Confidence:** HIGH (existing pipeline well-understood; domain patterns established in NLP/KG research; PROJECT.md requirements clear)

## Feature Landscape

### Table Stakes (Users Expect These)

Features that must work or the system produces no usable output. For a knowledge extraction pipeline, "users" are the downstream consumers (SPARQL queries, LLM retrieval systems, human browsers) and the operator running the pipeline.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Markdown source ingestion** | The corpus is MD files of variable length; the system is useless without this entry point | LOW | Reuse folio-enrich's ingestion stage with MD format support already present via DocumentFormat.MARKDOWN. Must handle front matter, headings, lists, inline citations, mixed chapter extracts and synthesized notes. |
| **Advice unit boundary detection** | Core extraction unit. Without segmenting text into discrete knowledge units, everything downstream operates on garbage. This is the critical-path bottleneck. | HIGH | LLM-driven semantic segmentation. Units range from single sentences to multi-paragraph blocks. 2025 research confirms LLM embeddings significantly improve semantic text segmentation accuracy. Must handle flowing prose without explicit delimiters. Boundaries are semantic, not syntactic. |
| **Knowledge type classification** | Each extracted unit must be typed (actionable advice, legal principle, case citation, procedural rule, pitfall) so consumers can filter and prioritize | MEDIUM | Five types defined in PROJECT.md. LLM classifier with confidence scores. Map to a small local taxonomy that bridges into FOLIO concept space. Clear taxonomy makes this tractable. |
| **FOLIO concept tagging** | The entire value proposition rests on mapping knowledge to FOLIO's ~18,000 concepts with IRIs. Without this, output is unstructured text. | HIGH | Reuse folio-enrich's three-path hybrid extraction (EntityRuler + LLM + semantic entity ruler) and 5-stage confidence scoring. Each knowledge unit gets one or more FOLIO concept IRIs with confidence. This is proven infrastructure, not new work. |
| **Multi-stage confidence scoring** | Without confidence, there is no way to filter noise, prioritize review, or set quality thresholds. Every extraction needs a trustworthiness signal. | MEDIUM | Leverage folio-enrich's existing 5-stage pipeline: initial extraction -> reconciliation -> resolution with embedding blending -> contextual reranking -> branch judge. Extend to cover advice-specific extraction quality. |
| **Task hierarchy discovery** | Practitioners query by task ("Taking a Deposition"), not by textbook chapter. Without task hierarchy, knowledge is a flat list -- which PROJECT.md explicitly identifies as insufficient. | HIGH | Discover top-level advocacy tasks from texts themselves (depositions, opening statements, motions, cross-examination, etc.), not from a predefined list. LLM-driven taxonomy induction. Cross-document aggregation required. |
| **Hierarchical task tree construction** | Sub-tasks and best practices organized under each discovered task. The tree IS the product's organizational backbone. | HIGH | Build tree: Task > Subtask > Best Practice / Principle / Pitfall. Must merge task fragments discovered across multiple source files. Depends on both task discovery and knowledge unit extraction being complete. |
| **OWL export with FOLIO compatibility** | FOLIO is OWL-based; output must be valid OWL importable alongside existing FOLIO structure or it cannot be consumed | MEDIUM | Core class/property mappings in OWL. Reuse rdflib patterns from folio-enrich's RDFExporter. Must validate against existing FOLIO OWL structure. |
| **Companion file for detailed advice** | Keeps FOLIO OWL clean (structural mappings only) while providing rich advice content in a linked SKOS/RDFS artifact | MEDIUM | W3C-sanctioned pattern: OWL for formal structure, SKOS for human-readable content with skos:narrower/broader for hierarchy, custom properties for advice content. Link via IRIs. Per KEY DECISION in PROJECT.md. |
| **Extraction provenance / lineage tracking** | Every extracted knowledge unit must trace back to source file, chapter, paragraph, and extraction method. Without this, nothing is auditable. | MEDIUM | Extend folio-enrich's existing lineage model (StageEvent records). Add source_file, source_span, chapter context, and extraction_method fields. Critical for credibility and review. |
| **Human-reviewable enriched output** | Intermediate output must be readable by humans for spot-checking quality. Automated quality with spot-checking is a KEY DECISION. | LOW | JSON or annotated MD showing extracted units, their types, FOLIO tags, confidence scores, and source attribution. Must be both human-reviewable and machine-parseable per PROJECT.md requirements. |
| **Batch pipeline execution** | Runs as batch, not interactive. Process all source files in a corpus run. | LOW | CLI or script-triggered pipeline. No real-time requirement per PROJECT.md out-of-scope constraints. |
| **"Ideas not expressions" distillation** | Core extraction philosophy, not an enhancement. Extracts underlying concepts/techniques rather than quoting passages. Without this, output risks copyright issues and is less useful than raw text. | HIGH | Built into boundary detection and extraction prompts. LLM must distill while preserving nuance. "As simple as possible, but no simpler" is a hard instruction to operationalize. Must be validated from day one. |

### Differentiators (Competitive Advantage)

Features that make this system distinctly more valuable than generic knowledge extraction or manual ontology curation.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Surprise / novelty flagging** | Automatically flags counterintuitive or non-obvious insights unlikely to be in LLM training data. These are the highest-value extractions per extraction philosophy. | MEDIUM | Compare extracted knowledge against LLM "common knowledge" baseline. If the LLM would not have generated this advice unprompted, flag as high-novelty. Contrastive prompting or log-probability analysis. |
| **Cross-document advice deduplication** | When multiple textbooks say the same thing differently, merge into one canonical knowledge unit with multiple source references. Prevents bloated ontology. | HIGH | Embedding similarity + LLM judge for ambiguous pairs. Must distinguish "same advice differently worded" from "similar but importantly different advice." A two-stage pipeline: vector similarity for obvious matches, LLM reasoning for edge cases. |
| **Confidence-gated auto-approval** | High-confidence extractions proceed automatically; only low-confidence units are flagged for review. Scales with growing corpus without proportional manual effort. | LOW | Threshold-based: above 0.85 auto-approve, below 0.5 flag for review, between = spot-check sample. Requires seeing real confidence distributions before tuning thresholds. |
| **Cross-source task tree merging** | Merges task hierarchy fragments from multiple books into a single coherent tree. Book A covers deposition prep, Book B covers deposition questioning -- both merge under "Depositions." | HIGH | Entity resolution across sources for task names. Merge strategies: union subtasks, reconcile conflicting advice, preserve source attribution. Ontology alignment at the task level. |
| **Conflict detection across sources** | When two sources give contradictory advice on the same task, flag rather than silently picking one. Preserves nuance for practitioners. | MEDIUM | Semantic similarity between advice units tagged to the same task + knowledge type. High similarity + content contradiction = flag. Requires nuanced LLM contradiction detection. |
| **SPARQL-optimized knowledge structure** | Output RDF/OWL is designed for practical SPARQL queries like "give me all pitfalls for depositions" or "all advice tagged with evidence law concepts." | MEDIUM | Design RDF schema with query patterns in mind. Use named graphs for provenance. Index by task, knowledge type, FOLIO branch, and confidence level. |
| **Multi-consumer output formats** | Same knowledge base serves SPARQL queries, LLM RAG retrieval, and direct human browsing. Three consumption modes from one pipeline. | MEDIUM | Three output shapes: (1) OWL/RDF for SPARQL, (2) JSON/JSON-LD chunks for RAG, (3) structured MD/HTML for browsing. Leverage folio-enrich's 13 existing export formats. |
| **Incremental corpus growth** | New source files added without reprocessing entire corpus. Architecture handles growth per PROJECT.md constraints. | MEDIUM | Content-hash-based change detection. Append-merge for task trees. Incremental OWL update without regenerating the full file. Only needed once corpus is large enough that full reprocessing is slow. |
| **Importance-aware extraction** | Even "obvious" advocacy principles get extracted (they serve as structured reminders), but novelty scoring distinguishes expected from surprising. | LOW | Two-tier: (1) novelty score (surprising vs. expected), (2) significance score (critical vs. minor). Both inform priority but neither filters. Per extraction philosophy: important reminders matter. |
| **Idempotent / re-runnable pipeline** | Operators iterate on extraction quality and re-run. Pipeline must not produce duplicates or corrupt state. | MEDIUM | Hash-based deduplication on input content. Deterministic output keyed by source + span + concept. Overwrite-on-rerun semantics. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but would damage the project's goals, violate its constraints, or create unsustainable complexity.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **User-facing legal advice UI** | Natural desire to "see" the knowledge in a polished interface | Explicitly out of scope per PROJECT.md. UI design is a separate project. Consumers build their own on top of the ontology. Coupling pipeline to a specific UI pattern limits downstream flexibility. | Export HTML for human browsing. Provide SPARQL endpoint. Produce well-documented output formats that any UI can consume. |
| **Substantive legal analysis / correctness evaluation** | "Is this advice actually correct?" | The system extracts what books say, not evaluates legal merit. Correctness evaluation requires a licensed attorney and creates liability. Explicitly out of scope per PROJECT.md. | Extract faithfully. Tag confidence in extraction quality, not legal correctness. Let practitioners evaluate substance. |
| **Real-time / interactive processing** | "Process this paragraph right now" | Batch pipeline with LLM calls, embedding generation, and OWL serialization is inherently latency-heavy. Interactive mode would compromise quality. Explicitly out of scope per PROJECT.md. | Batch pipeline with fast turnaround. Incremental processing handles "add one more file" without full rerun. |
| **Predefined task taxonomy** | "I already know the task categories -- just use my list" | Per KEY DECISION in PROJECT.md: discovering from texts is more robust. Source material may reveal tasks, sub-tasks, and cross-cutting concerns that a predefined list would miss. Limits the system to what the operator already knows. | Discover task hierarchy from texts. Let operator validate/prune the discovered taxonomy after extraction. |
| **Source text rewriting / paraphrasing** | "Make the advice sound better" or "standardize the language" | Explicitly out of scope per PROJECT.md. Introduces copyright risk, loses fidelity to source meaning, adds unnecessary LLM generation step. Rewriting is not extracting. | Distill to ideas (not expressions). Keep concise but faithful to the underlying concept. |
| **Full source text preservation** | "Store the original text alongside the extraction for reference" | Risks copyright issues (reproducing substantial portions of published textbooks). Contradicts "ideas, not expressions" philosophy. | Store source file reference + approximate location. The extracted unit is a distilled concept, not a quoted passage. |
| **Automatic FOLIO ontology extension** | "Add new concepts to FOLIO when the books mention things FOLIO doesn't cover" | FOLIO is a shared standard with its own governance (ALEA Institute, CC-BY). Unilateral extension creates incompatible forks. | Map to nearest FOLIO concept. Flag unmapped knowledge units as "candidate FOLIO additions" in a separate report. Propose through proper channels. |
| **Multi-language support** | FOLIO has translations for 10 languages | Source corpus is English advocacy textbooks. Premature internationalization adds complexity without value. | Build for English. Leverage FOLIO's existing multilingual labels passively. Add multilingual support only if/when non-English source material arrives. |
| **Citation verification / link resolution** | "Verify cited cases are real and correctly cited" | Requires access to legal databases (Westlaw, LexisNexis, CourtListener). Separate infrastructure and licensing concern. | Extract citations as-is with structured parsing via folio-enrich's eyecite/citeurl. Flag for downstream verification. |
| **Fine-grained manual review of every extraction** | "I want to approve each one" | Doesn't scale. Manual review of thousands of knowledge units is a bottleneck that kills the project. Per KEY DECISION: automated quality with spot-checking. | Confidence-gated auto-approval. Statistical spot-checking. Invest in better confidence scoring rather than more human review. |

## Feature Dependencies

```
[MD Source Ingestion]
    |
    v
[Advice Unit Boundary Detection] + ["Ideas not Expressions" Distillation]
    |                                  (embedded in boundary detection prompts)
    |
    +---> [Knowledge Type Classification]
    |         |
    |         +---> [Surprise / Novelty Flagging] (enhances classification)
    |
    +---> [FOLIO Concept Tagging] <--- requires FOLIO ontology loaded
    |         |
    |         +---> [Multi-Stage Confidence Scoring] (applied at each stage)
    |
    +---> [Source Attribution / Lineage Tracking] (applied at each stage)
    |
    +---> [Citation Extraction] (parallel, reuses folio-enrich individuals)

[Task Hierarchy Discovery] (cross-document, parallel with per-unit extraction)
    |
    v
[Hierarchical Task Tree Construction]
    |
    +---> [Cross-Source Task Tree Merging] (enhances tree with multi-book data)
    |
    +---> [Cross-Document Advice Deduplication] (post-merge)
    |
    +---> [Conflict Detection] (post-merge, flags contradictions)

[OWL Output Generation] + [Companion File Generation]
    |--- requires: [FOLIO Concept Tagging] + [Task Tree] + [Knowledge Type Classification]
    |
    v
[Multi-Consumer Output Formats] (OWL, SPARQL-optimized RDF, RAG chunks, HTML)

[Incremental Processing] --- wraps entire pipeline with change detection
[Confidence-Gated Auto-Approval] --- wraps output with review gates
[Idempotent Pipeline] --- ensures re-runnability without duplicates
```

### Dependency Notes

- **Advice Boundary Detection is the critical-path bottleneck.** Everything downstream depends on well-segmented knowledge units. If boundaries are wrong, every subsequent stage operates on garbage. This must be the first thing that works well. "Ideas not expressions" distillation is embedded in the boundary detection prompts, not a separate stage.
- **FOLIO Concept Tagging reuses proven infrastructure.** The folio-enrich pipeline's three-path extraction and 5-stage confidence scoring already work. This is a "plug in" dependency, not "build from scratch." But the tagging must work on distilled knowledge units (not full document text), which changes the input characteristics.
- **Task Hierarchy Discovery runs independently of per-unit extraction.** It reads across all source documents to find the task structure, while advice extraction operates within individual documents. They can run in parallel, then be merged.
- **Knowledge Type Classification informs FOLIO tagging.** Knowing whether a unit is advice vs. citation vs. procedural rule helps constrain which FOLIO branches to search and how to weight matches.
- **Cross-Document Deduplication requires the full corpus.** Cannot deduplicate until all documents are processed. Late-stage, cross-cutting concern.
- **OWL Export depends on everything upstream.** It serializes the final knowledge structure. Must be the last stage.
- **Incremental Processing, Idempotent Pipeline, and Confidence-Gated Approval are orthogonal.** They wrap the pipeline and can be added after the core flow works end-to-end.
- **Conflict Detection only fires during cross-source merging.** When two books cover the same task with contradictory advice, flag it. No value in single-source mode.
- **Novelty flagging enhances classification** but does not block it. Can be added as a scoring dimension after basic classification works.

## MVP Definition

### Launch With (v1)

Minimum viable pipeline: process source files, extract structured knowledge units, tag against FOLIO, organize by task, produce OWL output.

- [ ] **MD source ingestion** -- accept a directory of MD files, parse structure (headings, paragraphs, lists)
- [ ] **Advice unit boundary detection** -- LLM-driven segmentation into knowledge units with "ideas not expressions" distillation built into prompts
- [ ] **Knowledge type classification** -- tag each unit as advice, principle, citation, rule, or pitfall
- [ ] **FOLIO concept tagging** -- map units to FOLIO concepts using folio-enrich's hybrid extraction
- [ ] **Multi-stage confidence scoring** -- reuse folio-enrich's 5-stage confidence pipeline
- [ ] **Task hierarchy discovery** -- discover top-level tasks from corpus
- [ ] **Hierarchical task tree construction** -- organize extracted knowledge under discovered tasks with sub-task structure
- [ ] **OWL output generation** -- valid OWL with core structural mappings
- [ ] **Companion file generation** -- SKOS/RDFS companion for detailed advice content
- [ ] **Lineage / provenance tracking** -- source file, chapter, approximate location, extraction method for every unit
- [ ] **Human-reviewable JSON output** -- intermediate format for spot-checking extraction quality

### Add After Validation (v1.x)

Features to add once the core pipeline produces good output on the initial corpus and task hierarchy is validated.

- [ ] **Surprise / novelty flagging** -- requires baseline extraction to calibrate what's "surprising." Add once knowledge units are flowing.
- [ ] **Cross-document advice deduplication** -- needed when multiple source files cover overlapping topics. Requires seeing real duplicates to tune similarity thresholds.
- [ ] **Confidence-gated auto-approval** -- threshold tuning requires seeing real confidence distributions from production runs.
- [ ] **Idempotent re-runnable pipeline** -- hash-based dedup. Essential before iterating on extraction quality.
- [ ] **Multi-consumer output formats** -- add RAG-optimized JSON chunks and browsable HTML/MD beyond OWL. Leverage folio-enrich's 13 export formats.

### Future Consideration (v2+)

Features to defer until the pipeline is proven and the corpus is substantial.

- [ ] **Cross-source task tree merging** -- only valuable when multiple books cover overlapping tasks
- [ ] **Conflict detection across sources** -- dependent on cross-source merging
- [ ] **Incremental corpus growth** -- only needed when corpus is large enough that full reprocessing is slow
- [ ] **SPARQL-optimized knowledge structure** -- optimize RDF schema after initial output is validated with real queries
- [ ] **LLM-retrieval-optimized export** -- optimize chunk structure for RAG after extraction quality is proven
- [ ] **Importance-aware extraction ranking** -- refine two-tier priority scoring after initial calibration
- [ ] **FOLIO candidate concept reporting** -- report unmatched concepts as suggestions for FOLIO maintainers

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| MD source ingestion | HIGH | LOW | P1 |
| Advice unit boundary detection | HIGH | HIGH | P1 |
| Knowledge type classification | HIGH | MEDIUM | P1 |
| FOLIO concept tagging | HIGH | MEDIUM (reuses folio-enrich) | P1 |
| Confidence scoring | HIGH | LOW (reuses folio-enrich) | P1 |
| Task hierarchy discovery | HIGH | HIGH | P1 |
| Task tree construction | HIGH | HIGH | P1 |
| OWL output generation | HIGH | MEDIUM | P1 |
| Companion file (SKOS) | HIGH | MEDIUM | P1 |
| Lineage / provenance | MEDIUM | LOW (extends folio-enrich) | P1 |
| Human-reviewable output | MEDIUM | LOW | P1 |
| "Ideas not expressions" | HIGH | HIGH (embedded in P1 extraction) | P1 |
| Surprise / novelty flagging | MEDIUM | MEDIUM | P2 |
| Cross-document dedup | MEDIUM | HIGH | P2 |
| Confidence-gated auto-approval | MEDIUM | LOW | P2 |
| Idempotent pipeline | MEDIUM | MEDIUM | P2 |
| Multi-consumer formats | MEDIUM | LOW (reuses folio-enrich) | P2 |
| Cross-source merging | MEDIUM | HIGH | P3 |
| Conflict detection | LOW | MEDIUM | P3 |
| Incremental processing | MEDIUM | MEDIUM | P3 |
| SPARQL optimization | MEDIUM | LOW | P3 |
| RAG-optimized export | MEDIUM | LOW | P3 |
| Importance ranking | LOW | LOW | P3 |
| FOLIO candidate reporting | LOW | LOW | P3 |

**Priority key:**
- P1: Must have for launch -- pipeline produces structured, task-organized, FOLIO-mapped knowledge from source files
- P2: Should have -- quality refinement, deduplication, multi-format output
- P3: Nice to have -- cross-source intelligence, consumer-specific optimization, corpus scaling

## Competitor/Comparable Feature Analysis

This is a novel niche (legal advocacy knowledge extraction into FOLIO ontology), so there are no direct competitors. The closest comparables operate in adjacent spaces:

| Feature | Generic KG Construction (KARMA, ODKE+) | Legal NLP (John Snow Labs, LexNLP, ASKE) | Legal KM Systems (NetDocs, Everlaw) | Our Approach |
|---------|----------------------------------------|-----------------------------------------|-------------------------------------|--------------|
| Knowledge extraction | Entity/relation extraction from unstructured text | Legal entity extraction (parties, citations, provisions) | Document-level metadata tagging | Advocacy-specific knowledge unit extraction (advice, principles, pitfalls) -- novel knowledge type taxonomy |
| Ontology alignment | Generic ontology mapping, schema-constrained | Legal ontology alignment (varies by project) | Proprietary taxonomy, not OWL-based | FOLIO-specific tagging with 18K concepts using proven three-path hybrid extraction |
| Task hierarchy | Not typically present | Not present | Matter-centric organization | Core differentiator: task-centric hierarchy discovered from corpus, not predefined |
| Confidence scoring | LLM self-assessment, single-pass | Per-entity confidence | Binary relevant/not-relevant | 5-stage graduated confidence pipeline (proven in folio-enrich) |
| Output formats | RDF, JSON-LD, KG databases | JSON, Python objects, Spark annotations | Proprietary formats | OWL + SKOS companion + 13 export formats via folio-enrich |
| Incremental updates | Streaming architectures (SAGA) | Typically batch | Real-time document processing | Planned: content-hash-based incremental with merge |
| Provenance | Triple-level provenance | Varies, often minimal | Document-level audit trail | Annotation-level lineage with source file, span, extraction method, full stage history |
| Ideas vs. expressions | Extracts entities/relations as-is | Extracts legal provisions as-is | Stores documents as-is | Distills underlying concepts -- unique to this system's extraction philosophy |
| Novelty detection | Not present | Not present | Not present | Unique differentiator: flags counterintuitive insights unlikely in model weights |

**Key insight:** No existing system combines (1) advice-level semantic segmentation, (2) mapping to a comprehensive legal ontology, (3) task hierarchy discovered from corpus, and (4) OWL-compatible output with a companion advice file. This is a novel pipeline composition, not a novel technique at any individual stage.

## Sources

- [FOLIO - Federated Open Legal Information Ontology](https://openlegalstandard.org/)
- [FOLIO GitHub Repository](https://github.com/alea-institute/FOLIO)
- [FOLIO Plans New Features, LLM-Powered Tools (2025)](https://www.law.com/legaltechnews/2025/08/28/legal-matter-standard-project-folio-plans-new-features-llm-powered-tools/)
- [Legal-Onto: Ontology-based Legal Document Analysis (Springer, 2025)](https://link.springer.com/article/10.1007/s42979-025-04432-0)
- [LLM-Enhanced Semantic Text Segmentation (MDPI, 2025)](https://www.mdpi.com/2076-3417/15/19/10849)
- [Structural Text Segmentation of Legal Documents (ICAIL)](https://arxiv.org/abs/2012.03619)
- [Knowledge Graph Validation via LLMs + Human-in-the-Loop (ScienceDirect, 2025)](https://www.sciencedirect.com/science/article/pii/S030645732500086X)
- [KARMA: Multi-Agent LLMs for Automated KG Enrichment](https://openreview.net/pdf?id=k0wyi4cOGy)
- [Ontology Design Best Practices (Enterprise Knowledge)](https://enterprise-knowledge.com/ontology-design-best-practices-part/)
- [Using OWL and SKOS (W3C)](https://www.w3.org/2006/07/SWD/SKOS/skos-and-owl/master.html)
- [LexNLP: NLP for Legal and Regulatory Texts](https://arxiv.org/abs/1806.03688)
- [Legal NLP Survey (arXiv, 2024)](https://arxiv.org/html/2410.21306v1)
- [Document Segmentation with LLMs (Instructor)](https://python.useinstructor.com/examples/document_segmentation/)
- [Automated Taxonomy Construction Using LLMs (MDPI, 2025)](https://www.mdpi.com/2673-4117/6/11/283)
- [From LLMs to Knowledge Graphs: Production Systems 2025](https://medium.com/@claudiubranzan/from-llms-to-knowledge-graphs-building-production-ready-graph-systems-in-2025-2b4aff1ec99a)
- [Legal Ontologies and KG Resources (Liquid Legal Institute)](https://github.com/Liquid-Legal-Institute/Legal-Ontologies)
- [ASKE: Context-Aware Legal Information Extraction](https://www.sciencedirect.com/science/article/pii/S0267364923001139)
- Existing `folio-enrich` codebase (~/Coding Projects/folio-enrich): pipeline architecture, annotation models, 13 export formats, FOLIO service, OWL updater

---
*Feature research for: Legal knowledge extraction and ontology enrichment (Alea Advocate)*
*Researched: 2026-03-17*
