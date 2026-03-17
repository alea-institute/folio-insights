# Pitfalls Research

**Domain:** Legal knowledge extraction and ontology enrichment
**Researched:** 2026-03-17
**Confidence:** HIGH (multiple authoritative sources across ontology engineering, NLP/LLM extraction, and legal domain research)

## Critical Pitfalls

### Pitfall 1: Advice Boundary Detection Granularity Mismatch

**What goes wrong:**
The system splits source text into knowledge units at the wrong granularity -- either too fine (fragmenting a multi-step technique into meaningless atomic statements) or too coarse (lumping distinct advice items into a single blob). LLMs are particularly bad at consistent boundary detection in legal texts, where a single paragraph may contain three distinct techniques interleaved with a case citation and a warning. Research shows that "deep hierarchies in textbooks seem to be an unsolved problem, even for state-of-the-art LLMs" and that discrepancies between expert annotations and LLM boundary annotations are a primary failure mode in legal term extraction.

**Why it happens:**
Legal advocacy texts are rhetorically complex. Authors embed warnings inside technique descriptions, illustrate principles with extended examples, and layer sub-techniques without explicit boundary markers. An LLM prompt that says "extract advice units" will produce wildly inconsistent results depending on context window, prompt phrasing, and the specific text structure encountered.

**How to avoid:**
- Define a concrete "advice unit" specification with examples of correct and incorrect boundary decisions before writing any extraction code. Include edge cases: multi-paragraph techniques, inline warnings, advice-within-citations.
- Use a two-pass approach: first pass identifies candidate boundaries, second pass validates them against the specification. The first pass can be aggressive (over-split), the second pass merges.
- Build a gold-standard validation set of 50-100 manually annotated advice boundaries from representative source material. Measure precision/recall of boundary detection against this set before scaling.
- Accept partial matches as valid (concept correctly identified but boundary is subset of ideal) rather than requiring exact boundary alignment -- the research community uses this approach for good reason.

**Warning signs:**
- Extracted advice units vary wildly in length (some are 5 words, others are 3 paragraphs) without a clear pattern.
- The same source paragraph produces different unit counts on re-runs.
- Spot-checking reveals units that are incomplete thoughts or duplicate overlapping content.

**Phase to address:**
Phase 1 (Core Extraction Pipeline) -- this is the foundation. If boundaries are wrong, every downstream stage (FOLIO mapping, task hierarchy, OWL export) inherits the error.

---

### Pitfall 2: FOLIO Concept Mapping Recall Collapse

**What goes wrong:**
The system maps extracted knowledge to a tiny fraction of the ~18,000 FOLIO concepts because the matching strategy is too conservative, the search space is too large for naive approaches, or the concept labels don't match the vocabulary used in advocacy texts. Research on ontology concept placement shows that "the number of edges is over 3.5 times the number of concepts," making the search space enormous. The result is that 80%+ of extracted knowledge maps to the same 50 generic FOLIO concepts while thousands of specific, appropriate concepts go unused.

**Why it happens:**
- The FOLIO ontology uses formal legal terminology (e.g., IRI-based concept identifiers, standardized labels) while advocacy textbooks use practitioner language ("pin down the expert" vs. formal evidentiary procedure concepts).
- Naive embedding similarity against 18,000 concepts produces noisy results -- many concepts are semantically close but contextually wrong.
- The existing folio-enrich pipeline's EntityRuler uses exact pattern matching, which misses the vocabulary gap between textbook language and ontology labels.
- Zero-shot LLM prompting for concept placement "is still not adequate for the task" according to recent research, especially for domain-specific ontologies.

**How to avoid:**
- Build a vocabulary bridge: precompute mappings between common advocacy terms and FOLIO concept labels/alternative labels/definitions. Use FOLIO's alternative labels (`skos:altLabel`) and definitions, not just preferred labels.
- Leverage the existing 5-stage confidence scoring in folio-enrich, but add an advocacy-specific calibration step that accounts for the vocabulary gap.
- Monitor concept distribution: track which FOLIO concepts are being used and flag when the distribution is suspiciously concentrated. A healthy mapping should touch at least several hundred distinct concepts across a full textbook.
- Pre-filter FOLIO concepts by branch relevance (procedural law, evidence, civil procedure, etc.) to reduce the search space per extraction before running similarity matching.

