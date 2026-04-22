---
milestone: v2.0
milestone_name: shards-as-axioms
status: defined
defined_at: 2026-04-22
sources:
  - PRD-v2.0-draft-2.md
  - .planning/v2.0-MILESTONE-BRIEF.md
  - .planning/research/SUMMARY.md
  - .planning/research/STACK.md
  - .planning/research/FEATURES.md
  - .planning/research/ARCHITECTURE.md
  - .planning/research/PITFALLS.md
scope_discipline: "Aggressive GA — inherit brief P1+Should-Have; promote 4 former Defers (hardware-key signing, multi-sig attestations, 'explain this query' LLM helper, corpus fork + genealogy); promote private corpora from Should-Have to P1"
priority_key:
  P1: Must-Ship for v2.0 GA
  P2: Should-Ship if phase budget allows; else early v2.1
  P3: Defer to post-GA
---

# FOLIO Insights v2.0 — Requirements

## 1. Scope Summary

v2.0 is a **refactor-in-place** on the v1.1 FastAPI + SvelteKit + aiosqlite foundation. The brief resolved 40+ decisions; research (2026-04-20) validated those decisions against current PyPI and surfaced four corrections that are encoded below as RISK requirements. v2.0 ships shards as DID-signed, hash-anchored, SHACL-validated axioms queryable over a public SPARQL endpoint, with a polysemy-first review UI.

**Changes vs. brief (post-research + scope session 2026-04-22):**

- **Promoted to P1:** opt-in private corpora with envelope encryption (§CORPUS-06, §CORPUS-07)
- **Promoted to P2:** hardware-key signing (§DID-08), multi-sig attestations (§DID-09), "Explain this query" LLM helper (§SPARQL-09), corpus fork + genealogy viz (§CORPUS-08, §CORPUS-09)
- **New constraint:** Phase 0 RDF-12 hard gate with pre-specified Apache Jena Fuseki pivot path (§SEC-01, §STORAGE-01)
- **New quality bars:** novel UX surfaces (polysemy, contest) must pass practitioner think-aloud gate (§QUALITY-05), mandate `/gsd-discuss-phase` artifacts for Phase 15.polysemy and 15.contest (§UI-13)
- **Inherited unchanged:** all 7 design principles (§PRINCIPLE-01..07), 15-field envelope (§SHARD-01), 5 subtypes (§SHARD-02..06), governance model (§GOV-01..08), SHACL hybrid (§SHACL-01..05), pipeline LLM-agnostic refactor (§LLM-01..04), review UI surfaces (§UI-01..12), community artifacts (§GOV-07..08)

**Out of scope for v2.0** (remains post-GA): GraphQL endpoint, live WebSocket subscriptions, mobile-first apps, per-shard DID-based key-agreement encryption, centralized reputation scores, SPARQL UPDATE on public endpoint, anonymous contributions.

---

## 2. Requirements

### SHARD — Shard Envelope & Subtypes

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| SHARD-01 | P1 | 15-field Pydantic `Shard` envelope with discriminated-union subtype dispatch via `Literal[...]` tags | PRD §6.1 | Round-trip test: `Shard(**shard.model_dump()) == shard` across all 5 subtypes; discriminated-union test rejects invalid tag |
| SHARD-02 | P1 | `SimpleAssertionShard` subtype (single claim with one warrant chain) | PRD §6.2.1 | Schema validation pass; example A.1 round-trips |
| SHARD-03 | P1 | `DisputedPropositionShard` subtype with `dispute_state ∈ {hypothesis, attested, contested, aporetic}` + positions[] | PRD §6.2.2 | A.3 example round-trips; state transitions validated |
| SHARD-04 | P1 | `ConflictingAuthoritiesShard` subtype with `authorities[]` + `reconciliation_strategy` enum (8 values) | PRD §6.2.3 | A.2 example round-trips; all 8 reconciliation strategies enumerated in schema |
| SHARD-05 | P1 | `GlossShard` subtype (auxiliary explanatory shards) | PRD §6.2.4 | Schema + validator pass |
| SHARD-06 | P1 | `HypothesisShard` subtype with `citation_required: bool = True` crowdsourcing guard | PRD §6.2.5, §21.3 | Promotion path from hypothesis → attested requires citation present |
| SHARD-07 | P1 | Provenance-hash IRI scheme (`/shard/<hex16>`) with deterministic `canonicalize_source_span()` (NFC + LF + trim + RFC 3986 normalization) | PRD §6.3, §21.6; PITFALLS RISK-3 | Property test: same source + same span → same IRI across runs; re-hash nightly verification job passes |
| SHARD-08 | P1 | IRI collision detector with handling for collision space > 2³² | PRD §21.6 | Collision test at 100K shards; fallback behavior documented |
| SHARD-09 | P1 | Content versioning via append-only `ContentEdit` chain under immutable shard IRI; `get_shard_at(iri, t)` retrieves historical state | PRD §6.4, §21.7 | `test_content_edit_audit_append_only.py` passes; SHACL guard rejects edits to past versions |
| SHARD-10 | P1 | Bitemporal time-scoping: `valid_time_start`, `valid_time_end`, `transaction_time` on every shard | PRD §21.1; FEATURES §C | SPARQL `--as-of <date>` returns correct historical state |

