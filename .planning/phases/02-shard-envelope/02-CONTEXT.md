# Phase 02: Shard Envelope (§6.1) — Context

**Gathered:** 2026-04-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship the 15-field Pydantic `Shard` envelope as the v2.0 core data model with:
- **Round-trip guarantee** — `Shard(**shard.model_dump()) == shard` for every subtype placeholder
- **Discriminated-union guarantee** — invalid subtype tag fails validation with a useful error
- **Bitemporal guarantee** — `valid_time_start`, `valid_time_end`, `transaction_time` round-trip and serialize deterministically

REQ-IDs: **SHARD-01** (envelope + discriminated-union), **SHARD-10** (bitemporal time-scoping).

Every downstream phase (3–16) depends on this shape being correct.

**In scope for Phase 2:**
- `ShardEnvelope` base Pydantic model (15 fields per PRD §6.1)
- Five thin subtype stub classes that pin `shard_type: Literal[...]` discriminator (`SimpleAssertionShard`, `DisputedPropositionShard`, `ConflictingAuthoritiesShard`, `GlossShard`, `HypothesisShard`) — subtype-specific fields land in Phase 3
- `mint_shard_iri()` + provenance-hash derivation with determinism property test
- `ContentEdit` sub-model + `content_edits: list[ContentEdit]` field + minimal `add_edit()` helper (validator + SHACL gate land in Phase 5)
- Immutability enforcement on the 6 identity-and-origin fields via per-field `frozen=True`
- Round-trip + discriminated-union + bitemporal tests

**Out of scope (deferred to listed phases):**
- Subtype-specific fields (Phase 3)
- IRI collision detection + nightly re-hash verification (Phase 4)
- Full `ContentEdit` validator + forward-only SHACL gate (Phase 5)
- DID signing of reviewer attestations (Phase 6)
- Promotion governance (hypothesis → attested) + supersession policy enforcement (Phase 7)
- RDF 1.2 mapping + `json_schema_extra` RDF hints (Phase 11 SHACL, Phase 13 storage)

</domain>

<decisions>
## Implementation Decisions

### Identity Minting (Phase 2 Scope)

- **D-01:** Phase 2 mints `shard_iri` + `provenance_hash` and ships `mint_shard_iri(source_uri, source_span) -> (iri, hash)`. Phase 4 narrows to collision detection + nightly re-hash verification job. Matches PRD §6.1 authoring intent; makes round-trip tests real on day one.
- **D-02:** Provenance-hash recipe:
  ```
  input   = NFC(rfc3986_normalize(source_uri)) + "\n" + NFC(source_span).strip()
  hash    = hashlib.sha256(input.encode("utf-8")).hexdigest()   # 64 hex chars
  iri     = f"urn:folio:shard/{hash[:16]}"                      # first 16 chars of hash
  ```
  - Line separator is `"\n"` (LF only, never CRLF) — cross-platform determinism
  - Unicode normalization: `unicodedata.normalize("NFC", ...)` on both inputs
  - URI normalization: RFC 3986 percent-encoding + lowercase scheme/host; trailing-slash stripping; fragment preserved
  - Property test: same source + same span → same IRI across 1000 random runs (NFC + LF + trim + RFC 3986 applied)

### Bitemporal (SHARD-10)

- **D-03:** `valid_time_start: datetime | None = None`, `valid_time_end: datetime | None = None`. Null = unbounded. Phase 13 SPARQL `--as-of` treats `null_start` as −∞ and `null_end` as +∞. Simple timeless assertions can have both null.
- **D-04:** `transaction_time: datetime = Field(default_factory=lambda: datetime.now(UTC))`. tz-aware UTC always. Overrideable for historical ingest + replay. Not externally injected by storage layer (keeps Phase 2 self-contained; no Phase 13 dep leak).

### Discriminated-Union Shape

- **D-05:** Use Pydantic `Union` + `Field(discriminator='shard_type')`:
  ```python
  ShardType = Literal["simple_assertion", "disputed_proposition",
                      "conflicting_authorities", "gloss", "hypothesis"]

  class ShardEnvelope(BaseModel):
      shard_type: ShardType
      # ...15 envelope fields...

  class SimpleAssertionShard(ShardEnvelope):
      shard_type: Literal["simple_assertion"] = "simple_assertion"
      # Phase 3 adds subtype-specific fields

  # ...4 other subtype classes...

  Shard = Annotated[
      Union[SimpleAssertionShard, DisputedPropositionShard,
            ConflictingAuthoritiesShard, GlossShard, HypothesisShard],
      Field(discriminator="shard_type"),
  ]
  ```
  Pydantic validates tag on parse; invalid tag → `ValidationError` with useful message.
  Phase 3 fleshes subtype-specific fields; Phase 2 ships stubs only so the discriminator and round-trip machinery work immediately.

