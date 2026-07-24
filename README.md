# FOLIO Insights

Extract structured advocacy knowledge from legal knowledge sources and map it to the
[FOLIO legal ontology](https://github.com/alea-institute/FOLIO) as a validated,
browsable, queryable OWL module.

FOLIO Insights reads legal knowledge sources — practice guides, treatises,
continuing-legal-education materials, synthesized notes — and turns it into a
task-organized knowledge base
where every piece of advice, every principle, every citation, every procedural
rule, and every pitfall is distilled, tagged against 27K+ FOLIO concepts, and
attached to a discovered advocacy task (e.g., *Expert Depositions*, *Opening
Statements*, *Motion Practice*).

The output is a single SHACL-validated OWL file with companion JSON-LD,
browsable HTML, and Markdown — ready for SPARQL queries, LLM retrieval, or
human browsing.

---

## Why This Exists

Legal advocacy knowledge lives in long-form prose: dense sections, numbered
rules, embedded case cites, footnotes inside footnotes. Finding *all* the
cross-examination advice across five knowledge sources means reading five
knowledge sources. Finding the contradictions between them means reading them
twice.

FOLIO Insights distills that material into structured, task-organized knowledge
so that any practitioner, AI system, or application querying *"how do I take
an expert deposition"* gets back a hierarchical set of techniques, principles,
warnings, and authorities — each one traceable back to its source, each one
mapped to a formal FOLIO concept.

The system is **meant to be extractive, not generative**: it distills what the
source says, it does not evaluate legal merit and it does not rewrite the text.
Ideas, not expressions.

> **Known gap (2026-07).** A books-UAT de-risk run showed the v1.0 pipeline does
> **not** yet honor that contract: units were fabricated rather than grounded in
> the ingested text, and ~90% of 2,226 FOLIO tags pointed at the wrong concept
> because the LLM path emitted IRIs directly while the deterministic paths never
> ran (*Rule 26(a)(1)* → *Russian Federation*). Findings, gold set, and the locked
> extraction-quality rubric are in
> [`docs/evidence/books/`](docs/evidence/books/) and
> [`docs/rubrics/`](docs/rubrics/). The remediation is source-grounded extraction
> plus deterministic IRI resolution (the LLM never emits an IRI) via
> [folio-resolve](https://github.com/damienriehl/folio-resolve).
>
> **Half of that remediation has now landed (2026-07-24).** The deterministic
> resolution side is merged: the tagger delegates every label→IRI decision to
> the pinned `folio-resolve` package — `LabelResolver` (decompose-first, with a
> calibrated 0–100 whole-string bar that closes the old `0.6` no-op),
> `FOLIOEntityRuler`, `Reconciler`, `PlaceNameGate`, the seed alias blocklist,
> `SourceClassifier`, and an LLM-as-judge pass that can only reject or clamp,
> never mint an IRI. Chapter-level before/after evidence is in
> [`docs/evidence/books/folio-matching-proving-run/`](docs/evidence/books/folio-matching-proving-run/).
> **Source-grounded extraction is still outstanding**, so v1.0 corpus output
> remains unvalidated until that half lands too.

**Who it's for:**

- **Researchers and ontologists** building FOLIO-aligned legal knowledge bases.
- **Application developers** who want a queryable, task-indexed corpus of
  advocacy knowledge as a starting point.
- **AI engineers** wiring legal retrieval into RAG pipelines or agents — the
  JSON-LD export is sized for chunked retrieval.
- **Practitioners and educators** exploring how advocacy concepts connect
  through a browsable ontology.

---

## What v1.0 Ships

A complete, end-to-end pipeline from raw source files to validated OWL output,
with both a CLI batch workflow and an interactive web UI.

**Ingestion** — 14 document formats (Markdown, PDF, DOCX, HTML, and more) with
tiered boundary detection: structural heuristics first (headings, bullets,
numbered lists), then LLM refinement for ambiguous multi-advice paragraphs.

**FOLIO concept tagging** — 4-path extraction against the full ~27,000-label
FOLIO ontology with 5-stage confidence scoring, reusing folio-enrich's proven
EntityRuler, LLM, and semantic-ruler paths.

**Task hierarchy discovery** — LLM-driven discovery of top-level advocacy tasks
from the corpus, with sub-task structuring, cross-source merging, and NLI-based
contradiction detection across conflicting advice from different sources.

**Output** — SHACL-validated OWL (RDF/XML and Turtle), JSON-LD sized for RAG
chunking, a browsable HTML index, and a Markdown outline. All five formats
from one `export` command.

**Web UI** — Upload → Process → Discover → Review → Export, a full SvelteKit
review viewer served by FastAPI. Manual approval, task editing, contradiction
resolution, and one-click export in any of the five formats.

**Corpus tracking** — Incremental processing by content hash. Add documents,
re-run the pipeline, and only the new material gets re-processed.

**Scale at v1.0 (2026-04-04):** 26,198 LOC (17,510 Python + 8,688 Svelte/TS),
255 source files, 197 tests passing. On `master` today: ~25,400 Python LOC plus
~8,900 Svelte/TS, and 691 tests across 123 test files.

---

## What v2.0 Is Adding (in progress)

v2.0 — **shards-as-axioms** — reworks the knowledge unit into a signed,
versioned, governable *shard* so a corpus can be published, forked, and
attributed rather than merely exported. Phases 0–8 are complete; 9–20 are not
started (roadmap and per-phase detail in [`.planning/ROADMAP.md`](.planning/ROADMAP.md)):

- **Foundations / polysemy** — pyoxigraph chosen as the triple store at a 1M-triple
  hard gate; `distinguo` polysemy detection and review (`folio-insights polysemy
  detect|review`).
- **Shard envelope + IRI scheme + content versioning** — a stable IRI per shard,
  RFC 8785 canonical content hashing, and valid-time supersession queryable via
  `query_as_of` ([`docs/query-as-of.md`](docs/query-as-of.md)).
- **DID substrate** — ed25519 reviewer identities as `did:key`, `did:web` and
  `did:plc` resolution, and signed attestations (`folio-insights did
  generate|sign|verify|bind`).
- **Governance model** — proposal/attestation lifecycle with SHACL-enforced
  shapes (`folio-insights governance …`, `folio-insights corpus …`).
- **FOLIO v2 vocab + mini-BFO spine** — project vocabulary (`vocab/*.ttl`) aligned
  to Basic Formal Ontology, with a predicate drift audit that fails the build when
  emitted `fi:*` predicates diverge from the PRD.
- **Bench harness** — a deterministic 1M-triple corpus generator (`folio-insights
  bench gen`) behind the Phase 0 performance gate.

---

## Architecture

A four-stage batch pipeline that extends folio-enrich via a bridge adapter.
Each stage transforms its input into a progressively more structured form:

```
  +-----------+     +----------------+     +---------------+     +-------------+
  | Stage 1   | --> | Stage 2        | --> | Stage 3       | --> | Stage 4     |
  | Ingest +  |     | Task Hierarchy |     | OWL Mapping + |     | Validation +|
  | FOLIO Tag |     | Discovery      |     | Serialization |     | Export      |
  +-----------+     +----------------+     +---------------+     +-------------+
       |                   |                      |                     |
       v                   v                      v                     v
   Knowledge         Task tree with         RDF graph with        Validated OWL,
   units with        units attached         FOLIO links           TTL, JSON-LD,
   FOLIO tags        to leaf nodes          and provenance        HTML, Markdown
```

**Bridge pattern.** FOLIO Insights does not modify folio-enrich. It imports
`FolioService`, `EntityRuler`, and the reconciler as libraries through a
thin `folio_bridge` adapter that adds the sibling repo to `sys.path`. This
keeps folio-enrich's 27K-label index, 13 export formats, and confidence
scoring available without duplicating a single line.

See [`.planning/research/ARCHITECTURE.md`](.planning/research/ARCHITECTURE.md)
for the full design rationale and component breakdown.

---

## Setup

**Requirements:**

- Python 3.11+
- Node.js 20+ (only if you want to rebuild the SvelteKit viewer; prebuilt
  static assets ship with the repo)
- An LLM provider API key (Anthropic by default; any provider `instructor`
  supports will work)

**Clone the sibling repos.** FOLIO Insights imports services from folio-enrich
and folio-mapper through a `sys.path` bridge. Clone both as siblings of this
repo (or point the env vars elsewhere):

```bash
cd ~/your-workspace
git clone https://github.com/alea-institute/folio-enrich.git
git clone https://github.com/alea-institute/folio-mapper.git
git clone https://github.com/alea-institute/folio-insights.git
```

**Install FOLIO Insights:**

```bash
cd folio-insights
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

**Configure the environment:**

```bash
cp .env.example .env
# Edit .env to set LLM_PROVIDER, LLM_MODEL, and API keys.
# Bridge paths default to ../folio-enrich/backend and ../folio-mapper/backend
# and only need to be set if the siblings live elsewhere.
```

**Verify the install:**

```bash
folio-insights --version
pytest                       # 691 tests across 123 files
```

**Benchmark fixture (not committed).** The 1M-triple corpus `fixtures/bench.nq`
(~235 MB) is git-ignored — it exceeds GitHub's 100 MB limit. It's deterministic,
so regenerate it locally before running the benchmark suite (`tests/bench/`):

```bash
uv run folio-insights bench gen --seed 42 --target 1000000 \
  --profile phase-0-gate --out fixtures/bench.nq   # SHA256 ffb2c130...
```

---

## CLI Quickstart

The full pipeline is three commands — extract, discover, export — plus a
fourth to launch the review viewer.

```bash
# 1. Extract knowledge units from a directory of source documents
folio-insights extract ./my-sources --corpus advocacy --output ./output

# 2. Discover task hierarchy from the extracted units
folio-insights discover advocacy --output ./output

# 3. Export the approved tasks in every supported format
folio-insights export advocacy --format owl,ttl,jsonld,html,md

# 4. Launch the web review viewer
folio-insights serve --port 8742
```

Plus `folio-insights verify-iris` (audits stored tags against the live FOLIO
catalogue — the check that surfaced the hallucinated-IRI defect) and the v2.0
subgroups: `bench`, `polysemy`, `did`, `governance`, `corpus`. Each subgroup
imports its heavy dependencies lazily, so `folio-insights --help` never pulls
pyoxigraph, rdflib, or the crypto stack.

Each command is resumable: re-run with `--resume` (the default) and it picks
up from the last checkpoint. Each command also prints a summary when it
finishes — files processed, units extracted, tasks discovered, contradictions
found, validation results.

See `folio-insights <command> --help` for the full option set on each command
(confidence thresholds, cluster thresholds, NLI thresholds, approved-only vs.
all-units export, SHACL validation on/off, and more).

---

## Web UI

Launch the review viewer with `folio-insights serve` and open the URL it
prints. The UI wraps the same pipeline in a five-pane workflow:

- **Upload** — drop source files into a corpus; incremental dedup by content
  hash.
- **Process** — run extraction with live progress streaming (SSE); inspect
  confidence-gated units as they come in.
- **Discover** — run task discovery; see the emerging task tree and any
  flagged contradictions.
- **Review** — three-pane browser (task tree, unit detail, source context)
  for manual approval, label editing, re-parenting, and contradiction
  resolution.
- **Export** — choose formats, toggle approved-only, run SHACL validation,
  download the artifacts.

Everything the CLI does, the UI does — backed by the same pipeline code.

---

## Dependencies

**Python (runtime):** pydantic + pydantic-settings, FastAPI, uvicorn,
sse-starlette, rdflib, pyshacl, pyoxigraph + oxrdflib, sentence-transformers,
instructor (for LLM calls), aiosqlite, Click, httpx, lxml, folio-python, and the
bridge-tier deps folio-enrich needs but does not export (python-docx, rapidfuzz,
marisa-trie). The v2.0 DID substrate adds cryptography, PyNaCl, base58, jcs,
atproto, dag-cbor, joserfc, and Authlib.

**Python (optional):** `.[reasoning]` pulls owlready2 (HermiT, needs a JVM) — the
web tier deliberately omits it; only the worker and the CLI reasoning paths use it.

**Python (dev):** pytest, pytest-asyncio, pytest-timeout, pytest-benchmark,
hypothesis, ruff, dagger-io.

**Frontend:** SvelteKit 2, Svelte 5, Vite 7, TypeScript 5, `@keenmate/svelte-treeview`.
The viewer uses `@sveltejs/adapter-static` so FastAPI serves the built assets
directly — no separate Node runtime in production.

**Sibling-repo imports (via bridge adapter):** folio-enrich (FolioService,
EntityRuler, reconciler, 27K+ FOLIO labels), folio-mapper.

**External ontology:** [FOLIO](https://github.com/alea-institute/FOLIO) —
fetched once and cached locally. The v2.0 vocab spine also incorporates
[BFO](https://basic-formal-ontology.org/). Both are CC-BY 4.0.

See [`pyproject.toml`](pyproject.toml) for pinned versions and
[`THIRD-PARTY.md`](THIRD-PARTY.md) for the per-component license inventory.

---

## Project Layout

```
folio-insights/
├── src/folio_insights/     # Core pipeline, config, CLI, orchestration
│   ├── pipeline/           # 4-stage batch pipeline (extract, discover, ...)
│   ├── services/           # OWL serializer, task exporter, validators
│   │   └── bridge/         # sys.path adapters onto folio-enrich / folio-mapper
│   ├── quality/            # Confidence gate, scoring
│   ├── export/             # OWL / TTL / JSON-LD / HTML / Markdown writers
│   ├── vocab/              # v2.0 FOLIO-v2 vocabulary + mini-BFO spine (TTL)
│   ├── shards/             # Shard envelope, subtypes, IRI scheme
│   ├── temporal/           # Valid-time supersession + query_as_of
│   ├── revision/           # Content versioning + canonical content hashing
│   ├── identity/           # DID substrate (did:key / did:web / did:plc, signing)
│   ├── governance/         # Proposal + attestation lifecycle, SHACL shapes
│   ├── corpus/             # Corpus tracking + incremental processing
│   ├── polysemy/           # distinguo sense-splitting detection and review
│   ├── reason/             # OWL reasoning (owlready2 / HermiT, optional extra)
│   ├── store/              # pyoxigraph-backed triple store layer
│   ├── bench/              # 1M-triple deterministic corpus generator + gate
│   ├── worker.py           # Worker tier entry point (idle stub until Phase 10)
│   └── cli.py              # `folio-insights` CLI entry point
├── api/                    # FastAPI backend for the review viewer
│   ├── routes/             # upload, processing, discovery, review, export, ...
│   ├── services/           # Backend-specific services
│   └── main.py             # FastAPI app factory + `serve()` entry
├── viewer/                 # SvelteKit review viewer
├── docs/                   # Evidence packs, rubrics, campaigns, solutions
├── tests/                  # pytest suite (unit + integration markers)
└── .planning/              # GSD planning artifacts (kept in-repo on purpose)
```

---

## Contributing

Contributions are welcome. A few things to know first:

- **Sibling-repo workflow.** Most non-trivial changes touch the bridge adapter
  at some point. Clone folio-enrich and folio-mapper as siblings; run the
  integration tests (`pytest -m integration`) before opening a PR.
- **Planning artifacts are in-repo.** This project is built with
  [GSD](https://github.com/damienriehl/get-shit-done), so `.planning/` lives in
  version control — it holds phase plans, research notes, decisions, and
  architecture docs. That's the project's memory; contributions that change
  architecture should update it too.
- **Tests must pass.** 691 tests on `master` (197 at v1.0). Integration tests
  require the sibling repos; unit tests do not.
- **Confidence scoring and FOLIO tagging are load-bearing.** Changes to
  thresholds, gating, or the four extraction paths need a clear rationale —
  downstream consumers depend on the confidence contract.

Open an issue before starting work on anything large. Small fixes and
doc improvements are fine to PR directly.

---

## Out of Scope

By design, FOLIO Insights does **not**:

- Provide a user-facing legal advice UI. Downstream consumers build their own
  applications on top of the ontology.
- Evaluate legal merit. The system extracts what the sources say; it does not
  decide whether they are right.
- Run in real time. This is a batch pipeline — quality over speed.
- Rewrite source text. Ideas, not expressions; distill, never paraphrase in
  ways that would substitute for the original.
- Support non-English corpora at the source-text level. FOLIO's multilingual
  labels are used passively where available.

---

## Deploying to Railway

A dev environment is deployed on Railway at **https://folio-insights-production.up.railway.app**
as a **single web service** built from [`Dockerfile.web`](Dockerfile.web): a FastAPI backend
that also serves the built SvelteKit viewer (a static SPA) at `/`, on one port. The flat
[`railway.toml`](railway.toml) pins the builder and healthcheck as config-as-code:

```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile.web"

[deploy]
healthcheckPath = "/health"
healthcheckTimeout = 120
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3
```

> **Web-only by design.** The `worker` tier (OWL reasoning) is an idle stub until Phase 10 and
> is **not** deployed in this dev environment — there is no worker service, no Redis, no Oxigraph.
> The full multi-service GA cut (web + worker + Redis + Oxigraph, full SSR) is owned by Phase 20.
> Use a **flat** `railway.toml`, never nested `[services.*]` tables — Railway silently ignores the
> nested schema (which caused a prior HTTP 502: it fell back to building the stale `/Dockerfile`).

### One-time setup

The project already exists on Railway — **link** to it, do not create a new one:

```bash
npm i -g @railway/cli
railway login
railway link -p folio-insights -e production -s folio-insights   # link to the EXISTING project
```

Runtime variables are set as **masked** Railway variables. Non-secrets inline; secrets via stdin
(never on argv / shell history):

```bash
railway variable set LLM_PROVIDER=anthropic LLM_MODEL=claude-sonnet-4-6 -s folio-insights --skip-deploys
# Secrets (if/when needed) — paste the value at the prompt, then Ctrl-D:
# railway variable set SOME_SECRET --stdin -s folio-insights --skip-deploys
```

> **No shared LLM key is baked into the server.** LLM-backed features use Bring-Your-Own-Key
> (each user supplies their own key); the dev server intentionally has no `ANTHROPIC_API_KEY`.

### Auto-deploy on push to `master`

In the Railway dashboard: **Service → Settings → Source** → connect `alea-institute/folio-insights`
and set the trigger branch to `master`. Every push to `master` then triggers an automatic rebuild
and redeploy. To deploy manually instead: `railway up -s folio-insights`.

### Verify

```bash
URL="https://folio-insights-production.up.railway.app"
curl -sf "$URL/health"                  # {"status":"ok"}
curl -sI "$URL/" | head -1              # HTTP/2 200 (SPA shell; no x-railway-fallback header)
curl -sf "$URL/api/v1/corpora"          # JSON list of bundled corpora
```

### Notes

- **Data:** the baseline corpora `output/default/`, `output/demo/`, and `output/test1/` are
  whitelisted in `.gitignore` **and** re-included in `.dockerignore`, so `Dockerfile.web`'s
  `COPY output/` bundles them into the image and the viewer renders real data. Other generated
  output stays git-ignored. (SQLite `*.db-wal`/`*.db-shm` sidecars are excluded for build determinism.)
- **SPA viewer:** the viewer is built with `@sveltejs/adapter-static` and served by FastAPI
  (`StaticFiles` with an `index.html` fallback for client-side routes, so deep links / refreshes
  work). Full server-side rendering returns with the Phase 20 GA cut.
- **Image size** is large (~8.7 GB) because `sentence-transformers` pulls torch + CUDA libs.
  If you need a slimmer image, pin CPU-only torch in `Dockerfile.web`.
- **Reproducible builds:** `Dockerfile.web` defaults `SOURCE_DATE_EPOCH=0` so plain Railway builds
  (which pass no build-arg) succeed; the Dagger/CI path overrides it with the real commit epoch.
- First build on Railway takes ~8-15 minutes; subsequent builds reuse cached layers.

---

## License

MIT License — see [LICENSE](LICENSE).

Copyright © Damien Riehl and ALEA Institute.