### DID — Identity & Signed Attestations

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| DID-01 | P1 | Support did:key, did:web, did:plc via `authlib 1.7` + `atproto` + `cryptography` + `PyNaCl` (ed25519) + `joserfc` (JWS) + `dag-cbor` + `jcs` (RFC 8785) | Brief §Identity; STACK RISK-4 | `pytest tests/identity/` green across all 3 DID methods; explicit rejection of `didkit`, `pydid`, `python-jose`, `fastapi-users` in deps |
| DID-02 | P1 | Every write action (extract, promote, demote, contest, supersede, retract, distinguo, role-assertion) produces an `AttestedSignature` over the canonical content hash | PRD §3.1, §6.5, §10 | Governance log shows signed envelope for every state transition |
| DID-03 | P1 | Canonical content hash computed via `jcs.canonicalize(model_dump(exclude={'signatures', 'content_edits'}))`; order-independent | PRD §6.5; PITFALLS #5 | Property test: `verify(sign(x))` succeeds across shuffled field orders for 1000 random shards |
| DID-04 | P1 | Signing-time key capture: every `AttestedSignature` records `signing_key_id` (DID URL + `#keyfragment`) and `did_doc_snapshot_at` timestamp | PRD §6.5; PITFALLS #6 | `test_signature_survives_key_rotation.py` passes; historical DID docs cached |
| DID-05 | P1 | DID-binding onboarding flow: OAuth (GitHub/Google) login → bind existing or generate new did:key / register did:web / register did:plc via AT Proto bridge | Brief §Auth | Playwright flow covers all 3 binding paths with signed `fi:RoleAssertion` output |
| DID-06 | P1 | Server-side signing key storage is forbidden; all signing is client-side (browser-resident keys OR user-held hardware) | PRD §16 R5; FEATURES §D anti-feature | Security audit in Phase 19 verifies no key-at-rest on server for any DID |
| DID-07 | P1 | "What will I be signing?" preview shows canonical content hash + human-readable diff before signature prompt | FEATURES §D diff; Brief Should-Have | Preview renders for all 8 signed-action types; screenshot test |
| DID-08 | P2 | Hardware-key signing (Ledger / YubiKey / WebAuthn) for did:key | FEATURES §D diff (**promoted from Defer**) | E2E test against WebAuthn virtual authenticator; documented support matrix |
| DID-09 | P2 | Multi-signature attestations (N-of-M co-sign on promotion) with signer DID list in `AttestedSignature.cosigners[]` | FEATURES §D diff (**promoted from Defer**) | Schema + SHACL shape; UI flow; E2E: 2-of-3 promotion succeeds, 1-of-3 fails |

### GOV — Governance, Roles, Process

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| GOV-01 | P1 | 4-tier role model: `extractor`, `reviewer`, `arbiter`, `corpus_admin` — scoped per corpus via signed `fi:RoleAssertion` | PRD §3.1.1 | Role assertions round-trip; per-corpus role queries return correct set |
| GOV-02 | P1 | PROV-O governance log per corpus (`<corpus>/governance.ttl`); append-only enforced by SHACL + SQLite trigger | PRD §3.1.5 | Attempts to `DELETE`/`UPDATE` past governance rows rejected at storage layer; audit in Phase 19 |
| GOV-03 | P1 | Promotion workflow: `hypothesis → attested` requires `reviewer` role + citation + DID-signed `fi:Promotion` event | PRD §3.1.2, §21.3 | Promotion CLI + UI both enforce; test: unsigned promotion rejected |
| GOV-04 | P1 | Three-way disambiguation prompt: every "disagreement" action forces user to classify as **contest** / **supersede** / **retract** with distinct codepaths and copy | PRD §21.8, §21.9; PITFALLS #2 | UI test: no shared codepath between 3 ops; CLI has 3 distinct commands |
| GOV-05 | P1 | Contest workflow: position + citation → `contest_votes[]` populated → resolution via arbiter OR distinguo OR aporetic (3 paths, no majority-vote) | PRD §3.1.3 | All 3 resolution paths tested; majority-vote resolution explicitly rejected |
| GOV-06 | P1 | Retraction cascade preview: dependents visualized grouped by `{auto_rederive, aporetic, review_needed}` before commit | PRD §12; PITFALLS #2 | Dry-run UI shows blast-radius; rollback-before-commit affordance works |
| GOV-07 | P1 | Append-only RFC process at `.planning/rfcs/NNNN-title.md` with status lifecycle `draft → discussion → accepted/rejected → implemented`; no auto-merge | FEATURES §F | RFC schema + lifecycle linter in CI |
| GOV-08 | P1 | Community artifacts: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `GOVERNANCE.md`, `RFC-TEMPLATE.md` | PRD §15; FEATURES §F | Files exist, link from README, spell-check pass |
| GOV-09 | P2 | Governance log timeline viewer UI (PROV-O events filterable by corpus, DID, event-type, date-range) | FEATURES §F diff; Brief Should-Have | Renders 10K events < 2s; filter + export working |
| GOV-10 | P2 | Warrant trace-back UI — every shard shows PRD `§N` warrants + `§21.X` decisions it implements, as navigable links | FEATURES §F diff; Brief Should-Have | `Warrant:` metadata on shards surfaces as clickable breadcrumb |

