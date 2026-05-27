# Phase 5: Content Versioning (§6.4) - Pattern Map

**Mapped:** 2026-05-27
**Files analyzed:** 13 (4 modify, 9 create)
**Analogs found:** 13 / 13 (every new/modified file has a real in-repo analog)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/folio_insights/shards/audit.py` (MODIFY) | model + helper | event-driven (audit append) | itself (enrich in place) + `shards/subtypes.py` validator idiom | exact (extend) |
| `src/folio_insights/shards/envelope.py` (REUSE, likely untouched) | model | — | reuse `AttestedSignature`, `Triple`, 6 frozen fields, `model_rebuild()` | exact |
| `src/folio_insights/revision/content_edit.py` (CREATE) | service/domain | request-response (async write path) | `shards/audit.py::add_edit` (capture→append→assign) + `shards/minting.py` (hash) | role-match |
| `src/folio_insights/revision/store.py` (CREATE) | store/protocol | CRUD (get/put by IRI) | `shards/iri_registry.py::ShardIRIRegistry` (in-memory dict + typed raise) | role-match |
| `src/folio_insights/revision/shape_validation.py` (CREATE) | validation service | transform (model→RDF→pyshacl) | `services/shacl_validator.py::SHACLValidator.validate` + `polysemy/distinguo.py::validate_fork_proposal_shape` | exact (load/run) + role-match (distinguo) |
| `src/folio_insights/revision/content_edit_shape.ttl` (CREATE) | config (SHACL shape) | — | `export/shapes.ttl` (prefixes + NodeShape structure) + RESEARCH verified `sh:sparql` recipe | role-match |
| `src/folio_insights/revision/__init__.py` (CREATE) | package init | — | `shards/__init__.py` (re-export + `__all__`) | exact |
| `canonical_content_hash()` (in content_edit.py) | utility | transform (deterministic hash) | `shards/minting.py::mint_shard_iri` (sha256 over normalized payload) | role-match |
| `sign_attestation()` (in content_edit.py) | utility stub | — | `envelope.py::AttestedSignature` (reuse type, D-05) | exact (reuse) |
| `tests/revision/conftest.py` (CREATE) | test fixture | — | `tests/shards/conftest.py::_sample_shard` + `_SUBTYPE_DEFAULTS` | exact |
| `tests/revision/test_*.py` (CREATE, ~6 modules) | test (unit + async) | — | `tests/shards/test_audit_log.py` (unit) + `tests/shards/test_minting_determinism.py` (hypothesis) | exact |
| `tests/shards/test_audit_log.py` (MODIFY) | test | — | itself (migrate `field_name`→`field_path`) | exact (migrate) |
| `tests/shards/test_content_edit_audit_append_only.py` (CREATE) | test | — | `tests/shards/test_audit_log.py` (same module conventions) | exact |

## Pattern Assignments

### `src/folio_insights/shards/audit.py` (MODIFY — enrich ContentEdit + forward-only validator)

**Analog:** itself (extend the existing module) + `shards/subtypes.py` for the `@model_validator` idiom.

**Current ContentEdit shape to enrich** (`shards/audit.py` L40-53). The frozen + extra-forbid config is correct and stays; D-04 adds `field_path` (rename of `field_name`), required `rationale`, and `signature`:
```python
class ContentEdit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_name: str          # -> RENAME to field_path: str (D-04, dotted)
    old_value: Any
    new_value: Any
    edited_at: datetime
    editor_did: str
    # ADD: rationale: str                       (D-04 — required)
    # ADD: signature: AttestedSignature         (D-05 — reuse envelope stub)
```
Import `AttestedSignature` from `folio_insights.shards.envelope` (already imported alongside `ShardEnvelope` at L9). Note: importing `AttestedSignature` does NOT violate the dep-leak guard — it is pure Pydantic.

**Forward-only `@model_validator` — copy the idiom from `shards/subtypes.py` L105-127** (Phase 3 colocated `mode="after"` validators with raise-on-violation + CONTEXT citation in the message):
```python
@model_validator(mode="after")
def _disputed_invariants(self) -> "DisputedPropositionShard":
    if self.epistemic_status not in _DISPUTED_EPISTEMIC_STATUS_SUBSET:
        raise ValueError(
            f"DisputedPropositionShard.epistemic_status must be one of "
            f"{sorted(_DISPUTED_EPISTEMIC_STATUS_SUBSET)}; "
            f"got {self.epistemic_status!r} (CONTEXT D-03 4-subset)."
        )
    ...
    return self
