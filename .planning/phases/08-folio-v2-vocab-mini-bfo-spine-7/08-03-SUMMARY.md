---
phase: 08-folio-v2-vocab-mini-bfo-spine-7
plan: 03
subsystem: vocabulary
tags: [rdflib, pyshacl, sparql, supersession, valid-time, shacl, vocab, vocab-05]

# Dependency graph
requires:
  - phase: 08-folio-v2-vocab-mini-bfo-spine-7
    provides: "Plan 08-01 — fi:supersedes / fi:supersededBy / fi:validTimeStart / fi:validTimeEnd predicates in vocab/predicates.ttl; load_graph() and load_pyoxigraph_store() loaders in folio_insights.vocab; vocab/shapes.ttl base shapes (VocabPinShape, SignedActionEnumShape, RoleEnumShape) to append to"
  - phase: 05-content-versioning-6-4
    provides: "valid-time + supersession infrastructure (transaction-time + half-open interval semantics)"
provides:
  - "folio_insights.temporal package — rdflib-native valid-time query surface"
  - "query_as_of(graph, predicate, at_date) -> list[(URIRef, URIRef|Literal)] helper"
  - "fi:SupersessionAlignmentShape SHACL belt enforcing B.validTimeEnd == A.validTimeStart"
  - "docs/query-as-of.md — first file in a new docs/ directory; SPARQL + Python template for Phase 11/12"
  - "tests/temporal/fixtures/supersession_chain.ttl — 10-link reusable regression scaffold"
affects: ["11-triplestore", "12-ui", "phase-9-bfo-classifier", "future as-of CLI / UI surface"]

# Tech tracking
tech-stack:
  added: []  # no new dependencies — rdflib + pyshacl + pyoxigraph already in pyproject (Phase 0)
  patterns:
    - "Rdflib-native quarantine for temporal/ (D-04 dep-leak discipline mirrors Phase 7 governance)"
    - "SPARQL initBindings for caller-supplied parameters (PITFALLS Q3 / T-08-10 SPARQL-injection mitigation)"
    - "Half-open [validTimeStart, validTimeEnd) interval semantics enforced at SPARQL FILTER level"
    - "SHACL sh:sparql BAD-case polarity (non-empty result → conforms=False) reused from Phase 7 supersession_shape.ttl"
    - "sh:declare on the shapes ontology node so sh:sparql constraints resolve the fi: prefix"
    - "First docs/ directory — establishes the prose-doc precedent for the project"

key-files:
  created:
    - "src/folio_insights/temporal/__init__.py"
    - "src/folio_insights/temporal/as_of.py"
    - "tests/temporal/__init__.py"
    - "tests/temporal/fixtures/supersession_chain.ttl"
    - "tests/temporal/test_query_as_of.py"
    - "tests/temporal/test_dep_leak_guard.py"
    - "tests/temporal/test_supersession_alignment_shape.py"
    - "docs/query-as-of.md"
  modified:
    - "src/folio_insights/vocab/shapes.ttl"

key-decisions:
  - "Implemented per Phase 8 D-10: rdflib + stdlib only in temporal/; no pyoxigraph/oxrdflib/pyshacl/vocab/revision/store/governance imports"
  - "query_as_of accepts rdflib.Graph only (V1 minimum per D-10 discretion); Phase 11 will widen to Graph | Store polymorphic"
  - "Half-open [start, end) interval semantics — t == end belongs to the NEXT chain link (PRD §21.9); pinned by dedicated boundary test"
  - "SPARQL FILTER walks the chain implicitly — every shard carries its own validTimeStart/End, so no recursive Python walk is needed"
  - "fi:SupersessionAlignmentShape uses sh:targetSubjectsOf fi:supersedes + sh:sparql BAD-case (FILTER STR(?aStart) != STR(?bEnd))"
  - "sh:declare attached to the shapes ontology node so the sh:sparql sh:prefixes lookup succeeds under pyshacl 0.31.0"
  - "--as-of CLI flag confirmed deferred to Phase 11 (triplestore) / Phase 12 (UI) per D-11; docs/query-as-of.md cross-references the deferral"
  - "Used Literal(dt.isoformat(), datatype=XSD.dateTime) to coerce caller dates into the SPARQL FILTER comparator type, mirroring the validTimeStart/End rdfs:range xsd:dateTime in predicates.ttl"

