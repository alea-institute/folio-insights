---
phase: 08-folio-v2-vocab-mini-bfo-spine-7
verified: 2026-05-31T00:00:00Z
status: passed
score: 25/25
overrides_applied: 0
---

# Phase 8: FOLIO v2 Vocab + Mini-BFO Spine — Verification Report

**Phase Goal:** Ship the FOLIO v2 TTL vocabulary (`fi:*` predicates) and mini-BFO spine with version-pinning enforcement.
**Verified:** 2026-05-31
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | FOLIO v2 TTL parses with both rdflib and pyoxigraph; `owl:versionIRI` stable | VERIFIED | `load_graph()` returns 454 triples; `load_pyoxigraph_store()` returns 5 ontology rows; all 5 TTL files carry `2026.05.0` in `owl:versionIRI` (confirmed by `test_owl_version_iri.py` + direct check) |
| 2 | `fi:vocabVersion` SHACL shape enforces pin on every shard — unpinned shards rejected | VERIFIED | `fi:VocabPinShape` is a `sh:NodeShape` targeting `fi:Shard` with `sh:hasValue "2026.05.0"`; `ShardEnvelope.field_validator("vocab_version")` rejects any mismatch at construction (Pydantic belt verified); both belts present |
| 3 | All 4 analogia predicates + 4 distinction kinds queryable; Tractarian/Spinozan/Russellian/Carnap/Aristotelian predicates round-trip | VERIFIED | `fi:primeAnalogate`, `fi:proportionalRelation`, `fi:distinguishes`, `fi:distinctionKind` all present in vocab graph; 4 distinction kinds (`realis`, `rationis`, `rationis_cum_fundamento_in_re`, `analogica`) in `fi:DistinctionKindEnumShape` sh:in; `fi:elaborates`, `fi:dependsOnAxiom`, `fi:dependsOnDefinition`, `fi:closureMarker`, `fi:predicationMode` all present; `test_pyoxigraph_roundtrip.py` parameterized over all 9 predicates passes (59/59 vocab tests green) |
| 4 | Mini-BFO classes (9-class spine per D-06) present with `owl:equivalentClass` mappings to BFO 2020 in companion `bfo_mapping.ttl` | VERIFIED | All 9 classes confirmed: `Continuant`, `Occurrent`, `IndependentContinuant`, `SpecificallyDependentContinuant`, `GenericallyDependentContinuant`, `Role`, `Quality`, `Disposition`, `Process` declared as `owl:Class`; each maps to `obo/BFO_xxxxxxx` via `owl:equivalentClass` (not `rdfs:seeAlso`); D-06 divergence documented (drops PRD §7.2 `fi:Event`, adds SDC/GDC/Quality/Disposition) |
| 5 | Supersession predicates (`fi:supersedes`, `fi:supersededBy`) distinct from retraction; as-of query returns superseded shard | VERIFIED | Both predicates carry mutual `owl:inverseOf`; `fi:Retraction` is a distinct `owl:Class` with 4 triples in vocab graph; `query_as_of(graph, pred, date(2026,3,15))` returns link 3 shard binding (not empty, not latest), `date(2025,12,15)` returns empty — superseded shards recoverable at historical dates |

**Score:** 5/5 truths verified

---

### Per-Decision Evidence (D-01 through D-12)