```
The new validator goes on `ShardEnvelope` (the entity that owns `content_edits`). RESEARCH §"Pattern: Two-layer enforcement" gives the exact body — pairwise `zip(edits, edits[1:])`, raise if `curr.edited_at < prev.edited_at`. Decide placement: either add it to `envelope.py` (where `ShardEnvelope` is defined) or attach via `audit.py` after `model_rebuild()`. Adding directly to `envelope.py` is the cleaner colocation matching the `subtypes.py` idiom.

**`add_edit()` migration** (`shards/audit.py` L56-86): keep as a thin **sync** convenience wrapper (RESEARCH Open Question 2 recommendation) over the capture→append→assign sequence, migrated to `field_path` + new required `rationale`/`signature`. The existing capture-before-assign order (L76 `old_value = getattr(...)` BEFORE L86 `setattr(...)`) is the load-bearing invariant `test_audit_log.py::test_add_edit_captures_old_value_before_assignment` asserts — preserve it.

**Preserve `model_rebuild()`** (`shards/audit.py` L97). The forward-ref `content_edits: list["ContentEdit"]` in `envelope.py` L187 is resolved by this call at module bottom; `test_audit_log.py::test_content_edits_survive_json_round_trip` (L104-117) guards it. Do not remove or reorder it.

---

### `src/folio_insights/revision/content_edit.py` (CREATE — async write path + reverse-replay + helpers)

**Analog:** `shards/audit.py::add_edit` (the capture→append→assign skeleton) and `shards/minting.py` (deterministic sha256 hashing).

**`edit_shard_content()` write path** — the async, store-backed expansion of `add_edit`. The existing `add_edit` body (`shards/audit.py` L76-86) is the proven core sequence:
```python
old_value = getattr(shard, field_name)          # capture BEFORE mutation
shard.content_edits.append(ContentEdit(...))     # append audit record
setattr(shard, field_name, new_value)            # assign
```
Expand to the full D-01 signature + the gate/hash/sign/validate orchestration from RESEARCH §"System Architecture Diagram" (L246-291):
```python
async def edit_shard_content(
    shard_iri: str, field_path: str, new_value: Any,
    editor_did: str, rationale: str, signing_key,   # signing_key unused (Phase 6 stub)
    store: ShardStore,
) -> ContentEdit:
    shard = await store.get(shard_iri)               # D-02 lookup; None -> raise
    if field_path in IMMUTABLE_FIELD_PATHS:          # D-06 gate, BEFORE any mutation
        raise ValueError(...)
    old_value = get_field(shard, field_path)         # dotted-path getter
    pre_edit_hash = canonical_content_hash(shard)    # D-05, REAL hash
    edit = ContentEdit(field_path=field_path, old_value=old_value,
                       new_value=new_value, edited_at=datetime.now(UTC),
                       editor_did=editor_did, rationale=rationale,
                       signature=sign_attestation(editor_did, pre_edit_hash))
    shard.content_edits.append(edit)
    set_field(shard, field_path, new_value)          # dotted-path setter
    validate_shard(shard)                            # post-edit re-validation (re-runs @model_validator)
    await store.put(shard_iri, shard)
    return edit