patterns-established:
  - "Pattern 1: rdflib-only library helpers — temporal/as_of.py mirrors governance/shape_validation.py's quarantine doctrine (D-04)"
  - "Pattern 2: Per-package dep-leak guard test — tests/temporal/test_dep_leak_guard.py mirrors tests/governance/test_dep_leak_guard.py (recursive rglob scan with parametrized FORBIDDEN list)"
  - "Pattern 3: SHACL sh:sparql BAD-case polarity for cross-shard alignment — non-empty SELECT yields conforms=False; Pydantic envelope cannot enforce cross-shard relationships, so SHACL crosses the boundary"
  - "Pattern 4: docs/ as the home for prose+SPARQL templates downstream phases copy verbatim"

requirements-completed: [VOCAB-05]

# Metrics
duration: 25min
completed: 2026-05-31
---

# Phase 08 Plan 03: Supersession Query Surface (VOCAB-05) Summary

**Pure-rdflib `query_as_of(graph, predicate, at_date)` helper that walks `fi:supersedes` / `fi:validTimeStart`/`End` to surface a predicate's binding as of any past date, the `fi:SupersessionAlignmentShape` SHACL belt enforcing chain alignment, and `docs/query-as-of.md` as the Phase 11/12 copy-template.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-31T16:42Z
- **Completed:** 2026-05-31T17:07Z
- **Tasks:** 2 (both TDD: RED → GREEN)
- **Files created:** 8
- **Files modified:** 1
- **Tests added:** 17 (all green; 50 total in tests/temporal/ + tests/vocab/)

## Accomplishments

- **`folio_insights.temporal` package** — first new top-level subsystem since Phase 7 governance. Quarantined to rdflib + stdlib per D-04 dep-leak discipline (zero coupling to vocab/revision/store/governance under `src/`).
- **`query_as_of(graph, predicate, at_date) -> list[(URIRef, URIRef|Literal)]`** — SPARQL FILTER over `?start <= ?at && (!BOUND(?end) || ?at < ?end)` walks the supersession chain implicitly. `initBindings` parameterization is the PITFALLS Q3 / T-08-10 SPARQL-injection mitigation (`predicate` and `at_date` never f-string-interpolated).
- **`fi:SupersessionAlignmentShape`** appended to `vocab/shapes.ttl` — `sh:targetSubjectsOf fi:supersedes` + `sh:sparql` BAD-case SELECT (`FILTER(STR(?aStart) != STR(?bEnd))`) → non-empty result yields `conforms=False`. Polarity matches `governance/shapes/supersession_shape.ttl`.
- **`docs/query-as-of.md` (107 lines)** — first file in a new `docs/` directory. Prose intro citing PRD §21.9, 20-line SPARQL pattern with `initBindings` annotation, Python helper example, CLI/UI deferral cross-reference to Phase 11 / Phase 12 (D-11), and a SHACL-guard subsection.
- **10-link reusable fixture** — `tests/temporal/fixtures/supersession_chain.ttl` spans 2026-01-01 through 2026-10-01+ (link 10 open-ended), each link supersedes the prior, every adjacent pair shares the boundary (B.validTimeEnd == A.validTimeStart). Downstream phases can reuse this as a regression scaffold.
- **Dep-leak guard test** — `tests/temporal/test_dep_leak_guard.py` recursively scans `src/folio_insights/temporal/*.py` against `FORBIDDEN = [pyoxigraph, oxrdflib, pyshacl, folio_insights.{vocab,revision,store,governance}]`. The single rdflib-import sanity check pins that the quarantine is non-vacuous.

## Task Commits

Each task followed TDD: RED → GREEN.