**Warning signs:**
- Concept distribution follows extreme power law: top 20 concepts account for 90%+ of all mappings.
- Spot-checking reveals obviously relevant FOLIO concepts that the system never maps to.
- High-confidence mappings cluster around overly generic concepts (e.g., "Legal Proceeding" instead of "Expert Witness Deposition").

**Phase to address:**
Phase 2 (FOLIO Mapping Integration) -- but the vocabulary bridge work should begin during Phase 1 as part of understanding the source material.

---

### Pitfall 3: Task Hierarchy Over-Splitting or Under-Merging

**What goes wrong:**
The automatically discovered task hierarchy is either too flat (all advice grouped under "Trial Advocacy" with no sub-structure) or too deep and fragmented (dozens of micro-categories that no human would recognize as distinct tasks). Research on automatic taxonomy construction from text identifies this as a fundamental tension: "general terms that should remain in the parent topic present challenges to the clustering process, as their embeddings tend to fall on the boundaries of different sub-topics."

**Why it happens:**
- No ground truth for what the "right" task hierarchy looks like. Unlike FOLIO concept mapping (where the ontology provides a target), task hierarchy is discovered -- and different reasonable humans would organize the same material differently.
- Source texts may not cleanly separate into tasks. A deposition chapter might cover examination techniques that also apply to trial testimony.
- LLMs will confidently produce a hierarchy whether or not the underlying structure supports it. They will invent categories to fill perceived gaps.

**How to avoid:**
- Start with a seed taxonomy of top-level advocacy tasks derived from the source material's table of contents. Use this as a structural prior, not a fixed taxonomy -- allow the system to discover sub-tasks and cross-cutting concerns.
- Implement a minimum evidence threshold: a task category must have at least N (e.g., 5) distinct advice units assigned to it before it's promoted from a candidate to a confirmed task node.
- Build in a human review checkpoint specifically for the task hierarchy structure (even though the project favors automated quality). The hierarchy is a one-time structural decision that cascades through everything.
- Use silhouette scores or similar cluster quality metrics to detect when splitting adds no meaningful separation.

**Warning signs:**
- Task categories with only 1-2 advice units (over-splitting).
- Advice units that could equally belong to 3+ task categories (categories not discriminative).
- The hierarchy depth exceeds 4-5 levels without clear semantic distinction between levels.

**Phase to address:**
Phase 2 or Phase 3 (Task Hierarchy Discovery) -- but the seed taxonomy should be established during Phase 1 source material analysis.

---

### Pitfall 4: OWL Ontology Corruption During Import

**What goes wrong:**
Adding extracted knowledge to the FOLIO OWL file introduces structural errors: invalid axioms, broken class hierarchies, namespace collisions, or untyped entities. The OOPS! ontology pitfall scanner catalogues 40+ common pitfalls in OWL ontology development, and automated enrichment tools are particularly prone to: creating polysemous elements (P01), defining wrong inverse/equivalent relationships (P05/P27/P31), missing disjointness axioms (P10), namespace hijacking (P40), and creating untyped classes/properties (P34/P35). These errors may not cause immediate failures but silently corrupt SPARQL query results and reasoner behavior.

**Why it happens:**
- OWL serialization formats (RDF/XML, Turtle, Functional Syntax) have subtle syntactic requirements that programmatic generation can violate.
- The distinction between class-level and instance-level assertions is easy to get wrong when mapping advocacy advice (which is instance-level knowledge) into an ontology that primarily defines class hierarchies.
- Multiple rdfs:domain or rdfs:range statements are interpreted as conjunction (intersection) in OWL, not disjunction -- a frequent source of unintended semantics.
- owl:imports directives can cascade in unexpected ways, pulling in dependencies that conflict with local assertions.

