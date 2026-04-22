---
milestone: v2.0
milestone_name: shards-as-axioms
generated_at: 2026-04-22
phase_numbering: reset (Phase 0/1+)
total_phases: 23
critical_path_phases: 16
parallel_track_phases: 4
sources:
  - .planning/REQUIREMENTS.md
  - .planning/research/SUMMARY.md
  - .planning/v2.0-MILESTONE-BRIEF.md
  - PRD-v2.0-draft-2.md
---

# FOLIO Insights v2.0 — Roadmap (shards-as-axioms)

## 1. Milestone Overview

v2.0 is a **refactor-in-place** on the v1.1 FastAPI + SvelteKit + aiosqlite base. Phase numbering **resets to 0/1** for this milestone; v1.0 and v1.1 phases are archived under `.planning/milestones/`.

**Scope discipline:** Aggressive GA — inherits brief P1/Should-Have, promotes 4 former Defers (hardware-key signing, multi-sig attestations, "Explain this query" LLM helper, corpus fork + genealogy) to P2, and promotes private corpora to P1.

**Non-negotiable gates:**

- **Phase 0 HARD GATE** (SEC-01, SEC-02) with pre-specified pivot to Apache Jena Fuseki
- **Phase 14 UI design contract** before Phase 15 UI plans open (UI-19)
- **Novel UX gate** (QUALITY-05, UI-13): `/gsd-discuss-phase` CONTEXT.md required before `/gsd-plan-phase` for Phase 15.polysemy-fork and 15.contest-wizard; 3-5 legal-practitioner think-aloud sessions with ≥80% task completion before GA
- **Phase 19 pre-release security audit** blocks Phase 20 release cut

**Critical path** (16 phases, ~ordering): 0 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 13 → 14 → 15 → 16 → 19 → 20
**Parallel tracks** (4 phases): Phase 1 (polysemy spike, parallel with 2), Phase 12 (observability, parallel from 6), Phase 14 (UI design, parallel from 8), Phase 18 (community artifacts, parallel from 7)

---

## 2. Phases — Summary Checklist

- [ ] **Phase 0: Foundations / HARD GATE** — Validate stack; decide `keep=pyoxigraph` vs `pivot=fuseki`
- [ ] **Phase 1: Polysemy / distinguo Spike** (parallel) — Canonical *consideration* fixture validates §16 R2
- [ ] **Phase 2: Shard Envelope (§6.1)** — 15-field Pydantic `Shard`
- [ ] **Phase 3: Shard Subtypes (§6.2)** — 5 discriminated-union subtypes
- [ ] **Phase 4: IRI Scheme (§6.3)** — Provenance-hash IRIs with canonicalization + collision detector
- [ ] **Phase 5: Content Versioning (§6.4)** — `ContentEdit` chain + bitemporal time-scoping
- [ ] **Phase 6: DID Substrate (§6.5)** — did:key/web/plc signing; includes 6.1 core, 6.2 hardware-key (P2), 6.3 multi-sig (P2)
- [ ] **Phase 7: Governance Model (§3.1)** — 4-tier roles, PROV-O log, RFC process
- [ ] **Phase 8: FOLIO v2 Vocab + Mini-BFO (§7)** — `fi:*` TTL, `bfo_mapping.ttl`, version pinning
- [ ] **Phase 9: Seven Design Principles (§8)** — Sub-phased 9.P1–9.P7
- [ ] **Phase 10: Pipeline + LLM-Agnostic Refactor (§9)** — Stage 8 Shard Minter, instructor matrix, Arq migration
- [ ] **Phase 11: SHACL Hybrid (§10)** — 6 hand-written shapes + Pydantic-to-SHACL generator
- [ ] **Phase 12: Observability** (parallel) — structlog + OTel + Prometheus + cost tracking
- [ ] **Phase 13: Storage Layer (§11)** — Oxigraph, named graphs, TTL dump, export formats
- [ ] **Phase 13.5: Private Corpora** — Envelope encryption + access control (promoted P1)
- [ ] **Phase 14: UI Design Contract** (parallel) — SvelteKit adapter-node swap + design system
- [ ] **Phase 15: Review UI (§12)** — Sub-phased per surface (7 sub-phases)
- [ ] **Phase 16: Public SPARQL Endpoint + Write API** — Read `/sparql` + DID-gated REST writes + "Explain query" LLM helper
- [ ] **Phase 17: Testing Consolidation (§13)** — 203 v1 + ~425 new tests; golden-set harness
- [ ] **Phase 18: Community Artifacts + Docs** (parallel) — CONTRIBUTING, CoC, GOVERNANCE, RFC, mkdocs
- [ ] **Phase 18.5: Corpus Fork + Genealogy** (P2) — Fork capability + genealogy viz
- [ ] **Phase 19: Pre-Release Security Audit** — BLOCKS RELEASE
- [ ] **Phase 20: Release Cut** — v2.0.0 CalVer + Railway deploy + public SPARQL announce

---

## 3. Phase Details

### Phase 0 — Foundations / HARD GATE

**Goal**: Validate the locked v2.0 stack against reality and produce a binding keep-vs-pivot decision on the RDF substrate.
**Depends on**: Nothing (foundation).
**REQ-IDs covered**: SEC-01, SEC-02, QUALITY-01, QUALITY-03, QUALITY-04, OBS-04, STORAGE-04
**Critical path**: yes — blocks every other phase that touches RDF storage, SHACL-at-scale, or SSR.
**Parallel-track?**: no
**Research flag**: **yes** — RDF-12 migration, HermiT JVM tuning, SSR streaming, Dagger CI are all in MEDIUM-confidence research territory.
**Ship-critical?**: P1 (non-negotiable gate).
**Exit criteria (5 HARD GATES — all must pass OR pivot)**:
  1. **RDF 1.2 annotation pattern works** — every PRD §20 example query rewritten in RDF-12 syntax executes against pyoxigraph 0.5.7 on the 1M-triple benchmark corpus (STORAGE-04).
  2. **P95 SPARQL query latency < 500ms @ 1M triples** on the benchmark corpus (QUALITY-01).
  3. **Worker Docker image < 500 MB** with JVM 17 + HermiT + deps (QUALITY-03).
  4. **SSR page latency < 200ms** for a cold shard page via SvelteKit 5 adapter-node (QUALITY-04).
  5. **Dagger CI reproducible** — identical image digests local vs Railway (OBS-04).