1. **Task 1 RED — failing test scaffold** — `f8377d6` (test)
2. **Task 1 GREEN — `query_as_of` walker** — `bc12e30` (feat)
3. **Task 2 RED — both-polarity SHACL test** — `638bfe6` (test)
4. **Task 2 GREEN — `fi:SupersessionAlignmentShape` + `docs/query-as-of.md`** — `cfc7350` (feat)

_Note: TDD gate sequence — RED commits precede GREEN commits within each task. No REFACTOR phase needed; GREEN implementation was minimal and clean by construction._

## Files Created/Modified

### Created
- `src/folio_insights/temporal/__init__.py` — package marker + module docstring citing D-04 / D-10 / D-11 boundaries; re-exports `query_as_of` for `from folio_insights.temporal import query_as_of` ergonomics.
- `src/folio_insights/temporal/as_of.py` — the rdflib-native walker. Module docstring opens with the D-11 deferral comment and the D-10 / D-04 dep-leak discipline citation. `_AS_OF_SELECT` constant is the parameterized SPARQL. `_coerce_at` handles `date | datetime` → `xsd:dateTime Literal` for SPARQL FILTER comparison. `query_as_of` returns `list[tuple]`; empty list when no chain link matches.
- `tests/temporal/__init__.py` — empty package marker.
- `tests/temporal/fixtures/supersession_chain.ttl` — the 10-link fixture (see "10-link fixture valid-time layout" below).
- `tests/temporal/test_query_as_of.py` — 7 tests: 5 timepoint cases per the plan's `<behavior>` (before chain, link 1, link 5, link 10, far-future open-ended), plus 1 boundary semantics test (t == end → next link, not current), plus 1 empty-list-type contract test.
- `tests/temporal/test_dep_leak_guard.py` — parametrized `FORBIDDEN` scan + non-vacuous-import sanity test.
- `tests/temporal/test_supersession_alignment_shape.py` — both polarities: aligned 10-link chain conforms; misaligned 2-shard inline fixture (1-day gap between B.end and A.start) fails and the pyshacl report cites `SupersessionAlignmentShape` by name.
- `docs/query-as-of.md` — see "docs/query-as-of.md location" below.

### Modified
- `src/folio_insights/vocab/shapes.ttl` — APPENDED `fi:SupersessionAlignmentShape` after `fi:RoleEnumShape`. Did NOT rewrite any existing content from Plan 08-01 (`fi:VocabPinShape`, `fi:SignedActionEnumShape`, `fi:RoleEnumShape` preserved verbatim). Also appended an `sh:declare` block on `<https://folio-insights.aleainstitute.ai/vocab/shapes>` so the `sh:sparql` constraint resolves the `fi:` prefix via `sh:prefixes` under pyshacl 0.31.0.

## 10-link fixture valid-time layout (per plan output requirement)

The fixture lives at `tests/temporal/fixtures/supersession_chain.ttl`. Every shard subject is `<urn:test:shard/vN>`, every object is `"objectN"`, every link N ≥ 2 carries `fi:supersedes <urn:test:shard/v(N-1)>`. Test predicate is `fi:exampleProperty` to avoid collision with the real PRD §7.1 predicates.

| Link | fi:validTimeStart       | fi:validTimeEnd         | Notes                       |
|------|-------------------------|-------------------------|-----------------------------|
| v1   | 2026-01-01T00:00:00+00:00 | 2026-02-01T00:00:00+00:00 | chain origin               |
| v2   | 2026-02-01T00:00:00+00:00 | 2026-03-01T00:00:00+00:00 | aligned with v1's end       |
| v3   | 2026-03-01T00:00:00+00:00 | 2026-04-01T00:00:00+00:00 | aligned with v2's end       |
| v4   | 2026-04-01T00:00:00+00:00 | 2026-05-01T00:00:00+00:00 | aligned with v3's end       |
| v5   | 2026-05-01T00:00:00+00:00 | 2026-06-01T00:00:00+00:00 | aligned with v4's end       |
| v6   | 2026-06-01T00:00:00+00:00 | 2026-07-01T00:00:00+00:00 | aligned with v5's end       |
| v7   | 2026-07-01T00:00:00+00:00 | 2026-08-01T00:00:00+00:00 | aligned with v6's end       |
| v8   | 2026-08-01T00:00:00+00:00 | 2026-09-01T00:00:00+00:00 | aligned with v7's end       |
| v9   | 2026-09-01T00:00:00+00:00 | 2026-10-01T00:00:00+00:00 | aligned with v8's end       |
| v10  | 2026-10-01T00:00:00+00:00 | (absent)                | open-ended current link      |