**How to avoid:**
- Never directly manipulate OWL serialization files with string operations. Use a proper OWL library (owlready2 for Python, or RDFLib with careful OWL handling).
- Run the OOPS! pitfall scanner (oops.linkeddata.es) on every generated OWL output as a CI check.
- Validate with an OWL reasoner (HermiT or ELK for the OWL 2 EL profile) after every enrichment batch. Consistency checking is the minimum -- also verify no unsatisfiable classes were introduced.
- Use the "core mappings in OWL + detailed advice in companion file" architecture decision from PROJECT.md. This keeps the FOLIO OWL file structurally clean while allowing rich annotation in a linked SKOS/RDF companion file.
- Keep generated content in a separate OWL module that imports FOLIO rather than modifying FOLIO itself. This preserves upgradeability when FOLIO releases new versions.

**Warning signs:**
- OWL reasoner reports unsatisfiable classes or inconsistency after enrichment.
- SPARQL queries that previously worked return empty results or unexpected results.
- Ontology file size grows disproportionately to the amount of knowledge added (sign of redundant axioms).
- Tools like Protege cannot load the enriched ontology.

**Phase to address:**
Phase 3 (OWL Export/Import) -- but the architecture decision about companion files vs. inline OWL must be finalized in Phase 1.

---

### Pitfall 5: LLM Hallucination in Knowledge Extraction

**What goes wrong:**
The LLM invents legal principles, fabricates case citations, or attributes advice to the source text that does not appear there. This is especially dangerous because the project explicitly extracts "ideas not expressions" -- meaning the output is already a distillation, making it harder to verify against the source. Research shows that "LLMs tend to assign consistently high confidence scores to their own generated outputs" regardless of accuracy, meaning confidence scoring alone cannot catch hallucinations.

**Why it happens:**
- LLMs have extensive legal knowledge in their training data and will confidently blend their own knowledge with what appears in the source text, especially when prompted to "extract" rather than "quote."
- The "ideas not expressions" mandate actively encourages the LLM to rephrase, which opens the door to semantic drift from the source material.
- Case citations are particularly vulnerable: the LLM may "correct" an actual citation to a more famous case, or generate plausible-sounding citations that don't exist.
- Long extraction prompts with many instructions tend to produce more hallucinated content as the model tries to satisfy all requirements.

**How to avoid:**
- Implement source grounding verification: for every extracted knowledge unit, require the system to identify the specific paragraph(s) in the source text that support it. If no source span can be identified, flag the extraction.
- Treat case citations differently from advisory content: citations should be near-verbatim extraction (not "ideas not expressions") and should be validated against citation format patterns and, where possible, against legal citation databases.
- Use the existing folio-enrich confidence scoring pipeline, but add a "hallucination risk" dimension that flags extractions with no clear source span anchor.
- Limit LLM temperature to 0 or near-0 for extraction tasks. Reserve higher temperature for classification/categorization where creativity is acceptable.
- Include negative instructions: "Do not include any legal principle, case citation, or technique that is not discussed in the provided text."

**Warning signs:**
- Extracted case citations that don't appear anywhere in the source text.
- Advice units that are generically true but not discussed in the source material.
- Extraction output that is longer or more detailed than the source passage it came from.
- Confidence scores cluster near 1.0 with insufficient variance.

**Phase to address:**
Phase 1 (Core Extraction Pipeline) -- hallucination prevention must be designed into the extraction prompts and verification pipeline from the start.

---

### Pitfall 6: Incremental Processing Creates Inconsistent State

**What goes wrong:**
As new source material is added over time, the system reprocesses only new documents but the accumulated ontology and task hierarchy become inconsistent: duplicate advice units, conflicting task categorizations, orphaned FOLIO mappings, or a task hierarchy that no longer reflects the full corpus. The fundamental challenge of incremental ontology enrichment is that "the detection of new elements and [their] position in ontology are not automatically established."

**Why it happens:**
- New source material may cover the same topics as existing material but use different terminology, leading to duplicate knowledge units that aren't detected.
- The task hierarchy was discovered from an earlier, smaller corpus. New material may require restructuring the hierarchy (splitting a category, adding a new top-level task), but incremental processing doesn't trigger hierarchy re-evaluation.
- FOLIO concept mappings calibrated on early documents may be poorly calibrated for later documents that cover different legal domains.
- Without a global deduplication step, the ontology accumulates redundant assertions.

