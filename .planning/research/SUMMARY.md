# Project Research Summary

**Project:** FOLIO Insights v2.0 — shards-as-axioms milestone
**Domain:** Federated shard-based legal knowledge graph with DID-signed attestations, SPARQL endpoint, and polysemy-first review UI (refactor-in-place on v1.1 FastAPI / SvelteKit / aiosqlite base)
**Researched:** 2026-04-20
**Confidence:** HIGH on stack + architecture; MEDIUM-HIGH on features; HIGH on pitfalls

## Executive Summary

v2.0 is a **refactor-in-place** — not a rewrite — layered on the existing v1.1 extraction pipeline, FastAPI app, and SvelteKit viewer. The locked 40+ decisions from the milestone brief (Oxigraph/pyoxigraph, owlready2, instructor, Arq, SvelteKit 5 adapter-node, DID via did:key/web/plc, OAuth binding, PROV-O governance) are **all validated against PyPI on research date and still current-stable**, with four concrete risks surfaced that the brief didn't anticipate. The v1 7-stage pipeline is preserved; a **new Stage 8 "Shard Minter"** converts each `KnowledgeUnit` into a 15-field Pydantic `Shard`, signs it with a DID, SHACL-validates it, cluster-validates it (owlready2+HermiT), and bulk-loads it into pyoxigraph with a parallel rdflib bridge for pyshacl/JSON-LD. The v1 aiosqlite DB is preserved for relational indexes; pyoxigraph becomes the RDF system of record. A new `worker` Docker stage adds a JVM for HermiT; the `web` stage stays JVM-free.

The research surfaces **four corrections/additions to the brief** that must land in the roadmap: (1) **owlready2 is NOT pure-Python** — HermiT ships as a JVM jar (RISK-1); (2) **no off-the-shelf Pydantic-to-SHACL generator exists** — ~150 LOC must be written in-repo (RISK-2); (3) **pyoxigraph 0.5.x dropped RDF-star in favor of RDF 1.2** — triple terms in subject position no longer work, which invalidates several PRD §20 example queries and requires a syntax audit (**BLOCKING Phase 0**); (4) **identity stack needs specific picks** — `authlib > fastapi-users` (DID-first identity), `PyNaCl + cryptography + atproto + dag-cbor + jcs` for DID signing, `didkit` is dead and must be avoided. Feature-space research confirms v2.0's novelty zone — **polysemy forks with analogia predicates, contest-vs-supersede-vs-retract three-way split, DID-signed per-action attestations** — has no direct UX precedent; Wikidata/Solid/ActivityPub/YASGUI inform table stakes but not the hard cases, so the `/gsd-discuss-phase` work for Phase 15 UI must budget design iteration time.

Key risks are all **mitigable with discipline**: Phase 0 is a **hard gate** with 7 deliverables (Oxigraph spike, HermiT perf baseline, Dagger CI, 1M-triple load generator, SSR streaming prototype) that either validate the stack or trigger a pivot (Fuseki / Rust `reasonable` reasoner / defer streaming). The critical-path chain `0 → 2 → 3 → 6 → 7 → 8 → 9 → 10 → 11 → 13 → 14 → 15 → 16 → 17 → 19 → 20` is ~16 phases; observability (Phase 12), community artifacts (Phase 18), and UI design (Phase 14) can **parallel-track** off critical path. Security audit (Phase 19) is non-negotiable before release — DID signing, OAuth, rate limiting, and write API input validation all require scrutiny, and two BLOCKING security pitfalls (SPARQL `SERVICE` SSRF, DID key-rotation break of historical signatures) must be addressed by design, not post-hoc.

## Key Findings

### Recommended Stack

The locked stack validates against the latest PyPI releases (all 40+ packages verified same-day as research). The **one correction** is that `owlready2` is not pure-Python and requires JVM 17 in the worker Docker stage (+~200 MB). The **one gap** is the absence of a Pydantic-to-SHACL generator library, requiring ~150 LOC in-repo (`src/folio_insights/shapes/pydantic_to_shacl.py`). See `.planning/research/STACK.md` for full version pins.

