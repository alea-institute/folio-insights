---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Completed 01-02-PLAN.md
last_updated: "2026-04-13T02:07:16.102Z"
last_activity: 2026-04-13
progress:
  total_phases: 2
  completed_phases: 1
  total_plans: 7
  completed_plans: 6
  percent: 86
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-17)

**Core value:** Every piece of actionable legal advocacy knowledge must be discoverable by task, mapped to FOLIO concepts, and structured for practitioners, AI systems, and developers.
**Current focus:** Phase 01 — deploy-on-railway-as-dev-server

## Current Position

Phase: 01 (deploy-on-railway-as-dev-server) — EXECUTING
Plan: 3 of 3
Status: Ready to execute
Last activity: 2026-04-13

Progress: [█████████▒] 93%

## Performance Metrics

**Velocity:**

- Total plans completed: 14
- Average duration: 9.4 min
- Total execution time: 2.3 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-knowledge-extraction-pipeline | 4/4 | 71 min | 17.8 min |
| 01.1-upload-processing-ui | 4/4 | 22 min | 5.5 min |
| 02-task-hierarchy-discovery | 5/5 | 37 min | 7.4 min |
| 03-ontology-output-and-delivery | 1/2 | 8 min | 8.0 min |

**Recent Trend:**

- Last 5 plans: 6 min, 7 min, 8 min, 12 min, 8 min
- Trend: Stable around 8 min average

*Updated after each plan completion*
| Phase 02 P02 | 6 min | 2 tasks | 7 files |
| Phase 02 P03 | 7 min | 2 tasks | 9 files |
| Phase 02 P04 | 8 min | 2 tasks | 13 files |
| Phase 02 P05 | 12 min | 3 tasks | 10 files |
| Phase 03 P01 | 8 min | 2 tasks | 11 files |
| Phase 03 P02 | 2 min | 2 tasks | 9 files |
| Phase 03.1 P01 | 2 min | 2 tasks | 3 files |
| Phase 03.1 P02 | 5 min | 2 tasks | 7 files |
| Phase 01 P01 | 9 min | 3 tasks | 3 files |
| Phase 01-deploy-on-railway-as-dev-server P02 | 2 min | 3 tasks | 2 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 1]: Deployed to Railway as dev server — live URL: https://folio-insights-production.up.railway.app (single service, Dockerfile builder, /health healthcheck)
- [Phase 1]: Whitelisted output/default and output/test1 in .gitignore so bundled corpora ship in the Railway build context (future generated output stays gitignored)