**How to avoid:**
- Design the pipeline with a distinction between "document-level processing" (which can be incremental) and "corpus-level reconciliation" (which must run globally after new documents are added).
- Implement semantic deduplication using embedding similarity: before adding any knowledge unit, check if a semantically equivalent unit already exists. Use a conservative threshold (high similarity required to count as duplicate) to avoid false deduplication.
- Version the task hierarchy and corpus state. When new documents are added, run a "hierarchy health check" that validates existing categories still make sense with expanded corpus.
- Store per-document extraction results separately from the merged ontology, so corpus-level reconciliation can always be re-run from scratch if needed.

**Warning signs:**
- Duplicate or near-duplicate advice units appearing in query results.
- Task categories with advice units that clearly belong elsewhere (holdover from pre-restructuring).
- FOLIO concept distribution shifts dramatically between processing batches.
- The enriched ontology contains assertions with no source document provenance.

**Phase to address:**
Phase 1 (Pipeline Architecture) for the document-level vs. corpus-level split. Phase 4 (Incremental Processing) for the reconciliation and deduplication mechanisms.

---

### Pitfall 7: Multi-Consumer Output Design Afterthought

**What goes wrong:**
The system is built and tested primarily for one consumption mode (e.g., SPARQL queries) and then the output turns out to be poorly suited for the other two required consumers (LLM retrieval and human browsing). Retrofitting the output format is expensive because the data model assumptions are baked into the extraction and structuring logic.

**Why it happens:**
- SPARQL, LLM retrieval, and human browsing have fundamentally different requirements. SPARQL needs formal triples with IRI references. LLM retrieval needs natural language chunks with metadata. Human browsing needs navigable hierarchies with readable descriptions.
- It's natural to optimize for whichever consumption mode is tested first, then discover that the serialization doesn't serve other modes.
- Research on knowledge graph representations confirms "there is no consensus on which representations best support each consumer scenario."
- SKOS-based queries have known performance problems: "queries relying on equality or regex filters to do text-based searching are unlikely to perform well enough for real-time user interaction" on datasets over 100K triples.

**How to avoid:**
- Define output requirements for all three consumers before building the export stage. Write sample queries/retrieval patterns for each:
  - SPARQL: "Find all advice related to expert depositions with confidence > 0.8"
  - LLM retrieval: "Retrieve chunked advice about cross-examination techniques with FOLIO concept context"
  - Human browsing: "Navigate task hierarchy, drill into deposition preparation, see all advice with sources"
- Use the existing folio-enrich 13-format export system as a foundation, but ensure the data model supports all three modes from the start.
- Build the OWL/SKOS companion file structure with both formal triples (for SPARQL) and human-readable annotations (for browsing). Store natural language chunks alongside formal representations (for LLM retrieval).
- Test all three consumption modes with realistic queries at the end of each phase, not just at the end of the project.

**Warning signs:**
- All testing uses only one consumption mode (typically SPARQL or direct file inspection).
- Natural language descriptions are stripped during ontology formalization and not preserved anywhere.
- The task hierarchy is only navigable programmatically, not browsable.
- LLM retrieval returns formal triples instead of readable advice chunks.