## SHACL polarity test outcomes (per plan output requirement)

| Polarity | Data graph                                           | Expected `conforms` | Observed |
|----------|------------------------------------------------------|---------------------|----------|
| (1) ALIGNED   | 10-link `tests/temporal/fixtures/supersession_chain.ttl` (every B.end == next A.start) | `True`  | `True` (test green) |
| (2) MISALIGNED | inline 2-shard fixture: `A.validTimeStart = 2026-05-01`, `B.validTimeEnd = 2026-04-30`, `A fi:supersedes B` | `False` | `False` + report cites `SupersessionAlignmentShape` (test green) |

End-to-end command verification:
```sh
$ uv run python -c "from folio_insights.vocab import load_graph; from rdflib import Graph; import pyshacl; sg = load_graph(); dg = Graph().parse('tests/temporal/fixtures/supersession_chain.ttl', format='turtle'); ok, _, _ = pyshacl.validate(data_graph=dg, shacl_graph=sg, inference='none'); print('conforms=True' if ok else 'conforms=False')"
conforms=True
```

## docs/query-as-of.md location (per plan output requirement)

- **Path:** `docs/query-as-of.md` — top-level `docs/` directory NEW to this repo (first prose-doc file).
- **Length:** 107 lines.
- **Sections:** H1 title + prose intro citing PRD §21.9 → `## SPARQL pattern` (20-line query with `initBindings` annotation) → `## Python helper` (worked example using the 10-link fixture) → `## CLI / UI surface (deferred)` (D-11 cross-reference to Phase 11 / 12) → `## SHACL guard` (links to `fi:SupersessionAlignmentShape`) → `## See also` (8 cross-references).

## --as-of CLI deferral (per plan output requirement)

Confirmed: the `--as-of <date>` CLI flag and the UI date-picker remain **explicitly out of Phase 8 scope per D-11**. `docs/query-as-of.md` § "CLI / UI surface (deferred)" cross-references Phase 11 (triplestore CLI) and Phase 12 (UI) where the flag has a real query surface to attach to. Phase 8 ships predicates + library helper + SPARQL template; that's the minimum viable VOCAB-05 surface.

## Decisions Made

(Already enumerated in frontmatter `key-decisions:`; the most consequential)

- **Half-open intervals strictly enforced.** PRD §21.9 says `[start, end)`. The SPARQL FILTER uses `?start <= ?at` (inclusive lower bound) and `?at < ?end` (exclusive upper bound). The dedicated `test_t_exactly_at_boundary_falls_in_next_link` test pins that t == end belongs to the NEXT link — a one-line semantic guarantee future-Claude can lean on.
- **`Literal(dt.isoformat(), datatype=XSD.dateTime)` for the at-date coercion.** `rdflib.Literal(datetime, datatype=XSD.dateTime)` accepts datetimes but the lexical form needs to match the fixture's `"2026-05-15T00:00:00+00:00"^^xsd:dateTime` for SPARQL string-based filter consistency. Using `isoformat()` makes the lexical form explicit and round-trip stable.
- **`sh:declare` on the shapes ontology node.** Under pyshacl 0.31.0, `sh:prefixes <ontology-iri>` requires a corresponding `sh:declare` block at the same node. The Plan 08-01 shapes.ttl declared the ontology node but did not need `sh:declare` because its shapes did not use `sh:sparql`. Plan 08-03 introduces the first `sh:sparql` constraint in `vocab/shapes.ttl`, so the `sh:declare` block lands here.

## Deviations from Plan

