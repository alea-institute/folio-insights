# Phase 8 Plan 08-04 — Drift Audit Report (D-12 / D-13)

**Date:** 2026-05-31
**Auditor:** Plan 08-04 executor (Wave 3, single agent)
**Test artifact:** `tests/vocab/test_predicate_drift_audit.py`
**Scope discipline:** D-13 — atomic per-mismatch commits; renames / broader refactors / new features deferred.

## Methodology

`tests/vocab/test_predicate_drift_audit.py` scans every `*.py` and `*.ttl` file under

```
src/folio_insights/{governance, shards, polysemy, bench, revision, temporal}
```

with the regex `fi:([a-zA-Z][a-zA-Z0-9_]*)`, deduplicates the local-name set
(`EMITTED_PREDICATES`), then cross-checks it against the set of local names
declared in the loaded vocab graph (`DECLARED_PREDICATES`, from
`folio_insights.vocab.load_graph(include_bfo_mapping=True)`). The accepted
declaration types are:

- `owl:ObjectProperty` / `owl:DatatypeProperty` / `owl:AnnotationProperty`
- `owl:Class`
- `sh:NodeShape`
- `owl:NamedIndividual`

Each emitted local name must be either declared in the vocab graph or
explicitly waived in `DOCUMENTED_WAIVERS` with a citation back to this
report.

## Summary

| Metric | Count |
| --- | ---: |
| Total emitted predicates (Phase 2–7 sources) | 67 |
| Total declared in vocab graph (before audit) | 68 |
| Total declared in vocab graph (after audit) | 95 |
| In-scope fixes applied | 2 atomic commits (1 for distinction-kind enum + 1 for 26 missing predicates) |
| Deferred mismatches | 11 waivers |
| 4 D-12 named suspects | all PASS (Plan 08-01 already covered them) |

## Audited Predicates

### D-12 named suspects — all PASS, no fix required

| Predicate | PRD §7.1 expected | Observed in vocab | Disposition |
| --- | --- | --- | --- |
| `fi:hasRole` | `owl:DatatypeProperty` + `sh:in` enum {extractor, reviewer, arbiter, corpus_admin} | DatatypeProperty in predicates.ttl L184; `fi:RoleEnumShape` in shapes.ttl L96 with 4-value `sh:in` | no-change |
| `fi:signedAction` | `owl:DatatypeProperty` + `sh:in` 13-value enum mirroring `SignedAction` Literal | DatatypeProperty in predicates.ttl L172; `fi:SignedActionEnumShape` in shapes.ttl L62 with 13-value `sh:in` | no-change |
| `fi:GovernanceLog` | `owl:Class` in classes.ttl | Class in classes.ttl L112 | no-change |
| `fi:supersedes` / `fi:supersededBy` | `owl:ObjectProperty` pair with `owl:inverseOf` | Both in predicates.ttl L109/L116 with mutual `owl:inverseOf` | no-change |

### In-scope fixes applied

| # | Fix | Commit | File | Description |
| --- | --- | --- | --- | --- |
| 1 | Add `fi:DistinctionKindEnumShape` (Route B per Plan 08-04 Task 2 tolerance) | `d5bc180` | `vocab/shapes.ttl` | VOCAB-02 acceptance gate requires the 4 Scotist distinction-kind values (realis, rationis, rationis_cum_fundamento_in_re, analogica) be queryable. `fi:distinctionKind` was declared as DatatypeProperty but the closed-set semantics were not pinned. Added a `sh:in` belt mirroring `fi:RoleEnumShape` / `fi:SignedActionEnumShape` discipline. |
| 2 | Declare 26 missing emitted-but-undeclared predicates in `predicates.ttl` | `4dee874` | `vocab/predicates.ttl` | Phase 2–7 source emitted `fi:*` triples whose properties had no canonical declaration. D-13 in-scope fix: add property declarations only — no Python rename, no shape rewrite, no behaviour change. The Phase 7 per-event SHACL shapes already enforced the range constraints. |

**Predicates added in fix 2** (organised by emission site):

| Group | Predicates | Source |
| --- | --- | --- |
| Phase 7 governance events | `fi:hasEvent`, `fi:event`, `fi:action`, `fi:asof`, `fi:did`, `fi:signedAt`, `fi:signerDid`, `fi:subjectDid`, `fi:shardIri`, `fi:oldShardIri`, `fi:newShardIri`, `fi:cascadePreviewHash`, `fi:newStatus`, `fi:pending`, `fi:position`, `fi:citedIri` (16) | `src/folio_insights/governance/` |
| Phase 5 revision | `fi:seq`, `fi:contentEdits` (2) | `src/folio_insights/revision/` |
| Phase 0 bench-generator | `fi:confidence`, `fi:validFrom` (2) | `src/folio_insights/bench/generator.py` |
| Phase 1 polysemy distinguo | `fi:analogousTo`, `fi:proposedAt`, `fi:proposedBy` (3) | `src/folio_insights/polysemy/distinguo.py` |
| Polysemy fixture-loader / extraction | `fi:axiomSummary`, `fi:sourceDoc`, `fi:termOfArt` (3) | `src/folio_insights/polysemy/fixture_loader.py` |