### VOCAB — FOLIO v2 Vocabulary + Mini-BFO Spine

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| VOCAB-01 | P1 | FOLIO v2 TTL file (`fi:*` predicates) ships at stable `owl:versionIRI`; pinned via `fi:vocabVersion` on every shard | PRD §7; PITFALLS LD1 | Vocab TTL parses with rdflib + pyoxigraph; `fi:vocabVersion` SHACL shape enforces pin |
| VOCAB-02 | P1 | Analogia predicates: `fi:primeAnalogate`, `fi:proportionalRelation`, `fi:distinguishes`, `fi:distinctionKind` (realis / rationis / rationis_cum_fundamento_in_re / analogica) | PRD §7.1 | All 4 predicates + 4 distinction kinds queryable |
| VOCAB-03 | P1 | Tractarian elaboration (`fi:elaborates`), Spinozan dependencies (`fi:dependsOnAxiom`, `fi:dependsOnDefinition`), Russellian closure (`fi:closureMarker`), Carnap framework (`fi:Framework`), Aristotelian predication mode (`fi:predicationMode`) | PRD §7.1 | Each predicate round-trips in SPARQL + SHACL shape exists |
| VOCAB-04 | P1 | Mini-BFO spine (self-contained subset) with companion `bfo_mapping.ttl` documenting `owl:equivalentClass` mapping to full BFO 2020 | PRD §7.2, §21.2 | `Continuant`, `Occurrent`, `IndependentContinuant`, `SpecificallyDependentContinuant`, `GenericallyDependentContinuant`, `Process`, `Quality`, `Role`, `Disposition` present |
| VOCAB-05 | P1 | Supersession predicates (`fi:supersedes`, `fi:supersededBy`) — distinct from retraction; old shard remains queryable | PRD §7.1; §21.9 | Query at `--as-of <past-date>` returns superseded shard; retraction is different class |

### PRINCIPLE — Seven Design Principles

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| PRINCIPLE-01 | P1 | P1 — Cluster-level validator (owlready2 + HermiT) runs on shard clusters; worker-tier-only (JVM) | PRD §8.P1; STACK RISK-1 | Worker container includes JVM 17; web container does NOT; validator runs async warn-only in CI |
| PRINCIPLE-02 | P1 | P2 — Framework detector extracts framework from source metadata + corpus config + LLM inference; every shard records `fi:framework` + `extraction_prompt_hash` | PRD §8.P2 | Framework assignment deterministic across re-extractions; prompt hash stable |
| PRINCIPLE-03 | P1 | P3 — Explicit dependency graph: `fi:dependsOnAxiom` / `fi:dependsOnDefinition` stored as first-class edges; enables cascade preview + viz | PRD §8.P3 | DAG construction < 5s for 10K shards; cycle detection present |
| PRINCIPLE-04 | P1 | P4 — TBox (schema) separated from ABox (instances) into distinct named graphs; TBox constrained to OWL 2 EL by default | PRD §8.P4 | EL profile validator pass; TBox graph distinguishable in SPARQL |
| PRINCIPLE-05 | P1 | P5 — Closed-world assumption (CWA) islands explicitly marked via `fi:closureMarker`; default is open-world | PRD §8.P5 | SPARQL query with + without closure marker returns different results for negation-as-failure cases |
| PRINCIPLE-06 | P1 | P6 — Polysemy detector flags same-IRI shards with framework-conflicting axioms; human-gated (always) before distinguo commit | PRD §8.P6; PITFALLS #8 | FP test set < 10% FP rate on curated fixtures; auto-apply is impossible by design |
| PRINCIPLE-07 | P1 | P7 — BFO classifier with `permissive` mode; every shard assigned a mini-BFO class at ingest | PRD §8.P7, §14 | Coverage ≥ 95% of shards classified; unknown → permissive defaults documented |

