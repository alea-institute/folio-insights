# Phase 0: Foundations / HARD GATE — Research

**Researched:** 2026-04-22
**Domain:** RDF 1.2 + SPARQL 1.2 on pyoxigraph 0.5.7; HermiT-in-Docker; SvelteKit 5 adapter-node SSR; Dagger CI reproducibility; 1M-triple gate-tuning
**Confidence:** HIGH on RDF 1.2 syntax shift + pyoxigraph migration + Dockerfile reproducibility; MEDIUM-HIGH on HermiT/JVM sizing; MEDIUM on SvelteKit SSR cold-start numbers; MEDIUM on pyoxigraph 1M P95 tuning knobs (limited public bench data)

## Summary

The research question was **not** "which library?" (all stack picks are locked per CONTEXT.md D-01..D-18 and REQUIREMENTS.md RISK-1..4) but **"what unknown mechanics of the locked stack will trip the 5 HARD GATES?"**

One finding dominates Phase 0: **pyoxigraph 0.5.x flipped RDF-star → RDF 1.2** with two breaking consequences that are still under-documented in the stack research notes this project currently relies on. First, **quoted triples in subject position are no longer valid** — only object-position triple terms work. Second, **SPARQL-star `<<?s ?p ?o>>` syntax was replaced by RDF 1.2 annotation pipes `{| ?p2 ?o2 |}`**, fixed in pyoxigraph 0.5.2 and current in 0.5.7 [VERIFIED: Oxigraph CHANGELOG via WebFetch 2026-04-22 + https://pyoxigraph.readthedocs.io]. Every PRD §20 query must be rewritten against the new syntax; this is the entire body of Gate 1 work. The `rdflib` bridge through `oxrdflib` **does not carry RDF 1.2 triple terms** — pyoxigraph maintainer Tpt explicitly recommends "use pyoxigraph directly" for RDF-star/RDF-1.2 workloads, which means `pyshacl` integration will require a pyoxigraph→Turtle→rdflib serialize/parse round-trip (not live `Graph` sharing) whenever triple terms are present [CITED: github.com/oxigraph/oxigraph discussion #886].

Gates 2–5 are more mechanical. Gate 2 (P95 < 500ms @ 1M) has thin public benchmarks — Oxigraph's own BSBM is at 35M/100k-products, with no 1M-specific latency numbers published. Tuning levers are: `Store.optimize()` after bulk_load, `Store.bulk_load()` over `.add()`, `default_graph` / `named_graphs` parameters to prune the dataset before evaluation, and warm-cache via pre-query. Gate 3 (worker <500MB) is achievable with jlink custom JRE (≈58MB measured by Abdelghani 2025 for a Spring Boot base; ~80-120MB realistic for HermiT's classpath) + distroless or alpine-slim Python; the 500MB target is aggressive but plausible. Gate 4 (SSR <200ms) hinges on SvelteKit's **streaming via unawaited promises in `load()`** plus `setHeaders()` for edge cache — SvelteKit 5 makes this opt-in (top-level promises no longer auto-awaited). Gate 5 (bit-identical digest) requires BuildKit ≥0.11 with `SOURCE_DATE_EPOCH`, base images pinned by `@sha256:...`, fixed UID/GID, hash-pinned pip (uv pip compile --generate-hashes), and — critically — Dagger does NOT yet natively emit `SOURCE_DATE_EPOCH`; it must be piped as a build arg to the underlying BuildKit container [VERIFIED: dagger.io/blog/reproducible-builds].

**Primary recommendation:** Structure Phase 0 as 5 gate-plans + 1 infra-plan + 1 rename-plan (see Architecture Patterns → Phase 0 Plan Topology below). Gate 1 is binary → run first. Gate 5 is infrastructure → enables Gates 2/3/4 measurement. Gates 2/3/4 have formal tune-first rules (D-05/D-06/D-07) with escape hatches; plan the tune-first passes as explicit sub-tasks, not "tune as needed."

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Phase boundary (do NOT revisit):**
- Stack picks: pyoxigraph 0.5.7, rdflib 7.6.0 bridge, owlready2/HermiT, SvelteKit 5 + adapter-node, Dagger, Arq+Redis 7.4, `instructor` LLM abstraction
- Pivot target (Gate 1 failure): Apache Jena Fuseki
- 5 Exit gates: STORAGE-04 (RDF-12 annotation), QUALITY-01 (P95 SPARQL <500ms @ 1M), QUALITY-03 (worker image <500MB), QUALITY-04 (SSR <200ms), OBS-04 (Dagger reproducibility)
- Two-stage Docker split: `web` (JVM-free) + `worker` (JVM-included)
- PHILOSOPHY.md rename from `2026-04-19_Philosophy.md` (trivial deliverable)
- Greenfield on master — no `V1_COMPAT` flag, no v1-corpora migration

**Benchmark corpus + gold query set:**
- **D-01:** Scaled real corpus — re-extract v1 advocacy + FRE + Restatement of Contracts, replay bitemporal variations to 1M triples.
- **D-02:** PRD §20 queries rewritten in RDF-12 + 3–5 adversarial edge cases (deep GRAPH traversal, large CONSTRUCT, SERVICE-blocked attempts).
- **D-03:** Subtype ratios derived from v1 re-extracted output.
- **D-04:** Gate 1 STRICT binary — 100% of PRD §20 examples rewrite successfully, or pivot to Fuseki.

**Gate-failure decision rules:**
- **D-05 (Gate 2):** Tune first (3-day pass: query hints, RocksDB tuning, warm cache). ≤800ms post-tune → accept with SLO adjustment; >800ms → pivot.
- **D-06 (Gate 3):** Tune first (strip JVM debug/docs, jlink custom image, slim deps). ≤700MB post-tune → accept; >700MB → split reasoner into microservice in Phase 10 (no pivot).
- **D-07 (Gate 4):** Tune streaming + warm cache. ≤400ms → accept with SLO adjustment; >400ms → deferred-hydration fallback (SPA shell + client fetch); NOT full adapter swap.
- **D-08 (Gate 5):** Bit-identical image digest between local Dagger and Railway-deployed (`docker inspect --format '{{.Id}}'` matches).

**Spike scope (MAX-FIDELITY):**
- **D-09:** Full SSR nav tree — shard page + polysemy fork + supersession timeline against live pyoxigraph.
- **D-10:** Full Dagger CI — build + test + lint + deploy + Railway trigger (replaces GitHub Actions outright).
- **D-11:** Full 1M ABox HermiT reasoning against real FOLIO v2 TBox (cold-start + reasoning baseline).
- **D-12:** Open-ended timebox — Phase 0 runs until all 5 gates resolve.

**1M-triple load generator:**
- **D-13:** Scaled real corpus (matches D-01).
- **D-14:** CLI + pytest fixture dual API — `folio-insights bench gen --target 1000000 --out fixtures/bench.nq` + `@pytest.fixture def bench_1m_corpus`.
- **D-15:** Seeded deterministic — `--seed N` produces identical output.
- **D-16:** Phase-profile flags — `bench gen --profile phase-13-storage` / `--profile phase-16-sparql-adversarial` for reuse.

**Decision artifact:**
- **D-17:** `.planning/phases/00-foundations-hard-gate/00-DECISION.md` with binary verdict + per-gate measurement table + tuning passes + downstream branch guidance.

**PHILOSOPHY.md rename:**
- **D-18:** Pure rename only (`2026-04-19_Philosophy.md` → `PHILOSOPHY.md` at repo root). No content restructure.

### Claude's Discretion

- Exact query patterns for adversarial set (D-02) — researcher picks from §21 risk matrix
- JVM heap sizing (`-Xmx`) once HermiT measurements land
- Dagger pipeline stage ordering (build→test→lint→deploy) — standard patterns apply
- Subtype-ratio derivation methodology (D-03)

### Deferred Ideas (OUT OF SCOPE)

- **DID-signing the DECISION.md artifact** — deferred to Phase 6+ (DID substrate doesn't exist yet).
- **PHILOSOPHY.md content restructure** — Phase 18 (community artifacts), not Phase 0.
- **Query-log gold-set harvest from live Railway** — no v1 Railway traffic worth harvesting.
- **Per-gate time budget** — user rejected (D-12).
- **Separate Phase 0 sub-phases per gate** — single phase with gate-labeled plans.

### Downstream impact to flag in planning
- **Phase 15 overlap:** D-09 full SSR nav prototype partially pre-builds Phase 15 deliverables.
- **Phase 17 overlap:** D-10 full Dagger CI means Phase 17 inherits pipeline; Phase 17 narrows to test consolidation only.
- **Phase 20 overlap:** D-10 Railway trigger + D-08 bit-identical digest mean Phase 20 narrows to CalVer cut + announce.
- **Phase 10 dependency:** D-06 escape-hatch (split reasoner microservice) alters Phase 10 architecture if Gate 3 fails post-tune.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEC-01 | Phase 0 HARD GATE — RDF-12 annotation validates PRD §20 OR pivot to Apache Jena Fuseki | RDF 1.2 syntax findings (§Code Examples, §Common Pitfalls D1); Fuseki pivot scaffold (§Fuseki Pivot Scaffold) |
| SEC-02 | 5 gate measurement + failure triggers scoped pivots | §Gate-Tuning Playbooks for Gates 2/3/4; §Architecture Patterns → Phase 0 Plan Topology |
| STORAGE-04 | RDF 1.2 annotation validates PRD §20 queries | §Code Examples (RDF-12 rewrite patterns) + §Common Pitfalls D1 (annotation pipe syntax, object-only constraint, rdflib bridge limitations) |
| QUALITY-01 | P95 SPARQL < 500ms @ 1M triples | §Gate-Tuning Playbooks → Gate 2 (bulk_load + optimize + named_graphs pruning + warm cache); §Standard Stack → RocksDB tuning knobs |
| QUALITY-03 | Worker Docker image < 500MB (JVM 17 + HermiT + deps) | §Gate-Tuning Playbooks → Gate 3 (jlink custom JRE, distroless, strip-debug); §Don't Hand-Roll (don't invoke HermiT directly — use owlready2) |
| QUALITY-04 | SSR page latency < 200ms for cold shard page | §Gate-Tuning Playbooks → Gate 4 (streaming load, setHeaders cache-control, @polka/compression); §Code Examples (streaming +page.server.ts) |
| OBS-04 | Dagger CI reproducible — bit-identical digest local vs Railway | §Gate-Tuning Playbooks → Gate 5 (SOURCE_DATE_EPOCH, pinned digests, UID/GID, hash-pinned pip); §Common Pitfalls (Dagger SOURCE_DATE_EPOCH caveat) |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| RDF 1.2 triple load / SPARQL eval | Database (pyoxigraph Store, RocksDB on disk) | — | pyoxigraph is the canonical store; rdflib never writes directly (STORAGE-02 bridge-only) |
| SHACL validation @ 1M | Worker (pyshacl subprocess on serialized corpus slice) | Database (pyoxigraph serves the corpus via `dump(RdfFormat.TURTLE)`) | pyshacl needs rdflib `Graph`; rdflib has no RDF-12 support so pyoxigraph must serialize Turtle, rdflib parses it |
| Cluster validation (OWL 2 EL reasoning) | Worker (JVM 17 + HermiT via owlready2 subprocess) | — | JVM 17 is required; never ships on the web tier (RISK-1 mitigation) |
| SSR shard page render | Frontend server (SvelteKit adapter-node) | API/Backend (FastAPI `/sparql` endpoint) | adapter-node owns SSR; API owns the SPARQL query execution; browser only receives streamed HTML |
| Gate harness / benchmark runner | CLI (folio-insights bench) | Test suite (pytest fixture) | Dual surface per D-14 so the same generator feeds both ad-hoc perf runs and CI regressions |
| Reproducible image build | CI (Dagger pipeline → BuildKit) | Deploy target (Railway) | Dagger orchestrates; BuildKit performs reproducible export; Railway deploys the digest (never rebuilds) |
| Benchmark corpus persistence | Artifact (`fixtures/bench.nq` committed) | CLI (regenerate-from-seed for reproducibility) | Committed artifact → fast CI; seeded regeneration → Gate 5 digest stability |

