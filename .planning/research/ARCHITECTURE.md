# Architecture Patterns

**Domain:** Legal knowledge extraction and ontology enrichment
**Researched:** 2026-03-17
**Confidence:** HIGH (based on direct folio-enrich codebase inspection, FOLIO.owl examination, and current literature)

## Recommended Architecture

The system is a four-stage batch pipeline that extends the existing folio-enrich codebase. Each stage transforms its input into a progressively more structured form, ultimately producing OWL-compatible ontology extensions. The key architectural insight: this is NOT a modification to folio-enrich's runtime pipeline -- it is a **separate batch orchestrator** that reuses folio-enrich's services (`FolioService`, `EmbeddingService`, LLM registry) as imported libraries, then adds three entirely new components on top.

```
                         alea-advocate Pipeline
                         =====================

  +-----------+     +----------------+     +---------------+     +-------------+
  | Stage 1   | --> | Stage 2        | --> | Stage 3       | --> | Stage 4     |
  | FOLIO Tag |     | Task Tree      |     | OWL Mapping   |     | OWL Import  |
  | MD Sources|     | Structuring    |     | Generation    |     |             |
  +-----------+     +----------------+     +---------------+     +-------------+
       |                   |                      |                     |
       v                   v                      v                     v
  Enriched MD        Task Tree JSON        OWL + Companion        Standalone
  w/ FOLIO tags      (hierarchical)        SKOS/JSON files        advocacy-
  + knowledge        + knowledge units                            knowledge.owl
  unit boundaries    linked to tags                               (validated)


  Shared Services (imported from folio-enrich or standalone):
  +--------------+  +------------------+  +-----------+  +------------+
  | FolioService |  | EmbeddingService |  | LLM       |  | folio-     |
  | (ontology    |  | (FAISS index,    |  | Registry  |  | python     |
  |  access,     |  |  similarity)     |  | (per-task  |  | (OWL I/O)  |
  |  18K labels) |  |                  |  |  routing)  |  |            |
  +--------------+  +------------------+  +-----------+  +------------+
```

### Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| **MD Ingestion** | Read MD source files, parse markdown structure (headings, sections, paragraphs, lists), detect document structure hierarchy | Stage 1 |
| **Stage 1: FOLIO Tagger** | Detect knowledge unit boundaries (advice, principle, citation, rule, pitfall); distill ideas; tag each unit with FOLIO concepts using folio-enrich's three-path extraction + 5-stage confidence scoring | FolioService, EmbeddingService, LLM Registry |
| **Stage 2: Task Tree Builder** | Discover top-level advocacy tasks from tagged knowledge, build hierarchical task/sub-task trees, attach knowledge units as leaves, cross-reference units relevant to multiple tasks | Stage 1 output, LLM |
| **Stage 3: OWL Mapper** | Map task trees and knowledge units to OWL axioms: core class hierarchy in OWL, detailed advice in companion JSON-LD file | Stage 2 output, FolioService, rdflib |
| **Stage 4: OWL Importer** | Validate generated OWL, produce standalone advocacy ontology module, validate consistency | Stage 3 output, rdflib, lxml |
| **Corpus Registry** | Track which source files have been processed, content hashes for change detection, support incremental additions without full reprocessing | All stages |
| **Quality Gate** | Confidence-gated output filtering, random-sample spot-check support, low-confidence unit logging for manual review | Stage 1/2 output |

### Data Flow

