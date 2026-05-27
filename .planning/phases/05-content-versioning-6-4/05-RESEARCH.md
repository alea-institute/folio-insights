# Phase 5: Content Versioning (§6.4) - Research

**Researched:** 2026-05-27
**Domain:** Append-only audit chains, SHACL forward-only constraints (pyshacl/SPARQL), reverse-replay historical reconstruction, Pydantic v2 nested-model mutation
**Confidence:** HIGH (all critical claims verified by in-repo spikes against the installed toolchain)

## Summary

Phase 5 hardens the already-shipped `ContentEdit` chain into a real content-versioning discipline. The CONTEXT.md (D-01..D-09) already locks every design decision; this research fills the *implementation-knowledge* gaps and de-risks the single biggest external unknown (the literal "SHACL guard") by spiking it against the repo's actual toolchain.

**The headline finding: the SHACL forward-only guard is achievable today.** pyshacl 0.31.0 (already a core dependency) enforces a monotonic-`edited_at` constraint over an RDF-list edit chain via a `sh:sparql` self-join constraint. I verified both the negative case (a back-dated edit fails validation) and the positive case (an ordered chain conforms) with live spikes. SHACL *cannot* enforce immutability of past entries (that requires comparing two graph snapshots — out of scope for a stateless single-graph validator), so that half of D-08 is carried by the Pydantic `@model_validator` and the `IMMUTABLE_FIELD_PATHS` gate. This division is clean and matches the operator's "defense-in-depth" intent.

The other four flagged unknowns all resolved favorably: reverse-replay is a straightforward undo-loop with well-defined edge cases; the dotted-path helpers are simple `getattr`/`setattr` chains with two real Pydantic v2 gotchas (silent wrong-type assignment, and submodel-vs-frozen mutation rules); `canonical_content_hash()` is a one-liner over `model_dump(mode="json")` + sorted-key `json.dumps`; and `pytest-asyncio` is **already installed and configured** (`asyncio_mode="auto"`) — no dependency addition needed.

**Primary recommendation:** Implement the two-layer guard exactly as D-07 specifies — Pydantic `@model_validator` (monotonicity + append-only immutability) as the authoritative gate, plus a focused pyshacl `sh:sparql` shape (`validate_content_edit_shape()`) as defense-in-depth for the forward-only half only. Reconstruct via reverse-replay on a `model_copy(deep=True)` working copy. Hash via `model_dump(mode="json")` + canonical `json.dumps`. Use Hypothesis property tests for the reverse-replay invariants.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `edit_shard_content()` write path | Domain/Service (new `revision/` or extended `shards/audit.py`) | Store (in-memory `ShardStore`) | PRD §6.4 signature; orchestrates capture→append→assign→re-validate |
| Append-only / monotonicity enforcement | Domain (Pydantic `@model_validator`) | Validation (pyshacl shape) | D-07: validator is authoritative (works on live objects, no RDF); SHACL is defense-in-depth |
| Immutable-field gate | Domain (`IMMUTABLE_FIELD_PATHS` constant + Pydantic `frozen`) | — | D-06: single source of truth; SHACL cannot see "which field was edited" |
| `get_shard_at(iri, t)` reconstruction | Domain (reverse-replay) | Store (IRI lookup) | D-09: pure function over current state + edit chain |
| Shard persistence / lookup-by-IRI | Store (`ShardStore` protocol, in-memory dict) | — | D-02: thin seam Phase 13 (Oxigraph) swaps |
| Content hashing | Domain (`canonical_content_hash()`) | — | D-05: real deterministic JSON now; Phase 6 swaps JCS in |
| Signature capture | Domain (`sign_attestation()` stub) | — | D-05: placeholder slot; Phase 6 fills crypto |

## Standard Stack

### Core
| Library | Version (installed) | Purpose | Why Standard |
|---------|---------------------|---------|--------------|
| `pydantic` | 2.13.3 `[VERIFIED: uv run]` | ContentEdit enrichment, `@model_validator`, frozen fields, `model_copy` | Already the repo's core data layer (envelope.py) |
| `pyshacl` | 0.31.0 `[VERIFIED: uv run]` | The literal "SHACL guard" (D-07.2) via `sh:sparql` constraint | Already a core dep; `services/shacl_validator.py` is the load/run precedent |
| `rdflib` | 7.6.0 `[VERIFIED: uv run]` | Build the minimal RDF data graph to feed pyshacl | Already a core dep; used in `shacl_validator.py` |
| stdlib `hashlib` + `json` | 3.11+ | `canonical_content_hash()` deterministic JSON SHA-256 | Mirrors `shards/minting.py` precedent (sha256 over normalized payload) |