## Standard Stack

### Core (Phase 0)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pyoxigraph | 0.5.7 | RDF 1.2 store + SPARQL 1.2 engine | Locked per STACK.md RISK-3; RocksDB-backed, only Python lib with SPARQL 1.2 annotation pipe syntax [VERIFIED: pyoxigraph readthedocs via Context7 2026-04-22] |
| rdflib | 7.6.0 | Bridge for pyshacl / JSON-LD / Turtle **only** (not primary store) | Locked per STORAGE-02; **does not support RDF 1.2** — use via serialize/parse round-trip [CITED: github.com/oxigraph/oxigraph/discussions/886] |
| pyshacl | 0.31.0 | SHACL validation (consumes rdflib.Graph/Dataset) | Already in `pyproject.toml`; locked |
| owlready2 | 0.50 | HermiT reasoner wrapper (invokes `java -jar HermiT.jar` as subprocess) | Locked per RISK-1; **not pure Python**, requires JVM [CITED: owlready2.readthedocs.io/reasoning; WebSearch verified subprocess pattern with `-Xmx%sM` heap flag 2026-04-22] |
| SvelteKit | 5.55.4 | SSR + streaming via unawaited promises in `load()` | Locked per UI-01; adapter-node swap from adapter-static [VERIFIED: Context7 /sveltejs/kit docs 2026-04-22] |
| @sveltejs/adapter-node | 5.5.4 | Node.js runtime adapter (replaces adapter-static) | Unlocks SSR streaming [VERIFIED: svelte.dev/docs/kit/adapter-node] |
| Dagger | latest (install in Phase 0) | Reproducible containerized CI | Locked per OBS-04; Python or Go SDK; orchestrates BuildKit [VERIFIED: dagger.io/blog/reproducible-builds — Dagger "doesn't claim to solve reproducible builds" alone; pairs with SOURCE_DATE_EPOCH build arg] |
| BuildKit | ≥0.11 | Reproducible Docker exports with `SOURCE_DATE_EPOCH` + `rewrite-timestamp` | Locked indirectly via Dagger's OCI backend [CITED: docker.com/blog/highlights-buildkit-v0-11-release] |
| Arq | 0.28.0 | Async worker queue on Redis | Phase 10 cutover; Phase 0 provisions Redis sidecar via Dagger so pipeline can be tested |
| Redis | 7.4 | Arq broker + edge cache candidate for Gate 4 | Sidecar in Dagger pipeline |

**Version verification (2026-04-22):**
```bash
# pyoxigraph 0.5.7 released 2026-04-19 — confirmed in Oxigraph CHANGELOG via WebFetch
# pyoxigraph 0.5.6 (2026-03-14), 0.5.5 (2026-02-14) are prior
# pyoxigraph 0.5.2 is the release that FIXED the SPARQL 1.2 annotation pipe evaluation
```

**Installation (target worker stage):**
```bash
# Via uv (already in baseline Dockerfile)
uv pip install --system \
  'pyoxigraph==0.5.7' \
  'rdflib==7.6.0' \
  'pyshacl==0.31.0' \
  'owlready2==0.50' \
  'arq==0.28.0'
# Gate-3 tuning: pip install with hash-pinned requirements.lock for Gate 5 reproducibility
```

### Supporting (Phase 0 only)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| oxrdflib | latest 0.5.x-compat | rdflib Store backed by pyoxigraph | Consider for non-RDF-12 SHACL paths; **reject for RDF-12 paths** — use direct pyoxigraph + serialize round-trip |
| pytest-benchmark | ≥5.1 | Statistical measurement of Gate 2 P95 | Standard perf-benchmark fixture; commits results as JSON for trend tracking |
| hyperfine | latest | CLI-level latency measurement for Gate 4 (warm + cold) | Measures full page-render wall-clock; replaces bespoke bash timing |
| pip-tools / uv pip compile | 0.9+ | Hash-pinned `requirements.lock` for Gate 5 | `uv pip compile --generate-hashes` produces lock file consumed by reproducible build |
| @polka/compression | latest | Streaming-safe gzip middleware for adapter-node | **Standard `compression` package breaks streaming** per SvelteKit docs; always use `@polka/compression` [CITED: svelte.dev/docs/kit/adapter-node] |
| secoresearch/fuseki | 5.x | **Fuseki pivot scaffold only** — not installed unless Gate 1 fails | Preconfigured Fuseki Docker with SHACL + TDB2; minimum-viable conditional branch |

### Alternatives Considered (not locked — rejected per D-04/D-05/D-06/D-07)

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pyoxigraph 0.5.7 | Apache Jena Fuseki | **Only on Gate 1 failure (binary)**; external process, HTTP hop adds ~5-15ms base latency, but mature SPARQL 1.1 + SHACL + TDB2 named-graph support |
| owlready2+HermiT | `reasonable` (Rust OWL 2 RL) | OWL 2 RL not EL — would need TBox profile re-check; **escape hatch for D-06 post-tune**, not primary pick |
| adapter-node streaming | Deferred-hydration SPA shell | **Only if Gate 4 post-tune >400ms** per D-07; client-side fetch after static shell renders |
| Dagger + BuildKit | GitHub Actions + docker buildx | Rejected — D-10 MAX-FIDELITY user choice; Dagger is the locked pick |
| Scaled real corpus | Pure synthetic (BSBM / LUBM) | Rejected per D-01/D-13; realism dominates over volume for downstream phase reuse |

## Architecture Patterns

### System Architecture Diagram (Phase 0 gate harness)

```
              ┌─────────────────────────────────────────────────┐
              │ 1M-triple load generator (CLI + pytest fixture) │
              │  folio-insights bench gen --seed N --target 1M  │
              │  - re-extracts v1 advocacy                       │
              │  - adds FRE + Restatement                         │
              │  - replays bitemporal variations                 │
              └───────────────────┬─────────────────────────────┘
                                  │ N-Quads
                                  ▼
  ┌─────────────────────┐   bulk_load    ┌─────────────────────────┐
  │ fixtures/bench.nq   │───────────────▶│ pyoxigraph 0.5.7 Store  │
  │ (committed artifact,│                │  RocksDB on disk        │
  │  determinstic)      │                │  named_graphs per corpus│
  └─────────────────────┘                └──────────┬──────────────┘
                                                    │
      ┌────────────────┬─────────────────┬──────────┤
      │                │                 │          │
      ▼                ▼                 ▼          ▼
  ┌───────┐       ┌─────────┐      ┌──────────┐ ┌─────────────┐
  │Gate 1 │       │Gate 2   │      │Gate 3    │ │Gate 4       │
  │RDF-12 │       │P95<500ms│      │<500MB    │ │SSR<200ms    │
  │syntax │       │harness  │      │image     │ │cold shard   │
  │audit  │       │pytest-  │      │ (jlink+  │ │ (adapter-   │
  │all §20│       │benchmark│      │ distro-  │ │  node +     │
  │queries│       │ + warm  │      │ less +   │ │  streaming) │
  │       │       │ cache   │      │ owlready2│ │             │
  │STRICT │       │ + hints │      │ subproc) │ │             │
  └───┬───┘       └────┬────┘      └────┬─────┘ └──────┬──────┘
      │                │                │              │
      └────────┬───────┴────────┬───────┴──────┬───────┘
               │                │              │
               ▼                ▼              ▼
         ┌──────────────────────────────────────────┐
         │ Gate 5: Dagger CI (replaces GH Actions)  │
         │  - build local digest                    │
         │  - build Railway digest                  │
         │  - assert ==                             │
         │  SOURCE_DATE_EPOCH + pinned digests      │
         │  + UID/GID + hash-pinned pip             │
         └─────────────────┬────────────────────────┘
                           │
                           ▼
                ┌────────────────────────┐
                │ 00-DECISION.md         │
                │  verdict: keep | pivot │
                │  per-gate table        │
                │  tuning passes         │
                │  downstream branches   │
                └────────────────────────┘
```

### Phase 0 Plan Topology (recommendation)

Gates are NOT independent — Gate 5 (reproducible build) is infra that enables Gates 2/3/4 measurement, and Gate 1 is binary (run first, if fails everything else restructures around Fuseki). Recommend 7 plans:

| Plan | Covers | Blocks | Parallelizable? |
|------|--------|--------|-----------------|
| P0-A | PHILOSOPHY.md rename + `docs/` cleanup (D-18) | nothing | Yes — fully independent |
| P0-B | 1M-triple load generator (D-13..D-16) | P0-C, P0-D, P0-F | No — critical path |
| P0-C | Gate 1: RDF-12 rewrite of §20 + adversarial (D-02, D-04) | P0-F (decision) | After P0-B |
| P0-D | Two-stage Dockerfile (web/worker split) + Redis sidecar | P0-E, P0-F | After P0-B |
| P0-E | Dagger CI pipeline + Railway trigger (D-10, Gate 5) | P0-F (runs Gate measurements) | After P0-D |
| P0-F | Gates 2/3/4 measurement + tuning (D-05/D-06/D-07) | P0-G | After P0-C, P0-E |
| P0-G | DECISION.md artifact (D-17) + downstream-phase branch guidance | phase exit | After P0-C, P0-F |

**Parallelization:** P0-A can run in Wave 0 parallel with anything. P0-B is Wave 1 critical path. P0-C / P0-D can run in parallel in Wave 2. P0-E in Wave 3 once P0-D lands. P0-F gate measurement in Wave 4. P0-G synthesis in Wave 5. This aligns with D-12's open-ended timebox — no artificial per-gate time cap, but wave boundaries create natural sync points.

### Recommended Project Structure

