# Phase 8: FOLIO v2 Vocab + Mini-BFO Spine (§7) - Context

**Gathered:** 2026-05-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship the **FOLIO v2 TTL vocabulary** (`fi:*` predicates + classes), the **9-class mini-BFO spine** with companion **`bfo_mapping.ttl`** documenting alignment to BFO 2020, and **version-pin enforcement** so every shard declares which vocab version it was minted against.

What Phase 8 delivers — concrete and locked:

1. **A new Python package `src/folio_insights/vocab/`** with **5 TTL files** + a `VOCAB_VERSION` module constant + importlib.resources-backed loaders.
2. **All `fi:*` predicates and classes from PRD §7.1–§7.2 defined in TTL** — analogia, distinguo, subalternation, elaboration, dependencies, closure, framework, epistemic status, predication mode, supersession, valid-time, contest, attestations, role, content-edit, provenance-hash.
3. **9-class mini-BFO spine** (Continuant, IndependentContinuant, SpecificallyDependentContinuant, GenericallyDependentContinuant, Role, Occurrent, Process, Quality, Disposition) + a companion `bfo_mapping.ttl` with `owl:equivalentClass` rows to BFO 2020 IRIs (`bfo:BFO_*`).
4. **`fi:vocabVersion` pin** added as a required field on the **base shard envelope** + Pydantic validator (refuses mismatched value) + SHACL `fi:VocabPinShape` belt in `vocab/shapes.ttl`. Two-belt enforcement matching the Phase 6/7 convention.
5. **`fi:supersedes` / `fi:supersededBy` predicates** wired end-to-end: TTL definition + a new `folio_insights/temporal/as_of.py` library helper (`query_as_of(graph, predicate, at_date) -> rows`) + a documented SPARQL helper template at `docs/query-as-of.md`. NO new CLI subcommand in Phase 8 — `--as-of <date>` ships when its real home lands (Phase 11/12).
6. **Drift audit:** every `fi:*` predicate Phase 2–7 emits today is cross-checked against PRD §7.1; mismatches (e.g., a Literal where PRD says ObjectProperty) are fixed in this phase with regression tests.

**Critical scoping notes:**
- **FOLIO canonical IRIs (`https://folio.openlegalstandard.org/`) are UNTOUCHED.** Only the FOLIO Insights extension prefix moves. v1 OWL export's reference to the upstream FOLIO ontology stays exactly as-is.
- **v1's legacy FI-extension prefix (`https://folio.openlegalstandard.org/modules/folio-insights/`) is FROZEN.** Used only by the v1 OWL export pipeline (`services/owl_serializer.py`, `export/shapes.ttl`). No v2 logic grafts onto these paths.
- **Phase 8 ships TTL + envelope + helper. NOT a new triplestore (Phase 11). NOT a UI surface (Phase 12). NOT the P7 BFO classifier (Phase 9).**

</domain>

<decisions>
## Implementation Decisions

### Namespace + IRI

- **D-01: Canonical `fi:` IRI = `https://folio-insights.aleainstitute.ai/vocab/`** for the FOLIO Insights v2.0 extension vocabulary. Matches PRD §7.1 verbatim. Phase 0 (bench/generator.py) and Phase 1 (polysemy/distinguo.py + similarity_query.py) already write this prefix — no rework needed in those files; Phase 8 just bakes the canonical TTL behind them.
- **D-01a: FOLIO canonical IRIs (`https://folio.openlegalstandard.org/`) MUST NOT be touched.** The upstream alea-institute FOLIO ontology is sacred. Phase 8 must NOT rewrite, alias, or shim the canonical FOLIO concept IRIs. Any code that does will be reverted on review.
- **D-01b: v1's `https://folio.openlegalstandard.org/modules/folio-insights/` extension prefix is FROZEN** — used only by the v1 OWL export pipeline (`services/owl_serializer.py`, `export/shapes.ttl`). Phase 8 adds a `# v1-legacy — DO NOT migrate to v2 prefix` marker comment at the top of each file so future contributors don't accidentally graft v2 logic onto these paths. No bridge axioms, no dual-emission, no rewrite. Greenfield-on-master is the cover.

