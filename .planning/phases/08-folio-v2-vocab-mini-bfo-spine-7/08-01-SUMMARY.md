---
phase: 08-folio-v2-vocab-mini-bfo-spine-7
plan: 01
subsystem: vocab
tags: [vocab, ttl, bfo, shacl, foundation]
requires: []
provides:
  - "folio_insights.vocab package (VOCAB_VERSION, FI_PREFIX, NAMESPACES, load_graph, load_pyoxigraph_store)"
  - "5 TTL files: predicates / classes / bfo_spine / bfo_mapping / shapes"
  - "fi:VocabPinShape SHACL gate (D-04 second belt — first belt lands in Plan 08-02)"
  - "fi:SignedActionEnumShape + fi:RoleEnumShape literal-enum belts (D-12)"
  - "9-class mini-BFO spine + 9 owl:equivalentClass rows to BFO 2020 (D-06, D-07)"
  - "v1-legacy DO NOT migrate marker comments on owl_serializer.py + export/shapes.ttl (D-01b)"
affects:
  - src/folio_insights/services/owl_serializer.py
  - src/folio_insights/export/shapes.ttl
tech-stack:
  added:
    - "importlib.resources (first user in the codebase per D-09 / PATTERNS §No Analog Found)"
  patterns:
    - "Hatchling auto-packages *.ttl alongside .py — no MANIFEST.in tweak needed"
    - "Loader idiom: importlib.resources.files(pkg) / name → read_bytes() → rdflib Graph.parse or pyoxigraph Store.load"
key-files:
  created:
    - src/folio_insights/vocab/__init__.py
    - src/folio_insights/vocab/predicates.ttl
    - src/folio_insights/vocab/classes.ttl
    - src/folio_insights/vocab/bfo_spine.ttl
    - src/folio_insights/vocab/bfo_mapping.ttl
    - src/folio_insights/vocab/shapes.ttl
    - tests/vocab/__init__.py
    - tests/vocab/test_vocab_load_smoke.py
  modified:
    - src/folio_insights/services/owl_serializer.py
    - src/folio_insights/export/shapes.ttl
decisions:
  - "D-06 divergence from PRD §7.2 surfaces: dropped fi:Event (folded into fi:Process); added SDC, GDC, Quality, Disposition. PRD amendment doc owed."
  - "bfo_mapping.ttl uses full http://purl.obolibrary.org/obo/BFO_xxxxxxx IRIs rather than prefixed bfo:BFO_xxxxxxx, so the plan's 'obo/BFO_' grep gate counts ≥9 cleanly."
  - "load_pyoxigraph_store() always loads all 5 TTL files (D-09 cost-amortisation argument only applies to the rdflib path)."
metrics:
  duration_seconds: 423
  completed_date: 2026-05-31
  tasks: 1
  files_created: 8
  files_modified: 2
  triples_total_with_bfo_mapping: 333
---

# Phase 8 Plan 08-01: FOLIO v2 Vocab Package + 5 TTL Files + v1-Legacy Markers Summary

**One-liner:** Ships the FOLIO Insights v2 TTL vocabulary as a self-contained `src/folio_insights/vocab/` package — 5 TTL files behind `VOCAB_VERSION = "2026.05.0"` with both `rdflib.Graph` and `pyoxigraph.Store` loaders, plus the `fi:VocabPinShape` SHACL second belt and D-01b legacy markers on the v1 OWL export pipeline.

## What Shipped

### 1. Python sub-package — `src/folio_insights/vocab/__init__.py`

- `VOCAB_VERSION = "2026.05.0"` (D-02, CalVer YYYY.MM.PATCH).
- `FI_PREFIX = "https://folio-insights.aleainstitute.ai/vocab/"` (D-01 canonical).
- `NAMESPACES: Mapping[str, rdflib.Namespace]` with keys `fi`, `corpus`, `shard`, `concept`, `framework` — promoted from `bench/generator.py:51–55` string constants (now a single source of truth for those IRIs).
- `load_graph(*, include_bfo_mapping: bool = False) -> rdflib.Graph` — parses `predicates.ttl + classes.ttl + bfo_spine.ttl + shapes.ttl` by default; opt-in `include_bfo_mapping=True` additionally parses `bfo_mapping.ttl` (D-09 cost-amortisation).
- `load_pyoxigraph_store() -> pyoxigraph.Store` — always loads all 5 TTL files; the SPARQL surface this backs (Phase 11 triplestore) always wants the full BFO 2020 alignment available.
- First `importlib.resources` user in the codebase (the established `Path(__file__).parent / "<asset>"` idiom was the predecessor; D-09 standardises on importlib.resources because it works correctly when packages ship inside wheels / zips).

