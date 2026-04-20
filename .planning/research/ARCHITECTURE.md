# Architecture Research — v2.0 shards-as-axioms

**Domain:** Federated shard-based legal knowledge graph refactor on top of existing v1.1 FastAPI / SvelteKit / aiosqlite / rdflib app
**Researched:** 2026-04-20
**Confidence:** HIGH on integration seams (verified against v1.1 source tree) and on the PRD-mandated build order (§0 companion instructions + `.planning/v2.0-MILESTONE-BRIEF.md` phase structure); MEDIUM on SSR UI integration pattern (no v1 precedent for SvelteKit 5 adapter-node streaming in this codebase; RISK-4 in STACK.md); MEDIUM on Phase 0 perf harness shape (new work, but well-precedented from pyoxigraph community benchmarks).

---

## 0. TL;DR — The One-Paragraph Architecture

**v2.0 is a *refactor-in-place*, not a rewrite.** The v1.1 four-stage extraction pipeline is wrapped, not replaced: `IngestionStage → StructureParser → BoundaryDetection → Distiller → KnowledgeClassifier → FolioTagger → Deduplicator` keeps producing `KnowledgeUnit` objects, and a **new Stage 8 (Shard Minter)** converts each unit into a 15-field Pydantic `Shard` + subtype, signs it with a DID, writes it to **pyoxigraph** (canonical store) with a parallel **rdflib bridge graph** for SHACL/JSON-LD. The v1 `aiosqlite` SQLite database is preserved for corpus/review state but augmented with two new tables (`shards`, `identity_bindings`); `pyoxigraph` becomes the RDF system of record. The v1 disk-based job manager (`api/services/job_manager.py`) is replaced by **Arq on Redis**. The v1 SvelteKit `adapter-static` viewer is swapped for **adapter-node SSR** at Phase 14, preserving the existing route structure. A new `worker` Docker stage adds the JVM for `owlready2`/HermiT; the `web` stage stays JVM-free. **Phase 0 is non-negotiable**: an Oxigraph+rdflib-bridge spike, a HermiT-in-Docker perf baseline, the Dagger CI skeleton, and a synthetic 1M-triple load generator all land *before* §6.1 work begins — they are the gates that validate whether the locked stack actually meets the P95 < 500ms SLO.

---

## 1. System Overview — Target v2.0 Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                   EDGE:  Browsers, SPARQL clients, AI/RAG                     │
└───┬──────────────────────┬─────────────────────────┬─────────────────────────┘
    │ HTML (SSR)           │ SPARQL/JSON            │ TTL / JSON-LD
    │                      │ SSE (streaming)        │ (content-negotiated)
    │                      │                        │
┌───▼──────────────────────▼────────────────────────▼─────────────────────────┐
│                     WEB TIER   (JVM-free Docker stage)                       │
│  ┌────────────────────┐   ┌──────────────────┐   ┌────────────────────────┐ │
│  │ SvelteKit 5 SSR    │   │ FastAPI 0.136    │   │ SPARQL Endpoint        │ │
│  │ adapter-node       │◄──┤ (preserved v1    │◄──┤ /sparql (read-only)    │ │
│  │ /shard/{iri}       │   │  app augmented)  │   │ /sparql/write (DID gate│ │
│  │ /polysemy/...      │   │ + authlib OAuth  │   │  via REST wrapper)     │ │
│  │ /supersession/...  │   │ + DID middleware │   │ pyoxigraph.Store.query │ │
│  │ /sparql (YASGUI)   │   └────────┬─────────┘   └────────┬───────────────┘ │
│  └────────────────────┘            │                      │                  │
│                                    │ enqueue              │ read             │
└────────────────────────────────────┼──────────────────────┼──────────────────┘
                                     │                      │
                 ┌───────────────────▼───────┐              │
                 │ Redis 7.4 (Arq queue +   │              │
                 │ rate-limit + idem-keys)   │              │
                 └───────────┬───────────────┘              │
                             │ dequeue                      │
                             │                              │