```
.planning/phases/00-foundations-hard-gate/
├── 00-CONTEXT.md          # exists (18 decisions)
├── 00-DISCUSSION-LOG.md   # exists
├── 00-RESEARCH.md         # this file
├── 00-PLAN-*.md           # 7 plans per topology above
├── 00-VERIFICATION.md     # from gsd-verify-work
└── 00-DECISION.md         # FINAL ARTIFACT (D-17)

src/folio_insights/bench/
├── __init__.py
├── generator.py           # 1M-triple scaled-real generator (D-13..D-16)
├── profiles.py            # phase-profile flags (D-16)
└── cli.py                 # `folio-insights bench gen` CLI (D-14)

tests/bench/
├── conftest.py            # @pytest.fixture def bench_1m_corpus (D-14)
├── test_rdf12_patterns.py # Gate 1 regression — PRD §20 rewrites (D-02)
├── test_adversarial.py    # Gate 1 adversarial: SERVICE-blocked, deep GRAPH, large CONSTRUCT
├── test_p95_sparql.py     # Gate 2 — pytest-benchmark @500ms budget
└── test_ssr_latency.py    # Gate 4 — cold-page hyperfine harness

fixtures/
├── bench.nq               # committed 1M-triple N-Quads (D-15 deterministic seed)
└── gold_queries/          # §20 rewritten SPARQL + adversarial
    ├── q01_disputed_contracts.sparql
    ├── q02_retract_cascade_702.sparql
    ├── q03_analogia_crosscorpus.sparql
    └── adversarial/
        ├── deep_graph_traversal.sparql
        ├── large_construct.sparql
        └── service_blocked.sparql

docker/
├── Dockerfile.web         # JVM-free; adapter-node build + FastAPI runtime
├── Dockerfile.worker      # JVM 17 jlink custom runtime + HermiT + owlready2
└── dagger/
    ├── build.py           # Dagger Python SDK pipeline
    └── railway.py         # Railway deployment trigger

PHILOSOPHY.md              # renamed from 2026-04-19_Philosophy.md at repo root (D-18)
```

### Pattern 1: RDF 1.2 annotation pipe in SPARQL 1.2

**What:** SPARQL-star's `<<?s ?p ?o>>` subject-pattern is replaced by RDF 1.2's annotation block `{| ?p2 ?o2 |}` which follows a triple pattern.
**When to use:** Every PRD §20 query that needs to attach confidence / valid-time / extractor metadata to an asserted triple.
**Example (the Gate 1 rewrite pattern):**
```sparql
# Old (SPARQL-star 0.4.x — BROKEN in pyoxigraph 0.5.7):
SELECT ?shard ?confidence WHERE {
  <<?shard fi:subject ?concept>> fi:confidence ?confidence .
}

# New (SPARQL 1.2 annotation pipe — pyoxigraph 0.5.2+):
SELECT ?shard ?confidence WHERE {
  GRAPH ?g {
    ?shard fi:subject ?concept {| fi:confidence ?confidence |}
  }
}
# Source: https://github.com/oxigraph/oxigraph/blob/main/CHANGELOG.md (0.5.2 entry:
# "fixes evaluation of RDF 1.2 annotation syntax (e.g. SELECT * WHERE { ?s ?p ?o {| ?p2 ?o |} )")
```

### Pattern 2: pyoxigraph ↔ pyshacl bridge (named graphs + RDF 1.2 aware)

**What:** pyoxigraph holds the canonical store with RDF 1.2 triple terms; pyshacl wants an rdflib `Dataset`; rdflib does not understand RDF 1.2 annotation triples. Bridge via **serialize-to-Turtle then parse** (round-trip), losing triple-term annotations that aren't valid Turtle 1.2 in rdflib.
**When to use:** Per-shard SHACL validation (SHACL-03 requires per-shard incremental); NOT per-corpus batch.
**Example:**
```python
# src/folio_insights/bench/shacl_bridge.py
from pyoxigraph import Store, NamedNode, RdfFormat
from rdflib import Dataset
from pyshacl import validate

def validate_shard_via_bridge(store: Store, shard_iri: NamedNode, shapes_graph_path: str):
    # 1. CONSTRUCT the shard subgraph from pyoxigraph (triple terms flattened)
    construct_query = f"""
    CONSTRUCT {{ ?s ?p ?o }}
    WHERE {{ GRAPH ?g {{ ?s ?p ?o . FILTER(?s = <{shard_iri.value}>) }} }}
    """
    turtle_bytes = b"".join(store.query(construct_query).serialize(format=RdfFormat.TURTLE))

    # 2. Parse into rdflib Dataset for pyshacl
    data_graph = Dataset()
    data_graph.parse(data=turtle_bytes, format="turtle")

    # 3. Validate
    conforms, report_graph, report_text = validate(
        data_graph=data_graph,
        shacl_graph=shapes_graph_path,
        inference="rdfs",
        serialize_report_graph=True,
    )
    return conforms, report_text
```
**Source:** pyoxigraph `Store.query()` + `Store.dump(RdfFormat.TURTLE)` docs via Context7 2026-04-22; github.com/oxigraph/oxigraph/discussions/886 (maintainer recommends direct pyoxigraph over rdflib bridge for RDF 1.2).

### Pattern 3: SvelteKit 5 streaming SSR load

**What:** Return unawaited promises from `+page.server.ts` `load()`; SvelteKit streams HTML as each resolves. Critical data is awaited and blocks initial paint; nice-to-have data streams after.
**When to use:** Gate 4 baseline — shard page must paint critical fields before slow queries (dependency graph, attestation verification) resolve.
**Example:**
```typescript
// viewer/src/routes/shard/[hex16]/+page.server.ts
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch, setHeaders }) => {
  // Critical path: blocks initial paint (must be <200ms)
  const shardCore = await fetch(`/api/shard/${params.hex16}/core`).then(r => r.json());

  // Gate 4 tuning: edge-cache the HTML for 60s on repeat renders
  setHeaders({ 'cache-control': 'public, max-age=60, s-maxage=60' });

  return {
    shard: shardCore,                                              // awaited — blocks
    dependencies: fetch(`/api/shard/${params.hex16}/deps`).then(r => r.json()),      // streams
    attestations: fetch(`/api/shard/${params.hex16}/attests`).then(r => r.json()),   // streams
  };
};
// Source: /sveltejs/kit Context7 fetch 2026-04-22 (load + setHeaders + streaming promises)
```
```svelte
<!-- +page.svelte -->
<script>
  export let data;
</script>

<h1>{data.shard.iri}</h1>
<ShardCore shard={data.shard} />

{#await data.dependencies}
  <DependencySkeleton />
{:then deps}
  <DependencyGraph {deps} />
{/await}
```

### Pattern 4: Dagger reproducible build pipeline (Python SDK)

**What:** Dagger orchestrates; BuildKit enforces timestamp + layer determinism via `SOURCE_DATE_EPOCH`. Pin base image by digest, fix UID/GID, install with hash-pinned requirements.
**When to use:** Every Phase 0 CI run; Railway deploy triggers from the same pipeline (D-10 MAX-FIDELITY).
**Example:**
```python
# docker/dagger/build.py
import anyio, dagger, os

# Pinned by digest — not by tag — for reproducibility
PYTHON_DIGEST = "python:3.11-slim@sha256:<pinned-digest-from-docker-hub>"
NODE_DIGEST = "node:22-slim@sha256:<pinned-digest-from-docker-hub>"
TEMURIN_DIGEST = "eclipse-temurin:17-jre-alpine@sha256:<pinned-digest>"

async def main():
    async with dagger.Connection() as client:
        # Git commit timestamp → SOURCE_DATE_EPOCH for deterministic mtimes
        source_date_epoch = os.popen("git log -1 --pretty=%ct").read().strip()

        src = client.host().directory(".", exclude=[".git", "output", ".planning", "node_modules"])

        # Worker stage (with JVM for HermiT)
        worker = (
            client.container()
            .from_(TEMURIN_DIGEST)
            .with_env_variable("SOURCE_DATE_EPOCH", source_date_epoch)
            .with_exec(["apk", "add", "--no-cache", "python3", "py3-pip"])
            .with_directory("/app", src)
            .with_workdir("/app")
            .with_exec(["pip", "install", "--no-cache-dir",
                        "--require-hashes", "-r", "requirements.lock"])
            # Fix UID/GID for determinism
            .with_exec(["adduser", "-D", "-u", "1001", "appuser"])
            .with_user("1001")
        )

        # Web stage (JVM-free) — from python:3.11-slim
        web = (
            client.container()
            .from_(PYTHON_DIGEST)
            .with_env_variable("SOURCE_DATE_EPOCH", source_date_epoch)
            .with_directory("/app", src)
            # ... analogous steps, no Java
        )

        # Publish both; capture digests for Gate 5 comparison
        worker_digest = await worker.publish("ttl.sh/fi-worker:0.1")
        web_digest = await web.publish("ttl.sh/fi-web:0.1")
        print(f"Worker: {worker_digest}")
        print(f"Web: {web_digest}")

anyio.run(main)
# Source: dagger.io/blog/reproducible-builds + BuildKit SOURCE_DATE_EPOCH docs 2026-04-22
# Caveat: Dagger does NOT yet natively emit SOURCE_DATE_EPOCH; pipe as build arg.
```

### Pattern 5: jlink custom JRE for Gate 3

**What:** Eclipse Temurin's full JRE is ~180MB; jlink-stripped custom runtime for HermiT's classpath drops to ~60-80MB.
**When to use:** Worker image Gate 3 tuning pass (D-06 tune-first).
**Example:**
```dockerfile
# docker/Dockerfile.worker — builder stage: jlink custom JRE
FROM eclipse-temurin:17-jdk-alpine@sha256:<pinned-digest> AS jre-builder
RUN $JAVA_HOME/bin/jlink \
        --add-modules java.base,java.logging,java.xml,java.naming,java.sql,jdk.crypto.ec \
        --strip-debug \
        --no-man-pages \
        --no-header-files \
        --compress=2 \
        --output /opt/java-custom

# Worker runtime stage: Alpine + custom JRE + Python
FROM python:3.11-alpine@sha256:<pinned-digest>
COPY --from=jre-builder /opt/java-custom /opt/java-custom
ENV JAVA_HOME=/opt/java-custom PATH="/opt/java-custom/bin:$PATH"
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
# owlready2 will find `java` on PATH; points at custom runtime
# Source: Abdelghani 2025 "Optimizing java base docker images size from 674Mb to 58Mb"
#         + Adoptium jlink guidance
```

### Anti-Patterns to Avoid

