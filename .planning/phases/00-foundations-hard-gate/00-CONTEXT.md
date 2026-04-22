# Phase 0: Foundations / HARD GATE - Context

**Gathered:** 2026-04-22
**Status:** Ready for research (MEDIUM-confidence territory) → then planning

<domain>
## Phase Boundary

Validate the locked v2.0 stack (pyoxigraph 0.5.7 + rdflib bridge + owlready2/HermiT + SvelteKit 5 adapter-node + Dagger CI) against 5 hard exit gates on a 1M-triple benchmark corpus, and produce a binding `keep=pyoxigraph` vs `pivot=fuseki` decision artifact. Phase 0 blocks every downstream phase that touches RDF storage, SHACL-at-scale, SSR, or the CI pipeline.

**Locked (do NOT revisit in research/planning):**
- Stack picks: pyoxigraph 0.5.7, rdflib 7.6.0 bridge, owlready2/HermiT, SvelteKit 5 + adapter-node, Dagger, Arq+Redis 7.4, `instructor` LLM abstraction
- Pivot target (Gate 1 failure): Apache Jena Fuseki
- 5 Exit gates: STORAGE-04 (RDF-12 annotation), QUALITY-01 (P95 SPARQL <500ms @ 1M), QUALITY-03 (worker image <500MB), QUALITY-04 (SSR <200ms), OBS-04 (Dagger reproducibility)
- Two-stage Docker split: `web` (JVM-free) + `worker` (JVM-included)
- PHILOSOPHY.md rename from `2026-04-19_Philosophy.md` (trivial deliverable)
- Greenfield on master — no `V1_COMPAT` flag, no v1-corpora migration

</domain>

<decisions>
## Implementation Decisions

### Benchmark corpus composition + gold query set

- **D-01: Corpus composition** — Scaled real corpus: re-extract v1 advocacy shards under v2 pipeline, add FRE + Restatement of Contracts, replay bitemporal edits/supersessions to reach 1M triples. Matches Area 4 load-generator strategy. Rejected: pure synthetic / mixed / adjust-gate variants.
- **D-02: Gold query set** — PRD §20 examples rewritten in RDF-12 syntax + 3-5 adversarial edge cases (deep GRAPH traversal, large CONSTRUCT, SERVICE-blocked attempts). Feeds Phase 16 security testing downstream.
- **D-03: Subtype distribution** — Match real-corpus ratios from v1 re-extracted output (expected: SimpleAssertion-dominant, ~5-10% Disputed, smaller Conflicting/Gloss/Hypothesis). Research task: analyze v1 output to derive exact ratios before generator implementation.
- **D-04: Gate 1 pass criterion** — STRICT. Every PRD §20 example must rewrite in RDF-12 and execute correctly on pyoxigraph 0.5.7. Binary: 100% or pivot to Fuseki.

### Gate-failure decision rules (Gates 2-5)

- **D-05: Gate 2 rule (P95 SPARQL)** — Tune first (3-day pass: query hints, RocksDB tuning, warm cache). If ≤800ms post-tune → accept with SLO adjustment; >800ms → pivot to Fuseki. Note: this overrides the "no time budget" Area 3 decision specifically for the gate-tuning sub-step; it does NOT constrain overall gate resolution time.
- **D-06: Gate 3 rule (worker image >500MB)** — Tune first (strip JVM debug/docs, use JLink custom image, slim deps). ≤700MB post-tune → accept; >700MB → split reasoner into separate microservice in Phase 10 (no pivot on this gate alone).
- **D-07: Gate 4 rule (SSR >200ms)** — Tune streaming + warm cache. ≤400ms → accept with SLO adjustment; >400ms → deferred-hydration fallback (SPA shell + client fetch); NOT a full adapter swap.
- **D-08: Gate 5 definition** — Bit-identical image digest between local Dagger run and Railway-deployed image (`docker inspect --format '{{.Id}}'` matches). Requires deterministic Dockerfile (no apt timestamps, no random UIDs, SOURCE_DATE_EPOCH pinning).

### Spike scope + timeboxing (MAX-FIDELITY)