**Core technologies:**
- **pyoxigraph 0.5.7** — canonical RDF 1.2 / SPARQL-star store (RocksDB, ~200K triples/sec insert); replaces rdflib-on-SQLite from v1
- **rdflib 7.6.0** — bridge adapter only (pyshacl input + JSON-LD + Turtle-star canonicalization); NOT the primary store
- **pyshacl 0.31.0 + owlready2 0.50 (HermiT/JVM)** — SHACL validation + OWL 2 EL TBox reasoning; cluster validator runs in worker tier only
- **instructor 1.15.1** — LLM provider abstraction (Claude default; OpenAI + Ollama CI matrix); replaces v1's direct Anthropic calls
- **Arq 0.28.0 + Redis 7.4** — async job queue; replaces v1's disk-based job_manager
- **SvelteKit 5.55.4 + adapter-node 5.5.4 + Vite 8.0.9** — SSR replaces v1's adapter-static; unlocks deep-link shard pages + SSE streaming
- **FastAPI 0.136.0 + Pydantic 2.13.3 + authlib 1.7.0** — preserved/extended from v1; adds OAuth + DID middleware
- **DID crypto stack** — `cryptography` + `PyNaCl` (ed25519 hot path) + `joserfc` (JWS) + `atproto` (did:plc resolver) + `dag-cbor` + `jcs` (RFC 8785); reject `didkit`, `pydid`, `python-jose`, `fastapi-users`
- **Observability triple** — structlog 25.5.0 + OpenTelemetry 1.41.0 + prometheus-client 0.25.0
- **Dev tooling** — ruff 0.15.11, mypy 1.20.1 strict, pytest 9.0.3, Playwright 1.59.1 + axe-core 4.11.3 (WCAG 2.1 AA gate)

### Expected Features

v2.0 inherits UX patterns from five overlapping ecosystems (Wikidata/Wikibase statement ranks, Solid/LDP content negotiation, ActivityPub HTTP signatures, IETF RFC process, YASGUI/SPARQL tooling) but diverges in three novel zones with **no direct precedent**: (A) polysemy forks via `distinguo` with analogia predicates, (B) three-way contest-vs-supersede-vs-retract disambiguation, (C) DID-signed per-action attestations over content hashes. 10 categories A–J; see FEATURES.md.

**Must have (P1, GA):**
- 15-field shard envelope + 5 subtypes (SimpleAssertion, DisputedProposition, ConflictingAuthorities, Gloss, Hypothesis)
- Provenance-hash IRIs + content-negotiated dereference
- DID-signed attestations on every action + signature-verification badge
- Governance model (4 role tiers, PROV-O log, RFC process)
- FOLIO v2 vocabulary + mini-BFO spine
- All 7 §8 design principles (cluster validator, framework detector, dependency graph, TBox/ABox, closed-world, polysemy detector, BFO classifier)
- LLM-provider-agnostic pipeline (Claude default; OpenAI + Ollama CI)
- SHACL hybrid (Pydantic-gen + 6 hand-written shapes)
- Review UI: deep-link pages, polysemy fork UI, supersession timeline, contest/supersede/retract wizards, SPARQL explorer
- Public SPARQL read endpoint + DID-gated REST write API (NOT SPARQL UPDATE on public endpoint)
- Community artifacts: CONTRIBUTING, CoC (Contributor Covenant 2.1), GOVERNANCE, RFC
- WCAG 2.1 AA + P95 SPARQL <500ms @ 1M triples

**Should have (P1/P2 differentiators):**
- Dependency graph visualizer; prime-analogate picker + proportional-relation editor; retraction cascade preview; warrant trace-back UI; pre-shipped SPARQL query templates; streaming SSE results; governance log timeline viewer; "What will I be signing?" preview

**Defer (v2+):**
- Hardware-key signing; multi-sig attestations; corpus fork genealogy; "Explain this query" LLM helper; GraphQL endpoint; live WebSocket subscriptions; mobile-first apps

**Explicit anti-features (DO NOT BUILD):**
- Inline shard editing on public pages; vote up/down (§21.10); hide rejected objections; auto-apply distinguo; majority-vote contest resolution; unified delete button; unrestricted SPARQL UPDATE; server-held signing keys; anonymous contributions; auto-sync between corpora

### Architecture Approach

**Refactor-in-place.** v1.1's 7-stage pipeline preserved; new **Stage 8 (Shard Minter)** appended. Web tier augmented; SvelteKit adapter-static → adapter-node swap. Two-stage Docker split isolates JVM to worker; web stays lean.