### LLM — LLM-Agnostic Pipeline & Stage 8 Shard Minter

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| LLM-01 | P1 | `instructor.from_provider()` abstraction; Anthropic (Claude default), OpenAI, Ollama validated in CI matrix | PRD §21.5; Brief §LLM | CI matrix green across 3 providers; `--llm-provider` CLI flag works |
| LLM-02 | P1 | Per-shard `extractor_model` + `extraction_prompt_hash` fields populated | PRD §8.P2, §21.5 | Fields present and queryable; prompt hash stable across identical templates |
| LLM-03 | P1 | **Stage 8 Shard Minter** appends to v1 7-stage pipeline: `KnowledgeUnit → Shard` with subtype routing, IRI minting, framework detection, BFO classification, DID signing | Research §Architecture | Stage 8 isolated module; v1 stages 1-7 unmodified; E2E test: raw doc → signed shard |
| LLM-04 | P1 | Lazy-fill follow-up: fields `1,2,3,4,12,14,15` filled at extraction; fields `5-11, 13` filled async via Arq follow-up jobs | PRD §16 R1 (mitigation) | Arq DAG: extraction → follow-up; shard marked `extraction_phase=partial | complete` |
| LLM-05 | P1 | Arq 0.28 + Redis 7.4 replace v1 disk-based job_manager; side-by-side flag during migration with reconciliation script | PITFALLS #9 | Feature flag cuts over cleanly; no orphan jobs after cutover |
| LLM-06 | P1 | Single-layer retry (instructor-level); no nested retries; aggregate cost tracking at corpus level | Brief §LLM | Retry config documented; cost meter accurate within ±5% |

### SHACL — Validation

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| SHACL-01 | P1 | 6 hand-written SHACL shapes in `shared/` (envelope, subtypes, governance, supersession, distinguo, signatures) | PRD §10 | All 6 TTL files parse; pyshacl validates test fixtures |
| SHACL-02 | P1 | Pydantic-to-SHACL generator (~150 LOC) at `src/folio_insights/shapes/pydantic_to_shacl.py` emits TTL at build time | STACK RISK-2 | Generator emits valid TTL for all 15-field envelope variants; property test: round-trip `Pydantic → SHACL → validate(pydantic_instance)` |
| SHACL-03 | P1 | Per-shard incremental SHACL validation (not per-corpus batch); shapes pre-compiled at startup | PITFALLS #7 | Validation P95 < 50ms per shard at 1M-triple corpus |
| SHACL-04 | P1 | Build-time TTL emission via Dagger; generated TTL committed to repo or regenerated deterministically | STACK RISK-2 | CI verifies generated TTL matches repo OR regenerates deterministically |
| SHACL-05 | P1 | SHACL validation API endpoint: `POST /validate` accepts candidate shard JSON → returns pyshacl report | FEATURES §G diff | Endpoint returns report for valid + invalid fixtures; documented in OpenAPI |

### STORAGE — Oxigraph, Named Graphs, RDF 1.2

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| STORAGE-01 | P1 | pyoxigraph 0.5.7 (pinned) as canonical RDF 1.2 store (RocksDB backend); replaces rdflib-on-SQLite from v1 | STACK RISK-3 | Bulk load ≥ 200K triples/sec; query semantics match RDF 1.2 |
| STORAGE-02 | P1 | rdflib 7.6 as **bridge adapter only** (pyshacl input + JSON-LD + Turtle-star canonicalization); NOT primary store | Research §Stack | Code review verifies no write paths through rdflib; primary writes hit pyoxigraph |
| STORAGE-03 | P1 | Named-graph organization: one graph per corpus (ABox), shared TBox graph, per-corpus governance log graph | PRD §11 | SPARQL `GRAPH ?g { }` returns correct partitioning; cross-graph queries work |
| STORAGE-04 | P1 | RDF 1.2 annotation pattern validates PRD §20 example queries OR documented pivot to Apache Jena Fuseki triggers (see SEC-01) | STACK RISK-3 | Phase 0 spike passes OR pivot decision executes |
| STORAGE-05 | P1 | Nightly TTL dump + git commit of each corpus to repo-backed backup | Brief §Backup | Scheduled Arq job; commit visible in git log |
| STORAGE-06 | P1 | Export formats: `combined.ttl`, `abox/*.ttl`, `tbox.ttl`, `governance.ttl`, JSON-LD frames, SPARQL CONSTRUCT, N-Quads, Neo4j CSV | Brief §Export | All 8 formats export for benchmark corpus; round-trip test for TTL |
| STORAGE-07 | P1 | PII redaction on ingest (configurable patterns; default denies SSN / ABA numbers / phone numbers in raw-text fields) | Brief §PII | Redaction test on synthetic fixture; no PII in default-exported corpus |

