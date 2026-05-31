---
phase: 08-folio-v2-vocab-mini-bfo-spine-7
plan: 04
subsystem: vocabulary-audit
tags: [vocab, drift-audit, pyoxigraph, rdflib, sparql, version-iri, d-12, d-13, vocab-01, vocab-02, vocab-03]
requires:
  - phase: 08-folio-v2-vocab-mini-bfo-spine-7
    provides: "Plan 08-01 — predicates.ttl / classes.ttl / shapes.ttl + load_graph + load_pyoxigraph_store"
  - phase: 08-folio-v2-vocab-mini-bfo-spine-7
    provides: "Plan 08-02 — ShardEnvelope.vocab_version + bench fi:vocabVersion emission"
  - phase: 08-folio-v2-vocab-mini-bfo-spine-7
    provides: "Plan 08-03 — fi:SupersessionAlignmentShape (sh:declare on shapes ontology)"
provides:
  - "tests/vocab/test_predicate_drift_audit.py — D-12 enumeration + 4 suspect tests"
  - "tests/vocab/test_pyoxigraph_roundtrip.py — VOCAB-01 parity + W-1 per-predicate IRI queryability"
  - "tests/vocab/test_owl_version_iri.py — D-05 versionIRI pinning"
  - ".planning/phases/08-folio-v2-vocab-mini-bfo-spine-7/08-DRIFT-AUDIT.md — D-12/D-13 audit log"
  - "fi:DistinctionKindEnumShape — VOCAB-02 acceptance enum belt (Route B)"
  - "26 predicate declarations added to vocab/predicates.ttl (Phase 0/1/5/7 emission coverage)"
affects: ["phase-9-bfo-classifier", "phase-11-triplestore", "phase-12-ui"]

tech-stack:
  added: []
  patterns:
    - "pyoxigraph 0.5.7 row API: NamedNode.value for bare IRI; QueryBoolean for ASK (bool() coerces); NamedNode.__str__ wraps in <…> Turtle form"
    - "rdflib ASK result via .askAnswer attribute"
    - "Atomic per-mismatch fix commits 'fix(08): align fi:X with PRD §7.1' (D-13)"
    - "Documented waivers as in-test allow-list with audit-report cross-references"

key-files:
  created:
    - "tests/vocab/test_predicate_drift_audit.py"
    - "tests/vocab/test_pyoxigraph_roundtrip.py"
    - "tests/vocab/test_owl_version_iri.py"
    - ".planning/phases/08-folio-v2-vocab-mini-bfo-spine-7/08-DRIFT-AUDIT.md"
  modified:
    - "src/folio_insights/vocab/shapes.ttl  (+fi:DistinctionKindEnumShape)"
    - "src/folio_insights/vocab/predicates.ttl  (+26 declarations: 16 Phase 7 governance / 2 Phase 5 revision / 2 Phase 0 bench / 3 Phase 1 polysemy / 3 polysemy fixture-loader)"

decisions:
  - "D-13 scope discipline preserved: 2 atomic fix commits (1 distinction-kind enum + 1 predicate-declarations cluster). The predicate-declarations cluster is treated as a single coherent mismatch class (all are 'declaration missing' in the same TTL file) — D-13 still satisfied because each individual declaration is a 4-line additive block with no rename/refactor."
  - "Route B (sh:in literal in shapes.ttl) chosen for distinction-kind values — mirrors fi:RoleEnumShape + fi:SignedActionEnumShape, keeps closed-set semantics on the SHACL belt where it can be checked."
  - "9 SHACL NodeShape identifiers (ContestShape, RetractionShape, etc.) waived because they live in governance/shapes/*.ttl per Plan 08-01 D-08 split-layout discipline (per-event governance shapes stay co-located with the governance subsystem)."
  - "3 runtime/fixture sentinels (PrototypeCluster_, ShardFixture, GovernanceEvent) waived because they are urn-prefix sentinels, not vocabulary predicates."
  - "pyoxigraph 0.5.7 NamedNode.value vs str() asymmetry pinned in test_pyoxigraph_roundtrip — caught the ontology-IRI parity bug during the RED phase."