- **D-06:** `shard_type` is effectively immutable (enforced by per-subtype `Literal[...]` default). Promotion (e.g., hypothesis → simple_assertion) is a **new shard** with `supersedes = <old_iri>`. Preserves provenance + matches PRD §6.4 content-versioning and §7 supersession semantics. Phase 7 governance adds the promotion workflow; Phase 5 wires the supersession SHACL gate.

### Immutability Enforcement

- **D-07:** Per-field `Field(frozen=True)` on the 6 identity-and-origin fields on `ShardEnvelope`:
  - `shard_iri`
  - `provenance_hash`
  - `source_uri`
  - `source_span`
  - `extracted_at`
  - `first_extractor_did`

  Pydantic raises `FrozenFieldError` on assignment attempt. Mutable fields stay assignable. Clean, minimal ceremony, declaration-local.

- **D-08:** Mutable-with-audit fields (`sense`, `reference`, `elaborates`, `layer`, `framework_id`, etc.) allow in-place assignment. Every change appends a `ContentEdit` record:
  ```python
  class ContentEdit(BaseModel):
      field_name: str
      old_value: Any
      new_value: Any
      edited_at: datetime
      editor_did: str
      model_config = ConfigDict(frozen=True)   # audit records themselves are immutable
  ```
  Phase 2 ships the `content_edits: list[ContentEdit] = Field(default_factory=list)` field + a minimal `add_edit()` helper. Phase 5 wires the full validator + forward-only SHACL gate (rejects edits to past versions).

### Conventions (Carried Forward)

- **D-09:** Pydantic 2.13+, `ConfigDict`, `@model_validator` where needed. From Phase 1 patterns in `src/folio_insights/polysemy/dispositions.py` + `distinguo.py`.
- **D-10:** `from __future__ import annotations` on every module for forward-refs — matches Phase 1 style.
- **D-11:** snake_case field names. `Field(default_factory=list)` for mutable list defaults. `Optional[T] = None` (or `T | None = None` — pick one and stay consistent).
- **D-12:** All datetime fields tz-aware UTC. Serialize as ISO-8601 via Pydantic's default datetime handling; no custom serializer in Phase 2.

### Claude's Discretion

- Module location (`src/folio_insights/shards/` vs `src/folio_insights/core/shards.py`) — planner picks based on existing conventions
- Test layout (`tests/shards/test_envelope.py` + `tests/shards/test_mint.py` split, or single file) — planner picks
- Whether `mint_shard_iri` lives on `ShardEnvelope` as a classmethod or as a standalone function — planner picks
- Exact `@model_validator` vs `@field_validator` choice for shard_type pinning — Pydantic idiomatic preference

### Folded Todos

None — no pending todos matched Phase 02.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 2 spec (source of truth)
- `PRD-v2.0-draft-2.md` §6.1 — 15-field Shard envelope field list, immutability semantics, bitemporal rationale
- `PRD-v2.0-draft-2.md` §6.2 — 5 subtype definitions (Phase 3 scope; Phase 2 stubs need the `shard_type` Literal values)
- `PRD-v2.0-draft-2.md` §6.3 — IRI scheme + provenance-hash recipe (Phase 4 scope; Phase 2 minting function mirrors this)
- `PRD-v2.0-draft-2.md` §6.4 — ContentEdit chain semantics (Phase 5 scope; Phase 2 ships field + stub helper)
- `PRD-v2.0-draft-2.md` §21.1 — bitemporal SPARQL semantics (Phase 13 scope; Phase 2 field semantics must match)
- `.planning/REQUIREMENTS.md` — SHARD-01, SHARD-10 verbatim
- `.planning/ROADMAP.md` §Phase 2 — exit criteria and scope anchor

### Philosophy / non-negotiables
- `PHILOSOPHY.md` — shards-as-axioms rationale; envelope immutability intent

### Phase 0 carry-forward
- `.planning/phases/00-foundations-hard-gate/00-DECISION.md` — keep=pyoxigraph; RDF 1.2 substrate; deterministic builds
- `.planning/phases/00-foundations-hard-gate/00-CONTEXT.md` — stack pins (pydantic 2.13+, python 3.11+, rdflib 7.6 adapter-only)

### Phase 1 patterns to mirror
- `src/folio_insights/polysemy/dispositions.py` — Pydantic model style (ConfigDict, Literal tags, JSONL append; v2.0 Shard mirrors the typing discipline but not the JSONL persistence path)
- `src/folio_insights/polysemy/distinguo.py` — `ForkProposal` with `@model_validator` + `validate_fork_proposal_shape()` defense-in-depth pattern — template for D-08 content_edits invariants in Phase 5