- **Anti-pattern: Using rdflib as primary store.** Already rejected in STORAGE-02. The bridge is **one-way** (pyoxigraph → Turtle → rdflib) because rdflib does not support RDF 1.2. Never write to rdflib and expect pyoxigraph to see it.
- **Anti-pattern: Subject-position triple terms.** `<<?s ?p ?o>> ?p2 ?o2` is no longer valid in pyoxigraph 0.5.x. RDF 1.2 explicitly drops this. Use the annotation pipe `?s ?p ?o {| ?p2 ?o2 |}` or `rdf:Statement` reification [VERIFIED: Oxigraph CHANGELOG 0.5.0-beta.1].
- **Anti-pattern: `compression` package with adapter-node.** Breaks SvelteKit streaming. Always use `@polka/compression` [CITED: svelte.dev/docs/kit/adapter-node].
- **Anti-pattern: Tagged base images.** `python:3.11-slim` is a moving target. Use `python:3.11-slim@sha256:...` for Gate 5 determinism.
- **Anti-pattern: `useradd -r` without fixed UID.** Default UID allocation is non-deterministic. Use `useradd -u 1001 -g 1001` (or Alpine's `adduser -u 1001`).
- **Anti-pattern: `docker buildx build` without `--output type=image,rewrite-timestamp=true`.** Timestamps leak into layer metadata; digest mismatches between local and Railway.
- **Anti-pattern: Ad-hoc per-gate perf measurement.** Use `pytest-benchmark` + `hyperfine` so Gates 2/3/4 measurements live in CI with statistical assertions; one-off curl + time is not reproducible.
- **Anti-pattern: Triple terms in SHACL validation via rdflib.** Serialize through Turtle first — rdflib will silently drop annotation triples. Validate only what Turtle 1.2 can express, or validate in pyoxigraph via SPARQL `ASK` shapes.
- **Anti-pattern: Running HermiT in the web tier.** JVM bloat on web violates QUALITY-03 two-stage split. Reasoning runs in worker only, async warn-only per PRINCIPLE-01.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HermiT reasoner invocation | Raw `java -jar HermiT.jar` subprocess | `owlready2.sync_reasoner_hermit()` | owlready2 manages temp file, classpath, error parsing, closed-world flag; reinventing is ~300 LOC of edge cases [CITED: owlready2.readthedocs.io/reasoning] |
| SSR streaming | Custom WritableStream in `+server.ts` | Unawaited promise returns from `load()` | SvelteKit 5 streams promises natively, handles Promise.reject, wraps in {#await} blocks [VERIFIED: /sveltejs/kit Context7 docs] |
| Reproducible Docker builds | Custom timestamp-stripping + layer pinning scripts | `SOURCE_DATE_EPOCH` + BuildKit `rewrite-timestamp` | BuildKit 0.11+ provides this natively; DIY is fragile and misses apt/pip/wheel mtime cases [VERIFIED: reproducible-builds.org/docs/source-date-epoch/] |
| 1M-triple perf harness | Bespoke timing loop + stdev calc | `pytest-benchmark` + `hyperfine` | Both emit JSON; pytest-benchmark integrates with CI assertions; hyperfine handles warm/cold distinction |
| pyoxigraph → rdflib bridge | Manual Store traversal + Graph construction | `store.dump(RdfFormat.TURTLE)` → `graph.parse(data=..., format="turtle")` | The canonical bridge in STORAGE-02; maintainer-recommended [CITED: github.com/oxigraph/oxigraph/discussions/886] |
| Bit-identical digest check | Custom `docker inspect` parsing | `docker inspect --format '{{.Id}}'` + plain shell compare (D-08) | Already the standard; no reason to build a library |
| Base-image digest pinning | Copy-paste sha256 hashes into multiple files | Single `.env.docker` with `PYTHON_DIGEST=sha256:...` consumed by Dockerfile `FROM ${PYTHON_IMAGE}@${PYTHON_DIGEST}` + Dagger | Diffs easy to audit; one place to update per-base-image; pin `buildkit` version too |
| Fuseki pivot scaffold | Roll own TDB2 config | `apache/jena-fuseki:5.1.0` or `secoresearch/fuseki` Docker image | Fuseki 5 ships with SHACL + TDB2 + auth; `ENABLE_SHACL=1` flag; well-documented minimum-viable config [CITED: jena.apache.org/documentation/fuseki2/] |
| apt-get deterministic install | Custom snapshot of Debian packages | `apt-get install -y --no-install-recommends <pkg>=<exact-version>` + `rm -rf /var/lib/apt/lists/*` | Pinned versions + purging cache is the canonical Debian-reproducibility pattern |
| Python dep reproducibility | `pip freeze` output | `uv pip compile --generate-hashes -o requirements.lock` + `pip install --require-hashes -r requirements.lock` | Hash-pinned install is mandatory for Gate 5; freeze alone lacks hashes |

**Key insight:** Phase 0 is a measurement phase, not a systems-building phase. Every "Don't hand-roll" above is either (a) standard tooling with a known canonical pattern, or (b) a maintainer recommendation from the upstream library. Custom code in Phase 0 is a smell — the one exception is the 1M-triple load generator (D-13..D-16), which is unavoidably project-specific because it must re-extract v1 corpora under v2 pipeline.

## Gate-Tuning Playbooks

### Gate 1 — RDF 1.2 annotation pattern works

**Rule (D-04):** STRICT binary. 100% of PRD §20 examples rewrite in RDF-12 and execute correctly, OR pivot to Fuseki.

**Execution (no tuning — syntax audit only):**
1. Enumerate PRD §20 queries (3 in current PRD; the CONTEXT.md plus SPARQL-08 templates expand this to 13 total including polysemy/supersession/as-of/framework-filter).
2. For each, apply the rewrite pattern:
   - `<<?s ?p ?o>> ?ann ?val` → `?s ?p ?o {| ?ann ?val |}`
   - If original had subject-position triple term → **cannot rewrite** → attempt `rdf:Statement` reification → if query semantics preserved, count as pass; otherwise count as fail.
3. Commit each rewrite as `tests/bench/test_rdf12_patterns.py` with expected row count assertion.
4. Run against 1M-triple corpus (P0-B generator).
5. **Pass criterion:** all queries return non-empty results AND match semantic expectation (spot-check with arbiter).
6. **Fail criterion:** any query cannot be expressed or returns wrong results → trigger Fuseki pivot (P0-G DECISION.md).

**Adversarial set (D-02 — Claude's discretion from §21 risk matrix):**
- `adversarial/deep_graph_traversal.sparql` — `GRAPH ?g { ?s (fi:dependsOnAxiom|fi:dependsOnDefinition)+ ?o }` traversing 10 named graphs (cross-corpus per §21.8 contest-cascade).
- `adversarial/large_construct.sparql` — `CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }` on a full 1M graph to measure memory + serialization P95.
- `adversarial/service_blocked.sparql` — `SERVICE <http://evil.example/sparql> { ?s ?p ?o }` to verify the `SERVICE`-stripping middleware (Phase 16 dependency; Phase 0 records "blocked correctly" as a Gate 1 sub-assertion).
- `adversarial/service_ssrf.sparql` — `SERVICE <http://169.254.169.254/latest/meta-data/> { ... }` AWS metadata SSRF — proves SSRF defense (PITFALLS #4).
- `adversarial/supersession_as_of.sparql` — historical query with `--as-of 2022-01-01` against supersession chain (§21.9 canonical case).

### Gate 2 — P95 SPARQL < 500ms @ 1M

**Rule (D-05):** Tune first (3-day pass). ≤800ms post-tune → accept with SLO adjustment; >800ms → pivot to Fuseki.

**Tuning passes, ordered (do each, re-measure):**
1. **Bulk load via `Store.bulk_load()` not `Store.add()`.** bulk_load disables WAL + uses RocksDB bulk ingest; single `.add()` per triple is 100x slower at 1M. `Store.bulk_load(path="fixtures/bench.nq", format=RdfFormat.N_QUADS)`.
2. **Call `Store.optimize()` after bulk_load.** Triggers RocksDB compaction + index merge [VERIFIED: pyoxigraph docs via Context7].
3. **Prune dataset per query via `default_graph` / `named_graphs` params.** `store.query(q, named_graphs=[NamedNode(corpus_graph)])` avoids scanning TBox + governance graphs when only ABox is needed [VERIFIED: pyoxigraph Store.query API, Context7 2026-04-22].
4. **Warm cache pass before measurement.** Run each query twice; record second run's P95 (first fills RocksDB block cache). If Gate 4 targets cold-page, separate cold-cache measurement is in Gate 4 — not here.
5. **SPARQL query-plan rewrites.** Put most-selective triple pattern first; use FILTER after the pattern, not before; replace `OPTIONAL` with `NOT EXISTS` where semantically equivalent (NOT EXISTS is optimized; OPTIONAL is not).
6. **RocksDB tuning (LIMITED LEVERAGE).** pyoxigraph 0.5.x exposes minimal RocksDB config via Python API — `Store(path)` only. Larger tuning (block_cache_size, bloom_filter) requires forking or waiting on upstream. Document this limitation in DECISION.md.

**Measurement:** `pytest-benchmark` with `--benchmark-min-rounds=20 --benchmark-warmup=on`. Collect P50/P95/P99 per query; store JSON for trend.

**Honest uncertainty:** Public P95 numbers for pyoxigraph @ 1M triples are not published. Oxigraph's own BSBM test is 35M on 32GB RAM. 500ms P95 is **plausible but unverified**; Gate 2 is the verification. [CONFIDENCE: MEDIUM]

### Gate 3 — Worker image <500MB

**Rule (D-06):** Tune first. ≤700MB post-tune → accept; >700MB → split reasoner microservice in Phase 10.

**Baseline estimate (no tuning):**
- `python:3.11-slim` = ~125MB
- `eclipse-temurin:17-jre-alpine` = ~180MB (or ~60-80MB via jlink custom runtime)
- pyoxigraph wheel + RocksDB C++ lib = ~50MB
- owlready2 + HermiT.jar (8MB) + SQLite = ~30MB
- rdflib + pyshacl + deps = ~40MB
- Project code + fixtures = ~5MB

**Naive total:** ~430-500MB (tight). **Post-tuning target:** ~250-350MB.

**Tuning passes, ordered:**
1. **jlink custom JRE.** Drops JRE from 180MB to ~60-80MB (see Pattern 5 above). **Biggest single win.** [CITED: Abdelghani 2025; Adoptium docs]
2. **Distroless or Alpine.** `python:3.11-alpine` (~50MB base) vs `python:3.11-slim` (~125MB). Risk: Alpine musl vs glibc — pyoxigraph wheels must be musllinux-compatible (verify before switch). If Alpine wheels unavailable, fall back to `gcr.io/distroless/python3-debian12`.
3. **Multi-stage build.** Builder stage with `build-essential` + `pip install`; runtime stage with only runtime deps + artifacts. Baseline Dockerfile already does this partially.
4. **Purge build caches.** `pip install --no-cache-dir`; `rm -rf /root/.cache`; `apt-get clean && rm -rf /var/lib/apt/lists/*` (already in baseline).
5. **Exclude __pycache__ / .pyc.** `PYTHONDONTWRITEBYTECODE=1` (already in baseline).
6. **Strip JAR debug symbols.** HermiT.jar is 8MB already, but `jar uvf --strip-debug` is possible if needed.
7. **`--compress=2` in jlink.** Bundled in Pattern 5.

**Measurement:** `docker image inspect --format '{{.Size}}' ghcr.io/...:worker` after build.

### Gate 4 — SSR page <200ms

**Rule (D-07):** Tune streaming + warm cache. ≤400ms → accept with SLO adjustment; >400ms → deferred-hydration SPA fallback (NOT full adapter swap).

**What "cold shard page" means (scope-clarifying):** First request to `/shard/<hex16>` on a fresh Node process, against a fresh pyoxigraph query (no block cache warmup), wall-clock from request-first-byte to response-final-byte. This is the measurement Gate 4 targets.

**Tuning passes, ordered:**
1. **Critical-path minimization.** Only `shard_core` (15-field identity) is awaited in `load()`; dependencies + attestations stream after. See Pattern 3.
2. **`setHeaders({ 'cache-control': 'public, max-age=60, s-maxage=60' })`.** Lets Railway's edge or a reverse-proxy (Caddy, nginx) cache HTML; second-hit becomes <10ms.
3. **Precompile SvelteKit.** `vite build --mode production` with `kit.prerender.entries` for static-ish pages (not shard pages — those are dynamic).
4. **@polka/compression middleware.** Gzip streaming response; **never use standard `compression` package** (breaks streaming per SvelteKit docs).
5. **Node 22-slim base.** Avoid Node 25+ (too new for Railway); v22 is LTS with V8 optimizations over v20.
6. **Connection pool to pyoxigraph.** If FastAPI wraps pyoxigraph behind HTTP, pool connections; avoid per-request process spawn.
7. **Lazy-load heavy deps in `+page.server.ts`.** Avoid importing Cytoscape / YASGUI in server code (they're browser-only).

**Measurement:** `hyperfine 'curl -s http://localhost:8000/shard/<iri>' --warmup 3 --runs 50`. Record P50/P95.

**Honest uncertainty:** SvelteKit 5 cold-start on Railway Node 22 is not publicly benchmarked. 200ms is **aspirational**; 300-400ms is realistic for a warm-process cold-page render. [CONFIDENCE: MEDIUM-LOW]

### Gate 5 — Dagger CI reproducible

**Rule (D-08):** Bit-identical digest: `docker inspect --format '{{.Id}}' <local>` == `docker inspect --format '{{.Id}}' <railway-deployed>`.

**Required techniques (all must apply):**
1. **Pinned base images by digest.** `FROM python:3.11-slim@sha256:<digest>`, not `python:3.11-slim`. Regenerate digests quarterly via `crane digest python:3.11-slim` or `docker buildx imagetools inspect`.
2. **`SOURCE_DATE_EPOCH` build arg.** Set from `git log -1 --pretty=%ct`. Pass to BuildKit via `--opt build-arg:SOURCE_DATE_EPOCH=...`.
3. **BuildKit `rewrite-timestamp=true` output flag.** `--output type=image,name=...,rewrite-timestamp=true` normalizes all layer mtimes to SOURCE_DATE_EPOCH.
4. **Fixed UID/GID.** `useradd -u 1001 -g 1001 appuser` (Debian) or `adduser -u 1001 -D appuser` (Alpine).
5. **Hash-pinned pip.** `uv pip compile --generate-hashes pyproject.toml -o requirements.lock`; `pip install --require-hashes -r requirements.lock`.
6. **`apt-get install -y --no-install-recommends <pkg>=<version>` + `rm -rf /var/lib/apt/lists/*`** (already in baseline).
7. **`PYTHONDONTWRITEBYTECODE=1`** (already in baseline) — avoid `.pyc` mtime variance.
8. **Ordered COPY.** `COPY . /app` is non-deterministic on some filesystems. Prefer explicit `COPY pyproject.toml requirements.lock ./` then `COPY src/ ./src/` etc.
9. **Dagger: `WithTimestamps(SOURCE_DATE_EPOCH)` on final directory.** Dagger's container API supports timestamp normalization [CITED: dagger.io/blog/reproducible-builds "force all entries within a directory to have the same creation/modification timestamps"].
10. **Exclude `.git`, `output/`, `.planning/` from build context.** Local `.git` state leaks into layers via `COPY . .`.

**Caveat (from research):** Dagger "doesn't claim to solve reproducible builds" standalone; pairs with BuildKit's SOURCE_DATE_EPOCH. Dagger 0.x has SOURCE_DATE_EPOCH support on its roadmap but not natively emitted — must be piped as build arg [CITED: dagger.io/blog/reproducible-builds, verified 2026-04-22]. Confirm Dagger version at Phase 0 start.

**Measurement:** In Dagger pipeline, build twice, assert digests equal. Also: deploy one build to Railway, pull back the deployed image's digest, compare.

**Honest uncertainty:** Python wheel reproducibility has edge cases — some C-extension wheels (e.g., `sentence-transformers` via torch) embed build-path strings. pyoxigraph wheels are Rust-backed and should be reproducible if BuildKit is deterministic, **but this is unverified**. Gate 5 may expose a wheel-level issue that forces either (a) upstream patch to pyoxigraph, (b) source-build of wheels in CI, (c) accept non-reproducibility and document. [CONFIDENCE: MEDIUM]

## Fuseki Pivot Scaffold

**Trigger:** Gate 1 fails per D-04 (any PRD §20 query cannot be expressed in RDF 1.2 on pyoxigraph).

**What changes on Fuseki branch (per affected downstream phase):**

| Phase | Keep (pyoxigraph) | Pivot (Fuseki) | Diff delta |
|-------|-------------------|----------------|------------|
| 6 (DID) | in-process pyoxigraph writes | HTTP PATCH to Fuseki endpoint | +HTTP client; +auth-token for endpoint; same SHACL pipeline |
| 11 (SHACL) | pyoxigraph → Turtle → rdflib → pyshacl | Fuseki's native `fuseki:shacl` endpoint OR pyshacl over HTTP-fetched graph | **Fuseki wins**: native SHACL endpoint is faster; drops rdflib bridge entirely |
| 13 (Storage) | pyoxigraph RocksDB store | Fuseki TDB2 persistent store | Docker composition changes: Fuseki as separate service (port 3030); no in-process; worker only needs HTTP client |
| 16 (Public SPARQL) | custom FastAPI endpoint wrapping pyoxigraph | reverse-proxy to Fuseki `/sparql` with SERVICE-strip middleware injected | **Rewrite**: SERVICE-strip at HTTP layer (nginx lua or FastAPI middleware proxying to Fuseki); Fuseki has no native SERVICE-strip |

**Minimum-viable Fuseki config (copy-pasteable):**
```turtle
# config.ttl (Fuseki 5.x)
PREFIX fuseki:  <http://jena.apache.org/fuseki#>
PREFIX rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX tdb2:    <http://jena.apache.org/2016/tdb#>
PREFIX ja:      <http://jena.hpl.hp.com/2005/11/Assembler#>
PREFIX :        <#>

[] rdf:type fuseki:Server ;
   ja:context [ ja:cxtName "arq:queryTimeout" ; ja:cxtValue "30000" ] ; # 30s SPARQL-02 requirement
   .

<#service> rdf:type fuseki:Service ;
    fuseki:name "folio" ;
    # READ-ONLY public endpoint (SPARQL-01 — no fuseki:update)
    fuseki:endpoint [ fuseki:operation fuseki:query ; fuseki:name "sparql" ] ;
    # SHACL endpoint (SHACL-05)
    fuseki:endpoint [ fuseki:operation fuseki:shacl ; fuseki:name "shacl" ] ;
    fuseki:dataset <#dataset> .

<#dataset> rdf:type tdb2:DatasetTDB2 ;
    tdb2:location "/fuseki/databases/folio" ;
    # Named graphs per corpus (STORAGE-03)
    tdb2:unionDefaultGraph false . # keep corpora isolated
# Source: jena.apache.org/documentation/fuseki2/fuseki-configuration.html via WebFetch 2026-04-22
```
```bash
# Run Fuseki 5.1.0 with SHACL enabled
docker run --rm -p 3030:3030 \
  -v $(pwd)/config.ttl:/fuseki/config.ttl \
  -v fuseki-data:/fuseki/databases \
  -e ADMIN_PASSWORD=<from-secret> \
  apache/jena-fuseki:5.1.0 \
  --config=/fuseki/config.ttl
```

**Fuseki pivot does NOT affect:**
- Phases 2, 3, 4, 5 (shard envelope, subtypes, IRI, versioning) — Pydantic layer, unaffected
- Phases 7, 8 (governance, vocab) — TTL artifacts, unchanged
- Phase 9 (seven principles) — P1 cluster validator unchanged (still HermiT); others unchanged
- Phase 10 (pipeline + LLM) — Stage 8 Shard Minter re-targets writes to HTTP instead of in-process, minor
- Phase 12 (observability) — instrumentation points differ slightly (HTTP metrics vs in-process)

## Runtime State Inventory

> This is a greenfield-on-master phase, but **v1 state exists on disk** (v1 output/ directory, v1 corpora) and affects the 1M-triple generator.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | v1 `output/` has extracted shards in JSON format from Phase 01 (v1.0); `aiosqlite` review.db files | Re-extract under v2 pipeline via bench generator (D-13); do NOT migrate v1 JSON directly — schema mismatch |
| Live service config | Railway deploy at `folio-insights-production.up.railway.app` (v1.1) — no planned traffic disruption during Phase 0 | Dagger pipeline (D-10) redeploys on merge; coordinate with user before first redeploy |
| OS-registered state | None — no Task Scheduler, systemd, cron jobs | None — verified by inspection |
| Secrets/env vars | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` in Railway env; `REDIS_URL` (new, Phase 0 provisions) | Phase 0 adds `REDIS_URL` to Railway env; all other secrets carry over |
| Build artifacts | `output/` (3.8MB) currently bundled into Docker image; `tests/test_*.py` (203 v1 tests); `viewer/build/` from adapter-static | Phase 0 retains `output/` bundle; Gate 4 prototype adds `adapter-node` parallel build under `viewer/build-node/` until full swap in Phase 14 |

**Canonical question:** After Phase 0 lands, what runtime state breaks? Answer: none, if Dagger pipeline deploys successfully. Gate 5 (bit-identical) is specifically about preventing silent digest drift that could deploy a subtly-different build.

## Common Pitfalls

### Pitfall 1: RDF 1.2 annotation syntax silently returns zero rows

**What goes wrong:** Developer writes `<<?s ?p ?o>> ?ann ?val` SPARQL-star query on pyoxigraph 0.5.7; query parses successfully but matches zero triples because 0.5.x treats `<<>>` as object-position quoted-triple literal, not a pattern-matching construct.
**Why it happens:** Documentation lag — old tutorials, Wikidata Query Service examples, and the current STACK.md file all say "RDF-star supported natively." The 0.5.0-beta.1 CHANGELOG entry ("RDF-star support is now dropped in favor of RDF 1.2") is easy to miss.
**How to avoid:** Ban `<<` in SPARQL code reviews; add a lint rule. Every query goes through `tests/bench/test_rdf12_patterns.py` regression before merge.
**Warning signs:** Query runs, parser accepts, result set is empty (no error). UI shows "no data" instead of data.

### Pitfall 2: rdflib bridge drops triple-term annotations silently

**What goes wrong:** `store.dump(RdfFormat.TURTLE)` emits Turtle 1.2 with annotation syntax; `rdflib.Graph().parse(format="turtle")` **may or may not** understand RDF 1.2 annotations depending on rdflib 7.6 version. Silent drop = SHACL validates unrefined data.
**Why it happens:** rdflib 7.6.0 has stable Turtle-star parsing (0.4-era syntax) but RDF 1.2 triple-term parsing is not fully stabilized as of research date. Bridge round-trip loses annotations.
**How to avoid:** For RDF 1.2-annotated shards, **validate in pyoxigraph via SPARQL ASK shapes** (express SHACL constraint as ASK query) instead of pyshacl. For plain triples, the bridge is fine.
**Warning signs:** pyshacl report shows fewer triples validated than expected; SHACL report lists fewer focus nodes than corpus size.

### Pitfall 3: JVM cold-start torpedoes first cluster-validation call

**What goes wrong:** First `owlready2.sync_reasoner_hermit()` invocation takes 5-15 seconds (JVM startup + classpath load + HermiT initialization). If this runs synchronously in an HTTP request path, latency violates QUALITY-04.
**Why it happens:** owlready2 shells out to `java -jar HermiT.jar` on-demand; each subprocess is a fresh JVM unless kept alive.
**How to avoid:** (a) Run cluster validation **async** in worker tier only (PRINCIPLE-01 — already spec'd). (b) Consider a long-lived JVM subprocess with stdin/stdout protocol if async is insufficient. (c) Phase 0 benchmark measures cold-start cost so tuning decisions are data-driven.
**Warning signs:** Worker container logs show JVM startup 3+ times per task; P95 reasoning time dominated by startup not reasoning itself.

### Pitfall 4: Dagger's SOURCE_DATE_EPOCH is not automatic

**What goes wrong:** User assumes Dagger handles SOURCE_DATE_EPOCH natively (because it handles timestamps in general). Runs pipeline, gets different digests on second build.
**Why it happens:** Dagger's blog explicitly states SOURCE_DATE_EPOCH support is roadmap, not current [CITED: dagger.io/blog/reproducible-builds]. Must pipe as build arg to BuildKit.
**How to avoid:** Pass `SOURCE_DATE_EPOCH=<git-ct>` as `.with_env_variable` and `.with_build_arg` on every container; never rely on Dagger's `WithTimestamps()` alone.
**Warning signs:** Gate 5 digest comparison fails on second run; `docker inspect` shows different layer mtimes.

### Pitfall 5: `output/` bundle pollutes Docker build context → digest drift

**What goes wrong:** Current Dockerfile does `COPY output/ ./output/`. If `output/` has any write activity (new corpora, updated job files, SQLite WAL), digest changes.
**Why it happens:** Phase 0 needs a committed fixtures/ directory for the 1M-triple corpus (D-14). Gate 5 requires the build context to be deterministic.
**How to avoid:** Move benchmark fixtures to `fixtures/bench.nq` (committed, stable). Keep `output/` in `.dockerignore` for Phase 0 builds OR remove from Docker image entirely and load from volume at runtime.
**Warning signs:** Same commit, different digest; diff of layer manifests shows `output/*.sqlite-wal` changed.

### Pitfall 6: @sveltejs/adapter-node v5.x API surface drifted from v4

**What goes wrong:** Code written against adapter-node 4.x `handle()` hook fails on 5.x; or streaming idioms changed.
**Why it happens:** SvelteKit 2 migration: "top-level promises in load functions are no longer automatically awaited by SvelteKit to support data streaming" [CITED: /sveltejs/kit migration docs]. Must explicitly `await` critical-path promises now.
**How to avoid:** Verify every v1 load() function that migrates — audit for `const x = await …` vs `const x = …` patterns. Missing `await` on critical path → race condition.
**Warning signs:** Page renders with `undefined` for critical fields; hydration mismatch errors in console.

### Pitfall 7: Subtype-ratio assumption leaks into generator determinism

**What goes wrong:** D-03 says "match real-corpus ratios from v1 output." If the analysis script uses floating-point or non-seeded sampling, the "deterministic seed" guarantee of D-15 breaks when re-extracting.
**Why it happens:** Python's `random` module is deterministic with a seed, but `numpy.random` has its own seed; mixing breaks reproducibility. Multi-processed extraction introduces ordering variance.
**How to avoid:** Single `random.Random(seed)` instance passed explicitly to generator components; never use module-level `random.choice()`. Sort all collections before iterating.
**Warning signs:** `bench gen --seed 42` run twice produces different N-Quads files (diff shows ordering or sampling variance).

### Pitfall 8: pyoxigraph 0.5.x expects Python 3.11-3.12 (not 3.13)

**What goes wrong:** Host environment has Python 3.13.7. Wheel install works (pyoxigraph ships 3.13 wheels as of 0.5.7), but other stack dependencies — per STACK.md table — require `>=3.11,<3.13` due to `instructor` + pydantic compatibility.
**Why it happens:** STACK.md explicitly says "`3.13 has structural pattern-match regressions that affect instructor + pydantic internals`."
**How to avoid:** Pin `requires-python = ">=3.11,<3.13"` in pyproject.toml; use `uv python pin 3.11` for local dev; use `python:3.11-slim` for Docker (already baseline).
**Warning signs:** Tests pass locally on 3.13 but fail in Docker 3.11; or vice versa.

## Code Examples

Verified patterns from official sources.

### Example 1: Bulk-load 1M N-Quads + optimize + run Gate 1 query

```python
# src/folio_insights/bench/gate1_harness.py
from pyoxigraph import Store, RdfFormat, NamedNode
from pathlib import Path

def load_and_query(bench_path: Path, query_path: Path) -> list:
    # Create persistent Store (in-memory if path=None)
    store = Store(path="/tmp/gate-store")

    # Bulk-load 1M N-Quads — uses RocksDB bulk ingest path
    with open(bench_path, "rb") as f:
        store.bulk_load(f, format=RdfFormat.N_QUADS)

    # Compact indexes after bulk load (Gate 2 tuning step 2)
    store.optimize()

    # Prune to ABox named graph (Gate 2 tuning step 3)
    abox_graphs = [NamedNode(f"https://folio-insights.aleainstitute.ai/corpus/{c}")
                   for c in ["advocacy", "fre", "restatement"]]

    # RDF 1.2 annotation-pipe query (Gate 1 rewrite of PRD §20 example 1)
    query = query_path.read_text()
    solutions = list(store.query(query, named_graphs=abox_graphs))
    return solutions
# Source: pyoxigraph.Store.bulk_load + optimize + query docs via Context7 2026-04-22
```

### Example 2: RDF 1.2 annotation-pipe SPARQL (PRD §20.1 rewritten)

```sparql
# fixtures/gold_queries/q01_disputed_contracts.sparql
# Original PRD §20.1: "Find all disputed propositions in the contracts framework
#                      with unresolved objections" — does NOT use RDF-star in PRD
#                      form, so Gate 1 rewrite is a no-op. Regression test asserts.

PREFIX fi: <https://folio-insights.aleainstitute.ai/vocab/>

SELECT ?shard ?utrum WHERE {
  GRAPH ?g {
    ?shard a fi:DisputedPropositionShard ;
           fi:utrum ?utrum ;
           fi:framework <https://folio-insights.aleainstitute.ai/framework/us.federal.frcp> ;
           fi:epistemicStatus "aporetic" .
  }
}
# Source: PRD §20.1 (unchanged — no RDF-12 syntax required)
```

### Example 3: Gate 1 RDF-12 annotation pattern (NEW — confidence-annotated shard)

```sparql
# fixtures/gold_queries/q04_confidence_annotation.sparql
# NEW query not in PRD §20 — exercises the RDF 1.2 annotation pipe
# directly to validate Gate 1 requirement.

PREFIX fi: <https://folio-insights.aleainstitute.ai/vocab/>

SELECT ?shard ?confidence WHERE {
  GRAPH ?g {
    ?shard fi:subject ?concept {| fi:confidence ?confidence |} .
    FILTER(?confidence > 0.8)
  }
}
# Source: Oxigraph CHANGELOG 0.5.2 entry (annotation syntax eval fix) + W3C RDF 1.2
```

### Example 4: pytest-benchmark Gate 2 harness

```python
# tests/bench/test_p95_sparql.py
import json
import pytest
from pathlib import Path
from folio_insights.bench.gate1_harness import load_and_query

GATE2_BUDGET_MS = 500
QUERIES_DIR = Path("fixtures/gold_queries")

@pytest.fixture(scope="session")
def bench_1m_corpus():
    """D-14 pytest fixture — deterministic 1M-triple corpus from seeded generator."""
    # Pre-generated and committed to fixtures/bench.nq via `bench gen --seed 42`
    return Path("fixtures/bench.nq")

@pytest.mark.benchmark(group="gate2-sparql-p95")
@pytest.mark.parametrize("query_file", sorted(QUERIES_DIR.glob("q*.sparql")))
def test_gate2_p95_under_500ms(benchmark, bench_1m_corpus, query_file):
    # Benchmark runs 20 rounds with warmup; reports P95
    result = benchmark.pedantic(
        load_and_query,
        args=(bench_1m_corpus, query_file),
        rounds=20,
        warmup_rounds=3,
    )
    stats = benchmark.stats
    p95_ms = stats["95th percentile"] * 1000
    assert p95_ms < GATE2_BUDGET_MS, f"{query_file.name}: P95 {p95_ms:.1f}ms > {GATE2_BUDGET_MS}ms"
# Source: pytest-benchmark docs + Context7 pyoxigraph
```

### Example 5: Dockerfile.worker with jlink + pinned digests (Gate 3 + Gate 5)

```dockerfile
# docker/Dockerfile.worker
# syntax=docker/dockerfile:1.7

# ---- jlink JRE builder stage ----
FROM eclipse-temurin:17-jdk-alpine@sha256:<pin-before-use> AS jre-builder
RUN "$JAVA_HOME/bin/jlink" \
        --add-modules java.base,java.logging,java.xml,java.naming,java.sql,jdk.crypto.ec \
        --strip-debug \
        --no-man-pages \
        --no-header-files \
        --compress=2 \
        --output /opt/java-custom

# ---- Worker runtime stage ----
FROM python:3.11-alpine@sha256:<pin-before-use>

# Gate 5: reproducibility inputs
ARG SOURCE_DATE_EPOCH
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Copy custom JRE from builder
COPY --from=jre-builder /opt/java-custom /opt/java-custom
ENV JAVA_HOME=/opt/java-custom PATH="/opt/java-custom/bin:${PATH}"

# Gate 5: pinned UID/GID
RUN addgroup -g 1001 appuser && adduser -D -u 1001 -G appuser appuser

WORKDIR /app

# Hash-pinned install
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# Source (excluding .git, output, .planning via .dockerignore)
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser api/ ./api/

USER appuser
CMD ["python", "-m", "folio_insights.worker"]
# Source: Pattern 5 above + Pattern 4 Dagger build + BuildKit reproducibility docs
```

### Example 6: Dagger pipeline with SOURCE_DATE_EPOCH (Gate 5)

See Pattern 4 above. The critical line is:
```python
source_date_epoch = os.popen("git log -1 --pretty=%ct").read().strip()
.with_env_variable("SOURCE_DATE_EPOCH", source_date_epoch)
.with_build_arg("SOURCE_DATE_EPOCH", source_date_epoch)  # passed to Dockerfile ARG
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SPARQL-star `<<?s ?p ?o>>` quoted-triple patterns | SPARQL 1.2 annotation pipe `{| ?p ?o |}` | pyoxigraph 0.5.0-beta.1 (dropped rdf-star) → 0.5.2 (fixed annotation eval) | **BLOCKING**: every PRD §20 query needs rewrite; Gate 1 validates |
| RDF-star feature flag in pyoxigraph | RDF 1.2 via `rdf-12` flag (now default) | pyoxigraph 0.5.0 | Old `.nq` files auto-migrate on first open; Turtle serialization differs |
| Triple terms in subject position | Object position only | W3C RDF 1.2 spec change | Subject-position triple terms must be expressed via `rdf:Statement` reification |
| `docker buildx build` without reproducibility | `SOURCE_DATE_EPOCH` + `rewrite-timestamp=true` output flag | BuildKit 0.11 (2023) | Gate 5 hard requirement; not optional |
| SvelteKit load() auto-awaits promises | SvelteKit 2+ requires explicit `await` for critical path; unawaited promises stream | SvelteKit 2 migration | Pattern 3 streaming enables Gate 4 sub-200ms |
| rdflib as RDF-star store | oxrdflib bridge OR direct pyoxigraph | oxrdflib 0.5 — but **limited RDF 1.2 support** | Maintainer recommends direct pyoxigraph; rdflib bridge is one-way (pyoxigraph → Turtle → rdflib) for RDF 1.2 data |

**Deprecated/outdated:**
- **SPARQL-star syntax in Wikidata Query Service tutorials** — still showing `<<>>` patterns; do NOT copy these for pyoxigraph 0.5.x.
- **owlready2 < 0.48** — had older HermiT bundled; use 0.50 for JVM 17 compat.
- **`adapter-static`** — current v1 setup; swap to `adapter-node` in Gate 4 prototype.
- **GitHub Actions as CI** — replaced by Dagger in D-10.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker | All Gates (build, run) | ✓ | 29.4.0 | — |
| Dagger CLI | Gate 5 (D-10 pipeline) | ✗ | — | Install in Phase 0 P0-E; `curl -fsSL https://dl.dagger.io/dagger/install.sh | BIN_DIR=$HOME/.local/bin sh` |
| BuildKit | Gate 5 (reproducibility) | ✓ (bundled with Docker 29.4) | — | — |
| Java 17 (eclipse-temurin) | Gate 3 measurement (HermiT) | ✗ (local host has Java 21; target image needs 17) | 21.0.10 installed | Use `eclipse-temurin:17-jre-alpine@sha256:...` in Docker; local Java 21 is fine for non-build testing |
| Node.js 22 | Gate 4 (SvelteKit SSR) | ⚠ (host has Node 25.2.1; target is Node 22) | 25.2.1 | Use `node:22-slim@sha256:...` in Docker; nvm for local `nvm install 22 && nvm use 22` |
| Python 3.11 | Stack compat (STACK.md `<3.13`) | ⚠ (host has 3.13.7; project pinned to 3.11) | 3.13.7 | `uv python pin 3.11` for local venv; Docker uses `python:3.11-slim` |
| uv | Dep install + hash-pinned lock | ✓ | 0.9.22 | — |
| Redis 7.4 | Arq broker (Phase 10 cutover; Phase 0 sidecar test) | ✗ | — | Provision via Dagger as sidecar container; no local install needed |
| Railway CLI | D-10 Railway deploy trigger | Not verified | — | `npm i -g @railway/cli` or use API token via curl |
| pytest-benchmark | Gate 2 harness | ✗ (add to dev deps) | — | `uv pip install pytest-benchmark` |
| hyperfine | Gate 4 cold-page timing | ✗ | — | `apt install hyperfine` or `cargo install hyperfine` |

**Missing dependencies with no fallback:**
- **Dagger CLI** — must install in Phase 0 as explicit task (document install command + pin version).

**Missing dependencies with fallback:**
- **Redis** — provision via Dagger/Docker; no host install needed.
- **Java 17 / Node 22 / Python 3.11** — use Docker images; host versions only affect IDE/tests, not build.
- **hyperfine, pytest-benchmark** — add via package managers in Phase 0 setup.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.x (upgrade from v1's `>=8.0`); pytest-asyncio 0.25+; pytest-benchmark 5.1+ (new) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — already present |
| Quick run command | `pytest tests/bench/ -x --tb=short` |
| Full suite command | `pytest --benchmark-only --benchmark-json=bench-results.json` |
| Gate measurement | `pytest tests/bench/test_gate*.py --benchmark-autosave` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEC-01 / STORAGE-04 | RDF-12 rewrites execute on pyoxigraph | unit (integration with Store) | `pytest tests/bench/test_rdf12_patterns.py -x` | ❌ Wave 0 (P0-B + P0-C) |
| SEC-02 Gate 1 | PRD §20 rewrites 100% pass OR pivot | integration | `pytest tests/bench/test_gate1_rdf12.py -v` | ❌ Wave 0 (P0-C) |
| SEC-02 Gate 1 adversarial | SERVICE stripped, deep GRAPH, large CONSTRUCT behave correctly | integration | `pytest tests/bench/test_adversarial.py -v` | ❌ Wave 0 (P0-C) |
| QUALITY-01 Gate 2 | P95 < 500ms @ 1M (post-tune ≤800ms per D-05) | benchmark | `pytest tests/bench/test_p95_sparql.py --benchmark-only` | ❌ Wave 0 (P0-F) |
| QUALITY-03 Gate 3 | Worker image < 500MB (post-tune ≤700MB per D-06) | smoke (docker inspect) | `bash docker/check-image-size.sh worker 500` | ❌ Wave 0 (P0-F) |
| QUALITY-04 Gate 4 | SSR cold <200ms (post-tune ≤400ms per D-07) | benchmark (hyperfine) | `bash tests/bench/gate4_ssr_latency.sh` | ❌ Wave 0 (P0-F) |
| OBS-04 Gate 5 | Bit-identical digest local vs Railway | smoke | `bash docker/check-digest-match.sh` | ❌ Wave 0 (P0-E) |
| D-18 | PHILOSOPHY.md exists at repo root | smoke | `test -f PHILOSOPHY.md` | ❌ Wave 0 (P0-A) |
| D-14 | `folio-insights bench gen --target 1000000 --seed 42` produces deterministic output | integration | `pytest tests/bench/test_generator_determinism.py -v` | ❌ Wave 0 (P0-B) |

### Sampling Rate
- **Per task commit:** `pytest tests/bench/test_<relevant>.py -x` (< 30s)
- **Per wave merge:** `pytest tests/bench/ --benchmark-only --benchmark-max-time=2` (< 5 min)
- **Phase gate:** full gate suite + Docker build digest comparison + DECISION.md artifact generation

### Wave 0 Gaps (infrastructure to build before measurements)
- [ ] `src/folio_insights/bench/generator.py` — 1M-triple scaled-real generator (P0-B)
- [ ] `src/folio_insights/bench/cli.py` — `folio-insights bench` CLI command (P0-B)
- [ ] `tests/bench/conftest.py` — `bench_1m_corpus` fixture (P0-B)
- [ ] `tests/bench/test_rdf12_patterns.py` — Gate 1 regression (P0-C)
- [ ] `tests/bench/test_adversarial.py` — Gate 1 adversarial (P0-C)
- [ ] `tests/bench/test_p95_sparql.py` — Gate 2 perf assertions (P0-F)
- [ ] `tests/bench/test_generator_determinism.py` — seeded-output verification (P0-B)
- [ ] `tests/bench/gate4_ssr_latency.sh` — hyperfine harness (P0-F)
- [ ] `docker/check-image-size.sh`, `docker/check-digest-match.sh` — Gate 3/5 shell assertions (P0-E)
- [ ] `fixtures/bench.nq` — committed deterministic 1M corpus (P0-B artifact)
- [ ] `fixtures/gold_queries/` — 13 rewritten SPARQL + 5 adversarial (P0-C)
- [ ] `requirements.lock` via `uv pip compile --generate-hashes` (P0-E Gate 5 dep)
- [ ] Add `pytest-benchmark>=5.1` + `pytest-timeout` upgrade to `[project.optional-dependencies]` dev (P0-B)

## Security Domain

### Applicable ASVS Categories (Phase 0 subset — full audit in Phase 19)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Deferred — auth is Phase 6 |
| V3 Session Management | no | Deferred — Phase 6 |
| V4 Access Control | no | Deferred — Phase 7 |
| V5 Input Validation | yes | Gate 1 adversarial suite validates SPARQL injection-adjacent patterns (deep GRAPH, large CONSTRUCT); full `initBindings` pattern in Phase 16 |
| V6 Cryptography | partial | Gate 5 demands deterministic builds but no crypto primitives in Phase 0 — DID signing is Phase 6 |
| V10 Malicious Code | yes | Gate 1 SERVICE-blocked adversarial tests SSRF vector (PITFALLS #4) |
| V14 Configuration | yes | Gate 5 reproducible builds prevent supply-chain drift; pinned digests fight image-poisoning |

### Known Threat Patterns for {pyoxigraph + Fuseki + Dagger stack}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SPARQL SERVICE SSRF (remote endpoint, AWS metadata) | Information Disclosure / Tampering | Strip SERVICE from AST before execution (Phase 16 impl); Phase 0 only tests that adversarial query is blocked OR errors out cleanly (not required to have full middleware yet) |
| Large CONSTRUCT memory DoS | Denial of Service | 30s timeout (SPARQL-02 — Phase 16 impl); 10K row cap; Phase 0 adversarial test verifies the query doesn't hard-crash pyoxigraph |
| Deep GRAPH traversal DoS | Denial of Service | Same — timeout + depth limit (Phase 16); Phase 0 measures baseline behavior |
| Image supply-chain attack (poisoned base image) | Tampering | Pinned digests by sha256 (Gate 5); reject tag-based FROM |
| Build-time secret leak (API keys in layers) | Information Disclosure | `.dockerignore` excludes `.env`; `--secret` mount for build-time secrets; Gate 5 verifies no secrets in layer inspect |
| RDF parser fuzz (malformed N-Quads crashes bulk_load) | Denial of Service / Tampering | pyoxigraph's Rust parser is memory-safe; Phase 0 load generator produces valid-by-construction N-Quads |

**Phase 0 security scope is narrow.** Full ASVS-aligned audit is Phase 19 per REQUIREMENTS.md SEC-03. Phase 0 only verifies: (1) adversarial queries don't crash the store, (2) SSRF vector behavior is measurable (even if middleware is Phase 16), (3) build pipeline doesn't leak secrets.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | pyoxigraph 0.5.7 wheel is musllinux-compatible for Alpine | Gate 3 tuning step 2 | Fall back to debian-slim; adds ~75MB; image creeps toward 500MB limit |
| A2 | 1M triples will fit in RocksDB with default settings on a Railway container (2-4GB RAM) | Gate 2 | May hit OOM; tuning requires either beefier Railway plan or pagination |
| A3 | SvelteKit 5 cold-page SSR hits 200-300ms on Node 22 Railway (not measured in public benchmarks) | Gate 4 | Likely triggers D-07 SLO relaxation (≤400ms accept) |
| A4 | jlink custom JRE + HermiT.jar runs correctly with only the listed `--add-modules` (java.base, logging, xml, naming, sql, jdk.crypto.ec) | Gate 3 jlink pattern | May hit ClassNotFoundException at reasoning time; add modules iteratively |
| A5 | Dagger 0.x SOURCE_DATE_EPOCH support will work via build arg pipe-through (inferred from blog; not directly tested) | Gate 5 | If Dagger strips/overrides the build arg, Gate 5 fails; workaround is direct `buildctl` or buildx |
| A6 | rdflib 7.6.0's Turtle parser loses RDF 1.2 annotations silently, not crashes | Pitfall 2 | If it crashes, bridge is safer (error signals problem); if it silently drops, SHACL validation is incomplete |
| A7 | pyoxigraph's internal SPARQL optimizer does not expose query-plan hints (SPARQL 1.1 lacks them natively) | Gate 2 tuning step 5 | Tuning lever reduced; rely on triple-pattern reordering + FILTER placement |
| A8 | Phase 0 does not need a real pipeline.py refactor — the load generator's re-extraction uses v1 pipeline as-is | D-01 / D-13 | If v1 pipeline outputs can't produce RDF 1.2-annotated shards, D-11 HermiT benchmark is unrealistic |
| A9 | `oxrdflib` at current version does NOT transparently support RDF 1.2 via bridge | §Standard Stack Supporting | If it does, Pattern 2's serialize-round-trip is unnecessary overhead |
| A10 | Fuseki 5.x config (§Fuseki Pivot Scaffold) works as written with named graphs + SHACL + timeout | §Fuseki Pivot Scaffold | If pivot triggers, Phase 0 may need a second mini-spike to validate Fuseki config |
| A11 | HermiT JVM cold-start cost is 5-15s for 1M ABox (research mentions 12GB heap tests with cyclic axioms — realistic number unknown for our corpus) | Pitfall 3, Gate 3 baseline | Real cost could be higher; forces async-only reasoning (PRINCIPLE-01 already specs this) |

**If any of A1-A11 are user concerns, discuss before planning.** All have [ASSUMED] or [INFERRED] provenance and represent decisions the planner should call out in sub-tasks.

## Open Questions

1. **Does pyoxigraph 0.5.7 CONSTRUCT queries emit RDF 1.2 annotation syntax in Turtle output?**
   - What we know: `Store.dump(RdfFormat.TURTLE)` serializes triples; Triple model has Quoted-Triple in subject/object per API. [VERIFIED via Context7]
   - What's unclear: Does a CONSTRUCT `{| ?p ?o |}` pattern emit annotation-pipe Turtle or plain triples with `rdf:reifies`? Pipe syntax in Turtle 1.2 is still stabilizing.
   - Recommendation: Gate 1 test suite must assert CONSTRUCT output is parseable by both pyoxigraph (round-trip) and rdflib 7.6 (bridge); if rdflib drops annotations, document as known bridge-limitation.

2. **What is the exact musllinux wheel status for pyoxigraph 0.5.7?**
   - What we know: pyoxigraph is Rust-backed; PyO3 supports musllinux but each wheel must be built explicitly.
   - What's unclear: Does PyPI ship musllinux wheels for pyoxigraph 0.5.7 or only manylinux?
   - Recommendation: `pip download pyoxigraph==0.5.7 --platform musllinux_1_2_x86_64` dry-run in Phase 0; if no wheel, fall back to debian-slim for worker (A1).

3. **How much RAM does HermiT need for 1M ABox + v2 FOLIO TBox?**
   - What we know: Academic tests used 12GB heap for large cyclic ontologies.
   - What's unclear: Our TBox is small (mini-BFO + fi:*); ABox is 1M but mostly simple triples. Could be 2-4GB.
   - Recommendation: D-11 MAX-FIDELITY HermiT benchmark measures this directly; adjust `-Xmx` from measurement, not prediction.

4. **Will Dagger's in-process container digest match BuildKit's `docker buildx` digest, given identical inputs?**
   - What we know: Dagger runs BuildKit under the hood; both should be deterministic with SOURCE_DATE_EPOCH.
   - What's unclear: Minor BuildKit version drift between Dagger-bundled version and Docker-bundled version; any snapshotter differences.
   - Recommendation: Gate 5 explicitly tests local Dagger vs local `docker buildx` vs Railway-deployed, pairwise. Record any delta in DECISION.md.

5. **Is there a SPARQL query-plan hint syntax pyoxigraph supports?**
   - What we know: SPARQL 1.1 spec has no native hints; some engines (GraphDB) add vendor extensions.
   - What's unclear: Does pyoxigraph 0.5.x have any SERVICE-style hint or PRAGMA? [ASSUMED: NO per A7]
   - Recommendation: Grep pyoxigraph source or ask upstream; if hints exist, they're Gate 2 tuning lever 5 enhancement.

## Sources

### Primary (HIGH confidence)
- [pyoxigraph 0.5.7 docs (Context7)](https://pyoxigraph.readthedocs.io/en/stable/) — Store API, bulk_load, optimize, query, named_graphs, RDF 1.2 support status [verified 2026-04-22]
- [Oxigraph CHANGELOG](https://github.com/oxigraph/oxigraph/blob/main/CHANGELOG.md) — 0.5.0-beta.1 entry (rdf-star → rdf-12), 0.5.2 entry (annotation pipe eval fix), 0.5.7 release date [verified 2026-04-22]
- [SvelteKit 5 docs (Context7 /sveltejs/kit)](https://svelte.dev/docs/kit) — load() streaming, setHeaders, SvelteKit 2 migration (explicit await) [verified 2026-04-22]
- [SvelteKit adapter-node docs](https://svelte.dev/docs/kit/adapter-node) — @polka/compression recommendation, streaming caveat [verified 2026-04-22]
- [owlready2 0.50 reasoning docs](https://owlready2.readthedocs.io/en/latest/reasoning.html) — HermiT subprocess with -Xmx flag [cited via WebSearch 2026-04-22]
- [Dagger reproducible builds blog](https://dagger.io/blog/reproducible-builds) — SOURCE_DATE_EPOCH roadmap status, WithTimestamps() timestamp normalization [verified 2026-04-22]
- [reproducible-builds.org SOURCE_DATE_EPOCH](https://reproducible-builds.org/docs/source-date-epoch/) — canonical epoch standard [verified 2026-04-22]
- [BuildKit v0.11 release](https://www.docker.com/blog/highlights-buildkit-v0-11-release/) — rewrite-timestamp output flag [verified 2026-04-22]
- [Apache Jena Fuseki config docs](https://jena.apache.org/documentation/fuseki2/fuseki-configuration.html) — TDB2 + SHACL + query-timeout configuration [verified 2026-04-22]
- [oxigraph/oxigraph Discussion #886](https://github.com/oxigraph/oxigraph/discussions/886) — Maintainer recommendation: use pyoxigraph directly for RDF-star/RDF-1.2, not rdflib bridge [verified 2026-04-22]
- Project internal: `.planning/REQUIREMENTS.md` (v2.0 requirements), `.planning/research/STACK.md` (RISK-1, -3), `.planning/research/PITFALLS.md` (D1 RDF-12 BLOCKING)

### Secondary (MEDIUM confidence)
- [NTT Labs bit-for-bit Dockerfile reproducibility](https://medium.com/nttlabs/bit-for-bit-reproducible-builds-with-dockerfile-7cc2b9faed9f) — buildctl flags; repro-get for apt [cited 2026-04-22]
- [Adoptium Temurin Docker docs](https://hub.docker.com/_/eclipse-temurin) — jlink module stripping [cited 2026-04-22]
- [Abdelghani 2025: Optimizing Java base Docker images 674MB → 58MB](https://medium.com/@RoussiAbdelghani/optimizing-java-base-docker-images-size-from-674mb-to-58mb-c1b7c911f622) — jlink size floor [cited 2026-04-22]
- [W3C RdfStoreBenchmarking wiki](https://www.w3.org/wiki/RdfStoreBenchmarking) — BSBM / SP2Bench tooling [cited 2026-04-22]
- [Docker reproducible builds guide](https://docs.docker.com/build/ci/github-actions/reproducible-builds/) — SOURCE_DATE_EPOCH pattern [cited 2026-04-22]

### Tertiary (LOW confidence — needs validation in Phase 0)
- Public P95 SPARQL latency for pyoxigraph @ 1M triples (no published numbers; Gate 2 measures) [CONFIDENCE: LOW]
- SvelteKit 5 Node 22 Railway cold-start wall-clock (no published numbers; Gate 4 measures) [CONFIDENCE: LOW]
- pyoxigraph 0.5.7 musllinux wheel availability (inferred; verify at P0-D) [CONFIDENCE: LOW]
- Dagger's SOURCE_DATE_EPOCH build-arg pipe-through on current Dagger version (inferred from blog; verify at P0-E) [CONFIDENCE: LOW]

## Metadata

**Confidence breakdown:**
- RDF 1.2 syntax shift + pyoxigraph 0.5.x breaking changes: **HIGH** — verified via CHANGELOG + Context7 + maintainer discussion
- Gate 1 rewrite feasibility for PRD §20 queries: **MEDIUM** — PRD §20 queries don't currently use RDF-star syntax; all 3 extant examples rewrite as no-ops; adversarial set is new construction
- Gate 2 P95 @ 1M: **MEDIUM** — tuning levers well-documented; absolute latency not publicly benchmarked at our scale
- Gate 3 image size: **MEDIUM-HIGH** — jlink + alpine path is well-trod for Java workloads; pyoxigraph musllinux wheel availability is the swing factor
- Gate 4 SSR: **MEDIUM** — SvelteKit streaming pattern verified; Node 22 Railway cold-start is projection
- Gate 5 reproducibility: **HIGH** — SOURCE_DATE_EPOCH + BuildKit rewrite-timestamp are battle-tested; Dagger integration has one known caveat (must pipe as build arg)
- Fuseki pivot scaffold: **MEDIUM-HIGH** — Fuseki 5.x config is documented; downstream-phase branch guidance is inference from the stack delta

**Research date:** 2026-04-22
**Valid until:** ~2026-05-22 (30 days for stable Oxigraph/SvelteKit; Dagger roadmap moves fast — re-check Dagger SOURCE_DATE_EPOCH status if pyoxigraph or Dagger ships a major release before then)