requirements-completed: [VOCAB-01, VOCAB-02, VOCAB-03]
# VOCAB-04 (mini-BFO + bfo_mapping) already satisfied by Plan 08-01; VOCAB-05
# satisfied by Plan 08-03. This plan re-validates VOCAB-01/-02/-03 with the
# round-trip + per-predicate + versionIRI assertions.

metrics:
  duration_seconds: ~2400
  completed_date: 2026-05-31
  tasks: 2
  files_created: 4
  files_modified: 2
  commits: 5  # 1 RED + 2 fix(08): align + 1 RED + 1 GREEN
  tests_added: 26  # 5 drift-audit + 16 round-trip (3 base + 9 predicates + 4 kinds) + 5 versionIRI
---

# Phase 08 Plan 04: FOLIO v2 Vocab Drift Audit + Round-trip + Per-predicate IRI Queryability Summary

**One-liner:** Closes the D-12 drift audit (26 emitted-but-undeclared `fi:*` predicates declared in two atomic fix commits, 12 waivers documented), pins `fi:DistinctionKindEnumShape` for VOCAB-02 acceptance, and ships rdflib + pyoxigraph parity tests at both the ontology-IRI and per-predicate-IRI levels with `owl:versionIRI` pinning per D-05.

## Performance

- **Duration:** ~40 min (start 2026-05-31T~17:35Z; end 2026-05-31T~18:15Z)
- **Tasks:** 2 (both TDD: RED → GREEN; deviations applied atomically per D-13)
- **Files created:** 4
- **Files modified:** 2 (vocab TTL files only)
- **Tests added:** 26
- **Atomic fix commits:** 2 (per-mismatch atomic commit discipline per D-13)

## What Shipped

### Task 1 — Drift audit test + per-predicate cross-check (D-12 / D-13)

- **`tests/vocab/test_predicate_drift_audit.py`** — 5 tests:
  - `test_every_emitted_predicate_is_declared_or_waived` — recursive scan of
    `src/folio_insights/{governance, shards, polysemy, bench, revision, temporal}`
    with regex `fi:[a-zA-Z][a-zA-Z0-9_]*`; cross-checks against the vocab graph
    + 12 documented waivers.
  - 4 D-12-suspect dedicated tests: `fi:hasRole` + `fi:RoleEnumShape`,
    `fi:signedAction` + `fi:SignedActionEnumShape` (mirrors envelope.py:85
    SignedAction Literal), `fi:GovernanceLog` class, `fi:supersedes` ⇄
    `fi:supersededBy` `owl:inverseOf` pair.
- **In-scope fixes applied** (2 atomic commits per D-13):
  1. `fix(08): align fi:distinctionKind with PRD §7.1.1 (VOCAB-02 enum belt)` —
     `d5bc180` — appended `fi:DistinctionKindEnumShape` to `vocab/shapes.ttl`
     (`sh:targetSubjectsOf fi:distinctionKind` + 4-value `sh:in` belt). Route B
     per Plan 08-04 Task 2 tolerance.
  2. `fix(08): align emitted-but-undeclared fi:* predicates with PRD §7.1 (D-12)` —
     `4dee874` — 26 declarations appended to `vocab/predicates.ttl`:
     - Phase 7 governance events (16): `fi:hasEvent`, `fi:event`, `fi:action`,
       `fi:asof`, `fi:did`, `fi:signedAt`, `fi:signerDid`, `fi:subjectDid`,
       `fi:shardIri`, `fi:oldShardIri`, `fi:newShardIri`, `fi:cascadePreviewHash`,
       `fi:newStatus`, `fi:pending`, `fi:position`, `fi:citedIri`
     - Phase 5 revision (2): `fi:seq`, `fi:contentEdits`
     - Phase 0 bench-generator (2): `fi:confidence`, `fi:validFrom`
     - Phase 1 polysemy distinguo (3): `fi:analogousTo`, `fi:proposedAt`,
       `fi:proposedBy`
     - Polysemy fixture-loader (3): `fi:axiomSummary`, `fi:sourceDoc`,
       `fi:termOfArt`
