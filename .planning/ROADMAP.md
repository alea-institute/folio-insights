# Roadmap: FOLIO Insights

## Milestones

- ✅ **v1.0 MVP** — Phases 1-3.1 (shipped 2026-04-04) — [Archive](milestones/v1.0-ROADMAP.md)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-3.1) — SHIPPED 2026-04-04</summary>

- [x] Phase 1: Knowledge Extraction Pipeline (4/4 plans) — completed 2026-03-17
- [x] Phase 1.1: Upload & Processing UI (4/4 plans) — completed 2026-03-18
- [x] Phase 2: Task Hierarchy Discovery (5/5 plans) — completed 2026-03-19
- [x] Phase 3: Ontology Output and Delivery (2/2 plans) — completed 2026-04-04
- [x] Phase 3.1: Export UI Integration Fixes & Tech Debt (2/2 plans) — completed 2026-04-04

</details>

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Knowledge Extraction Pipeline | v1.0 | 4/4 | Complete | 2026-03-17 |
| 1.1 Upload & Processing UI | v1.0 | 4/4 | Complete | 2026-03-18 |
| 2. Task Hierarchy Discovery | v1.0 | 5/5 | Complete | 2026-03-19 |
| 3. Ontology Output and Delivery | v1.0 | 2/2 | Complete | 2026-04-04 |
| 3.1 Export UI Integration Fixes | v1.0 | 2/2 | Complete | 2026-04-04 |

### Phase 1: Deploy on Railway as Dev server

**Goal:** Ship folio-insights as a single Railway dev-environment service mirroring the sibling folio-enrich and folio-mapper pattern — a live *.up.railway.app URL serving the SvelteKit viewer (bundled) and FastAPI API from one container, redeploying on git push to master, rendering data end-to-end from bundled output/.
**Requirements**: none (dev deployment — no formal REQ-IDs)
**Depends on:** Phase 0 (none in practice — v1.0 shipped)
**Plans:** 3 plans

Plans:
- [x] 01-01-PLAN.md — Multi-stage Dockerfile + .dockerignore + /health endpoint
- [x] 01-02-PLAN.md — railway.toml + frontend relative-URL audit + regression smoke test
- [x] 01-03-PLAN.md — User-driven Railway deploy + README section + STATE.md URL record

### Phase 2: UAT Gap Fixes

**Goal:** Close the 5 issues surfaced by the comprehensive UAT sweep so every user-observable deliverable shipped in v1.0 + the Railway deploy works end-to-end from viewer dev-mode through ontology export — specifically: resolve LLM-path FOLIO tags to canonical IRIs, fix vite proxy port mismatch, normalize bundle-export error contract, seed an approved-task demo corpus for export validation, and clean up the Railway `processing_status=failed` artifact.
**Requirements**: none (gap closure — sourced from COMPREHENSIVE-UAT.md)
**Depends on:** Phase 1 (Railway deploy — I-5 is a post-deploy cleanup item)
**Plans:** 5 plans

Plans:
- [x] 02-01-PLAN.md — I-3: Fix vite proxy target 8700 → 9925 (Wave 1) — completed 2026-04-19
- [x] 02-02-PLAN.md — I-2: Bundle export 422 → 404 parity + regression tests (Wave 1) — completed 2026-04-19
- [x] 02-03-PLAN.md — I-1: LLM-path FOLIO IRI resolution at 0.6 threshold + proposed_class routing (Wave 1) — completed 2026-04-19
- [x] 02-04-PLAN.md — I-4: Seed output/demo/ corpus fixture for export validation (Wave 1) — completed 2026-04-19
- [ ] 02-05-PLAN.md — I-5: Exclude output/.jobs/ from Docker context + Railway redeploy checkpoint (Wave 2)

**Source:** .planning/phases/COMPREHENSIVE-UAT.md (Issues I-1 through I-5)