**Major components:**
1. **Shard Minter** (NEW, §6) — `KnowledgeUnit` → 15-field `Shard` with subtype routing, provenance-hash IRI, framework detection, BFO classification, DID signing
2. **DID Signer/Verifier** (NEW, §6.5) — did:key/web/plc; JCS canonicalization; signing-time key capture
3. **pyoxigraph Store** (REPLACES rdflib-as-store) — RDF 1.2 / SPARQL-star; named graphs per corpus + shared TBox + per-corpus governance log
4. **rdflib Bridge** (AUGMENT) — adapter only; pyshacl + JSON-LD + Turtle-star
5. **SHACL Validator** (AUGMENT) — 6 hand-written shapes + Pydantic-to-SHACL generator
6. **Cluster Validator** (NEW, §P1) — owlready2+HermiT subprocess; WORKER TIER ONLY; async warn-only
7. **Arq Worker** (REPLACES v1 disk job_manager)
8. **FastAPI + authlib + DID middleware** (AUGMENT) — OAuth → DID binding
9. **Public SPARQL Endpoint** (NEW) — read-only, rate-limited, 30s timeout, 10K cap
10. **DID-gated Write API** (NEW) — REST wrapper; bypasses SPARQL UPDATE
11. **Governance Service** (NEW, §3.1) — PROV-O log writer
12. **Framework Registry + BFO Classifier + Polysemy Detector** (NEW, §P2/P7/P6)
13. **SvelteKit 5 SSR** — deep-link shard pages, polysemy UI, supersession timeline, SPARQL explorer, SSE streaming

**Seven v2.0 patterns:** Shard-as-Transaction; Canonical-Content-Hash as Signature Target; Named-Graph-per-Corpus + Shared TBox + Separate Governance; Pipeline Stage Append (not mutate); Worker-Side Reasoning / Web-Side Query; Append-Only Everywhere; Build-Time SHACL Generation.

### Critical Pitfalls

35+ pitfalls across 6 dimensions; **10 "sink v2.0"** per PITFALLS.md executive summary:

1. **Oxigraph 0.5.x dropped RDF-star for RDF 1.2 — `<<?s ?p ?o>>` subject position breaks** (BLOCKING Phase 0) — Phase 0 spike tests annotation pattern; pin `==0.5.7`; rewrite every §20 example; document NOT SUPPORTED; CI regression test
2. **Retraction cascade collapsed into supersession (or vice versa) — §21.9 crux** (BLOCKING Phase 9+15) — mandatory three-way disambiguation prompt; three distinct CLI commands; blast-radius preview; NO shared codepath; UX copy testing with legal users
3. **Provenance-hash IRI non-determinism (whitespace/encoding drift)** (BLOCKING Phase 4) — `canonicalize_source_span()` with NFC + LF + trim; RFC 3986 URI normalization; property test; nightly re-hash verification
4. **Public SPARQL endpoint exposes `SERVICE` / `FROM NAMED` → SSRF + DoS** (BLOCKING Phase 16+19) — strip SERVICE from AST; allow-list trusted endpoints; 30s timeout; 10K cap; rate-limit by IP + DID
5. **JCS canonicalization on `model_dump()` → signature non-determinism** (BLOCKING Phase 6) — always go through `jcs.canonicalize()`; exclude `signatures` + `content_edits`; property test `verify(sign(x))` across shuffled field orders
6. **DID key rotation breaks historical signatures** (HIGH Phase 6+19) — capture `signing_key_id` in AttestedSignature; cache historical did.json snapshots; did:plc operation-log pinning; CI `test_signature_survives_key_rotation.py`
7. **SHACL validation on rdflib bridge at 1M triples blows P95 SLO** (HIGH Phase 0+11) — Phase 0 perf harness; per-shard incremental not per-corpus batch; pre-compile shapes at startup
8. **Polysemy detector false positives on legal terms-of-art that SHOULD be polysemous** (HIGH Phase 1+9) — Phase 1 *consideration* spike; human-gated accept/reject/modify always; FP test set; per-framework threshold
9. **Arq migration leaves v1 disk-based jobs orphaned** (MEDIUM Phase 10) — side-by-side feature flag; reconciliation script; cutover at Phase 12
10. **owlready2/HermiT JVM cold-start + OOM in worker container** (MEDIUM Phase 0) — Phase 0 benchmark gate; async cluster validation; chunked; `-Xmx` tuning; fallback to Rust `reasonable`

Additional watchlist: Pydantic discriminated-union collapse (use `Literal[...]`); shard IRI collision above 2³²; governance log append-only enforcement (SHACL + SQLite triggers); role-assertion loop; FOLIO vocab churn (LD1, pin `fi:vocabVersion`); GitHub username takeover → DID impersonation (F7); SPARQL injection (Q3, `initBindings`); named-graph-unaware queries (Q4); OTel prompt-attribute bloat (I4); WCAG AA pass-once regression (U2).

## Implications for Roadmap

Research validates the brief's 20-phase structure with **one refinement and one expansion**: (a) add **Phase 0 exit gates** as explicit pass criteria (5 gates); (b) sub-phase Phase 9 per principle (9.P1..P7) and Phase 15 per UI surface.