**Pivot branch (if gate 1 fails)**: Pre-specified pivot to Apache Jena Fuseki recorded in `.planning/phases/0-foundations/DECISION.md`. All downstream phases tagged "depends on Phase 0 keep/pivot decision" must branch on `keep=pyoxigraph` vs `pivot=fuseki`.
**Deliverables**:
  - PHILOSOPHY.md rename from v1 docs
  - Oxigraph + rdflib spike with §20 query audit
  - HermiT-in-Docker perf baseline
  - Dagger CI pipeline
  - 1M-triple load generator (fixtures reusable by Phases 11, 13, 16, 17)
  - SSR streaming prototype (adapter-node)
  - Two-stage Dockerfile prototype (web JVM-free / worker JVM)
  - Decision artifact: `keep=pyoxigraph` OR `pivot=fuseki`
**Plans**: TBD

---

### Phase 1 — Polysemy / distinguo Spike

**Goal**: Validate §16 Risk 2 (polysemy detector FP rate, human-gate design) via canonical legal *consideration* fixture before committing Phase 9.P6 architecture.
**Depends on**: Phase 0 (stack validated).
**REQ-IDs covered**: PRINCIPLE-06 (scoping only; full impl in 9.P6), VOCAB-02 (analogia predicates first-use)
**Critical path**: no — runs **in parallel with Phase 2**.
**Parallel-track?**: **yes**
**Research flag**: **yes** — polysemy FP curation + LLM-vs-rule hybrid is a core novel service with no ecosystem precedent.
**Ship-critical?**: P1 (de-risks 9.P6; spike output feeds that phase's plan).
**Exit criteria**:
  1. *Consideration* fixture set (≥20 shards across 3+ frameworks) classified by the prototype detector with ≤10% FP rate.
  2. Human-gate interaction pattern (accept / reject / modify) documented in spike SUMMARY.md — **no auto-apply path** (§16 R2).
  3. Per-framework threshold strategy proposed and open-sourced for 9.P6 planning.
**Plans**: TBD

---

### Phase 2 — Shard Envelope (§6.1)

**Goal**: Ship the 15-field Pydantic `Shard` envelope as the v2.0 core data model with round-trip and discriminated-union guarantees.
**Depends on**: Phase 0.
**REQ-IDs covered**: SHARD-01, SHARD-10
**Critical path**: yes.
**Parallel-track?**: no.
**Research flag**: no (standard Pydantic 2.13 patterns).
**Ship-critical?**: P1.
**Exit criteria**:
  1. `Shard(**shard.model_dump()) == shard` round-trips for every subtype placeholder.
  2. Discriminated-union test rejects invalid subtype tag with a useful error.
  3. Bitemporal fields (`valid_time_start`, `valid_time_end`, `transaction_time`) round-trip and serialize deterministically.
**Plans**: TBD

---

### Phase 3 — Shard Subtypes (§6.2)

**Goal**: Ship the 5 subtypes as discriminated-union variants of the envelope with schema + example round-trip coverage.
**Depends on**: Phase 2.
**REQ-IDs covered**: SHARD-02, SHARD-03, SHARD-04, SHARD-05, SHARD-06
**Critical path**: yes.
**Parallel-track?**: no.
**Research flag**: no.
**Ship-critical?**: P1.
**Exit criteria**:
  1. PRD examples A.1 (SimpleAssertion), A.2 (ConflictingAuthorities with 8 reconciliation strategies), A.3 (DisputedProposition) all round-trip.
  2. Gloss + Hypothesis subtypes parse and validate.
  3. `HypothesisShard` promotion path enforces `citation_required=True` — unsigned/un-cited promotion rejected.
**Plans**: TBD

---

### Phase 4 — IRI Scheme (§6.3)

**Goal**: Ship provenance-hash IRI minting with deterministic canonicalization and collision detection.
**Depends on**: Phase 3.
**REQ-IDs covered**: SHARD-07, SHARD-08
**Critical path**: yes.
**Parallel-track?**: no.
**Research flag**: no (documented pitfall, well-specified mitigation).
**Ship-critical?**: P1.
**Exit criteria**:
  1. Property test: same source + same span → same IRI across 1000 random runs (NFC + LF + trim + RFC 3986 applied).
  2. Nightly re-hash verification job passes on benchmark corpus.
  3. Collision detector exercised at 100K shards; fallback behavior documented.
**Plans**: TBD

---

### Phase 5 — Content Versioning (§6.4)

**Goal**: Ship the append-only `ContentEdit` chain and `get_shard_at(iri, t)` historical retrieval under immutable shard IRIs.
**Depends on**: Phase 4.
**REQ-IDs covered**: SHARD-09
**Critical path**: yes.
**Parallel-track?**: no.
**Research flag**: no.
**Ship-critical?**: P1.
**Exit criteria**:
  1. `test_content_edit_audit_append_only.py` green.
  2. SHACL guard rejects edits to past versions (forward-only semantics).
  3. `get_shard_at(iri, t)` returns correct historical state across a 10-edit fixture.
**Plans**: TBD

---

### Phase 6 — DID Substrate (§6.5)

**Goal**: Ship DID-signed attestations as the security substrate for every v2.0 write action, including hardware-key and multi-sig paths.
**Depends on**: Phase 5 (envelope + versioning must exist before we can sign them).
**REQ-IDs covered**: DID-01, DID-02, DID-03, DID-04, DID-05, DID-06, DID-07, DID-08 (P2), DID-09 (P2), SEC-05, SEC-06
**Critical path**: yes.
**Parallel-track?**: no (but unlocks Phase 7 + Phase 12).
**Research flag**: **yes** — DID key rotation, JCS edge cases, atproto signing paths need validation beyond base research.
**Ship-critical?**: P1 (core); DID-08, DID-09 are P2 stretch.
**Exit criteria**:
  1. `pytest tests/identity/` green across did:key / did:web / did:plc; Playwright OAuth→DID binding covers all 3 paths.
  2. `verify(sign(x))` property test passes across shuffled field orders for 1000 random shards (JCS canonicalization is stable).
  3. `test_signature_survives_key_rotation.py` green — historical `signing_key_id` + `did_doc_snapshot_at` replay works.
  4. Security review confirms **no server-side signing keys** for any DID (DID-06).
  5. "What will I be signing?" preview renders for all 8 signed-action types (DID-07).
**Sub-phases**:
  - **6.1 core (P1)**: did:key + did:web + did:plc; JCS `canonical_content_hash`; signing-time key capture; OAuth→DID binding; preview UI; GitHub-takeover defense (SEC-06).
  - **6.2 hardware-key signing (P2)**: Ledger / YubiKey / WebAuthn for did:key; E2E test against WebAuthn virtual authenticator (DID-08).
  - **6.3 multi-sig attestations (P2)**: N-of-M co-sign schema + SHACL shape + UI flow; 2-of-3 promotion succeeds / 1-of-3 fails (DID-09).
**Plans**: TBD
**UI hint**: yes

---

### Phase 7 — Governance Model (§3.1)

**Goal**: Ship the 4-tier role model, PROV-O governance log, and three-way disambiguation machinery that makes v2.0 governed-by-design.
**Depends on**: Phase 6.
**REQ-IDs covered**: GOV-01, GOV-02, GOV-03, GOV-04, GOV-05, GOV-06, GOV-07, GOV-08, GOV-09 (P2), GOV-10 (P2), CORPUS-05
**Critical path**: yes.
**Parallel-track?**: no (unlocks Phase 18 community artifacts to parallel).
**Research flag**: no (PROV-O + Covenant 2.1 are standard patterns).
**Ship-critical?**: P1 core; GOV-09, GOV-10 are P2 stretch (timeline viewer + warrant trace-back UI).
**Exit criteria**:
  1. Role assertions round-trip; per-corpus role queries return the correct set.
  2. Append-only governance log: `DELETE`/`UPDATE` on past rows rejected by both SHACL and SQLite trigger.
  3. Promotion `hypothesis → attested` requires reviewer role + citation + DID-signed `fi:Promotion` — unsigned promotion rejected end-to-end (CLI + API).
  4. Three-way disambiguation: contest / supersede / retract have **distinct codepaths** and **distinct CLI commands** (no shared code — code-review gate).
  5. Retraction cascade preview groups dependents `{auto_rederive, aporetic, review_needed}` with rollback-before-commit affordance.
  6. RFC process: `.planning/rfcs/NNNN-title.md` lifecycle linter green in CI; no auto-merge.
**Plans**: TBD

---

### Phase 8 — FOLIO v2 Vocab + Mini-BFO Spine (§7)

**Goal**: Ship the FOLIO v2 TTL vocabulary (`fi:*` predicates) and mini-BFO spine with version-pinning enforcement.
**Depends on**: Phase 7 (governance predicates anchored; supersession predicates used by §21.9 cascade preview).
**REQ-IDs covered**: VOCAB-01, VOCAB-02, VOCAB-03, VOCAB-04, VOCAB-05
**Critical path**: yes.
**Parallel-track?**: no (but unlocks Phase 14 UI design to parallel).
**Research flag**: no (standard TTL + OWL 2 EL).
**Ship-critical?**: P1.
**Exit criteria**:
  1. FOLIO v2 TTL parses with both rdflib and pyoxigraph; `owl:versionIRI` stable.
  2. `fi:vocabVersion` SHACL shape enforces pin on every shard — unpinned shards rejected.
  3. All 4 analogia predicates + 4 distinction kinds queryable; Tractarian / Spinozan / Russellian / Carnap / Aristotelian predicates round-trip.
  4. Mini-BFO classes (Continuant, Occurrent, IndependentContinuant, SDC, GDC, Process, Quality, Role, Disposition) present with `owl:equivalentClass` mappings to BFO 2020 in companion `bfo_mapping.ttl`.
  5. Supersession predicates (`fi:supersedes`, `fi:supersededBy`) distinct from retraction; as-of query returns superseded shard.
**Plans**: TBD

---

### Phase 9 — Seven Design Principles (§8)

**Goal**: Ship all 7 §8 design principles as sub-phased, independently-verifiable capabilities.
**Depends on**: Phase 8 (vocab predicates), Phase 1 (polysemy spike feeds 9.P6).
**REQ-IDs covered**: PRINCIPLE-01, PRINCIPLE-02, PRINCIPLE-03, PRINCIPLE-04, PRINCIPLE-05, PRINCIPLE-06, PRINCIPLE-07
**Critical path**: yes.
**Parallel-track?**: no (sub-phases within 9 may parallelize after 9.P4).
**Research flag**: **yes** for 9.P6 (polysemy FP curation — carries forward from Phase 1 spike).
**Ship-critical?**: P1 (all 7 principles).
**Exit criteria (roll-up across sub-phases)**:
  1. Cluster validator runs in worker tier only (no JVM in web); async warn-only in CI (9.P1).
  2. Framework assignment deterministic across re-extractions; `extraction_prompt_hash` stable (9.P2).
  3. DAG construction < 5s for 10K shards; cycle detection present (9.P3).
  4. TBox / ABox in distinct named graphs; TBox constrained to OWL 2 EL (9.P4).
  5. CWA islands produce different results vs. open-world default for negation-as-failure cases (9.P5).
  6. Polysemy detector ≤10% FP on curated fixtures; auto-apply **impossible by design** (9.P6).
  7. BFO classifier coverage ≥95% at ingest; unknown → permissive defaults documented (9.P7).
**Sub-phases**:
  - **9.P1 cluster validator** — owlready2 + HermiT subprocess; worker-tier only; async warn-only (PRINCIPLE-01).
  - **9.P2 framework detector** — source metadata + corpus config + LLM inference; records `fi:framework` + `extraction_prompt_hash` (PRINCIPLE-02).
  - **9.P3 dependency graph** — `fi:dependsOnAxiom` / `fi:dependsOnDefinition` first-class edges; cascade preview enabler (PRINCIPLE-03).
  - **9.P4 TBox/ABox split** — distinct named graphs; OWL 2 EL validator (PRINCIPLE-04).
  - **9.P5 closed-world islands** — `fi:closureMarker`; default open-world (PRINCIPLE-05).
  - **9.P6 polysemy detector** — framework-conflicting axiom flagging; human-gated always (PRINCIPLE-06).
  - **9.P7 BFO classifier** — permissive mode; ingest-time assignment (PRINCIPLE-07).
**Plans**: TBD

---

### Phase 10 — Pipeline + LLM-Agnostic Refactor (§9)

**Goal**: Ship Stage 8 Shard Minter appended to the v1 7-stage pipeline, with provider-agnostic LLM access and Arq-backed async orchestration.
**Depends on**: Phase 9 (principles feed framework detector + BFO classifier + polysemy hooks).
**REQ-IDs covered**: LLM-01, LLM-02, LLM-03, LLM-04, LLM-05, LLM-06
**Critical path**: yes.
**Parallel-track?**: no.
**Research flag**: no (instructor + Arq are standard patterns).
**Ship-critical?**: P1.
**Exit criteria**:
  1. CI matrix green across Anthropic (Claude default) + OpenAI + Ollama; `--llm-provider` CLI flag works.
  2. Per-shard `extractor_model` + `extraction_prompt_hash` fields populated and queryable.
  3. Stage 8 is an **isolated module**; v1 stages 1-7 are unmodified (code review gate); E2E: raw doc → signed shard.
  4. Lazy-fill: fields `{1,2,3,4,12,14,15}` at extraction; `{5-11, 13}` via Arq follow-up; shard marked `extraction_phase=partial|complete`.
  5. Arq 0.28 + Redis 7.4 cutover: side-by-side feature flag cleans up; no orphan jobs after reconciliation.
  6. Cost meter accurate within ±5%; single-layer (instructor-level) retry; no nested retries.
**Plans**: TBD

---

### Phase 11 — SHACL Hybrid (§10)

**Goal**: Ship the 6 hand-written SHACL shapes plus the ~150 LOC Pydantic-to-SHACL generator with build-time TTL emission.
**Depends on**: Phase 10 (Stage 8 emits shards that the shapes validate).
**REQ-IDs covered**: SHACL-01, SHACL-02, SHACL-03, SHACL-04, SHACL-05
**Critical path**: yes.
**Parallel-track?**: no.
**Research flag**: **yes** — Pydantic-to-SHACL generator has no ecosystem prior art (RISK-2).
**Ship-critical?**: P1.
**Exit criteria**:
  1. All 6 shapes (envelope, subtypes, governance, supersession, distinguo, signatures) parse; pyshacl validates fixtures.
  2. Generator round-trips: `Pydantic → SHACL → validate(pydantic_instance)` as a property test across all 15-field variants.
  3. Dagger build emits generated TTL deterministically; CI verifies regenerated TTL matches committed TTL.
  4. Per-shard incremental validation P95 < 50ms at 1M-triple corpus (shapes pre-compiled at startup).
  5. `POST /validate` returns pyshacl report for valid + invalid fixtures; documented in OpenAPI (SHACL-05).
**Plans**: TBD

---

### Phase 12 — Observability

**Goal**: Ship structlog + OpenTelemetry + Prometheus across app + worker, with prompt-attribute truncation and per-corpus cost tracking.
**Depends on**: Phase 6 (DID substrate exists to scope cost/trace attributes by DID).
**REQ-IDs covered**: OBS-01, OBS-02, OBS-03, OBS-04 (co-delivered with Phase 0 Dagger CI)
**Critical path**: no — **parallelizes from Phase 6**.
**Parallel-track?**: **yes**
**Research flag**: no (standard observability).
**Ship-critical?**: P1.
**Exit criteria**:
  1. Traces visible in OTel backend; Prometheus scrape returns expected metrics.
  2. Prompt-attribute truncation enforced (hash prompts > 2KB; no raw leakage).
  3. Per-corpus LLM cost report accurate within ±5% (tokens × provider price).
  4. Dagger-based CI reproducible across local + Railway (identical image digests).
**Plans**: TBD

---

### Phase 13 — Storage Layer (§11)

**Goal**: Ship pyoxigraph as canonical RDF 1.2 store with named-graph organization, rdflib bridge for pyshacl/JSON-LD, nightly TTL dumps, and export formats.
**Depends on**: Phase 0 (keep-vs-pivot decision), Phase 11 (SHACL hooks into store writes).
**REQ-IDs covered**: STORAGE-01, STORAGE-02, STORAGE-03, STORAGE-04, STORAGE-05, STORAGE-06, STORAGE-07, CORPUS-01, CORPUS-02, CORPUS-03, CORPUS-04
**Critical path**: yes.
**Parallel-track?**: no.
**Research flag**: no (Phase 0 already resolved RDF-12).
**Ship-critical?**: P1.
**Exit criteria**:
  1. Bulk load ≥ 200K triples/sec at 1M-triple benchmark; query semantics match RDF 1.2.
  2. Named-graph partitioning: one ABox graph per corpus + shared TBox + per-corpus governance; `GRAPH ?g { }` returns correct set.
  3. Code review confirms no write paths through rdflib — rdflib is adapter-only (STORAGE-02).
  4. Nightly TTL dump + git commit visible in git log.
  5. All 8 export formats (`combined.ttl`, `abox/*.ttl`, `tbox.ttl`, `governance.ttl`, JSON-LD, SPARQL CONSTRUCT, N-Quads, Neo4j CSV) round-trip for benchmark corpus.
  6. PII redaction on ingest rejects SSN/ABA/phone defaults; no PII in default-exported corpus.
  7. Benchmark corpora (v1 advocacy + FRE + Restatement of Contracts) all load + pass SHACL + pass cluster validation (CORPUS-04).
**Plans**: TBD

---

### Phase 13.5 — Private Corpora

**Goal**: Ship opt-in private corpora with envelope encryption and DID-based access control (promoted from Should-Have to P1 at scope session 2026-04-22).
**Depends on**: Phase 13 (storage + named graphs), Phase 6 (admin DID pubkey wraps corpus key).
**REQ-IDs covered**: CORPUS-06, CORPUS-07
**Critical path**: yes (blocks Phase 16 write-API behavior for private corpora).
**Parallel-track?**: no.
**Research flag**: no (envelope encryption with `cryptography.hazmat` is well-specified).
**Ship-critical?**: P1.
**Exit criteria**:
  1. Private corpus round-trips: write-encrypt-persist-read-decrypt produces the original shard.
  2. P95 decrypt latency < 5ms per shard on benchmark load.
  3. AuthZ test: 3 DIDs (admin / reviewer / outside) see correct views — outside DID gets 404 on SPARQL, 403 on write API.
  4. Governance log entries for private corpora redacted from public feed.
**Plans**: TBD

---

### Phase 14 — UI Design Contract

**Goal**: Swap SvelteKit adapter-static → adapter-node, establish component library skeleton, and land the "shards-as-axioms" bold aesthetic before any Phase 15 UI plan opens.
**Depends on**: Phase 0 (SSR prototype), Phase 8 (vocab gives component taxonomy).
**REQ-IDs covered**: UI-01, UI-18, UI-19, QUALITY-02
**Critical path**: yes (Phase 15 gated by Phase 14 artifact).
**Parallel-track?**: **yes** — can run alongside Phase 8+9 as long as it finishes before Phase 15 opens.
**Research flag**: **yes** — `/gsd-ui-phase` heavy design iteration; no ecosystem precedent for shards-as-axioms aesthetic.
**Ship-critical?**: P1.
**Exit criteria**:
  1. App boots with adapter-node; SSR renders initial HTML for shard pages.
  2. axe-core 4.11 CI gate **blocking**; waivers require RFC.
  3. Design system + component library skeleton committed; `/gsd-ui-phase` artifact lives in `.planning/phases/14-ui-design/`.
  4. `/gsd-plan-phase` for any 15.* sub-phase refuses to start without this phase's design contract.
**Plans**: TBD
**UI hint**: yes

---

### Phase 15 — Review UI (§12)

**Goal**: Ship all 7 review UI surfaces with per-surface sub-phases, mandatory UX discussion artifacts for novel surfaces, and a WCAG 2.1 AA quality gate.
**Depends on**: Phase 14 (design contract), Phase 13 (storage), Phase 10 (Stage 8 output), Phase 7 (governance events).
**REQ-IDs covered**: UI-02, UI-03, UI-04, UI-05, UI-06, UI-07, UI-08, UI-09, UI-10, UI-11, UI-12, UI-13, UI-14, UI-15 (P2), UI-16 (P2), UI-17 (P2), QUALITY-05
**Critical path**: yes.
**Parallel-track?**: no (sub-phases may parallelize after 15.shard-page lands).
**Research flag**: **yes** for 15.polysemy-fork and 15.contest-wizard — no direct UX precedent; `/gsd-discuss-phase` CONTEXT.md mandatory before `/gsd-plan-phase`.
**Ship-critical?**: P1 for all listed sub-phases; P2 surfaces (UI-15/16/17) as stretch.
**Exit criteria (roll-up)**:
  1. All 15 fields visible on shard page; content-negotiated dereference works (HTML vs TTL/JSON-LD via `Accept:`) (UI-02).
  2. Signature-verification badge reflects runtime state (valid/expired/unreachable) (UI-03).
  3. Subtype + status chips visually-regression-tested (UI-04).
  4. Copy-as-citation (BibTeX / Bluebook / Hyperlink) round-trips and survives content edits (UI-05).
  5. Polysemy fork UI full E2E with all 3 disposition paths; preview renders 3-hop dependency fixture (UI-06, UI-07).
  6. Supersession timeline renders 10-link chain < 500ms; as-of picker re-renders (UI-08); bitemporal toggle changes query semantics (UI-09).
  7. Contest / supersede / retract wizards have distinct copy + distinct codepaths + cascade preview (UI-10).
  8. Dependency graph renders 100-node fixture < 1s with 3-hop default and kernel-chain highlight (UI-11).
  9. Tractarian tree breadcrumb clickable and correct via cached transitive closure (UI-12).
  10. Novel UX gate: 15.polysemy-fork and 15.contest-wizard pass 3-5 legal-practitioner think-aloud sessions with ≥80% task completion; transcripts + completion rates in each sub-phase's SUMMARY.md (QUALITY-05).
  11. Rollback/escape-hatch affordances: 15-min undo on just-committed distinguo reverts cleanly; arbiter-override produces signed override event (UI-14).
  12. CI blocking axe-core 4.11 WCAG 2.1 AA (QUALITY-02).
**Sub-phases**:
  - **15.shard-page** — deep-link `/shard/<hex16>` with 15-field inspector, content negotiation, signature badge, subtype/status chips, copy-as-citation (UI-02, UI-03, UI-04, UI-05). P2 stretch surfaces UI-15/16/17 may ride here.
  - **15.polysemy-fork** — distinguo workflow with prime-analogate picker, proportional-relation editor, distinction-kind selector, "What would this fork affect?" preview, 15-min undo (UI-06, UI-07, UI-14 distinguo-side). **MANDATE: `/gsd-discuss-phase` CONTEXT.md before `/gsd-plan-phase`**. **Novel UX gate applies** (QUALITY-05).
  - **15.supersession-timeline** — horizontal ribbon + as-of picker + chain nav + supersession-vs-retraction indicator + bitemporal toggle (UI-08, UI-09).
  - **15.contest-wizard** — contest path with position + citation + arbiter/distinguo/aporetic resolution + arbiter-override affordance (UI-10 contest-side, UI-14 arbiter-override). **MANDATE: `/gsd-discuss-phase` CONTEXT.md before `/gsd-plan-phase`**. **Novel UX gate applies** (QUALITY-05).
  - **15.retract-supersede-disambiguation** — three-way prompt + distinct copy + retraction cascade preview; code-review gate on "no shared codepath" (UI-10 retract/supersede-side).
  - **15.dependency-graph** — Cytoscape.js DAG with 3-hop default, expand affordance, kernel-chain highlight (UI-11); Tractarian tree breadcrumb (UI-12).
  - **15.sparql-explorer** — navigation + shard-page integration only; Explorer impl owned by Phase 16.
**Plans**: TBD
**UI hint**: yes

---

### Phase 16 — Public SPARQL Endpoint + Write API

**Goal**: Ship the read-only public `/sparql` endpoint with full security hardening, the DID-gated REST write API, the SHACL validation endpoint, and the SPARQL Explorer UI with all pre-shipped templates.
**Depends on**: Phase 13 (storage), Phase 13.5 (private-corpus access control), Phase 6 (DID gate for writes), Phase 11 (SHACL `/validate`), Phase 14 (Explorer UI design contract).
**REQ-IDs covered**: SPARQL-01, SPARQL-02, SPARQL-03, SPARQL-04, SPARQL-05, SPARQL-06, SPARQL-07, SPARQL-08, SPARQL-13, SPARQL-14, SEC-04
**Critical path**: yes.
**Parallel-track?**: no.
**Research flag**: **yes** — SPARQL security hardening (SERVICE SSRF, `initBindings`, rate-limiting) + RDF-12 template authoring.
**Ship-critical?**: P1 core. P2 stretch (SPARQL-09, SPARQL-10, SPARQL-11, SPARQL-12) tracked as separate sub-plans within Phase 16.
**Exit criteria**:
  1. `POST UPDATE` on `/sparql` returns 403; `SELECT` / `CONSTRUCT` return 200 (SPARQL-01).
  2. Security test: `SERVICE` payload rejected at AST; DoS load test passes with 30s timeout + 10K row cap + IP+DID rate limits (SPARQL-02, SEC-04).
  3. Injection test suite passes via `initBindings` on every parameterized query (SPARQL-03).
  4. Content negotiation covers SPARQL JSON, SPARQL XML, CSV, TSV, Turtle (SPARQL-04).
  5. VoID + schema dump + SPARQL service description via `/sparql?format=void` (SPARQL-05).
  6. Browser-based YASGUI connects without proxy via restricted CORS (SPARQL-06).
  7. SPARQL Explorer Playwright E2E covers query-edit-execute (SPARQL-07).
  8. All 13 pre-shipped templates (8 PRD §20 + polysemy + supersession + contested + framework + `--as-of`) execute with non-empty results on benchmark corpus (SPARQL-08).
  9. Permalink encode→share→decode→execute round-trips (SPARQL-13).
  10. DID-gated REST write API: unsigned write returns 401; signed write → governance log entry + oxigraph update (SPARQL-14).
  11. (P2 stretch) "Explain this query" LLM helper generates description for 10 template queries (SPARQL-09); SSE streaming first row < 200ms (SPARQL-10); RDF-12 annotation helper produces valid queries (SPARQL-11); Cytoscape CONSTRUCT → graph → click → navigate (SPARQL-12).
**P2 sub-plans (tracked within Phase 16)**:
  - **16.explain-query (P2)** — instructor-powered "Explain this query" helper (SPARQL-09).
  - **16.sse-streaming (P2)** — SvelteKit adapter-node SSE streaming (SPARQL-10).
  - **16.rdf12-helper (P2)** — RDF-12 annotation query helper (SPARQL-11).
  - **16.graph-result (P2)** — Cytoscape.js CONSTRUCT viz (SPARQL-12).
**Plans**: TBD
**UI hint**: yes

---

### Phase 17 — Testing Consolidation (§13)

**Goal**: Preserve 203 v1 tests + ship ~425 new tests + golden-set Tier 3 shard-extraction harness + DID rotation + SHACL-at-scale scenarios.
**Depends on**: Phase 16 (all surfaces must exist to test them).
**REQ-IDs covered**: QUALITY-06, SEC-05 (key-rotation scenarios, co-ship)
**Critical path**: yes.
**Parallel-track?**: no.
**Research flag**: no.
**Ship-critical?**: P1.
**Exit criteria**:
  1. All 203 v1 tests green on `main`.
  2. New tests green; coverage ≥ 85% on new code.
  3. Tier 3 golden-set harness produces signed shards deterministically for benchmark fixtures.
  4. DID key-rotation scenario tests green (co-ship with SEC-05).
  5. SHACL-at-scale test verifies P95 < 50ms at 1M triples (co-verifies Phase 11 SLO).
**Plans**: TBD

---

### Phase 18 — Community Artifacts + Docs

**Goal**: Ship CONTRIBUTING, Code of Conduct (Contributor Covenant 2.1), GOVERNANCE, RFC template, mkdocs-material site, JupyterLite, and SPARQL cookbook.
**Depends on**: Phase 7 (governance model + RFC process must exist before we document them).
**REQ-IDs covered**: GOV-08 (co-delivered; governance artifacts proper shipped here)
**Critical path**: no — **parallelizes from Phase 7**.
**Parallel-track?**: **yes**
**Research flag**: no (standard mkdocs + cookbook).
**Ship-critical?**: P1.
**Exit criteria**:
  1. `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (CC 2.1), `GOVERNANCE.md`, `RFC-TEMPLATE.md` all exist and link from README.
  2. Spell-check CI pass.
  3. mkdocs-material site builds; JupyterLite notebook runs the SPARQL cookbook end-to-end against the public endpoint.
**Plans**: TBD

---

### Phase 18.5 — Corpus Fork + Genealogy (P2)

**Goal**: Ship corpus fork capability with genealogy visualizer (promoted from Defer at scope session 2026-04-22).
**Depends on**: Phase 13 (named graphs), Phase 7 (corpus_admin role + signed events), Phase 15.dependency-graph (Cytoscape.js viz primitive).
**REQ-IDs covered**: CORPUS-08, CORPUS-09
**Critical path**: no (P2 stretch; can slip to v2.1 if phase budget tightens).
**Parallel-track?**: no — sits after Phase 18 in ordering but does not block 19.
**Research flag**: no.
**Ship-critical?**: **P2 stretch**.
**Exit criteria**:
  1. Fork operation creates new named graph + fork metadata; origin remains intact; event is DID-signed and corpus_admin-scoped.
  2. Fork-tree visualizer renders 5-corpus + 3-fork-event fixture; click-node → open-corpus navigation works.
**Plans**: TBD
**UI hint**: yes

---

### Phase 19 — Pre-Release Security Audit

**Goal**: Execute the pre-release security audit covering crypto primitives, OAuth, DID rotation, SPARQL SERVICE/SSRF, rate limiting, write API input validation, and the GitHub-username-takeover → DID impersonation path (F7). BLOCKS RELEASE.
**Depends on**: Phases 6, 11, 13, 13.5, 16, 17 (everything auditable must exist).
**REQ-IDs covered**: SEC-03, SEC-04, SEC-05, SEC-06, DID-06 (audit-gate verification)
**Critical path**: yes — **non-negotiable release gate**.
**Parallel-track?**: no.
**Research flag**: **yes** — security audit vendors + DID threat models.
**Ship-critical?**: P1.
**Exit criteria**:
  1. Audit report addresses all 7 areas with sign-off.
  2. No server-held signing keys confirmed (DID-06).
  3. Historical signatures verify after key rotation (SEC-05).
  4. SERVICE SSRF defense verified by security test suite (SEC-04).
  5. GitHub-username-takeover squatter scenario rejects (SEC-06).
  6. Rate limiting + write API input validation verified under adversarial load.
**Plans**: TBD

---

### Phase 20 — Release Cut

**Goal**: Cut v2.0.0 CalVer, deploy Railway multi-service, announce the public SPARQL endpoint, and confirm benchmark corpora are live.
**Depends on**: Phase 19.
**REQ-IDs covered**: None new (integration milestone; validates all prior REQs end-to-end).
**Critical path**: yes (final).
**Parallel-track?**: no.
**Research flag**: no.
**Ship-critical?**: P1.
**Exit criteria**:
  1. v2.0.0 tag created (CalVer).
  2. Railway multi-service (web + worker + Redis + Oxigraph) deploy green.
  3. Public SPARQL endpoint announced + smoke-tested from external client.
  4. Benchmark corpora (v1 advocacy + FRE + Restatement of Contracts) live + queryable.
**Plans**: TBD

---

## 4. Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. Foundations / HARD GATE | 0/? | Not started | - |
| 1. Polysemy / distinguo Spike | 0/? | Not started | - |
| 2. Shard Envelope | 0/? | Not started | - |
| 3. Shard Subtypes | 0/? | Not started | - |
| 4. IRI Scheme | 0/? | Not started | - |
| 5. Content Versioning | 0/? | Not started | - |
| 6. DID Substrate | 0/? | Not started | - |
| 7. Governance Model | 0/? | Not started | - |
| 8. FOLIO v2 Vocab + Mini-BFO | 0/? | Not started | - |
| 9. Seven Design Principles | 0/? | Not started | - |
| 10. Pipeline + LLM-Agnostic | 0/? | Not started | - |
| 11. SHACL Hybrid | 0/? | Not started | - |
| 12. Observability | 0/? | Not started | - |
| 13. Storage Layer | 0/? | Not started | - |
| 13.5. Private Corpora | 0/? | Not started | - |
| 14. UI Design Contract | 0/? | Not started | - |
| 15. Review UI | 0/? | Not started | - |
| 16. Public SPARQL + Write API | 0/? | Not started | - |
| 17. Testing Consolidation | 0/? | Not started | - |
| 18. Community Artifacts + Docs | 0/? | Not started | - |
| 18.5. Corpus Fork + Genealogy (P2) | 0/? | Not started | - |
| 19. Pre-Release Security Audit | 0/? | Not started | - |
| 20. Release Cut | 0/? | Not started | - |

---

## 5. P1 Coverage Validation

All P1 REQ-IDs mapped to at least one phase. P2 REQ-IDs marked with `(P2)`.

| REQ-ID | Priority | Phase(s) |
|--------|----------|----------|
| SHARD-01 | P1 | 2 |
| SHARD-02 | P1 | 3 |
| SHARD-03 | P1 | 3 |
| SHARD-04 | P1 | 3 |
| SHARD-05 | P1 | 3 |
| SHARD-06 | P1 | 3 |
| SHARD-07 | P1 | 4 |
| SHARD-08 | P1 | 4 |
| SHARD-09 | P1 | 5 |
| SHARD-10 | P1 | 2 |
| DID-01 | P1 | 6 (6.1) |
| DID-02 | P1 | 6 (6.1) |
| DID-03 | P1 | 6 (6.1) |
| DID-04 | P1 | 6 (6.1) |
| DID-05 | P1 | 6 (6.1) |
| DID-06 | P1 | 6 (6.1), 19 |
| DID-07 | P1 | 6 (6.1) |
| DID-08 | P2 | 6 (6.2) |
| DID-09 | P2 | 6 (6.3) |
| GOV-01 | P1 | 7 |
| GOV-02 | P1 | 7 |
| GOV-03 | P1 | 7 |
| GOV-04 | P1 | 7 |
| GOV-05 | P1 | 7 |
| GOV-06 | P1 | 7 |
| GOV-07 | P1 | 7 |
| GOV-08 | P1 | 7, 18 |
| GOV-09 | P2 | 7 |
| GOV-10 | P2 | 7 |
| VOCAB-01 | P1 | 8 |
| VOCAB-02 | P1 | 1 (spike), 8 |
| VOCAB-03 | P1 | 8 |
| VOCAB-04 | P1 | 8 |
| VOCAB-05 | P1 | 8 |
| PRINCIPLE-01 | P1 | 9 (9.P1) |
| PRINCIPLE-02 | P1 | 9 (9.P2) |
| PRINCIPLE-03 | P1 | 9 (9.P3) |
| PRINCIPLE-04 | P1 | 9 (9.P4) |
| PRINCIPLE-05 | P1 | 9 (9.P5) |
| PRINCIPLE-06 | P1 | 1 (spike), 9 (9.P6) |
| PRINCIPLE-07 | P1 | 9 (9.P7) |
| LLM-01 | P1 | 10 |
| LLM-02 | P1 | 10 |
| LLM-03 | P1 | 10 |
| LLM-04 | P1 | 10 |
| LLM-05 | P1 | 10 |
| LLM-06 | P1 | 10 |
| SHACL-01 | P1 | 11 |
| SHACL-02 | P1 | 11 |
| SHACL-03 | P1 | 11 |
| SHACL-04 | P1 | 11 |
| SHACL-05 | P1 | 11 |
| STORAGE-01 | P1 | 13 |
| STORAGE-02 | P1 | 13 |
| STORAGE-03 | P1 | 13 |
| STORAGE-04 | P1 | 0, 13 |
| STORAGE-05 | P1 | 13 |
| STORAGE-06 | P1 | 13 |
| STORAGE-07 | P1 | 13 |
| SPARQL-01 | P1 | 16 |
| SPARQL-02 | P1 | 16 |
| SPARQL-03 | P1 | 16 |
| SPARQL-04 | P1 | 16 |
| SPARQL-05 | P1 | 16 |
| SPARQL-06 | P1 | 16 |
| SPARQL-07 | P1 | 16 |
| SPARQL-08 | P1 | 16 |
| SPARQL-09 | P2 | 16 (16.explain-query) |
| SPARQL-10 | P2 | 16 (16.sse-streaming) |
| SPARQL-11 | P2 | 16 (16.rdf12-helper) |
| SPARQL-12 | P2 | 16 (16.graph-result) |
| SPARQL-13 | P1 | 16 |
| SPARQL-14 | P1 | 16 |
| UI-01 | P1 | 14 |
| UI-02 | P1 | 15 (15.shard-page) |
| UI-03 | P1 | 15 (15.shard-page) |
| UI-04 | P1 | 15 (15.shard-page) |
| UI-05 | P1 | 15 (15.shard-page) |
| UI-06 | P1 | 15 (15.polysemy-fork) |
| UI-07 | P1 | 15 (15.polysemy-fork) |
| UI-08 | P1 | 15 (15.supersession-timeline) |
| UI-09 | P1 | 15 (15.supersession-timeline) |
| UI-10 | P1 | 15 (15.contest-wizard + 15.retract-supersede-disambiguation) |
| UI-11 | P1 | 15 (15.dependency-graph) |
| UI-12 | P1 | 15 (15.dependency-graph) |
| UI-13 | P1 | 15 (15.polysemy-fork + 15.contest-wizard) |
| UI-14 | P1 | 15 (15.polysemy-fork + 15.contest-wizard) |
| UI-15 | P2 | 15 (15.shard-page stretch) |
| UI-16 | P2 | 15 (15.shard-page stretch) |
| UI-17 | P2 | 15 (15.shard-page stretch) |
| UI-18 | P1 | 14 |
| UI-19 | P1 | 14 |
| CORPUS-01 | P1 | 13 |
| CORPUS-02 | P1 | 13 |
| CORPUS-03 | P1 | 13 |
| CORPUS-04 | P1 | 13 |
| CORPUS-05 | P1 | 7 |
| CORPUS-06 | P1 | 13.5 |
| CORPUS-07 | P1 | 13.5 |
| CORPUS-08 | P2 | 18.5 |
| CORPUS-09 | P2 | 18.5 |
| OBS-01 | P1 | 12 |
| OBS-02 | P1 | 12 |
| OBS-03 | P1 | 12 |
| OBS-04 | P1 | 0, 12 |
| SEC-01 | P1 | 0 |
| SEC-02 | P1 | 0 |
| SEC-03 | P1 | 19 |
| SEC-04 | P1 | 16, 19 |
| SEC-05 | P1 | 6 (6.1), 17, 19 |
| SEC-06 | P1 | 6 (6.1), 19 |
| QUALITY-01 | P1 | 0, 13, 16 |
| QUALITY-02 | P1 | 14, 15 |
| QUALITY-03 | P1 | 0 |
| QUALITY-04 | P1 | 0 |
| QUALITY-05 | P1 | 15 (15.polysemy-fork + 15.contest-wizard) |
| QUALITY-06 | P1 | 17 |

**Coverage summary**:

- P1 REQ-IDs: all mapped (0 orphans)
- P2 REQ-IDs: all mapped (0 orphans)
- Intentional multi-phase mappings: SEC-05, SEC-06, QUALITY-01, QUALITY-02, GOV-08, STORAGE-04, OBS-04, SEC-04, VOCAB-02, PRINCIPLE-06, DID-06 — each is either an audit re-verification (Phase 19), a cross-phase quality measurement (Phase 0 sets SLO, downstream phases re-measure), or a spike-then-implement pattern (Phase 1 spike → Phase 9.P6 impl).

---

## 6. Phase Numbering & Critical-Path Notes

- **Phase numbering reset**: v1.0 and v1.1 phases are archived under `.planning/milestones/v1.0-phases/` and `.planning/milestones/v1.1-phases/`. v2.0 begins at Phase 0.
- **Integer phases**: 0–20 are planned milestone work.
- **Decimal phases** (13.5, 18.5): Pre-planned inserts for aggressive-GA scope promotions — **NOT** `/gsd-insert-phase` urgent inserts. Numbered decimal to signal they sit between integers in dependency order.
- **Critical-path chain (16 phases)**: 0 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 13 → 13.5 → 14 (gate for 15) → 15 → 16 → 17 → 19 → 20. Phase 14 may execute in parallel with 8/9/10/11 but **must finish before 15 opens**.
- **Parallel tracks (4 phases)**: Phase 1 (parallel with 2), Phase 12 (parallel from 6), Phase 14 (parallel from 8 but gates 15), Phase 18 (parallel from 7). Phase 18.5 is P2-stretch and non-blocking.
- **Research-flag phases** (per research §Research Flags): 0, 6, 9 (9.P6), 11, 14, 15 (15.polysemy-fork, 15.contest-wizard), 16, 19. Each should trigger `/gsd-research-phase` before `/gsd-plan-phase`.

---

*Roadmap drafted: 2026-04-22*
*Source-of-truth requirements: `.planning/REQUIREMENTS.md`*
*Next: orchestrator review → commit → `/gsd-discuss-phase 0` (HARD GATE) → `/gsd-plan-phase 0`*