**Phase to address:**
Phase 1 (Data Model Design) for the multi-consumer data model. Phase 3 (Export) for the format-specific serializations.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| String manipulation instead of OWL library for ontology edits | Faster initial development, no library dependency | Silent ontology corruption, broken axioms, can't validate | Never -- the cost of debugging corrupt OWL outweighs any time savings |
| Skipping confidence scoring for "obvious" extractions | Faster processing, simpler pipeline | No way to distinguish high/low quality extractions downstream; undermines automated quality approach | Never -- even high-confidence extractions need scores for filtering |
| Hardcoded task hierarchy instead of discovered | Faster first version, guaranteed "reasonable" structure | Hierarchy doesn't adapt to new source material; misses cross-cutting concerns the author organized differently | Only acceptable as a seed taxonomy that the discovery process can revise |
| Single-pass extraction (no reconciliation) | Simpler pipeline, faster processing | Misses overlapping/conflicting extractions from different parts of the same text | Only in early prototyping; must add reconciliation before any production use |
| Storing extraction results only in final merged form | Less storage, simpler data model | Cannot re-run corpus-level reconciliation; cannot trace issues back to document-level extraction; blocks incremental processing | Never -- always store per-document extraction results |
| Using only FOLIO preferred labels for matching | Simpler matching logic | Misses the majority of valid mappings where source text uses different terminology than the preferred label | Never -- alternative labels and definitions exist for a reason |

## Integration Gotchas

Common mistakes when connecting to external systems and libraries.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| FOLIO Ontology (GitHub) | Treating FOLIO as static; downloading once and never updating | Pin to a specific FOLIO version tag; build update mechanism to diff new FOLIO versions against enriched content |
| owlready2 / RDFLib | Mixing OWL class-level axioms with instance-level assertions | Clearly separate TBox (class hierarchy, property definitions) from ABox (individual advice instances). Advice is instance-level data, FOLIO concepts are classes |
| folio-enrich Pipeline | Adding new stages that break the Job model contract by mutating unexpected fields | Follow the existing PipelineStage interface exactly; new stages must only add to `job.result.metadata` or `job.result.annotations`; never modify upstream stage outputs |
| LLM API (Ollama/OpenAI) | Using the same prompt for extraction and classification tasks | Extraction prompts should be constrained and grounded ("extract from this text"); classification prompts can reference the full FOLIO concept space. Different tasks need different models, temperatures, and token limits |
| SPARQL Endpoint | Writing queries that iterate over all SKOS labels with regex filters | Pre-index labels; use full-text search extensions; or materialize a label lookup table. Regex-based SPARQL label search does not scale past 100K triples |
| OWL Reasoner | Running full consistency checking on every incremental addition | Batch consistency checks; run after processing groups of documents, not after every single extraction. Use ELK (OWL 2 EL) instead of HermiT for large ontologies -- HermiT may not terminate on 18K+ concept ontologies |

## Performance Traps

Patterns that work at small scale but fail as the corpus grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Embedding similarity search against all 18K FOLIO concepts per extraction | Slow FOLIO mapping; extraction of a single chapter takes hours | Pre-cluster FOLIO concepts by branch; only search relevant branches per extraction. Cache embeddings. Use approximate nearest neighbor (FAISS/Annoy) instead of brute-force similarity | > 500 extractions per batch |
| Loading full OWL ontology into memory for every enrichment run | Memory exhaustion; slow startup | Load ontology once per batch; use persistent triple store (e.g., Oxigraph, Fuseki) for large ontologies rather than in-memory parsing | Enriched ontology exceeds ~100K triples |
| Unbounded LLM context for extraction prompts | Token limit errors; silently truncated context; degraded extraction quality | Chunk source documents to fit within model context window with overlap. Track chunk boundaries to avoid splitting advice units | Source chapters > 8K tokens |
| Full corpus re-embedding on every new document addition | Processing time grows linearly with corpus size for each new document | Incremental embedding updates; only embed new/changed documents. Store and reuse existing embeddings | > 50 source documents |
| Synchronous OWL validation after each extraction | Pipeline throughput drops to < 1 document/hour | Batch validation at end of processing run; use lightweight schema validation per-document and full OWL reasoning per-batch | > 10 documents per batch |

## Security Mistakes

Domain-specific security issues relevant to this project.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Including copyrighted text verbatim in ontology output | Copyright infringement; the project explicitly aims to extract ideas not expressions | Enforce minimum transformation: extracted content must be distilled/rephrased. Implement a similarity check against source text -- flag any extraction with > 80% token overlap with a source passage |
| Storing LLM API keys in pipeline configuration files | Key exposure if ontology or config files are shared | Use environment variables exclusively (folio-enrich already does this via `_try_get_task_llm`). Never log API keys |
| Publishing enriched ontology with sensitive source metadata | Source file paths, processing timestamps, or internal notes leak into public ontology | Strip internal metadata (file paths, processing logs) from export formats. Only include provenance metadata that is safe for publication |

