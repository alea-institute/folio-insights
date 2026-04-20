# FOLIO Insights

## What This Is

A knowledge extraction and ontology enrichment system that processes legal advocacy textbooks (pretrial, trial, and appellate) to extract structured advice, legal principles, case citations, procedural rules, and common pitfalls — then organizes them into a task hierarchy and serializes everything as a validated, FOLIO-compatible OWL module. The system includes a web UI for corpus management, pipeline processing, task review, and ontology export.

## Core Value

Every piece of actionable legal advocacy knowledge from these texts must be discoverable by task — so that any practitioner, AI system, or developer querying "how do I take an expert deposition" gets a structured, hierarchical set of techniques, principles, and warnings mapped to formal FOLIO concepts.

## Current State

**Shipped:** v1.1 Railway Dev Deploy + UAT Gap Closure (2026-04-20)
**Live URL:** https://folio-insights-production.up.railway.app
**Tests:** 203 passing (197 at v1.0 + 6 UAT regression tests from v1.1)
**Tech stack:** Python 3.11+, FastAPI, SvelteKit, SQLite (aiosqlite), rdflib, pyshacl, sentence-transformers; Dockerfile + railway.toml for Railway

**What v1.1 adds on top of v1.0:**
- Railway dev deploy: multi-stage Dockerfile (node:20-slim → python:3.11-slim), bundled viewer + API + 3.8 MB extraction dataset, `/health` healthcheck, non-root runtime, 120s healthcheck timeout
- `railway.toml` config-as-code + frontend relative-URL audit (zero hardcoded dev ports)
- **UAT I-1:** LLM-path FOLIO IRI resolution at 0.6 threshold + `proposed_class` routing (+4 tests)
- **UAT I-2:** Bundle export 422 → 404 parity (+2 tests)
- **UAT I-3:** Vite proxy 8700 → 9925 (unblocks viewer dev-mode UI)
- **UAT I-4:** Deterministic `output/demo/` approved-task fixture + idempotent seed script
- **UAT I-5:** `.dockerignore` excludes `output/.jobs/` — bundled corpora report `processing_status="completed"` on live Railway

**What v1.0 delivers (still core):**
- CLI batch pipeline: `folio-insights extract` → `discover` → `export`
- Web UI: Upload → Process → Discover Tasks → Review → Export (full end-to-end)
- 14-format document ingestion with tiered boundary detection
- 4-path FOLIO concept tagging against 27K+ labels with 5-stage confidence scoring
- Task hierarchy discovery with NLI contradiction detection
- SHACL-validated OWL output with Turtle, JSON-LD RAG chunks, browsable HTML, changelog

## Current Milestone: v2.0 shards-as-axioms

**Goal:** Refactor FOLIO Insights from enrichment pipeline into a federated, shard-based knowledge graph grounded in PHILOSOPHY.md — where every 15-field shard is a provenance-hashed micro-axiom queryable via SPARQL, reviewable by DID-signed attestations, and composable across a federated community.

**Target features:**
- Shard envelope (§6.1) with 5 subtypes (§6.2): SimpleAssertion, DisputedProposition, ConflictingAuthorities, Gloss, Hypothesis
- Provenance-hash IRI scheme (§6.3) + content versioning with append-only audit (§6.4) + DID-signed attestations (§6.5)
- New FOLIO v2 vocabulary + mini-BFO spine (§7)
- Seven design principles (§8.P1–P7): scholastic distinguo, polysemy forks, cluster validator, etc.
- LLM-provider-agnostic pipeline refactor via `instructor` (§9)
- SHACL hybrid validation — Pydantic-generated base + hand-written advanced shapes (§10)
- Oxigraph triplestore + named-graph storage (§11) with RDF-star
- Review UI redesign (§12) — polysemy forks, supersession timeline, SPARQL explorer, deep-link shard URLs
- Federated governance (§3.1 own phase) — PROV-O log, §21.10 downstream-weighs, open community
- Public SPARQL endpoint + DID-gated writes
- Community artifacts: CONTRIBUTING, CODE_OF_CONDUCT, GOVERNANCE, RFC process
- Pre-release security audit (crypto + OAuth + DID signing)
- WCAG 2.1 AA blocking gate; P95 SPARQL <500ms @ 1M triples

