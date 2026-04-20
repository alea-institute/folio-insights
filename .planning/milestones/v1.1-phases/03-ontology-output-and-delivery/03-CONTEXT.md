# Phase 3: Ontology Output and Delivery - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Serialize the complete approved knowledge structure (task classes + knowledge unit individuals) as a validated, FOLIO-compatible OWL module with companion output files serving three consumption modes (SPARQL queries, LLM RAG retrieval, human browsing). Support incremental corpus growth via full regeneration with diff tracking. OWL export reads exclusively from the review database — only approved items are serialized. The extraction pipeline (Phase 1) and task discovery pipeline (Phase 2) are complete; this phase consumes their output.

</domain>

<decisions>
## Implementation Decisions

### OWL module structure
- **Everything in one OWL file** — no separate SKOS companion file. This supersedes the Phase 1/2 decision to split "core in OWL + detail in SKOS." FOLIO's canonical format is OWL, so all metadata belongs in OWL
- Single OWL file per corpus: `folio-insights.owl` containing task classes, knowledge unit individuals, object properties, annotation properties, and all metadata (confidence, source lineage, novelty scores, contradiction records)
- SKOS/PROV-O/Dublin Core/CITO vocabularies used as OWL annotation properties **within** the OWL file — standard vocabulary, single file
- Module IRI: `https://folio.openlegalstandard.org/modules/folio-insights`
- Imports FOLIO base ontology: `<owl:imports rdf:resource="https://folio.openlegalstandard.org/"/>`