```
**Critical from RESEARCH** (Pitfall 2, L371-375): `validate_assignment` is OFF on `ShardEnvelope`, so `set_field` accepts wrong types silently. Re-validate via `validate_shard()` (`type(shard).model_validate(shard.model_dump())`) — do NOT fake it (CONTEXT discretion: "keep it honest").

**Dotted-path `get_field`/`set_field`** — copy verbatim from RESEARCH L171-184 (verified `getattr`/`setattr` chains; `Triple` submodel is mutable so `triple.object` assigns, the 6 frozen fields raise).

**`IMMUTABLE_FIELD_PATHS` constant** — copy the frozenset from RESEARCH L197-208 (6 frozen identity fields + `triple.subject`/`.predicate` + `content_edits`/`signatures`). The 6 identity fields it mirrors are `envelope.py` L101-106.

**`canonical_content_hash()`** — copy from RESEARCH L213-223. The sha256-over-normalized-payload precedent is `shards/minting.py` L89-93:
```python
payload = (uri_n + "\n" + span_n).encode("utf-8")
hash_hex = hashlib.sha256(payload).hexdigest()
```
The Phase 5 version swaps the payload for `json.dumps(shard.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. Phase 6 swaps the canonical-form line for JCS without touching the call site.

**`get_shard_at(iri, t)` reverse-replay** — copy the algorithm from RESEARCH L136-149. Key invariants: `model_copy(deep=True)` (never mutate stored shard), strict `>` for the undo condition (ties at `t` are kept), `None` for `t < extracted_at` and unknown IRI.

**`sign_attestation()` stub** — reuse `AttestedSignature` (`envelope.py` L49-66). RESEARCH L231 gives the exact stub: `AttestedSignature(did=editor_did, action="content_edit", over_content_hash=<pre_edit_hash>, signature="", signed_at=datetime.now(UTC))`.

---

### `src/folio_insights/revision/store.py` (CREATE — ShardStore protocol + in-memory dict)

**Analog:** `src/folio_insights/shards/iri_registry.py` (`ShardIRIRegistry` — the existing in-memory dict keyed by content, with a typed collision raise). Read it for the in-memory-dict-plus-typed-exception idiom; the new store mirrors it but keys by `shard_iri` and implements `get`/`put`.

**Protocol/ABC + impl** (D-02). Use `typing.Protocol` (or `abc.ABC`) for the seam Phase 13 swaps. The async signature matters (D-03):
```python
class ShardStore(Protocol):
    async def get(self, shard_iri: str) -> ShardEnvelope | None: ...
    async def put(self, shard_iri: str, shard: ShardEnvelope) -> None: ...

class InMemoryShardStore:
    def __init__(self) -> None:
        self._d: dict[str, ShardEnvelope] = {}
    async def get(self, shard_iri): return self._d.get(shard_iri)
    async def put(self, shard_iri, shard): self._d[shard_iri] = shard
```
**Boundary constraint:** stdlib + Pydantic only. This file lives in `revision/`, not `shards/`, so it is free of the `test_dep_leak_guard.py` constraint — but it must still not import Oxigraph/aiosqlite (D-02: the in-memory dict is the seam, Phase 13 fills it).

---

### `src/folio_insights/revision/shape_validation.py` (CREATE — validate_content_edit_shape)

**Analog (load/run pyshacl):** `services/shacl_validator.py::SHACLValidator` — specifically `_load_shapes` (L64-69, lazy `Graph().parse(..., format="turtle")`) and `validate` (L71-106). Copy the exact pyshacl call (L81-86):
```python
conforms, _results_graph, results_text = pyshacl.validate(
    data_graph, shacl_graph=shapes, inference="none", abort_on_first=False,
)
```
Reuse the `ValidationResult` dataclass shape (`shacl_validator.py` L26-32: `conforms`, `violations`, `results_text`) and the violation-message parsing loop (L88-100).

**Analog (defense-in-depth naming + intent):** `polysemy/distinguo.py::validate_fork_proposal_shape` (L99-127) — the Phase 1 distinguo idiom the `audit.py` comment cites. Note the distinction RESEARCH L126-132 draws: distinguo's function is a *Python-level re-check*; D-07.2 wants a *real pyshacl run*. Name it `validate_content_edit_shape(shard)` and have it (1) build a minimal local RDF graph from the shard's `content_edits` and (2) run pyshacl against the forward-only shape. Returns `ValidationResult` or raises.

**Minimal RDF mapping** — local to this phase (D-07, does NOT pull Phase 13 forward). Build an `rdflib.Graph` mapping each edit to an `rdf:List` node carrying `fi:editedAt` (xsd:dateTime) + integer `fi:seq`. Imports `rdflib` (`Graph`, `Namespace`) exactly as `shacl_validator.py` L14-15. **This file MUST live in `revision/` (or `services/`), NOT `shards/`** — `tests/shards/test_dep_leak_guard.py` L23 forbids `rdflib`/`pyoxigraph`/`oxrdflib`/`owlready2` imports anywhere under `src/folio_insights/shards/`.

---

### `src/folio_insights/revision/content_edit_shape.ttl` (CREATE — focused forward-only SHACL shape)

**Analog:** `src/folio_insights/export/shapes.ttl` (L1-23) for the prefix block + `sh:NodeShape`/`sh:targetClass`/`sh:message` structure. **Do NOT append to `export/shapes.ttl`** — that file targets the OWL export graph (`owl:Class`/`owl:NamedIndividual`), a different domain (RESEARCH Anti-Patterns L333).

**Shape body:** copy the verified `sh:sparql` self-join recipe from RESEARCH L83-103 (spiked live against pyshacl 0.31.0 — negative case fails, positive conforms). Constraint polarity is load-bearing: the SELECT matches the *bad* (back-dated) condition `FILTER(?ct < ?pt)` so a violation fires when ≥1 row returns (RESEARCH Pitfall 1, L365-369).

---

### `src/folio_insights/revision/__init__.py` (CREATE)

**Analog:** `shards/__init__.py` (L1-53) — re-export public names from submodules and declare `__all__`. Export `edit_shard_content`, `get_shard_at`, `get_field`, `set_field`, `IMMUTABLE_FIELD_PATHS`, `canonical_content_hash`, `sign_attestation`, `ShardStore`, `InMemoryShardStore`, `validate_content_edit_shape`.

---

### `tests/revision/conftest.py` (CREATE — 10-edit fixture + store fixture)

**Analog:** `tests/shards/conftest.py` (L108-160 `_sample_shard` keyword-only builder + L45-105 `_SUBTYPE_DEFAULTS`). Import and reuse `_sample_shard` rather than re-deriving (RESEARCH L420 says build the 10-edit fixture *with* the existing builder, extended for the enriched `ContentEdit`). The fixture-IRI-minted-once-at-module-scope optimization (L34-39) is worth mirroring.

Provide: a shared `InMemoryShardStore` pytest fixture, and a 10-edit `SimpleAssertionShard` fixture with strictly-increasing monthly `edited_at` on mutable fields (`sense`, `reference`, `triple.object`, `confidence`) plus known intermediate states for `get_shard_at(iri, t_k)` assertions, and at least one exact-`t` boundary tie.

---

### `tests/revision/test_*.py` (CREATE — unit + async + hypothesis)

**Unit/async analog:** `tests/shards/test_audit_log.py` (L1-25 module header + `pytestmark = pytest.mark.shards` + import-from-conftest pattern). `async def test_*` needs **no decorator** — `asyncio_mode="auto"` is already set (`pyproject.toml` L63). Reuse the `shards` marker (RESEARCH L239); no new marker needed.

**Hypothesis property-test analog:** `tests/shards/test_minting_determinism.py` (L27-48) — the `@settings(max_examples=1000, deadline=None)` + `@given(...)` idiom. Apply to the reverse-replay invariants (RESEARCH L151-165): `get_shard_at(iri, latest) == current`, `get_shard_at(iri, extracted_at) == as-extracted`, `get_shard_at(iri, t<extracted_at) is None`, and stored-shard-unchanged-after-call. Match Phase 2's 1000-example rigor (RESEARCH L427).

Module set (RESEARCH Wave 0, L411-416): `test_edit_shard_content.py`, `test_immutable_gate.py`, `test_forward_only_validator.py`, `test_shacl_forward_only.py`, `test_get_shard_at.py`, `test_get_shard_at_properties.py`.

---

### `tests/shards/test_audit_log.py` (MODIFY — field_name→field_path migration)

**Analog:** itself. Mechanical rename across 7 `field_name=` usages (RESEARCH L359). Every `ContentEdit(...)` construction site (L30-36, L43-49, L57-64) gains required `rationale=` + `signature=`, and `field_name=`→`field_path=`. The assertion `edit.field_name` (L77, L117) → `edit.field_path`. Keep the frozen-field-raise test (L97-102) — it still holds (the 6 identity fields stay frozen).

---

### `tests/shards/test_content_edit_audit_append_only.py` (CREATE — exit criterion 1)

**Analog:** `tests/shards/test_audit_log.py` (same module conventions, `shards` marker). Additive (REQUIREMENTS SHARD-09 acceptance file). Asserts: existing entries immutable (frozen + append-only), new edits append, back-dated append rejected by the `@model_validator`.

## Shared Patterns

### Deterministic sha256 hashing
**Source:** `src/folio_insights/shards/minting.py` L89-93
**Apply to:** `canonical_content_hash()` in `revision/content_edit.py`
```python
payload = (uri_n + "\n" + span_n).encode("utf-8")
hash_hex = hashlib.sha256(payload).hexdigest()
```
Same stdlib `hashlib` + UTF-8-encode discipline; Phase 5 hashes `json.dumps(model_dump(mode="json"), sort_keys=True)` instead of the URI+span payload.

### `@model_validator(mode="after")` raise-on-violation
**Source:** `src/folio_insights/shards/subtypes.py` L105-127
**Apply to:** the forward-only/append-only validator on `ShardEnvelope`
Colocate the validator with the model; raise `ValueError` with a CONTEXT-citing message (`... D-08b`). Phase 3 has 4 such validators (L105, L171, L227, L267) — follow that house style.

### pyshacl load + validate
**Source:** `src/folio_insights/services/shacl_validator.py` L64-106
**Apply to:** `validate_content_edit_shape()` in `revision/shape_validation.py`
Lazy `Graph().parse(..., format="turtle")` + `pyshacl.validate(data, shacl_graph=shapes, inference="none", abort_on_first=False)` + violation-message parsing into a `ValidationResult` dataclass.

### Defense-in-depth `validate_*_shape()`
**Source:** `src/folio_insights/polysemy/distinguo.py` L99-127
**Apply to:** the naming + intent of `validate_content_edit_shape()`
Explicit re-check beyond the always-on Pydantic validator, guarding records that bypass construction validators. RESEARCH L126-132: Phase 5's version additionally runs a real pyshacl shape (distinguo's is Python-only).