```
1. MD Source Files (on disk)
      |
      v
2. [MD Ingestion] Parse markdown structure, extract heading hierarchy,
   sections, paragraphs, list items
      |
      v
3. [Knowledge Unit Boundary Detection] LLM identifies where one piece of
   advice/principle/citation/rule/pitfall begins and ends. Two-pass:
   structural heuristics first (headings, bullets), then LLM refinement
   for ambiguous multi-advice paragraphs.
   Output: list of KnowledgeUnit objects with text, span, source_file
      |
      v
4. [Knowledge Type Classifier] LLM classifies each unit as:
   advice | principle | citation | procedural_rule | pitfall
   Also runs Surprise Scorer (counterintuitive/non-obvious content)
   and Distiller (compress to minimal words, ideas not expressions).
   Output: KnowledgeUnit with type, surprise_score, distilled_text
      |
      v
5. [FOLIO Concept Tagging] Reuse folio-enrich's three-path extraction:
   - EntityRuler: pattern-match FOLIO labels against knowledge unit text
   - LLM Concept: LLM identifies FOLIO concepts per knowledge unit
   - Semantic Ruler: embedding similarity for fuzzy matches
   Then: Reconciliation -> Resolution -> Confidence Scoring
   Output: each KnowledgeUnit now has FOLIO concept tags with IRIs +
   confidence scores + full lineage trail
      |
      v
6. [Task Discovery] LLM reads all tagged knowledge units and discovers
   top-level advocacy tasks (e.g., "Expert Depositions", "Opening
   Statements", "Motion Practice"). These become root nodes.
      |
      v
7. [Hierarchical Structuring] LLM organizes knowledge units under tasks:
   Task -> Sub-task -> Technique/Principle/Warning
   Each leaf node is a knowledge unit from Stage 1.
   Cross-references created for units relevant to multiple tasks.
   Output: TaskTree JSON with full hierarchy and linked knowledge units
      |
      v
8. [Deduplication] Content-hash exact dedup + embedding cosine similarity
   (threshold ~0.85) for near-dedup across documents.
      |
      v
9. [OWL Axiom Generation] Map the tree to OWL:
   - Each Task: owl:Class subclass of folio:AdvocacyTask
   - Each Sub-task: owl:Class subclass of parent Task
   - Core hierarchy in OWL file
   - Detailed advice in companion JSON-LD file
   - Cross-references to existing FOLIO concepts via rdfs:seeAlso
   Output: advocacy-knowledge.owl + advocacy-companion.jsonld
      |
      v
10. [OWL Validation + Import]
   - XML well-formedness (lxml)
   - RDF parse validity (rdflib)
   - IRI collision check against existing FOLIO
   - Referential integrity (all subClassOf targets exist)
   - Namespace consistency
   Output: validated standalone advocacy ontology module
```

## Stage 1: FOLIO Tagger -- Detailed Architecture

This is the most complex stage because it reuses folio-enrich's proven extraction pipeline but repurposes it for advocacy textbook prose rather than legal documents.

### What to Reuse from folio-enrich

These components were verified by direct codebase inspection:

| folio-enrich Component | Location | How to Reuse | Adaptation Needed |
|------------------------|----------|-------------|-------------------|
| `FolioService` singleton | `services/folio/folio_service.py` | Import directly -- provides `get_all_labels()` (label->concept map), `search_by_label()`, `get_concept()`, `get_all_property_labels()` | None -- already a lazy-init singleton |
| `EmbeddingService` | `services/embedding/service.py` | Import directly -- provides FAISS-backed similarity search over all FOLIO concept labels | None -- same concept embeddings |
| `EntityRulerStage` logic | `pipeline/stages/entity_ruler_stage.py` | Import the service layer, not the pipeline stage | Run against knowledge units, not document chunks |
| `LLMConceptIdentifier` | `services/concept/llm_concept_identifier.py` | Import directly | Modify prompts for advocacy text context |
| `ReconciliationStage` logic | `services/reconciliation/` | Import the service | Same dual-path merge logic, different input shape |
| `ResolutionStage` logic | `pipeline/stages/resolution_stage.py` | Import directly | No changes -- resolves concept text to FOLIO IRIs |
| `AhoCorasickMatcher` | `services/matching/aho_corasick.py` | Import directly | No changes -- fast multi-pattern string matching |
| Confidence scoring (5-stage) | Spread across reconciliation, resolution, rerank, branch_judge stages | Reuse scoring logic | May skip some stages (no document-level metadata context) |
| LLM registry + per-task routing | `services/llm/`, `pipeline/orchestrator.py` TaskLLMs | Import directly | Add new task names for advocacy-specific tasks |
| `PipelineStage` ABC | `pipeline/stages/base.py` | Extend for advocate stages | Same interface: `name` property + `execute(job)` method |

### What is NEW in Stage 1

| New Component | Purpose | Implementation Notes |
|--------------|---------|---------------------|
| **MD Structure Parser** | Parse markdown into sections/subsections, preserving heading hierarchy as `section_path: list[str]` | Use `markdown-it-py` (already a folio-enrich dep) for AST, walk heading tree |
| **Knowledge Unit Boundary Detector** | Two-pass detection: structural heuristics (headings, bullets, paragraph breaks), then LLM refinement for ambiguous cases | Structural pass handles 70-80% of cases cheaply; LLM resolves multi-advice paragraphs |
| **Knowledge Type Classifier** | Classify each unit: advice, principle, citation, procedural_rule, pitfall | LLM classifier with structured JSON output; single call per batch of units |
| **Surprise Scorer** | Flag units that are counterintuitive or unlikely in LLM training data | LLM evaluates: "Would a legal AI likely already know this? Rate 0-1 for surprise." |
| **Distillation Engine** | Extract core idea in minimal words (ideas, not expressions) | LLM with specific prompt: "Distill to minimum words needed to fully convey the concept. Strip filler, hedging, redundancy." |