### Serialization formats
- **Both RDF/XML and Turtle** — RDF/XML as primary (for Protege/WebProtege/FOLIO toolchain compatibility; folio-python's `OWLClass.to_owl_xml()` already generates this), plus Turtle (.ttl) as human-readable companion
- Files: `folio-insights.owl` (RDF/XML) + `folio-insights.ttl` (Turtle)

### OWL content richness
- Full metadata in OWL — classes + individuals + all annotation properties:
  - `rdfs:label`, `rdfs:comment` on classes
  - `folio:bestPractice`, `folio:principle`, `folio:pitfall` (advice text as annotation properties on task classes)
  - `folio:confidence` on individuals
  - `folio:noveltyScore` on individuals
  - `prov:wasDerivedFrom` (source lineage: book, chapter, section)
  - `dc:source` (source file reference)
  - Contradiction annotations where applicable

### Output location
- Per-corpus output directory alongside existing pipeline output:
  ```
  output/{corpus_name}/
    extraction.json       (Phase 1)
    review.json           (Phase 1)
    task_tree.json        (Phase 2)
    review.db             (Phases 1-2)
    folio-insights.owl    (Phase 3 - new)
    folio-insights.ttl    (Phase 3 - new)
    folio-insights.jsonld (Phase 3 - new, RAG)
    browsable/            (Phase 3 - new, HTML)
    CHANGELOG.md          (Phase 3 - new)
    validation-report.md  (Phase 3 - new)
  ```
- Per-corpus only — no auto-merge across corpora. Users merge corpora in the UI first if needed, then export

### Export trigger
- **Both CLI and UI**:
  - CLI: `folio-insights export <corpus> --format owl,ttl,jsonld,html,md --output ./export/ --approved-only` (default: approved-only=true)
  - UI: Export button on Tasks page with format checkboxes (OWL/XML, Turtle, JSON-LD, HTML, Markdown) and Download action
- Follows the sequential workflow: Upload -> Process -> Discover Tasks -> Review -> Export

### FOLIO maintainer deliverable
- Four-file package:
  - `folio-insights.owl` — the OWL module
  - `folio-insights.ttl` — human-readable Turtle version
  - `CHANGELOG.md` — structured changelog (new classes with justification, new individuals summary, reused FOLIO IRIs, custom properties defined, statistics)
  - `validation-report.md` — SHACL results + well-formedness checks

### SHACL validation
- **Core structural shapes** (practical, not pedantic):
  - Every `owl:Class` has `rdfs:label`
  - Every individual has `rdf:type`
  - No duplicate IRIs
  - No dangling references (every IRI target exists)
  - Namespace prefix consistency
  - Required annotations present: `folio:confidence` on individuals, `prov:wasDerivedFrom` on individuals
  - FOLIO IRI format matches pattern
- NOT validated (too strict): cardinality constraints, value range restrictions, closed world assumptions

### Validation pipeline
- **Post-generation, non-blocking gate**: validation runs automatically after OWL generation. If SHACL fails, export still produces the file but flags errors in `validation-report.md` and CLI output. User decides whether to fix before delivering to FOLIO maintainers
- Validation steps: SHACL shapes -> RDF well-formedness -> IRI collision check -> referential integrity -> namespace consistency

### RAG chunk design
- **Per-task JSON-LD chunks** — each chunk is a task class with all its knowledge units, subtasks, and metadata inlined. Matches core value: "discoverable by task"
- **JSONL format** — one JSON-LD object per line in `folio-insights.jsonld`. Easy to ingest into vector DBs, split, stream, or grep
- Shared `@context` defined in a separate `context.jsonld` file referenced by each line
- Typical chunk size: ~500-2000 tokens per task

### Human-browsable output
- **Both HTML site and Markdown**:
  - Static HTML site in `browsable/` directory: `index.html` with task tree navigation + per-task pages with knowledge units grouped by type, confidence badges, source references. Dark-themed to match the viewer
  - Single Markdown file: comprehensive outline format (extends existing MD export)
- Extends existing `TaskExporter` service which already generates JSON, Markdown, and HTML exports

### Incremental strategy
- **Full regeneration + diff** — every export regenerates complete OWL from ALL approved data in review.db. Changelog compares against previous export to show what changed. Previous export archived as `.owl.prev` for rollback
- No incremental patching — simpler, more reliable, no drift risk

### IRI stability
- **UUID-based with SQLite persistence** — generate IRIs via folio-python's `FOLIO.generate_iri()` (UUID4-based) on first export, persist in review.db. Re-exports reuse stored IRIs
- Edited units: new UUID + `owl:deprecated` on old IRI + `prov:wasRevisionOf` linking them
- New units: fresh UUID, stored in DB on generation
- Task class IRIs: use existing FOLIO IRIs (stable by definition)
- IRIs stable as long as review.db survives (which is already critical infrastructure)

### Export independence
- **Export reads ONLY from review.db** — `SELECT WHERE status='approved'`. Does not care about when or how data entered the database
- Clean separation: discovery pipeline handles merging/contradictions/review; export just serializes approved state
- Export is idempotent given the same database state

### Diff/changelog
- **Summary + itemized changes**: top-level stats (added/removed/changed/unchanged counts) followed by itemized lists of each change with task context
- Written to `CHANGELOG.md` alongside OWL file
- Attributes: new tasks discovered, new knowledge units added, tasks that gained subtasks, removed/rejected items, unchanged item count

### Claude's Discretion
- RDF graph construction internals (rdflib vs lxml strategy)
- SHACL shape file organization
- Exact HTML site layout and navigation patterns (extend existing dark theme)
- JSON-LD `@context` design details
- Turtle pretty-printing preferences
- Validation report formatting
- Export progress reporting (if needed for large corpora)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### FOLIO Ontology & IRI generation
- `~/Coding Projects/folio-python/folio/graph.py` — Authoritative IRI generation: `FOLIO.generate_iri()` (UUID4 -> base64 -> alphanumeric filter -> `https://folio.openlegalstandard.org/{token}`)
- `~/Coding Projects/folio-python/folio/models.py` — `OWLClass` model with `to_owl_xml()`, `to_jsonld()`, `to_json()` methods; `NSMAP` constant with owl/rdf/rdfs/skos/dc namespace prefixes; `OWLObjectProperty` model
- FOLIO GitHub (alea-institute/FOLIO) — Full ~18,000 concept ontology, canonical OWL format reference

### Existing folio-insights data models (Phase 1 & 2 output consumed by Phase 3)
- `src/folio_insights/models/knowledge_unit.py` — `KnowledgeUnit` with `folio_tags` (list of `ConceptTag`), `confidence`, `lineage` (list of `StageEvent`)
- `src/folio_insights/models/task.py` — `DiscoveredTask` with `folio_iri`, `parent_task_id`, `parent_iris` (polyhierarchy), `is_procedural`, `canonical_order`, `confidence`, `review_status`; `TaskHierarchy` container; `Contradiction` model

### Review database (source of truth for export)
- `api/db/models.py` — SQLite schema: `task_decisions` (approved tasks with folio_iri, label, hierarchy), `task_unit_links` (unit-to-task mappings), `contradictions` (resolution decisions), `review_decisions` (approved/edited unit text)
- `api/routes/review.py` — Review endpoints (query patterns for approved data)
- `api/routes/tree.py` — `_build_tree()` function (tree construction from DB)

### Existing export infrastructure (extend for OWL)
- `src/folio_insights/services/task_exporter.py` — `TaskExporter` with `export_markdown()`, `export_json()`, `export_html()` methods (extend with `export_owl()`, `export_ttl()`, `export_jsonld()`)
- `api/routes/export.py` — Export API endpoints: `GET /corpus/{id}/export/{markdown|json|html}` (extend with owl, ttl, jsonld)
- `src/folio_insights/quality/output_formatter.py` — `OutputFormatter` for JSON output (reference for serialization patterns)
- `src/folio_insights/quality/confidence_gate.py` — Confidence banding (reuse for gating which items enter OWL)

### Pipeline patterns (reference for CLI and orchestration)
- `src/folio_insights/cli.py` — Click-based CLI with `extract` and `discover` commands (extend with `export` command)
- `src/folio_insights/pipeline/orchestrator.py` — PipelineOrchestrator pattern (checkpoint, stage chaining)
- `src/folio_insights/services/bridge/folio_bridge.py` — `get_folio_service()`, `get_embedding_service()` bridge pattern

### folio-enrich integration
- `~/Coding Projects/folio-enrich/backend/app/services/folio/folio_service.py` — FolioService: `get_concept()`, hierarchy traversal, concept lookup

### Standards vocabularies (used as OWL annotation properties)
- W3C OWL — Core ontology language (classes, individuals, properties)
- W3C SKOS — `skos:broader`/`skos:narrower` (hierarchy), `skos:definition`, `skos:note`
- W3C PROV-O — `prov:wasDerivedFrom` (source lineage), `prov:wasRevisionOf` (edit history)
- Dublin Core — `dc:source` (source file reference), `dc:bibliographicCitation`
- CITO — `cito:isSupportedBy` (citation-task links)
- W3C SHACL — Shapes Constraint Language for validation

### Dependencies
- `rdflib>=7.6.0` (already in pyproject.toml) — RDF graph, SPARQL, serialization to RDF/XML, Turtle, JSON-LD
- `lxml>=5.0` (already in pyproject.toml) — XML/XPath manipulation
- `pyshacl` (to be added) — SHACL validation engine

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **folio-python OWLClass**: `to_owl_xml()` generates RDF/XML with full NSMAP; `to_jsonld()` for JSON-LD — direct reuse for OWL serialization
- **folio-python NSMAP**: Pre-configured namespace map (owl, rdf, rdfs, skos, dc) — use as base for rdflib graph
- **TaskExporter**: Already generates Markdown, JSON, HTML exports from task hierarchy — extend with OWL/TTL/JSONLD methods
- **Export API routes**: Already handle `/export/{format}` — extend with new format endpoints
- **ConfidenceGate**: Threshold-based banding — reuse for determining what enters OWL
- **review.db schema**: Already stores approved tasks, unit links, contradictions, edited text — this IS the export source
- **Click CLI pattern**: `extract` and `discover` commands — extend with `export` command following same pattern
- **rdflib** (already a dependency): Full RDF graph construction, serialization to RDF/XML, Turtle, JSON-LD, N-Triples

### Established Patterns
- **Bridge adapter**: Import folio-enrich/folio-python services as library
- **Per-corpus output**: All pipeline output goes to `{output_dir}/{corpus_name}/`
- **SQLite as source of truth**: Review decisions persist in aiosqlite; query for approved items
- **Dark-themed HTML export**: Existing HTML export uses inline CSS matching app.css variables
- **CLI → Settings → Service**: CLI args build Settings object, passed to service methods

### Integration Points
- **review.db**: Read approved tasks + units for OWL serialization
- **folio-python**: IRI generation for new individuals, OWLClass model for serialization
- **FolioService**: Concept lookup for validating FOLIO IRI references
- **TaskExporter**: Extend with new export methods
- **Export API routes**: Extend with OWL/TTL/JSONLD/SHACL endpoints
- **CLI**: New `export` subcommand
- **Tasks page UI**: Add Export button with format selection

</code_context>

<specifics>
## Specific Ideas

- "FOLIO's canonical file is OWL" — everything belongs in OWL, no separate SKOS companion file. Use SKOS vocabulary as annotation properties within the OWL file
- The sequential workflow completes: Upload -> Process -> Discover Tasks -> Review -> **Export** — this phase adds the final step
- Export is deliberately independent from the pipelines — it reads the review database and serializes whatever is approved. This clean separation means export is idempotent and doesn't need to understand pipeline internals
- IRI stability through persistence (not hashing) follows FOLIO conventions and avoids hash-input-sensitivity issues
- Full regeneration + diff is simpler and more reliable than incremental patching — the corpus isn't expected to be so large that regeneration is expensive

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-ontology-output-and-delivery*
*Context gathered: 2026-03-20*
