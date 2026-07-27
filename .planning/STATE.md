---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: shards-as-axioms
status: parked
parked_at: 2026-07-26
parked_by: "Damien — cockpit ask housekeeping-2026-07-24, q4-folio-insights-v2 ('Park with an explicit review date')"
review_date: 2026-08-23
review_date_status: PROVISIONAL -- 4 weeks, set by Fable; awaiting Damien's confirmation
stopped_at: Phase 8 complete; Phase 9 never opened
last_updated: "2026-07-27T16:45:00.000Z"
last_activity: 2026-05-31 -- Phase 08 completed (dormant since; formally parked 2026-07-26)
reality_audit: "2026-07-26 -- claims re-verified against code, git log and a full test run; see 'Reality Audit'"
platform_update: "2026-07-27 -- Railway account EMPTIED (Damien approved q1-railway-finish). Phase 3.5's running deliverable is gone; Phase 20 retargeted at Hetzner/Coolify; Park Risk 1 CLOSED. No other park finding changed."
progress:
  total_phases: 24
  completed_phases: 10
  total_plans: 41
  completed_plans: 41
  percent: 42
---

# Project State

> # ⛔ PARKED — v2.0 (shards-as-axioms)
>
> **Parked 2026-07-26** by Damien via cockpit ask **`housekeeping-2026-07-24`**, question
> `q4-folio-insights-v2` → *"Park with an explicit review date."*
> His note: *"analyze the state of the 8-week-old GSD work … determine what has already been
> done / needs to be done … refactor the GSD plans to reflect that."* — this file is that
> refactor.
>
> **Review date: 2026-08-23** (4 weeks). ⚠ **PROVISIONAL** — the 4-week window was chosen by
> Fable, not by Damien; the ask recorded no interval. Confirm or change it with him at the
> first opportunity, then drop this warning.
>
> **What "parked" means here:**
>
> - Do **not** open Phase 09 (or any later phase) without an explicit go from Damien.
> - Do **not** archive the milestone either — Phases 0–8 are real, verified, shipped code
>   that the rest of the repo builds on. Nothing here is dead.
> - Do **not** re-audit from scratch when you come back: the "Reality Audit — 2026-07-26"
>   and "Remaining Work" sections below are the resume brief. Re-verify only the four
>   **watch items** listed under "Park Risks".
> - Repo work continues on the **other** track (folio-resolve / tagger / annotator, CE-managed).
>   That track is *not* this milestone and does not un-park it.
>
> **At review (2026-08-23), the live question is still the one from the ask:** resume Phase 09
> under GSD, or archive v2.0 as partially-shipped and re-plan the still-wanted scope under CE
> (the recommended option at ask time). Parking bought time; it did not answer that.

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-24 after Phase 02)

**Core value:** Every piece of actionable legal advocacy knowledge must be discoverable by task, mapped to FOLIO concepts, and structured for practitioners, AI systems, and developers.
**Current focus:** *None — milestone parked 2026-07-26.* Last worked: Phase 08 — folio-v2-vocab-mini-bfo-spine-7.

## Current Position

Milestone: v2.0 shards-as-axioms — STARTED 2026-04-20, INITIALIZED 2026-04-22
Phase: 08 (folio-v2-vocab-mini-bfo-spine-7) — **COMPLETE** (4/4 plans have SUMMARYs;
`08-VERIFICATION.md` status `passed`, 25/25 must-haves)
Plan: 4 of 4
Status: **PARKED 2026-07-26** (dormant since 2026-05-31) — review **2026-08-23** *(provisional)*
Last activity: 2026-05-31 -- Phase 08 completed

Progress: 10 of 24 phases (Phases 0, 1, 2, 3, 3.5, 4, 5, 6, 7, 8) — all 41 planned plans in
those phases complete and verified. Next unstarted phase: **09 — Seven Design Principles (§8)**,
followed by Phases 10–20. See "Remaining Work" below for the reconciled, evidence-checked list —
it is shorter and differently shaped than the raw ROADMAP suggests.

Previous milestone: v1.1 — SHIPPED 2026-04-20 — was https://folio-insights-production.up.railway.app (**dead since 2026-07-27**, Railway account emptied; the live equivalent is https://folio-insights.dev.openlegalstandard.org)

## Reality Audit — 2026-07-26

