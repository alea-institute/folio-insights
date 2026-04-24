---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: milestone
status: awaiting_human_verify
stopped_at: "Phase 01 executor complete 2026-04-24"
last_updated: "2026-04-24T19:00:00.000Z"
last_activity: 2026-04-24 -- Phase 01 executor complete; awaiting /gsd-verify-work
progress:
  total_phases: 2
  completed_phases: 1
  total_plans: 14
  completed_plans: 14
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-20 after v1.1)

**Core value:** Every piece of actionable legal advocacy knowledge must be discoverable by task, mapped to FOLIO concepts, and structured for practitioners, AI systems, and developers.
**Current focus:** Phase 01 — polysemy-distinguo-spike

## Current Position

Milestone: v2.0 shards-as-axioms — STARTED 2026-04-20, INITIALIZED 2026-04-22
Phase: 01 (polysemy-distinguo-spike) — AWAITING HUMAN VERIFY
Plan: 6 of 6
Status: All 6 plans executed; 49/49 tests pass; verifier returned human_needed
Last activity: 2026-04-24 -- Phase 01 executor complete; awaiting /gsd-verify-work

Progress: [██████████] 100%

Previous milestone: v1.1 — SHIPPED 2026-04-20 — https://folio-insights-production.up.railway.app

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
| Phase 0 P1 | 4 | 2 tasks | 8 files |
| Phase 00 P02 | 5 | 1 tasks | 7 files |
| Phase 0 P4 | 13 | 3 tasks | 7 files |
| Phase 00-foundations-hard-gate P03 | 32min | 2 tasks | 24 files |
| Phase 0 P5 | 27 | 3 tasks | 11 files |
| Phase 00-foundations-hard-gate P6 | 17min | 2 tasks | 5 files |
| Phase 00-foundations-hard-gate P07 | 8min | 4 tasks | 17 files |
| Phase Phase 00-foundations-hard-gate P08 P8 | 20min | 3 tasks tasks | 6 files files |

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
- [00-01]: git mv preserves blame for PHILOSOPHY.md (D-18 resolved; file was at repo root, not docs/)
- [00-01]: pyproject.toml requires-python tightened to >=3.11,<3.13 per Pitfall 8 (instructor 3.13 regression)
- [00-01]: owlready2 ships no __version__; use importlib.metadata for version introspection
- [00-01]: Session-scoped bench_store fixture (pyoxigraph Store + bulk_load + optimize) reused across Gate 2 assertions
- [00-02]: rdf:Statement reification used instead of RDF 1.2 triple-term syntax for annotations — pyoxigraph N-Quads dump is Turtle-only for pipe syntax (Pitfall 1 compliant)
- [00-02]: In-memory pyoxigraph Store (path=None) for generation — avoids RocksDB mtime variance in ancillary files
- [00-02]: Module-bottom import of bench subgroup in cli.py keeps pyoxigraph off the hot path for non-bench CLI commands
- [00-02]: fixtures/bench.nq committed directly (235MB, <300MB plan cap); git-lfs migrate deferred until first GitHub push
- [00-04-D1]: A1 CONFIRMED — pyoxigraph 0.5.7 ships musllinux_1_2_x86_64 wheel; Alpine base for worker (no 75MB slim-fallback tax)
- [00-04-D2]: Worker install scoped to reasoning subset (pyoxigraph/owlready2/rdflib/oxrdflib) — Rule 2 deviation avoids torch pulling 2GB into worker image
- [00-04-D3]: 3-stage Dockerfile.worker (jre-builder / deps-builder / runtime) keeps gcc/g++/musl-dev out of final image even though owlready2 ships sdist-only
- [00-04-D4]: Base image digests pinned to manifest-list sha256 (not per-arch); regenerate quarterly via docker buildx imagetools inspect
- 00-03: gold queries target rdf:Statement reification (Plan 02 P2-D2); annotation-pipe preserved in SPARQL # comments for file-discipline; D-04 STRICT PASSED on 1M corpus — no Fuseki pivot
- 00-03: SEC-01 SSRF mitigation at PyoxigraphStore wrapper (ServiceClauseBlocked) — pyoxigraph 0.5.x TCP-connect timeout variance 5-135s against 169.254.169.254 makes network-timeout defence unreliable
- 00-03: Q11 rewritten nested SELECT + outer FILTER because pyoxigraph 0.5.x HAVING drops rows against xsd:integer bound variable
- 00-05-D1: ci/ package rename (local dagger/ would shadow dagger-io SDK via sys.path[0])
- 00-05-D2: worker reasoning-subset lockfile (requirements.worker.lock) — Gate 5 step 5 demands hash-pinning for both tiers
- 00-05-D3: opentelemetry-exporter-otlp-proto-grpc required at runtime by dagger-io 0.20.x (not pulled transitively)
- 00-05: Gate 5 Mode 1 VERDICT = PASS — local Dagger pipeline produces bit-identical digests across back-to-back runs (web + worker)
- 00-06: Gate 2 verdict = PASS — worst-case P95 = 116.95 ms on q13_confidence_histogram (>4x headroom over 500ms hard target); no tuning pass required, no pivot to Fuseki
- 00-06: Plan template named-graph IRIs (urn:folio:*, tbox, governance) corrected to real bench.nq layout (corpus/advocacy, corpus/fre, corpus/restatement) — unknown IRIs in named_graphs= silently return zero rows
- 00-06: pytest-benchmark 5.2.3 Stats has no percentile() method; P95 computed via nearest-rank into stats.sorted_data
- 00-07-D1: HermitHarness catches OwlReadyInconsistentOntologyError and records consistent=False with sentinel class <ontology-inconsistent> (owlready2 raises on whole-ontology unsatisfiability; valid D-11 result not reasoner crash)
- 00-07-D2: HermitHarness.__init__ writes owlready2.JAVA_MEMORY at construction (process-global) — subprocess spawn picks it up regardless of which harness instance .reason()s
- 00-07-D3: FastAPI stubs return canned JSON so Gate 4 measures SSR stack overhead not pyoxigraph query cost (Phase 15 wires real queries behind same URL contract)
- 00-07-D4: @polka/compression custom-server wiring deferred — dep installed, activation requires adapter-node server.js wrapper; Plan 08 flags as follow-up only if cache-control misses 200ms target
- 00-07-D5: Gate 3 verdict = PASS (fi-worker:smoke = 74.6 MB via docker inspect {{.Size}}, 15% of 500 MB target, 425 MB headroom); docker image ls DISK USAGE (243 MB) includes shared-layer accounting and is NOT the Gate 3 quantity
- 00-07-D6: Gate 4 DEFERRED to verify session (hyperfine not on Plan 07 host); D-11 full-1M DEFERRED pending .owl fixture + 1-2 day measurement window (D-12 open-ended timebox permits)
- 00-08-D1: Verdict = keep=pyoxigraph — all ship-critical gates (1/2/3/5 Mode 1) PASS with margin; Gates 4 and D-11 deferred but harness-ready and NOT pivot-triggers per OQ4 numeric policy
- 00-08-D2: OQ4 resolved — pivot requires ONE of (a) Gate 1 STRICT fail, (b) Gate 2 warm P95 > 800ms post-tune, (c) Gate 5 Mode 1 determinism fail; Gates 3/4/D-11 trigger escape-hatches, NOT pivot
- 00-08-D3: DID signature DEFERRED to Phase 6+ per D-17 chicken-and-egg; 4-step backfill procedure in DECISION.md Signature Deferral section with T-00-39 substitute-then-sign mitigation (verify body matches git-sha before signing)
- 00-08-D4: Fuseki scaffold (config.ttl + README + .gitkeep) retained on keep verdict per T-00-40 mitigation + v2.1 re-evaluation capacity; README banner reads 'scaffold not required; retained for v2.1 re-evaluation'
- 00-08-D5: BRANCH-GUIDANCE.md as separate @-ref doc at stable path; downstream PLAN.md files @-import instead of re-parsing DECISION.md; drift between them is a bug