### Version pinning

- **D-02: `VOCAB_VERSION` is a module constant in `folio_insights.vocab.__init__.py`.** Phase 8 ships `VOCAB_VERSION = "2026.05.0"` (CalVer `YYYY.MM.PATCH`). The patch dimension lets the vocab bump mid-month without a release-month skip if a typo or range correction lands.
- **D-03: `vocab_version` is a required field on the base shard envelope** with `default_factory=lambda: VOCAB_VERSION`. A Pydantic `field_validator` refuses construction if the supplied value doesn't equal the module constant. Symmetrical with how Phase 7's `corpus`/`position` fields work on `_BaseEvent`.
- **D-04: SHACL belt: `vocab/shapes.ttl::fi:VocabPinShape`** — a `sh:NodeShape` targeting every shard class that requires the `fi:vocabVersion` predicate be present and equal to the current `VOCAB_VERSION`. Two-belt enforcement: envelope catches typos/mismatches at construction; SHACL catches smuggled-in raw triples at storage/export.
- **D-05: `owl:versionIRI` semantics.** Each of the 5 vocab TTL files carries its own `owl:versionIRI` that includes `VOCAB_VERSION` (e.g. `<https://folio-insights.aleainstitute.ai/vocab/2026.05.0/predicates>`). Lets downstream consumers pin to a specific vocab snapshot independently per file.

### Mini-BFO scope

- **D-06: Ship the 9-class mini-BFO spine** per ROADMAP exit criterion 4 verbatim: `Continuant`, `IndependentContinuant`, `SpecificallyDependentContinuant`, `GenericallyDependentContinuant`, `Role`, `Occurrent`, `Process`, `Quality`, `Disposition`. PRD §7.2's 7-class list (which omits SDC/GDC/Quality/Disposition and adds Event) is amended via Phase 8: SDC/GDC supersede the umbrella `DependentContinuant`; Quality + Disposition land now so Phase 9's P7 BFO classifier doesn't inherit a gap; `Event` is folded into `Process` (BFO 2020 uses `process_boundary` only at the mapping layer).
- **D-07: `bfo_mapping.ttl` is exhaustive.** Every one of the 9 mini-BFO classes gets an explicit `owl:equivalentClass bfo:BFO_xxxxxxx` row + `rdfs:comment` documenting the alignment. No `rdfs:seeAlso` shortcuts — full equivalence so a downstream consumer that loads both files gets seamless interop without prose-doc lookups.

### TTL file layout + loaders

- **D-08: Split TTL layout under `src/folio_insights/vocab/`:**
  - `predicates.ttl` — all properties from PRD §7.1 (analogia, distinguo, subalternation, elaboration, dependencies, closure, framework, epistemic status, predication mode, supersession, valid-time, contest, attestations, role, content-edit, provenance-hash).
  - `classes.ttl` — non-BFO classes from PRD §7.2 (CommonAxiom, Postulate, Definition, MeaningPostulate, Framework + governance classes: RoleAssertion, ContentEdit, GovernanceLog, AttestedSignature, ContestVote).
  - `bfo_spine.ttl` — the 9 mini-BFO classes.
  - `bfo_mapping.ttl` — owl:equivalentClass rows to BFO 2020.
  - `shapes.ttl` — `fi:VocabPinShape` + per-predicate range/domain SHACL shapes that don't already live in a Phase-7 governance shape file.
- **D-09: Loaders use `importlib.resources`.** A `folio_insights.vocab.load_graph(*, include_bfo_mapping=False) -> rdflib.Graph` helper returns the merged graph as a single `rdflib.Graph` for SHACL validation. `bfo_mapping.ttl` is opt-in (downstream consumers who don't care about full BFO interop don't pay the parse cost). A parallel `load_pyoxigraph_store()` returns a pyoxigraph in-memory `Store` for SPARQL queries — round-trip parity validated at module import via a smoke test.