Every claim below was re-checked against the working tree, `git log`, and a full local test run
on 2026-07-26. **Headline: the roadmap's "done" claims are honest.** Phases 0–8 exist as real,
tested code; the drift was in the tracking tables, not the work.

**Test evidence (run 2026-07-26 on `master` @ `9fe8ec5`, local `.venv`, Python 3.12):**

- `pytest -q` → **1010 passed, 10 skipped** (with the Dagger Gate-5 test deselected).
- Gate-2 SPARQL P95 benchmarks re-ran **green today**, 8 weeks on: worst case
  `q13_confidence_histogram` warm **median ≈ 109 ms** against the 500 ms hard gate. The Phase-0
  keep=pyoxigraph verdict still holds on current hardware.
- **One real failure:** `tests/bench/test_gate5_digest.py::test_local_dagger_builds_bit_identical_web`
  → `FileNotFoundError: [Errno 2] No such file or directory: 'python'`. The Dagger provisioner
  shells out to `python` (not `python3`), which is absent from this box's PATH. **Environment
  regression, not a code regression** — Gate 5 passed at Phase 0 close. Cheap fix when resumed
  (or on any CI box that ships a `python` shim); it is *not* evidence the CI pipeline rotted.

**Per-phase verification (code evidence, not planning-doc assertions):**

| Phase | Verdict | Evidence in the tree |
|-------|---------|----------------------|
| 0 Foundations / HARD GATE | **DONE** | `src/folio_insights/store/pyoxigraph_store.py` (SERVICE-blocking wrapper), `bench/{generator,gate2_harness,profiles}.py`, `fixtures/bench.nq`, `ci/build.py` + `ci/railway.py` (Dagger), `Dockerfile.web` + `Dockerfile.worker`, `00-DECISION.md` verdict `keep=pyoxigraph`. Gates 1/2/3/5 passed; Gate 4 (SSR <200 ms) + D-11 were **deferred at close** and remain deferred. |
| 1 Polysemy spike | **DONE** | `src/folio_insights/polysemy/{detector,distinguo,similarity_query,cli}.py`, `tests/polysemy/`, `01-VERIFICATION.md`, `fp-labeling-audit.md` (Wilson FP lower bound 2.53% vs 10% gate). |
| 2 Shard Envelope | **DONE** | `shards/envelope.py` (15 fields incl. `extractor_model`, `extraction_prompt_hash`), `shards/minting.py`, `shards/audit.py`, `tests/shards/` (envelope round-trip, discriminated union, 1000-example minting determinism). |
| 3 Shard Subtypes | **DONE** | `shards/subtypes.py` (5 subtypes + Objection/Reply/AuthorityPosition), 5 `tests/shards/test_subtype_*.py` + `test_discriminated_union.py`; `03-VERIFICATION.md` status `passed`, 12/12. **The ROADMAP progress table said "0/? Not started" — that was the single worst piece of drift in the planning set; corrected 2026-07-26.** |
| 3.5 Railway dev server | **DONE — but its deliverable is now RETIRED** | Flat `railway.toml`, `Dockerfile.web`. The Railway dev server it delivered was **deleted 2026-07-27** with the rest of the account (Damien approved `q1-railway-finish`); `https://folio-insights-production.up.railway.app/` → **404**. The phase's *work* still counts as done — but its running artifact is gone and the config it produced (`railway.toml`, `ci/railway.py`) now describes a platform this project no longer uses. **Superseded by Coolify on Hetzner:** `https://folio-insights.dev.openlegalstandard.org/health` → **200** (verified 2026-07-27; Coolify app `folio-insights`, `k4k4pd2koxs06gre4row7n78`, `running:healthy`). |
| 4 IRI Scheme | **DONE** | `shards/iri_registry.py` (fail-closed collision halt), hex32 minting, `tests/shards/{test_minting_determinism,test_iri_collision,test_verify_iris_cli}.py`. |
| 5 Content Versioning | **DONE** | `revision/` package (`edit_shard_content`, in-memory `ShardStore` Protocol, `get_shard_at` reverse replay), `revision/content_edit_shape.ttl`, `tests/shards/test_content_edit_audit_append_only.py`. |
| 6 DID Substrate | **DONE (P1 + P2 core)** | `identity/{keys,signer,verifier,resolver,cache,binding,preview,cli,_b64}.py`, `tests/identity/`, `06-SECURITY.md` 15/15 threats closed. Web OAuth surface deferred per D-02 (correctly recorded). |
| 7 Governance Model | **DONE** | `governance/{events,log,roles,authorize,promote,contest,supersede,resolve_contest,retract,shape_validation}.py` + `governance/cli/` + 8 SHACL shapes + `rfc/` linter; `07-VERIFICATION.md` `passed`. Known and intended seam: `retract --apply` raises `NotImplementedError` until Phase 13 wires a persistent store (`governance/cli/retract.py:199`). |
| 8 FOLIO v2 Vocab + mini-BFO | **DONE** | `vocab/` (5 TTLs + loaders), `temporal/as_of.py`, `docs/query-as-of.md`, `tests/vocab/` + `tests/temporal/`; `08-VERIFICATION.md` 25/25, `08-DRIFT-AUDIT.md` clean. |
| 9–20 | **NOT STARTED** | No `.planning/phases/09*`–`20*` directories exist. No CONTEXT, no RESEARCH, no PLAN, no code. Nothing was half-built and abandoned. |