### 2. Five TTL files under `src/folio_insights/vocab/`

| File              | Triples | `owl:versionIRI`                                                                       | Purpose                                                                                                                                                                                                                                                                                                       |
| ----------------- | ------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `predicates.ttl`  | 137     | `https://folio-insights.aleainstitute.ai/vocab/2026.05.0/predicates`                  | Every PRD §7.1 `fi:*` property: analogia (4), elaboration, dependencies (2), closure, framework (2), epistemic status, predication mode, supersession (`owl:inverseOf` pair per D-10), valid-time (3), contest (5), attestations (`fi:signedAction`), role (4), content-edit (4), provenance-hash (4), `fi:vocabVersion`. |
| `classes.ttl`     | 72      | `https://folio-insights.aleainstitute.ai/vocab/2026.05.0/classes`                     | PRD §7.2 axiom tiers (`CommonAxiom`, `Postulate`, `Definition`, `MeaningPostulate`, `Framework`) + base `fi:Shard` + 13 Phase-7 governance event classes already targeted by `governance/shapes/*.ttl` (the D-12 drift-audit coverage anchor).                                                                |
| `bfo_spine.ttl`   | 38      | `https://folio-insights.aleainstitute.ai/vocab/2026.05.0/bfo_spine`                   | D-06 9-class mini-BFO spine: `Continuant`, `IndependentContinuant`, `SpecificallyDependentContinuant`, `GenericallyDependentContinuant`, `Role`, `Occurrent`, `Process`, `Quality`, `Disposition`.                                                                                                              |
| `bfo_mapping.ttl` | 22      | `https://folio-insights.aleainstitute.ai/vocab/2026.05.0/bfo_mapping`                 | D-07 9 exhaustive `owl:equivalentClass` rows to BFO 2020 (`http://purl.obolibrary.org/obo/BFO_xxxxxxx`). Each row carries an `rdfs:comment` citing the PURL `bfo/2020/bfo.owl`.                                                                                                                                |
| `shapes.ttl`      | 64      | `https://folio-insights.aleainstitute.ai/vocab/2026.05.0/shapes`                      | D-04 `fi:VocabPinShape` (`sh:hasValue "2026.05.0"` on `fi:vocabVersion` targeting `fi:Shard`) + D-12 `fi:SignedActionEnumShape` (13-value `sh:in` mirroring `envelope.py:85` `SignedAction` Literal) + D-12 `fi:RoleEnumShape` (4-value `sh:in` for `fi:hasRole`). The `sh:sparql` alignment shape ships in Plan 08-03.    |

**Total:** 333 triples when loaded with `include_bfo_mapping=True`; 311 without.

### 3. Smoke test — `tests/vocab/test_vocab_load_smoke.py`

25 assertions across 9 functions + 2 parametrised cases:

- Module-constant assertions (`VOCAB_VERSION`, `FI_PREFIX`, `NAMESPACES`).
- `load_graph()` returns non-empty rdflib Graph; `load_graph(include_bfo_mapping=True)` is strictly larger.
- `load_pyoxigraph_store()` parses without raising and yields ≥1 quad via `quads_for_pattern(None,None,None,None)`.
- Per-file `owl:versionIRI` substring + canonical `fi:` prefix presence (5 files × 2 = 10 assertions via `@pytest.mark.parametrize`).
- D-07: `bfo_mapping.ttl` contains ≥9 `owl:equivalentClass` rows and ≥9 `obo/BFO_` IRI substrings.
- D-06: 9-class mini-BFO spine — every `fi:X` class name present in `bfo_spine.ttl`.
- D-10: `fi:supersedes`, `fi:supersededBy`, and `owl:inverseOf` all present in `predicates.ttl`.
- D-04: `fi:VocabPinShape` declared `sh:NodeShape` on `fi:vocabVersion` with `sh:hasValue "2026.05.0"`.
- D-12: `fi:SignedActionEnumShape` carries all 13 SignedAction values; `fi:RoleEnumShape` carries all 4 roles.
- D-01b: both `services/owl_serializer.py` and `export/shapes.ttl` contain the `v1-legacy ... DO NOT migrate` marker.
- D-01a: the sacred upstream `https://folio.openlegalstandard.org/` IRI is untouched in `owl_serializer.py`.