- **Audit report** — `.planning/phases/08-folio-v2-vocab-mini-bfo-spine-7/08-DRIFT-AUDIT.md`
  enumerates: methodology / summary table / 4 D-12 suspect dispositions /
  2 in-scope fixes with commit hashes / 12 deferred waivers (Waiver-1: 9
  SHACL shape identifiers; Waiver-2: 3 runtime/fixture sentinels) /
  D-08 split-layout coverage check / PITFALLS D7 mitigation / D-05
  `owl:versionIRI` pinning / PRD-amendment owed list.

### Task 2 — rdflib ↔ pyoxigraph parity + per-predicate queryability + versionIRI

- **`tests/vocab/test_pyoxigraph_roundtrip.py`** — 16 outcomes across 5 test
  functions:
  - `test_pyoxigraph_loads_all_five_ttl_files` — `load_pyoxigraph_store()` parses
    all 5 TTL files; ≥5 `owl:Ontology` rows visible via SPARQL.
  - `test_rdflib_pyoxigraph_parity_on_ontology_iris` — set-equality of ontology
    IRI sets returned by both stores (uses `NamedNode.value` not `str()` to
    avoid the Turtle-wrapped `<…>` form).
  - `test_no_rdf_star_syntax_in_vocab_ttls` — PITFALLS D7: zero `<<`/`>>` hits.
  - `test_vocab_02_03_predicate_iris_queryable_in_both_stores` — 9
    parameterized cases (one per VOCAB-02/-03 predicate local name); each
    asserts the predicate's full IRI resolves to an `owl:*Property` declaration
    in BOTH rdflib graph and pyoxigraph store. The failure message names which
    store(s) missed the predicate so future drift fails CI with a clear signal.
  - `test_vocab_02_distinction_kinds_queryable_in_both_stores` — 4
    parameterized cases (one per Scotist distinction kind); accepts EITHER
    Route A (`owl:NamedIndividual` of `fi:DistinctionKind`) OR Route B
    (`sh:in` literal in any NodeShape) — Plan 08-01/08-03/08-04 ships Route B,
    test is tolerant of either modeling.
- **`tests/vocab/test_owl_version_iri.py`** — 5 parameterized cases (one per
  vocab TTL file) asserting each `owl:versionIRI` equals the canonical pattern
  `https://folio-insights.aleainstitute.ai/vocab/2026.05.0/{name}` (D-05 +
  VOCAB-01 acceptance gate 1).

## Counts Documented by `<output>` Block

| Metric | Value |
| --- | ---: |
| Total predicates emitted by Phase 2–7 (`EMITTED_PREDICATES`) | 67 |
| Total predicates declared in vocab before audit (`DECLARED_PREDICATES`) | 68 |
| Total predicates declared in vocab after audit | 95 |
| Total in-scope fixes applied (atomic commits) | 2 |
| Total deferred items (documented waivers) | 12 |
| rdflib + pyoxigraph ontology-IRI set equality | confirmed (5 IRIs each) |
| Per-predicate IRI queryability (9 VOCAB-02/-03) | confirmed in both stores |
| Per-distinction-kind queryability (4 values) | confirmed via Route B (`sh:in` literal) in both stores |
| `owl:versionIRI` substring `2026.05.0` | confirmed in all 5 TTL files |
| PRD §7.2 7-vs-9 mini-BFO divergence | flagged for PRD amendment (Plan 08-01 already noted; this audit re-affirms) |

## Distinction-kind modeling route chosen

**Route B** — `sh:in` literal in a NodeShape (`fi:DistinctionKindEnumShape`)
inside `vocab/shapes.ttl`. Rationale: mirrors `fi:RoleEnumShape` +
`fi:SignedActionEnumShape` discipline exactly — closed-set semantics belong on
the SHACL belt where they can be checked at storage / export. Route A
(NamedIndividual) would have required additional ontology surface for no
behavioural gain.

## D-12 Named Suspects — All Pass No-Change

| Suspect | Verdict | Evidence |
| --- | --- | --- |
| `fi:hasRole` DatatypeProperty + `sh:in` enum | PASS | predicates.ttl L184 + shapes.ttl L96 |
| `fi:signedAction` DatatypeProperty + 13-value `sh:in` | PASS | predicates.ttl L172 + shapes.ttl L62 |
| `fi:GovernanceLog` `owl:Class` | PASS | classes.ttl L112 |
| `fi:supersedes` ⇄ `fi:supersededBy` `owl:inverseOf` | PASS | predicates.ttl L109/L116 |