**Nothing is PARTIALLY DONE inside phases 0–8.** The partial-migration story people remember
belongs to the *other* track (folio-resolve), not to this milestone — see below.

## What Changed in the Repo While v2.0 Slept (and what it obsoletes)

Between 2026-06-01 and 2026-07-26 the repo was busy on a **separate, CE-managed track**. It is
important not to confuse the two, because both are called "v2":

- **GSD milestone "v2.0 shards-as-axioms"** = this file. Shards, DIDs, governance, SPARQL.
- **"folio-insights v2 in-app annotator"** = the CE track from
  `docs/brainstorms/2026-07-15-folio-matching-platform-brainstorm.md`. Tagger recall, per-tag
  verdicts, self-improving calibration. **Different work, colliding name.** When resuming,
  say which v2 you mean in every commit message.

What the other track landed (all on `master`):

- **`folio-resolve` migration, half done.** `pyproject.toml` now pins `folio-resolve>=0.1.0`;
  `pipeline/stages/folio_tagger.py` delegates every label→IRI decision to it (`LabelResolver`,
  `FOLIOEntityRuler`, `Reconciler`, `PlaceNameGate`, seed blocklist, `SourceClassifier`, an
  LLM judge that can only reject/clamp). `services/bridge/reconciliation_bridge.py` is migrated.
  **Still on the old `sys.path` bridge:** `services/bridge/folio_bridge.py` and
  `ingestion_bridge.py` (they still insert `../folio-enrich/backend` into `sys.path`), and the
  recall-side work (span decomposition → semantic/definition search → domain-prior judge,
  WS-D in the brainstorm) is **not** finished. README states the same: source-grounded
  extraction is still outstanding, so v1.0 corpus output remains unvalidated.