### Supersession query surface (VOCAB-05)

- **D-10: Phase 8 ships predicates + library helper + SPARQL template. NO new CLI flag.**
  - `fi:supersedes` / `fi:supersededBy` defined in `predicates.ttl` (`owl:inverseOf` pair).
  - `folio_insights/temporal/as_of.py` exports `query_as_of(graph, predicate, at_date) -> list[Row]` — returns the predicate's object as it was on `at_date`, walking the supersession chain backward using `fi:validTimeStart` / `fi:validTimeEnd`. Pure rdflib-based; no pyoxigraph dependency.
  - `docs/query-as-of.md` — prose + a 20-line SPARQL pattern Phase 11/12 can copy.
  - SHACL guard `fi:SupersessionAlignmentShape` in `vocab/shapes.ttl` enforces: when shard A `fi:supersedes` B, B's `fi:validTimeEnd` must equal A's `fi:validTimeStart`.
- **D-11: `--as-of <date>` CLI flag is OUT of Phase 8 scope.** Deferred to Phase 11 (triplestore) or Phase 12 (UI) where it has a real query surface. Phase 8 leaves a tracking todo with the exit-criterion cross-reference.

### Drift fixes (PRD-alignment audit)

- **D-12: Every `fi:*` predicate emitted by Phase 2–7 is audited against PRD §7.1.** Mismatches (e.g., a `Literal` range where PRD says `ObjectProperty`; a missing `owl:inverseOf`; a wrong `rdfs:range`) are fixed in Phase 8 with one regression test per fix. Specific suspects identified during scout:
  - `fi:hasRole` — PRD §7.1 says `DatatypeProperty` with values `extractor|reviewer|arbiter|corpus_admin` (a literal-range enum). Confirm Phase 7 `roles.py` matches; if it emits an ObjectProperty pointing at a Role class, the fix is on the Phase 7 side.
  - `fi:signedAction` — `DatatypeProperty` with the 13-value `SignedAction` Literal range. Phase 7 envelope already uses this as a `Literal`; Phase 8 TTL must declare the `sh:in` enumeration matching.
  - `fi:GovernanceLog` — class definition lands in `classes.ttl`; Phase 7's `governance_log_shape.ttl` already targets it.
  - `fi:supersedes` / `fi:supersededBy` — must be a single `owl:inverseOf` pair; Phase 7 `supersede.py` event must emit ONLY one of the two predicates (the other is inferred via inverse reasoning).
- **D-13: Scope discipline for drift fixes.** A fix is in-scope ONLY IF it changes the TTL or an envelope/Pydantic field declaration. Renames, broader refactors, or new features triggered by the audit are deferred. Each in-scope fix gets its own atomic commit `fix(08): align fi:X with PRD §7.1`.

### Claude's Discretion

- Exact `bfo:` IRI bindings in `bfo_mapping.ttl` (the planner can pick the BFO 2020 release version; `bfo:` namespace is conventionally `http://purl.obolibrary.org/obo/bfo.owl#` or the per-class IRIs `http://purl.obolibrary.org/obo/BFO_*`). Planner picks the convention; tests verify round-trip parses with rdflib + pyoxigraph.
- The per-predicate SHACL range/domain shapes in `shapes.ttl` (which predicates need explicit `sh:datatype` vs `sh:class` constraints beyond the basic `fi:VocabPinShape`). Planner judges what's worth a belt vs what's already enforced by the Pydantic envelope.
- Test layout under `tests/vocab/` and `tests/temporal/` — mirror the Phase 7 layout (per-decision file naming).
- Whether the `query_as_of` helper accepts `Graph | Store` (polymorphic) or only `Graph` (rdflib-only, V1 minimum). Planner picks based on what Phase 11 will actually call.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Primary spec
- `PRD-v2.0-draft-2.md` §7 — entire vocabulary chapter; the source of truth for every predicate and class definition
- `PRD-v2.0-draft-2.md` §7.1 — predicate definitions in Turtle (analogia, distinguo, subalternation, elaboration, dependencies, closure, framework, epistemic_status, predication_mode, supersession, valid-time, contest, attestations, role, content-edit, provenance-hash)
- `PRD-v2.0-draft-2.md` §7.2 — class definitions (axiom tiers, framework, mini-BFO 7 classes — Phase 8 amends to 9 per D-06)
- `PRD-v2.0-draft-2.md` §21.2 — mini-BFO scope decision (mini + companion bfo_mapping.ttl; NOT hard BFO import)
- `PRD-v2.0-draft-2.md` §21.9 — supersession ≠ retraction; valid-time semantics; old shard remains queryable