| Decision | Claim | Status | Evidence |
|----------|-------|--------|----------|
| D-01 | Canonical IRI `https://folio-insights.aleainstitute.ai/vocab/` everywhere in new vocab | VERIFIED | All 5 TTL files use `@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/>` (confirmed by smoke test `test_each_ttl_uses_canonical_fi_prefix` — 5 parameterized PASS); `FI_PREFIX` constant matches |
| D-01a | Sacred upstream FOLIO IRIs (`https://folio.openlegalstandard.org/`) UNTOUCHED in `services/owl_serializer.py:17` | VERIFIED | `owl_serializer.py` carries 5 occurrences of `https://folio.openlegalstandard.org/` (unchanged); smoke test `test_owl_serializer_canonical_folio_iri_untouched` PASS |
| D-01b | v1-legacy prefix marker comments atop `services/owl_serializer.py` and `export/shapes.ttl` | VERIFIED | `owl_serializer.py` lines 11-20: `# v1-legacy — DO NOT migrate to v2 prefix (Phase 8 D-01b).`; `export/shapes.ttl` line 1: `# v1-legacy — DO NOT migrate to v2 prefix (Phase 8 D-01b).`; smoke tests `test_owl_serializer_has_v1_legacy_marker` and `test_export_shapes_has_v1_legacy_marker` PASS |
| D-02 | `VOCAB_VERSION = "2026.05.0"` is a module constant on `folio_insights.vocab` | VERIFIED | `src/folio_insights/vocab/__init__.py` line 54: `VOCAB_VERSION: str = "2026.05.0"` |
| D-03 | `ShardEnvelope.vocab_version` has a `field_validator` that refuses mismatched values | VERIFIED | `envelope.py` line 346: `@field_validator("vocab_version")`; raises `ValueError` if `v != VOCAB_VERSION`; 4 `vocab_version` occurrences in envelope source; import `from folio_insights.vocab import VOCAB_VERSION` at line 43 |
| D-04 | `fi:VocabPinShape` SHACL shape exists in `vocab/shapes.ttl` | VERIFIED | Lines 42-51 of `shapes.ttl`: `fi:VocabPinShape a sh:NodeShape ; sh:targetClass fi:Shard ; sh:property [ sh:hasValue "2026.05.0" ; ... ]` |
| D-05 | Every `*.ttl` carries an `owl:versionIRI` containing `2026.05.0` | VERIFIED | All 5 files confirmed: `predicates.ttl`, `classes.ttl`, `bfo_spine.ttl`, `bfo_mapping.ttl`, `shapes.ttl` — each `owl:versionIRI` follows pattern `https://folio-insights.aleainstitute.ai/vocab/2026.05.0/{name}` |
| D-06 | 9-class mini-BFO spine — exact class list (drops PRD §7.2 fi:Event, adds SDC/GDC/Quality/Disposition) | VERIFIED | `bfo_spine.ttl` declares exactly 9 classes; D-06 divergence documented in file header and `rdfs:comment` on `fi:Occurrent`; no `fi:Event` present |
| D-07 | `bfo_mapping.ttl` uses `owl:equivalentClass` (NOT `rdfs:seeAlso`) for every mini-BFO class | VERIFIED | All 9 rows use `owl:equivalentClass`; file header comment explicitly states "No rdfs:seeAlso shortcuts"; verified programmatically — 9/9 equivalentClass mappings found |
| D-08 | TTL split into 5 files under `src/folio_insights/vocab/` | VERIFIED | `predicates.ttl`, `classes.ttl`, `bfo_spine.ttl`, `bfo_mapping.ttl`, `shapes.ttl` all present in `src/folio_insights/vocab/` |
| D-09 | Loaders use `importlib.resources` | VERIFIED | `vocab/__init__.py` lines 103/120: `pkg = files("folio_insights.vocab")` — uses `importlib.resources.files()` for both `load_graph()` and `load_pyoxigraph_store()` |
| D-10 | `temporal/as_of.py` exports `query_as_of(graph, predicate, at_date) -> list[Row]` and is pure rdflib | VERIFIED | Import lines: `from rdflib import ...`, `from rdflib.namespace import XSD` — only rdflib + stdlib; no `import pyoxigraph`, `oxrdflib`, or `pyshacl` at import level; `initBindings` used (not f-string); dep-leak tests 7/7 PASS |
| D-11 | `--as-of` CLI is NOT added in Phase 8 (deferred to Phase 11/12) | VERIFIED | No CLI argument registered in Phase 8 artifacts; `docs/query-as-of.md` section "CLI / UI surface (deferred)" explicitly cross-references Phase 11 and Phase 12; D-11 comment in `as_of.py` module docstring |
| D-12 | Drift audit ran (`08-DRIFT-AUDIT.md` exists) and 4 named suspects documented | VERIFIED | `08-DRIFT-AUDIT.md` present; all 4 named suspects (`fi:hasRole`, `fi:signedAction`, `fi:GovernanceLog`, `fi:supersedes`/`fi:supersededBy`) documented with PASS verdicts; 2 in-scope atomic fixes applied (`d5bc180`, `4dee874`); 11 waivers documented |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/folio_insights/vocab/__init__.py` | VOCAB_VERSION constant, FI_PREFIX, NAMESPACES, load_graph, load_pyoxigraph_store | VERIFIED | All 5 exports present; uses `importlib.resources.files` |
| `src/folio_insights/vocab/predicates.ttl` | PRD §7.1 fi:* properties including fi:supersedes | VERIFIED | 418 lines; all required predicates + 26 Phase 2-7 drift-fix predicates |
| `src/folio_insights/vocab/classes.ttl` | Non-BFO classes + fi:GovernanceLog | VERIFIED | fi:GovernanceLog at line 112; all 13 governance target classes present |
| `src/folio_insights/vocab/bfo_spine.ttl` | 9-class mini-BFO spine including fi:SpecificallyDependentContinuant | VERIFIED | All 9 classes with rdfs:subClassOf hierarchy |
| `src/folio_insights/vocab/bfo_mapping.ttl` | owl:equivalentClass to BFO 2020 | VERIFIED | 9 rows with `obo/BFO_xxxxxxx` IRIs; no rdfs:seeAlso |
| `src/folio_insights/vocab/shapes.ttl` | fi:VocabPinShape + fi:SupersessionAlignmentShape | VERIFIED | VocabPinShape (D-04), SignedActionEnumShape (D-12), RoleEnumShape (D-12), DistinctionKindEnumShape (VOCAB-02), SupersessionAlignmentShape (D-10) all present |
| `src/folio_insights/temporal/as_of.py` | query_as_of function, pure rdflib | VERIFIED | `def query_as_of` exported; rdflib-only imports at module level |
| `src/folio_insights/shards/envelope.py` | vocab_version field + field_validator | VERIFIED | field_validator at line 346; 4 vocab_version occurrences |
| `src/folio_insights/bench/generator.py` | per-shard fi:vocabVersion emission + VOCAB_VERSION import | VERIFIED | 2 VOCAB_VERSION references (import + emit); 3 vocabVersion references |
| `docs/query-as-of.md` | SPARQL pattern + Python example + Phase 11/12 deferral cross-reference | VERIFIED | 108 lines; SPARQL block present; D-11 deferral section present; fi:supersedes, fi:validTimeStart, fi:validTimeEnd referenced |
| `.planning/phases/08-folio-v2-vocab-mini-bfo-spine-7/08-DRIFT-AUDIT.md` | 4 named suspects audited + per-predicate table | VERIFIED | All 4 suspects PASS; full predicate table (67 emitted, 95 declared after fixes); 2 fix commits listed |
| `tests/vocab/test_vocab_load_smoke.py` | rdflib + pyoxigraph parse smoke + owl:versionIRI assertions | VERIFIED | 33+ parameterized cases; all 59 vocab tests green |
| `tests/vocab/test_envelope_vocab_pin.py` | Construction-time pin assertion | VERIFIED | File present |
| `tests/vocab/test_bench_emits_vocab_version.py` | per-shard fi:vocabVersion emission assertion | VERIFIED | File present |
| `tests/vocab/test_predicate_drift_audit.py` | Drift cross-check + 4 D-12 suspect tests | VERIFIED | File present; 5+ tests |
| `tests/vocab/test_pyoxigraph_roundtrip.py` | rdflib/pyoxigraph parity + 9 VOCAB-02/03 predicates | VERIFIED | File present; parameterized |
| `tests/vocab/test_owl_version_iri.py` | owl:versionIRI per file assertion | VERIFIED | File present |
| `tests/temporal/test_query_as_of.py` | 5 timepoint tests | VERIFIED | 7 tests pass (5 timepoints + 2 edge cases) |
| `tests/temporal/test_dep_leak_guard.py` | FORBIDDEN import guard | VERIFIED | 7 parameterized PASS |
| `tests/temporal/test_supersession_alignment_shape.py` | Both-polarity SHACL test | VERIFIED | 2 tests PASS (conforms=True + conforms=False) |
| `tests/temporal/fixtures/supersession_chain.ttl` | 10-link supersession chain fixture | VERIFIED | File present; fi:supersedes + fi:validTimeStart + fi:validTimeEnd chains verified |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/folio_insights/vocab/__init__.py` | `src/folio_insights/vocab/*.ttl` | `importlib.resources.files` | WIRED | `pkg = files("folio_insights.vocab")` used in both loaders |
| `src/folio_insights/vocab/bfo_mapping.ttl` | BFO 2020 PURLs | `owl:equivalentClass` | WIRED | 9 `obo/BFO_xxxxxxx` IRIs present |
| `src/folio_insights/shards/envelope.py` | `folio_insights.vocab.VOCAB_VERSION` | `from folio_insights.vocab import VOCAB_VERSION` | WIRED | Line 43 of envelope.py |
| `src/folio_insights/bench/generator.py` | `folio_insights.vocab.VOCAB_VERSION` | `from folio_insights.vocab import VOCAB_VERSION` | WIRED | Line 52 of generator.py; `Literal(VOCAB_VERSION)` emitted per shard |
| `src/folio_insights/temporal/as_of.py` | rdflib.Graph SPARQL | `graph.query(_AS_OF_SELECT, initBindings={...})` | WIRED | SPARQL bound via initBindings; returns list of (subject, object) tuples |
| `src/folio_insights/vocab/shapes.ttl` | `fi:supersedes` / `fi:validTimeStart` / `fi:validTimeEnd` | `sh:sparql` constraint | WIRED | `fi:SupersessionAlignmentShape` SELECT references all 3 predicates |

