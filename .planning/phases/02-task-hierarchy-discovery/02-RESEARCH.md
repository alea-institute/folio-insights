# Phase 2: Task Hierarchy Discovery - Research

**Researched:** 2026-03-19
**Domain:** LLM-driven task discovery, hierarchical clustering, FOLIO ontology mapping, contradiction detection, SvelteKit tree UI with drag-and-drop
**Confidence:** HIGH

## Summary

Phase 2 builds a second-pass pipeline that reads Phase 1's extraction output (knowledge units with FOLIO tags, heading context, and confidence scores) and organizes them into a discovered hierarchy of advocacy tasks. The pipeline uses two complementary signals: document structure (heading hierarchy from `HeadingContextExtractor`) and content clustering of knowledge units via embeddings. LLM analysis discovers implicit tasks, assigns canonical ordering to procedural tasks, and detects semantic contradictions between units on the same task. The entire pipeline is a separate orchestrator (`TaskDiscoveryOrchestrator`) following the same `InsightsPipelineStage` ABC and checkpoint pattern as Phase 1, with 6 stages: Heading Analysis, FOLIO Mapping, Content Clustering, Hierarchy Construction, Cross-Source Merging, and Contradiction Detection.

The viewer extends significantly: a merged FOLIO+task tree with badges and unit counts, a detail pane showing knowledge units grouped by type with contradiction highlighting, a source/discovery evidence pane, full review workflow with drag-and-drop restructuring, and a summary dashboard. The upload page gets a "Discover Tasks" button that triggers the second-pass pipeline with SSE progress.

All core technologies are already in the project's dependency tree: `sentence-transformers` (5.3.0) for embeddings and cross-encoder NLI, `scikit-learn` (1.8.0) for agglomerative clustering, `instructor` (1.14.4) for structured LLM output, `rdflib` (7.6.0) for SKOS/OWL output, `aiosqlite` for review persistence, and `@keenmate/svelte-treeview` (4.8.0, new dependency) for the hierarchical tree viewer with built-in drag-and-drop.

**Primary recommendation:** Build the pipeline as a clean second orchestrator using the same stage ABC; use `cross-encoder/nli-deberta-v3-base` for contradiction detection; use `@keenmate/svelte-treeview` for the tree viewer with drag-and-drop; store task hierarchy in SQLite alongside review decisions, deferring OWL serialization to Phase 3.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Tasks map to the **deepest appropriate FOLIO concept** -- as deep as possible, but no deeper
- System may create **new sibling concepts** when FOLIO lacks the right granularity (proposed alongside closest parent)
- New concept proposals go through the same review workflow as Phase 1's proposed classes
- Follow FOLIO's own hierarchy depth -- no artificial cap on levels
- FOLIO **polyhierarchy** supported: same concept (same IRI) appears under each parent in the tree
- **Both signals**: document structure (headings, chapters) AND content clustering of knowledge units
- Heading context from Phase 1's HeadingContextExtractor is a strong starting signal
- LLM analysis discovers **implicit tasks** that aren't in any heading but emerge from content clustering (cross-cutting tasks spanning multiple chapters)
- **Weighted blend** for task assignment when signals conflict: FOLIO tags get much higher weight than heading context
- Distinguish between **procedural tasks** (sequential steps) and **skill/categorical tasks** (collection of techniques)
- LLM attempts to **discover canonical ordering** of subtasks within procedural tasks (preparation -> execution -> follow-up), with "unordered" fallback
- Cross-cutting "meta-tasks" exist naturally via polyhierarchy
- Knowledge units **link to multiple task classes** (one canonical individual, multiple task links) -- not duplicated
- Under each task, knowledge units **grouped by type**: Best Practices, Principles, Pitfalls, Procedural Rules, Citations
- Citations linked to tasks as supporting evidence via CITO ontology (`cito:isSupportedBy`)
- **Orphan units** auto-assigned to nearest task AND flagged for review
- **Jurisdiction sensitivity** flagged when source text mentions jurisdictional variation
- Best practices, principles, pitfalls stored as **annotation properties** on each Task/Subtask class (per roadmap goal)
- Confidence and source metadata in companion SKOS file, not OWL
- Tasks are OWL classes; knowledge units are individuals (carried forward from Phase 1)
- **Separate second-pass pipeline** that reads Phase 1's extraction output -- not appended to the existing 7-stage orchestrator
- Can re-run task discovery without re-running extraction
- **Both CLI and UI invocation**: `folio-insights discover <corpus>` CLI command + "Discover Tasks" button in UI
- "Discover Tasks" button appears on **Upload page after Process completes** -- sequential workflow: Upload -> Process -> Discover Tasks
- **Full SSE progress** with stage pills (Heading Analysis -> FOLIO Mapping -> Content Clustering -> Hierarchy Construction -> Cross-Source Merging -> Contradiction Detection)
- **Full approve/reject/edit review cycle** for discovered tasks -- nothing enters OWL until reviewed (same gating as Phase 1)
- **Confidence-gated bulk review**: high-confidence task assignments bulk-approvable; low-confidence require individual review (green/yellow/red bands)
- **Full restructuring**: drag-and-drop to move subtasks, merge tasks, split tasks
- **Knowledge unit reassignment**: drag units between tasks (adds new link since units can be multi-task)
- **Manual task creation**: reviewer can create new tasks, name them, place in FOLIO hierarchy, assign units
- **Edits survive re-runs**: reviewer overrides stored; re-running discovery respects approved structure
- **Diff view on re-run**: shows new tasks discovered, units added/removed, hierarchy changes suggested
- **Keyboard shortcuts** extend Phase 1's set + task-specific additions (m=move, g=merge)
- **Same SQLite database** as Phase 1 -- extended with new tables for task decisions, hierarchy edits, reassignments
- **Semantic opposition** detection via LLM analysis of unit pairs within the same task (not just surface negation)
- Includes partial contradictions ("do X" vs "never do X except when Y")
- **Side-by-side presentation** with source references
- Reviewer can **resolve** contradictions: (1) keep both, (2) prefer one as primary, (3) merge into nuanced statement, (4) mark as jurisdiction-dependent
- **Source authority weighting**: sources assignable authority levels per corpus; higher-authority position suggested as primary
- **Merged single tree**: tasks integrated into FOLIO concept hierarchy (since tasks ARE FOLIO concepts)
- **Toggle** between "Show all concepts" and "Show tasks only" -- default to tasks-only
- **Badge + count** styling: task nodes show unit count; structural ancestors visible for context but no badge
- **Detail pane** (upper-right): task summary + knowledge units grouped by type with confidence and source references; contradictions highlighted with side-by-side treatment
- **Source pane** (lower-right): shows discovery evidence -- heading context, clustered knowledge units, source passages that led to task creation
- **Filter toolbar**: filter chips for unit type, confidence band, review status, flags (contradictions, orphans, jurisdiction-sensitive)
- **Review progress indicators**: each task node shows review completion state
- **Multi-format export**: Markdown (outline), JSON (machine-consumable), HTML (printable report)
- **Summary dashboard**: total tasks/subtasks, unit distribution by type, source coverage, confidence distribution, contradiction count, review progress