- [Roadmap]: Extend folio-enrich via bridge adapter, not modify its internals
- [Roadmap]: 3-phase structure following pipeline data dependencies (Extract -> Task Tree -> OWL)
- [Roadmap]: Phase 1 includes full extraction pipeline end-to-end (ingestion through quality output)
- [01-01]: Used importlib for folio-mapper bridge to avoid sys.path namespace conflict with folio-enrich's app package
- [01-01]: Added local markdown element parser to supplement folio-enrich's MarkdownIngestor which strips headings without returning structural elements
- [01-01]: folio-python added as direct dependency for FolioService singleton access
- [01-02]: Tier 1 structural heuristics handle headings (1.0), list items (0.9), paragraphs (0.7), transition words (0.8)
- [01-02]: Tier 2 semantic segmentation uses all-MiniLM-L6-v2 with cosine similarity threshold 0.3
- [01-02]: FourPathReconciler wraps base Reconciler unmodified; semantic +0.1 boost, heading +0.05 boost
- [01-02]: HeadingContextExtractor proximity weights: immediate=1.0, parent=0.7, chapter=0.4
- [01-02]: Near dedup at cosine 0.85 matches folio-enrich EMBEDDING_AUTO_RESOLVE_THRESHOLD
- [01-03]: PipelineCheckpoint uses static methods (not Pydantic model) for simpler save/load API
- [01-03]: Three separate JSON output files: extraction.json, review.json, proposed_classes.json for different consumers
- [01-03]: CLI uses local imports for lazy loading to avoid heavy bridge deps on --help
- [Phase 01-04]: FastAPI with aiosqlite for async SQLite review persistence (no ORM, direct SQL)
- [Phase 01-04]: SvelteKit adapter-static for SPA mode served by FastAPI StaticFiles
- [Phase 01-04]: Keyboard shortcuts dispatched globally with focus-context awareness (tree vs detail vs editor)
- [01.1-01]: Corpus metadata stored as corpus-meta.json files per directory (not SQLite), matching existing JSON pattern
- [01.1-01]: Lazy import of _output_dir from api.main in route modules to avoid circular imports
- [01.1-01]: Upload validates all file extensions upfront before processing any, rejecting batch with 400
- [01.1-01]: ZIP extraction writes to sources dir directly, skipping __MACOSX entries and directories
- [01.1-03]: ConfirmDialog uses {@html} for message to support bold corpus names in delete confirmation
- [01.1-03]: Focus trap in ConfirmDialog manual (Tab/Shift+Tab interception), no external dependency
- [01.1-03]: Task 1 already committed by prior 01.1-01 execution -- verified and reused
- [01.1-02]: JobManager keyed by corpus_id (one job file per corpus) matching folio-enrich disk-based pattern
- [01.1-02]: Pipeline runner iterates orchestrator._stages directly to inject progress callbacks between stages
- [01.1-02]: SSE generator polls job file every 0.5s with typed events (status, activity, complete, error)
- [01.1-02]: Atomic writes use asyncio.to_thread() wrapping sync tempfile+os.replace to avoid blocking event loop
- [01.1-04]: Processing store uses module-level EventSource with startProcessingStream/closeStream lifecycle functions
- [01.1-04]: UploadZone supports file picker and folder upload via separate hidden inputs (webkitdirectory)
- [01.1-04]: FileList uses text badges for format display rather than SVG icons
- [01.1-04]: ProgressDisplay derives stage states from currentStage position in ordered STAGES array
- [01.1-04]: Upload page renders four conditional states: no corpus, idle, processing, complete
- [01.1-04]: Auto-navigation uses $effect watching processingStatus + 1.5s setTimeout + goto()
- [02-01]: DiscoveryStage ABC mirrors InsightsPipelineStage but uses DiscoveryJob to keep pipelines independent
- [02-01]: Heading paths with < 2 knowledge units filtered as too sparse for task candidates
- [02-01]: FolioMappingStage marks unmapped candidates as proposed_siblings in job metadata
- [02-01]: ContentClusteringStage skips clusters with > 70% overlap with existing heading candidates
- [02-01]: LLM labeling gracefully degrades to word-based fallback when LLMBridge unavailable
- [02-01]: SentenceTransformer model loaded as lazy singleton to avoid repeated initialization
- [02-02]: HierarchyConstructionStage uses regex heuristic (not LLM) for jurisdiction sensitivity detection
- [02-02]: Orphan units assigned by embedding similarity to task centroids from linked unit texts
- [02-02]: CrossSourceMergingStage requires different source_file for embedding merge to avoid same-file false merges
- [02-02]: ContradictionDetector lazy-loads NLI model on first use to avoid heavy imports at startup
- [02-02]: Discovery checkpoints stored in discovery_checkpoints/ dir separate from extraction checkpoints/
- [02-02]: CLI discover command checks for review.db existence for optional decision persistence
- [02-03]: Discovery jobs use {corpus_id}_discovery key in same JobManager to coexist with extraction jobs
- [02-03]: Task tree built from SQLite queries (task_decisions + task_unit_links) rather than reading JSON files
- [02-03]: Bulk approve by confidence reads task_tree.json for confidence scores not stored in SQLite
- [02-03]: Hierarchy merge operation uses UPDATE OR IGNORE for unit links then deletes conflicting duplicates
- [02-03]: HTML export uses inline dark-theme CSS matching app.css variables for consistent visual identity
- [02-04]: SVG flag icons use child <title> elements to comply with Svelte 5 strict SVG typing
- [02-04]: TaskTree uses useFlatRendering and virtualScroll for large tree performance
- [02-04]: DiscoveryEvidence renders placeholder signal sections ready for future evidence API endpoint
- [02-04]: NavTabs extended to 3 tabs (Upload, Tasks, Review) matching sequential workflow
- [02-05]: SSR disabled for /tasks page because @keenmate/svelte-treeview references browser APIs at module level
- [02-05]: DiscoverButton follows ProcessButton 4-state lifecycle for consistency across upload workflow
- [02-05]: Dashboard toggle placed in header-right as grid icon matching compact header action pattern
- [02-05]: Keyboard shortcuts organized in REVIEW and TASK OPERATIONS sections for clarity
- [03-01]: Reimplemented folio-python IRI algorithm standalone to avoid 10s ontology download on every export
- [03-01]: Advice text aggregated as fi: annotation properties on task classes per CONTEXT.md single-file architecture
- [03-01]: Entity-level changelog diffing (compare IRI sets) instead of full triple-level graph subtraction
- [03-01]: Custom compact JSON-LD chunks for RAG instead of rdflib expanded form (3x smaller)
- [03-01]: rdflib serializes OWL as rdf:Description (valid RDF/XML) not owl:Ontology shorthand
- [03-01]: Namespace pre-binding pattern: all g.bind() before any g.add() to prevent ns1: artifacts
- [Phase 03]: CLI export uses sync sqlite3 for synchronous Click context; async methods via asyncio.run()
- [Phase 03]: ExportDialog uses 4-state machine (idle/exporting/complete/error) matching existing dialog patterns
- [Phase 03]: Bundle endpoint builds ZIP in-memory using Python zipfile for single-request download
- [Phase 03.1]: triggerExport uses direct fetch for ZIP binary responses, not request<T>() helper
- [Phase 03.1]: Recursive tree traversal required for nested TaskTreeNode trees (hasApprovedInTree, collectTasks)
- [Phase 03.1]: CLI serve uses lazy import of api.main.serve matching existing CLI pattern
- [Phase 03.1]: heading_analysis imports _PROXIMITY_WEIGHTS from heading_context eliminating duplicated constant
- [Phase 03.1]: Deduplicator standalone model documented as intentional design choice
- [Phase 01-01]: Used npm (not pnpm) for viewer build — lockfile is package-lock.json
- [Phase 01-01]: Belt-and-suspenders uv pip install of fastapi + uvicorn[standard] + python-multipart on top of project install — pyproject.toml does not declare them as direct deps
- [Phase 01-01]: Bundled output/ (3.8 MB) into image rather than Railway volume — simplest dev path per CONTEXT.md
- [Phase 01-01]: Image size 8.67 GB (vs 2.5 GB soft target) dominated by torch + CUDA libs pulled by sentence-transformers; not blocking Railway deploy, CPU-only torch deferred
- [Phase 01-02]: Replaced stale 'localhost:8700' port reference in client.ts docstring with neutral vite.config.ts reference — audit grep flags literal port numbers even in comments
- [Phase 01-02]: railway.toml omits startCommand — Dockerfile CMD expands ${PORT:-8000} and adding one here would bypass that substitution
- [Phase 01-02]: healthcheckTimeout = 120s to accommodate heavy image boot (torch + sentence-transformers); restartPolicyMaxRetries = 3 to surface crash loops as deploy failures

### Roadmap Evolution

- Phase 1 added: Deploy on Railway as Dev server (2026-04-12) — first phase of post-v1.0 work; numbering restarted after v1.0 archive

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1]: Gold-standard validation set (50-100 annotated boundaries) requires manual annotation of source material
- [Phase 1]: LLM provider selection for extraction tasks needs benchmarking against advocacy text

## Session Continuity

Last session: 2026-04-13T02:07:16.100Z
Stopped at: Completed 01-02-PLAN.md
Resume file: None
