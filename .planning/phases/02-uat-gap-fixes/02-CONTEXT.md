# Phase 2: UAT Gap Fixes — Context

**Gathered:** 2026-04-19
**Status:** Ready for planning
**Source:** Comprehensive UAT sweep (`.planning/phases/COMPREHENSIVE-UAT.md`)

<domain>
## Phase Boundary

Close the 5 issues surfaced by the comprehensive UAT against all v1.0 deliverables plus the Phase 01 Railway deploy. Each issue is sourced from a specific test or cluster of tests in `.planning/phases/COMPREHENSIVE-UAT.md` and has:

- a fixed root artifact set (1–3 files per issue)
- a clear reproduction recipe
- an expected post-fix behavior observable via curl or screenshot

Out of scope: new features, unrelated refactors, code reorganization, test coverage expansion beyond what's needed to lock each fix.
</domain>

<decisions>
## Implementation Decisions

### Issue Inventory (locked from UAT)

- **I-1 · Empty FOLIO IRIs on LLM-path tags** — major. Every `folio_tags[].iri` is `""` for LLM-extracted concepts, even for core FOLIO labels (`cross-examine`, `expert witness`, `bias`). Root area: `src/folio_insights/pipeline/stages/folio_tagger.py` + `src/folio_insights/services/bridge/reconciliation_bridge.py`. Fix must either wire the LLM-path through the FOLIO label→IRI resolver OR route unresolved labels to proposed-classes; `proposed_classes.json` is currently empty so both paths need verification.
- **I-2 · Bundle export returns 422 not 404 on empty corpus** — minor. `POST /api/v1/corpus/{id}/export/bundle` returns 422 with empty body; sibling endpoints (owl/ttl/jsonld/validation) return 404 with `{"detail":"No discovered tasks found"}`. Fix: route in `api/routes/export.py` must parity with the other export routes.
- **I-3 · Vite proxy hardcoded to :8700** — blocker for viewer dev. `viewer/vite.config.ts` has `server.proxy['/api'].target = 'http://localhost:8700'` but API runs on 9925. Fix: change target to `http://localhost:9925` OR make it env-driven (`VITE_API_URL` default 9925). Must comply with `feedback_api-client-proxy.md` — relative URLs, no hardcoded ports in client code.
- **I-4 · No approved-task fixture for export e2e** — major. All bundled `review.db` files have `task_decisions` count 0. CLI export refuses with "No tasks found to export." Fix: ship a seed script OR commit a minimal `output/demo/` with ≥1 approved task so OWL/TTL/JSON-LD/HTML/CHANGELOG outputs can be validated end-to-end. Code correctness covered by 45 unit tests; missing layer is real-artifact validation.
- **I-5 · Railway test1 shows `processing_status=failed`** — minor. Local returns `completed`; Railway live deploy returns `failed` for the same bundled corpus. Hypothesis: bundled image state diverged OR first-boot reprocess failed on Railway dev-tier memory. Fix: clean up bundled processing state OR reset status at image-build time.

### Fix Strategy

- **Sequencing:** I-3 first (unblocks viewer dev mode for manual re-testing), then I-1/I-2/I-4 (backend pipeline + fixtures), then I-5 (deployment state cleanup that should follow I-4 if seed data changes).
- **No regressions:** pytest (197 tests) must remain at 197/197 after each fix. New tests added for I-1 and I-2 specifically.
- **Viewer testing:** after I-3, re-run the 12 blocked viewer tests (24–28, 30, 33–36) in a follow-up UAT — NOT inside this phase.

### Railway Safety

- I-5 fix must not break the Phase 01 Railway deploy live URL. Any change to bundled `output/` or Dockerfile must be verified locally (`docker build && docker run`) before push to master.
- Do NOT remove `output/default/` or `output/test1/` corpora — they're the baseline Railway fixture set. I-4 adds a NEW `output/demo/` alongside them.

### Out of Scope (explicitly deferred)

- Re-run the comprehensive UAT (separate `/gsd-verify-work` invocation after this phase)
- Gold-standard validation set for boundary detection (Phase 1 blocker — separate effort)
- LLM provider benchmarking (Phase 1 blocker — separate effort)
- UI polish / new features
- CI/CD setup beyond Railway autodeploy

### Claude's Discretion

