# Third-Party Licenses & Attribution

folio-insights is licensed **MIT** (see `LICENSE`). It incorporates the
open-source components and openly-licensed ontologies below.

## Openly-licensed data

### FOLIO ontology — CC-BY 4.0
Extractions are mapped to **FOLIO** (Federated Open Legal Information Ontology),
maintained by the **ALEA Institute**, originating from the **SALI Alliance**;
consumed via `folio-python`. Licensed **CC-BY 4.0**.
- Source: https://github.com/alea-institute/FOLIO · License: https://creativecommons.org/licenses/by/4.0/

### Basic Formal Ontology (BFO) — CC-BY 4.0
The upper-ontology spine (`src/folio_insights/vocab/bfo_spine.ttl`,
`bfo_mapping.ttl`) incorporates **BFO**, licensed **CC-BY 4.0**.
- Source: https://basic-formal-ontology.org/ · License: https://creativecommons.org/licenses/by/4.0/

Project-authored vocab/SHACL (`vocab/classes.ttl`, `predicates.ttl`,
`shapes.ttl`, `export/context.jsonld`) is part of this repo under MIT.

### Axiom kernel texts — public domain
The kernel datasets (`src/folio_insights/kernel/data/*.json`) carry Latin texts
cut by `scripts/kernel/fetch_and_verify_sources.py` out of public-domain
editions (published before 1929); each item records its source URL, retrieval
time and the SHA-256 of the fetched file. No translation or editorial
apparatus is included.

| Collection | Edition (public domain) | Transcriptions used (carriers of the text) |
|------------|-------------------------|--------------------------------------------|
| Liber Sextus, lib. V tit. XII *De regulis iuris* (VI 5.12.1-88) | *Corpus iuris canonici*, ed. Aemilius Friedberg, pars secunda (Leipzig: B. Tauchnitz, 1881), cols. 1122-1124 | Internet Archive scans of that edition: item `liber-sextus-bonifacii-1298` (OCR text and the PDF's text layer) and item `corpusjuriscanon00richuoft` (University of Toronto copy), https://archive.org/ |
| Digest 50.17 *De diversis regulis iuris antiqui* (D.50.17.1-211) | Mommsen–Krüger Digest text | Université Grenoble Alpes, *Droit romain* site (https://droitromain.univ-grenoble-alpes.fr/Corpus/d-50.htm, primary) and The Latin Library (https://www.thelatinlibrary.com/justinian/digest50.shtml, cross-check) |

The web transcriptions are credited as the sources the public-domain text was
taken from; nothing of their site design or apparatus is copied.

## Runtime dependencies (`pyproject.toml` → `[project.dependencies]`)

| Component | License | Used for |
|-----------|---------|----------|
| pydantic, pydantic-settings | MIT | models + settings |
| instructor | MIT | structured LLM calls (the Phase 10 LLM port's validation and single retry layer) |
| openai | Apache-2.0 | LLM port transport: every supported provider's OpenAI-compatible chat-completions endpoint (declared directly in Phase 10; already in the lock as an instructor dependency) |
| tenacity | Apache-2.0 | LLM port retry policy (declared directly in Phase 10; already in the lock as an instructor dependency) |
| folio-python | MIT | FOLIO ontology access |
| folio-resolve | MIT | deterministic label→IRI resolution, entity ruler, reconciler, match gates |
| folio-propositions | MIT | proposition models imported by the folio-enrich bridge (git dependency, pinned to a commit in `uv.lock` / `requirements.vcs.lock`) |
| fastapi, python-multipart | MIT / Apache-2.0 | web tier + uploads |
| uvicorn, sse-starlette | BSD-3-Clause | ASGI server + progress streaming |
| httpx, click, lxml, rdflib | BSD-3-Clause | HTTP, CLI, XML, RDF graph |
| aiosqlite | MIT | async SQLite store |
| pyshacl | Apache-2.0 | SHACL validation |
| pyoxigraph | Apache-2.0 | triple store (Phase 0 gate winner) |
| oxrdflib | BSD-3-Clause | rdflib ↔ oxigraph bridge |
| sentence-transformers | Apache-2.0 | local embeddings |
| python-docx, rapidfuzz | MIT | bridge-tier: .docx ingestion, fuzzy label match |
| marisa-trie | MIT AND (BSD-2-Clause OR LGPL-2.1-or-later) | bridge-tier: label trie behind folio-python search |
| cryptography | Apache-2.0 OR BSD-3-Clause | did:web verification |
| PyNaCl | Apache-2.0 | ed25519 sign/verify hot path |
| base58 | MIT | did:key multibase encoding |
| jcs | Apache-2.0 | RFC 8785 canonical JSON (content hashing) |
| atproto | MIT | did:plc resolution |
| dag-cbor | MIT | DAG-CBOR decode of the did:plc operation log |
| joserfc | BSD-3-Clause | JWS wrapping for VC-style attestations |
| Authlib | BSD-3-Clause | OAuth `sub`-claim semantics for DID binding |

## Optional dependencies

| Component | License | Extra | Note |
|-----------|---------|-------|------|
| owlready2 (HermiT) | LGPL-3.0-or-later | `reasoning`, `dev` | **Copyleft.** Used unmodified as an installed, dynamically-imported library and never vendored or redistributed inside this repo, so it does not affect this project's MIT license. The web tier omits it entirely; only the worker and CLI reasoning paths import it. Any redistribution of a bundled artifact that includes owlready2 must honor the LGPL (offer the library's source and permit relinking). |

## Dev dependencies

| Component | License |
|-----------|---------|
| pytest, pytest-asyncio, pytest-timeout, pytest-benchmark | MIT |
| hypothesis | MPL-2.0 (file-level copyleft; test-only, not distributed) |
| ruff | MIT |
| dagger-io, opentelemetry-exporter-otlp-proto-grpc | Apache-2.0 |

## Image build tooling (`requirements.build.lock`, `apk.worker-build.lock`, `UV_IMAGE`)

Pinned so container rebuilds are reproducible over time (Gate 5). These run only
inside builder stages; none of them is installed in a shipped image.

| Component | License | Used for |
|-----------|---------|----------|
| uv (`ghcr.io/astral-sh/uv`) | MIT OR Apache-2.0 | installs the hash-pinned locks in both images |
| hatchling (+ packaging, pathspec, pluggy, trove-classifiers, tomlkit) | MIT (packaging: Apache-2.0 OR BSD-2-Clause; pathspec: MPL-2.0; trove-classifiers: Apache-2.0) | builds the folio-insights and folio-propositions wheels |
| setuptools, wheel | MIT | build owlready2's sdist (worker) |
| Cython | Apache-2.0 | generates owlready2's C optimizer; the generated code ships compiled inside owlready2 |
| gcc, binutils, musl-dev (Alpine) | GPL-3.0-or-later (GCC Runtime Library Exception) / MIT (musl) | compile owlready2's C optimizer in the worker deps-builder; not shipped |

## Frontend (`viewer/package.json`)

| Component | License |
|-----------|---------|
| Svelte 5, SvelteKit 2, `@sveltejs/adapter-static`, `@sveltejs/adapter-auto`, `@sveltejs/vite-plugin-svelte` | MIT |
| Vite 7, TypeScript 5, svelte-check | MIT / Apache-2.0 |
| `@keenmate/svelte-treeview` | MIT |
| Vitest 5 (`vitest`, dev only; pinned 5.0.3) | MIT |

## Models

`sentence-transformers` downloads `all-MiniLM-L6-v2` (Apache-2.0, sentence-transformers /
Microsoft) at first use. No model weights are vendored in this repo.