### Supporting (dev / test)
| Library | Version (installed) | Purpose | When to Use |
|---------|---------------------|---------|-------------|
| `pytest-asyncio` | 1.3.0 `[VERIFIED: uv run]` | Test the `async def edit_shard_content` path (D-03) | Already configured `asyncio_mode="auto"` — `async def test_*` runs with no decorator |
| `hypothesis` | 6.152.2 `[VERIFIED: uv run]` | Property tests for reverse-replay invariants (D-09) | Phase 2/4 precedent; ideal for `get_shard_at(iri, latest) == current` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `sh:sparql` self-join over RDF list | `sh:order` + list-shape `sh:node` constraints | `sh:order` validates *presence* of order, not *monotonic datetime comparison between adjacent elements*. The cross-element comparison fundamentally needs SPARQL. **Use sh:sparql.** |
| Manual RDF mapping for the shape | Reuse the Phase 11/13 RDF serializer | Phase 11/13 don't exist yet; D-07 explicitly says "minimal RDF mapping local to this phase — does NOT pull the Phase 13 store forward." **Build a tiny local mapper.** |
| `model_dump(mode="json")` + sorted json | `model_dump_json()` directly | `model_dump_json()` does not guarantee sorted keys; sorted keys are required for a stable canonical form. **Use dict-mode + `json.dumps(sort_keys=True)`.** |

**Installation:** Nothing to install. All five libraries are present and pinned. `pytest-asyncio>=0.25.0` and `asyncio_mode="auto"` are already in `pyproject.toml`.

## Package Legitimacy Audit

> No new external packages are introduced in Phase 5. All dependencies (pydantic, pyshacl, rdflib, pytest-asyncio, hypothesis) are pre-existing, pinned in `pyproject.toml`, and verified importable in the project venv via `uv run`.

| Package | Registry | Status | Disposition |
|---------|----------|--------|-------------|
| pydantic 2.13.3 | PyPI | pre-existing core dep | No action |
| pyshacl 0.31.0 | PyPI | pre-existing core dep | No action |
| rdflib 7.6.0 | PyPI | pre-existing core dep | No action |
| pytest-asyncio 1.3.0 | PyPI | pre-existing dev dep | No action |
| hypothesis 6.152.2 | PyPI | pre-existing dev dep | No action |

**Packages removed due to slopcheck [SLOP] verdict:** none (no new packages).
**Packages flagged as suspicious [SUS]:** none.

---

## The SHACL Guard (D-07.2) — Verified Recipe

This is the single biggest external unknown. **Verified working against pyshacl 0.31.0 in this repo's venv.**

### What SHACL CAN enforce (forward-only / monotonicity)

A `sh:sparql` constraint with a self-join over the edit list finds any *adjacent pair* where the later edit's `editedAt` precedes the earlier one's — a back-dated insert. This is the "forward-only" half of D-08(b).

**The minimal RDF mapping** (local to Phase 5, does NOT pull Phase 13 forward): emit each shard as a node with `fi:contentEdits` pointing at an `rdf:List` of edit nodes; each edit node carries `fi:editedAt` (xsd:dateTime) and an explicit integer `fi:seq` index (0,1,2,…) capturing append order.

**Verified working shape** (negative case fails, positive case conforms):

```turtle
# Source: spiked live against pyshacl 0.31.0 / rdflib 7.6.0 [VERIFIED: uv run spike]
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix fi: <https://folio-insights.example/> .

fi:ForwardOnlyShape a sh:NodeShape ;
    sh:targetClass fi:Shard ;
    sh:sparql [
        sh:message "Back-dated edit: an edit's editedAt precedes its predecessor (forward-only violation)" ;
        sh:select '''
            SELECT $this ?prev ?curr WHERE {
                $this <https://folio-insights.example/contentEdits>/(<http://www.w3.org/1999/02/22-rdf-syntax-ns#rest>*)/<http://www.w3.org/1999/02/22-rdf-syntax-ns#first> ?prev .
                $this <https://folio-insights.example/contentEdits>/(<http://www.w3.org/1999/02/22-rdf-syntax-ns#rest>*)/<http://www.w3.org/1999/02/22-rdf-syntax-ns#first> ?curr .
                ?prev <https://folio-insights.example/seq> ?ps . ?curr <https://folio-insights.example/seq> ?cs .
                FILTER(?cs = ?ps + 1)
                ?prev <https://folio-insights.example/editedAt> ?pt . ?curr <https://folio-insights.example/editedAt> ?ct .
                FILTER(?ct < ?pt)
            }
        ''' ;
    ] .
```

A SHACL `sh:sparql` constraint **flags a violation when its SELECT returns ≥1 row.** So the SELECT must match the *bad* condition (`?ct < ?pt`). The spike returned `conforms=False` for a back-dated chain and `conforms=True` for an ordered chain.

**Loading/running pattern** — mirror `services/shacl_validator.py` exactly:
```python
# Source: src/folio_insights/services/shacl_validator.py L80-86 [VERIFIED: codebase]
conforms, _results_graph, results_text = pyshacl.validate(
    data_graph, shacl_graph=shapes, inference="none", abort_on_first=False
)
```

### What SHACL CANNOT enforce (immutability of past entries)

D-08(a) — "mutating or deleting any existing `ContentEdit` entry is forbidden" — **cannot** be expressed in SHACL over a single graph snapshot. SHACL is stateless: it sees one graph and has no concept of "what the chain looked like before." Detecting a mutation/deletion requires diffing two snapshots (previous vs. current), which is a transactional concern, not a shape constraint.