- Exact file split per PLAN.md (planner decides: one-plan-per-issue vs grouped-by-area)
- Test framework for new regression tests (match existing pytest pattern under `tests/`)
- Whether I-1 fix uses `FolioService.resolve()` directly in `folio_tagger.py` or adds a reconciler hook
- Whether I-3 uses a hardcoded 9925 (simplest) or introduces `VITE_API_URL` env var (more flexible)
- Whether I-4 ships a Python seed script (`scripts/seed_demo_corpus.py`) or commits pre-built artifacts
- Whether I-5 fix is a Dockerfile `RUN` step that resets corpus-meta.json or a runtime sanity-check at boot

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### UAT source
- `.planning/phases/COMPREHENSIVE-UAT.md` — Canonical issue log; Issues Log + Gaps YAML block authoritative

### Auto-memory rules (user global)
- `/home/damienriehl/.claude/projects/-home-damienriehl-Coding-Projects-folio-insights/memory/feedback_api-client-proxy.md` — Proxy/URL rule; MUST NOT hardcode localhost ports in client code
- `/home/damienriehl/.claude/projects/-home-damienriehl-Coding-Projects-folio-insights/memory/feedback_await-async-ui.md` — Await async calls before closing dialogs

### Prior phase decisions (load for context continuity)
- `.planning/STATE.md` — Accumulated decisions, especially [01-01] through [01-03] recent entries
- `.planning/phases/01-deploy-on-railway-as-dev-server/01-CONTEXT.md` — Phase 01 Railway decisions (Dockerfile strategy, bundled output/)
- `.planning/phases/01-knowledge-extraction-pipeline/01-04-PLAN.md` — LLM-path extraction flow (I-1 root area)
- `.planning/phases/03-ontology-output-and-delivery/` — Export pipeline (I-2 root area)
- `.planning/phases/03.1-export-ui-integration-fixes/` — Export UI + CLI conventions (I-2 parity target)

### Source files (per issue)
- I-1: `src/folio_insights/pipeline/stages/folio_tagger.py`, `src/folio_insights/services/bridge/reconciliation_bridge.py`
- I-2: `src/folio_insights/api/routes/export.py` (plus sibling routes for parity check)
- I-3: `viewer/vite.config.ts`
- I-4: `output/default/`, `output/test1/`, `src/folio_insights/cli.py` export command
- I-5: `Dockerfile`, `output/test1/corpus-meta.json`

</canonical_refs>

<specifics>
## Specific Ideas

### I-1 regression test shape
- Create fixture corpus containing the sentence "Counsel used cross-examination to impeach the expert witness for bias."
- After extraction, assert every `folio_tags[].iri` is non-empty AND resolves to a FOLIO IRI pattern (`https://folio.openlegalstandard.org/...`).
- Test should fail on current code, pass after fix.

### I-2 regression test shape
- `pytest` against `POST /api/v1/corpus/{id}/export/bundle` with an empty corpus.
- Assert status 404 AND `response.json()["detail"]` matches sibling export endpoints exactly.

### I-3 verification
- Grep-level acceptance: `grep "localhost:8700" viewer/vite.config.ts` exits 1 (no match).
- Runtime: viewer at :9926 loads corpus list on bootup.
- Future-proofing: add a comment in vite.config.ts referencing the auto-memory rule so it's not reintroduced.

### I-4 seed data
- Minimum viable: 1 corpus with ≥1 extracted unit, ≥1 approved task_decision, ≥1 linked task_unit_link.
- CLI command `folio-insights export demo --format owl,ttl,jsonld,html` must produce non-empty artifacts.
- Commit the review.db + extraction.json under `output/demo/` in the same way `output/default/` and `output/test1/` are tracked.

### I-5 first-boot hypothesis
- Likely cause: Railway's dev-tier memory (512MB) is insufficient for torch + sentence-transformers bootstrapping AND cold-boot processing at the same time. Corpora marked `failed` because the background task OOM'd on first hit.
- Candidate fix: mark bundled corpora as `completed` at image-build time (they're pre-processed); OR strip `processing_status` from bundled `corpus-meta.json` so UI doesn't show it as failed.

</specifics>

<deferred>
## Deferred Ideas

- Adding a post-Phase-02 full UAT re-run — belongs in `/gsd-verify-work 2` after execution, not in this phase scope
- Observability / logging improvements discovered during fixes
- Migrating vite config to env-var pattern app-wide (only change the proxy target here)
- LLM provider benchmarking (orthogonal, documented as Phase 1 blocker)

</deferred>

---

*Phase: 02-uat-gap-fixes*
*Context gathered: 2026-04-19 via UAT-derived synthesis*