### Requirements
- `.planning/REQUIREMENTS.md` § VOCAB-01..VOCAB-05 — the 5 ship-critical requirements with acceptance gates
- `.planning/ROADMAP.md` § Phase 8 — exit criteria 1–5, especially the 9-class BFO list and the `--as-of` query gate

### Pitfalls + research
- `.planning/research/PITFALLS.md` Pitfall D2 — `fi:` IRI determinism (idempotent re-extraction must produce identical IRIs)
- `.planning/research/PITFALLS.md` Pitfall D7 — pyoxigraph 0.5.7 dropped rdf-star in favor of rdf-12 — RDF-star patterns from Wikidata tutorials silently return empty
- `.planning/research/PITFALLS.md` Pitfall D3 — Pydantic discriminated unions: every variant must declare its tag literally + `Annotated[Union[...], Field(discriminator='shard_type')]`

### Prior phase artifacts (read for drift audit + interop)
- `.planning/phases/02-shard-envelope/02-SUMMARY.md` — shard envelope structure; D-12 audit targets this
- `.planning/phases/04-iri-scheme-6-3/04-SUMMARY.md` — provenance-hash IRI scheme; `fi:provenanceHash` definition cross-check
- `.planning/phases/05-content-versioning-6-4/05-SUMMARY.md` — `fi:validTimeStart`/`End`/`fi:transactionTime` semantics + supersession infrastructure
- `.planning/phases/06-did-substrate-6-5/06-SUMMARY.md` — `fi:AttestedSignature`, `fi:did`, `fi:signature`, `fi:overContentHash`, `fi:signingKeyId` already wired
- `.planning/phases/07-governance-model-3-1/07-SUMMARY.md` (all 7 plan summaries) — every `fi:*` governance predicate Phase 8 must define is referenced here; the drift audit (D-12) starts here
- `.planning/phases/07-governance-model-3-1/07-CONTEXT.md` — D-04/D-05/D-13 + the GOV-04 three-way disambiguation that pins `fi:contests` vs `fi:supersedes` vs `fi:retracts` as distinct predicates

### Project-level
- `.planning/PROJECT.md` — milestone goal + tech stack lock (rdflib, pyoxigraph 0.5.7, pyshacl)
- `.planning/v2.0-MILESTONE-BRIEF.md` — Phase 8's milestone-level scope row + the `owl:versionIRI` strategy note