### SPARQL — Public Endpoint + Explorer

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| SPARQL-01 | P1 | Public **read-only** SPARQL endpoint at `/sparql`; no SPARQL UPDATE (writes go via DID-gated REST) | PRD §11; FEATURES §G | `POST UPDATE` returns 403; `SELECT`/`CONSTRUCT` return 200 |
| SPARQL-02 | P1 | Security hardening: `SERVICE` stripped from AST before execution; 30s timeout; 10K row cap; IP + DID rate limiting | PITFALLS #4; PRD §16 R5 | Security test: `SERVICE` payload rejected; DoS load test passes |
| SPARQL-03 | P1 | `initBindings` for all parameterized queries (prevents SPARQL injection) | PITFALLS Q3 | Injection test suite passes |
| SPARQL-04 | P1 | Content negotiation: SPARQL JSON, SPARQL XML, CSV, TSV, Turtle (for CONSTRUCT) | W3C SPARQL 1.1 | Accept-header tests cover all 5 formats |
| SPARQL-05 | P1 | Endpoint discovery metadata: VoID description + schema dump + SPARQL service description | FEATURES §G | `/sparql?format=void` returns machine-readable description |
| SPARQL-06 | P1 | CORS enabled with restricted origins (configurable); documented for browser clients | FEATURES §G | Browser-based YASGUI connects without proxy |
| SPARQL-07 | P1 | SPARQL Explorer UI (YASGUI-based) with syntax highlighting, prefix autocomplete, schema-aware completion from endpoint, query history | FEATURES §E | Playwright E2E covers query-edit-execute flow |
| SPARQL-08 | P1 | Pre-shipped templates: 8 from PRD §20 + polysemy inspection + supersession traversal + contested surfacing + framework filter + `--as-of` historical | PRD §20; FEATURES §E diff | All 13 templates execute against benchmark corpus with non-empty results |
| SPARQL-09 | P2 | "Explain this query" LLM helper — natural-language description of a SPARQL query via instructor | FEATURES §E diff (**promoted from Defer**) | UI button generates description; test against 10 template queries |
| SPARQL-10 | P2 | Streaming SPARQL results via SSE (SvelteKit adapter-node enables this) | Brief §SSR; FEATURES §E diff | Large-result test: first row < 200ms, subsequent rows stream |
| SPARQL-11 | P2 | RDF-12 annotation query helper (visual toggle generates annotation syntax from selector) | FEATURES §E diff | Helper produces valid RDF-12 queries executable against endpoint |
| SPARQL-12 | P2 | Visual graph result view (CONSTRUCT queries render via Cytoscape.js; click node → open shard page) | FEATURES §E diff | Integration test: CONSTRUCT → graph → click → navigate |
| SPARQL-13 | P1 | Shareable query permalink (URL-encoded query + optional endpoint params) | FEATURES §E | Permalink round-trip: encode → share → decode → execute |
| SPARQL-14 | P1 | DID-gated REST write API wraps SPARQL UPDATE internally; payloads must carry valid DID signature | FEATURES §G; PRD §11 | Unsigned write returns 401; signed write → governance log entry + oxigraph update |