### Knowledge Unit Model

```python
class KnowledgeType(str, Enum):
    ADVICE = "advice"           # techniques, strategies, tips
    PRINCIPLE = "principle"     # foundational rules
    CITATION = "citation"       # referenced cases
    RULE = "procedural_rule"    # required steps, deadlines
    PITFALL = "pitfall"         # mistakes to avoid

class KnowledgeUnit(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str                          # Distilled idea text
    original_text: str                 # Source text before distillation
    unit_type: KnowledgeType
    source_file: str                   # Path to source MD
    source_section: list[str]          # ["Chapter 8", "Expert Witnesses", "Methodology"]
    span: Span                         # Character offsets in source
    folio_tags: list[ConceptTag]       # FOLIO concept mappings with confidence
    surprise_score: float              # 0.0-1.0, higher = more surprising
    confidence: float                  # Overall extraction confidence
    content_hash: str                  # SHA-256 for dedup and caching
    lineage: list[StageEvent]          # Provenance trail
```

### Bridge Stage Pattern (Core Integration)

Rather than modifying folio-enrich's codebase, wrap its services as a bridge:

```python
class FolioEnrichBridgeStage:
    """Delegates each knowledge unit to folio-enrich services for FOLIO concept tagging.

    Does NOT run the full folio-enrich pipeline (which is designed for document
    enrichment with metadata extraction, document type detection, etc.).
    Instead, imports specific services:
    - EntityRuler pattern matching
    - LLM concept identification
    - Reconciliation (dual-path merge)
    - Resolution (IRI lookup)
    - Confidence scoring
    """

    def __init__(self):
        # Import folio-enrich services
        self.folio_svc = FolioService.get_instance()
        self.embedding_svc = EmbeddingService.get_instance()
        self.labels = self.folio_svc.get_all_labels()

    async def tag_unit(self, unit: KnowledgeUnit) -> KnowledgeUnit:
        # 1. EntityRuler pattern matching against unit text
        # 2. LLM concept identification
        # 3. Reconciliation + Resolution + Confidence scoring
        # 4. Map results to unit.folio_tags
        ...
```

## Stage 2: Task Tree Builder -- Detailed Architecture

### Discovery Strategy

The task tree is NOT predefined. The LLM reads all knowledge units (with their types and FOLIO tags) and inductively discovers what advocacy tasks the corpus covers. This is a two-pass process:

**Pass 1: Task Discovery**
- Input: All knowledge units with FOLIO tags, grouped by source section
- LLM prompt: "Given these extracted knowledge units from advocacy textbooks, identify the distinct top-level advocacy tasks they address. Focus on practitioner activities: depositions, motions, opening statements, jury selection, etc."
- Output: List of task names + descriptions + evidence (which units support each task)

**Pass 2: Hierarchical Organization**
- Input: Task list + all knowledge units
- LLM prompt per task: "Organize these knowledge units under [task name] into a logical sub-task hierarchy. Group related techniques, principles, and warnings together."
- Output: Tree structure per task

### Task Tree Model

```python
class TaskNode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str                            # "Expert Depositions"
    description: str                     # Brief description of this task
    parent_id: str | None = None         # None for root tasks
    children: list[TaskNode] = []
    knowledge_unit_ids: list[str] = []   # Primary assignment
    cross_ref_unit_ids: list[str] = []   # Secondary (cross-reference)
    folio_concept_iris: list[str] = []   # Relevant FOLIO concepts
    depth: int = 0                       # 0 = root, 1 = sub-task, etc.
    owl_iri: str | None = None           # Generated after OWL mapping
```

### Cross-Reference and Deduplication

Knowledge units may be relevant to multiple tasks. The tree builder must:
1. Assign each unit a primary task (strongest fit via embedding similarity)
2. Create `cross_ref_unit_ids` for secondary tasks (above similarity threshold but not primary)
3. Detect duplicate/near-duplicate units across source files using content hash + embedding cosine similarity (threshold ~0.85)
4. Merge near-duplicates, keeping the version with higher confidence and noting the merge in lineage