**Therefore the immutability half is carried entirely by:**
1. `ContentEdit.model_config = frozen=True` (already shipped — an individual record can't be mutated in place).
2. The Pydantic `@model_validator` (D-07.1) that re-checks append-only invariants on the shard.
3. The `IMMUTABLE_FIELD_PATHS` gate (D-06) listing `content_edits` itself as immutable-as-a-whole (you may append, never reorder/remove).

State this division explicitly in the plan so no task tries (and fails) to make SHACL enforce immutability. **The exit criterion 2 ("SHACL guard rejects edits to past versions") is satisfied by the forward-only SPARQL shape** — back-dated inserts are precisely "edits to a past version" in the temporal sense.

### `validate_content_edit_shape()` — the distinguo pattern

The Phase 1 `validate_fork_proposal_shape()` (`polysemy/distinguo.py` L99) is a **Python-level re-check**, not a pyshacl run — it guards against records loaded via `model_construct()` that bypass validators. D-07.2 wants a *real pyshacl shape*. **Recommendation: do both, named clearly:**
- `validate_content_edit_shape(shard)` → builds the minimal RDF graph + runs pyshacl against the forward-only shape (the literal "SHACL guard," defense-in-depth). Returns the existing `ValidationResult` shape or raises.
- The Pydantic `@model_validator` on the shard is the authoritative, always-on gate.

Keep the new shape in a Phase-5-local TTL (e.g. `src/folio_insights/revision/content_edit_shape.ttl`) — do NOT append it to `export/shapes.ttl` (that file targets the OWL export graph, a different concern).

## Reverse-Replay Reconstruction (D-09) — Verified Algorithm

```
get_shard_at(iri, t) -> ShardEnvelope | None:
  1. shard = store.get(iri)            # D-02 lookup; unknown IRI -> None (or typed raise)
  2. if shard is None: return None     # unknown IRI
  3. if t < shard.extracted_at: return None   # shard didn't exist yet (D-09 strict edge)
  4. working = shard.model_copy(deep=True)    # NEVER mutate stored shard (D-09)
  5. # undo every edit with edited_at > t, in REVERSE-chronological order
     for edit in reversed(working.content_edits):   # append order == chrono order
         if edit.edited_at > t:
             set_field(working, edit.field_path, edit.old_value)
         # else: this edit happened by t -> keep it (ties at exactly t are INCLUDED, D-09)
  6. # trim the content_edits list to only edits with edited_at <= t (the historical view)
  7. return working
```

**Correctness invariants** (assert these in tests):
- `get_shard_at(iri, latest_edit_time) == current_shard` (no edits undone)
- `get_shard_at(iri, extracted_at) == as-extracted state` (PRD §21.7 guarantee — all content edits undone)
- `get_shard_at(iri, t < extracted_at) is None`
- `get_shard_at(unknown_iri, t) is None` (planner's call: `None` vs typed raise — must be unambiguous, not a silent wrong answer)
- Stored shard object identity/content unchanged after the call (verify `store.get(iri) == pre_call_snapshot`)

**Edge cases (all from D-09):**
- **Time ties:** equal `edited_at` broken by list (append) order; an edit at *exactly* `t` counts as having-happened-by-`t` → **included** (kept, not undone). Use strict `>` for the undo condition.
- **`t` before `extracted_at`** → `None`.
- **No mutation of stored shard** — work on `model_copy(deep=True)` (verified: deep copy isolates submodels and preserves frozen enforcement).

**Reversal assumes append order == chronological order**, which the forward-only guard *guarantees* — they're mutually reinforcing. Document this coupling: reverse-replay correctness depends on the monotonicity invariant the guard enforces.

**Hypothesis property tests are an excellent fit** (Phase 2/4 precedent): generate a random sequence of N edits to mutable fields with monotonic timestamps, then assert `get_shard_at(latest) == current` and `get_shard_at(extracted_at) == initial` for arbitrary chains. This catches off-by-one undo bugs the 10-edit fixture might miss.

## Dotted-Path get_field / set_field Helpers (D-09 / Claude's discretion)

Parse `"triple.object"` → walk nested attributes. `"sense"` → top-level.

```python
def get_field(shard: ShardEnvelope, path: str) -> Any:
    obj = shard
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj

def set_field(shard: ShardEnvelope, path: str, value: Any) -> None:
    parts = path.split(".")
    obj = shard
    for part in parts[:-1]:
        obj = getattr(obj, part)     # walk to the parent submodel
    setattr(obj, parts[-1], value)   # assign the leaf
```

**Verified Pydantic v2 behaviors** `[VERIFIED: uv run spike]`:
- `s.triple.object = "x"` **succeeds** — `Triple` is `extra="forbid"` but NOT frozen, so leaf assignment on the submodel works.
- `s.shard_iri = "x"` **raises `ValidationError`** (type `frozen_field`) — the 6 identity fields are per-field frozen.
- `model_copy(deep=True)` produces a fully isolated copy: mutating the copy's `triple.object` does NOT affect the original; frozen enforcement is preserved on the copy.

**CRITICAL GOTCHA — silent wrong-type assignment** `[VERIFIED: uv run spike]`: `ShardEnvelope.model_config` does **not** set `validate_assignment` (it's `None`/off). So `s.confidence = "not_a_float"` is **silently accepted** without re-validation. This matters for `set_field`:
- The dotted-path setter applies `old_value`/`new_value` without type-checking.
- For reverse-replay this is safe (you're restoring a previously-valid value).
- For `edit_shard_content` the **incoming `new_value` is unvalidated** — a malformed edit could corrupt the shard silently. **Recommendation:** after `set_field`, call `validate_shard()` (the D-09 post-edit re-validation hook) which re-runs full validation via `type(shard).model_validate(shard.model_dump())`, OR set `validate_assignment=True` on the envelope. Flag this decision to the planner — it's the difference between a real guard and a fake one (CONTEXT explicitly says "keep it honest, don't fake validation that isn't happening").

**`IMMUTABLE_FIELD_PATHS` gate (D-06):** check `field_path in IMMUTABLE_FIELD_PATHS` and raise a clear error *before any mutation*. The set:
```python
IMMUTABLE_FIELD_PATHS = frozenset({
    # 6 Pydantic-frozen identity fields
    "shard_iri", "provenance_hash", "source_uri", "source_span",
    "extracted_at", "first_extractor_did",
    # identity-defining triple parts (Triple submodel is mutable, so frozen=True
    # does NOT protect these — the gate is the ONLY protection)
    "triple.subject", "triple.predicate",
    # append-only lists (append OK; reorder/remove/replace forbidden)
    "content_edits", "signatures",
})
```
Note: `triple.subject`/`triple.predicate` are NOT protected by Pydantic frozen (the `Triple` submodel is mutable) — the `IMMUTABLE_FIELD_PATHS` gate is their *only* protection. This is the asymmetry D-04/D-06 calls out: `triple.object` is editable (re-parenting, PRD decision #4) while `.subject`/`.predicate` are locked.

## canonical_content_hash() (D-05) — Verified Recipe

```python
# Source: spiked against pydantic 2.13.3 [VERIFIED: uv run]
import hashlib, json

def canonical_content_hash(shard: ShardEnvelope) -> str:
    """Deterministic SHA-256 over the pre-edit shard. Phase 6 swaps JCS in HERE
    without changing the call site (D-05)."""
    payload = shard.model_dump(mode="json")          # datetimes -> ISO8601, enums/Literals -> str
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()
```

**Verified facts** `[VERIFIED: uv run spike]`:
- `model_dump(mode="json")` serializes `datetime` → `"2026-04-24T12:00:00Z"` and Literal/enum fields → plain strings — fully JSON-safe primitives, no custom encoder needed.
- Hashing the **same instance** twice is fully stable (deterministic).
- **Nuance — `transaction_time` non-determinism:** two *independently-constructed* instances differ only in `transaction_time` (its `default_factory=datetime.now(UTC)`). This is NOT a problem: `canonical_content_hash` hashes a *specific* shard snapshot (the pre-edit shard), whose `transaction_time` is already fixed. The hash is meaningful and reproducible for that snapshot. If the planner wants the hash to represent *content only* (excluding bitemporal bookkeeping), exclude `transaction_time`/`valid_time_*` via `model_dump(mode="json", exclude={...})` — flag this as a design choice. Given D-05 says "over the pre-edit shard," hashing the full snapshot is correct and the simpler choice.
- **Phase 6 swap seam:** the JCS (RFC 8785) canonicalization replaces the `json.dumps(...)` line only. The function signature and call site stay identical. JCS differs from `sort_keys` json mainly in number formatting and Unicode escaping; for the string/datetime-heavy shard payload the two are nearly identical, so the Phase 6 swap is low-risk.

`sign_attestation(...)` stub (D-05): returns `AttestedSignature(did=editor_did, action="content_edit", over_content_hash=canonical_content_hash(pre_edit_shard), signature="", signed_at=datetime.now(UTC))`. The `AttestedSignature` stub (`envelope.py` L49, `extra="allow"`) is reused — no new type.

## pytest-asyncio Setup (D-03) — RESOLVED, no action

`[VERIFIED: pyproject.toml + uv run]`:
- `pytest-asyncio>=0.25.0` is **already** in `[project.optional-dependencies].dev` (installed: 1.3.0).
- `[tool.pytest.ini_options]` already sets `asyncio_mode = "auto"`.
- **Consequence:** `async def test_edit_shard_content()` runs with **no `@pytest.mark.asyncio` decorator** (auto mode collects all `async def` tests automatically). Existing async tests in the repo rely on this.
- Add `pytestmark = pytest.mark.shards` to the new test module (mirrors `test_audit_log.py` L25), and register no new marker — `shards` already exists in `pyproject.toml` markers.

## Architecture Patterns

### System Architecture Diagram

```
                          edit_shard_content(shard_iri, field_path, new_value,
                                              editor_did, rationale, signing_key)
                                          │
                                          ▼
                          ┌──────────────────────────────┐
       shard_iri ───────► │  ShardStore.get(iri)  (D-02)  │ ──► None? raise "unknown IRI"
                          └──────────────┬───────────────┘
                                          ▼
                          ┌──────────────────────────────┐
                          │  IMMUTABLE_FIELD_PATHS gate    │ ──► path immutable? RAISE (before any mutation)
                          │            (D-06)              │
                          └──────────────┬───────────────┘
                                          ▼
              old_value = get_field(shard, field_path)   (dotted-path getter)
              pre_edit_hash = canonical_content_hash(shard)   (D-05, REAL)
                                          ▼
              edit = ContentEdit(field_path, old_value, new_value, edited_at=now,
                                 editor_did, rationale,
                                 signature=sign_attestation(...))   ← Phase 6 stub
                                          ▼
              ┌────────────────── transactional ──────────────────┐
              │ shard.content_edits.append(edit)                  │
              │ set_field(shard, field_path, new_value)           │  ← rollback append on failure
              └───────────────────────────┬───────────────────────┘
                                          ▼
                   ┌────────────────────────────────────────┐
                   │  @model_validator (D-07.1, AUTHORITATIVE)│ ──► monotonic? append-only? else RAISE
                   │  validate_content_edit_shape (D-07.2)    │ ──► pyshacl forward-only (defense-in-depth)
                   │  validate_shard() post-edit re-validation │
                   └───────────────────────┬──────────────────┘
                                          ▼
                          ShardStore.put(iri, shard)   ──► return edit


  get_shard_at(iri, t):
       store.get(iri) ──► None? ──► return None
            │
            ▼  t < extracted_at? ──► return None
       working = shard.model_copy(deep=True)        ← never mutate stored
            │
            ▼  for edit in reversed(content_edits): if edit.edited_at > t: set_field(working, edit.field_path, edit.old_value)
       trim content_edits to edited_at <= t
            │
            ▼
       return working   (historical state at t)
```

### Recommended Project Structure (Claude's discretion — D-binding suggests `revision/`)
```
src/folio_insights/
├── revision/                       # NEW package (PRD §6.4 suggests revision/content_edit.py)
│   ├── __init__.py
│   ├── content_edit.py             # edit_shard_content, get_shard_at, get_field, set_field,
│   │                               #   IMMUTABLE_FIELD_PATHS, canonical_content_hash, sign_attestation stub
│   ├── store.py                    # ShardStore protocol + InMemoryShardStore (D-02 seam)
│   ├── shape_validation.py         # validate_content_edit_shape() — builds RDF + runs pyshacl
│   └── content_edit_shape.ttl      # the focused forward-only sh:sparql shape (NOT export/shapes.ttl)
└── shards/
    └── audit.py                    # ContentEdit ENRICHED (field_path, rationale, signature);
                                    #   @model_validator forward-only on ShardEnvelope;
                                    #   add_edit kept as thin sync wrapper or migrated
```
(Planner decides `revision/` vs. extending `shards/audit.py` per CONTEXT discretion. Respect the established boundary: no Oxigraph/aiosqlite imports leak into `shards/` — the in-memory store is fine since it's stdlib-only.)

### Pattern: Two-layer enforcement (D-07)
**What:** Pydantic `@model_validator(mode="after")` on the shard is the always-on authoritative gate; the pyshacl shape is opt-in defense-in-depth.
**When:** Validator runs on every construction/re-validation; SHACL runs in `validate_content_edit_shape()` (and any explicit pre-commit check).
**Example (validator — both halves of D-08):**
```python
# Mirrors shards/subtypes.py @model_validator idiom (Phase 3 precedent)
@model_validator(mode="after")
def _forward_only_append_only(self) -> "ShardEnvelope":
    edits = self.content_edits
    for prev, curr in zip(edits, edits[1:]):
        if curr.edited_at < prev.edited_at:
            raise ValueError(
                "content_edits must be monotonic in edited_at "
                "(no back-dated insert — forward-only, D-08b)"
            )
    return self
```
(The immutability half — D-08a — is enforced structurally: `ContentEdit` is frozen, and the only mutation API is `append`. A `@model_validator` cannot see deletions of past entries on its own; the `IMMUTABLE_FIELD_PATHS` gate blocks `content_edits` as a replaceable field.)

### Anti-Patterns to Avoid
- **Making SHACL enforce immutability:** wasted effort — SHACL is stateless over one graph. Immutability is Pydantic + the gate.
- **Mutating the stored shard in `get_shard_at`:** silently corrupts the store. Always `model_copy(deep=True)`.
- **Trusting `setattr` for type safety:** `validate_assignment` is off — wrong-type assignments pass silently. Re-validate after edit.
- **Appending the new shape to `export/shapes.ttl`:** that file targets the OWL export graph (`owl:Class`/`owl:NamedIndividual`), a different domain. Keep the content-edit shape separate.
- **Re-litigating `field_name` vs `field_path`:** D-04 locks `field_path` (dotted). Migrate `test_audit_log.py` accordingly.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Monotonicity check over RDF list | Custom RDF list walker in Python for the SHACL layer | `sh:sparql` self-join (verified recipe above) | SPARQL property paths over rdf:List are the idiomatic, tested approach |
| Deterministic JSON serialization | Manual recursive key-sorter / datetime formatter | `model_dump(mode="json")` + `json.dumps(sort_keys=True)` | Pydantic already handles datetime/enum/Literal → JSON primitives correctly |
| Deep working copy | Manual field-by-field reconstruction | `shard.model_copy(deep=True)` | Verified to isolate submodels AND preserve frozen enforcement |
| Async test plumbing | Custom event-loop fixtures | `asyncio_mode="auto"` (already configured) | Zero ceremony; `async def test_*` just works |
| SHACL load/run | New pyshacl wrapper | Mirror `services/shacl_validator.py` pattern | Existing `pyshacl.validate(..., inference="none", abort_on_first=False)` is the repo idiom |

**Key insight:** Every primitive Phase 5 needs already exists in the repo or its installed deps. The work is *composition and enforcement discipline*, not new machinery.

## Runtime State Inventory

> Phase 5 introduces an in-memory store and enriches a schema. The migration consequences (D-04 `field_name`→`field_path`) are a real rename-with-blast-radius, so this inventory applies.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None persistent.** `ShardStore` is in-memory dict (D-02), reset per process. No DB, no Oxigraph (Phase 13). No fixtures store `content_edits` entries with `field_name` *yet* (the 3 existing JSON fixtures have empty `content_edits: []` — verified in `example_a1_simple_assertion.json`). | None — the new 10-edit fixture is authored fresh with `field_path`. |
| Live service config | **None.** No external service holds the schema. | None. |
| OS-registered state | **None.** No scheduled tasks, daemons, or registries reference `ContentEdit` fields. | None. |
| Secrets/env vars | **None.** `signing_key` is a function parameter (Phase 6 stub), not an env var. No secret key names change. | None. |
| Build artifacts | **None stale.** No compiled artifacts embed `field_name`. | None. |
| **Code rename blast radius (D-04)** | `shards/audit.py` (`ContentEdit.field_name`, `add_edit(field_name=...)`); `tests/shards/test_audit_log.py` (7 tests use `field_name=` and `edit.field_name`); `tests/shards/conftest.py` (no `field_name` refs — verified); test builders constructing `ContentEdit`. | **Code edit** (not data migration): rename/augment `field_name`→`field_path`, add required `rationale` + `signature` to every `ContentEdit` construction site. Update `test_audit_log.py` assertions. |

**Verified by:** grep of fixtures (`content_edits: []` in all 3), `conftest.py` (`"content_edits": []` default, no `field_name` keys), and `test_audit_log.py` (7 `field_name` usages enumerated).

## Common Pitfalls

### Pitfall 1: SHACL constraint polarity inverted
**What goes wrong:** Writing the `sh:sparql` SELECT to match the *valid* condition makes valid chains fail and invalid chains pass.
**Why:** A `sh:sparql` constraint reports a violation when its SELECT returns ≥1 row. The SELECT must match the *bad* (back-dated) condition.
**How to avoid:** Test both polarities (verified: back-dated → `conforms=False`; ordered → `conforms=True`).
**Warning signs:** All chains conform, or all chains fail.

### Pitfall 2: Silent wrong-type field assignment
**What goes wrong:** `set_field(shard, "confidence", "garbage")` succeeds silently — `validate_assignment` is off.
**Why:** `ShardEnvelope.model_config` doesn't enable `validate_assignment` (verified `None`).
**How to avoid:** Re-validate after edit (`validate_shard()` or `validate_assignment=True`); validate `new_value` before applying.
**Warning signs:** A shard with a string in a float field round-trips without error until much later.

### Pitfall 3: Mutating the stored shard in reconstruction
**What goes wrong:** `get_shard_at` undoes edits on the live stored object, corrupting "current."
**Why:** Forgetting `model_copy(deep=True)`; or shallow-copying so the `Triple` submodel is shared.
**How to avoid:** `model_copy(deep=True)` (verified to isolate submodels). Add a test asserting `store.get(iri)` is unchanged after `get_shard_at`.
**Warning signs:** A second `get_shard_at` returns different results than the first.

### Pitfall 4: Off-by-one at the time boundary
**What goes wrong:** An edit at *exactly* `t` is wrongly undone (or wrongly kept).
**Why:** Using `>=` instead of `>` for the undo condition.
**How to avoid:** D-09 says an edit at exactly `t` counts as having-happened-by-`t` → keep it. Undo only `edited_at > t` (strict). Hypothesis test with timestamps landing exactly on `t`.
**Warning signs:** `get_shard_at(iri, latest_edit_time) != current`.

### Pitfall 5: `transaction_time` polluting the content hash comparison
**What goes wrong:** Comparing hashes of two freshly-built "identical" shards fails because `transaction_time` differs.
**Why:** `transaction_time` default_factory is `datetime.now(UTC)` (verified the ONLY non-deterministic field).
**How to avoid:** `canonical_content_hash` hashes a *specific snapshot* — this is fine. If content-only hashing is wanted, `exclude={"transaction_time", "valid_time_start", "valid_time_end"}`.
**Warning signs:** Hash assertions flake across runs when constructing fresh fixtures.

## Validation Architecture

> nyquist_validation is enabled (config.json `workflow.nyquist_validation: true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio 1.3.0 (`asyncio_mode="auto"`) + hypothesis 6.152.2 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`asyncio_mode="auto"`, `timeout=30`, marker `shards`) |
| Quick run command | `uv run pytest -m shards -x -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SHARD-09 | Append-only chain: existing entries immutable, new edits append | unit | `uv run pytest tests/shards/test_content_edit_audit_append_only.py -x` | ❌ Wave 0 (exit criterion 1 — additive) |
| SHARD-09 | SHACL guard rejects back-dated edit (forward-only) | unit | `uv run pytest tests/revision/test_shacl_forward_only.py -x` | ❌ Wave 0 |
| SHARD-09 | Pydantic `@model_validator` rejects non-monotonic chain | unit | `uv run pytest tests/revision/test_forward_only_validator.py -x` | ❌ Wave 0 |
| SHARD-09 | `get_shard_at(iri, t)` correct across 10-edit fixture | unit | `uv run pytest tests/revision/test_get_shard_at.py -x` | ❌ Wave 0 (exit criterion 3) |
| SHARD-09 | Reverse-replay invariants (latest==current, extracted_at==as-extracted) | property (hypothesis) | `uv run pytest tests/revision/test_get_shard_at_properties.py -x` | ❌ Wave 0 |
| SHARD-09 | `IMMUTABLE_FIELD_PATHS` gate raises before mutation | unit | `uv run pytest tests/revision/test_immutable_gate.py -x` | ❌ Wave 0 |
| SHARD-09 | `edit_shard_content` async write path (capture→append→assign→re-validate) | unit (async) | `uv run pytest tests/revision/test_edit_shard_content.py -x` | ❌ Wave 0 |
| SHARD-09 | Migrated `field_name`→`field_path` audit-log tests stay green | unit | `uv run pytest tests/shards/test_audit_log.py -x` | ✅ exists — migrate |

### Reference Fixtures
- **10-edit fixture (exit criterion 3):** author a `SimpleAssertionShard` + 10 sequential `ContentEdit`s to mutable fields (`sense`, `reference`, `triple.object`, `confidence`, …) with strictly increasing `edited_at` (e.g. monthly). Store known intermediate states at chosen `t` values so `get_shard_at(iri, t_k)` is asserted exactly. Build it with the existing `_sample_shard` builder (extend `conftest.py` for the enriched `ContentEdit` shape). Place in `tests/revision/conftest.py` or `tests/revision/fixtures/`.
- **Negative SHACL fixture:** a chain whose edit #N is back-dated (verified to fail the shape).
- **Boundary fixture:** an edit at *exactly* `t` (tie-break / off-by-one coverage).

### Sampling Rate
- **Per task commit:** `uv run pytest -m shards -x -q` plus the touched `tests/revision/` module.
- **Per wave merge:** `uv run pytest tests/shards tests/revision -q`.
- **Phase gate:** full suite `uv run pytest -q` green before `/gsd:verify-work`. Hypothesis property test runs full example budget (Phase 2 ran 1000/0/0 for minting determinism — match that rigor for reverse-replay).

### Wave 0 Gaps
- [ ] `tests/revision/conftest.py` — 10-edit fixture builder + shared `InMemoryShardStore` fixture.
- [ ] `tests/shards/test_content_edit_audit_append_only.py` — exit criterion 1 (additive).
- [ ] `tests/revision/test_shacl_forward_only.py`, `test_forward_only_validator.py`, `test_get_shard_at.py`, `test_get_shard_at_properties.py`, `test_immutable_gate.py`, `test_edit_shard_content.py`.
- [ ] Migrate `tests/shards/test_audit_log.py` for `field_name`→`field_path` + required `rationale`/`signature`.
- [ ] If a new `tests/revision/` dir is created, no new pytest marker needed (reuse `shards` or run unmarked).

## Security Domain

> `security_enforcement` is absent from config.json → enabled by default.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface in Phase 5 (DID signing is a Phase 6 stub) |
| V3 Session Management | no | — |
| V4 Access Control | partial | `editor_did` is captured but NOT verified (Phase 6). The audit log records *who claims* to have edited; integrity of that claim is Phase 6. Document this gap explicitly. |
| V5 Input Validation | **yes** | Pydantic models + `IMMUTABLE_FIELD_PATHS` gate + post-edit re-validation. **The silent-wrong-type-assignment gotcha is a V5 concern** — unvalidated `new_value` could inject bad data. |
| V6 Cryptography | deferred | `canonical_content_hash` uses SHA-256 (stdlib hashlib — never hand-roll). Real ed25519 signing is Phase 6. The `signature=""` placeholder must be unmistakably a stub (don't let an empty signature read as "verified"). |
| V11 Business Logic | **yes** | Append-only / forward-only is the core business-logic integrity invariant — enforced at two layers (D-07). |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Back-dated edit insert (history forgery) | Tampering | Forward-only monotonicity (Pydantic validator + SHACL `sh:sparql` shape) |
| Mutation/deletion of past audit entries | Tampering / Repudiation | `ContentEdit` frozen + append-only list + `IMMUTABLE_FIELD_PATHS` gate on `content_edits` |
| Editing an identity field (shard-IRI drift) | Tampering | 6 Pydantic-frozen fields + gate on `triple.subject`/`.predicate` |
| Silent bad-value injection via `set_field` | Tampering | Post-edit `validate_shard()` re-validation (validate_assignment is OFF — must re-validate) |
| Forged `editor_did` | Spoofing | **Accepted for Phase 5** — real DID verification is Phase 6. Document as a known, deferred gap. |
| Empty placeholder signature mistaken for valid | Repudiation | `signature=""` + `action="content_edit"`; Phase 6 fills real ed25519. Tests must assert the stub is clearly unsigned. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `revision/` package layout is the right home (vs extending `shards/audit.py`) | Project Structure | Low — CONTEXT explicitly leaves this to planner's discretion; either works |
| A2 | Hashing the full snapshot (incl. `transaction_time`) is the intended `canonical_content_hash` scope | canonical_content_hash | Low — D-05 says "over the pre-edit shard"; content-only is a trivial `exclude=` change if preferred |
| A3 | `get_shard_at` returns `None` (not raise) for unknown IRI | Reverse-Replay | Low — D-09 explicitly leaves this to planner ("None or a clearly-typed raise"); must just be unambiguous |
| A4 | Monthly-spaced timestamps in the 10-edit fixture are adequate granularity | Validation Architecture | Low — only needs strict monotonicity + at least one exact-tie boundary case |

**Note:** No `[ASSUMED]`-tagged *technical* claims remain — the five flagged unknowns were all verified by live spikes against the installed toolchain. The assumptions above are scoping/discretion choices the planner finalizes, not unverified facts.

## Open Questions (RESOLVED)

> Both questions are answered by the inline **Recommendation** blocks below, and Phase 5 plans implement those recommendations (Plan 02 Task 1 uses the targeted `validate_shard()` hook; Plan 01 Task 1 keeps `add_edit()` as a thin sync wrapper).

1. **Should `validate_assignment` be turned on for `ShardEnvelope`, or should `validate_shard()` re-validate after every edit?**
   - What we know: `validate_assignment` is currently off; `setattr` accepts wrong types silently (verified).
   - What's unclear: enabling `validate_assignment=True` globally could break other call sites that mutate fields without expecting re-validation cost; the targeted `validate_shard()` post-edit hook is safer.
   - Recommendation: use the targeted `validate_shard()` re-validation hook in `edit_shard_content` (the D-09 post-edit re-validation seam), leave `validate_assignment` off to avoid surprising Phase 2/3 code. Validate `new_value` against the field before applying.

2. **Does `add_edit()` (Phase 2 sync helper) stay as a thin wrapper or get deprecated?**
   - What we know: 5 existing tests exercise `add_edit` directly; CONTEXT leaves this to discretion.
   - Recommendation: keep `add_edit` as a thin **sync** convenience wrapper over the new logic (capture→append→assign), so `test_audit_log.py` semantics stay green after the `field_name`→`field_path` migration. The async `edit_shard_content` is the store-backed full path.

## Sources

### Primary (HIGH confidence — verified in-repo)
- `uv run` spikes against pyshacl 0.31.0 / rdflib 7.6.0 — forward-only `sh:sparql` constraint (negative + positive cases verified)
- `uv run` spikes against pydantic 2.13.3 — dotted-path get/set, frozen-field raise, `model_copy(deep=True)` isolation, `validate_assignment` off, `model_dump(mode="json")` determinism
- `src/folio_insights/services/shacl_validator.py` — pyshacl load/validate pattern (L64-106)
- `src/folio_insights/polysemy/distinguo.py` — `validate_*_shape()` defense-in-depth idiom (L99-127)
- `src/folio_insights/shards/{envelope,audit,minting}.py` — ShardEnvelope, ContentEdit, frozen fields, sha256 hashing precedent
- `tests/shards/{test_audit_log,conftest}.py` — test builder + migration blast radius
- `pyproject.toml` — pytest-asyncio + asyncio_mode + markers (D-03 resolved)
- `.planning/phases/05-content-versioning-6-4/05-CONTEXT.md` — locked decisions D-01..D-09
- `.planning/REQUIREMENTS.md` row SHARD-09 — acceptance criteria

### Secondary (MEDIUM confidence)
- SHACL `sh:sparql` over `rdf:List` via property paths — standard W3C SHACL/SPARQL pattern, confirmed by the live spike rather than docs alone.

### Tertiary (LOW confidence)
- None. All claims grounded in code or live spike.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every lib installed & version-verified via `uv run`
- SHACL guard recipe: HIGH — both polarities spiked live against pyshacl 0.31.0
- Reverse-replay algorithm: HIGH — algorithm + edge cases derived directly from D-09, Pydantic copy behavior verified
- Dotted-path / Pydantic gotchas: HIGH — frozen, deep-copy, validate_assignment all spiked
- canonical_content_hash: HIGH — determinism + datetime/enum serialization spiked
- Migration blast radius: HIGH — grep-verified across fixtures/conftest/tests

**Research date:** 2026-05-27
**Valid until:** 2026-06-26 (stable domain; pinned deps. Re-verify only if pyshacl/pydantic majors change.)