**Key context:**
- Greenfield on master — no `V1_COMPAT` flag, no v1 corpora to migrate
- Stack locked: Oxigraph (pyoxigraph) + rdflib bridge; owlready2 reasoner; Arq+Redis queue; `instructor` LLM abstraction; SvelteKit 5 + adapter-node (SSR); mkdocs-material docs
- CalVer (YYYY.MM) versioning; MIT license retained
- Honor-system `Warrant:` line in every commit citing §5 pattern + §21 decision
- Benchmark corpora: v1 advocacy (re-extracted) + FRE + Restatement of Contracts
- Decisions already captured in `.planning/v2.0-MILESTONE-BRIEF.md` (40+ Q&A resolved pre-milestone)

## Requirements

### Validated (v1.0)

- ✓ Ingest mixed MD source files of variable length — v1.0
- ✓ Detect advice unit boundaries using LLM-driven semantic segmentation — v1.0
- ✓ Tag all extracted knowledge units against full FOLIO ontology (~18,000 concepts) — v1.0
- ✓ Reuse folio-enrich's EntityRuler + LLM dual-path extraction and 5-stage confidence scoring — v1.0
- ✓ Produce enriched output that is both human-reviewable and machine-parseable — v1.0
- ✓ Discover top-level advocacy tasks from texts — v1.0
- ✓ Build hierarchical task trees with sub-tasks and best practices — v1.0
- ✓ Extract all knowledge types: advice, principles, citations, procedural rules, pitfalls — v1.0
- ✓ Map extracted advice into FOLIO OWL — v1.0
- ✓ Support multiple consumption modes: SPARQL/API, LLM RAG, UI browsing — v1.0
- ✓ Handle incremental corpus growth without reprocessing — v1.0
- ✓ Automated quality with confidence scoring — v1.0

### Active

See `.planning/REQUIREMENTS.md` for v2.0 scoped requirements (populated during milestone kickoff).

### Out of Scope

- User-facing legal advice UI — consumers build their own on top of the ontology
- Substantive legal analysis — we extract what books say, not evaluate legal merit
- Real-time / interactive processing — batch pipeline; quality over speed
- Source text rewriting — "ideas not expressions" means distill, not rewrite
- Multi-language support — English corpus; leverage FOLIO's multilingual labels passively

## Context

**Source Material:** Mixed MD files — chapter extracts from published advocacy textbooks and synthesized notes covering pretrial, trial, and appellate advocacy. Growing corpus.

**Dependencies:**
- `folio-enrich` (at `~/Coding Projects/folio-enrich`) — bridge adapter imports FolioService, EntityRuler, reconciler
- `folio-python` (at `~/Coding Projects/folio-python`) — IRI generation algorithm (UUID4 → base64 → alphanumeric)
- FOLIO ontology (alea-institute/FOLIO on GitHub) — ~18,000 legal concepts

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Extend folio-enrich via bridge adapter | Reuse proven extraction/scoring; avoid duplicating 13 export formats | ✓ Good — bridge imports 27K+ labels cleanly |
| Full FOLIO ontology (not subset) | Advocacy texts span procedural, evidentiary, and substantive law | ✓ Good — no missed connections |
| Discover task hierarchy from texts | More robust than predefined taxonomy | ✓ Good — discovered tasks user hadn't considered |
| Single OWL file with embedded SKOS/PROV-O annotations | Simpler than separate companion file; all metadata in one artifact | ✓ Good — superseded original companion-file plan |
| Advice as annotation properties on Task/Subtask classes | Simplest model — advice goes with the class | ✓ Good — clean OWL structure |
| Standalone IRI generation (reimplemented from folio-python) | Avoids 10s ontology download on every export | ✓ Good — fast, compatible |
| Standalone sentence-transformers for deduplication | FAISS index in folio_bridge sized for FOLIO concepts, not pairwise similarity | ✓ Good — documented design choice |
| SvelteKit adapter-static served by FastAPI | SPA mode for review viewer; FastAPI handles API + static files | ✓ Good — simple deployment |

## Constraints

- **Ontology format**: Valid OWL compatible with FOLIO structure
- **Pipeline reuse**: Build on folio-enrich's architecture via bridge
- **Growing corpus**: Incremental additions without reprocessing
- **Multi-consumer**: Serve SPARQL queries, LLM retrieval, and human browsing

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-20 — v2.0 shards-as-axioms milestone started*