## UX Pitfalls

Common experience problems for the three consumer types.

| Pitfall | Consumer Impact | Better Approach |
|---------|----------------|-----------------|
| FOLIO concept IRIs without human-readable labels in query results | SPARQL consumers see opaque IRIs; must do secondary lookups to understand results | Always include `skos:prefLabel` and `rdfs:comment` alongside IRI references in query-accessible annotations |
| Task hierarchy with inconsistent depth | Human browsers encounter some tasks with 5 levels of sub-tasks and others with none; confusing navigation | Normalize hierarchy depth; ensure consistent granularity across top-level tasks. Use "leaf node" markers to signal terminus |
| Advice chunks too long for LLM retrieval context | LLM retrieval consumers hit token limits or get diluted responses from oversized chunks | Store advice in two forms: full-detail (for human browsing) and distilled summary (for LLM retrieval). Target 200-500 tokens per retrieval chunk |
| No provenance trail visible to consumers | Users cannot assess advice reliability or trace back to source material | Include source document reference, extraction confidence score, and FOLIO mapping confidence in every consumer-facing output |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Extraction pipeline:** Often missing deduplication across documents -- verify that the same advice from two different chapters doesn't appear twice in the ontology
- [ ] **FOLIO mapping:** Often missing alternative label matching -- verify that mappings use `skos:altLabel` and concept definitions, not just `skos:prefLabel`
- [ ] **Task hierarchy:** Often missing cross-references -- verify that advice relevant to multiple tasks is linked to all relevant task nodes, not just the first one discovered
- [ ] **OWL export:** Often missing namespace declarations -- verify that all generated IRIs resolve, all prefixes are declared, and `owl:Ontology` metadata is present
- [ ] **Incremental processing:** Often missing idempotency -- verify that re-processing an already-processed document doesn't create duplicate entries
- [ ] **Confidence scoring:** Often missing calibration -- verify that confidence scores correlate with actual accuracy by spot-checking high vs. low confidence extractions
- [ ] **Multi-consumer output:** Often missing one consumer mode -- verify all three (SPARQL, LLM retrieval, human browsing) work with realistic test queries before declaring export complete
- [ ] **Source grounding:** Often missing hallucination detection -- verify that every extraction can be traced to a specific source passage and that fabricated content is flagged

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Boundary detection mismatch | MEDIUM | Re-run extraction with revised boundary specification; per-document results stored separately means no data loss. Requires re-running FOLIO mapping and hierarchy assignment on affected documents |
| FOLIO mapping recall collapse | MEDIUM | Add vocabulary bridge mappings and re-run FOLIO mapping stage only. Pipeline architecture should allow re-running individual stages without full reprocessing |
| Task hierarchy over/under-splitting | LOW-MEDIUM | Restructure hierarchy and re-assign advice units. If advice units store their own content independently of hierarchy position, this is a metadata-only operation |
| OWL corruption | HIGH | If caught early (CI validation), fix the generation code and re-export. If corruption has propagated into downstream systems, requires full re-export from per-document extraction results. This is why storing per-document results separately is critical |
| LLM hallucination in corpus | HIGH | Must identify and remove fabricated content. If source grounding metadata exists, filter by "no source span" flag. If not, requires manual review of low-confidence or ungrounded extractions. Prevention is far cheaper than recovery |
| Incremental inconsistency | MEDIUM | Re-run corpus-level reconciliation from stored per-document results. This is why the document-level vs. corpus-level architecture split is essential -- it makes recovery a re-run rather than a rebuild |
| Multi-consumer format mismatch | MEDIUM-HIGH | Retrofit data model to support missing consumer. Cost depends on how deeply the single-consumer assumptions are embedded. Early multi-consumer testing limits blast radius |

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Advice boundary granularity mismatch | Phase 1: Extraction Pipeline | Gold-standard validation set; boundary precision/recall metrics above threshold |
| FOLIO concept mapping recall collapse | Phase 2: FOLIO Mapping | Concept distribution analysis; minimum distinct concept count per chapter; spot-check unused relevant concepts |
| Task hierarchy over/under-splitting | Phase 2-3: Task Discovery | Cluster quality metrics; minimum evidence threshold per task node; human review of top-level structure |
| OWL ontology corruption | Phase 3: OWL Export | OOPS! scanner passes; OWL reasoner consistency check; SPARQL smoke tests against enriched ontology |
| LLM hallucination | Phase 1: Extraction Pipeline | Source grounding coverage (% of extractions with identified source span); citation format validation; fabrication detection rate |
| Incremental processing inconsistency | Phase 4: Incremental Pipeline | Idempotency test (reprocess same doc, verify no duplicates); deduplication coverage; hierarchy stability check |
| Multi-consumer output mismatch | Phase 1 (data model) + Phase 3 (export) | Test queries for all three consumers at end of each phase; realistic retrieval/browsing/query scenarios |