### Phase 0: Foundations (BLOCKS ALL)
**Rationale:** Validates locked stack. Three BLOCKING risks (RDF-12, HermiT JVM, SSR streaming) resolve here or roadmap pivots.
**Delivers:** PHILOSOPHY.md rename; Oxigraph+rdflib spike; HermiT-in-Docker perf baseline; Dagger CI; 1M-triple load generator; SSR streaming prototype; two-stage Dockerfile prototype.
**Exit gates:** P95 SPARQL < 500ms @ 1M; worker image < 500 MB; SSR latency < 200ms; RDF 1.2 annotation pattern works; Dagger CI runs.

### Phase 1: Polysemy/distinguo Spike (parallel with Phase 2)
**Rationale:** Validates §16 Risk 2 via canonical *consideration* example.

### Phases 2–6: Shard Envelope & DID Substrate (SEQUENTIAL, critical path)
- **2 — §6.1 envelope:** Pydantic `Shard`; round-trip tests
- **3 — §6.2 subtypes:** Discriminated-union with `Literal` tags
- **4 — §6.3 IRI scheme:** `mint_shard_iri()` with canonicalization; collision detector
- **5 — §6.4 versioning:** `ContentEdit` + append-only SHACL guard; `get_shard_at()`
- **6 — §6.5 DID attestations:** did:key/web/plc; JCS `canonical_content_hash()`; signing-time key capture

### Phase 7: Governance Model (§3.1)
Role assertions; PROV-O log; minimum-admin invariant; append-only SHACL + SQLite triggers.

### Phase 8: FOLIO v2 Vocab + Mini-BFO Spine (§7)
`fi:*` TTL; `bfo_mapping.ttl`; `owl:versionIRI` scheme.

### Phase 9: Seven Design Principles (§8) — SUB-PHASE per principle
9.P1 cluster validator, 9.P2 framework detector, 9.P3 dependency graph, 9.P4 TBox/ABox, 9.P5 closed-world, 9.P6 polysemy, 9.P7 BFO.

### Phase 10: Pipeline + LLM-Agnostic Refactor (§9)
Stage 8 Shard Minter; `instructor.from_provider()` with CI matrix; Arq migration with side-by-side feature flag; single-layer retry.

### Phase 11: SHACL Hybrid (§10)
6 hand-written shapes + Pydantic-to-SHACL generator (~150 LOC, RISK-2); build-time TTL emission.

### Phase 12: Observability (parallelize from Phase 6)
structlog + OTel + Prometheus; prompt-attribute truncation; aggregate cost tracking.

### Phase 13: Storage Layer (§11) — GATE
Oxigraph Store; named-graph writer; rdflib bridge; nightly TTL dump; incremental SHACL.

### Phase 14: UI Design Contract (pre-§12; parallelize from Phase 8)
SvelteKit adapter-node full swap; component library skeleton; axe-core CI gate; bold aesthetic via `/gsd-ui-phase`.

### Phase 15: Review UI (§12) — SUB-PHASE per surface
15.shard-page, 15.polysemy-fork, 15.supersession-timeline, 15.contest-wizard, 15.retract-supersede-disambiguation, 15.dependency-graph, 15.sparql-explorer. Heavy `/gsd-discuss-phase` for 15.polysemy + 15.contest-wizard.

### Phase 16: Public SPARQL Endpoint
Read-only `/sparql` with SERVICE-stripping + allow-list + rate limit + timeout + cap; NO SPARQL UPDATE; `initBindings`; templates with GRAPH scoping; DID-gated REST write API; SHACL validation endpoint.

### Phase 17: Testing Consolidation (§13)
203 v1 + ~425 new tests; Tier 3 golden-set harness; DID rotation scenarios; SHACL-at-scale.

### Phase 18: Community Artifacts + Docs (§15; parallelize from Phase 7)
CONTRIBUTING, CoC, GOVERNANCE, RFC, mkdocs-material, JupyterLite, SPARQL cookbook.

### Phase 19: Pre-Release Security Audit (BLOCKS RELEASE)
Crypto; OAuth; DID rotation; SPARQL; rate limiting; write API; F7 scenario.

### Phase 20: Release Cut
v2.0.0 CalVer; Railway multi-service deploy; public SPARQL announce; benchmark corpora ingested.

### Phase Ordering Rationale