---

### Data-Flow Trace (Level 4)

Not applicable to TTL vocabulary files (static data, not dynamic rendering). Verified instead via behavioral spot-checks.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| rdflib parses all 5 TTL files | `load_graph(include_bfo_mapping=True)` | 454 triples, non-zero | PASS |
| pyoxigraph parses all 5 TTL files | `load_pyoxigraph_store()` | 5 ontology rows | PASS |
| `VOCAB_VERSION` constant correct | assertion in Python | `"2026.05.0"` | PASS |
| `FI_PREFIX` constant correct | assertion in Python | `"https://folio-insights.aleainstitute.ai/vocab/"` | PASS |
| bfo_mapping opt-in increases triple count | `len(g_bfo) > len(g_no_bfo)` | True | PASS |
| query_as_of returns historical shard | `query_as_of(g, pred, date(2026,3,15))` | `[(urn:test:shard/v3, "object3")]` | PASS |
| query_as_of returns empty before chain | `query_as_of(g, pred, date(2025,12,15))` | `[]` | PASS |
| query_as_of returns open-ended latest | `query_as_of(g, pred, date(2026,10,15))` | `[(urn:test:shard/v10, "object10")]` | PASS |
| 9 BFO equivalentClass mappings | `owl:equivalentClass` triples with `obo/BFO_` prefix | 9/9 verified | PASS |
| fi:supersedes inverseOf fi:supersededBy | `(supersedes, owl:inverseOf, supersededBy) in g` | True | PASS |
| fi:Retraction distinct from supersession | `fi:Retraction` triples in graph | 4 triples (exists as owl:Class) | PASS |