None — plan executed exactly as written. No auto-fixes were needed (no Rule 1 bugs, no Rule 2 missing-critical, no Rule 3 blockers); the Wave 1 prerequisites (`folio_insights.vocab.VOCAB_VERSION`, `load_graph()`, `load_pyoxigraph_store()`, `fi:supersedes` / `fi:supersededBy` / `fi:validTimeStart` / `fi:validTimeEnd` in `predicates.ttl`, the appendable `vocab/shapes.ttl`) were all in place from the merged Wave 1, so both tasks proceeded directly RED → GREEN with no architecture deviation.

## Issues Encountered

None — both tasks went RED → GREEN on first implementation. The fixture's `xsd:dateTime` literals were chosen with timezone suffixes (`+00:00`) from the outset to avoid rdflib's naive-vs-aware comparison quirks; this paid off as the implementation worked first try.

## Threat Flags

None — no new threat surface introduced beyond the threat model in PLAN.md:

- T-08-10 (Tampering — SPARQL injection via `at_date`) **mitigated**: `initBindings={"predicate": predicate, "at": at_literal}` is the only way caller values reach the query; no f-string interpolation.
- T-08-11 (Tampering — supersession-chain integrity at storage) **mitigated**: `fi:SupersessionAlignmentShape` ships and both polarities are tested.
- T-08-12 (Information Disclosure — historical shards via `query_as_of`) **accepted** per plan; Phase 13.5 CORPUS-07 owns private-corpus access control.
- T-08-13 (DoS — pathological 10K+ link chain) **accepted** per plan; Phase 11 owns pyoxigraph polymorphic + perf bench.
- T-08-14 (Tampering — future helper accidentally importing pyoxigraph) **mitigated**: `tests/temporal/test_dep_leak_guard.py` is parametrized + recursive, so any future submodule under `temporal/` is automatically scanned.

## User Setup Required

None — no environment variables, no external services, no dashboard configuration. Phase 11 / Phase 12 will introduce the CLI flag and UI date picker per D-11.

## Next Phase Readiness

- **Wave 2 of Phase 8 (this plan)** is complete; **Plan 08-04 (drift audit)** is the remaining work and depends on Plan 08-03 per `40607e7` plan-revision commit. Plan 08-04 can now proceed.
- **Phase 11 (triplestore)** can lift `query_as_of` directly: the `Graph | Store` widening is a 1-line signature edit + an isinstance branch on `pyoxigraph.Store`. The SPARQL pattern and `initBindings` discipline transfer verbatim.
- **Phase 12 (UI)** can copy the SPARQL block from `docs/query-as-of.md` verbatim into the SSR layer's query template.
- **Phase 9 (BFO classifier)** inherits the full 9-class mini-BFO spine + the canonical `fi:` vocabulary surface from Wave 1; nothing in this plan affects Phase 9's input contract.

---

## Self-Check: PASSED

Verified all created files exist:
- `src/folio_insights/temporal/__init__.py` — FOUND
- `src/folio_insights/temporal/as_of.py` — FOUND
- `tests/temporal/__init__.py` — FOUND
- `tests/temporal/fixtures/supersession_chain.ttl` — FOUND
- `tests/temporal/test_query_as_of.py` — FOUND
- `tests/temporal/test_dep_leak_guard.py` — FOUND
- `tests/temporal/test_supersession_alignment_shape.py` — FOUND
- `docs/query-as-of.md` — FOUND

Verified all commit hashes exist on `worktree-agent-ac8a3a844478b423b`:
- `f8377d6` (Task 1 RED) — FOUND
- `bc12e30` (Task 1 GREEN) — FOUND
- `638bfe6` (Task 2 RED) — FOUND
- `cfc7350` (Task 2 GREEN) — FOUND

Verified the modified file diff is APPEND-ONLY (no Plan 08-01 content rewritten):
- `src/folio_insights/vocab/shapes.ttl` — Plan 08-01's `fi:VocabPinShape`, `fi:SignedActionEnumShape`, `fi:RoleEnumShape` blocks intact; `fi:SupersessionAlignmentShape` + `sh:declare` block appended after them.

---

*Phase: 08-folio-v2-vocab-mini-bfo-spine-7*
*Completed: 2026-05-31*