### Claude's Discretion
- LLM prompt design for task discovery, ordering, and contradiction detection
- Exact clustering algorithm for implicit task discovery
- Technical details of FOLIO hierarchy traversal and polyhierarchy resolution
- Embedding model choice for semantic opposition detection
- Specific confidence thresholds for task assignment
- Dashboard layout and visualization choices
- Drag-and-drop implementation details

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TASK-01 | System discovers top-level advocacy tasks from the texts themselves (e.g., depositions, opening statements, motions, cross-examination) | Heading Analysis stage extracts task candidates from heading hierarchy; Content Clustering stage discovers implicit tasks from knowledge unit embeddings; LLM validates and names discovered tasks with Instructor structured output |
| TASK-02 | System builds hierarchical task trees: Task > Subtask > Best Practice / Principle / Pitfall | Hierarchy Construction stage builds parent-child relationships using FOLIO concept hierarchy (polyhierarchy-aware); knowledge units attach as annotation-property metadata grouped by type; procedural task ordering detected by LLM |
| TASK-03 | System merges task hierarchy fragments discovered across multiple source files into a single coherent tree | Cross-Source Merging stage uses embedding similarity (cosine > 0.85 threshold from Phase 1's dedup) to match tasks across sources; canonical task selected by highest aggregate confidence; FOLIO IRI matching provides exact merge targets |
| TASK-04 | System detects and flags contradictory advice from different sources on the same task | Contradiction Detection stage uses cross-encoder NLI model (`cross-encoder/nli-deberta-v3-base`, 92.38% SNLI accuracy) for initial semantic opposition screening, then LLM analysis for nuanced partial contradictions; results stored with both positions and source references |
</phase_requirements>

## Standard Stack

### Core (already installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sentence-transformers | 5.3.0 | Embeddings (all-MiniLM-L6-v2) + cross-encoder NLI (nli-deberta-v3-base) | Already used in Phase 1 dedup; cross-encoder NLI is the established approach for contradiction detection |
| scikit-learn | 1.8.0 | AgglomerativeClustering for content clustering | Already installed; hierarchical clustering preserves dendrogram structure matching task hierarchy |
| instructor | 1.14.4 | Structured LLM output for task discovery, ordering, contradiction analysis | Already used in Phase 1; Pydantic model validation with automatic retries |
| rdflib | 7.6.0 | SKOS broader/narrower hierarchy + CITO citation links | Already used; standard Python RDF library |
| pydantic | 2.12.5 | Data models for tasks, contradictions, discovery results | Already used everywhere |
| aiosqlite | 0.20+ | Review persistence for task decisions, hierarchy edits | Already used in Phase 1 review database |
| click | 8.1.8 | CLI `discover` subcommand | Already used for `extract` command |
| folio-python | 0.1.5+ | FOLIO IRI generation, concept hierarchy access | Already a dependency |

### New Dependencies
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| @keenmate/svelte-treeview | 4.8.0 | Hierarchical tree viewer with built-in drag-and-drop, search, virtual scroll | Task tree display with restructuring; handles 500-10k nodes with progressive flat rendering |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| @keenmate/svelte-treeview | Custom tree + HTML5 DnD | Treeview has built-in LTree paths, DnD with above/below/child positions, virtual scroll; custom would take 2-3x longer for worse results |
| AgglomerativeClustering | HDBSCAN | Agglomerative gives explicit dendrogram hierarchy matching task tree shape; HDBSCAN better for unknown cluster counts but flat output |
| cross-encoder/nli-deberta-v3-base | LLM-only contradiction detection | Cross-encoder is fast batch screening (0.2B params); LLM is slow but nuanced. Use cross-encoder to filter candidates, then LLM for confirmation |
| cross-encoder/nli-deberta-v3-base | cross-encoder/nli-distilroberta-base | deberta-v3-base has 92.38% accuracy vs distilroberta's lower accuracy; worth the slightly larger model |

**Installation:**
```bash
# Python (already installed in venv)
# No new Python dependencies needed

# Viewer
cd viewer && npm install @keenmate/svelte-treeview@4.8.0
```

## Architecture Patterns

### Recommended Project Structure
```
src/folio_insights/
  pipeline/
    stages/                      # Existing Phase 1 stages
    discovery/                   # NEW: Phase 2 task discovery
      __init__.py
      orchestrator.py            # TaskDiscoveryOrchestrator (same pattern as PipelineOrchestrator)
      stages/
        __init__.py
        base.py                  # DiscoveryJob model (extends InsightsJob pattern)
        heading_analysis.py      # Stage 1: Extract task candidates from headings
        folio_mapping.py         # Stage 2: Map candidates to FOLIO concepts
        content_clustering.py    # Stage 3: Cluster knowledge units to discover implicit tasks
        hierarchy_construction.py # Stage 4: Build parent-child tree with ordering
        cross_source_merging.py  # Stage 5: Merge task fragments across sources
        contradiction_detection.py # Stage 6: Detect semantic opposition
  models/
    knowledge_unit.py            # Existing (unchanged)
    task.py                      # NEW: DiscoveredTask, TaskHierarchy, Contradiction models
  services/
    heading_context.py           # Existing (reused)
    task_clustering.py           # NEW: Embedding-based task clustering
    contradiction_detector.py    # NEW: Cross-encoder NLI + LLM contradiction analysis
    task_exporter.py             # NEW: Multi-format export (MD, JSON, HTML)

api/
  routes/
    tree.py                      # EXTENDED: Merged FOLIO+task tree with badges
    review.py                    # EXTENDED: Task review endpoints
    processing.py                # EXTENDED: SSE for discovery pipeline
    discovery.py                 # NEW: Discovery trigger, task CRUD, contradiction resolution
    export.py                    # NEW: Multi-format export endpoints
  db/
    models.py                    # EXTENDED: Task review tables schema
  services/
    pipeline_runner.py           # EXTENDED: Discovery pipeline runner
    discovery_runner.py          # NEW: Task discovery pipeline runner with progress

viewer/src/
  routes/
    +page.svelte                 # EXTENDED: Task tree view with new components
    upload/+page.svelte          # EXTENDED: "Discover Tasks" button
  lib/
    components/
      TaskTree.svelte            # NEW: Tree using @keenmate/svelte-treeview with DnD
      TaskDetail.svelte          # NEW: Task detail pane with grouped units
      ContradictionView.svelte   # NEW: Side-by-side contradiction display
      DiscoveryEvidence.svelte   # NEW: Source pane showing discovery provenance
      FilterToolbar.svelte       # NEW: Filter chips for type, confidence, status, flags
      TaskDashboard.svelte       # NEW: Summary dashboard with statistics
      ManualTaskDialog.svelte    # NEW: Dialog for creating manual tasks
      DiffView.svelte            # NEW: Re-run diff showing changes
    stores/
      tasks.ts                   # NEW: Task tree state, selected task, filters
      discovery.ts               # NEW: Discovery pipeline SSE state
    api/
      client.ts                  # EXTENDED: Task discovery, review, export endpoints
```

### Pattern 1: TaskDiscoveryOrchestrator (Second-Pass Pipeline)
**What:** A separate orchestrator that reads Phase 1 output and runs 6 discovery stages
**When to use:** Always -- this is the core pipeline for Phase 2
**Example:**
```python
# Source: Follows existing PipelineOrchestrator pattern from orchestrator.py
class DiscoveryJob(BaseModel):
    """Pipeline job carrying state across discovery stages."""
    corpus_name: str
    source_dir: Path
    # Phase 1 input
    knowledge_units: list[KnowledgeUnit] = Field(default_factory=list)
    documents: list[CorpusDocument] = Field(default_factory=list)
    # Discovery output
    discovered_tasks: list[DiscoveredTask] = Field(default_factory=list)
    task_hierarchy: TaskHierarchy | None = None
    contradictions: list[Contradiction] = Field(default_factory=list)
    orphan_units: list[str] = Field(default_factory=list)  # unit IDs
    metadata: dict = Field(default_factory=dict)

class TaskDiscoveryOrchestrator:
    """Orchestrate the 6-stage task discovery pipeline."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._stages = self._build_stages()

    def _build_stages(self) -> list[InsightsPipelineStage]:
        return [
            HeadingAnalysisStage(),
            FolioMappingStage(),
            ContentClusteringStage(),
            HierarchyConstructionStage(),
            CrossSourceMergingStage(),
            ContradictionDetectionStage(),
        ]

    async def run(self, corpus_name: str, resume: bool = True) -> DiscoveryJob:
        """Load Phase 1 output, then run all discovery stages."""
        # Load extraction.json from Phase 1
        extraction_path = self.settings.output_dir / corpus_name / "extraction.json"
        data = json.loads(extraction_path.read_text())

        job = DiscoveryJob(
            corpus_name=corpus_name,
            source_dir=self.settings.output_dir / corpus_name / "sources",
            knowledge_units=[KnowledgeUnit(**u) for u in data["units"]],
        )

        # Checkpoint-based stage execution (same pattern as Phase 1)
        for stage in self._stages:
            if resume and PipelineCheckpoint.has_checkpoint(stage.name, corpus_dir):
                restored = PipelineCheckpoint.load(stage.name, corpus_dir)
                if restored is not None:
                    job = restored
                    continue
            job = await stage.execute(job)
            PipelineCheckpoint.save(stage.name, job, corpus_dir)

        return job
```

### Pattern 2: Two-Phase Contradiction Detection (Fast Screen + Deep Analysis)
**What:** Cross-encoder NLI for fast batch screening, then LLM for nuanced analysis
**When to use:** Contradiction Detection stage (Stage 6)
**Example:**
```python
# Source: cross-encoder/nli-deberta-v3-base HuggingFace model card
from sentence_transformers import CrossEncoder

class ContradictionDetector:
    """Detect contradictions between knowledge units within the same task."""

    def __init__(self):
        self._nli_model = CrossEncoder("cross-encoder/nli-deberta-v3-base")
        self._label_mapping = ["contradiction", "entailment", "neutral"]

    async def screen_pairs(
        self, units: list[KnowledgeUnit]
    ) -> list[tuple[str, str, float]]:
        """Phase 1: Fast NLI screening of all unit pairs.

        Returns pairs where contradiction score > threshold.
        """
        pairs = []
        for i, u1 in enumerate(units):
            for u2 in units[i+1:]:
                pairs.append((u1.text, u2.text))

        if not pairs:
            return []

        scores = self._nli_model.predict(pairs)
        # scores shape: (n_pairs, 3) -> [contradiction, entailment, neutral]

        candidates = []
        pair_idx = 0
        for i, u1 in enumerate(units):
            for u2 in units[i+1:]:
                contradiction_score = scores[pair_idx][0]
                if contradiction_score > 0.7:  # Threshold for LLM follow-up
                    candidates.append((u1.id, u2.id, float(contradiction_score)))
                pair_idx += 1

        return candidates

    async def deep_analyze(
        self, unit_a: KnowledgeUnit, unit_b: KnowledgeUnit
    ) -> Contradiction | None:
        """Phase 2: LLM analysis for nuanced contradiction assessment."""
        # Uses Instructor for structured output
        ...
```

### Pattern 3: Heading-to-FOLIO Task Mapping with Weighted Blend
**What:** Combine heading hierarchy signal with FOLIO tag signal, weighting FOLIO higher
**When to use:** HeadingAnalysis and FolioMapping stages
**Example:**
```python
# Source: Existing HeadingContextExtractor pattern + CONTEXT.md weighted blend
class TaskCandidate(BaseModel):
    """A candidate task discovered from heading or content analysis."""
    label: str
    folio_iri: str | None = None  # Matched FOLIO concept IRI
    folio_label: str = ""
    source_signal: str  # "heading", "clustering", "llm"
    confidence: float
    heading_path: list[str] = Field(default_factory=list)
    knowledge_unit_ids: list[str] = Field(default_factory=list)
    is_procedural: bool = False
    canonical_order: int | None = None

def compute_task_confidence(
    folio_confidence: float,
    heading_confidence: float,
    folio_weight: float = 0.7,
    heading_weight: float = 0.3,
) -> float:
    """Weighted blend: FOLIO tags get much higher weight than heading context."""
    return (folio_confidence * folio_weight) + (heading_confidence * heading_weight)
```

### Pattern 4: SQLite Task Review Tables (Extending Phase 1 Schema)
**What:** New tables for task decisions, hierarchy edits, unit reassignments, contradictions
**When to use:** Review persistence for all task-related decisions
**Example:**
```sql
-- Extends existing review_decisions and proposed_class_decisions tables

CREATE TABLE IF NOT EXISTS task_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    corpus_name TEXT NOT NULL,
    folio_iri TEXT,
    label TEXT NOT NULL,
    parent_task_id TEXT,
    status TEXT NOT NULL DEFAULT 'unreviewed',  -- unreviewed/approved/rejected/edited
    is_procedural INTEGER DEFAULT 0,
    canonical_order INTEGER,
    is_manual INTEGER DEFAULT 0,  -- 1 if manually created by reviewer
    edited_label TEXT,
    reviewer_note TEXT DEFAULT '',
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS task_unit_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    corpus_name TEXT NOT NULL,
    is_canonical INTEGER DEFAULT 0,  -- 1 if this is the unit's canonical task
    assignment_source TEXT DEFAULT 'discovery',  -- discovery/manual/reassignment
    confidence REAL DEFAULT 0.0,
    reviewed INTEGER DEFAULT 0,
    UNIQUE(task_id, unit_id)
);

CREATE TABLE IF NOT EXISTS hierarchy_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corpus_name TEXT NOT NULL,
    edit_type TEXT NOT NULL,  -- move/merge/split/create/delete
    source_task_id TEXT,
    target_task_id TEXT,
    detail TEXT DEFAULT '',  -- JSON with edit specifics
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contradictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    unit_id_a TEXT NOT NULL,
    unit_id_b TEXT NOT NULL,
    corpus_name TEXT NOT NULL,
    nli_score REAL,  -- Cross-encoder contradiction score
    contradiction_type TEXT DEFAULT 'full',  -- full/partial/jurisdictional
    resolution TEXT,  -- keep_both/prefer_a/prefer_b/merge/jurisdiction
    resolved_text TEXT,  -- Merged nuanced statement if resolution=merge
    resolver_note TEXT DEFAULT '',
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(unit_id_a, unit_id_b, task_id)
);

CREATE TABLE IF NOT EXISTS source_authority (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corpus_name TEXT NOT NULL,
    source_file TEXT NOT NULL,
    authority_level INTEGER DEFAULT 5,  -- 1-10 scale
    author TEXT DEFAULT '',
    UNIQUE(corpus_name, source_file)
);

CREATE INDEX IF NOT EXISTS idx_task_corpus ON task_decisions(corpus_name);
CREATE INDEX IF NOT EXISTS idx_task_status ON task_decisions(status);
CREATE INDEX IF NOT EXISTS idx_task_parent ON task_decisions(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tul_task ON task_unit_links(task_id);
CREATE INDEX IF NOT EXISTS idx_tul_unit ON task_unit_links(unit_id);
CREATE INDEX IF NOT EXISTS idx_contradiction_task ON contradictions(task_id);
```

### Pattern 5: @keenmate/svelte-treeview Integration
**What:** Use the LTree path-based treeview for the merged FOLIO+task tree
**When to use:** TaskTree.svelte component
**Example:**
```svelte
<script lang="ts">
  import Tree from '@keenmate/svelte-treeview';
  import '@keenmate/svelte-treeview/styles.scss';

  interface TaskTreeNode {
    id: string;
    path: string;          // LTree dot-notation: "1.2.3"
    label: string;
    folio_iri: string;
    unit_count: number;
    review_status: string;  // "unreviewed" | "partial" | "complete"
    is_task: boolean;       // vs structural ancestor
    has_contradictions: boolean;
    has_orphans: boolean;
    sortOrder: number;
  }

  let { data, onselect, ondrop }: {
    data: TaskTreeNode[];
    onselect: (node: TaskTreeNode) => void;
    ondrop: (info: { draggedNode: TaskTreeNode; dropNode: TaskTreeNode; position: string }) => void;
  } = $props();

  // Use $state.raw for large datasets (1000+ items) per treeview docs
  let treeData = $state.raw(data);
</script>

<Tree
  data={treeData}
  idMember="id"
  pathMember="path"
  displayValueMember="label"
  dragDropMode="both"
  orderMember="sortOrder"
  shouldUseInternalSearchIndex={true}
  searchValueMember="label"
  onNodeClick={(node) => onselect(node)}
  onNodeDrop={(info) => ondrop(info)}
/>
```

### Anti-Patterns to Avoid
- **Duplicating knowledge units across tasks:** Units link to multiple tasks via `task_unit_links` join table, not by copying. One canonical individual, multiple task relationships.
- **Hardcoding task taxonomy:** Tasks MUST be discovered from source texts, not from a predefined list. The heading analysis and content clustering produce candidates; the LLM validates and names them.
- **Running contradiction detection on all pairs globally:** Only compare units within the same task. Cross-task contradictions are expected (different contexts). Within-task pairs should be screened with cross-encoder first, then deep LLM analysis only for candidates above threshold.
- **Losing review decisions on re-run:** Store all human overrides in SQLite. When re-running discovery, load approved task structure first, then only propose additions/changes as diffs.
- **Building a custom tree component:** Use `@keenmate/svelte-treeview` which handles LTree paths, DnD positioning (above/below/child), virtual scroll for large trees, and search indexing out of the box.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Hierarchical tree UI with DnD | Custom recursive tree + HTML5 DnD | @keenmate/svelte-treeview | Built-in DnD with position control, virtual scroll, search indexing, LTree path management |
| NLI contradiction screening | Embedding cosine + threshold | CrossEncoder("cross-encoder/nli-deberta-v3-base") | Purpose-built for entailment/contradiction/neutral classification; 92.38% accuracy |
| Text clustering | Manual similarity grouping | sklearn.cluster.AgglomerativeClustering | Produces dendrogram hierarchy matching task tree structure; handles variable cluster sizes |
| Structured LLM output | Manual JSON parsing + retries | instructor with Pydantic models | Automatic validation, retries, type safety -- already in project |
| FOLIO concept hierarchy traversal | Manual parent_iris walking | FolioService.search_by_label() + folio-python | Handles polyhierarchy, branch detection, label search -- already integrated via bridge |

**Key insight:** The project already has all Python dependencies installed. The only new dependency is the npm treeview component. The architecture challenge is not tooling but orchestrating the pipeline stages and managing the complex review state.

## Common Pitfalls

### Pitfall 1: Quadratic Pair Explosion in Contradiction Detection
**What goes wrong:** Comparing all N knowledge units pairwise across the corpus gives O(N^2) pairs -- thousands of units means millions of comparisons
**Why it happens:** Naive implementation compares everything against everything
**How to avoid:** Only compare units within the same task (much smaller groups). Use cross-encoder batch prediction for fast screening, then LLM analysis only for high-score candidates (> 0.7 contradiction score). Batch cross-encoder predictions in groups of 64-128 pairs.
**Warning signs:** Contradiction detection stage taking > 5 minutes for small corpora

### Pitfall 2: FOLIO Polyhierarchy Creating Duplicate Tree Nodes
**What goes wrong:** A concept with multiple parents appears multiple times in the tree, confusing the reviewer
**Why it happens:** FOLIO supports polyhierarchy (multiple `parent_iris`), so the same IRI can appear under different branches
**How to avoid:** In the tree view, show each concept once at its primary (most relevant) location. Use a "Also appears under:" link or badge for secondary parents. In the data model, the concept exists once with multiple parent references.
**Warning signs:** Tree showing identical task labels in different branches

### Pitfall 3: Heading-Only Discovery Missing Cross-Cutting Tasks
**What goes wrong:** Tasks like "Witness Preparation" that span depositions, trial, and hearings are never discovered because they don't appear as headings
**Why it happens:** Relying solely on document structure misses emergent patterns
**How to avoid:** Content clustering is the second signal -- cluster knowledge units by embedding similarity independent of heading context. LLM analysis of cluster contents identifies cross-cutting tasks. Polyhierarchy naturally represents these (same task under multiple parents).
**Warning signs:** All discovered tasks map 1:1 to document headings; no cross-cutting tasks found

### Pitfall 4: Re-Run Destroying Reviewer Edits
**What goes wrong:** Re-running discovery after adding new source files wipes out all approved task assignments and hierarchy edits
**Why it happens:** Discovery pipeline overwrites previous output without checking for existing decisions
**How to avoid:** Before discovery stages run, load all approved decisions from SQLite. Mark approved tasks as locked -- discovery can propose additions around them but never modify them. Show diff view on re-run: new tasks discovered, new units to assign, hierarchy changes suggested.
**Warning signs:** Reviewer approves 50 tasks, adds a new book, re-runs discovery, and all 50 decisions are gone

### Pitfall 5: Orphan Units Polluting Task Tree
**What goes wrong:** Units with no clear task assignment end up in a massive "Uncategorized" bucket or silently dropped
**Why it happens:** Not all knowledge units have strong heading context or FOLIO tags that match discovered tasks
**How to avoid:** Auto-assign orphans to the nearest task by embedding similarity, then flag them for review. Show orphan count in dashboard. Reviewer can batch-process orphans.
**Warning signs:** More than 20% of units are orphans after discovery

### Pitfall 6: Slow Virtual Scroll with Svelte 5 Deep Proxies
**What goes wrong:** Tree with 1000+ nodes becomes unresponsive
**Why it happens:** Svelte 5's `$state()` creates deep proxies; @keenmate/svelte-treeview docs warn of "up to 5,000x slowdown"
**How to avoid:** Use `$state.raw()` instead of `$state()` for tree data arrays with 1000+ items. The treeview component's progressive flat rendering mode handles 500-10,000 nodes efficiently.
**Warning signs:** Tree interactions (expand/collapse) take > 200ms

## Code Examples

### Content Clustering with AgglomerativeClustering
```python
# Source: scikit-learn 1.8.0 AgglomerativeClustering docs
import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sentence_transformers import SentenceTransformer

def cluster_units_for_task_discovery(
    units: list[KnowledgeUnit],
    distance_threshold: float = 0.5,
) -> list[list[int]]:
    """Cluster knowledge units by embedding similarity to discover implicit tasks.

    Uses agglomerative clustering with cosine affinity and average linkage.
    distance_threshold controls granularity: lower = more clusters = finer tasks.
    """
    model = SentenceTransformer("all-MiniLM-L6-v2")
    texts = [u.text for u in units]
    embeddings = model.encode(texts, normalize_embeddings=True)

    clustering = AgglomerativeClustering(
        n_clusters=None,  # Discover cluster count automatically
        distance_threshold=distance_threshold,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(embeddings)

    # Group unit indices by cluster
    clusters: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        clusters.setdefault(label, []).append(idx)

    return list(clusters.values())
```

### Cross-Encoder NLI for Contradiction Screening
```python
# Source: cross-encoder/nli-deberta-v3-base HuggingFace model card
from sentence_transformers import CrossEncoder

_nli_model = None

def get_nli_model() -> CrossEncoder:
    global _nli_model
    if _nli_model is None:
        _nli_model = CrossEncoder("cross-encoder/nli-deberta-v3-base")
    return _nli_model

def screen_contradictions(
    pairs: list[tuple[str, str]],
    threshold: float = 0.7,
) -> list[tuple[int, float]]:
    """Screen text pairs for contradictions using NLI cross-encoder.

    Returns indices and scores for pairs above contradiction threshold.
    Label mapping: 0=contradiction, 1=entailment, 2=neutral.
    """
    model = get_nli_model()
    scores = model.predict(pairs)  # shape: (n_pairs, 3)

    results = []
    for i, score in enumerate(scores):
        contradiction_score = float(score[0])
        if contradiction_score > threshold:
            results.append((i, contradiction_score))

    return results
```

### Instructor Structured Output for Task Discovery
```python
# Source: instructor 1.14.4 pattern (already in project)
import instructor
from pydantic import BaseModel, Field

class DiscoveredTaskResponse(BaseModel):
    """LLM response for task discovery from a cluster of knowledge units."""
    task_label: str = Field(description="Concise label for the advocacy task")
    task_description: str = Field(description="One-sentence description")
    is_procedural: bool = Field(
        description="True if steps must be performed in order"
    )
    subtask_labels: list[str] = Field(
        default_factory=list,
        description="Ordered list of subtask labels (if procedural)"
    )
    folio_concept_suggestion: str = Field(
        default="",
        description="Suggested FOLIO concept label to map to"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence this is a distinct advocacy task"
    )

class ContradictionAnalysis(BaseModel):
    """LLM analysis of a potential contradiction between two units."""
    is_contradiction: bool
    contradiction_type: str = Field(
        description="full, partial, or jurisdictional"
    )
    explanation: str = Field(
        description="Why these positions conflict"
    )
    context_dependency: str = Field(
        default="",
        description="Conditions under which each position is valid"
    )
    suggested_resolution: str = Field(
        description="keep_both, prefer_a, prefer_b, merge, or jurisdiction"
    )
```

### LLM Bridge Extension for Task Discovery Tasks
```python
# Source: Existing LLMBridge pattern in llm_bridge.py
# Extend INSIGHTS_TASKS tuple with new task names
INSIGHTS_TASKS: tuple[str, ...] = (
    # Phase 1 tasks (existing)
    "boundary", "classifier", "distiller", "novelty",
    "heading_mapper", "concept", "branch_judge",
    # Phase 2 tasks (new)
    "task_discovery",      # Discover tasks from unit clusters
    "task_ordering",       # Determine procedural vs categorical, canonical order
    "contradiction",       # Deep contradiction analysis
    "orphan_assignment",   # Assign orphan units to nearest task
)
```

### Multi-Format Export
```python
# Source: Architecture decision from CONTEXT.md
def export_task_hierarchy_markdown(
    tasks: list[DiscoveredTask],
    units_by_task: dict[str, list[KnowledgeUnit]],
) -> str:
    """Export task hierarchy as Markdown outline."""
    lines = ["# Advocacy Task Hierarchy\n"]

    for task in sorted(tasks, key=lambda t: t.canonical_order or 0):
        indent = "  " * task.depth
        lines.append(f"{indent}- **{task.label}**")

        if task.is_procedural:
            lines.append(f"{indent}  _(procedural - ordered steps)_")

        task_units = units_by_task.get(task.id, [])
        by_type = group_units_by_type(task_units)

        for unit_type, type_units in by_type.items():
            lines.append(f"{indent}  - {unit_type}:")
            for unit in type_units:
                lines.append(f"{indent}    - {unit.text}")

    return "\n".join(lines)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Keyword matching for contradiction | Cross-encoder NLI models (deberta-v3) | 2023-2024 | 92%+ accuracy vs ~60% for keyword; handles paraphrasing |
| Flat clustering (k-means) | Hierarchical agglomerative clustering | Standard | Preserves dendrogram -> natural task hierarchy |
| Manual drag-and-drop trees | @keenmate/svelte-treeview for Svelte 5 | 2024-2025 | Built-in DnD with position control, virtual scroll, LTree paths |
| sentence-transformers bi-encoder for NLI | Cross-encoder for NLI classification | Established | Cross-encoder is slower but significantly more accurate for pairwise classification |
| Svelte $state() for large lists | $state.raw() for 1000+ items | Svelte 5 | Avoids deep proxy overhead; 5000x speedup per treeview docs |

**Deprecated/outdated:**
- `svelte-sortable-list` / `svelte-dnd-action`: Svelte 4 libraries, not compatible with Svelte 5 runes
- `cross-encoder/nli-roberta-base`: Superseded by deberta-v3-base with higher accuracy

## Open Questions

1. **Optimal distance_threshold for AgglomerativeClustering**
   - What we know: Lower threshold = more clusters = finer-grained tasks. The dedup threshold is 0.85 (too similar = duplicate). Task clustering needs a wider band.
   - What's unclear: The exact threshold for advocacy text. Starting at 0.5 is reasonable but may need tuning.
   - Recommendation: Start with 0.5, expose as a configuration parameter, tune based on output quality. Add a `--cluster-threshold` CLI option.

2. **Contradiction NLI threshold for LLM follow-up**
   - What we know: Cross-encoder outputs 3 scores (contradiction/entailment/neutral). Need a threshold to decide which candidates get expensive LLM analysis.
   - What's unclear: Whether 0.7 is optimal. Too low = too many LLM calls; too high = missed contradictions.
   - Recommendation: Start at 0.7, log all pairs > 0.5 for analysis. Surface the threshold in settings.

3. **Tree node count and performance**
   - What we know: FOLIO has ~18,000 concepts. The "tasks only" filter significantly reduces this. @keenmate/svelte-treeview handles 500-10,000 with progressive flat rendering.
   - What's unclear: How many task nodes a typical corpus will produce (likely 50-500).
   - Recommendation: Default to "tasks only" view. Use progressive flat rendering. Use $state.raw() for tree data.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio 0.25+ |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `cd "/home/damienriehl/Coding Projects/folio-insights" && .venv/bin/pytest tests/ -x --timeout=30` |
| Full suite command | `cd "/home/damienriehl/Coding Projects/folio-insights" && .venv/bin/pytest tests/ --timeout=60` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TASK-01 | Discover top-level tasks from text headings and content clustering | unit | `.venv/bin/pytest tests/test_task_discovery.py -x` | Wave 0 |
| TASK-01 | LLM discovers implicit tasks from unit clusters | unit | `.venv/bin/pytest tests/test_task_discovery.py::test_implicit_task_discovery -x` | Wave 0 |
| TASK-02 | Build hierarchical task tree with parent-child relationships | unit | `.venv/bin/pytest tests/test_hierarchy.py -x` | Wave 0 |
| TASK-02 | Procedural vs categorical task classification | unit | `.venv/bin/pytest tests/test_hierarchy.py::test_procedural_ordering -x` | Wave 0 |
| TASK-02 | Knowledge units grouped by type under tasks | unit | `.venv/bin/pytest tests/test_hierarchy.py::test_unit_grouping -x` | Wave 0 |
| TASK-03 | Cross-source task merging by embedding similarity | unit | `.venv/bin/pytest tests/test_merging.py -x` | Wave 0 |
| TASK-03 | FOLIO IRI matching for exact merge targets | unit | `.venv/bin/pytest tests/test_merging.py::test_iri_merge -x` | Wave 0 |
| TASK-04 | Cross-encoder NLI contradiction screening | unit | `.venv/bin/pytest tests/test_contradictions.py -x` | Wave 0 |
| TASK-04 | LLM deep contradiction analysis | unit | `.venv/bin/pytest tests/test_contradictions.py::test_deep_analysis -x` | Wave 0 |
| TASK-04 | Contradiction resolution storage | unit | `.venv/bin/pytest tests/test_contradictions.py::test_resolution_storage -x` | Wave 0 |
| -- | Discovery API endpoints (trigger, stream, CRUD) | integration | `.venv/bin/pytest tests/test_discovery_api.py -x` | Wave 0 |
| -- | Task review endpoints (approve, reject, edit, bulk) | integration | `.venv/bin/pytest tests/test_task_review_api.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/ -x --timeout=30`
- **Per wave merge:** `.venv/bin/pytest tests/ --timeout=60`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_task_discovery.py` -- covers TASK-01 (heading analysis, content clustering, LLM discovery)
- [ ] `tests/test_hierarchy.py` -- covers TASK-02 (tree building, ordering, unit grouping)
- [ ] `tests/test_merging.py` -- covers TASK-03 (cross-source merging, IRI matching)
- [ ] `tests/test_contradictions.py` -- covers TASK-04 (NLI screening, deep analysis, resolution)
- [ ] `tests/test_discovery_api.py` -- covers discovery trigger, SSE stream, task CRUD endpoints
- [ ] `tests/test_task_review_api.py` -- covers task review workflow endpoints

## Sources

### Primary (HIGH confidence)
- scikit-learn 1.8.0 AgglomerativeClustering docs -- hierarchical clustering with cosine affinity
- cross-encoder/nli-deberta-v3-base HuggingFace model card -- 92.38% SNLI accuracy, contradiction/entailment/neutral labels
- @keenmate/svelte-treeview GitHub/npm -- LTree paths, DnD with position control, virtual scroll, Svelte 5 compatibility
- Existing codebase: PipelineOrchestrator, InsightsPipelineStage, DeduplicatorStage, HeadingContextExtractor, ConfidenceGate, LLMBridge, review.py, processing.py -- all patterns verified by direct code reading

### Secondary (MEDIUM confidence)
- W3C SKOS Reference -- skos:broader/narrower for task hierarchy representation
- sentence-transformers 5.3.0 CrossEncoder API -- verified available in project venv
- instructor 1.14.4 -- structured LLM output with Pydantic validation

### Tertiary (LOW confidence)
- Optimal clustering distance_threshold (0.5 starting point) -- needs empirical tuning
- NLI contradiction threshold (0.7 starting point) -- needs empirical tuning

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all Python packages already installed and verified in project venv; npm package verified on registry
- Architecture: HIGH - follows established Phase 1 patterns (orchestrator, pipeline stages, review DB, SSE, CLI); direct code reading confirms compatibility
- Pitfalls: HIGH - identified from direct codebase analysis (polyhierarchy in FOLIO, Svelte 5 proxy overhead, re-run state preservation)
- Contradiction detection: HIGH - cross-encoder/nli-deberta-v3-base well-documented with verified accuracy scores

**Research date:** 2026-03-19
**Valid until:** 2026-04-19 (30 days - stable ecosystem, established patterns)