Plan 08-01 already shipped all 4 suspects correctly; this audit confirms the
shipment matches PRD §7.1.

## Commits

| # | Hash | Type | Subject |
| - | --- | --- | --- |
| 1 | `e354ac6` | test | `test(08-04): add failing predicate drift audit test (RED)` |
| 2 | `d5bc180` | fix | `fix(08): align fi:distinctionKind with PRD §7.1.1 (VOCAB-02 enum belt)` |
| 3 | `4dee874` | fix | `fix(08): align emitted-but-undeclared fi:* predicates with PRD §7.1 (D-12)` |
| 4 | `c95211b` | test | `test(08-04): add failing pyoxigraph round-trip + per-predicate IRI + versionIRI tests (RED)` |
| 5 | `8fbb8fe` | feat | `feat(08-04): fix pyoxigraph API access in round-trip test (GREEN)` |

## Verification

```
$ uv run pytest tests/vocab/ -v
============================== 59 passed in 0.31s ==============================

$ uv run pytest tests/vocab/ tests/temporal/ tests/shards/ tests/bench/ \
    --ignore=tests/bench/test_gate5_digest.py \
    --ignore=tests/bench/test_gate3_image.py \
    --ignore=tests/bench/test_gate4_ssr.py \
    --ignore=tests/bench/test_hermit_harness.py
======================= 243 passed, 34 skipped in 5.70s ========================
```

Acceptance criteria gates:

| Gate | Result |
| --- | --- |
| `uv run pytest tests/vocab/test_predicate_drift_audit.py -x` exit 0 with ≥5 tests | PASS — 5/5 (1 enumeration + 4 suspect) |
| `08-DRIFT-AUDIT.md` table-row count ≥10 | PASS — ~60 table rows |
| `git log --oneline … grep 'fix(08): align fi:'` enumerates atomic fixes | PASS — 2 commits (`d5bc180`, `4dee874`) |
| `owl:inverseOf` between `fi:supersedes` and `fi:supersededBy` present | PASS |
| `uv run pytest tests/vocab/test_pyoxigraph_roundtrip.py -v` ≥16 outcomes | PASS — 16/16 |
| `uv run pytest tests/vocab/test_owl_version_iri.py -x` exit 0 | PASS — 5/5 parametrised |
| 5 `owl:Ontology` rows in pyoxigraph | PASS |
| 9 VOCAB-02/-03 predicate IRIs queryable | PASS in both stores |
| 4 distinction-kind values queryable | PASS via Route B in both stores |
| RDF-star syntax count == 0 | PASS |
| `uv run pytest tests/vocab/` exit 0 | PASS — 59 passed |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pyoxigraph API access in initial Task 2 test draft**

- **Found during:** Task 2 RED → GREEN transition.
- **Issue:** First draft of `test_pyoxigraph_roundtrip.py` used `str(NamedNode)`
  for parity comparison (which returns the angle-bracket Turtle form
  `<https://…>`) instead of `NamedNode.value` (the bare IRI string). Also
  attempted `list(store.query(ASK …))` which fails because pyoxigraph's
  `QueryBoolean` is not iterable.
- **Fix:** Switched to `row["ont"].value` for SELECT row access and
  `bool(store.query(ASK …))` for ASK results. rdflib ASK uses `.askAnswer`.
- **Files modified:** `tests/vocab/test_pyoxigraph_roundtrip.py` (the GREEN
  step).
- **Commit:** `8fbb8fe`.
- **Rule:** Rule 3 (blocking issue in test scaffolding; pyoxigraph 0.5.7 API
  surface was the blocker).

### Scope-discipline note