### Companion BFO source (read for D-07 mapping rows)
- BFO 2020 PURL: `http://purl.obolibrary.org/obo/bfo/2020/bfo.owl` — the IRIs for `bfo:BFO_0000002` (Continuant), `bfo:BFO_0000003` (Occurrent), `bfo:BFO_0000004` (IndependentContinuant), `bfo:BFO_0000019` (Quality), `bfo:BFO_0000016` (Disposition), `bfo:BFO_0000020` (SpecificallyDependentContinuant), `bfo:BFO_0000031` (GenericallyDependentContinuant), `bfo:BFO_0000023` (Role), `bfo:BFO_0000015` (Process)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`src/folio_insights/bench/generator.py:51–55`** — already declares the canonical prefix as Python constants `FI`, `CORPUS`, `SHARD`, `CONCEPT`, `FRAMEWORK`. **Promote these to `folio_insights.vocab.NAMESPACES`** (a `Mapping[str, rdflib.Namespace]`) so bench/generator, polysemy, governance, and future Phase 11/12 all read from one source. The file's own comment says: *"MUST match Phase 8 fi:* when those land; for Phase 0 the generator uses stable canonical IRIs."* Phase 8 closes this loop.
- **`src/folio_insights/polysemy/similarity_query.py:37`** + **`polysemy/distinguo.py:33`** — already encode the canonical prefix in SPARQL `PREFIX fi:` declarations. After Phase 8, these can switch from inline string literals to `from folio_insights.vocab import FI_PREFIX`. Optional code-tidiness fix; not required for Phase 8 success.
- **`src/folio_insights/shards/envelope.py`** — Phase 2 base envelope; Phase 7 added 13 governance event variants. Phase 8 adds:
  - `vocab_version: str = Field(default_factory=lambda: VOCAB_VERSION)` to `_BaseEvent` (or the equivalent base shard envelope class — verify in plan-phase which is the right base).
  - A `field_validator("vocab_version")` that refuses mismatched values.
- **`src/folio_insights/governance/shapes/*.ttl`** — Phase 7 SHACL shapes use the canonical `fi:` prefix in `@prefix` declarations. Phase 8 must NOT touch these; they auto-align once `vocab/predicates.ttl` defines the predicates these shapes target.
- **`src/folio_insights/store/pyoxigraph_store.py`** + **`store/__init__.py`** — Phase 4 pyoxigraph store; Phase 8 vocab graph must load into this store without errors (round-trip test via `tests/vocab/test_pyoxigraph_roundtrip.py`).
- **`src/folio_insights/services/shacl_validator.py`** — Phase 1 SHACL validator; Phase 8 vocab's `shapes.ttl` plugs into the same pipeline.

### Established Patterns

- **Two-belt enforcement** (Phase 6/7 convention) — Pydantic catches at construction, SHACL catches at the storage layer. Phase 8 D-04 follows this verbatim.
- **`@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/>`** is already the project convention in 5+ files. Phase 8 codifies the prefix as `folio_insights.vocab.FI_PREFIX`.
- **Per-Phase TTL co-location** — Phase 7 ships `src/folio_insights/governance/shapes/*.ttl` alongside the governance Python package. Phase 8 mirrors: `src/folio_insights/vocab/*.ttl` alongside the new `vocab` Python package.
- **`importlib.resources` for static asset loading** — Phase 1's `polysemy/fixture_loader.py` already uses this for fixture TTL files. Phase 8 reuses the same pattern for the 5 vocab TTL files.
- **`owl:versionIRI` per file** — v1 `services/owl_serializer.py` already emits per-ontology versionIRI; Phase 8 carries this forward into each of the 5 split files.
- **`@prefix` discipline in shapes** — Phase 7 SHACL shapes carry only the prefixes they need, never a kitchen-sink import. Phase 8's `shapes.ttl` follows the same minimal-imports rule.

### Integration Points

- **Base envelope add** (`src/folio_insights/shards/envelope.py`) — D-03 lands a new required field. Every Phase 2–7 test fixture that constructs a shard inherits the default; tests that construct envelopes via raw dict-passing get a 1-line patch.
- **Bench generator** (`src/folio_insights/bench/generator.py`) — must emit `fi:vocabVersion "2026.05.0"` on every generated shard for the post-Phase-8 generator run. Add a line near the `FI`/`CORPUS`/`SHARD` constants.
- **`folio-insights export` command** — v1 export path frozen; if a `folio-insights export --vocab` flag is desired, it lands in a follow-up phase (deferred). PRD §7 acceptance test (`folio-insights export --include-vocab` emits the new vocab as a separate TTL file) is the ONLY CLI surface Phase 8 touches — implement it minimally if the user wants the acceptance gate green here, otherwise defer.
- **`folio_insights/temporal/as_of.py`** (D-10) — new module. Imports rdflib only. Has zero coupling to vocab/, revision/, or store/ (D-04 dep-leak discipline mirrors Phase 7 governance).
- **`docs/query-as-of.md`** — new doc. Prose + a 20-line SPARQL pattern using `fi:supersedes` / `fi:validTimeStart`/`End`. Phase 11/12 will reference this when wiring the actual `--as-of` flag.