### Keyword-only fixture builder
**Source:** `tests/shards/conftest.py` L108-160 (`_sample_shard`)
**Apply to:** `tests/revision/conftest.py`
Defaults-dict + `**overrides` builder; reuse the existing one rather than re-deriving the 30-field envelope.

### Hypothesis property test
**Source:** `tests/shards/test_minting_determinism.py` L27-48
**Apply to:** `tests/revision/test_get_shard_at_properties.py`
`@settings(max_examples=1000, deadline=None)` + `@given(...)` for reverse-replay invariants.

### `pytest.mark.shards` + asyncio auto-mode
**Source:** `tests/shards/test_audit_log.py` L25; `pyproject.toml` L63-74
**Apply to:** all `tests/revision/` modules
`pytestmark = pytest.mark.shards` (reuse existing marker, no new one). `async def test_*` runs decorator-free under `asyncio_mode="auto"`.

## No Analog Found

None. Every new file maps to a concrete in-repo analog. The closest thing to a gap is the `sh:sparql` self-join SHACL constraint (no prior `sh:sparql` shape exists — `export/shapes.ttl` uses only `sh:property`/`sh:minCount`), but RESEARCH L71-124 provides a *verified* recipe spiked against the installed pyshacl 0.31.0, so the planner has a concrete source.

