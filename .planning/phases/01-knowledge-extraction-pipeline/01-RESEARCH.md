# Phase 1: Knowledge Extraction Pipeline - Research

**Researched:** 2026-03-17
**Domain:** Legal knowledge extraction pipeline with folio-enrich bridge integration, multi-format ingestion, tiered boundary detection, four-path FOLIO extraction, and interactive review viewer
**Confidence:** HIGH

## Summary

Phase 1 builds a batch CLI pipeline that ingests multi-format legal source files (DOCX, PDF, HTML, MD, TXT, RTF, XML, CSV, XLSX, WPD, EML/MSG), extracts typed knowledge units with FOLIO concept tags and confidence scores, and presents them in an interactive SvelteKit + FastAPI review viewer for human validation before any OWL generation. The heaviest technical lift is the **folio-enrich bridge adapter** -- importing folio-enrich's services (FolioService, EmbeddingService, LLM routing, reconciliation, citation extraction, normalizer) as a library without modifying folio-enrich's codebase. The second major challenge is extending the reconciler from two/three paths (EntityRuler + LLM + optional embedding triage) to four paths (adding document-structure heading context as an independent signal).

The project is greenfield -- no src/, tests/, or pyproject.toml exist yet. Source files are DOCX and PDF (not MD as originally assumed in the roadmap), confirming the critical need for multi-format ingestion from day one. folio-enrich already provides 7 ingestors (PDF via PyMuPDF, DOCX via python-docx, HTML via BeautifulSoup4, Markdown, plain text, RTF via striprtf, Email via extract-msg) with a clean registry pattern. folio-mapper provides Excel/CSV/TSV parsing. New parsers are needed only for XML (lxml, already a dep) and WPD (via Free Law Project's Doctor microservice).

**Primary recommendation:** Build the folio-enrich bridge adapter FIRST as the foundation, then layer ingestion, boundary detection, extraction, FOLIO tagging, and finally the review viewer on top. The bridge adapter's success or failure determines whether Phase 1 architecture works at all.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Project renamed to **folio-insights** -- pyproject.toml, package name, CLI entry point all start as `folio-insights`
- **Supported input formats**: MD, DOCX, PDF, TXT, HTML, RTF, XML, CSV, Excel (.xlsx), WordPerfect (.wpd), Email (EML/MSG)
- **Reuse folio-enrich ingestors** for: PDF, DOCX, HTML, MD, TXT, RTF, EML/MSG
- **Reuse folio-mapper file_parser** for: Excel, CSV, TSV
- **Add new parsers** for: XML (lxml), WordPerfect (via FLP Doctor microservice)
- **Tiered boundary detection**: Structural heuristics (Tier 1, ~70-80%) -> Embedding segmentation (Tier 2, ~15-20%) -> LLM fallback (Tier 3, ~5%)
- **Four-path FOLIO extraction**: EntityRuler + LLM + Semantic + Document Structure (heading context as independent signal)
- **LLM provider agnostic** with tiered model selection (light/medium/large per task), preference toward local
- **OWL modeling**: Tasks=classes (existing FOLIO IRIs), knowledge units=individuals (new IRIs), citations=individuals
- **Standards reuse**: SKOS, PROV-O, Dublin Core, CITO, Web Annotation
- **Review viewer**: SvelteKit + FastAPI + SQLite, three-pane layout (FOLIO tree left, detail upper-right, source lower-right)
- **Review gates output** -- nothing enters OWL until reviewed
- **Confidence bands**: >=0.8 high, 0.5-0.8 medium, <0.5 low
- **4-plan breakdown**: 01-01 scaffolding+ingestion, 01-02 extraction pipeline, 01-03 output+quality+CLI, 01-04 review viewer
- One idea per knowledge unit; a paragraph with 3 tips becomes 3 separate units
- Extract everything regardless of obviousness; use novelty scoring to distinguish surprising from expected
- JSON stores source references only (file path, chapter, section, character span) -- no original text copied (copyright safety)
- All heading levels contribute to document structure signal, weighted by proximity (immediate subheading = strongest, parent = medium, chapter = weakest)
- Heading-to-FOLIO mapping quality >= 0.7 = strong signal; < 0.7 = weaker signal, fall back to parent headings
- Reuse folio-enrich's existing nupunkt, spaCy, eyecite+citeurl, Aho-Corasick, text chunking
- Reuse mjbommar/273v ecosystem: Kelvin patterns, LMSS taxonomy, LogiLLM
- Shared folio-insights instance with separate named corpora
- Each FOLIO tag shows its extraction path in the review viewer (EntityRuler, LLM, Semantic, or Heading Context)

### Claude's Discretion
- Technical architecture decisions (pipeline internals, stage implementation)
- Performance optimization
- Specific LLM prompts for extraction, classification, distillation
- Loading skeleton and error state design in the viewer
- Which specific sentence-transformers model to use for Tier 2 boundary detection

### Deferred Ideas (OUT OF SCOPE)
- Multi-reviewer support (multiple users reviewing the same corpus) -- future enhancement to SQLite schema
- Phase 2 adds a second tree tab (advocacy task hierarchy) alongside the FOLIO concept tree in the viewer
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INGEST-01 | Ingest directory of MD files (mixed chapter extracts and synthesized notes) | folio-enrich MarkdownIngestor already handles MD; extend to directory walk with format auto-detection |
| INGEST-02 | Preserve document structure (headings, paragraphs, lists) during parsing | folio-enrich's `ingest_with_elements()` returns `TextElement` objects with `section_path`, `element_type`, `level`. Extend for heading hierarchy tracking. |
| INGEST-03 | Handle variable-length source files (single pages to full chapters) | folio-enrich's `chunk_text()` with configurable `max_chars` and `overlap` already handles this |
| EXTRACT-01 | Detect advice unit boundaries using semantic segmentation (sentence to multi-paragraph) | Tiered approach: structural heuristics -> sentence-transformers cosine drop -> LLM fallback. Use nupunkt for legal-domain sentence splitting as foundation. |
| EXTRACT-02 | Distill ideas (not expressions) -- extract concepts/techniques not quotes | LLM distillation stage with specific prompts; source grounding verification prevents hallucination |
| EXTRACT-03 | Each distilled idea as simple as possible but no simpler -- includes all necessary detail | LLM prompt engineering with examples; spot-check validation against gold standard |
| EXTRACT-04 | Extract important advocacy principles even if "obvious" | Extract all; novelty scoring (EXTRACT-05) distinguishes surprising from expected |
| EXTRACT-05 | Flag counterintuitive/non-obvious insights as high-novelty | LLM surprise scorer: "Would a legal AI likely know this? Rate 0-1 for surprise" |
| EXTRACT-06 | Deduplicate identical advice expressed differently across source documents | Content-hash exact dedup + embedding cosine similarity (~0.85 threshold) for near-dedup |
| CLASS-01 | Classify each knowledge unit by type using FOLIO ontology classes | LLM classifier with structured output: advice, principle, citation, procedural_rule, pitfall |
| CLASS-02 | Knowledge types include: actionable advice, legal principles, case citations, procedural rules, common pitfalls | Five-type taxonomy matches folio-enrich's classification patterns |
| CLASS-03 | Each classification carries a confidence score | Per-classification confidence from LLM + reconciliation pipeline |
| FOLIO-01 | Map each unit to FOLIO concepts using four-path extraction (EntityRuler + LLM + semantic + document structure) | Extend folio-enrich's reconciler from 2-path to 4-path; add document structure as independent signal |
| FOLIO-02 | Apply folio-enrich's 5-stage confidence scoring to all FOLIO concept mappings | Bridge adapter imports entire confidence pipeline: EntityRuler -> Reconciliation -> Resolution -> ContextualRerank -> BranchJudge |
| FOLIO-03 | Tag against full FOLIO ontology (~18,000 concepts) | FolioService singleton provides full ontology access; EmbeddingService provides FAISS-backed similarity over all concepts |
| FOLIO-04 | Each tagged unit carries full lineage: source file, chapter, location, extraction method, confidence | Extend folio-enrich's StageEvent lineage model; record_lineage() utility already exists |
| QUAL-01 | Produce human-reviewable enriched output (JSON with spans/nested spans) | Pydantic models with .model_dump() -> JSON; plus interactive review viewer |
| QUAL-02 | High-confidence auto-approve; low-confidence flagged for review | Confidence bands: >=0.8 auto-approve, 0.5-0.8 careful review, <0.5 deep review |
| QUAL-03 | Output both human-readable and machine-parseable for downstream consumption | JSON output + interactive HTML viewer; JSON is the canonical format |
| PIPE-02 | Pipeline runs as batch process (CLI or script-triggered) | Click/Typer CLI with `folio-insights extract <dir>` command |
</phase_requirements>

## Standard Stack

### Core (from folio-enrich -- already available as dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| folio-python | >=0.2.0 | FOLIO ontology access, IRI generation, concept lookup | Foundation library for all FOLIO operations; already in folio-enrich |
| rdflib | 7.6.0 | RDF graph construction, SPARQL, serialization | Already in folio-enrich; verified current on PyPI |
| spaCy | >=3.7.0 | NLP: sentence segmentation, NER, dependency parsing | Already in folio-enrich; provides linguistic backbone |
| nupunkt | >=0.1.0 | Legal-domain sentence boundary detection | Already in folio-enrich; handles "42 U.S.C. ss 1983" correctly |
| PyMuPDF (pymupdf) | >=1.24.0 | PDF text extraction | Already in folio-enrich; best Python PDF parser |
| python-docx | >=1.0.0 | DOCX text extraction | Already in folio-enrich |
| beautifulsoup4 | >=4.12.0 | HTML parsing | Already in folio-enrich |
| markdown-it-py | >=3.0.0 | Markdown AST parsing | Already in folio-enrich; provides heading hierarchy |
| striprtf | >=0.0.26 | RTF text extraction | Already in folio-enrich |
| extract-msg | >=0.48.0 | Email (EML/MSG) parsing | Already in folio-enrich |
| eyecite | >=2.7 | Legal citation extraction (55M+ citations tested) | Already in folio-enrich; battle-tested |
| citeurl | >=12.0 | Legal citation URL normalization | Already in folio-enrich |
| pyahocorasick | >=2.0.0 | Fast multi-pattern string matching | Already in folio-enrich; used by EntityRuler |
| faiss-cpu | >=1.8 | Vector similarity search (FAISS index) | Already in folio-enrich; FOLIO concept embedding search |
| openpyxl | >=3.1.0 | Excel file parsing | Already in folio-enrich; also used by folio-mapper |
| Pydantic | >=2.7.0 | Data model validation | Foundation for all models; pervasive in folio-enrich |
| pydantic-settings | >=2.7.0 | Configuration management with .env support | Already in folio-enrich |
| FastAPI | >=0.115.0 | API backend for review viewer | Already in folio-enrich |
| httpx | >=0.28.0 | Async HTTP client | Already in folio-enrich |
| lxml | >=5.0 | XML parsing (new XML ingestor + WPD via Doctor) | Already a folio-python dependency |

### New Dependencies (Phase 1 additions)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sentence-transformers | >=3.0.0 | Embedding-based semantic segmentation (Tier 2 boundary detection) | Tier 2 boundary detection; cosine similarity drops between sentence embeddings detect topic shifts |
| instructor | >=1.14.0 | Structured LLM output with Pydantic validation and auto-retry | All LLM extraction, classification, and distillation tasks; turns LLM responses into validated Pydantic models |
| click | >=8.0.0 | CLI framework for batch pipeline | `folio-insights extract <dir>` command; lightweight, proven |
| aiosqlite | >=0.20.0 | Async SQLite for review viewer persistence | Review decisions persist across sessions and pipeline re-runs |
| Svelte 5 | 5.53.x | Frontend framework for review viewer | Compiled SPA served as static files from FastAPI |
| SvelteKit | 2.55.x | SvelteKit with adapter-static for SSG build | Prerendered SPA build served via FastAPI StaticFiles mount |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| instructor | LangChain/LlamaIndex | instructor is 10x lighter, focused on structured extraction; LangChain adds 100+ transitive deps |
| instructor | folio-enrich's raw `llm.structured()` | folio-enrich's method works but lacks auto-retry and Pydantic validation; instructor adds these cheaply |
| sentence-transformers | Pure LLM boundary detection | Sentence-transformers are CPU-only, local, ~5x cheaper; LLM reserved for ambiguous ~5% |
| click | typer | Click is more established, no additional dependency (typer wraps click); either works |
| SvelteKit | React (folio-mapper uses React) | User decision locked SvelteKit; compiled Svelte is smaller and faster for this use case |
| aiosqlite | SQLAlchemy + SQLite | aiosqlite is lightweight async wrapper; SQLAlchemy overhead not needed for simple review schema |

**Installation (new deps only):**
```bash
# Python backend
pip install "sentence-transformers>=3.0.0" "instructor>=1.14.0" "click>=8.0.0" "aiosqlite>=0.20.0"

# Frontend (review viewer)
npm create svelte@latest viewer
cd viewer && npm install
```

## Architecture Patterns

### Recommended Project Structure
```
folio-insights/
  src/
    folio_insights/
      __init__.py
      cli.py                          # Click CLI: `folio-insights extract <dir>`
      config.py                       # Settings (pydantic-settings, .env support)
      models/
        knowledge_unit.py             # KnowledgeUnit, KnowledgeType enum
        corpus.py                     # CorpusDocument, CorpusManifest
        review.py                     # ReviewDecision, ReviewStatus
      pipeline/
        orchestrator.py               # Batch pipeline runner with checkpointing
        stages/
          base.py                     # PipelineStage ABC (same interface as folio-enrich)
          ingestion.py                # Multi-format ingestion (delegates to bridge)
          structure_parser.py         # Document structure extraction (heading hierarchy)
          boundary_detection.py       # Tiered: structural -> embedding -> LLM
          knowledge_classifier.py     # Type classification + novelty scoring
          distiller.py                # Idea distillation (LLM)
          folio_tagger.py             # Four-path FOLIO extraction (bridge to services)
          deduplicator.py             # Content-hash + embedding dedup
      services/
        bridge/
          __init__.py
          folio_bridge.py             # FolioService, EmbeddingService adapter
          ingestion_bridge.py         # folio-enrich ingestor adapter
          llm_bridge.py               # LLM registry adapter with per-task routing
          reconciliation_bridge.py    # Extended 4-path reconciler
          mapper_bridge.py            # folio-mapper FileParser adapter
        boundary/
          structural.py               # Tier 1: heading/bullet/paragraph heuristics
          semantic.py                 # Tier 2: sentence-transformers cosine drop
          llm_refiner.py              # Tier 3: LLM for ambiguous cases
        heading_context.py            # Document structure -> FOLIO signal (4th path)
        corpus_registry.py            # Track processed files via content hash
        prompts/                      # LLM prompt templates
          boundary.py
          classification.py
          distillation.py
          novelty.py
      quality/
        confidence_gate.py            # Threshold-based filtering (>=0.8, 0.5-0.8, <0.5)
        output_formatter.py           # JSON + summary report generation
  viewer/                             # SvelteKit review viewer
    src/
      routes/
        +page.svelte                  # Three-pane layout
        +layout.svelte
      lib/
        components/
          FolioTree.svelte            # FOLIO concept tree (left pane)
          DetailView.svelte           # Knowledge unit detail (upper-right)
          SourceContext.svelte         # Source text context (lower-right)
          ReviewControls.svelte       # Approve/reject/edit controls
          ConfidenceFilter.svelte     # Toggleable confidence filter tabs
        stores/
          review.ts                   # Review state management
          tree.ts                     # FOLIO tree state
        api/
          client.ts                   # FastAPI client (auto-generated from OpenAPI)
    svelte.config.js                  # adapter-static for SSG build
  api/                                # FastAPI review viewer backend
    main.py                           # FastAPI app with StaticFiles mount for viewer
    routes/
      review.py                       # Review CRUD endpoints
      tree.py                         # FOLIO tree data endpoints
      source.py                       # Source text context endpoints
    db/
      models.py                       # SQLite schema for review decisions
      session.py                      # aiosqlite session management
  sources/                            # Source files (gitignored)
  output/                             # Pipeline output directory
    checkpoints/                      # Stage checkpoint files (JSON)
    review/                           # Low-confidence units for manual review
  tests/
    conftest.py                       # Shared fixtures (bridge mocks, sample data)
    test_ingestion.py
    test_boundary_detection.py
    test_classification.py
    test_folio_tagger.py
    test_deduplication.py
    test_pipeline.py
    test_review_api.py
  pyproject.toml
```

### Pattern 1: Bridge Adapter (Critical Integration)

**What:** Import folio-enrich services as a library via Python path manipulation, wrapping them in a clean adapter layer that folio-insights owns.

**When to use:** All interactions with folio-enrich services.

**Why:** folio-enrich is a FastAPI web application, not a library. Its services depend on `app.config.settings` and use `from app.X import Y` paths. The bridge adapter must handle this import context.

**Example:**
```python
# services/bridge/folio_bridge.py
import sys
from pathlib import Path

# Add folio-enrich backend to Python path
FOLIO_ENRICH_ROOT = Path.home() / "Coding Projects" / "folio-enrich" / "backend"

def _ensure_path():
    """Add folio-enrich to sys.path if not already present."""
    path_str = str(FOLIO_ENRICH_ROOT)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

def get_folio_service():
    """Get FolioService singleton from folio-enrich."""
    _ensure_path()
    from app.services.folio.folio_service import FolioService
    return FolioService.get_instance()

def get_embedding_service():
    """Get the module-level FAISS embedding index."""
    _ensure_path()
    from app.services.embedding.service import get_embedding_index
    return get_embedding_index()

def get_normalizer():
    """Get normalizer functions."""
    _ensure_path()
    from app.services.normalization.normalizer import (
        split_sentences, chunk_text, normalize_and_chunk
    )
    return split_sentences, chunk_text, normalize_and_chunk
```

**Risk:** folio-enrich's `app.config.settings` uses pydantic-settings which reads from environment. The bridge must either (a) set the required env vars before importing, or (b) mock/override the settings. This is the **highest-risk integration point** and should be tested first.

### Pattern 2: Extended Four-Path Reconciler

**What:** Extend folio-enrich's `Reconciler` from 2 input paths (EntityRuler + LLM) to 4 paths (EntityRuler + LLM + Semantic + Document Structure).

**When to use:** FOLIO concept tagging stage.

**Why:** The existing Reconciler in `services/reconciliation/reconciler.py` takes `ruler_concepts` and `llm_concepts` as inputs. We need to add `semantic_concepts` (from embedding similarity) and `heading_concepts` (from document structure mapping).

**Example:**
```python
# services/bridge/reconciliation_bridge.py
from dataclasses import dataclass
from typing import list

@dataclass
class FourPathInput:
    ruler_concepts: list       # EntityRuler pattern matches
    llm_concepts: list         # LLM concept identification
    semantic_concepts: list    # Embedding similarity matches
    heading_concepts: list     # Document structure -> FOLIO mapping

class FourPathReconciler:
    """Extended reconciler adding semantic and heading context paths."""

    def __init__(self, base_reconciler, embedding_service=None):
        self._base = base_reconciler
        self._embedding = embedding_service

    def reconcile(self, inputs: FourPathInput) -> list:
        # Step 1: Base 2-path reconciliation (ruler + LLM)
        base_results = self._base.reconcile_with_embedding_triage(
            inputs.ruler_concepts, inputs.llm_concepts
        )

        # Step 2: Integrate semantic path (boost agreements, add new)
        merged = self._integrate_semantic(base_results, inputs.semantic_concepts)

        # Step 3: Integrate heading context (independent signal, tagged as source="heading")
        final = self._integrate_heading(merged, inputs.heading_concepts)

        return final
```

### Pattern 3: Tiered Boundary Detection

**What:** Three-tier boundary detection minimizing LLM usage.

**When to use:** Knowledge unit boundary detection stage.

**Example:**
```python
# services/boundary/structural.py
def detect_structural_boundaries(elements: list[TextElement]) -> list[Boundary]:
    """Tier 1: Free, instant. Handles ~70-80% of boundaries.

    Rules:
    - Heading change = boundary
    - Numbered/bulleted list item = boundary per item
    - Double newline (paragraph break) = candidate boundary
    - Transition words ("However,", "In contrast,") = candidate
    """
    ...

# services/boundary/semantic.py
def detect_semantic_boundaries(
    sentences: list[str],
    model_name: str = "all-MiniLM-L6-v2",
    threshold: float = 0.3,
) -> list[Boundary]:
    """Tier 2: CPU-only, cheap. Handles ~15-20% of remaining.

    Compute cosine similarity between consecutive sentence embeddings.
    Drops below threshold indicate topic shift = boundary.
    """
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name)
    embeddings = model.encode(sentences)
    # Find cosine drops between consecutive sentences
    ...
```

### Pattern 4: Per-Task LLM Routing (from folio-enrich)

**What:** Each pipeline task gets its own configurable LLM provider and model.

**When to use:** All LLM-dependent stages.

**How it works in folio-enrich:** The `TaskLLMs` dataclass in `pipeline/orchestrator.py` holds per-task LLM providers. `_try_get_task_llm()` reads `llm_{task}_provider` and `llm_{task}_model` from settings (env vars), falling back to the global default. For Ollama, it auto-selects tier-appropriate models (simple/medium/complex).

**folio-insights extension:** Add new task names for Phase 1 tasks:
```python
# New task names for folio-insights
INSIGHTS_TASKS = (
    "boundary",        # Tier 3 LLM boundary refinement -> light model
    "classifier",      # Knowledge type classification -> medium model
    "distiller",       # Idea distillation -> large model
    "novelty",         # Surprise scoring -> medium model
    "heading_mapper",  # Heading -> FOLIO concept mapping -> light model
    "concept",         # LLM concept identification -> medium model (reuse folio-enrich)
    "branch_judge",    # Branch disambiguation -> large model (reuse folio-enrich)
)
```

### Pattern 5: SvelteKit + FastAPI Integration

**What:** SvelteKit built as static SPA, served from FastAPI via StaticFiles mount.

**When to use:** Review viewer deployment.

**How:**
```python
# api/main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI(title="folio-insights Review Viewer")

# Mount SvelteKit build output
VIEWER_BUILD = Path(__file__).parent.parent / "viewer" / "build"
if VIEWER_BUILD.exists():
    app.mount("/", StaticFiles(directory=VIEWER_BUILD, html=True), name="viewer")
```

```javascript
// viewer/svelte.config.js
import adapter from '@sveltejs/adapter-static';
export default {
  kit: {
    adapter: adapter({ fallback: 'index.html' }),  // SPA mode
    paths: { base: '' }
  }
};
```

**Development:** Run SvelteKit dev server (port ~5173) and FastAPI (port ~8700+) separately with CORS enabled. Production: build SvelteKit -> mount from FastAPI.

### Anti-Patterns to Avoid

- **Modifying folio-enrich's codebase:** Import services via bridge adapter, never edit folio-enrich files. The two projects have different lifecycles.
- **Running full folio-enrich pipeline per unit:** Cherry-pick relevant services (EntityRuler, LLM concept, reconciliation, resolution, confidence scoring). Skip document type detection, 28-field metadata extraction, property extraction -- irrelevant for knowledge units.
- **Putting full advice text in OWL axioms:** Core mappings in OWL; detailed advice in companion JSON-LD (Phase 3 concern, but data model designed for it now).
- **Hardcoding FOLIO IRIs:** Always access via FolioService. FOLIO evolves; use `search_by_label()` and `get_concept()` dynamically.
- **Single-model LLM:** Use tiered model selection. Heading-to-FOLIO mapping (light/cheap) != idea distillation (large/expensive).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Legal sentence splitting | Regex-based sentence splitter | nupunkt (already in folio-enrich) | Legal citations ("42 U.S.C. ss 1983"), case numbers, abbreviations break standard splitters |
| FOLIO concept matching | Custom string matching | EntityRuler + AhoCorasickMatcher + EmbeddingService (folio-enrich) | 18,000 concepts with preferred labels, alt labels, definitions -- folio-enrich already indexes and searches all of these |
| Citation extraction | Citation regex parser | eyecite + citeurl (already in folio-enrich) | Battle-tested on 55M+ legal citations; handles FullCase, ShortCase, FullLaw, FullJournal, Supra, Id citations |
| Structured LLM output | Manual JSON parsing of LLM responses | instructor library | Auto-retry on validation failure, Pydantic model validation, support for all major providers |
| PDF text extraction | pdfminer/PyPDF2 | PyMuPDF (already in folio-enrich) | PyMuPDF is fastest Python PDF parser; handles layout, tables, images |
| WordPerfect conversion | Custom WPD parser | Free Law Project Doctor (Docker microservice) | WPD format is proprietary; Doctor handles wpd2html + HTML cleanup |
| FAISS vector index | Custom cosine similarity | faiss-cpu (already in folio-enrich) | Approximate nearest neighbor at scale; folio-enrich already has FOLIOEmbeddingIndex |
| LLM provider abstraction | Custom API wrappers | folio-enrich LLM registry (13 providers) | OpenAI, Anthropic, Google, xAI, Ollama, LM Studio, Groq, Mistral, Cohere, Meta Llama, GitHub Models, Llamafile, Custom -- all already implemented |

**Key insight:** The folio-enrich codebase is a goldmine of battle-tested legal NLP services. The entire Phase 1 value proposition rests on reusing them effectively via the bridge adapter rather than rebuilding any of them.

## Common Pitfalls

### Pitfall 1: folio-enrich Import Context Failure
**What goes wrong:** folio-enrich's services use `from app.X import Y` import paths and depend on `app.config.settings` being initialized with pydantic-settings. Importing them from outside folio-enrich's application context fails with ImportError or missing settings.
**Why it happens:** folio-enrich is a FastAPI web app, not a library. Its import system assumes it's running within its own `backend/` directory.
**How to avoid:**
  1. Add folio-enrich's `backend/` to `sys.path` before any imports
  2. Set required environment variables (or create a minimal `.env`) before importing `app.config`
  3. Initialize FolioService singleton manually (it's lazy-init, so calling `get_instance()` + any method triggers FOLIO loading)
  4. Write an integration test that imports all needed services as the FIRST task in Plan 01-01
**Warning signs:** `ModuleNotFoundError: No module named 'app'`, settings validation errors, FOLIO ontology not loading

### Pitfall 2: Boundary Detection Granularity Mismatch
**What goes wrong:** Knowledge units are either too fine (fragmenting multi-step techniques) or too coarse (lumping distinct advice together). Legal texts interleave warnings, techniques, and citations within single paragraphs.
**Why it happens:** No explicit boundary markers in flowing prose; LLMs produce inconsistent results.
**How to avoid:**
  1. Define a concrete "knowledge unit" specification with examples before writing extraction code
  2. Tier 1 structural heuristics handle the clear cases (headings, bullets, numbered lists)
  3. Tier 2 embedding-based detection catches topic shifts in flowing prose
  4. Tier 3 LLM refinement only for truly ambiguous multi-advice paragraphs
  5. Build a validation set of ~50 manually annotated boundaries from source material
**Warning signs:** Units vary wildly in length (5 words to 3 paragraphs); same source produces different unit counts on re-runs

### Pitfall 3: FOLIO Concept Mapping Recall Collapse
**What goes wrong:** 80%+ of knowledge maps to the same 50 generic FOLIO concepts while thousands of specific concepts go unused.
**Why it happens:** Advocacy textbooks use practitioner language ("pin down the expert") not formal ontology labels ("Examination of Expert Witness").
**How to avoid:**
  1. Use ALL FOLIO label types: preferred labels, alternative labels (`skos:altLabel`), and definitions
  2. The four-path extraction provides multiple chances to match: pattern matching, LLM inference, embedding similarity, and heading context
  3. Monitor concept distribution -- flag when top 20 concepts account for >70% of all mappings
  4. Pre-filter by FOLIO branch relevance per document section
**Warning signs:** Extreme power-law concept distribution; spot-checks reveal obviously relevant FOLIO concepts never matched

### Pitfall 4: LLM Hallucination in Extraction
**What goes wrong:** LLM invents legal principles, fabricates citations, or attributes advice not in the source text. Especially dangerous with "ideas not expressions" mandate.
**Why it happens:** LLMs blend training data with source text; distillation encourages rephrasing which enables semantic drift.
**How to avoid:**
  1. Source grounding verification: every extracted unit must identify specific source paragraph(s)
  2. Citations extracted near-verbatim (not distilled) using eyecite, not LLM
  3. Temperature = 0 for extraction tasks
  4. Negative instructions: "Do not include any principle, citation, or technique not discussed in the provided text"
  5. Flag extractions with no clear source span anchor
**Warning signs:** Citations not found in source text; extracted advice more detailed than source passage; confidence scores all cluster near 1.0

### Pitfall 5: Four-Path Reconciliation Complexity
**What goes wrong:** Adding document structure as a fourth path to the reconciler creates combinatorial explosion of agreement/conflict cases. The existing reconciler handles ruler+LLM (2 paths, 3 cases: both_agree, ruler_only, llm_only). Four paths creates 15 possible combinations.
**Why it happens:** The reconciler was designed for 2-path merging with simple rules.
**How to avoid:**
  1. Keep document structure as an INDEPENDENT signal, not merged into the reconciler core
  2. Run the base 2-path reconciliation first (ruler + LLM) -- this is proven
  3. Then layer semantic and heading signals as boosters/new-additions to the reconciled result
  4. Heading context never overrides a reconciled result -- it only boosts confidence or adds new concept suggestions
  5. Each concept's source field records which paths contributed (visible in review viewer)
**Warning signs:** Reconciliation stage runtime explodes; conflicting concepts from different paths create noise

### Pitfall 6: SvelteKit/FastAPI State Sync
**What goes wrong:** Review decisions made in the viewer don't persist correctly, or pipeline re-runs overwrite review state.
**Why it happens:** Two separate state systems (pipeline JSON output + SQLite review DB) must stay synchronized.
**How to avoid:**
  1. SQLite is the source of truth for review decisions
  2. Pipeline re-runs update knowledge units but NEVER overwrite existing review decisions
  3. Use content hashes to detect when a knowledge unit has changed (invalidates old review decision)
  4. Review viewer queries both the latest pipeline output AND the review DB, merging them
**Warning signs:** Approved items reappear as unreviewed after re-run; review counts don't match pipeline output counts

## Code Examples

### folio-enrich Ingestion Registry (verified from source)
```python
# Source: folio-enrich/backend/app/services/ingestion/registry.py
# Format auto-detection: extension -> content heuristic -> default

_INGESTORS: dict[DocumentFormat, type[IngestorBase]] = {
    DocumentFormat.PLAIN_TEXT: PlainTextIngestor,
    DocumentFormat.PDF: PDFIngestor,
    DocumentFormat.WORD: WordIngestor,
    DocumentFormat.HTML: HTMLIngestor,
    DocumentFormat.MARKDOWN: MarkdownIngestor,
    DocumentFormat.RTF: RTFIngestor,
    DocumentFormat.EMAIL: EmailIngestor,
}

def detect_format(filename: str | None, content: str) -> DocumentFormat:
    # Extension-based detection first, then content heuristics
    ext_map = {
        "txt": DocumentFormat.PLAIN_TEXT,
        "md": DocumentFormat.MARKDOWN,
        "html": DocumentFormat.HTML, "htm": DocumentFormat.HTML,
        "pdf": DocumentFormat.PDF,
        "docx": DocumentFormat.WORD, "doc": DocumentFormat.WORD,
        "rtf": DocumentFormat.RTF,
        "eml": DocumentFormat.EMAIL, "msg": DocumentFormat.EMAIL,
    }
    # ... then base64 prefix detection, content pattern detection

def ingest_with_elements(doc: DocumentInput) -> tuple[str, list[TextElement]]:
    """Returns both raw text and structural elements (heading, paragraph, list_item)."""
    ingestor = get_ingestor(doc.format)
    return ingestor.ingest_with_elements(doc)
```

### folio-enrich PipelineStage ABC (verified from source)
```python
# Source: folio-enrich/backend/app/pipeline/stages/base.py
class PipelineStage(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @abc.abstractmethod
    async def execute(self, job: Job) -> Job:
        """Execute this pipeline stage, mutating the job in place and returning it."""

def record_lineage(
    annotation: Annotation, stage: str, action: str,
    detail: str = "", confidence: float | None = None,
) -> None:
    annotation.lineage.append(StageEvent(
        stage=stage, action=action, detail=detail,
        confidence=confidence,
        timestamp=datetime.now(timezone.utc).isoformat(),
    ))
```

### folio-enrich Reconciler (verified from source)
```python
# Source: folio-enrich/backend/app/services/reconciliation/reconciler.py
class Reconciler:
    """Merge EntityRuler and LLM concept identification results."""

    def reconcile(self, ruler_concepts, llm_concepts) -> list[ReconciliationResult]:
        # Pass 1: Exact (text, IRI) matching -- both_agree
        # Pass 2: Cross-match empty-IRI concepts by text alone
        # Pass 3: Remaining unmatched (ruler_only or llm_only)
        ...

    def reconcile_with_embedding_triage(self, ruler_concepts, llm_concepts):
        # Enhanced: uses embedding similarity for IRI conflict resolution
        # Batch embeds conflicting pairs in single forward pass
        # Falls back to definition-overlap tiebreaker
        ...
```

### folio-enrich Per-Task LLM Routing (verified from source)
```python
# Source: folio-enrich/backend/app/pipeline/orchestrator.py
LLM_TASKS = ("classifier", "extractor", "concept", "branch_judge",
             "area_of_law", "synthetic", "individual", "property", "document_type")

@dataclass
class TaskLLMs:
    classifier: LLMProvider | None = None
    extractor: LLMProvider | None = None
    concept: LLMProvider | None = None
    branch_judge: LLMProvider | None = None
    # ... per-task fields

    @classmethod
    def from_settings(cls, fallback: LLMProvider | None = None) -> TaskLLMs:
        result = cls()
        for task in LLM_TASKS:
            llm = _try_get_task_llm(task, fallback)
            setattr(result, _TASK_FIELD_MAP.get(task, task), llm)
        return result

# Env var pattern: LLM_CLASSIFIER_PROVIDER, LLM_CLASSIFIER_MODEL, etc.
# Fallback: global LLM_PROVIDER + LLM_MODEL
# Ollama tier: empty model -> auto-select simple/medium/complex based on task
```

### folio-enrich LLM Provider Registry (verified from source)
```python
# Source: folio-enrich/backend/app/services/llm/registry.py
# 13 providers supported:
# OpenAI, Anthropic, Google, Mistral, Cohere, Meta Llama,
# Ollama, LM Studio, Custom, Groq, xAI, GitHub Models, Llamafile

DEFAULT_MODELS = {
    LLMProviderType.openai: "gpt-4o",
    LLMProviderType.anthropic: "claude-sonnet-4-6",
    LLMProviderType.google: "gemini-3-flash-preview",
    LLMProviderType.ollama: "",  # tier mode: auto-select
    # ... 10 more providers
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| MD-only ingestion (roadmap assumption) | Multi-format (DOCX, PDF, HTML, MD, TXT, RTF, XML, CSV, XLSX, WPD, EML/MSG) | CONTEXT.md decisions | Actual source files are DOCX and PDF; MD-only would miss all current sources |
| Pure LLM boundary detection | Tiered: structural -> embedding -> LLM | CONTEXT.md decisions | ~95% of boundaries handled without LLM calls; massive cost reduction |
| 3-path extraction (EntityRuler + LLM + Semantic) | 4-path (+ Document Structure heading context) | CONTEXT.md decisions | Heading context as independent signal improves tagging accuracy for well-structured textbooks |
| sentence-transformers all-MiniLM-L6-v2 only | all-MiniLM-L6-v2 for speed, all-mpnet-base-v2 for accuracy | 2025 MTEB benchmarks | all-mpnet-base-v2 gets ~87-88% STS-B vs MiniLM's ~84-85%, but is 5x slower. **Recommendation:** Use all-MiniLM-L6-v2 for Tier 2 boundary detection (speed matters more than marginal accuracy for pre-filtering); use the folio-enrich FAISS index (which already uses all-MiniLM-L6-v2) for concept similarity |
| Owlready2 for OWL | rdflib-only (no Owlready2) | Stack research decision | rdflib already in folio-enrich; Owlready2 can't handle punned entities, requires JVM for reasoning |
| LangChain for LLM orchestration | instructor for structured extraction | 2025-2026 | instructor is 10x lighter, focused on the actual need (structured output), no agent overhead |

**Deprecated/outdated:**
- folio-enrich's contextual rerank stage is **disabled by default** as of 2026-02-27 (the 50/50 LLM/pipeline blend was degrading precision). folio-insights should not rely on it being enabled.

## mjbommar / 273v Ecosystem Assessment

### python-lmss (273v)
**What it is:** Python library for the Legal Matter Standard Specification (LMSS) -- 10,000+ law-focused tags/nodes with hierarchical relationships.
**Current state:** Version 0.1.1, last updated March 2023. Not on PyPI (must install from GitHub). 32 commits total, minimal maintenance.
**Usability:** LOW. The library provides fuzzy search over LMSS concepts but is stale and not production-grade. FOLIO already provides 18,000 concepts with much richer tooling (folio-python, FolioService).
**Recommendation:** Do NOT add as a dependency. If LMSS supplementary tags are desired, implement as a lightweight lookup table imported from the LMSS OWL file directly via rdflib.

### LogiLLM (mjbommar)
**What it is:** Zero-dependency structured LLM programming framework. Define input->output signatures, framework handles prompt engineering and output parsing.
**Current state:** Early-stage (28 commits, 2 stars). Active development but not widely adopted.
**Usability:** LOW-MEDIUM. The concept overlaps with instructor (which has 11K stars, 3M+ monthly downloads). instructor is more proven for our use case.
**Recommendation:** Do NOT add. Use instructor instead -- it's the established tool for structured LLM extraction with Pydantic validation.

### Kelvin Legal Data OS (273v)
**What it is:** Patterns for legal data processing from 273 Ventures.
**Current state:** Public examples repository exists but is primarily a reference/educational resource.
**Usability:** LOW. Kelvin patterns are interesting conceptually but not a library to import. The chunking patterns from folio-enrich's existing normalizer are more directly applicable.
**Recommendation:** Reference for design patterns only. Do not import or depend on.

### Free Law Project Doctor
**What it is:** Docker microservice for document conversion (PDF, RTF, DOC, DOCX, WPD, HTML, TXT). Uses ffmpeg, pdftotext, tesseract, ghostscript internally.
**Current state:** Actively maintained. Docker image: `freelawproject/doctor:latest`. API available at port 5050.
**WPD handling:** Converts via `wpd2html` followed by HTML cleanup.
**Usability:** HIGH for WPD conversion specifically. Deploy as sidecar Docker container.
**Recommendation:** Use for WPD conversion only. For PDF/DOCX/HTML, folio-enrich's native ingestors are faster (no HTTP overhead). Deploy Doctor only when WPD files are present in the corpus.

## Open Questions

1. **folio-enrich settings isolation**
   - What we know: folio-enrich's Settings class reads from env vars and has many defaults
   - What's unclear: Whether importing folio-enrich services from folio-insights will conflict with folio-insights' own Settings
   - Recommendation: Use separate env var prefixes. Test bridge adapter import in Plan 01-01 before proceeding.

2. **Source file copyright boundaries**
   - What we know: JSON stores source references only (no original text). Knowledge units are distilled ideas.
   - What's unclear: How much source text context the review viewer can display for "trust but verify" validation
   - Recommendation: Display source text ONLY in the viewer (never persisted in JSON output). Viewer reads directly from source files on disk.

3. **Embedding model for FOLIO concept matching**
   - What we know: folio-enrich uses all-MiniLM-L6-v2 for its FAISS index
   - What's unclear: Whether the same model should be used for Tier 2 boundary detection
   - Recommendation: Yes, use all-MiniLM-L6-v2 for both. Consistency with folio-enrich's index matters more than marginal accuracy gains from mpnet. One model = one dependency = simpler deployment.

4. **Doctor microservice deployment model**
   - What we know: Doctor runs as a Docker container on port 5050
   - What's unclear: Whether the user has Docker available; how to handle WPD files if Docker is unavailable
   - Recommendation: Make Doctor optional. If Docker is not running, skip WPD files with a warning. Configure Doctor URL via env var (`DOCTOR_URL=http://localhost:5050`).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | None -- Wave 0 (to be created in Plan 01-01) |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v --timeout=30` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-01 | Ingest directory of multi-format files | integration | `pytest tests/test_ingestion.py::test_directory_walk -x` | Wave 0 |
| INGEST-02 | Preserve document structure | unit | `pytest tests/test_ingestion.py::test_structure_preservation -x` | Wave 0 |
| INGEST-03 | Handle variable-length files | unit | `pytest tests/test_ingestion.py::test_variable_length -x` | Wave 0 |
| EXTRACT-01 | Boundary detection (tiered) | unit+integration | `pytest tests/test_boundary_detection.py -x` | Wave 0 |
| EXTRACT-02 | Ideas not expressions distillation | unit | `pytest tests/test_distillation.py -x` | Wave 0 |
| EXTRACT-03 | Minimal but complete distillation | unit | `pytest tests/test_distillation.py::test_nuance_preservation -x` | Wave 0 |
| EXTRACT-04 | Extract "obvious" principles | unit | `pytest tests/test_classification.py::test_extracts_obvious -x` | Wave 0 |
| EXTRACT-05 | Novelty scoring | unit | `pytest tests/test_classification.py::test_novelty_scoring -x` | Wave 0 |
| EXTRACT-06 | Cross-document deduplication | unit | `pytest tests/test_deduplication.py -x` | Wave 0 |
| CLASS-01 | Type classification via FOLIO | unit | `pytest tests/test_classification.py::test_type_classification -x` | Wave 0 |
| CLASS-02 | Five knowledge types | unit | `pytest tests/test_classification.py::test_all_types -x` | Wave 0 |
| CLASS-03 | Classification confidence scores | unit | `pytest tests/test_classification.py::test_confidence -x` | Wave 0 |
| FOLIO-01 | Four-path FOLIO extraction | integration | `pytest tests/test_folio_tagger.py::test_four_path -x` | Wave 0 |
| FOLIO-02 | 5-stage confidence scoring | integration | `pytest tests/test_folio_tagger.py::test_confidence_pipeline -x` | Wave 0 |
| FOLIO-03 | Full ontology (18K concepts) | integration | `pytest tests/test_folio_tagger.py::test_full_ontology -x` | Wave 0 |
| FOLIO-04 | Full lineage tracking | unit | `pytest tests/test_folio_tagger.py::test_lineage -x` | Wave 0 |
| QUAL-01 | Human-reviewable JSON output | unit | `pytest tests/test_output.py::test_json_format -x` | Wave 0 |
| QUAL-02 | Confidence gating (auto-approve/flag) | unit | `pytest tests/test_output.py::test_confidence_gate -x` | Wave 0 |
| QUAL-03 | Machine-parseable output | unit | `pytest tests/test_output.py::test_parseable -x` | Wave 0 |
| PIPE-02 | Batch CLI execution | integration | `pytest tests/test_pipeline.py::test_cli -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q`
- **Per wave merge:** `pytest tests/ -v --timeout=30`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `pyproject.toml` -- project config with pytest settings (asyncio_mode="auto", timeout=30)
- [ ] `tests/conftest.py` -- shared fixtures: mock FolioService, sample TextElements, sample KnowledgeUnits, temp directory with sample source files
- [ ] `tests/test_bridge.py` -- integration test that folio-enrich services import correctly via bridge adapter
- [ ] All test files listed above -- none exist yet (greenfield project)
- [ ] Framework install: `pip install "pytest>=8.0" "pytest-asyncio>=0.25.0" "pytest-timeout>=2.3"`

## Sources

### Primary (HIGH confidence)
- folio-enrich codebase (directly examined): `services/folio/folio_service.py`, `services/ingestion/registry.py`, `services/ingestion/base.py`, `services/reconciliation/reconciler.py`, `services/normalization/normalizer.py`, `services/embedding/service.py`, `services/embedding/folio_index.py`, `services/concept/llm_concept_identifier.py`, `services/individual/citation_extractor.py`, `services/llm/base.py`, `services/llm/registry.py`, `services/llm/openai_compat.py`, `pipeline/orchestrator.py`, `pipeline/stages/base.py`, `pipeline/stages/branch_judge_stage.py`, `pipeline/stages/rerank_stage.py`, `models/annotation.py`, `models/document.py`, `config.py`, `pyproject.toml`
- folio-mapper codebase (directly examined): `services/file_parser.py`, `package.json` (React+Vite frontend confirmed)
- FOLIO ontology structure confirmed from folio-enrich's FolioService and folio-python integration
- [SvelteKit adapter-static docs](https://svelte.dev/docs/kit/adapter-static) -- prerendered SPA build
- [FastAPI StaticFiles docs](https://fastapi.tiangolo.com/tutorial/static-files/) -- mounting static build output

### Secondary (MEDIUM confidence)
- [SvelteKit + FastAPI integration patterns](https://turtledev.io/blog/how-to-build-sveltekit-spa-with-fastapi-backend) -- verified architecture: separate dev, combined production
- [sentence-transformers model comparison](https://milvus.io/ai-quick-reference/what-are-some-popular-pretrained-sentence-transformer-models-and-how-do-they-differ-for-example-allminilml6v2-vs-allmpnetbasev2) -- all-MiniLM-L6-v2 vs all-mpnet-base-v2 benchmarks
- [LLM-Enhanced Semantic Text Segmentation (MDPI, 2025)](https://www.mdpi.com/2076-3417/15/19/10849) -- embedding-based segmentation approaches
- [Free Law Project Doctor](https://github.com/freelawproject/doctor) -- Docker microservice for WPD conversion via wpd2html
- [python-lmss](https://github.com/273v/python-lmss) -- v0.1.1, last updated March 2023, not on PyPI
- [LogiLLM](https://github.com/mjbommar/logillm) -- early-stage structured LLM framework, 28 commits

### Tertiary (LOW confidence)
- mjbommar/273v Kelvin patterns -- referenced in CONTEXT.md but no substantial library to import; educational reference only
- LMSS taxonomy supplementary value -- FOLIO's 18K concepts likely subsume most of LMSS's 10K legal tags

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all core libraries verified from folio-enrich's codebase and PyPI
- Architecture: HIGH -- bridge adapter pattern verified against actual folio-enrich import structure; four-path reconciler designed from actual reconciler source code
- Pitfalls: HIGH -- based on direct codebase inspection (import paths, settings dependencies, reconciler complexity)
- mjbommar/273v ecosystem: MEDIUM -- python-lmss and LogiLLM directly inspected via GitHub; both assessed as non-essential
- SvelteKit + FastAPI: MEDIUM -- pattern verified across multiple sources; adapter-static + StaticFiles mount is well-documented
- Sentence-transformers model choice: MEDIUM -- benchmarks from multiple sources; recommendation to match folio-enrich's existing model

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (30 days -- stable domain, folio-enrich unlikely to change drastically)
