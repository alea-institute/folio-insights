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

## Notable dependencies

| Component | License |
|-----------|---------|
| pydantic, pydantic-settings, instructor, folio-python, fastapi | MIT |
| rdflib, httpx, click, lxml, aiosqlite, uvicorn | BSD |
| sentence-transformers | Apache-2.0 |
| viewer: Svelte, SvelteKit, Vite, @keenmate/svelte-treeview | MIT |