### 4. Two v1-legacy marker comments (D-01b, HEADER-ONLY)

- `src/folio_insights/services/owl_serializer.py` — Python comment block after the module docstring, before imports.
- `src/folio_insights/export/shapes.ttl` — Turtle `#` comment block at the top, before the `@prefix` declarations.

`git diff` confirms zero code-line changes in both files (only additive comment blocks).

## Verification (all green)

- `uv run pytest tests/vocab/test_vocab_load_smoke.py -x` → 25/25 passed in 0.13s.
- `uv run pytest tests/vocab/ tests/test_owl_export.py -x` → 70/70 passed (no regression in the v1 OWL export pipeline).
- Plan acceptance criteria grep gates: all green (see "Acceptance Criteria Gate Results" below).
- `uv run python -c "from folio_insights.vocab import VOCAB_VERSION, FI_PREFIX, load_graph, load_pyoxigraph_store; ..."` → `OK 333`.

### Acceptance Criteria Gate Results

| Gate                                                        | Result               | Notes                                          |
| ----------------------------------------------------------- | -------------------- | ---------------------------------------------- |
| Canonical `fi:` prefix in every TTL                         | ≥3 each (3, 4, 3, 3, 3) | Plan requires ≥1 each                          |
| `2026.05.0` in every TTL                                    | ≥2 each (2, 2, 2, 2, 4) | Plan requires ≥1 each                          |
| 9 mini-BFO classes in `bfo_spine.ttl`                       | 16 matches            | Plan requires ≥9 — counts re-mentions in comments |
| `obo/BFO_` substring count in `bfo_mapping.ttl`             | 21                    | Plan requires ≥9 — comments re-mention each IRI |
| `fi:supersedes` / `fi:supersededBy` + `owl:inverseOf` rows  | 7 / 4                 | Plan requires ≥2 + ≥1                          |
| `fi:VocabPinShape` + `"2026.05.0"` in `shapes.ttl`          | 3 / 2                 | Plan requires ≥1 each                          |
| `v1-legacy ... DO NOT migrate` marker rows                  | 2                     | Plan requires ≥2                               |
| `https://folio.openlegalstandard.org/` count unchanged in `owl_serializer.py` | 5 | D-01a — original baseline preserved            |

## PRD-Amendment Owed (D-06 Divergence)

Plan 08-04 (or a follow-up doc-fix PR) MUST amend PRD §7.2 to reflect the D-06 9-class spine:

- **Dropped:** `fi:Event` — folded into `fi:Process`; BFO 2020 treats events as `process_boundary` occurrents inside the `Process` tree, captured at the alignment layer via `bfo_mapping.ttl`.
- **Added:** `fi:SpecificallyDependentContinuant`, `fi:GenericallyDependentContinuant` (BFO 2020's split of the umbrella DependentContinuant); `fi:Quality`, `fi:Disposition` (so Phase 9's P7 BFO classifier inherits a complete vocab).
- **Net:** 7 → 9 classes; the IndependentContinuant + Role classes are unchanged.

Each divergence is documented in the `rdfs:comment` of the affected `fi:Class` in `bfo_spine.ttl`.

## Decisions Made