### Roadmap Evolution

- Phase 1 added: Deploy on Railway as Dev server (2026-04-12) — first phase of post-v1.0 work; numbering restarted after v1.0 archive

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1]: Gold-standard validation set (50-100 annotated boundaries) requires manual annotation of source material
- [Phase 1]: LLM provider selection for extraction tasks needs benchmarking against advocacy text

## Deferred Items

Items acknowledged and deferred at v1.1 milestone close on 2026-04-20. All are v1.0-inherited (pre-date v1.1 scope); v1.1's own work — Phase 01 deploy-on-railway (3/3 plans) + Phase 02 uat-gap-fixes (5/5 plans) — is fully verified via `.planning/v1.1-MILESTONE-AUDIT.md`.

| Category | Item | Status |
|----------|------|--------|
| debug | corpus-processing-no-extraction | awaiting_human_verify |
| debug | create-corpus-silent-fail | awaiting_human_verify |
| debug | llm-api-config | awaiting_human_verify |
| uat_gap | Phase 03 03-HUMAN-UAT.md (4 pending scenarios) | partial |
| verification_gap | Phase 01 01-VERIFICATION.md | human_needed |
| verification_gap | Phase 01.1 01.1-VERIFICATION.md | human_needed |
| verification_gap | Phase 03 03-VERIFICATION.md | human_needed |

## Session Continuity

Last session: 2026-04-24T19:00:00.000Z
Stopped at: Phase 01 executor complete — awaiting /gsd-verify-work
Resume file: .planning/phases/01-polysemy-distinguo-spike/01-VERIFICATION.md
Resume action: /gsd-verify-work 1 — live keystroke-gate UX check; FP labeling reconciliation (2 draft labels + 2 rationale retrofits); pick Option A/B/C from 01-SUMMARY.md §4 threshold policy

**Planned Phase:** 01 (polysemy-distinguo-spike) — 6 plans — 2026-04-24T14:34:36.502Z
**Executed Phase:** 01 (polysemy-distinguo-spike) — 6/6 plans complete; 49/49 tests pass; Wilson FP lower bound 2.53% (gate ≤10%); verifier: human_needed — 2026-04-24T19:00:00.000Z