## Sources

- [Survey on legal information extraction: current status and open challenges](https://link.springer.com/article/10.1007/s10115-025-02600-5) -- comprehensive survey of NLP challenges in legal domain
- [NLP for the Legal Domain: Tasks, Datasets, Models, Challenges](https://arxiv.org/abs/2410.21306) -- boundary detection and extraction limitations
- [Leveraging LLMs for legal terms extraction](https://link.springer.com/article/10.1007/s10506-025-09448-8) -- boundary annotation discrepancies between experts and LLMs
- [HiPS: Hierarchical PDF Segmentation of Textbooks](https://arxiv.org/html/2509.00909v1) -- deep hierarchies unsolved even for SOTA LLMs
- [A Language Model based Framework for New Concept Placement in Ontologies](https://arxiv.org/html/2402.17897) -- concept placement challenges and search space complexity
- [OOPS! OntOlogy Pitfall Scanner Catalogue](https://oops.linkeddata.es/catalogue.jsp) -- 40+ catalogued OWL ontology development pitfalls
- [Common Pitfalls in Ontology Development](https://www.researchgate.net/publication/221274977_Common_Pitfalls_in_Ontology_Development) -- foundational pitfall taxonomy
- [Ontology enrichment using a large language model](https://www.sciencedirect.com/science/article/pii/S1532046425000942) -- automated concept placement evaluation challenges
- [Comparison of Reasoners for large Ontologies in the OWL 2 EL Profile](https://www.semantic-web-journal.net/sites/default/files/swj120_2.pdf) -- reasoner performance on large ontologies
- [Knowledge Graphs, LLMs, and Hallucinations: An NLP Perspective](https://www.sciencedirect.com/science/article/pii/S1570826824000301) -- KG-RAG for hallucination mitigation
- [SPARQL Best Practices](https://www.topquadrant.com/doc/8.1/sparql/sparql_best_practices.html) -- SKOS label query performance pitfalls
- [Using OWL and SKOS](https://www.w3.org/2006/07/SWD/SKOS/skos-and-owl/master.html) -- W3C guidance on OWL/SKOS integration patterns
- [TaxoGen: Unsupervised Topic Taxonomy Construction](https://arxiv.org/pdf/1812.09551) -- taxonomy over-splitting and general term boundary problems
- [Incremental Ontology Population and Enrichment through Semantic-based Text Mining](https://www.researchgate.net/publication/292139184_Incremental_Ontology_Population_and_Enrichment_through_Semantic-based_Text_Mining) -- incremental enrichment challenges
- [Comparing Python libraries for working with ontologies](https://incenp.org/notes/2025/comparing-python-ontology-libraries.html) -- current state of Python OWL tooling
- [5 Methods for Calibrating LLM Confidence Scores](https://latitude.so/blog/5-methods-for-calibrating-llm-confidence-scores) -- confidence calibration approaches and limitations

---
*Pitfalls research for: Legal knowledge extraction and ontology enrichment*
*Researched: 2026-03-17*
