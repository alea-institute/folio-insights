# Phase 03: Shard Subtypes (§6.2) — Context

**Gathered:** 2026-04-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Flesh out the 5 subtype stub classes Phase 02 left behind. Each gains its PRD-§6.2 subtype-specific fields. Phase 03 modifies **only** `src/folio_insights/shards/subtypes.py` and tests under `tests/shards/`. Does NOT touch `envelope.py` or change the discriminator shape (locked by Phase 02 D-05).

REQ-IDs: **SHARD-02** (SimpleAssertion), **SHARD-03** (DisputedProposition), **SHARD-04** (ConflictingAuthorities + 8-value reconciliation), **SHARD-05** (Gloss), **SHARD-06** (Hypothesis + citation_required gate).

**Exit criteria (from ROADMAP):**
1. PRD examples A.1 (SimpleAssertion), A.2 (ConflictingAuthorities w/ 8 reconciliation strategies), A.3 (DisputedProposition) all round-trip.
2. Gloss + Hypothesis subtypes parse and validate.
3. `HypothesisShard` ships `citation_required: bool = True`; promotion-gate enforcement lives in Phase 7 governance (this phase ships only the field).

**In scope for Phase 3:**
- Expand each of the 5 subtype classes in `subtypes.py` with their PRD-§6.2 fields
- Nested Pydantic models alongside their parent subtype (`Objection`, `Reply`, `AuthorityPosition`) — same file, no separate `subtype_models.py`
- Per-subtype `@model_validator` invariants (e.g., DisputedProp narrows envelope `epistemic_status` to a 4-value subset)
- New tests under `tests/shards/` covering round-trip + edge cases for each subtype
- 3 verbatim PRD-fixture tests (A.1, A.2, A.3) + hypothesis property tests (100–500 per subtype, capped to keep CI < 2s)