- **D-09: SSR prototype scope** — Full navigation tree: three Phase 15 surfaces prototyped (shard page + polysemy fork + supersession timeline) against live pyoxigraph. Higher fidelity than minimum spike; deliberately overlaps Phase 15 to de-risk UX gate (QUALITY-05).
- **D-10: Dagger CI scope** — Full CI: build + test + lint + deploy + Railway trigger. Dagger pipeline replaces GitHub Actions. Overlaps Phase 17 (testing) and Phase 20 (release). Downstream phases inherit the pipeline rather than building it.
- **D-11: HermiT benchmark realism** — Full benchmark corpus reasoning at 1M ABox + real FOLIO v2 TBox (when available; else v1 TBox as seed). Measures production cold-start + reasoning cost. May exceed JVM memory → informs `-Xmx` tuning in worker tier. Expected measurement cost: 1-2 days per run.
- **D-12: Time budget** — Open-ended; no fixed per-gate budget. Phase 0 runs until all 5 gates resolve. Implication: downstream phase scheduling depends on Phase 0 resolution date; milestone calendar flexes accordingly.

### 1M-triple load generator design

- **D-13: Generation strategy** — Scaled real corpus (matches D-01). Re-extract v1 + FRE + Restatement, replay bitemporal variations to 1M. Rejects synthetic/faker approaches.
- **D-14: API surface** — CLI + pytest fixture. Both: `folio-insights bench gen --target 1000000 --out fixtures/bench.nq` for one-off perf runs + `@pytest.fixture def bench_1m_corpus` for CI regression tests.
- **D-15: Determinism** — Seeded deterministic. `--seed N` produces identical output across runs. Required for Gate 5 bit-identical digest goal and stable regression tests.
- **D-16: Phase reusability** — Single generator with phase-profile flags. `bench gen --profile phase-13-storage` / `--profile phase-16-sparql-adversarial` etc. Single codebase, tested once, reusable across Phases 11/13/16/17.

### Decision artifact format

- **D-17: DECISION.md location + format** — `.planning/phases/00-foundations-hard-gate/00-DECISION.md` — structured artifact with: (a) binary verdict `keep=pyoxigraph` OR `pivot=fuseki`; (b) per-gate measurement table with actual values; (c) tuning passes performed and results; (d) downstream-phase branch guidance (which phases must adjust on pivot). Signed by a DID once Phase 6 ships — NOT required for Phase 0 (chicken-and-egg: DID substrate depends on Phase 0 validation).

### PHILOSOPHY.md rename

- **D-18: Rename scope** — Pure rename (`docs/2026-04-19_Philosophy.md` → `PHILOSOPHY.md` at repo root). No content restructure in Phase 0. Restructure belongs in Phase 18 (community artifacts).

### Claude's Discretion

- Exact query patterns for adversarial set (D-02) — researcher picks from §21 risk matrix
- JVM heap sizing (`-Xmx` tuning) once HermiT measurements land
- Dagger pipeline stage ordering (build→test→lint→deploy) — standard patterns apply
- Subtype-ratio derivation methodology (D-03) — e.g., analyze last v1 corpus vs use sample

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 0 source-of-truth
- `.planning/REQUIREMENTS.md` §SEC (SEC-01, SEC-02) + §STORAGE (STORAGE-04) + §QUALITY (QUALITY-01, QUALITY-03, QUALITY-04) + §OBS (OBS-04) — authoritative REQ definitions
- `.planning/ROADMAP.md` §Phase 0 — exit criteria, pivot branch, deliverables list
- `.planning/v2.0-MILESTONE-BRIEF.md` §Phase Order (Phase 0 row) + §Quality Bars + §Data & Scale — brief-level commitments
- `.planning/research/SUMMARY.md` §Phase 0: Foundations + §Research Flags — Oxigraph RDF-12 risk, HermiT JVM risk, SSR streaming gap

### Authoritative v2.0 spec
- `PRD-v2.0-draft-2.md` §20 — example queries (the set that must rewrite in RDF-12)
- `PRD-v2.0-draft-2.md` §21 — risk matrix (source of adversarial queries)
- `PRD-v2.0-draft-2.md` §16 — security risks (source of SERVICE-blocked test queries)
- `docs/2026-04-19_Philosophy.md` — to be renamed PHILOSOPHY.md as Phase 0 deliverable

### Stack risks (BLOCKING for Phase 0)
- `.planning/research/SUMMARY.md` §Pitfalls #1 (Oxigraph RDF-12 migration, BLOCKING) + #7 (SHACL@1M perf) + #10 (HermiT JVM cold-start, MEDIUM)
- `.planning/REQUIREMENTS.md` §Key Risk Mitigations — RISK-1 (HermiT JVM two-stage Docker) + RISK-3 (Oxigraph RDF-12 pivot to Fuseki)