### Deferred mismatches (DOCUMENTED_WAIVERS)

**Waiver-1 — Per-package SHACL NodeShape identifiers.** Plan 08-01 D-08 split-layout
discipline: only vocab-anchor shapes (`fi:VocabPinShape`, `fi:SignedActionEnumShape`,
`fi:RoleEnumShape`, `fi:SupersessionAlignmentShape`, and now `fi:DistinctionKindEnumShape`)
live in `vocab/shapes.ttl`. Per-event governance shapes stay co-located with the
governance subsystem (`governance/shapes/*.ttl`) so the audit-trail belt is sharper
and the dep-leak guard remains non-vacuous. These shape identifiers appear in
`grep` hits because they are referenced in the governance subsystem's own SHACL
graphs and Python validation entry points, NOT because they should be lifted
into the canonical vocab.

| Waived identifier | Rationale |
| --- | --- |
| `fi:ContestShape` | governance/shapes/contest_shape.ttl |
| `fi:ContestResolutionShape` | governance/shapes/contest_resolution_shape.ttl |
| `fi:PromotionShape` | governance subsystem |
| `fi:RetractionShape` | governance/shapes/retraction_shape.ttl |
| `fi:SupersessionShape` | governance/shapes/supersession_shape.ttl |
| `fi:RoleAssertionShape` | governance/shapes/role_assertion_shape.ttl |
| `fi:RoleRevocationShape` | governance/shapes/role_revocation_shape.ttl |
| `fi:GovernanceLogShape` | governance/shapes/governance_log_shape.ttl |
| `fi:ForwardOnlyShape` | revision/content_edit_shape.ttl |

**Waiver-2 — Test-fixture / runtime sentinels.** These local-names are not vocab
predicates; they are URI-prefix sentinels used by Phase 1 fixture-loader or the
governance audit-log emitter (`urn:fi:event:` style URIs and prototype-cluster
auto-IDs). They do not appear in canonical TTL exports.

| Waived identifier | Rationale |
| --- | --- |
| `fi:PrototypeCluster_` | runtime fixture marker in polysemy/prototype_cluster.py |
| `fi:ShardFixture` | test fixture marker in polysemy/fixture_loader.py |
| `fi:GovernanceEvent` | Phase 7 internal urn-prefix sentinel (`urn:fi:event:<corpus>:<position>`) |

## D-08 split-layout coverage check (drift closure for VOCAB-01)

The vocab graph loaded by `folio_insights.vocab.load_graph(include_bfo_mapping=True)`
contains every Phase 7 governance class that Phase 7 SHACL shapes reference. The
governance shapes in `src/folio_insights/governance/shapes/*.ttl` use `sh:targetClass`
against these `fi:` class IRIs:

- `fi:RoleAssertion`, `fi:RoleRevocation`, `fi:Promotion`, `fi:Demotion`,
  `fi:Contest`, `fi:ContestResolution`, `fi:Supersession`, `fi:Retraction`,
  `fi:ContentEdit`, `fi:GovernanceLog`, `fi:Distinguo`, `fi:AttestedSignature`,
  `fi:ContestVote`

All 13 are declared as `owl:Class` in `vocab/classes.ttl` (`test_vocab_load_smoke.py`
confirms this; `test_GovernanceLog_class_declared` additionally exercises the
critical-path one).

## RDF-star (PITFALLS D7) mitigation

`tests/vocab/test_pyoxigraph_roundtrip.py::test_no_rdf_star_syntax_in_vocab_ttls`
grep-asserts zero `<<` / `>>` triple-term hits across all 5 vocab TTL files.
Verified post-fix: 0 hits across the 5 vocab TTL files.

## `owl:versionIRI` (D-05) pinning

`tests/vocab/test_owl_version_iri.py` parameterises 5 cases (one per TTL file)
asserting each owl:versionIRI matches the canonical pattern
`https://folio-insights.aleainstitute.ai/vocab/2026.05.0/{name}`. All 5 pass.

## Post-audit verification

```sh
$ uv run pytest tests/vocab/ -v
============================== 59 passed in 0.31s ==============================
$ uv run pytest tests/vocab/ tests/temporal/ tests/shards/ tests/bench/ \
    --ignore=tests/bench/test_gate5_digest.py \
    --ignore=tests/bench/test_gate3_image.py \
    --ignore=tests/bench/test_gate4_ssr.py \
    --ignore=tests/bench/test_hermit_harness.py
======================= 243 passed, 34 skipped in 5.70s ========================
```

## PRD-amendment owed

Plan 08-01's SUMMARY already flagged the D-06 9-class vs PRD §7.2 7-class divergence
(dropped `fi:Event`, added SDC, GDC, Quality, Disposition). This audit reaffirms
that owed amendment; no new PRD divergence introduced by Plan 08-04.

Additional minor amendment owed: PRD §7.1.1 should explicitly enumerate the 4
Scotist distinction-kind values as a closed set (the `sh:in` belt Plan 08-04 added
encodes them in the vocab; the PRD prose currently lists them only in the §7.1.1
narrative).