**Out of scope (deferred):**
- IRI scheme generation (Phase 04 — Phase 02's `mint_shard_iri` is already used; Phase 04 narrows to collision detection)
- `ContentEdit` audit gate hardening (Phase 05 — Phase 02 ships the schema; Phase 05 adds forward-only SHACL)
- DID-signed `AttestedSignature` real verification (Phase 06)
- Promotion workflow + `citation_required` gate enforcement at promotion-time (Phase 07 governance)
- SHACL referential-integrity gate on `GlossShard.glosses` (Phase 11 SHACL OR Phase 13 storage layer)
- RDF/JSON-LD serialization (Phase 11/13)

</domain>

<decisions>
## Implementation Decisions

### Subtype Field Specs (per PRD §6.2)

#### D-01: SimpleAssertionShard ships as a TRUE empty subtype

```python
class SimpleAssertionShard(ShardEnvelope):
    shard_type: Literal["simple_assertion"] = "simple_assertion"
```

No subtype-specific fields. Matches PRD §6.2.1 verbatim ("the envelope carries everything"). Phase 02's stub already satisfies this — Phase 3 only adds round-trip tests for it. Maximum extensibility: any shard not fitting the other 4 types lands here.

#### D-02: DisputedPropositionShard fields + nested models

Nested models (in `subtypes.py`):
```python
class Objection(BaseModel):
    model_config = ConfigDict(frozen=False, extra="forbid")
    cites: str           # IRI of cited authority
    argues: str          # the objection proposition
    strength: float      # 0.0..1.0

class Reply(BaseModel):
    model_config = ConfigDict(frozen=False, extra="forbid")
    objection_index: int
    replies_via: Literal["distinguo", "authority_supersession", "scope_limitation", "factual_distinction"]
    argument: str
```

Subtype:
```python
class DisputedPropositionShard(ShardEnvelope):
    shard_type: Literal["disputed_proposition"] = "disputed_proposition"
    utrum: str                                    # required — well-formed binary question
    objections: list[Objection]                   # required — ≥1 element
    sed_contra: Objection                         # required — brief authoritative counter-cite
    respondeo: str                                # required — determinative answer
    uses_distinctions: list[str] = Field(default_factory=list)  # optional — IRIs of distinction shards
    replies: list[Reply]                          # required — replies mapping objections
```

#### D-03: DisputedPropositionShard reuses envelope `epistemic_status` (no separate `dispute_state` field)

Add `@model_validator(mode='after')` on DisputedPropositionShard:
- Constrains `epistemic_status ∈ {"hypothesis", "attested", "contested", "aporetic"}` (subset of envelope's 8 values)
- Raises `ValidationError` with type `value_error` if `epistemic_status` is outside this 4-value subset for this subtype

DRY: no duplicate state field. `SHARD-03`'s `dispute_state ∈ {hypothesis, attested, contested, aporetic}` requirement is satisfied by the validator-constrained subset of `epistemic_status`. Update REQUIREMENTS.md commentary if needed (record as locked decision).

Additional invariant in the validator:
- `objections` must have at least one element (no empty objections list)
- Every `Reply.objection_index` must be a valid index into `objections` (raise on out-of-range)

#### D-04: ConflictingAuthoritiesShard fields + nested model + hard 8-value Literal

Nested model:
```python
class AuthorityPosition(BaseModel):
    model_config = ConfigDict(frozen=False, extra="forbid")
    authority_iri: str
    position: str
    jurisdiction: str
    weight: Literal["binding", "persuasive", "minority", "majority"]
```

Subtype:
```python
ReconciliationStrategy = Literal[
    "sense_distinction",
    "contextual_limitation",
    "voice_attribution",
    "textual_correction",
    "retraction_later",
    "subsequent_overruling",
    "jurisdictional_scoping",
    "unreconciled",
]

class ConflictingAuthoritiesShard(ShardEnvelope):
    shard_type: Literal["conflicting_authorities"] = "conflicting_authorities"
    sic: list[AuthorityPosition]              # required — one side of the conflict
    non: list[AuthorityPosition]              # required — the other side
    reconciliation_strategy: ReconciliationStrategy   # required
    reconciliation_note: str                  # required — rationale for the chosen strategy
```

**No 9th `"custom"` escape hatch.** Novel reconciliation strategies require a Phase 7 governance RFC + enum extension. Schema discipline > experimental flexibility. Enforces precise SPARQL queries over reconciliation strategies.

`@model_validator(mode='after')` on ConflictingAuthoritiesShard:
- `sic` and `non` must each have ≥1 element
- `reconciliation_note` must not be empty string (whitespace-only rejected)

#### D-05: GlossShard fields + format-only IRI validation

```python
GlossKind = Literal["clarificatoria", "extensiva", "restrictiva", "dissentiens", "historica"]

class GlossShard(ShardEnvelope):
    shard_type: Literal["gloss"] = "gloss"
    glosses: str                              # required — IRI of shard being annotated
    gloss_kind: GlossKind                     # required
    gloss_text: str                           # required — non-empty commentary text
```

`@model_validator(mode='after')` on GlossShard:
- `glosses` must match the regex `^urn:folio:shard/[a-f0-9]{16}$` (Phase 02 D-02 IRI prefix) OR `^https?://[^\s]+$` (legacy/external shard URLs allowed during transition). Format-only check.
- `glosses != self.shard_iri` (no self-glossing)
- `gloss_text` must not be empty/whitespace-only

**Referential integrity (does the target IRI actually exist?) is deferred:**
- Phase 5 SHACL shape OR Phase 13 storage layer enforces target-existence at write-time.
- Phase 3 does NOT import pyoxigraph/rdflib (preserves Phase 02 dep-leak guard).

#### D-06: HypothesisShard fields + citation_required ships, gate enforcement deferred

```python
GenerationMethod = Literal["combinatorial", "inductive", "analogical"]

class HypothesisShard(ShardEnvelope):
    shard_type: Literal["hypothesis"] = "hypothesis"
    generation_method: GenerationMethod                    # required
    promotion_requirements: list[str] = Field(default_factory=list)   # optional — descriptive prereqs
    ttl_days: int = 90                                     # default 90 per PRD §6.2.5
    citation_required: bool = True                         # default True per §21.3 RESOLVED decision
```

**Phase 3 ships the field, Phase 7 enforces the gate.**

- No Pydantic validator at construction time blocks creation of a `HypothesisShard` with `citation_required=True` and empty `depends_on_*` lists. A hypothesis can legitimately start with no citations and accumulate them before promotion.
- Phase 7 governance workflow checks at promotion time: if `citation_required=True` AND all 4 `depends_on_*` lists are empty, the promotion operation is rejected end-to-end (CLI, API, signed event).

`@model_validator(mode='after')` on HypothesisShard:
- `ttl_days >= 1` (no zero or negative TTL)
- (No citation gate — Phase 7 owns that)

### Shape & Discriminator (locked from Phase 02)

#### D-07: Single `subtypes.py` file

All 5 subtype classes + 3 nested models (Objection, Reply, AuthorityPosition) + 3 typed `Literal` aliases (`ReconciliationStrategy`, `GlossKind`, `GenerationMethod`) live in `src/folio_insights/shards/subtypes.py`. Estimated ~250–350 LOC. Keeps imports flat: `from folio_insights.shards import DisputedPropositionShard, Objection`.

No `subtypes/` sub-package. No `subtype_models.py` split. Phase 02 established the location; reusing it.

#### D-08 (carried from Phase 02): Discriminated union shape unchanged

`Shard = Annotated[Union[SimpleAssertionShard, DisputedPropositionShard, ConflictingAuthoritiesShard, GlossShard, HypothesisShard], Field(discriminator="shard_type")]` stays exactly as Phase 02 shipped it. The 5 subtype classes still inherit `ShardEnvelope` and pin `shard_type: Literal[...] = "..."`. Phase 3 only adds fields *inside* the existing class bodies.

### Test Strategy

#### D-09: Round-trip tests = verbatim PRD fixtures + hypothesis property tests

Two layers, both required:

1. **Verbatim PRD fixtures** — Three fixture-driven tests (A.1, A.2, A.3 from PRD §6.2). JSON strings transcribed verbatim into `tests/shards/fixtures/` (or inline as test constants). Test asserts:
   - `Adapter(Shard).validate_python(json.loads(fixture)).model_dump() == loaded_dict` (round-trip)
   - The parsed instance is the expected subtype class
   - Specific subtype-specific fields contain the expected values
   - Audit-friendly: the exact PRD example validates; documents intent

2. **Hypothesis property tests** — Per-subtype generators under `tests/shards/test_subtype_properties.py`:
   - SimpleAssertion: 100 examples (low — empty subtype, mostly tests envelope inheritance still works under the discriminator)
   - DisputedProposition: 300 examples (highest — most fields + nested models + validator invariants)
   - ConflictingAuthorities: 200 examples (8-value Literal coverage + AuthorityPosition coverage)
   - Gloss: 200 examples (5-value GlossKind coverage + IRI format edge cases)
   - Hypothesis: 200 examples (3-value GenerationMethod + ttl_days boundaries + citation_required default behavior)
   - Total ≤ 1000 examples; CI runtime budget < 2s

`@settings(max_examples=N, deadline=None)` per Phase 02 D-12 pattern.

### Tests file layout (D-10)

- `tests/shards/test_subtype_simple_assertion.py` — verbatim A.1 fixture + edge cases for the empty subtype
- `tests/shards/test_subtype_disputed_proposition.py` — verbatim A.3 fixture + Objection/Reply nesting + epistemic_status subset validator + objection_index range validator
- `tests/shards/test_subtype_conflicting_authorities.py` — verbatim A.2 fixture + AuthorityPosition + 8-strategy enum + sic/non non-empty validator
- `tests/shards/test_subtype_gloss.py` — IRI format validation + self-glossing rejection + 5 gloss_kind values
- `tests/shards/test_subtype_hypothesis.py` — `citation_required=True` field default + ttl_days boundary + 3 generation_method values + (NO promotion-gate test in Phase 3 — Phase 7 owns it)
- `tests/shards/test_subtype_properties.py` — hypothesis property tests (one strategy per subtype)
- `tests/shards/fixtures/` — three JSON files (`example_a1_simple_assertion.json`, `example_a2_conflicting_authorities.json`, `example_a3_disputed_proposition.json`) transcribed from PRD §6.2

### Phase 02 carry-forward (unchanged)

#### D-11: Pydantic conventions stay identical to Phase 02
- Pydantic 2.13+, `ConfigDict(extra="forbid")` on every model
- `from __future__ import annotations` at module top
- snake_case fields; `Field(default_factory=list)` for mutable list defaults
- tz-aware UTC datetime everywhere; ISO-8601 default serialization
- `Optional[T]` and `T | None` interchangeable — Phase 02 uses `T | None`; Phase 3 follows
- No imports of `pyoxigraph` / `rdflib` / `oxrdflib` / `owlready2` (dep-leak guard from Phase 02 covers `subtypes.py`)

### Claude's Discretion

- Exact regex for `glosses` IRI validation (re-use Phase 02's `_IRI_PREFIX = "urn:folio:shard/"` constant + add a hex16 suffix pattern)
- Property-test strategies for each nested model (`Objection`, `Reply`, `AuthorityPosition`) — planner picks reasonable strategies; tests should cover boundary values for `strength`, `objection_index`, `weight`
- `@model_validator(mode='after')` vs `@model_validator(mode='before')` — planner picks based on Pydantic best practices
- Test fixture file format (JSON vs inline-Python-dict) — planner picks; JSON aligns better with audit story

### Folded Todos

None — no pending todos matched Phase 03.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 3 spec (source of truth)
- `PRD-v2.0-draft-2.md` §6.2 — 5 subtype field lists, nested models, validation rules, Examples A.1/A.2/A.3 (subtype source of truth)
- `PRD-v2.0-draft-2.md` §21.3 — RESOLVED: Hypothesis promotion authority (citation requirement on promotion)
- `.planning/REQUIREMENTS.md` — SHARD-02 through SHARD-06 verbatim
- `.planning/ROADMAP.md` §Phase 3 — exit criteria + scope anchor

### Phase 02 carry-forward (locked decisions and shipped artifacts)
- `.planning/phases/02-shard-envelope/02-CONTEXT.md` — D-01..D-12 (envelope shape, discriminator, frozen identity, ContentEdit audit, conventions)
- `.planning/phases/02-shard-envelope/02-SECURITY.md` — accepted risks AR-01..AR-10 (downstream-phase ownership for ingest/redaction/governance/storage)
- `src/folio_insights/shards/envelope.py` — READ-ONLY in Phase 3; defines the 22 required + 15 optional envelope fields each subtype inherits
- `src/folio_insights/shards/subtypes.py` — Phase 3 modifies this file; Phase 02 stub structure preserved
- `src/folio_insights/shards/audit.py` — `ContentEdit` + `add_edit` (Phase 02); subtype-specific field edits append ContentEdit per D-08
- `src/folio_insights/shards/minting.py` — Phase 02's deterministic IRI minter; Phase 3 fixtures call this for round-trip
- `pyproject.toml` — `hypothesis>=6.100` dev dep + `shards` pytest marker (Phase 02)

### Phase 1 patterns (carry-forward style)
- `src/folio_insights/polysemy/distinguo.py` — `ForkProposal` `@model_validator` + standalone `validate_*_shape()` defense-in-depth pattern (template for D-03 epistemic_status subset validator)

### Downstream phase contracts (Phase 3 must not block these)
- `.planning/ROADMAP.md` §Phase 4 (IRI Scheme) — Phase 02's `mint_shard_iri` already shipped; Phase 4 narrows to collision detection. Phase 3 fixtures use minted IRIs.
- `.planning/ROADMAP.md` §Phase 5 (Content Versioning) — `ContentEdit` + SHACL forward-only gate + GlossShard `glosses` referential-integrity SHACL shape
- `.planning/ROADMAP.md` §Phase 6 (DID Substrate) — `AttestedSignature.verify()`; Phase 3 ships subtype fields, no signature work
- `.planning/ROADMAP.md` §Phase 7 (Governance Model) — promotion workflow that enforces HypothesisShard's `citation_required=True` gate at promote-time. **Phase 3 ships the field; Phase 7 enforces the gate.**
- `.planning/ROADMAP.md` §Phase 11 (SHACL Hybrid) — `GlossShard` referential-integrity SHACL shape
- `.planning/ROADMAP.md` §Phase 13 (Storage Layer) — write-time validation of GlossShard.glosses target existence

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `src/folio_insights/shards/envelope.py:60` — `AttestedSignature` permissive stub (Phase 02 placeholder); subtypes inherit `signatures: list[AttestedSignature]` field
- `src/folio_insights/shards/envelope.py` — 22 required + 15 optional inherited fields; subtypes do NOT redefine any
- `src/folio_insights/shards/subtypes.py` — current 5 stub class skeletons (Phase 3 expands these in place)
- `src/folio_insights/shards/minting.py` — `mint_shard_iri(source_uri, source_span) -> (iri, hash)` (Phase 3 fixtures call this)
- `src/folio_insights/shards/audit.py` — `ContentEdit` + `add_edit` (subtype-specific field edits go through this; Phase 02 model_rebuild at module bottom resolves forward ref)
- `tests/shards/conftest.py` — Phase 02 fixture factory; Phase 3 tests can extend with per-subtype fixtures
- `tests/shards/test_envelope_roundtrip.py` — Phase 02 round-trip pattern (uses real `mint_shard_iri`); subtype-specific tests follow the same recipe
- `tests/shards/test_minting_determinism.py` — hypothesis 1000-example pattern; Phase 3 reuses `@settings(max_examples=N, deadline=None)` per subtype

### Established Patterns

- Pydantic 2.13+, `ConfigDict(extra="forbid")` on every model
- `from __future__ import annotations` at module top
- Per-field `Field(frozen=True)` for immutable identity fields (Phase 02); subtype-specific fields are mutable (no `frozen=True`)
- `@model_validator(mode='after')` for cross-field invariants (Phase 1 `distinguo.py::ForkProposal`); Phase 3 reuses for `epistemic_status` subset constraint, `objection_index` range check, etc.
- `Literal[...]` for closed enums (preferred over Python `Enum` class) — every Phase 02 enum is a `Literal`; Phase 3 follows for `ReconciliationStrategy`, `GlossKind`, `GenerationMethod`
- Test imports use `from tests.shards.conftest import ...` (Phase 02 conftest path)

### Integration Points

- Subtypes are constructed via `SubtypeShard(**fields)` or via `TypeAdapter(Shard).validate_python(payload)` (latter dispatches via `shard_type` discriminator)
- ContentEdit audit log is automatic via `add_edit(shard, field_name, new_value, editor_did)` for any mutable subtype-specific field
- `tests/shards/conftest.py::default_envelope_kwargs` (or equivalent) likely provides shared envelope-field fixtures; Phase 3 builds subtype-specific kwargs on top

### Constraints Inherited from Phase 02 / Phase 0

- Pydantic v2 frozen-field assignment raises `ValidationError(type='frozen_field')` (NOT v1 `FrozenFieldError`) — applies to inherited identity fields; subtype-specific fields are mutable so this doesn't affect Phase 3 directly
- No imports of pyoxigraph/rdflib/oxrdflib/owlready2 in `subtypes.py` (dep-leak guard from Phase 02 covers all `src/folio_insights/shards/*.py`)
- Python 3.11+, <3.13 (instructor 3.13 regression per Phase 0 pitfall)
- Deterministic builds (Dagger CI) — fixtures must be stable; PRD-fixture JSON files committed to repo

</code_context>

<specifics>
## Specific Ideas

- **PRD verbatim fixtures** — A.1/A.2/A.3 transcribed JSON committed under `tests/shards/fixtures/`. Auditor-friendly. Each fixture's IRI is computed via `mint_shard_iri()` in the test setup so the fixtures stay determinism-locked.
- **Nested models alongside parent subtype** — `Objection` and `Reply` declared in `subtypes.py` directly above `DisputedPropositionShard`; `AuthorityPosition` declared above `ConflictingAuthoritiesShard`. Reads top-to-bottom in code.
- **Type alias exports** — `ReconciliationStrategy`, `GlossKind`, `GenerationMethod` are public type aliases (re-exported from `folio_insights.shards.__init__`). Downstream phases that need to enumerate the strategies (e.g., Phase 11 SHACL generator) import the alias rather than re-declaring the values.
- **No promotion logic in Phase 3** — `HypothesisShard.citation_required` is a field, not a method. No `promote()` method on the subtype. Phase 7 ships the workflow.
- **Validators are descriptive, not blocking** — Where the spec gives a count rule (e.g., "objections must have ≥1 element"), the `@model_validator` raises `ValidationError` with a message describing the violation. Test asserts on `errors()[0]['type']` per Phase 02 D-07 pattern.

</specifics>

<deferred>
## Deferred Ideas

### Reviewed Todos (not folded)

None — no pending todos matched Phase 03.

### Out-of-scope ideas surfaced during discussion

- **9th `"custom"` reconciliation strategy with free-text note** — explicitly rejected for Phase 3 (D-04). Novel strategies require a Phase 7 governance RFC + Literal extension.
- **Promotion workflow + citation_required gate enforcement** — Phase 7 governance scope (D-06). Phase 3 ships the field only.
- **GlossShard target-shard existence validation** — Phase 5 SHACL or Phase 13 storage layer (D-05). Phase 3 does format-only.
- **`generation_method` post-hoc audit** (verifying that a HypothesisShard tagged `"combinatorial"` was actually combinatorially generated) — Phase 9.P2 framework detector, not Phase 3.
- **Subtype splitting into a `subtypes/` sub-package** — rejected for now (D-07). If `subtypes.py` exceeds ~600 LOC in a future phase, revisit then.
- **Dispute-state field separate from envelope `epistemic_status`** — rejected (D-03). DRY wins; validator constrains the subset.
- **Per-extraction-path required/optional split** (which fields are mandatory at extraction-time vs. only at promotion-time) — Phase 7 governance + Phase 10 Stage 8 Shard Minter scope. Phase 3 declares all subtype-specific fields as required where the PRD specifies.

</deferred>

---

*Phase: 03-shard-subtypes*
*Context gathered: 2026-04-25*
