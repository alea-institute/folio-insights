# Phase 3: Ontology Output and Delivery - Research

**Researched:** 2026-03-21
**Domain:** OWL ontology serialization, RDF tooling, SHACL validation, multi-format export
**Confidence:** HIGH

## Summary

Phase 3 serializes the approved knowledge structure from review.db into a validated, FOLIO-compatible OWL module with companion files for SPARQL, RAG, and human browsing. The core stack is already in place: rdflib 7.6.0 (installed, verified) handles all RDF graph construction and serialization to RDF/XML, Turtle, and JSON-LD natively. folio-python provides the authoritative IRI generation algorithm (`FOLIO.generate_iri()`) and `OWLClass` model with `to_owl_xml()` / `to_jsonld()` methods. The existing `TaskExporter` service and `export.py` API routes provide the extension points.

The main engineering work is: (1) building an OWL graph from approved DB state using rdflib, (2) adding pyshacl for SHACL validation, (3) generating per-task JSON-LD chunks for RAG, (4) extending the existing HTML export for browsable output, (5) adding a CLI `export` command, and (6) adding a UI export button. All patterns and infrastructure are established from Phases 1-2.

**Primary recommendation:** Use rdflib as the sole graph construction and serialization engine. Build custom JSON-LD chunks (not rdflib's expanded JSON-LD) for the RAG output. Add pyshacl 0.31.0 for SHACL validation. Extend existing TaskExporter, export API routes, and CLI.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Everything in one OWL file** -- no separate SKOS companion file. FOLIO's canonical format is OWL, so all metadata belongs in OWL. SKOS/PROV-O/Dublin Core/CITO used as annotation properties within the OWL file.
- **Both RDF/XML and Turtle** -- RDF/XML as primary (Protege/WebProtege/FOLIO toolchain compatibility), plus Turtle (.ttl) as human-readable companion
- **Full metadata in OWL** -- classes + individuals + all annotation properties (rdfs:label, rdfs:comment, folio:bestPractice, folio:confidence, folio:noveltyScore, prov:wasDerivedFrom, dc:source, contradiction annotations)
- **Module IRI**: `https://folio.openlegalstandard.org/modules/folio-insights`
- **Imports FOLIO base**: `<owl:imports rdf:resource="https://folio.openlegalstandard.org/"/>`
- **Per-corpus output directory** alongside existing pipeline output
- **Both CLI and UI export** -- CLI: `folio-insights export <corpus> --format owl,ttl,jsonld,html,md --output ./export/ --approved-only`; UI: Export button on Tasks page
- **Four-file FOLIO maintainer package**: folio-insights.owl, folio-insights.ttl, CHANGELOG.md, validation-report.md
- **Core structural SHACL shapes** (practical, not pedantic): every owl:Class has rdfs:label, every individual has rdf:type, no duplicate IRIs, no dangling references, namespace consistency, required annotations
- **Post-generation non-blocking validation** -- export still produces files if SHACL fails, flags errors in validation-report.md
- **Per-task JSON-LD chunks** in JSONL format for RAG; shared @context in separate context.jsonld
- **Both HTML site and Markdown** for human-browsable output; extends existing TaskExporter
- **Full regeneration + diff** -- every export regenerates complete OWL from ALL approved data in review.db. Previous export archived as .owl.prev
- **UUID-based IRI stability** with SQLite persistence via folio-python's `FOLIO.generate_iri()`. Edited units get new UUID + owl:deprecated + prov:wasRevisionOf
- **Export reads ONLY from review.db** -- `SELECT WHERE status='approved'`
- **Changelog**: summary + itemized changes written to CHANGELOG.md

### Claude's Discretion
- RDF graph construction internals (rdflib vs lxml strategy)
- SHACL shape file organization
- Exact HTML site layout and navigation patterns (extend existing dark theme)
- JSON-LD `@context` design details
- Turtle pretty-printing preferences
- Validation report formatting
- Export progress reporting (if needed for large corpora)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| OWL-01 | System produces valid OWL with core structural mappings compatible with FOLIO | rdflib 7.6.0 builds OWL graphs with OWL/RDFS/SKOS namespaces; folio-python OWLClass.to_owl_element() for reference; FOLIO NSMAP for namespace consistency |
| OWL-02 | System produces companion SKOS/RDFS for detailed advice (SUPERSEDED by CONTEXT: everything in one OWL file) | All metadata goes in single OWL file using SKOS/PROV-O/DC as annotation properties within OWL -- this addresses the spirit of OWL-02 within the single-file architecture |
| OWL-03 | System supports SPARQL, RAG (JSON-LD chunks), and human browsing (HTML/MD) | rdflib Graph.query() for SPARQL; custom per-task JSON-LD chunks in JSONL for RAG; extended TaskExporter HTML/MD for browsing |
| OWL-04 | FOLIO-incorporation-ready format with annotated diffs and SHACL validation | pyshacl 0.31.0 for SHACL; rdflib SH namespace for shape definitions; CHANGELOG.md for diffs; validation-report.md for results |
| OWL-05 | Generate FOLIO IRIs using folio-python's WebProtege-compatible algorithm | FOLIO.generate_iri() verified: UUID4 -> base64 -> alphanumeric filter -> `https://folio.openlegalstandard.org/{token}`; persist in SQLite for stability |
| PIPE-01 | Incremental corpus growth without reprocessing | Full regeneration from review.db + diff against previous export; new files go through pipeline (Phases 1-2) then export reads all approved data |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| rdflib | 7.6.0 | RDF graph construction, SPARQL, serialization to RDF/XML, Turtle, JSON-LD | Already installed; native OWL/RDFS/SKOS/PROV/DC namespace support; verified all 3 output formats work |
| pyshacl | 0.31.0 | SHACL validation engine | Standard Python SHACL validator; works with rdflib graphs directly; latest stable version |
| folio-python | >=0.1.5 | IRI generation, OWLClass model, NSMAP constants | Already a dependency; `FOLIO.generate_iri()` is the authoritative IRI algorithm |
| lxml | >=5.0 | XML manipulation (used by folio-python internally) | Already installed; used by folio-python's `OWLClass.to_owl_element()` |
| aiosqlite | >=0.20.0 | Async SQLite access to review.db | Already installed; established pattern from Phases 1-2 |
| click | >=8.0.0 | CLI framework | Already installed; existing `extract` and `discover` commands to extend |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rdflib SH namespace | built-in | SHACL shape graph construction | When defining validation shapes |
| rdflib PROV namespace | built-in | Provenance annotations | For prov:wasDerivedFrom, prov:wasRevisionOf |
| json (stdlib) | built-in | JSON-LD chunk serialization | For JSONL RAG output (custom, not rdflib's expanded form) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| rdflib for RDF/XML | folio-python lxml directly | rdflib handles complete graph; lxml only handles individual class elements. Use rdflib for full ontology, reference folio-python NSMAP for namespace consistency |
| pyshacl for validation | Custom XML/RDF validation | pyshacl is the standard; don't hand-roll SHACL interpretation |
| rdflib JSON-LD serialization | Custom JSON-LD per task | rdflib outputs expanded JSON-LD (full IRIs, verbose). Custom JSON-LD with compact @context is better for RAG chunks |

**Installation:**
```bash
pip install pyshacl>=0.31.0
```

**Version verification:** rdflib 7.6.0 confirmed installed. pyshacl 0.31.0 is latest on PyPI (needs installation).

## Architecture Patterns

### Recommended Project Structure
```
src/folio_insights/
  services/
    task_exporter.py         # EXTEND: add export_owl(), export_ttl(), export_jsonld()
    owl_serializer.py        # NEW: rdflib graph builder from DB data
    shacl_validator.py       # NEW: SHACL shape definitions + validation
    changelog_generator.py   # NEW: diff computation + CHANGELOG.md generation
    iri_manager.py           # NEW: IRI persistence in SQLite, generation via folio-python
  export/
    context.jsonld           # NEW: shared JSON-LD @context file
    shapes.ttl               # NEW: SHACL shape definitions (static)
api/routes/
  export.py                  # EXTEND: add owl, ttl, jsonld, validation endpoints
viewer/src/
  lib/components/
    ExportDialog.svelte      # NEW: format selection dialog
  routes/tasks/
    +page.svelte             # EXTEND: add Export button
```

### Pattern 1: RDF Graph Construction from Database
**What:** Build a complete rdflib Graph by querying review.db for approved tasks and units, then serialize to multiple formats.
**When to use:** Every export operation.
**Example:**
```python
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL, SKOS, DC, PROV, XSD

FOLIO = Namespace("https://folio.openlegalstandard.org/")
FOLIO_INSIGHTS = Namespace("https://folio.openlegalstandard.org/modules/folio-insights/")

def build_owl_graph(tasks: list[dict], units_by_task: dict, metadata: dict) -> Graph:
    g = Graph()
    g.bind("folio", FOLIO)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("skos", SKOS)
    g.bind("dc", DC)
    g.bind("prov", PROV)

    # Ontology declaration
    ont = URIRef("https://folio.openlegalstandard.org/modules/folio-insights")
    g.add((ont, RDF.type, OWL.Ontology))
    g.add((ont, OWL.imports, URIRef("https://folio.openlegalstandard.org/")))
    g.add((ont, RDFS.label, Literal("FOLIO Insights Module")))

    # Task classes
    for task in tasks:
        task_iri = URIRef(task["folio_iri"])
        g.add((task_iri, RDF.type, OWL.Class))
        g.add((task_iri, RDFS.label, Literal(task["label"])))
        if task.get("parent_task_id"):
            parent = find_parent_iri(tasks, task["parent_task_id"])
            if parent:
                g.add((task_iri, RDFS.subClassOf, URIRef(parent)))

    # Knowledge unit individuals
    for task_id, units in units_by_task.items():
        for unit in units:
            unit_iri = URIRef(get_or_create_iri(unit["id"]))
            g.add((unit_iri, RDF.type, OWL.NamedIndividual))
            g.add((unit_iri, RDFS.label, Literal(unit["text"][:100])))
            # ... annotations

    return g
```

### Pattern 2: IRI Persistence in SQLite
**What:** Store generated IRIs in review.db keyed by entity ID so re-exports produce identical IRIs.
**When to use:** First export generates IRIs; subsequent exports reuse them.
**Example:**
```sql
-- New table in review.db
CREATE TABLE IF NOT EXISTS iri_registry (
    entity_id TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,  -- 'task' or 'unit'
    iri TEXT NOT NULL UNIQUE,
    corpus_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    deprecated_at TEXT,
    superseded_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_iri_entity ON iri_registry(entity_id);
CREATE INDEX IF NOT EXISTS idx_iri_iri ON iri_registry(iri);
```

### Pattern 3: SHACL Validation with pyshacl
**What:** Define shapes as a Turtle graph, validate the data graph with pyshacl, capture results.
**When to use:** Post-generation validation step.
**Example:**
```python
import pyshacl
from rdflib import Graph

def validate_owl(data_graph: Graph, shapes_graph: Graph) -> tuple[bool, Graph, str]:
    conforms, results_graph, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes_graph,
        inference="none",
        abort_on_first=False,
    )
    return conforms, results_graph, results_text
```

### Pattern 4: Extending Existing Export Infrastructure
**What:** Add new methods to TaskExporter and new routes to export.py following existing patterns.
**When to use:** All new export formats.
**Example:**
```python
# In TaskExporter -- new methods
def export_owl(self, tasks, units_by_task, metadata) -> str:
    """Serialize to RDF/XML."""
    graph = build_owl_graph(tasks, units_by_task, metadata)
    return graph.serialize(format="xml")

def export_ttl(self, tasks, units_by_task, metadata) -> str:
    """Serialize to Turtle."""
    graph = build_owl_graph(tasks, units_by_task, metadata)
    return graph.serialize(format="turtle")

# In export.py -- new routes
@router.get("/corpus/{corpus_id}/export/owl")
async def export_owl_endpoint(corpus_id: str):
    ...
```

### Pattern 5: Full Regeneration with Diff
**What:** On each export, regenerate everything from DB. Archive previous output. Compare and generate changelog.
**When to use:** Every export operation.
**Example:**
```python
def export_with_diff(output_dir: Path, corpus_name: str, graph: Graph):
    owl_path = output_dir / corpus_name / "folio-insights.owl"

    # Archive previous if exists
    if owl_path.exists():
        prev_path = owl_path.with_suffix(".owl.prev")
        shutil.copy2(owl_path, prev_path)

    # Write new
    owl_content = graph.serialize(format="xml")
    owl_path.write_text(owl_content)

    # Generate diff
    if prev_path.exists():
        prev_graph = Graph().parse(str(prev_path), format="xml")
        added = graph - prev_graph  # rdflib supports graph subtraction
        removed = prev_graph - graph
        changelog = generate_changelog(added, removed)
```

### Anti-Patterns to Avoid
- **Building OWL XML manually with lxml**: Use rdflib for the complete graph. folio-python's `to_owl_element()` is for individual class serialization within its own context; rdflib handles the full ontology with all namespaces correctly.
- **Using rdflib's JSON-LD for RAG chunks**: rdflib outputs expanded JSON-LD with full IRIs (verbose, ~3x larger). Build custom compact JSON-LD objects per task for efficient RAG ingestion.
- **Generating IRIs on every export**: IRIs must be stable across exports. Generate once, persist in SQLite, reuse on subsequent exports.
- **Blocking export on validation failure**: Validation is non-blocking. Export always produces files; validation results go to validation-report.md.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| RDF graph construction | Custom XML builder | rdflib Graph | rdflib handles namespace management, blank nodes, literal types, serialization to 3+ formats correctly |
| SHACL validation | Custom constraint checking | pyshacl | SHACL is a W3C standard with edge cases; pyshacl handles the full spec |
| IRI generation | Custom UUID-to-IRI algorithm | folio-python FOLIO.generate_iri() | Must match WebProtege's algorithm exactly for FOLIO compatibility |
| RDF/XML serialization | lxml ElementTree construction | rdflib Graph.serialize(format="xml") | Correct namespace declarations, entity handling, encoding |
| Turtle serialization | String formatting | rdflib Graph.serialize(format="turtle") | Prefix declarations, blank node serialization, escaping |
| Graph diff | Manual triple comparison | rdflib graph subtraction (g1 - g2) | rdflib supports set operations on graphs natively |

**Key insight:** rdflib is the Swiss Army knife here. It handles graph construction, SPARQL, all serialization formats, namespace management, and even graph set operations (diff). The only thing to build custom is the JSON-LD RAG chunks (because rdflib's JSON-LD is expanded form, not the compact per-task chunks needed for RAG).

## Common Pitfalls

### Pitfall 1: Namespace Prefix Collisions
**What goes wrong:** rdflib auto-generates namespace prefixes (ns1, ns2) if you don't bind them before adding triples.
**Why it happens:** Namespace binding order matters in rdflib; bindings after triples may not take effect for serialization.
**How to avoid:** Always call `g.bind()` for all namespaces immediately after creating the Graph, before adding any triples.
**Warning signs:** `ns1:` or `ns2:` prefixes appearing in Turtle output.

### Pitfall 2: JSON-LD Expanded vs Compact Form
**What goes wrong:** rdflib's `format="json-ld"` outputs expanded JSON-LD with full IRIs (`http://www.w3.org/2002/07/owl#Class` instead of `owl:Class`), making chunks 3x larger than needed for RAG.
**Why it happens:** rdflib serializes to expanded form by default; compaction requires a context document.
**How to avoid:** Build custom JSON-LD dicts per task using compact prefixed names and a shared `@context` reference, similar to folio-python's `OWLClass.to_jsonld()` pattern. Don't use rdflib for the JSONL output.
**Warning signs:** JSON-LD chunks > 5KB per task; full IRI strings everywhere.

### Pitfall 3: IRI Format Mismatch with FOLIO
**What goes wrong:** Generated IRIs don't match FOLIO's WebProtege format, causing merge conflicts.
**Why it happens:** Custom IRI generation algorithms differ subtly from FOLIO's UUID4->base64->alphanumeric filter.
**How to avoid:** Always use `FOLIO.generate_iri()` from folio-python. Never invent custom IRI generation.
**Warning signs:** IRIs with non-alphanumeric characters, wrong prefix, or wrong length.

### Pitfall 4: Circular Imports in Export Routes
**What goes wrong:** Importing from `api.main` at module level causes circular dependency.
**Why it happens:** Export routes need `get_db_for_corpus()` from main, but main imports the router.
**How to avoid:** Use the established pattern: lazy imports inside functions (`from api.main import ...`), same as existing `export.py`.
**Warning signs:** `ImportError: cannot import name` at startup.

### Pitfall 5: Missing Approved-Only Filter
**What goes wrong:** Export includes unreviewed or rejected items.
**Why it happens:** Forgetting the `WHERE status='approved'` filter on DB queries.
**How to avoid:** Export data loading function must always filter by approved status. Default `--approved-only=true` on CLI.
**Warning signs:** OWL output contains more items than expected; rejected items appear.

### Pitfall 6: rdflib Graph Subtraction Performance
**What goes wrong:** Diff computation (`g1 - g2`) is slow for large graphs.
**Why it happens:** rdflib graph subtraction iterates all triples.
**How to avoid:** For the diff, don't diff the entire serialized output. Instead, diff at the entity level: compare sets of task IRIs and unit IRIs between old and new exports. Use rdflib graph subtraction only if entity-level diff shows changes.
**Warning signs:** Export taking > 30 seconds for moderate corpus sizes.

### Pitfall 7: folio-python FOLIO Class Initialization
**What goes wrong:** `FOLIO()` constructor downloads the full ontology from GitHub on first use (slow, requires network).
**Why it happens:** FOLIO class auto-loads the ontology in `__init__`.
**How to avoid:** For IRI generation only, we don't need the full ontology. Extract the `generate_iri` algorithm as a standalone function, or use the FOLIO class with caching enabled (default). The `generate_iri` method is a `self` method but only uses `self.iri_to_index` for uniqueness checking -- for our use case, check uniqueness against our SQLite iri_registry instead.
**Warning signs:** Export hanging for 10+ seconds on first run.

## Code Examples

### Building the OWL Graph
```python
# Source: verified with rdflib 7.6.0 installed in this project
from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL, SKOS, DC, XSD, PROV

FOLIO = Namespace("https://folio.openlegalstandard.org/")

# Custom annotation properties for folio-insights
FOLIO_INSIGHTS = Namespace("https://folio.openlegalstandard.org/modules/folio-insights/")

def create_base_graph() -> Graph:
    g = Graph()
    # Bind ALL namespaces before adding triples
    g.bind("folio", FOLIO)
    g.bind("owl", OWL)
    g.bind("rdf", RDF)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)
    g.bind("skos", SKOS)
    g.bind("dc", DC)
    g.bind("prov", PROV)
    g.bind("fi", FOLIO_INSIGHTS)

    # Ontology declaration
    ont_iri = URIRef("https://folio.openlegalstandard.org/modules/folio-insights")
    g.add((ont_iri, RDF.type, OWL.Ontology))
    g.add((ont_iri, OWL.imports, URIRef("https://folio.openlegalstandard.org/")))
    g.add((ont_iri, RDFS.label, Literal("FOLIO Insights Module")))
    g.add((ont_iri, DC.description, Literal("Legal advocacy knowledge extracted and structured by folio-insights")))

    return g
```

### IRI Generation with Persistence
```python
# Source: folio-python/folio/graph.py FOLIO.generate_iri() algorithm
import base64
import uuid

def generate_folio_iri(existing_iris: set[str]) -> str:
    """Generate a FOLIO-compatible IRI (WebProtege algorithm).

    Reimplements FOLIO.generate_iri() without requiring full ontology load.
    """
    for _ in range(16):
        base_value = uuid.uuid4()
        base64_value = "".join(
            c for c in base64.urlsafe_b64encode(base_value.bytes)
            .decode("utf-8").rstrip("=")
            if c.isalnum()
        )
        iri = f"https://folio.openlegalstandard.org/{base64_value}"
        if iri not in existing_iris:
            return iri
    raise RuntimeError("Failed to generate a unique IRI.")
```

### SHACL Shape Definition
```turtle
# shapes.ttl -- Core structural shapes for folio-insights OWL validation
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix folio: <https://folio.openlegalstandard.org/> .
@prefix fi: <https://folio.openlegalstandard.org/modules/folio-insights/> .

fi:ClassShape a sh:NodeShape ;
    sh:targetClass owl:Class ;
    sh:property [
        sh:path rdfs:label ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "Every owl:Class must have at least one rdfs:label"
    ] .

fi:IndividualShape a sh:NodeShape ;
    sh:targetClass owl:NamedIndividual ;
    sh:property [
        sh:path rdf:type ;
        sh:minCount 1 ;
        sh:message "Every individual must have rdf:type"
    ] ;
    sh:property [
        sh:path prov:wasDerivedFrom ;
        sh:minCount 1 ;
        sh:message "Every individual must have prov:wasDerivedFrom (source lineage)"
    ] .
```

### Per-Task JSON-LD RAG Chunk
```python
# Custom JSON-LD chunk builder (NOT rdflib -- compact form for RAG)
import json

JSONLD_CONTEXT = {
    "folio": "https://folio.openlegalstandard.org/",
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "prov": "http://www.w3.org/ns/prov#",
    "fi": "https://folio.openlegalstandard.org/modules/folio-insights/",
}

def build_task_chunk(task: dict, units: list[dict]) -> dict:
    """Build a compact JSON-LD chunk for a single task and its units."""
    chunk = {
        "@context": "./context.jsonld",
        "@id": task["folio_iri"],
        "@type": "owl:Class",
        "rdfs:label": task["label"],
        "fi:isProcedural": task.get("is_procedural", False),
        "fi:units": [
            {
                "@type": "owl:NamedIndividual",
                "rdfs:label": u.get("text", "")[:100],
                "skos:note": u.get("text", ""),
                "fi:unitType": u.get("unit_type", "unknown"),
                "fi:confidence": u.get("confidence", 0),
                "dc:source": u.get("source_file", ""),
            }
            for u in units
        ],
    }
    if task.get("parent_task_id"):
        chunk["rdfs:subClassOf"] = {"@id": find_parent_iri(task)}
    return chunk

def write_jsonl(chunks: list[dict], output_path: Path):
    """Write one JSON-LD object per line."""
    with open(output_path, "w") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, separators=(",", ":")) + "\n")
```

### CLI Export Command
```python
# Extends existing Click CLI pattern from cli.py
@cli.command("export")
@click.argument("corpus_name")
@click.option("--output", "-o", default="./output", type=click.Path(resolve_path=True))
@click.option("--format", "-f", default="owl,ttl,jsonld,html,md", help="Comma-separated formats")
@click.option("--approved-only/--all", default=True)
@click.option("--verbose", "-v", is_flag=True)
def export(corpus_name, output, format, approved_only, verbose):
    """Export approved knowledge as OWL ontology and companion files."""
    ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Custom XML for OWL | rdflib Graph.serialize(format="xml") | rdflib 6.0+ | No need to manually construct XML; rdflib handles all serialization |
| Separate SKOS files | Everything in single OWL with SKOS annotations | CONTEXT.md decision | Single file simplifies delivery and FOLIO integration |
| Incremental RDF patching | Full regeneration + diff | CONTEXT.md decision | Simpler, no drift risk, acceptable performance for expected corpus size |
| rdflib 6.x JSON-LD | rdflib 7.6.0 native JSON-LD | rdflib 7.0 | JSON-LD no longer requires separate json-ld extra package |

**Deprecated/outdated:**
- `rdflib-jsonld` package: merged into rdflib core in 7.0. Do not install separately.
- folio-python's `OWLClass.to_owl_xml()` for full ontology: use for reference, but rdflib handles complete ontology serialization better.

## Open Questions

1. **folio-python FOLIO class initialization cost**
   - What we know: `FOLIO()` constructor downloads the full ontology (~18K concepts) from GitHub. The `generate_iri()` method checks `self.iri_to_index` for uniqueness.
   - What's unclear: Whether we need to instantiate the full FOLIO class or can extract the IRI generation algorithm standalone.
   - Recommendation: Reimplement `generate_iri()` as a standalone function that checks uniqueness against our SQLite iri_registry. This avoids the 10-second ontology download on every export. The algorithm is simple (UUID4 -> base64 -> alphanumeric filter) and documented in graph.py lines 2137-2168.

2. **Review status filtering for export**
   - What we know: The CONTEXT says "SELECT WHERE status='approved'". The task_decisions table has a status column.
   - What's unclear: Whether review_decisions (unit-level) status should also gate inclusion. Units linked to approved tasks may themselves be unreviewed.
   - Recommendation: Export approved tasks from task_decisions. For units linked to approved tasks, include all linked units regardless of unit review status (the task approval implies the associated units are acceptable).

3. **Custom annotation properties**
   - What we know: CONTEXT specifies `folio:bestPractice`, `folio:principle`, `folio:pitfall`, `folio:confidence`, `folio:noveltyScore` as annotation properties.
   - What's unclear: Whether these should use the FOLIO namespace or a folio-insights module namespace.
   - Recommendation: Use a folio-insights module namespace (`fi:`) for custom properties not in FOLIO's canonical vocabulary. Declare them as `owl:AnnotationProperty` in the ontology.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ with pytest-asyncio |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `pytest tests/ -x --timeout=30` |
| Full suite command | `pytest tests/ --timeout=60` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OWL-01 | OWL graph produces valid RDF/XML with classes and properties | unit | `pytest tests/test_owl_export.py::test_valid_owl_output -x` | Wave 0 |
| OWL-02 | Single OWL file contains SKOS/PROV annotations | unit | `pytest tests/test_owl_export.py::test_annotations_in_owl -x` | Wave 0 |
| OWL-03 | SPARQL queries return results; JSON-LD chunks valid; HTML renders | unit | `pytest tests/test_owl_export.py::test_consumption_modes -x` | Wave 0 |
| OWL-04 | SHACL validation runs and produces report | unit | `pytest tests/test_owl_export.py::test_shacl_validation -x` | Wave 0 |
| OWL-05 | IRIs match FOLIO format and persist across exports | unit | `pytest tests/test_owl_export.py::test_iri_generation_and_persistence -x` | Wave 0 |
| PIPE-01 | Re-export after adding new source produces diff | integration | `pytest tests/test_owl_export.py::test_incremental_export -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_owl_export.py -x --timeout=30`
- **Per wave merge:** `pytest tests/ --timeout=60`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_owl_export.py` -- covers OWL-01 through OWL-05, PIPE-01
- [ ] `tests/test_export_api.py` -- covers export API endpoints (OWL/TTL/JSONLD)
- [ ] pyshacl installation: `pip install pyshacl>=0.31.0`

## Sources

### Primary (HIGH confidence)
- rdflib 7.6.0 installed and verified in project: supports RDF/XML, Turtle, JSON-LD serialization; built-in OWL/RDFS/SKOS/PROV/DC/SH namespaces
- folio-python `folio/graph.py` lines 2137-2168: `FOLIO.generate_iri()` algorithm (UUID4 -> base64 -> alphanumeric filter)
- folio-python `folio/models.py`: `OWLClass` model, `NSMAP` constant, `to_owl_xml()`, `to_jsonld()` methods
- Existing project code: `task_exporter.py`, `export.py`, `cli.py`, `models.py` -- verified extension points

### Secondary (MEDIUM confidence)
- pyshacl 0.31.0 on PyPI: latest stable version, rdflib-compatible SHACL validator
- rdflib SH namespace verified: `http://www.w3.org/ns/shacl#` with NodeShape, property, path, minCount, etc.

### Tertiary (LOW confidence)
- None -- all findings verified against installed software and existing code

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- rdflib installed and serialization verified; folio-python code reviewed; pyshacl version confirmed on PyPI
- Architecture: HIGH -- extends established patterns (TaskExporter, export.py, cli.py); all extension points verified in code
- Pitfalls: HIGH -- derived from direct testing of rdflib behavior and code review of folio-python

**Research date:** 2026-03-21
**Valid until:** 2026-04-21 (stable libraries, locked decisions)