## Stage 3: OWL Mapper -- Detailed Architecture

### The "Core in OWL, Details in Companion" Pattern

This is the critical architectural decision. FOLIO.owl is a 293,603-line RDF/XML file with ~18,000 concepts. It must remain clean and interoperable. Detailed advocacy advice text does not belong as deeply nested OWL axioms.

**In the OWL file (core mappings):**
- New `owl:Class` declarations for advocacy tasks and sub-tasks
- `rdfs:subClassOf` hierarchy mirroring the task tree
- `rdfs:seeAlso` links to existing FOLIO concepts
- Minimal annotations: `rdfs:label`, `skos:prefLabel`, `skos:definition` (brief, 1-2 sentences)
- Custom `owl:AnnotationProperty` for advocacy-specific metadata (e.g., `advocate:hasKnowledgeType`)

**In the companion file (detailed advice):**
- Full knowledge unit text with distilled ideas
- Extended `skos:note`, `skos:example`, `skos:editorialNote` annotations
- Surprise scores, confidence levels, source citations
- Cross-references between knowledge units
- Format: JSON-LD (machine-readable, links back to OWL IRIs via `@id`)

### IRI Generation Strategy

New concepts need IRIs that:
1. Live in the FOLIO namespace (`https://folio.openlegalstandard.org/`)
2. Do not collide with existing FOLIO concepts (verified by checking `FolioService.get_concept()`)
3. Follow FOLIO's IRI pattern (short alphanumeric identifiers, as seen in the OWL file)
4. Are deterministic (same input produces same IRI) for idempotent re-runs

```python
def generate_advocacy_iri(task_path: list[str]) -> str:
    """Generate a FOLIO-compatible IRI from a task hierarchy path.

    Uses ADV prefix to distinguish from native FOLIO concepts.
    Deterministic: same path always produces same IRI.
    """
    content_hash = hashlib.blake2b(
        "/".join(task_path).encode(), digest_size=16
    ).digest()
    encoded = base62_encode(content_hash)
    return f"https://folio.openlegalstandard.org/ADV{encoded}"
```

The `ADV` prefix distinguishes advocacy-generated IRIs from FOLIO's native ones (which use single-letter prefixes like `R`, `A`, etc. as observed in the actual FOLIO.owl file).

### OWL Generation with rdflib

Use `rdflib` (already a folio-enrich dependency) rather than owlready2 because:

1. **Already in the dependency tree** -- folio-enrich imports `rdflib` in `services/export/rdf_exporter.py` for RDF/Turtle export
2. **FOLIO.owl is RDF/XML** -- confirmed by examining the 293K-line cached file at `~/.folio/cache/github/*.owl`; rdflib handles RDF/XML natively
3. **We need simple class declarations, not reasoning** -- owlready2's value is OWL reasoning (HermiT/Pellet integration), which this pipeline does not need
4. **Companion file is JSON-LD** -- rdflib supports JSON-LD serialization directly
5. **No additional dependency** -- owlready2 would add a new dep with its SQLite quadstore