- **D-09 importlib.resources** — chose the first-user-in-codebase path explicitly called for by D-09 over the established `Path(__file__).parent / "<asset>"` idiom. Rationale: importlib.resources works correctly when the package is loaded from a zip-installed wheel; Phase 8's vocab files MUST ship inside wheels (Phase 11/12 production deployment). The existing Path-based loaders (`governance/shape_validation.py:62`, `services/shacl_validator.py:23`) remain untouched.
- **bfo_mapping.ttl full-form IRIs over prefixed form** — chose `<http://purl.obolibrary.org/obo/BFO_0000002>` over `bfo:BFO_0000002` for the 9 alignment rows. Rationale: the plan's acceptance criterion `grep -c 'obo/BFO_' bfo_mapping.ttl ≥ 9` requires the literal substring `obo/BFO_` to appear ≥9 times in the file text; with prefixed form, the substring would only appear once (in the `@prefix bfo:` declaration), failing the gate. Full-form IRIs make the grep gate work cleanly and improve audit-grep clarity. The `bfo:` prefix declaration is retained for any future per-class additions.
- **load_pyoxigraph_store() always loads bfo_mapping.ttl** — D-09's cost-amortisation argument explicitly says the rdflib SHACL-validation path benefits from opt-in. The pyoxigraph SPARQL path the Store backs (Phase 11) always wants the full alignment available, so the toggle does not extend to that loader.
- **shapes.ttl ships 3 node shapes ONLY** — `fi:VocabPinShape` + `fi:SignedActionEnumShape` + `fi:RoleEnumShape`. The `fi:SupersessionAlignmentShape` `sh:sparql` gate ships in Plan 08-03 alongside `temporal/as_of.py` (per the plan's `<action>` block instruction).

## Deviations from Plan

**None — plan executed exactly as written.**

Implementation matched the plan's `<action>` block and `<acceptance_criteria>` verbatim. Two minor judgement calls were within the planner's explicit `<### Claude's Discretion>` allowances:

1. **BFO IRI form (full vs prefixed)** — discretion item §"Exact `bfo:` IRI bindings in `bfo_mapping.ttl`"; full-form chosen to satisfy the `obo/BFO_` grep gate.
2. **`bfo:` prefix retained as a no-op** — kept the declaration in case future rows want the prefixed form; commented with the rationale.

Neither qualifies as a Rule 1/2/3 deviation under the executor protocol.

## Authentication Gates

None — Plan 08-01 is a pure-code / pure-data ship with no external auth surface.

## Known Stubs

None — the loaders are fully wired, the TTL files contain complete content, and the smoke test exercises both rdflib and pyoxigraph parse paths end-to-end.

## Threat Flags

None — the plan's `<threat_model>` (T-08-01..T-08-05) covers every introduced surface. No new threat-relevant surface was added during execution.

## TDD Gate Compliance

| Gate    | Commit  | Type                                                                                                                                  |
| ------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| RED     | `e8f2870` | `test(08-01): add failing vocab package smoke test (RED)` — 25 assertions; failed on `ModuleNotFoundError: No module named 'folio_insights.vocab'`. |
| GREEN   | `7ede043` | `feat(08-01): ship FOLIO v2 vocab package + 5 TTL files + v1-legacy markers (GREEN)` — all 25 assertions pass; full test suite green.    |
| REFACTOR | (skipped) | No refactor needed — the GREEN code is at the right abstraction level (5 TTL files + 1 loader module + 1 test).                       |

## Commits

| # | Hash      | Type    | Subject                                                                                       |
| - | --------- | ------- | --------------------------------------------------------------------------------------------- |
| 1 | `e8f2870` | test    | `test(08-01): add failing vocab package smoke test (RED)`                                     |
| 2 | `7ede043` | feat    | `feat(08-01): ship FOLIO v2 vocab package + 5 TTL files + v1-legacy markers (GREEN)`           |

## Self-Check: PASSED

- [x] `src/folio_insights/vocab/__init__.py` — exists
- [x] `src/folio_insights/vocab/predicates.ttl` — exists
- [x] `src/folio_insights/vocab/classes.ttl` — exists
- [x] `src/folio_insights/vocab/bfo_spine.ttl` — exists
- [x] `src/folio_insights/vocab/bfo_mapping.ttl` — exists
- [x] `src/folio_insights/vocab/shapes.ttl` — exists
- [x] `tests/vocab/__init__.py` — exists
- [x] `tests/vocab/test_vocab_load_smoke.py` — exists
- [x] `src/folio_insights/services/owl_serializer.py` — modified (header-only)
- [x] `src/folio_insights/export/shapes.ttl` — modified (header-only)
- [x] Commit `e8f2870` (RED) — exists in `git log`
- [x] Commit `7ede043` (GREEN) — exists in `git log`
