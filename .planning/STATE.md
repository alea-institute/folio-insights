---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: milestone
status: dormant
stopped_at: Phase 8 complete; Phase 9 never opened
last_updated: "2026-07-24T00:00:00.000Z"
last_activity: 2026-05-31 -- Phase 08 completed (dormant since)
progress:
  total_phases: 24
  completed_phases: 10
  total_plans: 41
  completed_plans: 41
  percent: 42
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-24 after Phase 02)

**Core value:** Every piece of actionable legal advocacy knowledge must be discoverable by task, mapped to FOLIO concepts, and structured for practitioners, AI systems, and developers.
**Current focus:** Phase 08 — folio-v2-vocab-mini-bfo-spine-7

## Current Position

Milestone: v2.0 shards-as-axioms — STARTED 2026-04-20, INITIALIZED 2026-04-22
Phase: 08 (folio-v2-vocab-mini-bfo-spine-7) — **COMPLETE** (all 4 plans have SUMMARYs;
`ROADMAP.md` marks it "completed 2026-05-31")
Plan: 4 of 4
Status: **DORMANT since 2026-05-31** — awaiting an explicit resume-or-archive decision
Last activity: 2026-05-31 -- Phase 08 completed

Progress: 10 of 24 phases (Phases 0–8 + 3.5). Next unstarted phase: **09 — Seven Design
Principles (§8)**, followed by Phases 10–20 (pipeline refactor, SHACL hybrid, observability,
Oxigraph storage, private corpora, UI design contract, review UI, public SPARQL endpoint,
testing consolidation, community artifacts, corpus fork, security audit, release cut).

Previous milestone: v1.1 — SHIPPED 2026-04-20 — https://folio-insights-production.up.railway.app

## ⚠ Reconciliation — 2026-07-24 (housekeeping sweep)

This file had drifted and was overstating both progress and activity:

- It said "Phase 08 EXECUTING, Plan 1 of 4" and "Progress 100%". Phase 08 in fact
  **finished**: all four plans (08-01…08-04) have SUMMARY files and `ROADMAP.md` lists
  Phase 8 as completed 2026-05-31. Corrected above.
- **Nothing has moved on this milestone in ~8 weeks.** The last v2.0 commit is
  2026-05-31; every commit since then belongs to a different track — the FOLIO
  tagger / judge pipeline and the `folio-resolve` migration (`feat/wire-decompose-tagger`,
  active through 2026-07-24). The repo is busy; *this milestone* is not.
- **14 phases remain** (09–20), including the Oxigraph storage layer, the 7-surface review
  UI, the public SPARQL endpoint, a pre-release security audit and the release cut. That is
  a multi-week commitment, not a resumable afternoon.

Standing policy is GSD-for-in-flight-plans-only, CE for new work — so this milestone sits
exactly on the seam and needs an owner decision rather than another silent quarter:
**resume Phase 09 under GSD, archive v2.0 as partially-shipped and re-plan the wanted
scope under CE, or explicitly park it with a review date.** Posted as an ask
(`briefs/qa/housekeeping-2026-07-24.json`). Until that is answered, treat v2.0 as dormant,
not in-flight.

## Performance Metrics

**Velocity:**

