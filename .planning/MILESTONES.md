# Milestones

## v1.1 Railway Dev Deploy + UAT Gap Closure (Shipped: 2026-04-20)

**Phases completed:** 2 phases, 8 plans, ~17 tasks
**Git range:** since tag `v1.0` (2026-04-04); 31 commits on master (incl. docs + parallel-planning WIP)
**Known deferred items at close:** 7 v1.0-inherited (see STATE.md Deferred Items)
**Audit:** [v1.1-MILESTONE-AUDIT.md](milestones/v1.1-MILESTONE-AUDIT.md) — passed, 5/5 UAT reqs, 8/8 integration checks

**Key accomplishments:**

- Live Railway dev server at `https://folio-insights-production.up.railway.app` — single service, multi-stage Dockerfile (node:20-slim → python:3.11-slim), bundled SvelteKit viewer + FastAPI API + 3.8 MB extraction dataset, `/health` healthcheck, non-root runtime
- `railway.toml` config-as-code with DOCKERFILE builder + `/health` healthcheck (120s timeout) + restart-on-failure policy; frontend relative-URL audit (zero hardcoded dev ports in `viewer/src/`)
- **UAT I-3** (blocker): Vite proxy `8700 → 9925` — unblocks all viewer dev-mode UI testing
- **UAT I-2** (minor): Bundle export `422 → 404` parity with sibling owl/ttl/jsonld endpoints + 2 regression tests
- **UAT I-1** (major): LLM-path FOLIO IRI resolution at 0.6 threshold + `extraction_path="proposed_class"` fallback for unresolved labels + 4 regression tests
- **UAT I-4**: Deterministic `output/demo/` approved-task fixture (2 approved + 2 task_unit_links) + idempotent `scripts/seed_demo_corpus.py` — unblocks end-to-end export validation
- **UAT I-5** (minor): `.dockerignore` exclusion of `output/.jobs/` — bundled corpora now report `processing_status="completed"` on live Railway (verified post-deploy); Railway autodeploy reconnected mid-checkpoint
- pytest 197 → 203 passed (+6 regression tests, 0 failures)

---

## v1.0 MVP (Shipped: 2026-04-04)

**Phases completed:** 5 phases, 17 plans, 40 tasks

**Key accomplishments:**

- Greenfield folio-insights package with bridge adapters importing 27K+ FOLIO labels from folio-enrich, multi-format ingestion (14 extensions), and heading-hierarchy-aware structure parser
- Tiered boundary detection (structural/semantic/LLM), five-type knowledge classifier with novelty scoring, four-path FOLIO concept tagger with heading context, and cross-document deduplicator
- Confidence-gated output layer with 3-file JSON output, 7-stage pipeline orchestrator with checkpoint resume, and `folio-insights extract` batch CLI
- FastAPI + SvelteKit three-pane review viewer with FOLIO concept tree, keyboard-driven approve/reject/edit workflow, confidence filtering, source context display, and SQLite persistence
- Corpus CRUD API with file upload endpoint supporting 13 formats + ZIP extraction with path traversal protection
- Disk-based job manager with atomic writes, pipeline runner with stage-by-stage SSE progress updates, and CorpusRegistry SHA-256 dedup fix enabling re-processing skip
- SvelteKit routing with Upload/Review nav tabs, shared corpus store, API client extensions, CorpusSidebar with create/delete dialogs, and reusable ConfirmDialog component
- Drag-and-drop upload zone, file list with status indicators, SSE-driven progress display with 7 stage pills, collapsible activity log, and auto-navigation to review page on processing completion
- 5 Pydantic data models, 3 discovery pipeline stages (heading analysis, FOLIO mapping, content clustering), agglomerative clustering service, and Wave 0 test scaffolds for all 4 phase requirements
- Full 6-stage discovery pipeline with hierarchy construction, cross-source merging, two-phase NLI+LLM contradiction detection, decision-persistent orchestrator, and CLI discover command
- Complete backend API for task discovery with SSE progress, task CRUD, review workflow, contradiction resolution, hierarchy editing, source authority, and multi-format export
- Task hierarchy viewer with @keenmate/svelte-treeview DnD tree, grouped knowledge units, chip-based filters, side-by-side contradiction resolution, and three-pane /tasks page
- Complete Phase 2 frontend with TaskDashboard overlay, DiffView accept/reject, ManualTaskDialog, DiscoverButton with SSE progress on upload page, three-tab navigation, and extended keyboard shortcuts
- Core OWL serialization engine with rdflib graph builder, pyshacl validation, entity-level changelog diffing, and compact JSON-LD RAG chunks
- CLI export command, 5 REST API endpoints (OWL/TTL/JSONLD/validation/bundle), and ExportDialog UI with format selection and validation display
- Fixed three blocking export integration breaks: hasApprovedTasks guard (wrong status + flat check), triggerExport JSON parse error on ZIP binary, and TaskTreeNode type mismatch with phantom fields
- Working CLI serve command, imported constants replacing duplicates, documented deduplicator model choice, and 15 real tests replacing Wave-0 scaffolds

---