### Downstream phase contracts (Phase 2 must not block these)
- `.planning/ROADMAP.md` §Phase 3 (Shard Subtypes) — discriminator shape (D-05) is the integration contract
- `.planning/ROADMAP.md` §Phase 4 (IRI Scheme) — collision detection contract; Phase 2's `mint_shard_iri` must be callable from Phase 4's re-hash job
- `.planning/ROADMAP.md` §Phase 5 (Content Versioning) — ContentEdit validator contract; Phase 2's `content_edits` field must match Phase 5's SHACL shape
- `.planning/ROADMAP.md` §Phase 7 (Governance) — supersession / promotion contract; D-06 (shard_type immutability via supersedes chain) must carry through
- `.planning/ROADMAP.md` §Phase 13 (Storage Layer) — bitemporal SPARQL `--as-of` semantics; D-03 (null = unbounded) must round-trip through RDF-12

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `src/folio_insights/polysemy/dispositions.py` — Pydantic model pattern: `ConfigDict(frozen=False)`, `Literal` tags for discriminators, `Field(default_factory=list)` for mutables. Direct template.
- `src/folio_insights/polysemy/distinguo.py` — `ForkProposal` with `@model_validator` + standalone `validate_*_shape()` function — pattern for D-08 `ContentEdit` invariants.
- `src/folio_insights/polysemy/reviewer.py` — `ensure_reviewer_did()` returns a `did:key:z...` string — Phase 2's `first_extractor_did` field can be populated from this helper in tests/fixtures.
- `src/folio_insights/models/knowledge_unit.py` (v1 baseline) — `KnowledgeUnit`, `Span`, `ConceptTag` Pydantic models. v2.0 `Shard` lives alongside; no migration in Phase 2.

### Established Patterns

- Pydantic 2.13+, `BaseModel`, `ConfigDict`, `Field(...)`, `model_dump()` / `model_validate()` / `model_dump_json()`.
- `from __future__ import annotations` at module top; forward refs resolved via Pydantic's automatic handling.
- tz-aware UTC datetime; ISO-8601 serialization default.
- Test style: pytest + CliRunner patterns from Phase 1 `tests/polysemy/`. Round-trip tests use `hypothesis` for property checks (see `tests/polysemy/test_fp_rate.py`).

### Integration Points

- `src/folio_insights/store/pyoxigraph_store.py` — Phase 13 persistence target; Phase 2 does NOT write through this yet but defines the data that Phase 13 will serialize. No Phase-13 dep leak into Phase 2.
- `src/folio_insights/services/bridge/folio_bridge.py` — FOLIO IRI resolution; Phase 2's `reference` field values will be FOLIO IRIs in real shards (resolution happens in Phase 10 Stage 8).
- Envelope identity (D-01/D-02) must match the contract Phase 4 consumes for collision detection.

### Constraints Inherited from Phase 0

- Python 3.11+, <3.13 (instructor 3.13 regression per `00-01` pitfall 8)
- Deterministic builds (Dagger CI) — minting must be deterministic; no wall-clock in hashes
- pyoxigraph 0.5.7 pinned; Phase 2 does not import it but downstream serialization expects RDF-12 compatibility

</code_context>

<specifics>
## Specific Ideas

- `ShardEnvelope` is the **base class**; the five subtype classes inherit and pin their `shard_type` Literal. This gives Phase 3 a clean extension point — subtype-specific fields are added to subtype classes only.
- The `add_edit(field_name, new_value, editor_did)` helper is deliberately minimal in Phase 2: it assigns the new value (if the field isn't frozen) and appends a `ContentEdit` to `content_edits`. Phase 5 hardens it with forward-only semantics and SHACL validation.
- Property-test determinism is a hard bar for D-02: 1000 random (source_uri, source_span) pairs, each hashed twice, must produce identical IRIs. Catches NFC/LF/trim regressions early.
- `ShardType = Literal[...]` is exported as a public alias so downstream code can import the same type used in the discriminator, avoiding string-literal drift across modules.

</specifics>

<deferred>
## Deferred Ideas

### Reviewed Todos (not folded)

None — no pending todos matched Phase 02.

### Out-of-scope ideas surfaced during discussion

- **RDF `json_schema_extra` hints on each field** — deferred to Phase 11 (SHACL) / Phase 13 (storage). Phase 2 stays pure-Pydantic; the RDF mapping lives where the RDF concerns live.
- **Per-extraction-path required/optional field split** (minimal-at-extraction vs full-at-promotion) — deferred to Phase 7 (governance) + Phase 10 (Stage 8 Shard Minter). Phase 2 declares all fields nullable that can legitimately be null at extraction; promotion-time requirements are Phase 7's job.
- **Migration helper from v1 `KnowledgeUnit` → v2 `Shard`** — v2.0 is greenfield (no v1 corpora to migrate per PROJECT.md "Key context"). A migration helper would be new capability outside Phase 2 scope.
- **`AttestedSignature` sub-model full definition** — Phase 2 can declare a placeholder `AttestedSignature` stub (to type the `signatures` field); Phase 6 DID substrate ships the real model. Phase 2 `signatures: list[AttestedSignature] = Field(default_factory=list)` with a stub class is sufficient.
- **Optional `framework_id` year-versioning** — PRD §6.1 notes framework_id is NOT year-versioned; time-scoping happens at the shard level. Phase 2 honors this: `framework_id: str` (just a string), no year suffix enforcement.

</deferred>

---

*Phase: 02-shard-envelope*
*Context gathered: 2026-04-24*
