# Phase 02: Shard Envelope — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-24
**Phase:** 02-shard-envelope
**Areas discussed:** Identity minting scope, Bitemporal semantics, Discriminated-union shape, Immutability enforcement

---

## Gray Area Selection

**Question:** Which areas do you want to discuss for Phase 02 Shard Envelope?

| Option | Description | Selected |
|--------|-------------|----------|
| Identity minting scope | Phase 2 mints IRIs or defers to Phase 4 | ✓ |
| Bitemporal semantics | Nullability + transaction_time source | ✓ |
| Discriminated-union shape | Single class vs Union of subtypes | ✓ |
| Immutability enforcement | frozen fields vs whole-model vs validator | ✓ |

**User's choice:** All four areas selected.

---

## Identity Minting Scope

### Q1. Phase 2 scope for identity fields (shard_iri + provenance_hash): mint and populate them here, or emit placeholders and mint in Phase 4?

| Option | Description | Selected |
|--------|-------------|----------|
| Mint in Phase 2 | Include mint_shard_iri() + determinism property test. Phase 4 narrows to collision detection + nightly re-hash. | ✓ |
| Defer to Phase 4 | Phase 2 emits `iri:placeholder-<uuid>` and `sha256:placeholder`. Simpler envelope scope but weaker round-trip tests. | |
| Mint but skip collision checks | Phase 2 mints and hashes; collision detection + nightly re-hash stay in Phase 4. | |

**User's choice:** Mint in Phase 2 (recommended).

### Q2. Provenance-hash recipe (the input to SHA-256 that derives shard_iri)?

| Option | Description | Selected |
|--------|-------------|----------|
| Normalize inputs | `SHA-256(NFC(rfc3986_normalize(source_uri)) + "\n" + NFC(source_span).strip())`. LF only. Property-test determinism across 1000 runs. | ✓ |
| Raw inputs | SHA-256 of `source_uri + "\n" + source_span` verbatim. Faster; risks hash drift if upstream normalizes inconsistently. | |
| Include extractor DID in hash | SHA-256 of `DID + "\n" + source_uri + "\n" + source_span`. Prevents cross-extractor collisions; re-extraction produces new shard for identical text. | |

**User's choice:** Normalize inputs (recommended).

---

## Bitemporal Semantics

### Q3. Bitemporal field nullability — how do valid_time_start / valid_time_end behave?

| Option | Description | Selected |
|--------|-------------|----------|
| Both nullable | `valid_time_start: datetime \| None = None`, `valid_time_end: datetime \| None = None`. Null = unbounded. Phase 13 SPARQL `--as-of` treats null_start as −∞, null_end as +∞. | ✓ |
| At least one required | @model_validator enforces at least one of start/end is set. Prevents totally-unbounded shards. | |
| Both required, use sentinels | Start defaults to 0001-01-01; end defaults to 9999-12-31. Simpler SPARQL; sentinels leak into UI and exports. | |

**User's choice:** Both nullable (recommended).

### Q4. transaction_time — when and how is it set?

| Option | Description | Selected |
|--------|-------------|----------|
| Model default_factory at construction | `Field(default_factory=lambda: datetime.now(UTC))`. Overrideable for historical ingest + replay. tz-aware UTC always. | ✓ |
| Externally injected at persistence | Phase 13 storage layer writes it on insert. Pro: single source of truth. Con: Phase 2 round-trip tests miss the field; leaks Phase 13 dep into Phase 2. | |
| Required-at-construction, no default | Caller must pass transaction_time explicitly. Forces deliberate choice; annoying for 90% "now" case. | |

**User's choice:** Model default_factory at construction (recommended).

---

## Discriminated-Union Shape

### Q5. Discriminated-union shape — one Shard class or five subtype classes?

| Option | Description | Selected |
|--------|-------------|----------|
| Union of 5 subtypes + Discriminator | `Annotated[Union[...5 subtypes...], Field(discriminator='shard_type')]`. Phase 2 ships ShardEnvelope + 5 stub subtype classes; Phase 3 adds subtype-specific fields. | ✓ |
| Single class with Literal tag + optional subtype fields | One fat Shard class; @model_validator enforces 'when shard_type=X, fields Y required'. Simpler serialization; fat class in Phase 3. | |
| Single envelope + composed payload | `Shard.envelope` + `Shard.payload: Union[...]`. Cleaner separation but doubles model depth. | |

