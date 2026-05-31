# Phase 8: FOLIO v2 Vocab + Mini-BFO Spine (§7) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-31
**Phase:** 08-folio-v2-vocab-mini-bfo-spine-7
**Areas discussed:** Namespace canonicalization + v1 migration; Version-pinning mechanism + failure mode; Mini-BFO class scope (7 vs 9); TTL layout + supersession query surface

---

## Namespace canonicalization (`fi:` prefix)

| Option | Description | Selected |
|--------|-------------|----------|
| `https://folio-insights.aleainstitute.ai/vocab/` | Matches PRD §7.1 verbatim; Phase 0 + Phase 1 already write this prefix. v1's `openlegalstandard.org/modules/folio-insights/` becomes legacy-only. | ✓ |
| `https://folio.openlegalstandard.org/modules/folio-insights/` | Matches v1 export. Phase 0–7 source must be rewritten; higher blast radius. | |
| Both, with `owl:equivalentProperty`/`Class` bridge | 2× the triples in every export; slower SHACL; lets v1 consumers keep working. | |

**User's choice:** `https://folio-insights.aleainstitute.ai/vocab/` (Recommended)
**Notes:** None at this turn; clarifications followed on v1 export disposition.

## v1 OWL export disposition

| Option | Description | Selected |
|--------|-------------|----------|
| Freeze v1 paths as v1-only; v2 export ships separately | Leave `services/owl_serializer.py` + `export/shapes.ttl` untouched; add `# v1-legacy` marker comments. | ✓ |
| Rewrite v1 paths to v2 prefix | Breaks bit-for-bit v1 export comparison; pollutes Phase 8 with v1 scope. | |
| Add `owl:equivalentProperty` bridge in v2 vocab only | 2× the triples; both prefixes side-by-side. | |

**User's choice:** Freeze v1 paths (Recommended) — with a critical clarification.
**Notes:** User verbatim: *"To be clear, I want the FOLIO IRIs to remain canonical for FOLIO items. We're just changing IRIs for the Shards, right? But if you've been thinking about changing the FOLIO canonical IRIs, please revert! If you're just changing OTHER IRIs (e.g., shards), then please proceed with your recommendation (e.g., freeze as v1 only, v2 export ships separately)."*

This is captured as **D-01a** in CONTEXT.md: FOLIO canonical IRIs (`https://folio.openlegalstandard.org/`) are sacred and MUST NOT be touched. Only the FOLIO Insights extension prefix moves. v1's legacy FI-extension prefix is frozen with a `# v1-legacy` comment marker so future contributors don't accidentally graft v2 logic onto v1 paths.

---

## Version-pinning mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Module constant in new vocab package | `folio_insights.vocab.VOCAB_VERSION` is a CalVer string; envelope reads at construction. One source of truth. | ✓ |
| Per-corpus config setting | `<corpus>/manifest.json` declares vocab_version; lets multiple corpora pin different versions. Threading cost. | |
| Build-time stamp from `pyproject.toml` | Couples vocab and code release cadence. | |

**User's choice:** Module constant (Recommended)
**Notes:** None.

## SHACL pin shape location + rejection contract

| Option | Description | Selected |
|--------|-------------|----------|
| Pydantic envelope validator + SHACL belt in `vocab/shapes.ttl` | Two-belt enforcement matching Phase 6/7 convention. | ✓ |
| Pydantic-only (no SHACL) | Raw RDF triples bypass the check; no recovery for hand-constructed triples. | |
| SHACL-only (no Pydantic validator) | Wrong-pin envelopes live in memory until write time; deviates from project convention. | |

**User's choice:** Pydantic + SHACL belt (Recommended)
**Notes:** None.

## `vocab_version` field placement on envelope

| Option | Description | Selected |
|--------|-------------|----------|
| Required field on base envelope; `default=VOCAB_VERSION`; Pydantic validator | Symmetrical with Phase 7 `corpus`/`position`. | ✓ |
| Required field, no default — caller MUST supply | Every test fixture in tests/shards/ must thread `vocab_version=`; large diff. | |
| Computed property, not stored | Deserialized shards lose mint-time version; breaks audit story. | |

**User's choice:** Required + default + validator (Recommended)
**Notes:** None.

## CalVer format for `VOCAB_VERSION`

| Option | Description | Selected |
|--------|-------------|----------|
| `YYYY.MM.PATCH` (e.g. `"2026.05.0"`) | Lets the vocab patch mid-month without a release-month skip. | ✓ |
| `YYYY.MM` (e.g. `"2026.05"`) | Two patches in one month force a parallel patch dimension. | |
| `YYYY.MM.DD` (e.g. `"2026.05.31"`) | Date-precise but noisy; tests pinning are date-sensitive. | |

