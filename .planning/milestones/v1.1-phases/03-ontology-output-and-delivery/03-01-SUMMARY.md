---
phase: 03-ontology-output-and-delivery
plan: 01
subsystem: export
tags: [rdflib, owl, shacl, pyshacl, jsonld, turtle, rdf, iri, validation]

# Dependency graph
requires:
  - phase: 02-task-hierarchy-discovery
    provides: approved tasks with FOLIO IRIs, unit-task links, contradictions in review.db
provides:
  - IRIManager for FOLIO-compatible IRI generation and SQLite persistence
  - OWLSerializer for rdflib-based OWL graph construction from review data
  - SHACLValidator for structural validation and markdown report generation
  - ChangelogGenerator for entity-level diff computation between exports
  - JSONLDBuilder for compact per-task RAG chunks in JSONL format
  - SHACL shapes.ttl and JSON-LD context.jsonld static assets
  - iri_registry table in DB schema for IRI stability
affects: [03-02-PLAN]

# Tech tracking
tech-stack:
  added: [pyshacl>=0.31.0]
  patterns: [rdflib graph construction with pre-bound namespaces, UUID4-base64 IRI generation, entity-level graph diffing, compact JSON-LD for RAG]

key-files:
  created:
    - src/folio_insights/services/iri_manager.py
    - src/folio_insights/services/owl_serializer.py
    - src/folio_insights/services/shacl_validator.py
    - src/folio_insights/services/changelog_generator.py
    - src/folio_insights/services/jsonld_builder.py
    - src/folio_insights/export/shapes.ttl
    - src/folio_insights/export/context.jsonld
    - src/folio_insights/export/__init__.py
    - tests/test_owl_export.py
  modified:
    - api/db/models.py
    - pyproject.toml

key-decisions:
  - "Reimplemented folio-python IRI algorithm standalone to avoid 10s ontology download on every export"
  - "rdflib serializes OWL ontologies as rdf:Description not owl:Ontology shorthand -- valid RDF/XML"
  - "Advice text (best_practice, principle, pitfall) aggregated as fi: annotation properties on task classes"
  - "IRI uniqueness check compares Class vs NamedIndividual overlap rather than subject occurrence count"
  - "Entity-level diffing for changelogs (compare IRI sets) rather than full triple-level graph subtraction"
  - "Custom compact JSON-LD chunks for RAG instead of rdflib expanded form (3x smaller)"

patterns-established:
  - "Namespace pre-binding: all g.bind() calls before any g.add() to prevent ns1: artifacts"
  - "OWL annotation properties declared explicitly as owl:AnnotationProperty for tooling compatibility"
  - "SHACL validation as post-generation non-blocking check with markdown report output"
  - "Per-task JSON-LD chunks referencing shared context.jsonld for RAG ingestion"

requirements-completed: [OWL-01, OWL-02, OWL-04, OWL-05, PIPE-01]

# Metrics
duration: 8min
completed: 2026-03-22
---

# Phase 03 Plan 01: OWL Serialization Engine Summary

**Core OWL serialization engine with rdflib graph builder, pyshacl validation, entity-level changelog diffing, and compact JSON-LD RAG chunks**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-22T22:10:39Z
- **Completed:** 2026-03-22T22:18:55Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments
- Five new Python service modules (iri_manager, owl_serializer, shacl_validator, changelog_generator, jsonld_builder) all importable and tested
- Two static export assets (shapes.ttl SHACL shapes, context.jsonld namespace map) validated
- iri_registry table added to DB schema for IRI persistence across re-exports
- pyshacl dependency added to project for SHACL validation
- 45 tests passing covering all OWL export engine components

## Task Commits

Each task was committed atomically:

1. **Task 1: IRI manager and OWL graph serializer** - `a92a13f` (test: RED), `526a86c` (feat: GREEN)
2. **Task 2: SHACL validator, changelog generator, and JSON-LD builder** - `ed9c354` (test: RED), `462f8e8` (feat: GREEN)

_TDD tasks: each has separate test and implementation commits._

## Files Created/Modified
- `src/folio_insights/services/iri_manager.py` - FOLIO IRI generation (UUID4-base64) and SQLite persistence
- `src/folio_insights/services/owl_serializer.py` - rdflib OWL graph construction from approved task/unit data
- `src/folio_insights/services/shacl_validator.py` - SHACL validation, IRI uniqueness, referential integrity checks
- `src/folio_insights/services/changelog_generator.py` - Entity-level diff and CHANGELOG.md generation
- `src/folio_insights/services/jsonld_builder.py` - Compact per-task JSON-LD chunks for RAG in JSONL format
- `src/folio_insights/export/shapes.ttl` - SHACL shape definitions (ClassShape, IndividualShape)
- `src/folio_insights/export/context.jsonld` - Shared JSON-LD @context with 9 namespace mappings
- `src/folio_insights/export/__init__.py` - Package init for export assets
- `api/db/models.py` - Added iri_registry table with entity_id and iri indexes
- `pyproject.toml` - Added pyshacl>=0.31.0 to dependencies
- `tests/test_owl_export.py` - 45 tests across 8 test classes

## Decisions Made
- Reimplemented folio-python's generate_iri() as standalone function to avoid loading the full 18K-concept ontology on every export (10+ second delay)
- Used rdflib's rdf:Description serialization (valid RDF/XML) rather than requiring owl:Ontology shorthand element
- Aggregated advice text annotations (best_practice, principle, pitfall) directly on task classes as fi: annotation properties per CONTEXT.md
- Entity-level changelog diffing (compare IRI sets) instead of full triple-level graph subtraction for performance
- Custom compact JSON-LD chunks for RAG output instead of rdflib's expanded form (keeps chunks under 2000 tokens)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed RDF/XML serialization assertion**
- **Found during:** Task 1 (OWL serializer implementation)
- **Issue:** Test expected `<owl:Ontology>` shorthand element but rdflib 7.6.0 serializes as `<rdf:Description>` with `rdf:type` triple (both valid RDF/XML)
- **Fix:** Updated test assertion to check for ontology IRI and owl#Ontology type reference instead of XML element name
- **Files modified:** tests/test_owl_export.py
- **Verification:** Test passes, serialized XML contains correct ontology declaration
- **Committed in:** 526a86c (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor test assertion adjustment for rdflib serialization format. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All five service modules ready for integration into export API routes and CLI command (Plan 03-02)
- OWLSerializer.build_graph() accepts the same data structure returned by _load_export_data() in api/routes/export.py
- SHACL shapes ready for validation pipeline integration
- JSON-LD builder ready for JSONL file generation

## Self-Check: PASSED

All 9 created files verified on disk. All 4 commit hashes verified in git log.

---
*Phase: 03-ontology-output-and-delivery*
*Completed: 2026-03-22*