## Boundary Constraint (LOAD-BEARING)

`tests/shards/test_dep_leak_guard.py` L23 enforces that **no module under `src/folio_insights/shards/` may import `pyshacl`, `rdflib`, `pyoxigraph`, `oxrdflib`, or `owlready2`.** Therefore:
- The RDF-mapping + pyshacl code (`shape_validation.py`, `content_edit_shape.ttl`) **MUST** live in the new `revision/` package (or `services/`), never in `shards/`.
- The in-memory `ShardStore` is stdlib + Pydantic only, so it may live anywhere — but `revision/` is the natural home (RESEARCH L293-308 recommended structure).
- `audit.py`'s enrichment stays pure Pydantic + stdlib (importing `AttestedSignature` from `envelope.py` is fine — no storage lib).

This resolves CONTEXT's "Claude's Discretion" module-layout question decisively toward the `revision/` package: extending `shards/audit.py` for the SHACL half would trip the dep-leak guard.

## Metadata

**Analog search scope:** `src/folio_insights/shards/`, `src/folio_insights/services/`, `src/folio_insights/polysemy/`, `src/folio_insights/export/`, `tests/shards/`
**Files scanned:** audit.py, envelope.py, minting.py, subtypes.py, iri_registry.py (referenced), distinguo.py, shacl_validator.py, shapes.ttl, test_audit_log.py, conftest.py, test_minting_determinism.py, test_dep_leak_guard.py, 3 fixtures, pyproject.toml
**Pattern extraction date:** 2026-05-27
