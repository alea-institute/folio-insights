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
- [ ] 01-02-PLAN.md — railway.toml + frontend relative-URL audit + regression smoke test
- [ ] 01-03-PLAN.md — User-driven Railway deploy + README section + STATE.md URL record