### v1 codebase (what's being replaced)
- `pyproject.toml` — current deps (aiosqlite, rdflib, adapter-static)
- `Dockerfile` — current single-stage build (baseline for two-stage migration)
- `railway.toml` — current deploy config
- `api/main.py` — current FastAPI entrypoint (preserved; will get DID middleware in Phase 6)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (from v1.1)
- **FastAPI + authlib stack** (`api/main.py`, `api/routes/`): preserved; DID middleware grafts on in Phase 6
- **SvelteKit 5 viewer** (`viewer/`): `adapter-static` swaps to `adapter-node` as part of Gate 4 prototype; component code mostly portable
- **pytest harness** + 203 passing v1 tests: preserved; Phase 0 adds gate-measurement tests + load-generator fixtures
- **Dockerfile + railway.toml**: current single-stage Dockerfile becomes baseline for two-stage split (`web` JVM-free, `worker` JVM-included)
- **v1 extraction pipeline** (`src/folio_insights/`): invoked by the load generator to re-extract corpus under v2 pipeline for D-01/D-13

### Established Patterns
- **Relative-URL API client** (Vite proxy pattern from v1.1 UAT I-3): carries into adapter-node SSR; proxy config changes but pattern stays
- **Job-file-on-disk pattern** (v1 `api/services/job_manager.py`): being REPLACED by Arq+Redis; Phase 0 Dagger pipeline must provision Redis sidecar
- **Checkpoint + SUMMARY.md pattern** (pipeline stages): stays; Phase 0 deliverables include fixtures that this pattern consumes

### Integration Points
- **New:** pyoxigraph store replaces rdflib-as-store (currently via aiosqlite). API routes that read/write triples refactor in Phase 13; Phase 0 only stands up the store for benchmarking.
- **New:** Arq worker tier replaces `job_manager`. Phase 0 Dagger pipeline provisions Redis + worker; Phase 10 does the actual cutover.
- **New:** adapter-node SSR replaces adapter-static. Phase 0 prototype covers 3 Phase 15 surfaces; Phase 15 builds on these.
- **New:** Dagger CI replaces GitHub Actions. Phase 0 full-CI scope (D-10) means Phase 17 inherits the pipeline rather than building it.

</code_context>

<specifics>
## Specific Ideas

- User explicitly chose MAX-FIDELITY Phase 0 across scope dimensions (D-09 full nav tree, D-10 full CI, D-11 full 1M HermiT reasoning, D-12 open-ended timebox). This signals a preference for "validate hard up front" over "minimum spike, iterate later" — downstream plans should honor that rigor.
- Gate 5 bit-identical digest (D-08) is the strongest reproducibility standard — requires deterministic Dockerfile patterns (SOURCE_DATE_EPOCH, stripped timestamps, pinned UIDs). Research this before planning.
- RDF-12 migration (Gate 1 / D-04) is BLOCKING: the pivot decision shape means downstream phases need conditional plans. Researcher should scope "what changes on Fuseki branch" for each affected phase (6, 11, 13, 16).

</specifics>

<deferred>
## Deferred Ideas

- **DID-signing the DECISION.md artifact** — deferred to Phase 6+ (DID substrate doesn't exist yet; chicken-and-egg).
- **PHILOSOPHY.md content restructure** — Phase 18 (community artifacts), not Phase 0. Phase 0 does the rename only.
- **Query-log gold-set harvest from live Railway** — considered in Area 1 Q2 but rejected; no v1 Railway is receiving traffic at a scale worth harvesting. Revisit for v2.1.
- **Per-gate time budget** — user explicitly rejected (D-12); Phase 0 runs until resolution. Milestone calendar adjusts accordingly.
- **Separate Phase 0 sub-phases per gate** — NOT needed; single phase with gate-labeled plans.

### Downstream impact to flag in research + planning

- **Phase 15 overlap:** D-09 full SSR nav prototype (3 surfaces) partially pre-builds Phase 15 deliverables. Planner should check Phase 15 scope when Phase 0 lands — some tasks may be redundant/promotable.
- **Phase 17 overlap:** D-10 full Dagger CI means Phase 17 inherits pipeline; Phase 17 plans should narrow to test-consolidation only, not CI construction.
- **Phase 20 overlap:** D-10 Railway trigger + D-08 bit-identical digest mean Phase 20 deploy mechanics are largely solved; Phase 20 narrows to CalVer cut + announce.
- **Phase 10 dependency:** D-06 escape-hatch (split reasoner into microservice) alters Phase 10 architecture if Gate 3 fails post-tune. Phase 10 planner should budget for this branch.

</deferred>

---

*Phase: 00-foundations-hard-gate*
*Context gathered: 2026-04-22*