- Total plans completed: 44
- Average duration: 9.4 min
- Total execution time: 2.3 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-knowledge-extraction-pipeline | 4/4 | 71 min | 17.8 min |
| 01.1-upload-processing-ui | 4/4 | 22 min | 5.5 min |
| 02-task-hierarchy-discovery | 5/5 | 37 min | 7.4 min |
| 03-ontology-output-and-delivery | 1/2 | 8 min | 8.0 min |
| 01 | 7 | - | - |
| 02 | 3 | - | - |
| 03 | 2 | - | - |
| 03.5 | 3 | - | - |
| 04 | 2 | - | - |
| 05 | 3 | - | - |
| 6 | 3 | - | - |
| 07 | 7 | - | - |

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
| Phase 05 P05-01 | 4 min | 3 tasks | 5 files |
| Phase 05 P05-02 | 6 min | 2 tasks | 9 files |
| Phase 05 P05-03 | 2 min | 2 tasks | 4 files |

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
- [Phase 03.5]: Railway dev server RESTORED — live at https://folio-insights-production.up.railway.app (502 → healthy). Root cause: nested `[services.*]` railway.toml silently ignored → Railway built the stale v1.1 `/Dockerfile`, whose `COPY output/` failed against the output-excluding `.dockerignore`.
- [Phase 03.5]: railway.toml collapsed to a FLAT web-only config ([build] Dockerfile.web + [deploy] /health) so config-as-code engages; worker left uncreated (web-only locked; Phase 10/20 own worker+GA)
- [Phase 03.5]: ci/railway.py corrected for CLI v4.x — image deploy `railway add -i` (not the removed `up --image`); env=-only token preserved
- [Phase 03.5]: owlready2 (JVM reasoner) moved from core deps to a `reasoning` extra — the JVM-free web image never imports it and its sdist wheel build failed on Railway's builder; worker installs it explicitly so unaffected
- [Phase 03.5]: viewer reverted from adapter-node (SSR, never deployable on one port) to adapter-static SPA served by FastAPI StaticFiles + SPAStaticFiles index.html fallback; 3 SSR routes (shards/timeline/polysemy [id]) converted to client loads; full SSR + Gate 4 (QUALITY-04) deferred to Phase 20
- [Phase 03.5]: Dockerfile.web fixes — COPY src/ before `uv pip install .` (empty-package bug), default SOURCE_DATE_EPOCH=0 (hatchling int('') crash on Railway), bundle output/{default,demo,test1} via .dockerignore re-include
- [Phase 03.5]: LLM keys are Bring-Your-Own-Key — no shared ANTHROPIC_API_KEY baked into the dev server (per operator decision); LLM_PROVIDER/LLM_MODEL set as non-secret defaults
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
- [Phase 05-01]: ContentEdit enriched to PRD §6.4 shape (dotted field_path, required rationale, AttestedSignature stub slot); signature is unsigned placeholder — real ed25519/JCS deferred to Phase 6 (D-04, D-05)
- [Phase 05-01]: Forward-only @model_validator on ShardEnvelope uses strict < (equal edited_at allowed, ties by append order); only D-08b monotonicity lives here, D-08a immutability is structural (frozen + IMMUTABLE_FIELD_PATHS)
- [Phase 05-01]: add_edit kept as thin SYNC wrapper for flat top-level fields; dotted nested paths (triple.object) are the Plan 02 set_field/edit_shard_content path (RESEARCH OQ2)
- [Phase 05-02]: ShardStore is a runtime_checkable typing.Protocol over an in-memory dict (D-02 seam); stdlib + Pydantic only, no aiosqlite/pyoxigraph — Phase 13 fills the persistent backend behind the identical async get/put interface
- [Phase 05-02]: IMMUTABLE_FIELD_PATHS is a 10-member frozenset gate raising BEFORE any mutation (6 frozen identity + triple.subject/.predicate + content_edits/signatures); triple.object stays editable for re-parenting (D-04, D-06)
- [Phase 05-02]: get_shard_at reverse-replays on model_copy(deep=True) with strict > undo (exact-t ties kept); returns None for unknown IRI and t<extracted_at (D-09); validate_shard re-runs full validation post-edit since validate_assignment is OFF (V5)
- [Phase 05]: [05-03] SHACL forward-only guard (content_edit_shape.ttl + validate_content_edit_shape) lives in revision/, not shards/, keeping the dep-leak guard green — rdflib/pyshacl imports are forbidden only under shards/; revision/ is outside that boundary (exit criterion 2 satisfied literally)
- [Phase 05]: [05-03] SHACL enforces ONLY the forward-only half; immutability of past entries (D-08a) is carried by ContentEdit frozen + IMMUTABLE_FIELD_PATHS gate — SHACL is stateless over a single snapshot and cannot detect deletions (RESEARCH L115-124); documented division, not a gap

### Roadmap Evolution

- Phase 1 added: Deploy on Railway as Dev server (2026-04-12) — first phase of post-v1.0 work; numbering restarted after v1.0 archive
- Phase 3.5 inserted after Phase 3: Railway dev server restore and auto-deploy (2026-05-22) — parallel infra track, off critical path, non-blocking; not urgent (decimal-numbered insert, no renumber of 4–20)

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

Last session: 2026-05-31T15:46:30.304Z
Stopped at: Phase 8 context gathered
Resume file: .planning/phases/08-folio-v2-vocab-mini-bfo-spine-7/08-CONTEXT.md
Resume action: /gsd-discuss-phase 3 (Shard Subtypes §6.2) — or /gsd-plan-phase 3 --skip-research if you want to go direct

**Planned Phase:** 03 (Shard Subtypes (§6.2)) — 2 plans — 2026-04-25T15:19:49.181Z
**Executed Phase:** 02 (shard-envelope) — 3/3 plans complete; 47 shard tests + 96 combined with polysemy pass; hypothesis 1000/0/0 minting determinism — 2026-04-24T21:45:00.000Z
**Verified Phase:** 02 — UAT 12/12 pass (2026-04-24); /gsd-secure-phase 02 SECURED 25/25 threats (15 mitigated + 10 accepted across Phase 4/5/6/10/13 downstream dependencies)
**Next Phase:** 03 (Shard Subtypes) — depends on Phase 2; P1 critical path; REQ-IDs SHARD-02..SHARD-06 (5 subtypes: SimpleAssertion / DisputedProposition / ConflictingAuthorities / Gloss / Hypothesis)