**Confidence: HIGH** (verified: rdflib is imported in folio-enrich's codebase, FOLIO.owl format confirmed from disk)

## Stage 4: OWL Importer -- Detailed Architecture

### Import Strategy: Standalone Module

| Strategy | Pros | Cons | Recommendation |
|----------|------|------|----------------|
| **Physical merge** into FOLIO.owl | Single file, simple deployment | Messy diffs, hard to update FOLIO independently, 293K lines already | NO |
| **owl:imports** declaration | Clean separation, FOLIO updates independently | Requires both files accessible at URLs | YES for production |
| **Standalone module** with `rdfs:seeAlso` links | Maximum independence, can evolve separately | Consumers must load both files | YES as initial approach |

**Recommended: Standalone module first, owl:imports later.**

Build `advocacy-knowledge.owl` as a self-contained ontology that references FOLIO concepts via `rdfs:seeAlso` and `rdfs:subClassOf`. No physical merge into the 293K-line FOLIO.owl file. Later, a single `owl:imports` statement can be added to FOLIO.owl pointing to the advocacy module.

### Validation Pipeline

```
1. XML well-formedness          (lxml.etree.fromstring -- already a folio-enrich dep)
2. RDF parse validity           (rdflib.Graph.parse)
3. IRI collision check          (verify no new IRIs in FolioService.get_concept())
4. Referential integrity        (all rdfs:subClassOf targets exist in FOLIO or module)
5. Namespace consistency        (all new entities use folio: namespace)
6. Companion link integrity     (all IRIs in companion JSON-LD exist in OWL)
7. Re-serialize roundtrip test  (parse -> serialize -> parse -> compare)
```

## Patterns to Follow

### Pattern 1: Batch Orchestrator with Checkpointing

**What:** Each stage writes its output to disk as JSON before the next stage begins. If the pipeline fails mid-run, it can resume from the last checkpoint.

**When:** Always -- LLM calls can fail, and the pipeline processes growing corpora. Re-running from scratch is wasteful.

**Why:** Each stage's output is independently valuable for debugging. Checkpoints enable incremental development (work on Stage 2 while Stage 1 output is stable).

```python
class PipelineCheckpoint:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def save(self, stage: str, data: Any) -> Path:
        path = self.output_dir / f"{stage}.json"
        path.write_text(json.dumps(data, indent=2, default=str))
        return path

    def load(self, stage: str) -> dict | None:
        path = self.output_dir / f"{stage}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def has_checkpoint(self, stage: str) -> bool:
        return (self.output_dir / f"{stage}.json").exists()
```

### Pattern 2: Incremental Corpus Processing

**What:** Track which source files have been processed via content hashes. On re-run, only process new or modified files. Stage 1 and 2 are incremental; Stage 3 and 4 always regenerate from current state (OWL output is derived, not incrementally modified).

**When:** After initial pipeline works end-to-end. Essential for growing corpus.

**Why:** The corpus "starts small but will grow as more source material is added over time" (PROJECT.md). Reprocessing everything on each addition wastes LLM calls.

```python
class CorpusRegistry:
    def __init__(self, registry_path: Path):
        self.registry_path = registry_path
        self._manifest: dict[str, str] = {}  # filepath -> content_hash

    def needs_processing(self, filepath: Path) -> bool:
        current_hash = hashlib.sha256(filepath.read_bytes()).hexdigest()
        return current_hash != self._manifest.get(str(filepath))
```

### Pattern 3: Confidence-Gated Output

**What:** Only knowledge units above a configurable confidence threshold make it into the final OWL output. Below-threshold units are logged for manual review.

**When:** At the Stage 1 -> Stage 2 boundary and Stage 3 output.

**Why:** "Automated quality-first approach -- minimize manual review with spot-checking" (PROJECT.md).

```
confidence >= 0.80  -> Include in OWL output (auto-confirmed)
0.60 <= conf < 0.80 -> Include but flag for spot-check
confidence < 0.60   -> Exclude, log to review/ directory
```

### Pattern 4: Deterministic IRI Generation

**What:** Generate IRIs from content hashes so the same input always produces the same IRI.

**When:** Stage 3, OWL Mapper.

**Why:** Idempotent re-runs. If the pipeline is re-run on the same corpus, it produces the same IRIs, so the output can be safely overwritten without creating orphan concepts.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Modifying folio-enrich's Pipeline In Place

**What:** Adding advocacy-specific stages directly to folio-enrich's `PipelineOrchestrator` and `PipelineConfig`.

**Why bad:** folio-enrich is a general-purpose document enrichment tool with 586 tests across 45 files. Adding advocacy-textbook-specific stages pollutes its architecture, creates coupling, and risks breaking existing tests. The two projects have different lifecycles.

**Instead:** Import folio-enrich's services as a library. Build a separate orchestrator in alea-advocate that calls into `FolioService`, `EmbeddingService`, etc. directly.

### Anti-Pattern 2: Putting Full Advice Text in OWL Axioms

**What:** Encoding entire distilled knowledge units as OWL class definitions or annotation values directly in the OWL file.

**Why bad:** FOLIO.owl is already 293,603 lines. OWL ontologies are designed for class hierarchies and formal semantics, not free-text knowledge management. Bloating it with thousands of advice paragraphs makes it unwieldy for OWL reasoners and violates the separation between ontological structure and knowledge content.

**Instead:** Core mappings (class hierarchy, brief definitions, cross-references) in OWL. Detailed advice in companion JSON-LD that links back to OWL IRIs.

### Anti-Pattern 3: Flat Knowledge Extraction (No Hierarchy)

**What:** Extracting knowledge units and tagging them with FOLIO concepts but skipping hierarchical task structuring.

**Why bad:** The core value proposition is discoverability by task. "Any practitioner, AI system, or developer querying 'how do I take an expert deposition' gets a structured, hierarchical set of techniques, principles, and warnings" (PROJECT.md). A flat list is just a search index.

**Instead:** Stage 2 (task tree building) is essential. The hierarchy IS the product.

### Anti-Pattern 4: Tightly Coupling to FOLIO.owl's Internal Structure

**What:** Hard-coding parent class IRIs, branch structures, or annotation property patterns from the current FOLIO.owl snapshot.

**Why bad:** FOLIO is an evolving ontology (updated January 2026, version-managed via ETag in owl_cache.py). Its internal structure can change. The existing folio-enrich codebase handles this via the `FolioService` abstraction layer and dynamic branch map building.

**Instead:** Always access FOLIO through `FolioService` or `folio-python` APIs. Use `search_by_label()` and `search_by_prefix()` to find concepts dynamically. Never hard-code IRIs.

### Anti-Pattern 5: Running Full folio-enrich Pipeline Per Unit

**What:** Instantiating `PipelineOrchestrator` and running all 16 stages for each individual knowledge unit.

**Why bad:** Many folio-enrich stages are irrelevant for short advice units: document type detection, 28-field metadata extraction, citation parsing, property extraction. Running all 16 stages per unit is wasteful and produces noisy results.

**Instead:** Cherry-pick the relevant services: EntityRuler pattern matching, LLM concept identification, reconciliation, resolution, and confidence scoring. Skip metadata, document type, individual/property extraction.

## Suggested Build Order

The stages have strict data dependencies:

```
Stage 1 depends on: folio-enrich services (must be importable)
Stage 2 depends on: Stage 1 output (knowledge units with FOLIO tags)
Stage 3 depends on: Stage 2 output (task trees) + rdflib
Stage 4 depends on: Stage 3 output (generated OWL)
```

**Build order implications for roadmap:**

1. **Phase 1: Foundation + Stage 1** -- Project structure, folio-enrich as importable dependency, MD ingestion, knowledge unit boundary detection, type classification, FOLIO tagging via bridge pattern. This is the largest phase because it involves the most complex extraction logic and the folio-enrich integration.

2. **Phase 2: Stage 2** -- Task discovery and hierarchical structuring. Can begin once Stage 1 produces even partial output on a few source files.

3. **Phase 3: Stage 3 + 4** -- OWL mapping, companion file generation, validation, and import. Relatively mechanical once the mapping rules are defined and Stage 2 produces task trees.

4. **Phase 4 (cross-cutting): Quality + Incremental** -- Confidence-gated output, spot-check support, corpus registry for incremental processing, deduplication. Can be interleaved with earlier phases but should be formalized as its own phase.

## Project Structure

```
alea-advocate/
  src/
    advocate/
      __init__.py
      config.py                      # Settings (source dirs, thresholds, LLM config)
      cli.py                         # CLI entry point for batch pipeline runs
      models/
        knowledge_unit.py            # KnowledgeUnit, KnowledgeType enum
        task_tree.py                 # TaskNode, TaskTree
        owl_mapping.py               # OWLMapping, CompanionEntry
        corpus.py                    # CorpusDocument, CorpusManifest
      pipeline/
        orchestrator.py              # Batch pipeline runner with checkpointing
        stages/
          base.py                    # AdvocateStage base (same interface as folio-enrich)
          md_ingestion.py            # Markdown parsing + structure extraction
          boundary_detection.py      # Knowledge unit boundary detection (structural + LLM)
          knowledge_classifier.py    # Knowledge type classification
          folio_tagger.py            # FOLIO concept tagging (bridge to folio-enrich services)
          surprise_scorer.py         # Surprise/novelty scoring
          distiller.py               # Idea distillation (compress text)
          task_discoverer.py         # Top-level task discovery (LLM)
          tree_builder.py            # Hierarchical organization (LLM)
          deduplicator.py            # Content-hash + embedding dedup
          owl_mapper.py              # Task tree -> OWL axioms (rdflib)
          companion_generator.py     # Companion JSON-LD file
          owl_validator.py           # OWL validation pipeline
      services/
        corpus_registry.py           # Track processed files via content hash
        folio_bridge.py              # Adapter for folio-enrich services import
        iri_generator.py             # Deterministic IRI generation
        prompts/                     # LLM prompt templates
          segmentation.py
          classification.py
          task_discovery.py
          distillation.py
      quality/
        confidence_gate.py           # Threshold-based output filtering
        spot_checker.py              # Random sampling for manual review
  sources/                           # MD source files (gitignored)
  output/                            # Pipeline output directory
    checkpoints/                     # Stage checkpoint files (JSON)
    advocacy-knowledge.owl           # Generated OWL module
    advocacy-companion.jsonld        # Detailed advice companion
    review/                          # Low-confidence units for manual review
  tests/
  pyproject.toml
```

## Scalability Considerations

| Concern | Small corpus (10 files) | Medium corpus (100 files) | Large corpus (1000+ files) |
|---------|------------------------|--------------------------|---------------------------|
| **LLM costs** | Trivial (~$1-5) | Moderate (~$20-50) | Significant (~$200+); incremental processing and caching essential |
| **Processing time** | Minutes | ~1 hour | Hours; checkpointing, batch scheduling essential |
| **OWL file size** | Negligible (~100 new classes) | Manageable (~1K new classes) | Standalone module essential; physical merge impractical |
| **Task tree depth** | Shallow (2-3 levels) | Moderate (3-4 levels) | May need subtree splitting to keep trees navigable |
| **Deduplication** | Content-hash exact dedup sufficient | Embedding-based near-dedup needed | FAISS index for embedding search (reuse folio-enrich infrastructure) |
| **Memory** | Everything fits in RAM | Advice unit embeddings may need batching | FAISS on-disk index, SQLite for manifest instead of JSON |

## Sources

- **folio-enrich codebase** (directly examined): Pipeline orchestrator (`pipeline/orchestrator.py`), PipelineStage ABC (`pipeline/stages/base.py`), RDF exporter (`services/export/rdf_exporter.py`), FolioService (`services/folio/folio_service.py`), OWL cache/updater (`services/folio/owl_cache.py`, `owl_updater.py`), annotation models (`models/annotation.py`), job models (`models/job.py`), document models (`models/document.py`), LLM concept stage (`pipeline/stages/llm_concept_stage.py`) **[HIGH confidence]**
- **FOLIO.owl file**: Examined 293,603-line RDF/XML file from disk cache at `~/.folio/cache/github/*.owl`. Confirmed OWL Class structure with `rdfs:subClassOf`, `rdfs:label`, `skos:prefLabel`, `skos:definition`, `skos:altLabel`, `skos:example` annotations. Object Properties use `rdfs:domain`, `rdfs:range`, `owl:inverseOf`. **[HIGH confidence]**
- [FOLIO GitHub Repository](https://github.com/alea-institute/FOLIO) -- Ontology structure, format, 18K+ concepts **[HIGH confidence]**
- [folio-python library](https://github.com/alea-institute/folio-python) -- Python API for FOLIO access, v0.2.0 with OWL Object Properties support **[HIGH confidence]**
- [rdflib GitHub](https://github.com/RDFLib/rdflib) -- RDF manipulation library, already a folio-enrich dependency **[HIGH confidence]**
- [W3C: Using OWL and SKOS](https://www.w3.org/2006/07/SWD/SKOS/skos-and-owl/master.html) -- OWL+SKOS integration patterns for companion files **[HIGH confidence]**
- [Comparing Python ontology libraries (2025)](https://incenp.org/notes/2025/comparing-python-ontology-libraries.html) -- rdflib vs owlready2 vs py-horned-owl comparison; rdflib recommended for RDF/XML manipulation without reasoning **[MEDIUM confidence]**
- [ODKE+: Ontology-Guided Open-Domain Knowledge Extraction](https://arxiv.org/html/2509.04696v1) -- Production LLM-based ontology enrichment pipeline patterns **[MEDIUM confidence]**
- [Ontology enrichment using LLMs for concept placement (2025)](https://www.sciencedirect.com/science/article/pii/S1532046425000942) -- LLM-driven concept placement strategies **[MEDIUM confidence]**
- [From LLMs to Knowledge Graphs: Production-Ready Systems (2025)](https://medium.com/@claudiubranzan/from-llms-to-knowledge-graphs-building-production-ready-graph-systems-in-2025-2b4aff1ec99a) -- 300-320% ROI patterns for KG construction **[LOW confidence, single source]**