┌────────────────────────────▼──────────────────────────────┼──────────────────┐
│                  WORKER TIER   (JVM-bearing Docker stage) │                  │
│                                                           │                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │                  │
│  │ v1 Pipeline  │  │ Shard Minter │  │ SHACL Validator│   │                  │
│  │ (7 stages,   │─▶│ (new §6.1-   │─▶│ (pyshacl +     │   │                  │
│  │  KnowledgeU  │  │  §6.5; 5     │  │  per-subtype   │   │                  │
│  │  out)        │  │  subtypes;   │  │  shapes §10)   │   │                  │
│  │              │  │  DID sign)   │  │                │   │                  │
│  └──────────────┘  └──────┬───────┘  └───────┬────────┘   │                  │
│                           │                  │            │                  │
│                           │ Shard model      │ Shape      │                  │
│                           ▼                  ▼ violations │                  │
│              ┌──────────────────────────────────────┐    │                  │
│              │ Cluster Validator (owlready2/HermiT) │    │                  │
│              │   — JVM subprocess —                 │    │                  │
│              └──────────────┬───────────────────────┘    │                  │
│                             │                             │                  │
│                             ▼                             │                  │
│  ┌──────────────────────────────────────────────────┐    │                  │
│  │ Graph Writer                                     │◄───┤                  │
│  │   • rdflib.Graph (bridge): SHACL + JSON-LD +     │    │                  │
│  │     Turtle-star canonicalization                 │    │                  │
│  │   • pyoxigraph.Store.bulk_load() (canonical):   │    │                  │
│  │     RDF-star; named graphs per corpus            │────┼──────────────────┘
│  └──────────────────────────────────────────────────┘    │
│                                                           │
└───────────────────────────────────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────────────────────┐
│                           PERSISTENCE                                          │
│  ┌──────────────────┐   ┌─────────────────────┐   ┌──────────────────────┐    │
│  │ pyoxigraph       │   │ SQLite (aiosqlite)  │   │ FAISS (sentence-     │    │
│  │ RocksDB          │   │  • review.db (v1)   │   │  transformers;       │    │
│  │  • abox/*.ttl-g  │   │  • shards.db (v2):  │   │  preserved from v1)  │    │
│  │  • tbox.ttl-g    │   │    - shard_index    │   │                      │    │
│  │  • governance.g  │   │    - identity_bind  │   │                      │    │
│  │  • vocab.ttl-g   │   │    - attest_cache   │   │                      │    │
│  │  RDF 1.2 / SPARQL│   │    - corpus_config  │   │                      │    │
│  │  -star           │   │    - govern_log(v2) │   │                      │    │
│  └──────────────────┘   └─────────────────────┘   └──────────────────────┘    │
│                                                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐   │
│  │ Git-backed TTL corpora (nightly dump + commit, per brief backup policy)│   │
│  └────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
                      Observability: structlog JSON → stdout
                        OpenTelemetry OTLP/gRPC → collector
                        Prometheus /metrics (scraped)
```

### 1.1 Component Responsibilities (v2.0 target)

| Component | Status | Responsibility | v1 Origin | New File(s) |
|---|---|---|---|---|
| **SvelteKit 5 SSR** | REWRITE (adapter swap + new routes) | Per-shard HTML pages, polysemy/supersession UI, SPARQL explorer, streaming SSE | `viewer/` adapter-static | `viewer/src/routes/shard/[iri]/+page.server.ts`, `/polysemy`, `/supersession`, `/sparql` |
| **FastAPI app** | AUGMENT | HTTP entry, routing, OAuth+DID middleware, SSE streaming | `api/main.py` | `api/auth/`, `api/sparql.py`, `api/shards.py`, `api/attestation.py` |
| **OAuth + DID middleware** | NEW | `authlib` GitHub/Google flow → DID binding table → per-request `request.state.did` | — | `api/auth/oauth.py`, `api/auth/did_binding.py` |
| **Public SPARQL endpoint** | NEW | Read-only SPARQL 1.1 + SPARQL-star against pyoxigraph; rate-limited, timeout 30s, size-capped | — | `api/sparql.py` |
| **DID-gated write API** | NEW | REST wrapper that validates DID sig → SHACL → ingests; `POST /api/shards` | — | `api/shards.py`, `api/attestation.py` |
| **Arq worker** | REPLACE | Async job queue (extraction, shard-mint, export, nightly dump); replaces v1 disk-based job manager | `api/services/job_manager.py`, `pipeline_runner.py`, `discovery_runner.py` | `worker/tasks.py`, `worker/settings.py` |
| **v1 extraction pipeline** | PRESERVE | 7-stage ingest→boundary→distill→classify→tag→dedupe flow producing `KnowledgeUnit`s | `src/folio_insights/pipeline/` | unchanged internally; called from `worker/tasks.py` |
| **Shard Minter** | NEW (core §6) | `KnowledgeUnit` + metadata → typed `Shard` with 15-field envelope; subtype routing; provenance-hash IRI mint; `first_extractor_did` attestation | — | `src/folio_insights/shards/minter.py`, `shards/subtype_router.py`, `shards/iri.py` |
| **DID signer / verifier** | NEW (core §6.5) | `did:key`/`did:web`/`did:plc` sign + verify over canonical content hash; pluggable method backends | — | `src/folio_insights/did/{key,web,plc,signer,verifier,canonicalize}.py` |
| **SHACL validator** | AUGMENT | v1 has `shacl_validator.py` for OWL export; v2 adds per-subtype + envelope + attestation + governance shapes; Pydantic-to-SHACL generator | `src/folio_insights/services/shacl_validator.py`, `shapes.ttl` | `src/folio_insights/shapes/{envelope,attestation,governance,supersession,...}.shacl.ttl`, `shapes/pydantic_to_shacl.py` |
| **Cluster validator** | NEW (§P1) | Runs `owlready2`+HermiT against a cluster (source doc / subtree / doctrinal neighborhood); detects cross-shard contradictions | — | `src/folio_insights/validation/cluster_validator.py` — **JVM-dependent; worker stage only** |
| **Graph writer** | NEW | Serializes `Shard` → rdflib graph (for SHACL + JSON-LD) → bulk-loads into pyoxigraph named graph | — | `src/folio_insights/storage/graph_writer.py` |
| **pyoxigraph store** | REPLACE (vs rdflib-as-store in v1) | Canonical RDF 1.2 / SPARQL-star; RocksDB backend; named graphs per corpus | rdflib-on-SQLite in v1 storage | `src/folio_insights/storage/oxigraph_store.py` |
| **rdflib bridge** | AUGMENT (scope change) | In v2, rdflib is ONLY a bridge for pyshacl input + JSON-LD serialization + Turtle-star canonicalization — NOT the primary store | `src/folio_insights/services/owl_serializer.py` | `src/folio_insights/storage/rdflib_bridge.py` |
| **folio-enrich bridge** | PRESERVE | FolioService / EntityRuler / reconciler — continues to provide 27K+ labels | `src/folio_insights/services/bridge/` | unchanged |
| **Instructor LLM pipeline** | REPLACE (§9) | `instructor.from_provider()` abstraction; Claude default; OpenAI + Ollama in CI | `llm_bridge.py` direct Anthropic calls | `src/folio_insights/llm/client.py`, `llm/prompts/`, `llm/extraction.py` |
| **Governance service** | NEW (§3.1) | Role assertions, promotion/demotion/contest/supersede workflows, PROV-O log writer | — | `src/folio_insights/governance/{roles,promotion,contest,supersede,log}.py` |
| **Framework registry** | NEW (§P2) | Per-corpus framework definitions; framework-detector; `fi:Framework` individuals | — | `src/folio_insights/frameworks/{registry,detector}.py` |
| **BFO classifier** | NEW (§P7) | FOLIO → mini-BFO mapping table + rule-based classifier + LLM fallback | — | `src/folio_insights/bfo/{spine,classifier}.py`, `bfo_mapping.ttl` |
| **Polysemy detector** | NEW (§P6) | Flags same-IRI shards with framework-conflicting axioms; proposes distinguo forks | — | `src/folio_insights/polysemy/{detector,distinguo,prototype_cluster}.py` |
| **Attestation registry** | NEW | Verification cache (`fi:verified true` annotations); failed-verification blocks write | — | `src/folio_insights/did/verifier.py` + SQLite `attestation_cache` table |
| **Observability layer** | NEW (cross-cutting) | structlog JSON logging, OTel spans wrapping every instructor call + SHACL run + SPARQL query, Prometheus counters/histograms | — | `src/folio_insights/observability/{logging,tracing,metrics}.py` |

### 1.2 Per-Tier Deployment Shape

| Tier | Runtime | Docker stage | Critical deps | Why the split |
|---|---|---|---|---|
| **Web** | Python 3.11 + FastAPI + SvelteKit SSR | `web` (JVM-free, ~200 MB) | pyoxigraph (read), authlib, structlog, OTel, redis-py | SPARQL reads don't need HermiT. JVM-free = fast Railway cold starts. |
| **Worker** | Python 3.11 + Arq + OpenJDK 17 JRE | `worker` (JVM-bearing, ~400 MB) | instructor, owlready2+HermiT, pyshacl, pyoxigraph (write), DID crypto, sentence-transformers, folio-enrich | Cluster validator requires JVM. Bulk extraction isolated from user-facing latency. |
| **Redis** | Redis 7.4 | external (Railway plugin) | — | Arq backend + rate limiter + idempotency keys + OAuth state |

**Rationale for two-stage Dockerfile:** STACK.md RISK-1 — `owlready2` is NOT pure-Python; HermiT ships as a JVM jar. Putting it in `web` would add ~200 MB + ~1-2s cold start to every web container. Splitting isolates the JVM to the worker and keeps the public-facing tier lean. The `web` container mounts pyoxigraph read-only (or connects to a shared RocksDB volume); the `worker` container has write access.

---

## 2. Integration Seams: What Gets Wrapped, What Gets Rewritten

This is the load-bearing table. Every v2.0 feature touches v1.1 code in one of four ways:

### 2.1 Seam Taxonomy

| Seam Type | Meaning | v2.0 Examples |
|---|---|---|
| **PRESERVE** | v1 code runs unchanged; new code calls it | v1 pipeline stages, `folio-enrich` bridge, `IRIManager` (v1 `src/folio_insights/services/iri_manager.py`), sentence-transformers FAISS, `CorpusManifest` model |
| **AUGMENT** | v1 code gets new methods/fields added without breaking existing callers | FastAPI app (new routers added), SHACL validator (new shapes), SQLite schema (new tables alongside existing `review.db`), Corpus model (new `framework_id`, `shacl_mode`, `retention_policy` columns) |
| **ADAPT** | v1 outputs feed new components via a new adapter; v1 internals unchanged | `KnowledgeUnit` → `Shard` via Shard Minter adapter, v1 extraction.json → shard-mint import path |
| **REPLACE** | v1 code deleted in favor of new implementation; callers rewired | `llm_bridge.py` (direct Anthropic) → `instructor.from_provider()`; `job_manager.py` (disk-based) → Arq; SvelteKit `adapter-static` → `adapter-node`; rdflib-as-store → pyoxigraph-as-store |

### 2.2 File-Level Integration Map

| v1 file | Seam | v2.0 change | Phase |
|---|---|---|---|
| `src/folio_insights/models/knowledge_unit.py` | PRESERVE | Unchanged; remains stage output | — |
| `src/folio_insights/models/corpus.py` | AUGMENT | Add `framework_id`, `shacl_enforcement`, `retention_policy`, `reviewer_roles` fields | Phase 2 (envelope) + Phase 7 (governance) |
| `src/folio_insights/models/review.py` | AUGMENT | Add `shard_iri` (nullable during migration), `did_attested` fields | Phase 6 (DID) |
| `src/folio_insights/models/task.py` | PRESERVE | Task trees still valid; link via `elaborates` edges | — |
| `src/folio_insights/pipeline/orchestrator.py` | AUGMENT | Add Stage 8 (Shard Minter) after Stage 7 (Deduplicator); preserve checkpoint shape | Phase 10 |
| `src/folio_insights/pipeline/stages/*` | PRESERVE | Seven stages untouched; new stage appended | — |
| `src/folio_insights/pipeline/discovery/orchestrator.py` | AUGMENT | Emit polysemy-detection + cluster-validation signals as new stage outputs | Phase 9 |
| `src/folio_insights/services/bridge/folio_bridge.py` | PRESERVE | 27K+ label lookup continues unchanged | — |
| `src/folio_insights/services/bridge/llm_bridge.py` | REPLACE | Swap direct Anthropic calls for `instructor.from_provider()` | Phase 10 |
| `src/folio_insights/services/iri_manager.py` | PRESERVE (augmented by new `shards/iri.py`) | v1 IRI gen stays for FOLIO concept IRIs; new `shards/iri.py` mints provenance-hash shard IRIs | Phase 4 |
| `src/folio_insights/services/owl_serializer.py` | REPLACE | New `storage/graph_writer.py` takes over; old module retained as export-path for v1 compat until v2.0-final | Phase 13 |
| `src/folio_insights/services/shacl_validator.py` | AUGMENT | Extend with per-subtype shapes; add generator for Pydantic-base shapes | Phase 11 |
| `src/folio_insights/services/jsonld_builder.py` | AUGMENT | Feed from rdflib bridge graph (new); emit framed JSON-LD per PRD | Phase 13 |
| `src/folio_insights/services/changelog_generator.py` | AUGMENT | Read content_edits + governance log PROV-O; emit reverse-chronological view | Phase 7 |
| `src/folio_insights/services/task_exporter.py` | PRESERVE | Task export still valid | — |
| `src/folio_insights/services/corpus_registry.py` | AUGMENT | Add per-corpus SHACL enforcement flag, framework list, role assertions | Phase 7 |
| `src/folio_insights/services/contradiction_detector.py` | ADAPT | NLI output becomes input to `ConflictingAuthoritiesShard` subtype router | Phase 3 |
| `src/folio_insights/cli.py` | AUGMENT | Add new commands: `did generate`, `sign`, `verify`, `edit`, `history`, `at`, `supersede`, `contest`, `resolve-contest`, `promote`, `demote`, `distinguo`, `framework register` | Phase 6 + 7 |
| `api/main.py` | AUGMENT | Add OAuth + DID middleware; register new routers for `shards`, `sparql`, `attestation`, `governance`, `distinguo`, `supersession` | Phase 14 + 15 |
| `api/routes/*.py` | AUGMENT | Existing routes preserved; new routes added in parallel | Phase 15+16 |
| `api/services/job_manager.py` | REPLACE | Delete; Arq replaces it — migration path: keep both running during Phase 10 under feature flag, cut over at Phase 12 | Phase 10/12 |
| `api/services/pipeline_runner.py` | REPLACE | Delete; becomes `worker/tasks/run_pipeline.py` Arq task | Phase 10 |
| `api/services/discovery_runner.py` | REPLACE | Delete; becomes `worker/tasks/run_discovery.py` Arq task | Phase 10 |
| `api/db/session.py` | AUGMENT | Add migrations for new shards table, identity_bindings table, governance_log_cache, attestation_cache | Phase 2+6+7 |
| `api/db/models.py` | AUGMENT | Add new SQLModel/aiosqlite schema for shard index, bindings | Phase 2+6 |
| `viewer/svelte.config.js` | REPLACE | `@sveltejs/adapter-static` → `@sveltejs/adapter-node` | Phase 14 |
| `viewer/src/routes/+page.svelte` | AUGMENT | Preserve existing landing; add SSR wrapper | Phase 14 |
| `viewer/src/routes/tasks/**` | AUGMENT | Keep v1 task review UI; overlay shard-subtype badges | Phase 15 |
| `viewer/src/routes/upload/**` | AUGMENT | Keep v1 upload flow; add DID signing step in post-ingest review | Phase 15 |
| `viewer/src/lib/stores/**` | AUGMENT | Add shard store, attestation store, governance log store | Phase 15 |
| `viewer/src/lib/components/**` | AUGMENT | Existing review components preserved; new `<ShardInspector>`, `<PolysemyFork>`, `<SupersessionTimeline>`, `<SparqlExplorer>`, `<ContestWizard>`, `<SuperssedeWizard>`, `<DependencyGraph>` added | Phase 14/15 |
| `Dockerfile` | REPLACE | Single-stage → two-stage split (`web` JVM-free + `worker` JVM-bearing); `railway.toml` picks `web` target for the Railway service; `worker` runs as separate Railway service | Phase 0 spike + Phase 12 finalization |
| `pyproject.toml` | AUGMENT | Add ~40 new deps from STACK.md; Python version unchanged | Phase 0 |
| `tests/` | AUGMENT | Keep 203 tests; add ~425 new per PRD §13 test budget | every phase |

### 2.3 Seam Anti-Patterns (Things To NOT Do)

| Anti-Pattern | Why Tempting | Why It Breaks v2.0 | Correct Approach |
|---|---|---|---|
| Wrap `KnowledgeUnit` as a `SimpleAssertionShard` synonym | Minimal code change; "just alias it" | Loses the 15-field envelope discipline; envelope validation has nothing to check | Shard Minter is a real adapter; `KnowledgeUnit` → `Shard` is a *transformation with information gain* (framework detect, BFO classify, DID sign, IRI mint) |
| Keep rdflib as the primary store "for compatibility" | v1 uses rdflib; fewer changes | Violates STACK.md decision; rdflib is ~5K triples/sec vs pyoxigraph ~200K/sec; P95 SLO fails at 1M triples | pyoxigraph is canonical; rdflib is a bridge adapter for pyshacl/JSON-LD only |
| Run HermiT inside the web tier for "query-time reasoning" | Clean mental model; reasoning is a query | JVM cold-start adds 1-2s to every web container restart; ~200 MB image bloat on user-facing tier | HermiT is offline only (cluster-validate flag in Arq worker); web tier queries pre-computed inferences |
| Put DID signing keys in server env vars for convenience | "Simpler onboarding" | Defeats the point of decentralized identity; §16 R5 security audit would block release | Client-side signing (browser/desktop); server verifies only; offer encrypted-at-rest backup |
| Enable SPARQL UPDATE on the public endpoint | "SPARQL-complete" | Bypasses DID-gated write API, SHACL, governance log, audit trail | Read-only SPARQL on public endpoint; all writes through REST wrapper that enforces the attestation pipeline |
| Reuse `api/services/job_manager.py` and "add Arq later" | Fewer Phase 10 changes | Creates two parallel job systems; observability diverges; SSE progress breaks during cutover | Replace cleanly in Phase 10 behind `FOLIO_JOB_BACKEND=arq` flag; cut over at Phase 12 |
| Emit shards as a post-hoc export from v1 pipeline rather than during the pipeline | "Keep pipeline clean" | Loses per-shard DID signing at extraction time; `first_extractor_did` becomes a retcon | Stage 8 (Shard Minter) runs *inside* the pipeline; emits signed shards directly |
| Use a single pyoxigraph graph for everything | "Simpler" | PRD §11 mandates named graphs per corpus + TBox graph + governance graph; SPARQL cross-corpus queries are first-class | Named graph per corpus + dedicated tbox + governance graphs from day one |

---

## 3. Build Order — The Dependency-Driven Phase Sequence

### 3.1 PRD-Mandated Order (§0 companion instructions)

The PRD explicitly sequences: **§6 → §7 → §8 → §9 → §10 → §11 → §12 → §13 → §14**. The milestone brief refines this into 20 phases. This research validates that sequence against the actual v1.1 codebase and identifies the minimum-viable-architecture dependencies.

### 3.2 Annotated Build Order

| # | Phase | What ships | Why in this position (dependency rationale) | Parallelizable with | Blocks |
|---|---|---|---|---|---|
| **0** | **Foundations** | `PHILOSOPHY.md` rename, Oxigraph+rdflib-bridge spike, HermiT-in-Docker perf baseline, Dagger CI skeleton, synthetic 1M-triple load generator | **BLOCKS ALL.** Validates the locked stack before any §6 work. RISK-1 (owlready2/JVM) and RISK-4 (adapter-node SSR streaming) resolve here or the roadmap pivots | — (gate phase) | Everything |
| **1** | Polysemy/distinguo spike on *consideration* | Prototype detector on the canonical PRD example; proves §16 Risk 2 mitigation works | Needs Phase 0 storage spike only | Phase 2 | Phase 9 P6 |
| **2** | **§6.1 — 15-field shard envelope** | Pydantic `Shard` model; serialize/deserialize; `aiosqlite` `shards` table alongside `review.db`; round-trip tests | Pure Pydantic; no storage-layer dependency beyond Phase 0 spike | Phase 3 (once §6.1 stable) | Phases 3-6 |
| **3** | **§6.2 — Five shard subtypes** | `SimpleAssertion`, `DisputedProposition`, `ConflictingAuthorities`, `Gloss`, `Hypothesis` classes with discriminated-union `shard_type` | Builds on §6.1 envelope | Phase 4 | Phase 9+11 |
| **4** | **§6.3 — IRI scheme** | `mint_shard_iri()` deterministic hashing; collision-check harness; content-negotiated HTTP dereference scaffold | Needs §6.1 Shard model; FastAPI already exists | — (short phase) | Phase 13+15 |
| **5** | **§6.4 — Content versioning** | `ContentEdit` model; `edit_shard_content()`; append-only SHACL guard; `get_shard_at()` historical reconstruction | Needs §6.1 + §6.5 (signatures on edits) — **ordering: §6.5 must be at least stubbed before full §6.4** | Phase 6 (stubbed) | Phase 15 edit-UI |
| **6** | **§6.5 — DID-signed attestations** | `did:key` + `did:web` + `did:plc` implementations; `canonical_content_hash()`; `AttestedSignature` model; verify-and-cache SHACL rule | Needs §6.1 envelope; `cryptography` + `pynacl` + `atproto` deps | Phase 7 | Phases 7 (governance signs attestations), 15, 16 (write API), 19 (audit) |
| **7** | **§3.1 — Governance model** | Role assertions, promotion/demotion/contest/supersede workflows, PROV-O governance log, append-only guarantees | Needs §6.5 (every governance action is a signed attestation) | Phase 8 | Phase 15 workflows, 16 write API, 18 community artifacts |
| **8** | **§7 — FOLIO v2 vocab + mini-BFO spine** | `fi:*` vocabulary TTL; `bfo_mapping.ttl`; Framework class; analogia/distinctio predicates | Needs §6 envelope (references new vocab terms) | Phase 9 | Phases 9 (principles implement on this vocab), 13 (storage imports vocab) |
| **9** | **§8 — Seven design principles** | P1 cluster validator (owlready2+HermiT), P2 framework detector, P3 dependency graph + retraction cascade, P4 TBox/ABox separator, P5 closed-world scoping, P6 polysemy detector + distinguo, P7 BFO classifier | Needs §6 + §7. **Longest phase** — consider sub-phasing per principle | Phase 10 (LLM refactor can happen in parallel once §6 shipped) | Phase 11 SHACL ref§8, Phase 15 UI surfaces services |
| **10** | **§9 — Pipeline + LLM-agnostic refactor** | Add Stage 8 (Shard Minter) to `orchestrator.py`; swap `llm_bridge.py` for `instructor.from_provider()`; Arq worker migration; CI matrix across Anthropic/OpenAI/Ollama | Needs §6 + §8 (pipeline emits shards with all principles applied) | Phase 11 | Phases 12 (obs wraps instructor calls), 13 (write path ends at pyoxigraph) |
| **11** | **§10 — SHACL hybrid** | Hand-written shapes (supersession, attestation, governance, content_edit, contest, immutable_fields) + Pydantic-to-SHACL generator (RISK-2 mitigation, ~150 LOC, in-repo) | Needs §6 + §7 + §3.1 (all models must be final before shape emission) | Phase 12 | Phase 13 (storage writes through SHACL), Phase 16 (validation API) |
| **12** | **Observability** | structlog JSON, OTel wrapping instructor + pyoxigraph + SHACL, Prometheus counters | Cross-cutting; ideally lands before Phase 13 so storage metrics ship with storage | Phase 13 | Everything thereafter (every new component instruments itself) |
| **13** | **§11 — Storage layer** | Oxigraph `Store` adapter; named-graph writer; rdflib bridge; bulk_load performance pass; nightly TTL dump + git commit; backup verification | Needs §6 + §7 + §10 (schemas must be final before bulk-load tuning) | Phase 14 | Phases 15+16 (UI + endpoint both query this) |
| **14** | **UI design contract via `/gsd-ui-phase`** | Bold "shards-as-axioms" aesthetic; SvelteKit 5 adapter-node swap; SSR scaffolding; component library skeletons | Needs nothing beyond Phase 0 spike (adapter-node streaming validated there) | Phase 15 (once adapter swap stable) | Phase 15 (all §12 UI work) |
| **15** | **§12 — Review UI** | Shard deep-link pages, polysemy fork UI, supersession timeline, contest/supersede/retract wizards, dependency graph visualizer, SPARQL explorer skeleton | Needs Phase 14 design system + Phase 9 services + Phase 13 storage | Phase 16 (SPARQL explorer can begin in parallel) | Phase 17 testing consolidation |
| **16** | **Public SPARQL endpoint** | Read-only `/sparql` with rate-limit + timeout + size cap + content negotiation; DID-gated `/api/shards` write endpoint; SHACL validation endpoint; VoID description | Needs Phase 13 storage + Phase 6 signatures + Phase 11 SHACL | Phase 18 | Phase 17, 19 |
| **17** | **§13 — Testing consolidation** | 203 v1 tests + ~425 new tests; philosophical-fidelity tests; regression tests | — | Phase 18 | Phase 19 |
| **18** | **§15 + community artifacts** | CONTRIBUTING.md, CODE_OF_CONDUCT.md, GOVERNANCE.md, RFC process, `docs/architecture/*.md`, `docs/guides/*.md` | Needs stable architecture (Phase 7+) | Phase 19 | Phase 20 release |
| **19** | **Pre-release security audit** | Crypto (ed25519, JCS, signature verification), OAuth (PKCE, state, nonce), DID signing (did:key/web/plc), rate limiting, write API input validation | **BLOCKS RELEASE** per brief §16 R5 | — | Phase 20 |
| **20** | **Release cut** | v2.0.0 CalVer tag; Railway deploy; public SPARQL announce; post-release fuller audit scheduled | — | — | — |

### 3.3 Critical Path

The critical path through 20 phases is:

```
0 → 2 → 3 → 6 → 7 → 8 → 9 → 10 → 11 → 13 → 14 → 15 → 16 → 17 → 19 → 20
```

Everything outside this chain can be parallelized.

**Why this chain:**
- §6 (envelope → subtypes → IRI → versioning → attestations) is strictly sequential (each sub-phase uses prior output)
- §3.1 Governance can only exist once attestations exist (§6.5)
- §7 vocabulary must exist before §8 principles can reference it
- §8 principles must exist before §9 pipeline can apply them
- §10 SHACL must exist before §13 storage can enforce validation on write
- Phase 14 UI design contract is a gate for any §12 UI work
- Phase 19 audit is a hard release gate

### 3.4 Parallelization Opportunities

| Parallel track | Phases | Rationale |
|---|---|---|
| **Observability track** | Phase 12 can start at Phase 6 | structlog + OTel setup only needs Python scaffolding, not domain models |
| **Community artifacts track** | Phase 18 CoC + CONTRIBUTING.md can start at Phase 7 | Docs don't need final code; governance model is settled by Phase 7 |
| **Polysemy spike track** | Phase 1 can run alongside Phase 2 | The spike uses a synthetic harness, not real shards |
| **Design system track** | Phase 14 (aesthetic + component skeletons) can begin at Phase 8 | Visual language doesn't need working services |
| **LLM provider CI matrix** | Phase 10 CI work (Anthropic+OpenAI+Ollama) can begin at Phase 8 | `instructor` integration tests don't need shards yet |
| **BFO mapping table curation** | Phase 8 starter mapping table can be hand-built before Phase 7 vocab | Pure ontology work, no code |

**The three biggest wins** in parallel scheduling are:

1. **Phase 12 observability at Phase 6.** Every new module instruments itself as it's written. Post-hoc OTel instrumentation is 3x the work.
2. **Phase 14 UI design at Phase 8.** SvelteKit adapter-node swap is isolated to `viewer/svelte.config.js`; can land while domain models are still solidifying.
3. **Phase 18 community artifacts at Phase 7.** Governance model is the main input; CoC + CONTRIBUTING don't wait for pipeline or UI.

---

## 4. Data Migration Path — v1 JSON → v2 Shards

### 4.1 The Greenfield Clarification

Per milestone brief: **"no v1 corpora to migrate."** The brief locks `FOLIO_INSIGHTS_V1_COMPAT=false` — there is no backward-compat flag.

But v1 extraction.json / review.json / proposed_classes.json files *do* exist on disk at `/home/damienriehl/Coding Projects/folio-insights/output/` (v1.0 advocacy corpus; 3.8 MB bundled). Brief §"Benchmark corpora" says: **"Advocacy (v1 re-extracted)."** This means:

- v1 JSON outputs are **source material**, not migration targets
- The advocacy corpus gets **re-extracted from its source texts** under v2.0 pipeline, producing shards natively
- v1 JSON is retained in `output/.v1.0-snapshot/` for **regression comparison**, not for data carry-over

This simplifies the data-migration picture dramatically: **no field-level v1→v2 translation; re-extract instead.**

### 4.2 Data Flow Map — Greenfield Re-Extraction

```
Source texts (MD files, 14 formats)
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│ v1 Pipeline (PRESERVED, Stages 1-7)                          │
│   Ingestion → Structure → Boundary → Distiller               │
│   → Classifier → FolioTagger → Deduplicator                  │
│                                                              │
│ Output: List[KnowledgeUnit]  (in-memory, also JSON archive) │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ NEW: Stage 8 — Shard Minter                                  │
│                                                              │
│  for unit in units:                                          │
│    iri, hash = mint_shard_iri(unit.source_file,              │
│                               unit.original_span_text)       │
│    framework_id = framework_detector.detect(unit)            │
│    bfo_cat = bfo_classifier.classify(unit)                   │
│    subtype = subtype_router.route(unit)   # NLI + markers   │
│    shard = build_shard(                                      │
│      iri=iri, hash=hash, unit=unit,                          │
│      framework_id=framework_id, bfo=bfo_cat,                 │
│      first_extractor_did=config.extractor_did,               │
│      signatures=[did_signer.sign("extract", shard)],         │
│      subtype=subtype,                                        │
│    )                                                          │
│                                                              │
│  Output: List[Shard]  (typed, 15-field envelope complete)   │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ SHACL Validator (pyshacl against bridge rdflib.Graph)       │
│   — envelope shape  (generated from Pydantic)                │
│   — per-subtype shapes                                       │
│   — attestation shape (signature verification)               │
│   — supersession shape                                       │
│   — governance shape                                         │
│   — content_edit shape                                       │
│                                                              │
│ Failures → block write, structlog WARN, Prometheus counter  │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ Cluster Validator (owlready2+HermiT; WORKER stage only)     │
│   Clusters: source-doc, Tractarian-subtree, doctrinal-nbh   │
│   Output: consistency + coverage + cross-ref reports         │
│                                                              │
│ Failures → flag on shard; don't block; log to corpus report │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ Graph Writer                                                 │
│   1. Serialize Shard → rdflib bridge graph (Turtle-star)    │
│   2. pyoxigraph.Store.bulk_load(graph, target_graph=corpus) │
│   3. Update SQLite shard_index + attestation_cache           │
│   4. Append to governance log graph                          │
│   5. emit Prometheus counter `shards_written_total`         │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
                Persistent pyoxigraph (RocksDB)
                + SQLite index (fast shard lookup by IRI)
                + Git-backed TTL dump (nightly snapshot)
```

### 4.3 Re-Extraction of v1 Advocacy Corpus (Benchmark Path)

Concrete migration steps for the one existing corpus:

1. **Snapshot v1 outputs** → `output/advocacy/.v1.0-snapshot/` (keep JSON for comparison; git-ignored from v2.0 pipeline consumers)
2. **Re-run source ingestion** against v1's source MD files (located per corpus manifest)
3. **v2.0 pipeline with Stage 8** produces ~N shards
4. **Regression comparison script** (new): `scripts/compare_v1_v2_extraction.py` diffs
   - Count: v1 KnowledgeUnits vs v2 Shards (allow -10% to +30%; shards split on polysemy forks)
   - Text coverage: v1 units → v2 shards should preserve the same source spans (±tokenization drift)
   - FOLIO tag overlap: Jaccard similarity on FOLIO IRIs tagged (target ≥ 0.85)
5. **Cluster validator flags** any new cross-shard issues; per PRD §17 success criterion 2: "at most 10% additional conflicts (real ones that v1.0 missed)"
6. **Reviewer DID attestation** on the re-extracted corpus closes the migration

### 4.4 Non-Data Migration Artifacts

Items that *do* need a migration treatment even under greenfield:

| Item | v1 location | v2 treatment | Migration effort |
|---|---|---|---|
| **Approved tasks in `review.db`** | `output/<corpus>/review.db` (aiosqlite) | v2 re-approves via DID signatures; approval is re-done as an attested action | Phase 7/15 — reviewer UI walks through re-signing |
| **Discovered task tree** | `output/<corpus>/proposed_classes.json` | Tree structure preserved; each task becomes a shard `elaborates` edge; task membership becomes `depends_on_shards` | Phase 10 — Stage 8 reads task tree and populates `elaborates` |
| **FOLIO concept cache** | sentence-transformers FAISS index | PRESERVE unchanged; index is corpus-independent | — |
| **Pipeline checkpoints** | `output/<corpus>/checkpoints/*.json` | PRESERVE; checkpoint format unchanged (v1 stages still produce `InsightsJob`) | — |
| **Bundled extraction dataset** | `output/` in Docker image (3.8 MB) | REPLACE; v2.0 ships with re-extracted corpus pinned to `--as-of` commit hash | Phase 19/20 |

---

## 5. Minimum Viable Architecture for Phase 0

Phase 0 is a gate phase — it either validates the locked stack or triggers a stack pivot. Per brief: "Oxigraph+rdflib-bridge spike, perf harness, Dagger CI."

### 5.1 Phase 0 Deliverables

| Deliverable | What ships | Pass criterion | Owner in v1 code |
|---|---|---|---|
| **Philosophy rename** | `2026-04-19_Philosophy.md` → `PHILOSOPHY.md`; canonical link updated in PROJECT.md and PRD | File renamed; links resolve | root |
| **Oxigraph spike** | `src/folio_insights/storage/oxigraph_store.py` stub; round-trip 100K synthetic triples through pyoxigraph + rdflib bridge; benchmark bulk_load vs. incremental add | bulk_load ≥ 100K triples/sec; round-trip isomorphic | NEW |
| **Perf harness** | `scripts/bench_sparql.py` — loads 1M synthetic shards (generated via faker); runs 20 canonical queries from PRD §20; measures P50/P95/P99 | P95 SPARQL < 500ms @ 1M triples (brief quality bar); log per-query timings to Prometheus | NEW |
| **HermiT-in-Docker spike** | Two-stage Dockerfile (worker stage adds openjdk-17-jre-headless); `scripts/bench_cluster_validator.py` runs owlready2 reasoner over a 10K-shard cluster | Reasoner completes < 30s; image size < 500 MB for worker stage | `Dockerfile` |
| **Dagger CI skeleton** | `ci/dagger/main.py` defines pipeline: lint (ruff) → type check (mypy) → tests (pytest) → build web image → build worker image → SHACL lint fixture shapes | Runs locally with `dagger run python ci/dagger/main.py`; runs in GitHub Actions via dagger-action | `.github/workflows/` |
| **SSR streaming prototype** | `viewer/src/routes/stream-test/+server.ts` — dummy SSE endpoint that streams 10K mock SPARQL result rows over SvelteKit 5 adapter-node | Browser receives rows incrementally; no buffering; latency-to-first-byte < 200ms | NEW |
| **Synthetic load generator** | `scripts/generate_fake_corpus.py` — emits 1M shards with realistic envelope distributions; feeds perf harness and storage spike | 1M shards generated in < 10 min; output valid under SHACL envelope shape | NEW |

### 5.2 Phase 0 Acceptance Gate

Phase 0 PASSES when:

- [x] All 7 deliverables ship
- [x] P95 SPARQL < 500ms @ 1M triples (VALIDATES brief quality bar; if fails → pivot to Apache Jena Fuseki external or re-scope corpus target)
- [x] Worker Docker image < 500 MB (VALIDATES RISK-1 mitigation; if fails → pivot to Rust `reasonable` reasoner and downgrade OWL 2 EL → OWL 2 RL)
- [x] SSR streaming prototype latency < 200ms (VALIDATES RISK-4; if fails → defer SPARQL streaming to post-GA, ship batch-response SPARQL)
- [x] Dagger CI runs locally and on GitHub Actions (reproducibility baseline)

### 5.3 Phase 0 Exit Decision Matrix

| If… | Then… |
|---|---|
| All gates pass | Proceed to Phase 1 (polysemy spike) → Phase 2 (§6.1 envelope) |
| SPARQL P95 fails | Option A: narrow corpus target to 100K (keep single-node); Option B: pivot to Fuseki external (adds service; changes deploy shape); Option C: add query-level caching layer (e.g., Redis-cached SPARQL results) |
| Worker image > 500 MB | Option A: strip JVM to headless-tiny; Option B: pivot to `reasonable` (Rust OWL 2 RL); Option C: run reasoner as separate long-lived service |
| SSR streaming fails | Defer streaming; ship batch SPARQL for GA; revisit post-v2.0 with WebTransport or custom SSE gateway |
| Dagger proves unwieldy | Fall back to plain GitHub Actions (less local reproducibility but lower complexity); document the tradeoff in MEMORY |

---

## 6. Architectural Patterns (v2.0 Specific)

### Pattern 1: Shard-as-Transaction

**What:** Every shard write is a transaction: mint IRI → build envelope → SHACL validate → cluster validate → DID sign → bulk_load pyoxigraph → update SQLite index → append governance log. All-or-nothing.

**When to use:** Every ingest path — pipeline Stage 8, REST write API, content edit.

**Trade-offs:**
- Pros: atomicity; no half-written shards; audit log never diverges from store
- Cons: transaction spans two stores (pyoxigraph + SQLite) — needs a saga pattern

**Implementation sketch:**

```python
async def write_shard_txn(shard: Shard) -> None:
    async with txn_context():
        validate_shacl(shard)
        validate_cluster(shard)  # warn-only if cluster fails
        verify_signatures(shard)
        await oxigraph_store.bulk_load_atomic(shard.to_turtle_star(), named_graph=shard.corpus_graph_iri())
        await sqlite.execute("INSERT INTO shard_index ...", shard.index_row())
        await governance_log.append(shard.extract_event())
    metrics.shards_written_total.labels(corpus=shard.corpus, subtype=shard.shard_type).inc()
```

### Pattern 2: Canonical-Content-Hash as Signature Target

**What:** Every DID signature targets `canonical_content_hash(shard)` — a SHA-256 over JCS-canonicalized JSON, excluding `signatures` and `content_edits` lists. This gives a stable target that doesn't self-reference.

**When to use:** Every signature (extract, promote, demote, content_edit, reparent, distinguo, reconcile, contest, resolve_contest, supersede).

**Trade-offs:**
- Pros: deterministic; re-hashing anywhere produces identical result; signatures stay valid across serialization round-trips
- Cons: adds JCS dep; requires discipline (forgetting to exclude `signatures` = infinite loop)

**Implementation sketch:**

```python
def canonical_content_hash(shard: Shard) -> str:
    payload = shard.model_dump(exclude={"signatures", "content_edits"})
    canonical = jcs.canonicalize(payload)  # RFC 8785
    return hashlib.sha256(canonical).hexdigest()
```

### Pattern 3: Named-Graph-per-Corpus + Shared TBox + Separate Governance

**What:** Each corpus has its own named graph for ABox; the TBox (fi:* vocab + BFO spine + FOLIO imports) lives in a shared graph; every corpus has its own governance log graph.

**When to use:** Always. Every shard write names its corpus graph; every vocabulary edit names the TBox graph.

**Trade-offs:**
- Pros: cross-corpus SPARQL is native (`FROM NAMED <corpus:advocacy>`); tbox edits don't rewrite abox; governance log easily exported as standalone PROV-O
- Cons: SPARQL queries must be graph-aware; users forgetting `GRAPH ?g {...}` get unexpected results — mitigation: pre-ship templates (FEATURES.md E differentiator)

### Pattern 4: Pipeline Stage Append, Not Mutate

**What:** Stage 8 (Shard Minter) is appended to the v1 pipeline. Stages 1-7 continue to emit `KnowledgeUnit`; Stage 8 consumes them. No existing stage is modified.

**When to use:** Any v1 → v2 transformation where v1 outputs are stable.

**Trade-offs:**
- Pros: zero regression risk on 203 v1 tests; bug isolation is simple (v1 test fails → v1 regression, not v2 bug)
- Cons: can't leverage per-stage signals inside earlier stages (e.g., boundary detector doesn't know about shard subtypes)

### Pattern 5: Worker-Side Reasoning, Web-Side Query

**What:** All OWL reasoning (owlready2+HermiT) runs in the worker tier only. Web tier only executes SPARQL against pre-reasoned pyoxigraph. Inferences are materialized into the store at write time.

**When to use:** Every ingest + every cluster-validation pass.

**Trade-offs:**
- Pros: web tier stays JVM-free; cold starts fast; user-facing latency predictable
- Cons: inferred triples persist in the store (storage cost); inference updates require re-materialization (amortized over bulk writes)

### Pattern 6: Append-Only Everywhere

**What:** `signatures`, `content_edits`, governance log, contest_votes — all append-only. Enforced in SHACL (shapes forbid deletions) AND in storage (SQLite triggers reject UPDATE/DELETE on these tables).

**When to use:** Any field carrying audit semantics.

**Trade-offs:**
- Pros: tamper-evident; historical reconstruction always possible
- Cons: storage grows monotonically — brief sets ttl_days=90 default for hypotheses as the one exception; other append-only fields grow without bound (acceptable for v2.0 scale target 1M-10M shards)

---

## 7. Data Flow Diagrams

### 7.1 Extract Flow (Greenfield Shard Mint)

```
User CLI: `folio-insights extract <dir> --corpus advocacy --llm-provider anthropic`
            │
            ▼
  api/services/ingestion_bridge.py (v1, PRESERVED)
            │  reads 14-format docs
            ▼
  Arq enqueue: worker/tasks/run_pipeline.py
            │  async, non-blocking
            ▼
  Worker picks up job → runs Stages 1-7 (v1, PRESERVED)
            │  emits List[KnowledgeUnit]
            ▼
  Stage 8: Shard Minter (NEW)
            │  for each unit:
            │    - mint_shard_iri(src, span)          [§6.3]
            │    - framework_detector.detect()         [§P2]
            │    - bfo_classifier.classify()           [§P7]
            │    - subtype_router.route()              [§6.2]
            │    - build_shard() with 15 fields        [§6.1]
            │    - did_signer.sign("extract", shard)   [§6.5]
            ▼
  SHACL validate (pyshacl on rdflib bridge graph)     [§10]
            │   envelope + subtype + attestation + immutable_fields
            ▼
  Cluster validate (owlready2+HermiT)                 [§P1]
            │   warn-only; shards proceed with flag
            ▼
  Graph writer: bulk_load into pyoxigraph             [§11]
            │   named graph: corpus:advocacy (abox)
            │   inferred triples materialized
            ▼
  SQLite: update shards_index + attestation_cache     [v1 db augmented]
            │
            ▼
  Governance log append: `extract` event signed       [§3.1]
            │
            ▼
  Prometheus: shards_written_total++                  [§12 obs]
  structlog: bind(corpus=advocacy, shard_iri=...)     [§12 obs]
  OTel span closes
            │
            ▼
  SSE progress push → SvelteKit viewer
            │
            ▼
  User sees: "1,247 shards minted; 3 cluster conflicts; 0 SHACL failures"
```

### 7.2 User SPARQL Query Flow

```
User browser: YASGUI editor on /sparql page
            │
            ▼
  SvelteKit SSR route: /sparql
            │  POST /sparql with body = query
            ▼
  FastAPI /sparql route
            │  - rate limit check (fastapi-limiter + Redis)
            │  - timeout wrapper (30s)
            │  - size cap (10K rows)
            │  - CORS headers set
            ▼
  OTel span: sparql.query
  structlog: bind(query_hash=..., did=request.state.did or "anon")
            │
            ▼
  pyoxigraph.Store.query(sparql_text)
            │  - SPARQL 1.1 + SPARQL-star
            │  - named-graph-aware
            ▼
  Results iterator
            │  - if Accept: text/event-stream → stream SSE frames
            │  - if Accept: application/sparql-results+json → batch JSON
            │  - if Accept: text/turtle (CONSTRUCT) → turtle stream
            ▼
  Prometheus: sparql_query_duration_seconds.observe(elapsed)
            │
            ▼
  User sees: streaming result table in YASGUI
```

### 7.3 DID-Gated Write API Flow

```
Federated contributor: signs shard client-side
            │  (browser wallet or CLI `folio-insights sign`)
            ▼
  POST /api/shards with body = {shard, signature}
            │
            ▼
  FastAPI auth middleware:
    - authlib session (OAuth) → identity_binding lookup → request.state.did
            │
            ▼
  /api/shards handler:
    1. Verify did_signer.verify(shard, signature, request.state.did)  [§6.5]
    2. Check role: request.state.did has `extractor|reviewer|...` in corpus
    3. SHACL validate shard (envelope + subtype + immutable_fields)   [§10]
    4. If shard.shard_type == Hypothesis AND action == "promote":
         - check depends_on_* citations [§3.1.2]
    5. Cluster validate (warn-only)                                   [§P1]
    6. Write transaction (Pattern 1)
    7. Append governance log event                                    [§3.1.5]
            │
            ▼
  Response: 201 Created with shard_iri + canonical_content_hash
```

---

## 8. Scaling Considerations

| Scale | Architecture adjustments |
|---|---|
| **< 100K shards** (early corpora) | pyoxigraph in-memory mode; no streaming needed; single Arq worker; SQLite for everything; owlready2 reasoner runs in < 5s |
| **100K-1M shards** (GA target) | pyoxigraph RocksDB persistent; Redis for rate limiting; 2-4 Arq workers; SPARQL streaming optional; cluster validator parallelized by cluster axis |
| **1M-10M shards** (brief target ceiling) | pyoxigraph with RocksDB tuning (bloom filters, block cache); SPARQL streaming mandatory; 10+ Arq workers; nightly TTL dump becomes incremental (only changed corpora); named-graph partitioning enforced in all queries |
| **> 10M shards** (beyond brief) | Consider external Fuseki or TDB2; introduce query-result caching layer; horizontal worker scaling; per-corpus read replicas |

### 8.1 Scaling Priorities (what breaks first)

1. **SPARQL query latency at 1M triples** — addressed by Phase 0 perf harness gate; mitigate via pre-shipped query templates (no user-authored ad-hoc queries hitting hot paths) + streaming + named-graph scoping
2. **Cluster validator runtime as corpora grow** — HermiT scales poorly past ~50K axioms; mitigate by clustering (never validates whole corpus at once) + pre-materializing inferences at write time
3. **Arq queue backlog on bulk re-extract** — mitigate by worker pool size + idempotency keys (re-extraction is safe to retry)
4. **SQLite write contention on `shard_index`** — aiosqlite serializes writes; at 10K shards/min, switch to WAL mode; past 100K/min, consider per-corpus SQLite DBs or migrate index to PostgreSQL

---

## 9. Anti-Patterns Specific to This Domain

### Anti-Pattern 1: Stringly-Typed Shard Subtypes

**What people do:** `shard_type = "disputed_proposition"` as a string, checked via `if shard.shard_type == "...":` throughout the code.

**Why it's wrong:** Pydantic discriminated unions exist for this; subtype fields (like `DisputedProposition.utrum`) become `Optional[str]` on the base class, losing type safety.

**Do this instead:** Use Pydantic v2 discriminated union on `shard_type` field; downstream code gets a `DisputedPropositionShard` typed object with guaranteed `utrum`/`objections`/`respondeo`/`replies` fields.

### Anti-Pattern 2: Regenerating Shard IRIs on Re-Extract

**What people do:** Every pipeline run re-mints IRIs, treating them as non-deterministic.

**Why it's wrong:** Breaks the provenance-hash invariant (§6.3 decision #6). Re-extracting the same (source, span) pair *must* produce the same IRI or permalinks break.

**Do this instead:** `mint_shard_iri()` is pure; test with `test_shard_iri_deterministic_across_runs.py`; any re-extraction lands as a content edit (new AttestedSignature, content_edit audit entry) against the same IRI.

### Anti-Pattern 3: Bundling SHACL Shapes into Code

**What people do:** Hard-code SHACL shapes as Python string constants.

**Why it's wrong:** Shapes are data; external reviewers need to read them; `pyshacl` wants graph input, not strings.

**Do this instead:** Shapes live as `.ttl` files under `src/folio_insights/shapes/`; ship them with the package (`importlib.resources`); generator outputs `envelope.shacl.ttl` as a build artifact.

### Anti-Pattern 4: Signing Keys in Server Memory

**What people do:** Load private keys on server boot, sign server-side for "convenience."

**Why it's wrong:** Defeats decentralized identity; §16 R5 security audit fails; any server compromise reveals all reviewers' keys.

**Do this instead:** Client-side signing always. CLI uses local `~/.folio-insights/signing.key`; browser UI uses WebCrypto / hardware key (post-GA). Server verifies only.

### Anti-Pattern 5: Synchronous Cluster Validation

**What people do:** Run owlready2+HermiT inside the HTTP request handler to validate on write.

**Why it's wrong:** Reasoning is slow (seconds to minutes on large clusters); blocks the write; JVM cold start on first request hits every reviewer.

**Do this instead:** Cluster validation is always async via Arq. Write accepts on SHACL pass alone; cluster validation runs in background; results posted as shard annotations; UI surfaces flags eventually-consistent.

### Anti-Pattern 6: Overloading `aiosqlite` as the Graph Store

**What people do:** Keep rdflib-on-SQLite as it was in v1; add shards as rows.

**Why it's wrong:** Pyoxigraph is ~40x faster for bulk load; SPARQL 1.1 on rdflib-sqlite is slow and lacks SPARQL-star.

**Do this instead:** SQLite stays for *relational* indexes (shard_index → pyoxigraph IRI; identity_bindings; corpus config; attestation cache). RDF goes in pyoxigraph.

### Anti-Pattern 7: Wrapping Every Instructor Call in Retry

**What people do:** Decorate every LLM call with `@tenacity.retry(stop=stop_after_attempt(5))`.

**Why it's wrong:** `instructor` already has retries for validation failures; stacking retries creates exponential blow-up on bad days; observability gets confusing (which retry fired?).

**Do this instead:** Let `instructor` handle validation retries; wrap the top-level extraction in tenacity only for network-layer failures (httpx timeouts, rate limits). Single retry layer; single OTel span.

---

## 10. Integration Points

### 10.1 External Services

| Service | Integration Pattern | Notes |
|---|---|---|
| **Anthropic API** | `instructor.from_anthropic(anthropic.AsyncAnthropic())` | Default provider; needs `ANTHROPIC_API_KEY` env |
| **OpenAI API** | `instructor.from_openai(openai.AsyncOpenAI())` | CI matrix only; needs `OPENAI_API_KEY` |
| **Ollama (local)** | `instructor.from_ollama(...)` | CI matrix + air-gapped option; `OLLAMA_HOST` env |
| **GitHub OAuth** | `authlib.integrations.starlette_client.OAuth("github")` | Needs client ID + secret; PKCE + state + nonce |
| **Google OAuth** | same, registered as `"google"` | Needs Google Workspace setup for institutional |
| **did:plc directory** | `atproto.IdResolver().did.resolve(did)` | For did:plc resolution; httpx under the hood |
| **did:web HTTPS lookup** | `httpx.AsyncClient().get(f"https://{domain}/.well-known/did.json")` | Simple well-known fetch |
| **Redis 7.4** | Arq + `redis-py` async client; single instance serves queue + rate limit + idempotency | Railway Redis plugin or self-hosted |
| **OTel collector** | OTLP/gRPC export to Tempo/Jaeger/Honeycomb; endpoint via `OTEL_EXPORTER_OTLP_ENDPOINT` | Optional; degrades gracefully if collector unavailable |
| **Prometheus scraper** | `/metrics` endpoint via `prometheus-fastapi-instrumentator`; scrape interval 15s typical | Self-hosted or Grafana Cloud |
| **FOLIO canonical endpoint** | Read-only from `alea-institute/FOLIO` GitHub releases | Pinned version per corpus; cached in v1's `folio-enrich` bridge |

### 10.2 Internal Boundaries

| Boundary | Communication | Notes |
|---|---|---|
| **Web tier ↔ Worker tier** | Arq jobs over Redis | Idempotency keys on every job; retry-safe |
| **FastAPI ↔ pyoxigraph** | In-process Python bindings | Both tiers have pyoxigraph; worker writes, web reads |
| **FastAPI ↔ SQLite** | aiosqlite in-process | Preserve v1 pattern; add new tables alongside `review.db` |
| **Shard Minter ↔ v1 pipeline** | Direct call (`stage_8.run(job.units)`) | Stage 8 consumes `List[KnowledgeUnit]` from Stage 7 output |
| **rdflib bridge ↔ pyoxigraph** | Serialize through Turtle-star | rdflib graph → `.serialize(format="ttls")` → pyoxigraph `Store.load()` |
| **SvelteKit ↔ FastAPI** | HTTP/JSON (SPA mode in dev, SSR in prod) | `viewer/vite.config.ts` proxies `/api` to localhost:9925 in dev |
| **SPARQL endpoint ↔ Store** | In-process pyoxigraph call | No HTTP hop internally; the REST endpoint wraps Store.query |
| **Governance log writer ↔ pyoxigraph governance graph** | Named-graph write | Dedicated graph per corpus; append-only SHACL guard |
| **Cluster validator ↔ worker** | In-worker subprocess (`java -jar HermiT.jar`) | JVM lives only in worker stage; web tier never calls it |
| **Arq worker ↔ FAISS** | In-process `folio-enrich` bridge | PRESERVED from v1; no change needed |

### 10.3 Critical API Contracts

**1. Pydantic `Shard` ↔ SHACL shape:** Pydantic is the source of truth. The generator emits `envelope.shacl.ttl` from `Shard.model_json_schema()`. Hand-written shapes augment (never override) the generated base. This means: change `Shard` → re-run generator → update shapes → re-run tests.

**2. `Shard` ↔ pyoxigraph Turtle-star:** Round-trippable. `Shard.to_turtle_star()` produces Turtle-star; `Shard.from_turtle_star(store, iri)` reconstructs. Tested via round-trip fixture.

**3. DID ↔ `AttestedSignature`:** Verification is deterministic. `verify(shard, sig)` re-canonicalizes content → SHA-256 → checks signature → returns bool. Caching via `fi:verified true` annotation avoids re-verification.

**4. OAuth identity ↔ DID binding:** Many-to-many. One OAuth email can bind multiple DIDs (e.g., personal did:key + institutional did:web). One DID can bind zero or one OAuth emails. Binding is an explicit user action, signed by the DID key (proves control) + confirmed via OAuth (proves email control).

**5. `Shard.corpus_id` ↔ pyoxigraph named graph:** Computed at write: `corpus_graph_iri = f"https://folio-insights.aleainstitute.ai/corpus/{shard.corpus_id}/abox"`. SPARQL queries filter by `FROM NAMED <corpus_graph_iri>`.

---

## 11. Open Architectural Questions (for `/gsd-discuss-phase`)

| Q | Context | Recommendation (informed opinion) |
|---|---|---|
| **Q1** | Should the `web` and `worker` Docker images share a base layer or be fully independent? | **Shared base** (python:3.11-slim + core deps); worker adds JDK layer. Saves ~150 MB per image and keeps dep versions in lockstep. |
| **Q2** | Where does `fi:verified true` annotation live — on the shard itself or on the signature blank node? | **On the signature blank node** (RDF-star annotation). Lets one shard have a mix of verified/unverified signatures without model pollution. |
| **Q3** | When a content edit invalidates old signatures (signature over *prior* content hash), do we keep them? | **Keep always, append-only.** Old signatures attest to a prior content hash. Current state may not verify against them, but the audit log preserves the provenance. Display UX: strike-through old sigs, highlight current-content-hash sigs. |
| **Q4** | Should Phase 10 Arq migration happen big-bang or side-by-side with v1's job_manager? | **Side-by-side with feature flag** (`FOLIO_JOB_BACKEND=arq\|disk`). Cut over at Phase 12 when observability wraps both. Reduces regression risk. |
| **Q5** | Does the SvelteKit adapter-static → adapter-node swap land at Phase 0 (spike) or Phase 14 (UI phase)? | **Spike at Phase 0** (prototype streaming); full swap at Phase 14 (when UI design contract is in place). Don't rewrite routes for adapter-node at Phase 0 — only prove streaming works. |
| **Q6** | Do we ship the §10 Pydantic-to-SHACL generator as a build-time step or runtime step? | **Build-time.** `pyproject.toml` postinstall hook emits `envelope.shacl.ttl`; checked into repo; diffed in CI. Avoids runtime coupling to Pydantic internals and keeps shapes reviewable in PRs. |
| **Q7** | How does the governance log get ingested — as shards or as separate PROV-O RDF? | **Separate named graph** (`governance:<corpus>`) in pyoxigraph; not shards. Governance events are events (occurrent); shards are assertions. Conflating them corrupts the shard model. |

---

## 12. Roadmap Implications — Summary

### Phase sequencing insight (for `/gsd-new-milestone`)

- **Phases 0, 6, 11, 13, 14, 19 are gates.** They either unblock downstream phases or block release. Buffer each with 1-2 extra days of contingency.
- **Phases 2-6 (§6 subsections) should land on consecutive weeks.** Each depends on the prior; splitting them across sprints causes context-switching costs.
- **Phases 9 and 15 are the largest.** Consider sub-phasing per principle (9.P1, 9.P2, ...) and per UI surface (15.shard, 15.polysemy, ...). The brief already hints at this structure.
- **Observability (Phase 12) must land before Phase 13.** Post-hoc OTel instrumentation of the storage layer is painful; instrumenting as you write it is trivial.
- **UI design contract (Phase 14) must precede any §12 UI work** — per brief "/gsd-ui-phase."

### Dependency-critical files that must exist early

1. `src/folio_insights/models/shard.py` — by Phase 2
2. `src/folio_insights/shards/iri.py` (`mint_shard_iri`) — by Phase 4
3. `src/folio_insights/did/signer.py` + `verifier.py` — by Phase 6
4. `src/folio_insights/storage/oxigraph_store.py` — by Phase 13 (stub in Phase 0)
5. `src/folio_insights/shapes/envelope.shacl.ttl` (auto-generated) — by Phase 11
6. `worker/tasks.py` + `worker/settings.py` — by Phase 10
7. `viewer/svelte.config.js` adapter-node swap — by Phase 14
8. Two-stage `Dockerfile` — by Phase 12 (prototype in Phase 0)

### Parallel scheduling opportunities

- Begin Phase 12 observability at Phase 6 (OTel scaffolding is domain-free)
- Begin Phase 14 design system at Phase 8 (visual language is code-free)
- Begin Phase 18 CoC + CONTRIBUTING at Phase 7 (governance model is the main input)
- CI matrix for LLM providers (Phase 10 sub-work) can begin at Phase 8

### Risks that hit the roadmap hardest

1. **Phase 0 SPARQL P95 gate failure** → replans Phase 13 (swap to Fuseki) + adds a deploy-complexity phase. Mitigation: build realistic 1M-shard synthetic corpus early.
2. **HermiT JVM image bloat** → forces worker/web split earlier (Phase 12 → Phase 0). Already planned; low risk.
3. **Pydantic-to-SHACL generator takes longer than 1-2 days** → Phase 11 slips; mitigation: hand-written shapes cover P0 alone; generator is a late-Phase-11 deliverable, not a gate.
4. **SvelteKit adapter-node streaming doesn't work reliably** (RISK-4) → Phase 15 SPARQL explorer ships without streaming; acceptable degradation; flagged in release notes.
5. **Stack pivot at Phase 0** (Fuseki / reasonable / Rust reasoner) → 2-4 week delay; re-plan only Phases 13 + 19; other phases unaffected.

---

## Sources

- **Internal:** `PRD-v2.0-draft-2.md` §0, §3.1, §6 (full), §7, §8, §9, §10, §11, §12, §13, §14, §16, §17 · `.planning/v2.0-MILESTONE-BRIEF.md` (phase structure + stack decisions) · `.planning/PROJECT.md` (v1.1 state) · `.planning/research/STACK.md` (version pins + RISK-1 + RISK-2 + RISK-4) · `.planning/research/FEATURES.md` (feature dependencies + MVP scope)
- **v1.1 codebase inspection** (HIGH confidence):
  - `src/folio_insights/pipeline/orchestrator.py` — 7-stage pipeline shape + checkpoint pattern
  - `src/folio_insights/pipeline/stages/*.py` — ingestion, structure_parser, boundary_detection, distiller, knowledge_classifier, folio_tagger, deduplicator
  - `src/folio_insights/models/knowledge_unit.py` — `KnowledgeUnit` schema (Pydantic v2)
  - `src/folio_insights/services/bridge/{folio,ingestion,llm,mapper,reconciliation}_bridge.py` — folio-enrich bridge pattern
  - `src/folio_insights/services/{iri_manager,owl_serializer,shacl_validator,jsonld_builder,changelog_generator,corpus_registry,contradiction_detector,task_exporter}.py` — service layer
  - `api/main.py`, `api/routes/*.py`, `api/services/{job_manager,pipeline_runner,discovery_runner}.py`, `api/db/{session,models}.py` — FastAPI + disk-based job manager
  - `viewer/svelte.config.js`, `viewer/src/routes/*`, `viewer/src/lib/{api,components,stores}/*` — SvelteKit adapter-static shape
  - `Dockerfile` — current single-stage (node:20-slim → python:3.11-slim) pattern
- **Ecosystem references:**
  - [pyoxigraph 0.5.7 docs on named graphs + SPARQL-star](https://pyoxigraph.readthedocs.io/) — HIGH
  - [owlready2 reasoning docs — HermiT Java dependency](https://owlready2.readthedocs.io/en/latest/reasoning.html) — HIGH (source of RISK-1)
  - [SvelteKit 5 adapter-node + streaming SSR](https://svelte.dev/docs/kit/adapter-node) — MEDIUM (RISK-4 flag)
  - [Arq 0.28 worker + async context](https://arq-docs.helpmanual.io/) — HIGH
  - [instructor multi-provider pattern](https://python.useinstructor.com/integrations/) — HIGH
  - [W3C PROV-O](https://www.w3.org/TR/prov-o/) — governance log format per brief
  - [RFC 8785 JCS](https://datatracker.ietf.org/doc/html/rfc8785) — canonical JSON for signing
  - [W3C DID Core v1.0](https://www.w3.org/TR/did-core/) — did:key/web/plc specifications
  - [Dagger CI Python SDK](https://docs.dagger.io/sdk/python/) — CI reproducibility pattern
  - [Railway multi-service deploy](https://docs.railway.com/) — worker + web service split

---

*Architecture research for: FOLIO Insights v2.0 shards-as-axioms*
*Researched: 2026-04-20*
*File: `.planning/research/ARCHITECTURE.md`*
