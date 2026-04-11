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

The system is **extractive, not generative**: it distills what the source says,
it does not evaluate legal merit and it does not rewrite the text. Ideas, not
expressions.

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

**Scale:** 26,198 LOC (17,510 Python + 8,688 Svelte/TS), 255 source files, 197
tests passing, v1.0 shipped 2026-04-04.

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
pytest                       # 197 tests should pass
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

**Python (runtime):** FastAPI, rdflib, pyshacl, sentence-transformers,
instructor (for LLM calls), aiosqlite, Click, httpx, lxml, folio-python.

**Python (dev):** pytest, pytest-asyncio, pytest-timeout.

**Frontend:** SvelteKit 2, Svelte 5, Vite 7, TypeScript 5, `@keenmate/svelte-treeview`.
The viewer uses `@sveltejs/adapter-static` so FastAPI serves the built assets
directly — no separate Node runtime in production.

**Sibling-repo imports (via bridge adapter):** folio-enrich (FolioService,
EntityRuler, reconciler, 27K+ FOLIO labels), folio-mapper.

**External ontology:** [FOLIO](https://github.com/alea-institute/FOLIO) —
fetched once and cached locally.

See [`pyproject.toml`](pyproject.toml) for pinned versions.

---

## Project Layout

```
folio-insights/
├── src/folio_insights/     # Core pipeline, config, CLI, orchestration
│   ├── pipeline/           # 4-stage batch pipeline (extract, discover, ...)
│   ├── services/           # OWL serializer, task exporter, validators
│   ├── quality/            # Confidence gate, scoring
│   └── cli.py              # `folio-insights` CLI entry point
├── api/                    # FastAPI backend for the review viewer
│   ├── routes/             # upload, processing, discovery, review, export, ...
│   ├── services/           # Backend-specific services
│   └── main.py             # FastAPI app factory + `serve()` entry
├── viewer/                 # SvelteKit review viewer
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
- **Tests must pass.** 197 tests at v1.0. Integration tests require the
  sibling repos; unit tests do not.
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

## License

MIT License — see [LICENSE](LICENSE).

Copyright © Damien Riehl and ALEA Institute.