### UI — Review Interface

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| UI-01 | P1 | SvelteKit 5.55 + adapter-node 5.5 (replaces v1 adapter-static); Vite 8.0 | Brief §Frontend | App boots with adapter-node; SSR renders shard pages with initial HTML |
| UI-02 | P1 | Deep-link shard pages at `/shard/<hex16>` with 15-field inspector (collapsible panels: identity / triple / sense / framework / provenance / epistemic / dependencies / BFO / governance) | PRD §12; FEATURES §A | All 15 fields visible; content-negotiated (HTML to browser, TTL/JSON-LD to clients via `Accept:`) |
| UI-03 | P1 | Signature verification badge on every shard (valid ✓ / expired ⚠ / DID doc unreachable) | FEATURES §A | Badge reflects runtime verification; test with rotated + expired DIDs |
| UI-04 | P1 | Subtype + status chips (S/D/C/G/H icon + hypothesis/attested/contested/superseded/aporetic pill) | FEATURES §A | Visual regression test |
| UI-05 | P1 | Copy-as-citation button (BibTeX / Bluebook / Hyperlink; includes shard IRI + content hash + as-of date) | FEATURES §A | All 3 formats round-trip; citation survives content edits per §21.7 |
| UI-06 | P1 | Polysemy fork UI (distinguo workflow): flag surfacing → side-by-side sense panels → accept/reject/modify → prime-analogate picker → proportional-relation editor → distinction-kind selector → DID-signed commit | PRD §12; FEATURES §B | Full flow E2E with fixture; Playwright covers all 3 disposition paths |
| UI-07 | P1 | "What would this fork affect?" preview (dependents + SHACL re-validation + RAG chunk re-chunk) before distinguo commit | FEATURES §B diff; Brief Should-Have | Preview renders correctly for 3-hop dependency fixture |
| UI-08 | P1 | Supersession timeline with horizontal ribbon + as-of date picker + current-shard highlight + supersession chain nav + "why was this superseded?" panel + supersession-vs-retraction indicator | PRD §12; FEATURES §C | Timeline renders 10-link chain < 500ms; as-of picker re-renders shard |
| UI-09 | P1 | Transaction-time vs. valid-time toggle (bitemporal axes per §8.P2; gated behind advanced toggle) | FEATURES §C diff | Toggle changes query semantics; docs explain bitemporal model |
| UI-10 | P1 | Contest / supersede / retract wizards with three-way disambiguation prompt + distinct copy + retraction cascade preview | PRD §12, §21.8; FEATURES §H | All 3 wizards distinct in code + UI; no shared codepath (code review) |
| UI-11 | P1 | Dependency graph visualizer (Cytoscape.js DAG with 3-hop default, expand affordance, kernel-chain highlight) | FEATURES §A diff; Brief Should-Have | Graph renders 100-node fixture < 1s; click navigation works |
| UI-12 | P1 | Tractarian tree breadcrumb (sidebar: `1 → 1.2 → 1.2.3` with siblings via `fi:elaborates`) | FEATURES §A diff | Transitive closure cached; breadcrumb clickable + correct |
| UI-13 | P1 | Mandate `/gsd-discuss-phase` artifact (CONTEXT.md with UX decisions) before planning Phase 15.polysemy and Phase 15.contest sub-phases | Scope session 2026-04-22 | Plan phase gating: refuse to start without CONTEXT.md for these 2 sub-phases |
| UI-14 | P1 | Rollback / escape-hatch affordances: time-bounded (15 min) undo on just-committed distinguo; arbiter-override affordance on contest resolutions | FEATURES §B diff; Scope session | Undo within window reverts cleanly; arbiter override produces signed override event |
| UI-15 | P2 | Fregean sense/reference split panel (`sense` intensional + scoped; `reference` FOLIO IRI + TBox preview) | FEATURES §A diff | Panel present on all shards; clicking `reference` shows TBox info |
| UI-16 | P2 | "What does this sentence mean?" side-by-side view (source pinpoint vs. shard triple + `logical_form_imputed`) | FEATURES §A diff | View renders on shards with `logical_form_imputed` populated |
| UI-17 | P2 | RDF-star annotation expander (per-triple confidence, valid-time, extractor, reviewer signatures) | FEATURES §A diff | Expander fetches annotations via RDF-12 query and displays |
| UI-18 | P1 | WCAG 2.1 AA compliance enforced via axe-core 4.11 in Playwright CI (blocking gate) | Brief §Quality | CI fails on any axe violation; documented exemptions require RFC |
| UI-19 | P1 | Bold "shards-as-axioms" aesthetic via `/gsd-ui-phase` Phase 14 design contract before Phase 15 UI implementation | Brief §UI; FEATURES dep-notes | Design system + component library skeleton committed before any Phase 15 plan opens |

### CORPUS — Corpus Management & Federation

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| CORPUS-01 | P1 | Per-corpus configuration (framework registry, retention policies, reviewer role assignments, SHACL enforcement mode) | Brief §Corpus | Config loaded from `<corpus>/config.toml`; round-trip test |
| CORPUS-02 | P1 | Cross-corpus SPARQL queries work across named graphs; diff two corpora on same concept IRI | FEATURES §J | Query `?c1 ?p ?o` + `?c2 ?p ?o` returns diff; integration test |
| CORPUS-03 | P1 | `owl:sameAs` / `fi:analogousTo` links for cross-corpus references; no shared global shard namespace | FEATURES §J | Per-corpus IRI space preserved; `sameAs` links traversable |
| CORPUS-04 | P1 | Benchmark corpora ingested for GA: v1 advocacy + FRE + Restatement of Contracts | Brief §Benchmark | All 3 corpora load + pass SHACL + pass cluster validation |
| CORPUS-05 | P1 | Corpus-admin role-assertion flow (DID-signed `fi:RoleAssertion` grants roles per §3.1.1) | PRD §3.1.1 | Role grant + revocation E2E; governance log entry for each |
| CORPUS-06 | P1 | **Opt-in private corpora** with envelope encryption: per-corpus symmetric key encrypts serialized shards at rest; corpus key wrapped by admin DID's public key (via `cryptography.hazmat`) | Scope session 2026-04-22 (**promoted from Should-Have**) | Private corpus round-trips; P95 decrypt < 5ms per shard |
| CORPUS-07 | P1 | Private corpus access control: SPARQL queries return 404 for un-authorized DIDs; write API returns 403; governance log entries redacted from public feed | Scope session 2026-04-22 | AuthZ test: 3 DIDs (admin/reviewer/outside) see correct view |
| CORPUS-08 | P2 | Corpus fork capability (corpus_admin-only, DID-signed); derivative corpus has supersession links to origin | FEATURES §F, §J diff (**promoted from Defer**) | Fork operation creates new named graph + fork metadata; origin remains intact |
| CORPUS-09 | P2 | Corpus fork + genealogy visualizer (shows fork tree; click node → open corpus) | FEATURES §F diff (**promoted from Defer**) | Viz renders fork tree from fixture with 5 corpora + 3 fork events |