**User's choice:** `YYYY.MM.PATCH` (Recommended)
**Notes:** Phase 8 ships `"2026.05.0"`.

---

## Mini-BFO class scope

| Option | Description | Selected |
|--------|-------------|----------|
| 9 classes — exit-criterion list | Continuant, IndependentContinuant, SpecificallyDependentContinuant, GenericallyDependentContinuant, Role, Occurrent, Process, Quality, Disposition. Matches ROADMAP exit criterion 4 + PRINCIPLE-07. | ✓ |
| 7 classes — PRD §7.2 verbatim | DependentContinuant umbrella; no SDC/GDC split; includes Event. Phase 9 P7 classifier inherits gap. | |
| Defer Quality + Disposition to Phase 9 | Ship 7-class set now; add 2 later. PHASE-8 verification gate becomes a moving target. | |

**User's choice:** 9 classes (Recommended)
**Notes:** PRD §7.2 needs amendment (drops `fi:Event`, adds SDC/GDC/Quality/Disposition). Captured as a `<specifics>` note in CONTEXT.md.

---

## TTL file layout

| Option | Description | Selected |
|--------|-------------|----------|
| Split: predicates / classes / bfo_spine / bfo_mapping / shapes | 5 files; each has own owl:versionIRI; easy review/diff; selective import. | ✓ |
| Single file + bfo_mapping + shapes | 3 files; faster load. 600+ line monoliths. | |
| Single ontology with internal sections | Comment-divided monolith + bfo_mapping. Minimal file count. | |

**User's choice:** Split layout (Recommended)
**Notes:** Under `src/folio_insights/vocab/`.

---

## VOCAB-05 supersession query surface

| Option | Description | Selected |
|--------|-------------|----------|
| Predicates + library helper + SPARQL template | Smallest clean landing; `--as-of` CLI deferred to Phase 11/12 where it has a real home. | ✓ |
| Predicates + library helper + `folio-insights query --as-of` subcommand | Full end-to-end surface now; risk of churn when query's real home lands. | |
| Predicates + SHACL semantics only | No helper; VOCAB-05 `--as-of` exit becomes "deferred" with roadmap amendment. | |

**User's choice:** Predicates + helper + template (Recommended)
**Notes:** ROADMAP exit criterion 5 needs an annotation noting the CLI flag is deferred to Phase 11/12.

## `query_as_of` helper location

| Option | Description | Selected |
|--------|-------------|----------|
| `folio_insights/temporal/as_of.py` — new module | Pure single-responsibility module; Phase 11/12 imports without dragging vocab/. | ✓ |
| `folio_insights/vocab/query_as_of.py` | Mixes data and behavior in vocab/. | |
| `folio_insights/revision/query_as_of.py` | Mixes read+write seams; less obvious home for future temporal queries. | |

**User's choice:** `temporal/as_of.py` (Recommended)
**Notes:** Aligns with D-04 dep-leak discipline (each package has one job).

---

## Drift fixes (PRD-alignment audit)

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 8 vocab matches PRD §7.1; fix Phase 2–7 drift in-phase | Audits every `fi:*` predicate; mismatches fixed with regression tests in Phase 8. | ✓ |
| Phase 8 vocab matches what code emits today; amend PRD | PRD becomes moving target; doesn't help if Phase 2–7 made a wrong call. | |
| Defer drift-fixes to Phase 8.1 | SHACL validation on existing artifacts fails until 8.1. | |

**User's choice:** Fix in-phase (Recommended)
**Notes:** Scope discipline locked in D-13 — a fix is in-scope ONLY if it changes TTL or an envelope/Pydantic field declaration. Renames/refactors deferred.

---

## Claude's Discretion

- Exact `bfo:` IRI binding convention in `bfo_mapping.ttl` (per-class vs ontology-level)
- Per-predicate SHACL range/domain shapes in `shapes.ttl` (which need belts beyond `VocabPinShape`)
- Test layout under `tests/vocab/` and `tests/temporal/`
- Whether `query_as_of` accepts `Graph | Store` polymorphically or only `Graph`

## Deferred Ideas

- `--as-of <date>` CLI subcommand — Phase 11/12
- v1 OWL export → v2 prefix migration — never (greenfield cover)
- Cross-vocab `owl:equivalentProperty` bridges to LKIF/LegalRuleML/etc. — future phase, community demand only
- `folio-insights export --include-vocab` CLI flag — planner's call
- BFO classifier (P7) — Phase 9
- Performance benchmarking of `query_as_of` — Phase 0 gates post-vocab-load
- JSON-LD context file for v2 vocab — Phase 12 UI follow-up
