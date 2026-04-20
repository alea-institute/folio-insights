# Stack Research — v2.0 shards-as-axioms

**Domain:** Federated shard-based knowledge graph (Python backend + SvelteKit SSR frontend) with SPARQL endpoint, SHACL validation, DID-signed attestations, LLM-provider-agnostic extraction pipeline
**Researched:** 2026-04-20
**Confidence:** HIGH for version-pinning of locked libs (verified against PyPI on research date); MEDIUM for auxiliary integration libs (verified against official docs + PyPI); single RISK flag surfaced below for owlready2

## Summary

The v2.0-MILESTONE-BRIEF locked 12 infrastructure choices across triplestore, reasoner, LLM abstraction, DID methods, job queue, CI/CD, UI framework, auth, docs, and playground. All 12 are **still current-stable on 2026-04-20** and all are active-release projects (most with a release within the last 90 days). **One correction is required:** the brief describes `owlready2` as a "pure-Python HermiT" reasoner — it is not; HermiT ships as a bundled Java `.jar` and requires a JVM at runtime. Our Docker image already has a Python-3.11-slim base; the JVM must be added (~ +200MB). This is flagged below as **RISK-1**; mitigation options (JVM bundle vs. Rust-based `reasonable` reasoner) are documented.

The auxiliary surface area needed to integrate DID + OAuth + SPARQL + SHACL + Arq + instructor end-to-end is wider than the brief suggests. Significant auxiliary additions:

1. **DID signing cryptography** — `cryptography` and `pynacl` for ed25519 keys; `joserfc` for JWS wrapping; `dag-cbor` for `did:plc` operation signing; `atproto` as the did:plc resolver client. `didkit` (Spruce Systems) is stale (2024-08) and declining; we should not adopt it.
2. **OAuth on FastAPI** — `authlib` is the right choice over `fastapi-users` for the v2.0 use case (OAuth + DID binding over a DID-first identity model; `fastapi-users` is optimized for password-based user management we don't want).
3. **Observability triple** — `structlog` + OpenTelemetry Python SDK (`opentelemetry-api/sdk/instrumentation-fastapi/instrumentation-redis/exporter-otlp`) + `prometheus-fastapi-instrumentator`. All three are OTel-1.41 compatible as of April 2026.
4. **SHACL generator** — **no off-the-shelf Pydantic-to-SHACL library exists** (verified via web search + PyPI survey). The "Pydantic-generated base" leg of the hybrid-SHACL strategy (§10) requires writing a generator in-repo. Recommend a small utility module `shapes/pydantic_to_shacl.py` that walks a Pydantic model's JSON Schema and emits `sh:NodeShape` + `sh:property` turtle; budget ~1-2 days in Phase 11.
5. **No JSON-LD signing library we can adopt** — RDF dataset canonicalization for DID-signed provenance uses JCS (JSON Canonicalization Scheme, RFC 8785) via `jcs`; for RDF-star/Turtle canonicalization there is no mature Python lib — we canonicalize via `rdflib`'s `to_canonical_graph()` and hash the N-Triples output.

## Recommended Stack

### Core Technologies (LOCKED — verified current-stable)

| Technology | Version (pin) | Purpose | Why Recommended |
|------------|---------------|---------|-----------------|
| **Python** | `>=3.11,<3.13` | Runtime | Matches v1 baseline; 3.13 has structural pattern-match regressions that affect `instructor` + pydantic internals. |
| **pyoxigraph** | `0.5.7` | Canonical triplestore + SPARQL 1.1 + SPARQL-star query engine | Released 2026-04-19 (today-1). Rust-backed, embeds a RocksDB backend, supports RDF 1.2 / RDF-star / SPARQL-star / Turtle-star natively. No JVM required. This is the single canonical store; all other RDF tooling (rdflib, pyshacl) bridges to it. |
| **rdflib** | `7.6.0` | Bridge graph — JSON-LD serialization, pySHACL input, Turtle-star I/O | Released 2026-02-13. rdflib 7.x has stable RDF-star parsing in Turtle, N-Triples-star, and TriG-star. We use rdflib only as an adapter *into* pyoxigraph, not as the primary store (decision #11.1). |
| **pyshacl** | `0.31.0` | SHACL validator (§10) | Released 2026-01-16. Validates `rdflib.Graph` instances; we feed it the bridge graph. Supports SHACL Core + SHACL-SPARQL advanced constraints. |
| **owlready2** | `0.50` | OWL 2 reasoner (HermiT / Pellet) for TBox classification (§P1 cluster validator) | Released 2026-02-05. **See RISK-1.** Wraps HermiT-Java; we need a JVM in the Docker image. Used inside the `--cluster-validate` flag only; pyoxigraph handles all SPARQL reasoning on the ABox. |
| **instructor** | `1.15.1` | LLM abstraction across providers (Claude/OpenAI/Gemini/Ollama/17+ others) | Released 2026-04-03. Pydantic-first structured outputs; `from_anthropic()`, `from_openai()`, `from_google()`, `from_ollama()` factories verified. `instructor.from_provider("anthropic/claude-sonnet-4-5")` unified string API works in 1.15. |
| **Arq** | `0.28.0` | Async job queue over Redis | Released 2026-04-16. Native asyncio; compatible with Redis 7.4; supports async worker context via `WorkerSettings`; DLQ via retry limit + error callback. |
| **Redis** (python client) | `redis==7.4.0` | Arq backend + rate-limiter + idempotency keys | Released 2026-03-24. Async client; requires Redis server 7.x. |
| **FastAPI** | `0.136.0` | Web API framework | Released 2026-04-16. Async-native; auto-generated OpenAPI; dependency injection powers DID auth middleware. |
| **Pydantic** | `2.13.3` | Shard envelope models + SHACL generator input + instructor contracts | Released 2026-04-20 (today). v2.13 has fix for discriminated-union inference on `subtype` field (§6.2 shard subtypes). |
| **pydantic-settings** | `2.14.0` | Env-var config (OAuth secrets, REDIS_URL, SIGNING_KEY_PATH) | Released 2026-04-20. |
| **aiosqlite** | `0.22.1` | SQLite shard store (retains v1 compatibility; § 11 "shard_store.py") | Released 2025-12-23. |
| **SvelteKit** | `@sveltejs/kit@2.57.1` + `svelte@5.55.4` + `@sveltejs/adapter-node@5.5.4` | SSR UI | adapter-node replaces v1's adapter-static (LOCKED per brief). Unlocks deep-link shard URLs + SPARQL streaming endpoints. |
| **Vite** | `8.0.9` | Frontend build | SvelteKit 2.57 requires Vite 6+; we pin 8.x. |

### Auxiliary Libraries (PROPOSED — needed to integrate locked choices)

#### DID signing + attestation (§6.5)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **cryptography** | `46.0.7` | ed25519 key generation + loading (PEM/DER); x25519; libsodium-free path | Generating `did:key` keypairs (`folio-insights did generate`); verifying arbitrary signatures during `folio-insights verify`. |
| **PyNaCl** | `1.6.2` | libsodium binding for fast ed25519 sign/verify | Signing `AttestedSignature.signature` field. Faster than `cryptography` for repeated signing (benchmark: ~6x). Used in hot path during bulk attestation. |
| **joserfc** | `1.6.4` | JWS / JWK / JWT / COSE-aligned signing | Wrapping DID signatures as detached JWS when interoperability with external verifiers is needed (e.g., exporting attestations as Verifiable Credentials). Prefer over `python-jose` (unmaintained for 18+ months) and `PyJWT` (no JWS support). |
| **atproto** | `0.0.65` | did:plc resolver client + DAG-CBOR operation builder + PLC directory I/O | `did:plc` method implementation. `atproto.IdResolver().did.resolve(did)` resolves a PLC DID to its signing key. We do **not** use `atproto` for Bluesky posting — only identity. |
| **dag-cbor** | `0.3.3` | Deterministic CBOR encoding for did:plc operation signing | did:plc operations are signed over DAG-CBOR bytes (per did:plc spec v0.1). |
| **jcs** | `0.2.1` | RFC 8785 JSON Canonicalization Scheme | Canonicalizing `Shard.content` JSON before hashing (provenance_hash §6.3) and before signing (AttestedSignature.over_content_hash). |

**Deliberately rejected for DID:**
- ❌ `didkit` — last release 2024-08; Spruce Systems pivoted away; not Python-3.12-compatible.
- ❌ `pydid` (0.5.3) — document-shape library; we don't need the abstraction layer, and it imports deprecated `pycryptodome` APIs.
- ❌ `py-ed25519-bindings` — stale (2022). Use `py-ed25519-zebra-bindings` (1.3.0, Sept 2025) if we need a pure-Rust ed25519 backend that avoids libsodium; otherwise `PyNaCl` is simpler.

#### OAuth + session auth (§3.1 identity binding)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **Authlib** | `1.7.0` | OAuth 2.0 + OIDC client for GitHub / Google / institutional IdPs | `Authlib.integrations.starlette_client.OAuth` plugs into FastAPI's Starlette foundation directly. Supports PKCE, state, nonce validation. |
| **itsdangerous** | `2.2.0` | Signed session cookies (Starlette `SessionMiddleware` backend) | Post-OAuth session state; binds OAuth identity to a session ID that the DID binding endpoint consumes. |
| **python-multipart** | `0.0.26` | Form parsing for OAuth callback | FastAPI requires this for form-encoded callbacks; pinned to 0.0.26 for CVE-2024-53981 fix. |
| **email-validator** | `2.3.0` | OAuth email claim validation | Required by Pydantic `EmailStr` on IdentityBinding model. |

**Deliberately rejected for auth:**
- ❌ `fastapi-users` (15.0.5) — feature-rich but opinionated toward password-based user tables and SQLAlchemy. Our identity model is **DID-first, OAuth-secondary** (OAuth is binding metadata, not the primary key). `fastapi-users` would force either a fake password column or a complex custom `AuthBackend` that defeats the point of adopting it.
- ❌ `python-jose` — unmaintained since mid-2025, has uncapped `ecdsa` dependency warning.

#### Observability (§Phase 12 cross-cutting)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **structlog** | `25.5.0` | Structured JSON logging with contextvars | Single logger across FastAPI request handlers, Arq workers, and CLI. Binds `corpus_id`, `shard_iri`, `extractor_did` into every log entry via context processors. |
| **python-json-logger** | `4.1.0` | JSON formatter for stdlib `logging` — routes `uvicorn.access` and `arq` internal logs into structlog-compatible JSON | Keeps non-structlog library output in the same JSON stream so Railway / any log aggregator sees one schema. |
| **opentelemetry-api** | `1.41.0` | OTel trace + metrics API | Cross-cutting instrumentation. |
| **opentelemetry-sdk** | `1.41.0` | OTel implementation | Paired exactly with `-api`; never mix minor versions. |
| **opentelemetry-instrumentation-fastapi** | `0.62b0` | Auto-instrument FastAPI request spans | Note `0.62b0` is a *beta* version — the OTel Python "instrumentation" family uses a `N.NNbX` scheme that maps to SDK `1.41`. This is **not** a pre-release gate; it's stable for production. |
| **opentelemetry-instrumentation-redis** | `0.62b0` | Auto-instrument Arq's Redis calls | Traces show task enqueue/dequeue as child spans of the originating HTTP request. |
| **opentelemetry-instrumentation-httpx** | `0.62b0` | Auto-instrument outbound LLM API calls (Anthropic/OpenAI SDKs all use httpx) | Per-provider p50/p95 latency tagged with `llm.provider` + `llm.model`. |
| **opentelemetry-exporter-otlp** | `1.41.0` | OTLP/gRPC export to any collector (Grafana Tempo, Honeycomb, SigNoz, Jaeger) | Single exporter; protocol-agnostic. |
| **prometheus-client** | `0.25.0` | Prometheus metrics primitives | Shard-count, extraction-duration histogram, SHACL-violation counters. |
| **prometheus-fastapi-instrumentator** | `7.1.0` | Auto `/metrics` endpoint on FastAPI | One line of setup; respects `prometheus-client` default registry. |

#### LLM provider SDKs (dependencies of `instructor`)

| Library | Version | Purpose |
|---------|---------|---------|
| **anthropic** | `0.96.0` | Claude API (default provider) |
| **openai** | `2.32.0` | OpenAI + Azure OpenAI |
| **ollama** | `0.6.1` | Local model runner (Llama/Mistral/Qwen for air-gapped extraction) |

#### HTTP + utility

| Library | Version | Purpose |
|---------|---------|---------|
| **httpx** | `0.28.1` | Async HTTP client (used by atproto, authlib, LLM SDKs) |
| **httpx-sse** | `0.4.3` | Server-Sent Events for streaming SPARQL results from endpoint to UI |
| **tenacity** | `9.1.4` | Retry/backoff decorators for LLM calls + PLC directory lookups (exponential backoff per §9.pipeline-retry decision) |
| **orjson** | `3.11.8` | 3-5x faster JSON (parse/dump) vs. stdlib — Shard serialization is a hot path |
| **aiofiles** | `25.1.0` | Async file I/O for corpus snapshots (`.v1.0-snapshot/` during migration) |

### Development Tools

| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| **pytest** | `9.0.3` | Test runner | Matches existing v1 tests. |
| **pytest-asyncio** | `1.3.0` | Async test support | Set `asyncio_mode = "auto"` in `pyproject.toml`. |
| **ruff** | `0.15.11` | Linter + formatter | Replaces black + flake8 + isort. Configure `select = ["E", "F", "I", "B", "UP", "RUF", "S"]`; `S` enables bandit-like security rules critical for DID/OAuth code. |
| **mypy** | `1.20.1` | Type check | Configure `strict = true` on all new `folio_insights.shards.*`, `folio_insights.did.*`, `folio_insights.auth.*` modules. |
| **pre-commit** | `4.5.1` | Git hooks | Runs ruff + mypy + `pyshacl` on fixture shapes. |
| **@playwright/test** | `1.59.1` | E2E tests for §12 review UI | Required for the WCAG 2.1 AA blocking gate (Chromium + Firefox + WebKit). |
| **@axe-core/playwright** | `4.11.2` | Accessibility rules injected into Playwright tests | The WCAG blocking gate (§quality bar) runs `AxeBuilder(page).analyze()` on every new UI component in CI. |
| **axe-core** | `4.11.3` | Transitive; pinned to avoid accidental minor bumps between test + doc |

### Docs + playground (LOCKED)

| Tool | Version | Purpose |
|------|---------|---------|
| **mkdocs-material** | `9.7.6` | Primary docs site | Builds on GitHub Pages + Dagger CI; mermaid graphs for BFO spine + shard subtype hierarchy. |
| **jupyterlite** | `0.7.4` | Browser-embedded notebooks for demos | Each PRD example in §18 Appendix A becomes a live notebook. |
| **jupyterlab** | `4.5.6` | Self-hosted JupyterHub kernel | For depth demos (SPARQL over 1M triples). |
| **jupyterhub** | `5.4.4` | Multi-user hub | Self-hosted per brief. |

## Risks

### RISK-1 — owlready2 is NOT pure-Python (HermiT needs JVM) **[MEDIUM severity, KNOWN PRIOR TO PHASE 0]**

The milestone brief states:
> Reasoner: `owlready2` (pure-Python HermiT) for OWL 2 EL TBox

**This is incorrect.** `owlready2` 0.50 bundles HermiT and Pellet as Java `.jar` files inside `owlready2/hermit/` and shells out to `java -jar HermiT.jar` at reasoning time. A JVM (Java 11+) must be installed at runtime.

**Impact:**
- Our Docker image (currently `python:3.11-slim`, ~180 MB) grows by ~200 MB when OpenJDK 17 JRE is added. Railway's deploy plan will still fit, but cold-start time increases ~1-2s.
- Cannot be used inside `pyoxigraph`-only query paths (e.g., if we ever want to serve TBox reasoning from the SPARQL endpoint, we'd need a subprocess).
- Creates a Java CVE surface we didn't have in v1.

**Mitigation options (rank-ordered):**

1. **Accept the JVM** (recommended). Install `openjdk-17-jre-headless` in the Docker stage that runs the pipeline (not the web tier — the reasoner only runs offline during `folio-insights discover --cluster-validate`). This contains the blast radius: the public-facing web container stays JVM-free. Roadmap implication: Phase 13 (storage) needs a separate Docker stage split for "worker" vs. "web".
2. **Rust-based `reasonable` reasoner** — `reasonable` (pypi: not published; rust crate at gtfierro/reasonable) is a pure-Rust OWL 2 RL reasoner with Python bindings. It covers OWL 2 RL (not EL), which is fine for the TBox shape we need (inheritance + property chains; no existential quantifiers we classify with). **Tradeoff:** profile mismatch — we stated OWL 2 EL in the brief; we'd need to re-check any classified ontology against RL. Spike this in Phase 0 before committing.
3. **Embedding-based approximate reasoner** (`OWLAPY`'s EBR) — too lossy for legal content where hierarchical correctness is the whole point. **Reject.**

**Action:** Flag for discussion in `/gsd-new-milestone` Phase 0 spike. The brief's implementation-order plan already calls for a "Oxigraph+rdflib-bridge spike" in Phase 0; extend that spike to include a HermiT-in-Docker benchmark OR a `reasonable`-Rust POC.

### RISK-2 — No off-the-shelf Pydantic-to-SHACL generator exists **[LOW severity, SCOPE CLARIFICATION]**

Verified via PyPI survey + web search (2026-04-20): there is no maintained Python library that generates SHACL shapes from Pydantic models. The brief's "Pydantic-generated base + hand-written advanced" strategy (§10 hybrid SHACL) therefore requires building the generator in-repo.

**Scope implication:** Add a new module `src/folio_insights/shapes/pydantic_to_shacl.py` (~150 LOC estimate) that:
- Introspects a Pydantic `BaseModel` via `model_json_schema()`
- Emits `sh:NodeShape` with `sh:property` entries for each field
- Maps JSON Schema types to `sh:datatype` (integer → xsd:integer, Literal[...] → `sh:in (...)`, etc.)
- Respects `sh:minCount`/`sh:maxCount` from Pydantic `Optional`/`List` annotations
- Hand-written shapes (supersession, attestation, governance, content_edit, contest, immutable_fields — 6 shapes listed in PRD §10) augment, never override, the generated base

Budget 1-2 days in Phase 11 for the generator; it is not on the critical path (hand-written shapes cover P0 validation on their own).

### RISK-3 — instructor `from_provider()` string API minor-version coupling **[LOW severity]**

Claude default + OpenAI/Ollama CI validation (decision #5) works today on `instructor==1.15.1`. The unified `instructor.from_provider("anthropic/claude-sonnet-4-5")` API (added in 1.12) is the right abstraction but has had 3 breaking signature changes between 1.12 and 1.15. **Pin tightly** (`instructor==1.15.*`) and bump explicitly with test coverage.

### RISK-4 — SvelteKit 5 adapter-node + SSR streaming RDF **[LOW severity]**

SvelteKit 5 with `adapter-node` supports SSR streaming via `+page.server.ts` and `Response.body` passthrough. SPARQL streaming over SSE requires the endpoint to flush results as SPARQL/JSON line-by-line. Validated in a community example (SvelteKit + SSE + async iterator), but not as a first-party SvelteKit pattern. **Prototype in Phase 14** before committing the SPARQL explorer UI to this shape.

## Installation

```bash
# Core Python (pyproject.toml dependencies)
pip install \
    'pyoxigraph==0.5.7' \
    'rdflib==7.6.0' \
    'pyshacl==0.31.0' \
    'owlready2==0.50' \
    'instructor==1.15.1' \
    'arq==0.28.0' \
    'redis==7.4.0' \
    'fastapi==0.136.0' \
    'pydantic==2.13.3' \
    'pydantic-settings==2.14.0' \
    'aiosqlite==0.22.1' \
    'uvicorn==0.44.0'

# DID + cryptography
pip install \
    'cryptography==46.0.7' \
    'pynacl==1.6.2' \
    'joserfc==1.6.4' \
    'atproto==0.0.65' \
    'dag-cbor==0.3.3' \
    'jcs==0.2.1'

# OAuth
pip install \
    'authlib==1.7.0' \
    'itsdangerous==2.2.0' \
    'python-multipart==0.0.26' \
    'email-validator==2.3.0'

# Observability
pip install \
    'structlog==25.5.0' \
    'python-json-logger==4.1.0' \
    'opentelemetry-api==1.41.0' \
    'opentelemetry-sdk==1.41.0' \
    'opentelemetry-instrumentation-fastapi==0.62b0' \
    'opentelemetry-instrumentation-redis==0.62b0' \
    'opentelemetry-instrumentation-httpx==0.62b0' \
    'opentelemetry-exporter-otlp==1.41.0' \
    'prometheus-client==0.25.0' \
    'prometheus-fastapi-instrumentator==7.1.0'

# LLM providers
pip install \
    'anthropic==0.96.0' \
    'openai==2.32.0' \
    'ollama==0.6.1'

# Utilities
pip install \
    'httpx==0.28.1' \
    'httpx-sse==0.4.3' \
    'tenacity==9.1.4' \
    'orjson==3.11.8' \
    'aiofiles==25.1.0'

# Dev dependencies
pip install --group dev \
    'pytest==9.0.3' \
    'pytest-asyncio==1.3.0' \
    'ruff==0.15.11' \
    'mypy==1.20.1' \
    'pre-commit==4.5.1'

# Frontend (package.json)
npm install \
    '@sveltejs/kit@2.57.1' \
    'svelte@5.55.4' \
    '@sveltejs/adapter-node@5.5.4' \
    'vite@8.0.9'

npm install -D \
    '@playwright/test@1.59.1' \
    '@axe-core/playwright@4.11.2' \
    'axe-core@4.11.3'
```

**Docker base image changes from v1:**
```dockerfile
# worker stage (gains JVM for owlready2)
FROM python:3.11-slim AS worker
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# web stage (stays JVM-free — faster cold start)
FROM python:3.11-slim AS web
# no Java
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `pyoxigraph` (embedded) | **Apache Jena Fuseki** (external) | If we ever need federated SPARQL across multiple corpora hosted on different servers. For v2.0 single-node target (1M-10M shards), embedded pyoxigraph wins on latency (no network hop) and operational simplicity (one container). |
| `owlready2` + HermiT | **`reasonable`** (Rust OWL 2 RL) | If JVM bloat becomes operationally painful and we can downgrade the reasoning profile from EL to RL. Phase 0 spike will decide. |
| `Arq` | **Dramatiq** | If we add RabbitMQ for cross-service messaging (not planned for v2.0). Arq is purely Redis-backed; Dramatiq supports both brokers and has richer middleware. Celery rejected — not async-native, operational overhead not justified for single-node deploy. |
| `instructor` | **LiteLLM** | If we need fine-grained cost tracking + request-routing policies. `instructor` focuses on *structured output*; `LiteLLM` focuses on *provider routing*. `instructor` can wrap a `LiteLLM`-routed client (composable), so this is a non-exclusive alternative to consider later. |
| `authlib` | **FastAPI OAuth2 flow directly** (no library) | Never. The DIY path re-implements PKCE + state + nonce validation; a CVE is only a matter of time. |
| `structlog` + OTel | **Just structlog** | If OTel's ~15 MB dependency adds cold-start cost that matters. For a self-hosted shards service, span-level debugging is essential as corpora scale past 100K shards; keep OTel. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `didkit` / `didkit-python` | Last release 2024-08. Spruce Systems deprecated the Python bindings; Rust core still exists but Python wheels are not built for 3.12+. | Hand-rolled `did:key` with `PyNaCl` + `did:web` with `httpx` + `atproto` for `did:plc`. |
| `pydid` | Wraps DID document parsing in a Pydantic layer that adds little value and transitively pulls in `pycryptodome` (we already have `cryptography`). | Parse DID docs directly with `httpx`+`orjson`; we only need the `verificationMethod` key. |
| `python-jose` | Unmaintained since mid-2025. `ecdsa` CVE surface. | `joserfc` (by the Authlib author, actively maintained, Pydantic-2 compatible). |
| `PyJWT` for JWS | Only does JWT compact serialization — not JWS detached or JSON serialization, both of which we need for DID-signed shard attestations. | `joserfc`. |
| `fastapi-users` | Forces password-based user model; our identity is DID-first. | `authlib` + custom `DIDBinding` SQLite table joining OAuth email → DID(s). |
| `Celery` | Not async-native; operational weight not justified for single-container deploy. | `Arq` (LOCKED). |
| `py-ed25519-bindings` (0.2.0, 2022) | Stale; not Python 3.12-compatible. | `PyNaCl` (libsodium, broadly maintained) OR `py-ed25519-zebra-bindings` (1.3.0, 2025) if pure-Rust preferred. |
| `SPARQLWrapper` | HTTP client for remote SPARQL endpoints. Our endpoint is in-process. | `pyoxigraph.Store.query()` directly. |
| `rdflib`-as-primary-store | rdflib triplestore is <5K triples/sec; pyoxigraph is ~200K triples/sec insert. | Use rdflib only as the bridge for pyshacl / JSON-LD, not as the backing store. |
| `owlready2.default_world` as SPARQL engine | Owlready2's SPARQL is incomplete (no SPARQL-star, no federated queries). | pyoxigraph for all SPARQL; owlready2 only inside the cluster validator. |
| `pydantic` v1 | EOL; `instructor` 1.15 requires v2. | `pydantic==2.13.3`. |
| `slowapi` for rate limiting | Last release 2024-02, sync-only middleware. | `fastapi-limiter==0.2.0` (Redis-backed, async, shares our Arq Redis instance). |
| SvelteKit `adapter-static` | v1 used this; SSR and deep-link SPARQL streaming require a real server runtime. | `adapter-node` (LOCKED). |

## Stack Patterns by Variant

**If reviewer deployment is institutional (JupyterHub / DID:web):**
- Use `did:web` as primary reviewer DID (discoverable via HTTPS, tied to domain)
- Use `authlib` with institutional OIDC provider (Google Workspace / GitHub Enterprise)
- DID binding stored in SQLite `identity_bindings` table

**If reviewer deployment is individual (desktop key, did:key or did:plc):**
- `did:key` for offline-first reviewers (private key in `~/.folio-insights/signing.key`)
- `did:plc` for AT Proto-native reviewers (Bluesky handle → PLC directory lookup)
- OAuth only for initial identity binding, not per-action auth

**If corpus scale is small (<100K shards):**
- pyoxigraph in-memory mode (no RocksDB on disk)
- SvelteKit SSR renders SPARQL result pages directly without streaming

**If corpus scale exceeds 1M shards:**
- pyoxigraph persistent RocksDB with `store = Store("./data")` path
- SPARQL streaming via SSE mandatory for the UI's SPARQL explorer
- Arq worker pool size bumped (default 10 → 50) for parallel extraction

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `pyoxigraph==0.5.7` | `rdflib==7.6.0` | Bridge via `pyoxigraph.Store.dump(RdfFormat.TURTLE)` → `rdflib.Graph().parse(data=..., format="turtle")`. No direct object sharing. |
| `pyshacl==0.31.0` | `rdflib>=7.0,<8.0` | pySHACL constructs its own `rdflib.Dataset` internally; pass graph objects not pyoxigraph stores. |
| `owlready2==0.50` | Python 3.11+, OpenJDK 17 JRE | JVM flag for Java reasoning: `owlready2.JAVA_EXE = "/usr/bin/java"`. |
| `instructor==1.15.1` | `pydantic>=2.10,<3.0`, `anthropic>=0.60`, `openai>=2.0`, `ollama>=0.5` | `from_provider()` strings require these minimums. |
| `arq==0.28.0` | `redis-py==7.4.0` | Arq 0.28 has `async with redis.pipeline()` support; older Redis clients break. |
| `opentelemetry-api==1.41.0` | `opentelemetry-sdk==1.41.0` | **Always** pin to identical minor version. Minor drift causes silent span loss. |
| `opentelemetry-instrumentation-*==0.62b0` | `opentelemetry-api==1.41.0` | The `0.62bN` beta family maps to SDK `1.41`; this is the OTel-Python versioning pattern, not pre-release. |
| `authlib==1.7.0` | `httpx>=0.27,<0.30`, `itsdangerous>=2.0` | Starlette `SessionMiddleware` requires `itsdangerous`. |
| `SvelteKit@2.57.1` | `vite@>=6.0,<9.0`, `svelte@^5.0` | adapter-node 5.x requires SvelteKit 2.5+. |
| `@axe-core/playwright@4.11.2` | `axe-core@4.11.x` | Minor-version match mandatory. |

## Integration Points (how the locked choices connect)

```
┌────────────────────────────────────────────────────────────────────┐
│                        FastAPI web tier                            │
│  authlib OAuth  ──►  DID binding  ──►  structlog + OTel traces     │
│        │                                          │                │
│        ▼                                          ▼                │
│  ┌──────────────┐                        ┌─────────────────┐       │
│  │ SvelteKit 5  │                        │ Prometheus      │       │
│  │ adapter-node │ ◄─── SSE stream ─────  │ metrics scrape  │       │
│  └──────────────┘                        └─────────────────┘       │
│        │                                                           │
│        │  SPARQL query                                             │
│        ▼                                                           │
│  ┌──────────────────────────────────────────────────────┐          │
│  │  pyoxigraph Store (canonical — RDF-star + SPARQL-star)│         │
│  │       ▲                                               │         │
│  │       │ rdflib bridge (pyshacl input + JSON-LD export)│         │
│  └──────────────────────────────────────────────────────┘          │
└─────────────────────────────┬──────────────────────────────────────┘
                              │ enqueue job
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│                    Arq worker tier (has JVM)                       │
│  instructor ──► LLM ──► Pydantic Shard ──► DID sign (PyNaCl/JCS)   │
│                              │                                     │
│                              ▼                                     │
│                      pyshacl validate                              │
│                              │                                     │
│                              ▼                                     │
│            owlready2 (HermiT) cluster validator                    │
│                              │                                     │
│                              ▼                                     │
│                     pyoxigraph write                               │
└────────────────────────────────────────────────────────────────────┘
```

**Key integration contracts:**

1. **Pydantic Shard → SHACL validation:** Pydantic models (§6.1 envelope) are the authoritative schema. The generator we build (RISK-2 mitigation) emits `envelope.shacl.ttl`. `pyshacl.validate(data_graph=rdflib_graph, shacl_graph=envelope_shape)` runs on every shard write.
2. **Pydantic Shard → pyoxigraph insert:** Serialize Shard to Turtle via rdflib, parse into `pyoxigraph.Store.load(data, RdfFormat.TURTLE_STAR)`. Bulk-insert uses `Store.bulk_load()` for ~200K triples/sec.
3. **DID signing pipeline:** `jcs.canonicalize(shard.model_dump())` → SHA-256 → `PyNaCl.SigningKey.sign(hash)` → base58 → `AttestedSignature.signature`. Verification re-canonicalizes and re-hashes; `jcs` is deterministic so hashes must match.
4. **OAuth → DID binding:** `authlib.integrations.starlette_client.OAuth("github")` handles flow; on callback, look up `identity_bindings(oauth_email, did)` table; if absent, 403 until user signs a binding proof with their DID key.
5. **instructor → structlog → OTel:** `instructor.from_anthropic(client)` wraps Anthropic SDK; `structlog.get_logger().bind(provider="anthropic", model=...)` context flows to OTel spans via `structlog.processors.format_exc_info` + the `LoggingInstrumentor`.

## Sources

- [pyoxigraph 0.5.7 PyPI](https://pypi.org/project/pyoxigraph/) — version verified, released 2026-04-19
- [pyoxigraph docs — RDF-star + SPARQL-star](https://pyoxigraph.readthedocs.io/) — HIGH confidence
- [rdflib 7.6.0 PyPI](https://pypi.org/project/rdflib/) — version verified 2026-02-13
- [pyshacl 0.31.0 PyPI](https://pypi.org/project/pyshacl/) — HIGH
- [owlready2 0.50 docs — Reasoning](https://owlready2.readthedocs.io/en/latest/reasoning.html) — "HermiT and Pellet are written in Java" — HIGH (source of RISK-1)
- [instructor 1.15.1 PyPI](https://pypi.org/project/instructor/) — HIGH
- [instructor multi-provider docs](https://python.useinstructor.com/integrations/) — HIGH; verified Anthropic/OpenAI/Google/Ollama integration
- [Arq 0.28.0 PyPI](https://pypi.org/project/arq/) — HIGH
- [FastAPI 0.136.0 PyPI](https://pypi.org/project/fastapi/) — HIGH
- [Authlib 1.7.0 PyPI + FastAPI OAuth Client docs](https://docs.authlib.org/en/latest/client/fastapi.html) — HIGH
- [WorkOS — Top FastAPI auth solutions 2026](https://workos.com/blog/top-authentication-solutions-fastapi-2026) — MEDIUM; confirmed fastapi-users-vs-authlib analysis
- [atproto Python SDK — did:plc signing](https://atproto.blue/en/latest/) — MEDIUM; did:plc spec verification via [did:plc v0.1](https://web.plc.directory/spec/v0.1/did-plc)
- [OpenTelemetry Python 1.41.0 release](https://pypi.org/project/opentelemetry-api/) — HIGH
- [structlog 25.5.0 PyPI](https://pypi.org/project/structlog/) — HIGH
- [SvelteKit 2.57.1 npm](https://www.npmjs.com/package/@sveltejs/kit) — HIGH
- [PyPI survey on 2026-04-20 for 40+ packages above] — HIGH (all versions verified same-day)
- [Search: "SHACL generator from Pydantic" 2026] — source of RISK-2 (no library exists)
- [GitHub: rch/pyowlready2, gtfierro/reasonable] — sources for RISK-1 mitigation options — MEDIUM

---
*Stack research for: v2.0-shards-as-axioms milestone*
*Researched: 2026-04-20*