</code_context>

<specifics>
## Specific Ideas

- **FOLIO canonical IRIs are sacred** (user verbatim emphasis). The `https://folio.openlegalstandard.org/` prefix in `services/owl_serializer.py:17` (`FOLIO = Namespace("https://folio.openlegalstandard.org/")`) refers to the upstream alea-institute FOLIO ontology. Phase 8 must not rewrite, alias, or shim this. If anyone proposes to: revert immediately.
- The legacy FI-extension prefix (`https://folio.openlegalstandard.org/modules/folio-insights/` in `services/owl_serializer.py:18-19` and `export/shapes.ttl:7`) IS in scope to mark legacy — but ONLY with a comment marker, not a content rewrite. Add `# v1-legacy — DO NOT migrate to v2 prefix (Phase 8 D-01b)` at the top of each file.
- `VOCAB_VERSION = "2026.05.0"` is the Phase 8 shipping value. Future patch bumps land as `"2026.05.1"`, `"2026.05.2"`, etc. — a patch bump must also bump `owl:versionIRI` in each affected TTL file.
- Mini-BFO maps to BFO 2020 — NOT BFO Classic, NOT BFO 1.1. The PURL is `http://purl.obolibrary.org/obo/bfo/2020/bfo.owl`. Planner must verify the IRIs in `bfo_mapping.ttl` resolve.
- The 9-class mini-BFO list explicitly DROPS PRD §7.2's `fi:Event` class (folded into `Process` per D-06) and ADDS SDC, GDC, Quality, Disposition that PRD §7.2 doesn't list. Plan-phase must annotate the divergence so PRD §7.2 can be amended in the same PR or a follow-up doc-fix.

</specifics>

<deferred>
## Deferred Ideas

- **`--as-of <date>` CLI subcommand** — exit criterion 5 calls for this end-to-end; Phase 8 D-11 defers to Phase 11 (triplestore) or Phase 12 (UI) where it has a real query surface. Phase 8 leaves a tracking todo. **Track:** ROADMAP exit criterion 5 must be amended to read "predicates + library helper + SPARQL template ship in Phase 8; `--as-of` CLI/UI surface ships in Phase 11/12."
- **v1 OWL export → v2 prefix migration** — explicitly out of scope (greenfield-on-master means no v1 corpora to migrate). v1 paths stay legacy-frozen forever.
- **Cross-vocab `owl:equivalentProperty` bridges to other legal ontologies** (LKIF, LegalRuleML, etc.) — not in PRD §7. Future phase if community demand emerges.
- **`folio-insights export --include-vocab` CLI flag** — PRD §7 acceptance test mentions this surface; can be implemented minimally in Phase 8 OR deferred to a follow-up phase. Planner can decide based on test-effort budget; D-10's library helper + SPARQL template is the minimum-viable surface for VOCAB-05.
- **BFO classifier (P7)** — Phase 9 work; mini-BFO spine ships here so Phase 9 inherits a complete vocab.
- **Performance benchmarking of `query_as_of`** — pure correctness in Phase 8; Phase 0 gates re-check performance once the vocab loads in pyoxigraph. If `bfo_mapping.ttl` parse adds > 50ms to startup, revisit `importlib.resources` vs lazy-loading in Phase 11.
- **JSON-LD context file for v2 vocab** — analogous to `src/folio_insights/export/context.jsonld` but for the new prefix. Useful for browser-side RAG consumers. Deferred to a Phase 12 (UI) follow-up.

</deferred>

---

*Phase: 8-folio-v2-vocab-mini-bfo-spine-7*
*Context gathered: 2026-05-31*