**User's choice:** Union of 5 subtypes + Discriminator (recommended).

### Q6. Can shard_type mutate? (E.g., hypothesis → simple_assertion on promotion)

| Option | Description | Selected |
|--------|-------------|----------|
| No — new shard via supersedes chain | shard_type is effectively immutable. Promotion creates a new shard with `supersedes = <old_iri>`. Matches PRD §6.4 / §7 supersession. | ✓ |
| Yes — mutable with ContentEdit audit | shard_type can change in place; every transition appends a ContentEdit. Simpler data model; blurs identity. | |
| Yes, but only hypothesis → attested | Narrow exception for promotion flow; all other transitions require supersession. | |

**User's choice:** No — new shard via supersedes chain (recommended).

---

## Immutability Enforcement

### Q7. Immutability enforcement — how do we prevent edits to shard_iri, provenance_hash, source_uri, source_span, extracted_at, first_extractor_did?

| Option | Description | Selected |
|--------|-------------|----------|
| Per-field frozen | `Field(frozen=True)` on each of the 6 immutable fields. Pydantic raises FrozenFieldError on assignment. Clean, minimal ceremony. | ✓ |
| Whole-model frozen + separate mutable container | `ConfigDict(frozen=True)` on ShardEnvelope; mutable fields live in separate ShardState model. Strongest guarantee; two-model ceremony everywhere. | |
| @model_validator post-init guard | Not frozen at Pydantic layer; validator compares new state to snapshot and rejects changes. More flexible; more runtime code. | |

**User's choice:** Per-field frozen (recommended).

### Q8. Mutable-with-audit fields (sense, reference, elaborates, layer, framework_id) — how are edits recorded?

| Option | Description | Selected |
|--------|-------------|----------|
| Append to content_edits on each change | In-place assignment; ContentEdit (field_name, old, new, edited_at, editor_did) appends on mutation. Phase 2 ships field + minimal add_edit() helper. Phase 5 ships full validator + SHACL. | ✓ |
| Phase 2 adds fields only, no edit recording yet | Declare content_edits field; Phase 5 wires enforcement. Clean boundary; Phase 2 tests could miss audit-leak bug. | |
| Immutable fields only in Phase 2 | Whole envelope frozen in Phase 2; Phase 5 un-freezes + adds ContentEdit. Breaks 15-field spec; awkward Phase 5 refactor. | |

**User's choice:** Append to content_edits on each change (recommended).

---

## Done Check

**Question:** We've covered the 4 selected areas. Any remaining gray areas to explore before I write CONTEXT.md?

| Option | Description | Selected |
|--------|-------------|----------|
| I'm ready for context | 8/8 recommended picks captured. RDF metadata and per-path required/optional flow through naturally (Phase 11/13 owns RDF; Phase 7 owns promotion). | ✓ |
| Discuss RDF metadata + required/optional split | Two more questions on json_schema_extra hints and extraction-vs-promotion field splits. | |
| Explore more gray areas | Freeform continuation. | |

**User's choice:** I'm ready for context (recommended).

---

## Claude's Discretion

Four small implementation details were deferred to the planner:
- Module location (`src/folio_insights/shards/` vs `src/folio_insights/core/shards.py`)
- Test file layout (split by concern vs single file)
- `mint_shard_iri` as classmethod vs standalone function
- `@model_validator` vs `@field_validator` for shard_type pinning

## Deferred Ideas

- RDF `json_schema_extra` hints on fields — Phase 11 (SHACL) / Phase 13 (storage)
- Per-extraction-path required/optional split — Phase 7 (governance) / Phase 10 (Stage 8 Shard Minter)
- v1 `KnowledgeUnit` → v2 `Shard` migration helper — greenfield v2.0 (no migration needed)
- `AttestedSignature` sub-model full definition — Phase 6 (DID substrate); Phase 2 ships a stub
- `framework_id` year-versioning — not year-versioned per PRD §6.1; time-scoping is shard-level
