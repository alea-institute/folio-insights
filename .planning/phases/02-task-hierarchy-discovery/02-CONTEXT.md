# Phase 2: Task Hierarchy Discovery - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Discover advocacy tasks from extracted knowledge units and build a validated hierarchical task tree across the corpus. Tasks are OWL classes mapped to FOLIO concept IRIs (with new sibling proposals when FOLIO lacks specificity). Knowledge units (best practices, principles, pitfalls) attach as annotation-property metadata on each Task/Subtask class. Cross-source merging produces a single coherent tree. Contradictions detected and flagged. Full review workflow in the viewer. OWL serialization is Phase 3.

</domain>

<decisions>
## Implementation Decisions

### Task granularity and FOLIO mapping
- Tasks map to the **deepest appropriate FOLIO concept** — as deep as possible, but no deeper
- System may create **new sibling concepts** when FOLIO lacks the right granularity (proposed alongside closest parent)
- New concept proposals go through the same review workflow as Phase 1's proposed classes
- Follow FOLIO's own hierarchy depth — no artificial cap on levels
- FOLIO **polyhierarchy** supported: same concept (same IRI) appears under each parent in the tree

### Task discovery method
- **Both signals**: document structure (headings, chapters) AND content clustering of knowledge units
- Heading context from Phase 1's HeadingContextExtractor is a strong starting signal
- LLM analysis discovers **implicit tasks** that aren't in any heading but emerge from content clustering (cross-cutting tasks spanning multiple chapters)
- **Weighted blend** for task assignment when signals conflict: FOLIO tags get much higher weight than heading context

### Task types and ordering
- Distinguish between **procedural tasks** (sequential steps: do A then B then C) and **skill/categorical tasks** (collection of techniques)
- LLM attempts to **discover canonical ordering** of subtasks within procedural tasks (preparation → execution → follow-up), with "unordered" fallback
- Cross-cutting "meta-tasks" (e.g., "Witness Preparation" spanning depositions, trial, hearings) exist naturally via polyhierarchy

### Knowledge unit assignment
- Knowledge units **link to multiple task classes** (one canonical individual, multiple task links) — not duplicated
- Under each task, knowledge units **grouped by type**: Best Practices, Principles, Pitfalls, Procedural Rules, Citations
- Citations linked to tasks as supporting evidence via CITO ontology (`cito:isSupportedBy`)
- **Orphan units** auto-assigned to nearest task AND flagged for review — all flags reviewable in a batch
- **Jurisdiction sensitivity** flagged when source text mentions jurisdictional variation ("in federal court..." vs "some states require...")

### OWL modeling
- Best practices, principles, pitfalls stored as **annotation properties** on each Task/Subtask class (per roadmap goal)
- Confidence and source metadata in companion SKOS file, not OWL
- Tasks are OWL classes; knowledge units are individuals (carried forward from Phase 1)

### Pipeline architecture
- **Separate second-pass pipeline** that reads Phase 1's extraction output — not appended to the existing 7-stage orchestrator
- Can re-run task discovery without re-running extraction
- **Both CLI and UI invocation**: `folio-insights discover <corpus>` CLI command + "Discover Tasks" button in UI
- "Discover Tasks" button appears on **Upload page after Process completes** — sequential workflow: Upload → Process → Discover Tasks
- **Full SSE progress** with stage pills (Heading Analysis → FOLIO Mapping → Content Clustering → Hierarchy Construction → Cross-Source Merging → Contradiction Detection)

### Review workflow
- **Full approve/reject/edit review cycle** for discovered tasks — nothing enters OWL until reviewed (same gating as Phase 1)
- **Confidence-gated bulk review**: high-confidence task assignments bulk-approvable; low-confidence require individual review (green/yellow/red bands)
- **Full restructuring**: drag-and-drop to move subtasks, merge tasks, split tasks
- **Knowledge unit reassignment**: drag units between tasks (adds new link since units can be multi-task)
- **Manual task creation**: reviewer can create new tasks, name them, place in FOLIO hierarchy, assign units — flagged as "manually created"
- **Edits survive re-runs**: reviewer overrides stored; re-running discovery respects approved structure
- **Diff view on re-run**: shows new tasks discovered, units added/removed, hierarchy changes suggested
- **Keyboard shortcuts** extend Phase 1's set (a=approve, r=reject, e=edit, arrows navigate) + task-specific additions (m=move, g=merge)
- **Same SQLite database** as Phase 1 — extended with new tables for task decisions, hierarchy edits, reassignments

### Contradiction handling
- **Semantic opposition** detection via LLM analysis of unit pairs within the same task (not just surface negation)
- Includes partial contradictions ("do X" vs "never do X except when Y")
- **Side-by-side presentation** with source references: each side shows distilled advice, source book/chapter, author reasoning
- Reviewer can **resolve** contradictions: (1) keep both (valid in different contexts), (2) prefer one as primary, (3) merge into nuanced statement, (4) mark as jurisdiction-dependent
- **Source authority weighting**: sources assignable authority levels per corpus; higher-authority position suggested as primary in contradictions

### Task tree viewer
- **Merged single tree**: tasks integrated into FOLIO concept hierarchy (since tasks ARE FOLIO concepts)
- **Toggle** between "Show all concepts" and "Show tasks only" — default to tasks-only
- **Badge + count** styling: task nodes show unit count (e.g., "Cross-Examination (23)"); structural ancestors visible for context but no badge
- **Detail pane** (upper-right): task summary + knowledge units grouped by type (Best Practices, Principles, Pitfalls, Citations, Rules) with confidence and source references; contradictions highlighted with side-by-side treatment
- **Source pane** (lower-right): shows discovery evidence — heading context, clustered knowledge units, source passages that led to task creation
- **Filter toolbar**: filter chips for unit type, confidence band, review status, flags (contradictions, orphans, jurisdiction-sensitive)
- **Review progress indicators**: each task node shows review completion state (checkmark when all approved, partial indicator, unreviewed)
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### FOLIO Ontology
- `~/Coding Projects/folio-python/folio/graph.py` — IRI generation (`FOLIO.generate_iri()`), concept hierarchy traversal, polyhierarchy support
- FOLIO GitHub (alea-institute/FOLIO) — Full ~18,000 concept ontology with IRIs, branches, labels, parent-child relationships