- **Deps hygiene fixed (2026-07-05, `181b2b7` + `750e5a6`).** `fastapi`, `uvicorn[standard]`,
  `python-multipart`, `python-docx`, `rapidfuzz`, `marisa-trie` are now declared core deps.
  → **This retires the deferred item recorded in BOTH
  `.planning/phases/00-foundations-hard-gate/deferred-items.md` and
  `.planning/phases/07-governance-model-3-1/deferred-items.md`** ("fastapi not installed →
  7 api test suites fail to collect"). Those 7 suites collect and pass today. The two
  `deferred-items.md` files are left in place as history; treat this line as their closure.
- **Evidence + rubric artifacts** under `docs/evidence/books/` and `docs/rubrics/` — the
  books-UAT de-risk findings and the locked extraction-quality rubric v1.0. Relevant to Phase 10
  planning if v2.0 ever resumes (they describe how the pipeline actually behaves today).

### Obsolete / must-be-replanned items in the v2.0 roadmap

None of Phases 0–8 is obsolete. These **unstarted** items are:

| Item | Status | Why |
|------|--------|-----|
| **Phase 10 — Pipeline + LLM-Agnostic Refactor (§9)** | **OBSOLETE AS PLANNED** (goal survives, plan does not) | It was written in April against the v1 7-stage tagger. That tagger was substantially rewritten in July around `folio-resolve` (judge pipeline, domain prior, calibration recording, deterministic resolution). "Append Stage 8 to the existing 7 stages" no longer describes the thing being appended to. Re-plan from the current `pipeline/stages/folio_tagger.py`, not from §9. |
| **Phase 20 — "Railway multi-service deploy"** | **OBSOLETE — settled 2026-07-27, no longer "decide at review"** | The drain is **complete**: Damien approved `q1-railway-finish`, and the Railway account was emptied 2026-07-27 (2 projects / 8 services deleted; every project id returns *Project not found*). There is no Railway to deploy to. **Retarget the exit criterion at Hetzner/Coolify now** — that is where the working replacement already runs. See `railway-to-hetzner/docs/teardown-snapshots/2026-07-27/TEARDOWN-LOG.md`. |
| **Phase 14 + 15 — UI Design Contract + 7-surface Review UI** | **AT RISK OF COLLISION — re-scope before planning** | The CE annotator track targets the *same* SvelteKit viewer with a different design (per-tag verdict chips, span-anchored full-text rendering, `tag_verdicts` table). Two design contracts for one viewer is a guaranteed conflict. Whichever lands first owns the viewer's design system. |
| Phase 0 Gate 4 (SSR <200 ms) + D-11 full-1M reasoner run | **STILL DEFERRED** (not obsolete) | Deferred at Phase 0 close by decision `00-07-D6`, and the adapter-node→adapter-static reversal in Phase 3.5 pushed full SSR to Phase 20. Both are harness-ready; neither is a pivot trigger (`00-08-D2`). |

## Remaining Work — the resume brief (written 2026-07-26 so nobody re-audits)

If v2.0 resumes as GSD, this is the honest queue. Phases 9, 11, 12, 13, 13.5, 16, 17, 18, 18.5,
19 are **unchanged and still valid as written in ROADMAP.md** — nothing that landed since
invalidates them. The deltas are:

1. **Phase 09 (Seven Design Principles)** — next in sequence, unchanged, and the natural resume
   point. Its 9.P6 sub-phase already has its de-risking spike done (Phase 1) and 9.P7 has its
   BFO spine (Phase 8). Largest single phase; sub-phase it.
2. **Phase 10** — **re-plan, do not resume** (see obsolescence table). Read
   `docs/evidence/books/` + `docs/rubrics/extraction-quality-v1` first; the pipeline it refactors
   is not the pipeline §9 describes.
3. **Phase 13 (Storage Layer)** is the biggest unblocker in the queue — three finished phases are
   holding explicit stubs for it: `governance/log.py` (in-memory dict behind the `GovernanceLog`
   Protocol), `governance/cli/retract.py` (`--apply` refuses with `NotImplementedError`), and
   `revision/`'s in-memory `ShardStore`. Doing 13 early would convert three "seams" into working
   features. Consider re-ordering 13 ahead of 10/11 if the milestone resumes at reduced scope.
4. **Phases 14/15** — re-scope against the CE annotator first (see collision note above).
5. **Phase 20** — **answered 2026-07-27: the target is Hetzner/Coolify.** Railway is gone account-wide, and `folio-insights` already runs healthy at `folio-insights.dev.openlegalstandard.org` under Coolify. This is no longer a review-time question; rewrite the exit criterion against Coolify when the phase opens. `railway.toml` and `ci/railway.py` should be deleted or archived at the same time.
6. **Environment chore (5 min, do it whenever):** Gate 5's Dagger harness needs a `python` on
   PATH (currently only `python3`). Until then `tests/bench/test_gate5_digest.py` fails locally
   and misleads anyone re-auditing.

## Park Risks — the four things to re-verify at review (2026-08-23), not before

1. ~~**The Railway dev server may be deleted underneath Phase 3.5.**~~ **RESOLVED — it
   happened. 2026-07-27.** Damien approved `q1-railway-finish` ("Approve the whole drain"),
   and the Railway account was emptied the same day. Phase 3.5's running deliverable is gone
   and Phase 20 has its new home: **Hetzner/Coolify**, where `folio-insights` is already
   healthy. Nothing to verify at review — this risk is closed, and the two rows above are
   updated. The remaining chore is cleanup: `railway.toml` and `ci/railway.py` are now dead
   config. **This was the only one of the four risks with an external clock; the other three
   still stand.**
2. **Viewer-design collision** — has the CE annotator shipped UI into `viewer/`? If yes,
   Phases 14/15 must be re-scoped, not resumed.
3. **`folio-resolve` drift** — the pin is `>=0.1.0`, open-ended. If that library moved fast
   during the park, the tagger's behaviour may have changed without a commit here.
4. **Stack drift on a 4-month-old locked stack** — `pyoxigraph==0.5.7`, `atproto==0.0.65`,
   `pynacl==1.6.2`, `jcs==0.2.1` etc. are hard-pinned (`.planning/research/STACK.md`). Re-run
   the suite before trusting any of it; the Gate-2 benchmarks are the fast canary.

## ⚠ Reconciliation — 2026-07-24 (housekeeping sweep)

*(Superseded by the 2026-07-26 audit above — retained as history. Its conclusion "needs an owner
decision" was answered on 2026-07-26: park with a review date.)*

This file had drifted and was overstating both progress and activity:

- It said "Phase 08 EXECUTING, Plan 1 of 4" and "Progress 100%". Phase 08 in fact
  **finished**: all four plans (08-01…08-04) have SUMMARY files and `ROADMAP.md` lists
  Phase 8 as completed 2026-05-31. Corrected above.
- **Nothing has moved on this milestone in ~8 weeks.** The last v2.0 commit is
  2026-05-31; every commit since then belongs to a different track — the FOLIO
  tagger / judge pipeline and the `folio-resolve` migration (`feat/wire-decompose-tagger`,
  active through 2026-07-24 — **merged to master 2026-07-24**, branch retired). The repo is busy; *this milestone* is not.
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

Milestone parked 2026-07-26 — no active todos. The resume queue lives in "Remaining Work" above.

### Blockers/Concerns

- [Phase 1]: Gold-standard validation set (50-100 annotated boundaries) requires manual annotation of source material
- [Phase 1]: LLM provider selection for extraction tasks needs benchmarking against advocacy text

## Deferred Items

> **2026-07-26 audit note.** Separately from the v1.1-inherited table below, the *phase-level*
> `deferred-items.md` files in `phases/00-foundations-hard-gate/` and
> `phases/07-governance-model-3-1/` both recorded the same blocker — "`fastapi` is not a declared
> dependency, so 7 `api/` test suites fail to collect". **That is RESOLVED** as of commits
> `181b2b7` + `750e5a6` (2026-07-05): fastapi/uvicorn/python-multipart/python-docx/rapidfuzz/
> marisa-trie are declared core deps and all 7 suites pass in the 2026-07-26 run. The companion
> item in the Phase 07 file — `tests/test_ingestion.py` needing `folio-enrich/backend` on disk —
> is **still open**, and is now tangled with the half-finished `folio-resolve` migration
> (`folio_bridge.py` / `ingestion_bridge.py` still `sys.path`-import folio-enrich). It belongs to
> the CE track, not to this milestone.

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

**Milestone PARKED 2026-07-26 — there is no session to resume.** Do not act on this block until
Damien un-parks v2.0 (review due 2026-08-23, provisional).

Last session: 2026-05-31T15:46:30.304Z
Stopped at: Phase 08 COMPLETE (4/4 plans, verified) — Phase 09 never opened
Resume file: **this file** — read "Reality Audit", "Remaining Work" and "Park Risks" above first
Resume action (only after an explicit un-park): re-verify the four Park Risks, then
`/gsd-discuss-phase 9` (Seven Design Principles §8) — **or**, if the review lands on
"archive + re-plan under CE", `/gsd-complete-milestone` and take the wanted scope to
`compound-engineering:ce-brainstorm` instead.

**Executed Phase:** 08 (folio-v2-vocab-mini-bfo-spine-7) — 4/4 plans complete — 2026-05-31
**Verified Phase:** 08 — `08-VERIFICATION.md` passed, 25/25 must-haves, all 5 VOCAB reqs covered;
code review closed 2 critical + 5 warnings + 4 info (commits `36805e0`…`042bb82`)
**Next Phase:** 09 (Seven Design Principles §8) — depends on Phase 8 (vocab predicates) + Phase 1
(polysemy spike feeds 9.P6); P1 critical path; REQ-IDs PRINCIPLE-01..PRINCIPLE-07; sub-phased
9.P1–9.P7; **not started, not planned, and blocked on the park**

> *(Superseded 2026-07-26: this block previously still pointed at Phase 03 as "next" — an
> April-vintage entry that survived five completed phases. Phase 03 finished 2026-04-25.)*