### OBS — Observability & Operations

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| OBS-01 | P1 | structlog 25.5 + OpenTelemetry 1.41 + prometheus-client 0.25 instrumentation across app + worker | Brief §Observability | Traces visible in OTel backend; Prometheus scrape works |
| OBS-02 | P1 | Prompt-attribute truncation (don't leak raw prompts > 2KB to traces; hash instead) | PITFALLS I4 | No prompt bloat; truncation test |
| OBS-03 | P1 | Aggregate LLM cost tracking per corpus (tokens in/out × provider price) | Brief §LLM | Cost report per corpus accurate within ±5% |
| OBS-04 | P1 | Dagger-based CI with reproducible builds across local + Railway | Brief §CI | Dagger pipeline builds identical image digests |

### SEC — Security & Audit

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| SEC-01 | P1 | **Phase 0 HARD GATE** — RDF-12 annotation pattern validates all PRD §20 query patterns, OR pivot to Apache Jena Fuseki (pre-specified fallback) | STACK RISK-3; Scope session 2026-04-22 | Phase 0 spike exits with decision artifact: `keep=pyoxigraph` OR `pivot=fuseki`; both branches have ROADMAP entries |
| SEC-02 | P1 | Phase 0 exit gates (5): P95 SPARQL < 500ms @ 1M triples; worker image < 500MB; SSR latency < 200ms; RDF-12 annotation pattern works; Dagger CI reproducible | Research §Phase 0 | All 5 gates measured in Phase 0; failures trigger scoped pivots (per SEC-01 branch) |
| SEC-03 | P1 | Pre-release security audit (crypto primitives, OAuth, DID rotation, SPARQL SERVICE/SSRF, rate limiting, write API input validation, GitHub-username-takeover → DID impersonation F7) | PRD §16 R5; PITFALLS #4, #6 | Audit report addresses all 7 areas with sign-off |
| SEC-04 | P1 | SERVICE SSRF defense verified via security test suite (external URL fetch attempt blocked) | PITFALLS #4 | Security test fails if SERVICE bypasses filter |
| SEC-05 | P1 | DID key rotation scenario tests: historical signatures verify after rotation; key-at-time-of-signing recovered | PITFALLS #6 | `test_signature_survives_key_rotation.py` green |
| SEC-06 | P1 | GitHub-username-takeover defense: DID binding requires DNS / `.well-known` proof of control; squatter detection | PITFALLS F7 | Squatter scenario test: old DID ↔ new GitHub account rejects |

### QUALITY — Acceptance Bars

| ID | Priority | Requirement | Source | Acceptance |
|----|----------|-------------|--------|------------|
| QUALITY-01 | P1 | **P95 SPARQL query latency < 500ms @ 1M triples** on benchmark corpus | Brief §Quality | Phase 0 harness measures; Phase 13 + 16 regressions caught in CI |
| QUALITY-02 | P1 | **WCAG 2.1 AA** passing per axe-core 4.11 on all user-facing pages | Brief §Quality | CI blocking; no waivers without RFC |
| QUALITY-03 | P1 | **Worker Docker image < 500 MB** (JVM + HermiT + deps) | Research §Phase 0 | Phase 0 measures; build-time check |
| QUALITY-04 | P1 | **SSR page latency < 200ms** for cold shard page | Research §Phase 0 | Phase 0 measures; SSR perf test in CI |
| QUALITY-05 | P1 | **Novel UX gate** — Phase 15.polysemy-fork and Phase 15.contest-wizard pass 3-5 legal-practitioner think-aloud sessions with ≥80% task completion before GA | Scope session 2026-04-22 | Session transcripts + completion rates documented in Phase 15 SUMMARY.md |
| QUALITY-06 | P1 | Test coverage: 203 v1 tests preserved + ~425 new tests passing; golden-set Tier 3 harness for shard extraction | PRD §13 | All tests green on `main`; coverage report ≥ 85% on new code |

---

## 3. Risk-Driven Requirements (research corrections)

| Risk | Requirement refs | Description |
|------|-------------------|-------------|
| RISK-1 owlready2/HermiT is NOT pure-Python (JVM jar) | PRINCIPLE-01, OBS-01, QUALITY-03 | Two-stage Dockerfile: JVM-free `web` tier; JVM-included `worker` tier. Cluster validator runs only in worker. |
| RISK-2 No Pydantic-to-SHACL generator exists | SHACL-02, SHACL-04 | ~150 LOC in-repo generator with build-time TTL emission. |
| RISK-3 Oxigraph 0.5.x dropped rdf-star for RDF 1.2 (BLOCKING Phase 0) | SEC-01, STORAGE-01, STORAGE-04 | Phase 0 spike as HARD GATE; pre-specified pivot to Apache Jena Fuseki on failure. Rewrite all PRD §20 queries for RDF-12. |
| RISK-4 Identity stack library picks | DID-01, DID-06 | `authlib 1.7 > fastapi-users`; `PyNaCl + cryptography + atproto + dag-cbor + jcs + joserfc`; explicit rejection of `didkit`, `pydid`, `python-jose`, `fastapi-users`. |

---

## 4. Anti-Requirements (DO NOT BUILD)

Inherited from brief + FEATURES anti-feature tables:

- **Inline shard editing** on public pages — bypasses DID-signed review flow
- **Vote up/down on shards** — §21.10 rejects system-imposed reputation
- **Hide rejected objections / losing arguments** — DisputedPropositionShard preserves them by design
- **Auto-apply distinguo** when detector confidence high — §16 R2 + §8.P6 demand human gate
- **Majority-vote contest resolution** — §21.8 + §21.10 preserve arbiter OR distinguo OR aporetic
- **Unified delete button** across retract/supersede/contest — conflates three categorically different ops
- **Unrestricted SPARQL UPDATE** on public endpoint — all writes through DID-gated REST
- **Server-held signing keys** — defeats decentralized-identity thesis
- **Anonymous contributions** — attestation requires identified DID
- **Auto-sync between corpora** — federation means intentional divergence
- **Shared global namespace across corpora** — breaks provenance anchoring
- **Reputation score / badges** — §21.10 explicit rejection
- **Auto-merge RFCs after N days of silence** — silence ≠ consensus; IETF rejects this pattern

---

## 5. Deferred to v2.1+

| Item | Reason deferred |
|------|-----------------|
| GraphQL endpoint | Surface area + schema-over-RDF is active research; not in brief |
| Live WebSocket subscriptions | Batch-pipeline architecture per PROJECT.md Out-of-Scope |
| Mobile-first apps | No signal from desktop research-tool audience |
| Per-shard DID-based key-agreement encryption (ECDH) | Complex + risky vs. envelope encryption; promote post-signal |
| Full post-release security audit (second pass) | Pre-release audit is P1 (SEC-03); second audit deferred to first post-GA quarter |
| "Cascade simulation" dry-run retraction with full rollback | Current cascade preview (GOV-06) is sufficient for GA; full transactional dry-run is analyst power tool |
| Contest vote visualization (position-bars) | Shipping with list rendering for GA; diff viz post-GA |
| Hardware-key signing ecosystem expansion beyond YubiKey / Ledger / WebAuthn | GA covers the 3 common cases |

---

## 6. Traceability

Every requirement above traces to at least one of:

- **PRD-v2.0-draft-2.md** (authoritative spec) — `§N.M` refs in Source column
- **.planning/v2.0-MILESTONE-BRIEF.md** (40+ locked decisions)
- **.planning/research/STACK.md** (version pins + RISKs 1-4)
- **.planning/research/FEATURES.md** (10 feature categories A-J)
- **.planning/research/PITFALLS.md** (10 "sink v2.0" + 25 watchlist)
- **Scope session 2026-04-22** (this requirements pass: Aggressive GA + 4 Defer promotions + private-corpora P1 + novel-UX gates)

When a requirement is implemented, link the implementing phase / plan in its acceptance-column or in a `fi:implements` annotation on the ROADMAP entry.

---

*Requirements defined: 2026-04-22*
*Next: spawn `gsd-roadmapper` for v2.0 ROADMAP.md (reset phase numbering at 1; ~21 phases per research §Implications for Roadmap + aggressive-GA scope adds)*