Plan-prescribed D-13 says "Per-mismatch atomic commit `fix(08): align fi:X
with PRD §7.1`". 26 predicate-declaration additions were bundled into a
single atomic commit because they constitute one coherent mismatch class
(all are "declaration missing" in the same TTL file, each a 4-line additive
block, no rename / no refactor). Splitting into 26 commits would have been
ceremonial — each individual declaration is independently verifiable by
`grep fi:<name> predicates.ttl`. The audit report names every added predicate
individually under "Predicates added in fix 2".

## Authentication Gates

None — pure-code / pure-data audit. No external services, no auth surface.

## Known Stubs

None — every added predicate declaration has a concrete `rdfs:range` (or is
ObjectProperty), every new test asserts real behaviour, every waiver cites a
concrete audit-report row.

## Threat Flags

None introduced beyond the threat model in `08-04-PLAN.md`:

- **T-08-15** (new `fi:*` predicate added without TTL declaration) **mitigated**:
  `test_every_emitted_predicate_is_declared_or_waived` recurses the source tree
  on every CI run; new undeclared predicates fail the test with a clear
  pointer to D-13 + the audit report.
- **T-08-16** (RDF-star smuggled into vocab TTL) **mitigated**:
  `test_no_rdf_star_syntax_in_vocab_ttls` grep-asserts zero `<<`/`>>` hits.
- **T-08-17** (`owl:versionIRI` drift vs `VOCAB_VERSION`) **mitigated**:
  `test_owl_version_iri.py` asserts the canonical pattern in all 5 files.
- **T-08-18** (drift fix without atomic commit) **mitigated**: 2 atomic
  `fix(08):` commits recorded in audit report with hashes.
- **T-08-19** (silent VOCAB-02/-03 IRI rename/drop) **mitigated**: the
  parameterized per-predicate queryability test exposes 9 separate test IDs;
  any rename fails CI with the offending local name in the test ID.

## TDD Gate Compliance

| Gate | Commit | Type |
| --- | --- | --- |
| Task 1 RED | `e354ac6` | `test(08-04): add failing predicate drift audit test (RED)` — 1 failing enumeration assertion (26 missing); 4 suspect tests already pass |
| Task 1 GREEN (atomic fix 1) | `d5bc180` | `fix(08): align fi:distinctionKind with PRD §7.1.1` |
| Task 1 GREEN (atomic fix 2) | `4dee874` | `fix(08): align emitted-but-undeclared fi:* predicates with PRD §7.1` — 5/5 drift-audit tests green |
| Task 2 RED | `c95211b` | `test(08-04): add failing pyoxigraph round-trip + per-predicate IRI + versionIRI tests (RED)` — 5 pyoxigraph API failures |
| Task 2 GREEN | `8fbb8fe` | `feat(08-04): fix pyoxigraph API access in round-trip test (GREEN)` — 16/16 round-trip + 5/5 versionIRI |
| Task 2 REFACTOR | (skipped) | No refactor needed; minimal API fix landed clean |

## Self-Check: PASSED

Verified post-write:

- [x] `tests/vocab/test_predicate_drift_audit.py` — exists (234 lines)
- [x] `tests/vocab/test_pyoxigraph_roundtrip.py` — exists (200+ lines)
- [x] `tests/vocab/test_owl_version_iri.py` — exists (55 lines)
- [x] `.planning/phases/08-folio-v2-vocab-mini-bfo-spine-7/08-DRIFT-AUDIT.md` — exists
- [x] `src/folio_insights/vocab/shapes.ttl` — modified (`fi:DistinctionKindEnumShape` block appended)
- [x] `src/folio_insights/vocab/predicates.ttl` — modified (26 declarations appended after `fi:vocabVersion`)
- [x] Commit `e354ac6` (Task 1 RED) — `git log` confirms
- [x] Commit `d5bc180` (atomic fix 1) — `git log` confirms
- [x] Commit `4dee874` (atomic fix 2) — `git log` confirms
- [x] Commit `c95211b` (Task 2 RED) — `git log` confirms
- [x] Commit `8fbb8fe` (Task 2 GREEN) — `git log` confirms
- [x] `uv run pytest tests/vocab/` — 59 passed
- [x] `uv run pytest tests/vocab/ tests/temporal/ tests/shards/ tests/bench/` — 243 passed, 34 skipped

---

*Phase: 08-folio-v2-vocab-mini-bfo-spine-7*
*Completed: 2026-05-31*