---

### Probe Execution

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| Vocab test suite | `uv run pytest tests/vocab/ -v` | 59 passed | PASS |
| Temporal test suite | `uv run pytest tests/temporal/ -v` | 17 passed | PASS |
| Combined suite | `uv run pytest tests/vocab/ tests/temporal/ -q` | 76 passed in 0.42s | PASS |

---

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|---------------|-------------|--------|----------|
| VOCAB-01 | 08-01, 08-02, 08-04 | FOLIO v2 TTL ships at stable `owl:versionIRI`; pinned via `fi:vocabVersion` on every shard | SATISFIED | All 5 TTL files carry `owl:versionIRI` with `2026.05.0`; `fi:VocabPinShape` SHACL belt + `field_validator` Pydantic belt both active |
| VOCAB-02 | 08-01, 08-04 | Analogia predicates + 4 distinction kinds queryable | SATISFIED | All 4 analogia predicates declared as owl properties; 4 distinction kinds in `fi:DistinctionKindEnumShape` sh:in; parameterized pyoxigraph roundtrip test passes |
| VOCAB-03 | 08-01, 08-04 | Tractarian/Spinozan/Russellian/Carnap/Aristotelian predicates | SATISFIED | `fi:elaborates`, `fi:dependsOnAxiom`, `fi:dependsOnDefinition`, `fi:closureMarker`, `fi:predicationMode` all present; roundtrip verified in both rdflib and pyoxigraph |
| VOCAB-04 | 08-01 | Mini-BFO spine + `bfo_mapping.ttl` with `owl:equivalentClass` | SATISFIED | 9-class spine in `bfo_spine.ttl`; `bfo_mapping.ttl` has 9 `owl:equivalentClass` rows to BFO 2020 PURLs |
| VOCAB-05 | 08-01, 08-03 | Supersession predicates distinct from retraction; as-of query works | SATISFIED | `fi:supersedes`/`fi:supersededBy` as `owl:inverseOf` pair; `fi:Retraction` is distinct class; `query_as_of()` returns historical shard at past date; `--as-of` CLI deferred per D-11 (cross-referenced in docs) |

All 5 requirements SATISFIED. No VOCAB requirement orphaned.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | — | — | All modified files pass anti-pattern scan |

No `TBD`, `FIXME`, or `XXX` markers found in Phase 8 modified files (vocab TTL files, temporal/as_of.py, shards/envelope.py additions, bench/generator.py additions). Marker comments in docstrings (`# DEFERRED (D-11)`) are intentional, properly cross-referenced to Phase 11/12, and not debt markers.

---

### Human Verification Required

None. All must-haves are verifiable programmatically:

- TTL parsing is deterministic and scripted (rdflib + pyoxigraph)
- SHACL enforcement is validated by two-polarity tests
- `query_as_of` behavior verified against 10-link fixture
- Version pinning verified via field_validator tests
- dep-leak guard verified via recursive import scan

---

### Gaps Summary

No gaps found. All 25 must-have checks (5 roadmap truths × 5 evidence levels + 12 per-decision checks + 8 behavioral spot-checks) are verified. The 939/939 test gate reported by the orchestrator is consistent with the 76/76 Phase 8 tests observed here.

**Phase 8 goal is fully achieved.**

---

_Verified: 2026-05-31T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