- §6 subsections strictly sequential
- §3.1 Governance requires §6.5
- §7 vocab before §8 principles
- §8 principles before §9 pipeline
- §10 SHACL before §11 storage enforcement
- Phase 14 UI design before Phase 15 per-feature UI
- Phase 19 audit is non-negotiable release gate
- Phase 0 is the meta-gate

### Research Flags

**Needs `/gsd-research-phase`:**
- Phase 0 (RDF-12 migration; HermiT JVM tuning; SSR streaming; Dagger)
- Phase 6 (DID key rotation per method; JCS edge cases; atproto for signing)
- Phase 9.P6 (polysemy FP curation; LLM-vs-rule hybrid — core novel service)
- Phase 11 (Pydantic-to-SHACL generator design)
- Phase 14 (heavy `/gsd-ui-phase`; bold aesthetic direction)
- Phase 15.polysemy, 15.contest-wizard (no UX precedent; `/gsd-discuss-phase` + UX copy testing)
- Phase 16 (SPARQL security hardening; RDF-12 templates)
- Phase 19 (security audit vendors; DID threat models)

**Standard patterns (skip):** Phase 2/3/4/5 (Pydantic v2); Phase 7 (PROV-O); Phase 8 (TTL); Phase 10 (`instructor` + Arq); Phase 12 (obs standard); Phase 13 (pyoxigraph named graphs); Phase 17 (pytest); Phase 18 (mkdocs); Phase 20 (Railway).

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | 40+ packages PyPI-verified on research date; RISK-1/2 surfaced with mitigations; RISK-3/4 flagged for Phase 0 |
| Features | MEDIUM-HIGH | Table stakes HIGH (five ecosystem precedents); differentiators HIGH (PRD decisions); novel UX zones MEDIUM-LOW (no direct precedent) — flagged for Phase 15 `/gsd-discuss-phase` |
| Architecture | HIGH | Integration seams verified against v1.1 source; PRD build order validated; two-stage Docker split solid; MEDIUM on SSR streaming |
| Pitfalls | HIGH | 35+ cross-validated across STACK RISK-1..4 + ARCHITECTURE anti-patterns + PRD §16 risks; Oxigraph drop verified from CHANGELOG; SPARQL security verified against IBM LQE CVEs + OWASP |

**Overall confidence:** HIGH — 40+ decisions hold up; four corrections addressable in Phase 0 / 6 / 11; no fundamental re-scoping needed.

### Gaps to Address

1. **SvelteKit 5 adapter-node SSE streaming** — no v1 precedent; Phase 0 prototype or defer to post-GA
2. **Oxigraph 0.5 RDF-star → RDF 1.2 exact semantics for §20 queries** — Phase 0 spike rewrites examples
3. **Polysemy detector FP tuning** — Phase 1 spike + Phase 9.P6 iterative
4. **UX for distinguo/contest/supersede** — Phase 15 UX copy testing with legal users
5. **Benchmark corpus bias (US-federal-centric)** — flag v2.1; document release notes
6. **DID key-rotation operational discipline at federated scale** — Phase 6 + Phase 19 scenarios
7. **JupyterHub self-hosting ops load** — Phase 18 runbook

## Sources

**Primary (internal):** `.planning/v2.0-MILESTONE-BRIEF.md`, `PRD-v2.0-draft-2.md`, `PHILOSOPHY.md` (pending rename), `.planning/PROJECT.md`, `.planning/research/{STACK,FEATURES,ARCHITECTURE,PITFALLS}.md`, v1.1 codebase.

**Primary (external HIGH):** pyoxigraph 0.5.7 PyPI + Oxigraph CHANGELOG 0.5.0-beta.1 (source of D1); owlready2 reasoning docs (RISK-1); instructor multi-provider integrations; Arq 0.28.0; FastAPI 0.136.0; Authlib FastAPI OAuth; W3C DID Core + did:plc spec v0.1 + AT Proto Identity; W3C PROV-O; RFC 8785 JCS; SvelteKit 5 adapter-node; sib-swiss/sparql-editor; OpenTelemetry Python 1.41.0.

**Secondary (MEDIUM):** WorkOS FastAPI auth 2026; Wikidata Help:Ranking + Deprecation; Solid Project; ActivityPub HTTP Signatures; IETF RFC process; Martin Fowler Bitemporal History; ABA Stare Decisis; Risks of did:plc; FAIR Cookbook IDs; IBM LQE CVEs.

**Tertiary (LOW, needs validation):** SvelteKit + SSE community examples; legal-KG polysemy literature; DAO governance attack patterns.

---
*Research completed: 2026-04-20*
*Ready for roadmap: yes*
*Downstream: REQUIREMENTS.md → ROADMAP.md*