### Existing folio-insights pipeline (Phase 1 output consumed by Phase 2)
- `src/folio_insights/pipeline/orchestrator.py` — PipelineOrchestrator pattern (reference for second-pass orchestrator)
- `src/folio_insights/pipeline/stages/base.py` — InsightsPipelineStage ABC and InsightsJob model (reuse for task discovery stages)
- `src/folio_insights/models/knowledge_unit.py` — KnowledgeUnit model with folio_tags, unit_type, source_section, cross_references
- `src/folio_insights/pipeline/stages/deduplicator.py` — Near-dedup at cosine 0.85 (reference for cross-source merging similarity detection)
- `src/folio_insights/pipeline/stages/structure_parser.py` — Heading hierarchy resolution (input for heading-based task discovery)
- `src/folio_insights/services/heading_context.py` — HeadingContextExtractor (Phase 1's fourth extraction path — reuse for task-heading mapping)
- `src/folio_insights/services/bridge/llm_bridge.py` — Per-task LLM routing (extend with task discovery tasks)
- `src/folio_insights/quality/confidence_gate.py` — Confidence banding pattern (reuse for task confidence gating)

### Existing folio-insights API and viewer
- `api/routes/tree.py` — `_build_tree()` function (extend for merged FOLIO+task tree)
- `api/routes/review.py` — Review endpoints (extend with task review actions)
- `api/routes/processing.py` — SSE processing pattern (replicate for task discovery progress)
- `api/routes/upload.py` — Upload page endpoints (add "Discover Tasks" trigger)
- `api/db/` — SQLite review database (extend with task review tables)
- `viewer/src/routes/+page.svelte` — Review viewer (extend with task tree, detail pane changes, filter toolbar)
- `viewer/src/routes/upload/+page.svelte` — Upload page (add Discover Tasks button)

### folio-enrich integration
- `~/Coding Projects/folio-enrich/backend/app/services/folio/folio_service.py` — FolioService: `get_concept()`, hierarchy traversal for FOLIO parent-child resolution
- `~/Coding Projects/folio-enrich/backend/app/services/streaming/sse.py` — SSE event generator pattern (replicate for task discovery)

### Standards
- W3C SKOS — `skos:broader`/`skos:narrower` for task hierarchy, `skos:related` for cross-cutting links
- CITO — `cito:isSupportedBy` for citation-task links
- W3C PROV-O — `prov:wasDerivedFrom` for task discovery provenance

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **InsightsPipelineStage ABC**: Same interface for new task discovery stages (`name` + `execute(job)`)
- **PipelineOrchestrator**: Pattern for second-pass orchestrator (checkpoint-based resume, stage chaining)
- **DeduplicatorStage**: Near-dedup at cosine 0.85 — reference for cross-source task merging
- **HeadingContextExtractor**: Heading-to-FOLIO mapping with proximity weights — reuse for task discovery signal
- **LLMBridge**: Per-task LLM routing — extend `INSIGHTS_TASKS` tuple with task discovery tasks
- **ConfidenceGate**: Threshold-based banding — reuse for task confidence gating
- **`_build_tree()` in tree.py**: Branch-based tree builder — extend for merged FOLIO+task tree with polyhierarchy
- **SSE pattern in processing.py**: Job polling + typed events — replicate for task discovery progress
- **Review SQLite schema**: aiosqlite with async patterns — extend with task review tables
- **SvelteKit tree component**: Existing tree rendering — extend with badges, progress indicators, filters

### Established Patterns
- **Bridge adapter**: Import folio-enrich services as library, don't modify internals
- **PipelineStage ABC**: `name` property + `execute(job)` async method
- **Per-task LLM routing**: Environment variable overrides (`LLM_{TASK}_PROVIDER`)
- **Checkpoint resume**: JSON checkpoint per stage for long-running pipelines
- **SSE typed events**: status, activity, complete, error event types
- **Keyboard shortcuts**: Global dispatch with focus-context awareness

### Integration Points
- **Phase 1 output**: extraction.json, review.json, proposed_classes.json consumed by task discovery pipeline
- **FolioService**: Hierarchy traversal for polyhierarchy resolution and concept lookup
- **Review database**: Same SQLite DB extended with task-specific tables
- **Upload page**: "Discover Tasks" button added after "Process" in the sequential workflow
- **CLI**: New `discover` subcommand alongside existing `extract`

</code_context>

<specifics>
## Specific Ideas

- Tasks ARE FOLIO concepts — the merged tree is natural because the task hierarchy IS a filtered view of the FOLIO ontology with knowledge units attached
- "As deep as possible, but no deeper" — the system should find the most specific FOLIO concept that accurately captures the discovered task, creating siblings only when needed
- The sequential workflow (Upload → Process → Discover Tasks → Review) mirrors the natural pipeline dependency: you can't discover tasks until extraction is done
- Source authority weighting helps when mixing authoritative treatises (Mauet, Lubet) with practice guides — the authoritative source's position gets default preference in contradictions
- Review edits surviving re-runs is critical for growing corpora — users shouldn't have to re-approve the same task structure every time a new textbook is added

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-task-hierarchy-discovery*
*Context gathered: 2026-03-18*
