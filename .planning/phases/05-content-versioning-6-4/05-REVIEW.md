---
phase: 05-content-versioning-6-4
reviewed: 2026-05-27T17:15:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - src/folio_insights/revision/__init__.py
  - src/folio_insights/revision/content_edit.py
  - src/folio_insights/revision/store.py
  - src/folio_insights/revision/shape_validation.py
  - src/folio_insights/revision/content_edit_shape.ttl
  - src/folio_insights/shards/audit.py
  - src/folio_insights/shards/envelope.py
findings:
  critical: 2
  warning: 3
  info: 1
  total: 6
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-05-27T17:15:00Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Phase 5 delivers the `ContentEdit` append-only chain, the `edit_shard_content` write path,
`get_shard_at` reverse-replay, and SHACL defense-in-depth over the edit chain. The
architecture is sound and the documented stubs (unsigned `sign_attestation`, unauthenticated
`editor_did`, deferred Oxigraph) are correctly scoped to Phase 6/13 with explicit comments.

Two critical bugs were confirmed by live execution: (1) the transactional rollback in
`edit_shard_content` only covers the `set_field`-raises path; if `validate_shard` raises
after a successful `set_field`, the `InMemoryShardStore` is already holding the corrupted
reference and no rollback fires; (2) `canonical_content_hash` includes `transaction_time`
in its `model_dump` payload, making hashes non-deterministic across independently-constructed
`ShardEnvelope` instances despite the docstring's "deterministic" claim.

Three warnings round out the findings: `add_edit` in `shards/audit.py` has the symmetric
phantom-edit bug (no rollback if `setattr` raises), `get_field`/`set_field` accept arbitrary
dotted attribute paths with no schema-field whitelist, and the `validate_shard` return value
is discarded at the call site in `edit_shard_content`.

The SHACL shape, the SPARQL FILTER polarity, the forward-only Pydantic `@model_validator`,
the `IMMUTABLE_FIELD_PATHS` gate ordering, the deep-copy isolation in `get_shard_at`, and
the editor-DID stub documentation all check out correctly.

---

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Store Corruption When `validate_shard` Raises After Successful `set_field`

**File:** `src/folio_insights/revision/content_edit.py:210-221`

**Issue:** `edit_shard_content` fetches the shard from `InMemoryShardStore.get()`, which
returns the **same Python object reference** stored in the dict (confirmed: `id(stored) ==
id(shard)` at runtime). The rollback guard (`shard.content_edits.pop()`) is inside the
`except` block that wraps only the `set_field` call (lines 211-215). If `set_field`
**succeeds** but `validate_shard` **raises** (line 219) — which happens for any value that
passes Pydantic's no-validate-assignment setattr but fails `model_validate`, e.g.,
`layer="INVALID_LAYER"` — the shard is left in a corrupted state **visible to the store**,
and `store.put()` is never called but is also never needed to propagate the corruption.

Live execution confirmed: after triggering a `validate_shard` failure on an invalid Literal
value, `await store.get('iri:test')` returns a shard with the bad value set AND the
`ContentEdit` for that failed edit still appended. The store holds corrupted data despite
the caller receiving an exception.

```python
# edit_shard_content lines 210-221 — the gap is between the two try blocks:
shard.content_edits.append(edit)
try:
    set_field(shard, field_path, new_value)  # ← rollback guarded here
except Exception:
    shard.content_edits.pop()
    raise

validate_shard(shard)     # ← raises here; shard is ALREADY mutated in the store
#                            no rollback of content_edits.append or set_field
await store.put(shard_iri, shard)
```

**Fix:** Either (a) extend the rollback window to cover `validate_shard`, or (b) operate on
a deep copy and only write it to the store on success:

```python
# Option (b) — deep copy, then atomic write on success
import copy

shard = await store.get(shard_iri)
if shard is None:
    raise ValueError(...)
if field_path in IMMUTABLE_FIELD_PATHS:
    raise ValueError(...)

working = copy.deepcopy(shard)          # isolation: mutations stay off the stored ref
old_value = get_field(working, field_path)
pre_edit_hash = canonical_content_hash(working)

edit = ContentEdit(...)

working.content_edits.append(edit)
try:
    set_field(working, field_path, new_value)
except Exception:
    raise  # no need to pop — working is discarded on exception

validate_shard(working)                 # raises cleanly; stored shard is untouched

await store.put(shard_iri, working)     # only reaches here on full success
return edit
```

---

### CR-02: `canonical_content_hash` Includes `transaction_time` — Hash Is Non-Deterministic Across Instances

**File:** `src/folio_insights/revision/content_edit.py:107-109`

**Issue:** `canonical_content_hash` calls `shard.model_dump(mode="json")` with no field
exclusions. `ShardEnvelope.transaction_time` has `default_factory=lambda: datetime.now(UTC)`,
so every independently-constructed `ShardEnvelope` (e.g. after a process restart or across
two nodes) has a different `transaction_time`, producing a different hash for logically
identical content. The docstring states the hash is "deterministic" and mirrors
`shards/minting.py`, but the phase context note that `transaction_time` "doesn't leak in"
is factually incorrect — `model_dump()` includes it in the payload.

Live execution confirmed: two `ShardEnvelope(**same_kwargs)` instances constructed 10 ms
apart produce different `canonical_content_hash()` values.

This matters concretely: the `pre_edit_hash` captured in `sign_attestation` is meant to be
a content binding that can be reproduced and verified. If Phase 6 signs the hash and a
verifier reconstructs the shard from stored data (after `transaction_time` has long since
been baked in), the hash will match only by coincidence (same in-process object). A hash
that cannot be independently recomputed from the stored record is not a content binding.

```python
# Current — leaks transaction_time
payload = shard.model_dump(mode="json")
canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

# Fix — exclude the non-content, wall-clock field
payload = shard.model_dump(mode="json", exclude={"transaction_time"})
canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

If `content_edits` itself contains timestamps that are also wall-clock (they are — `edited_at`
is `datetime.now(UTC)`), those are part of the audit chain content and SHOULD be included
since they were recorded at write time and are stable from that point on. Only
`transaction_time`, which is re-generated at construction, needs exclusion.

---

## Warnings

### WR-01: `add_edit` Has No Rollback When `setattr` Raises — Phantom Audit Entry

**File:** `src/folio_insights/shards/audit.py:118-136`

**Issue:** `add_edit` follows the sequence: `getattr` → `content_edits.append(edit)` →
`setattr(shard, field_path, new_value)`. If `setattr` raises (e.g., the caller passes one
of the six `Field(frozen=True)` identity fields), the `ContentEdit` is already in
`shard.content_edits` and is never removed. The chain now carries an audit entry for an
assignment that never happened.

Live execution confirmed: calling `add_edit(shard, 'shard_iri', 'new_iri', ...)` raises
`ValidationError` as expected but leaves `len(shard.content_edits) == 1` with a phantom
entry whose `old_value`/`new_value` describe the failed assignment.

Note: `edit_shard_content` does implement the rollback (`shard.content_edits.pop()` in its
`except` block), but the guard only reaches `add_edit`'s equivalent path, not the
`validate_shard` path (CR-01). `add_edit` is the thin sync wrapper that lacks both rollbacks.

```python
def add_edit(shard, field_path, new_value, editor_did, rationale):
    old_value = getattr(shard, field_path)
    edit = ContentEdit(
        field_path=field_path,
        old_value=old_value,
        new_value=new_value,
        edited_at=datetime.now(UTC),
        editor_did=editor_did,
        rationale=rationale,
        signature=AttestedSignature(...),
    )
    shard.content_edits.append(edit)
    try:
        setattr(shard, field_path, new_value)
    except Exception:
        shard.content_edits.pop()   # ← add this rollback
        raise
```

---

### WR-02: `get_field` / `set_field` Accept Arbitrary Attribute Paths — No Schema-Field Whitelist

**File:** `src/folio_insights/revision/content_edit.py:67-90`

**Issue:** Both helpers use bare `getattr`/`setattr` traversal. Any dotted path that resolves
via Python's attribute lookup is accepted, not just paths to declared Pydantic fields.
Examples that succeed at runtime: `get_field(shard, '__class__')` returns the metaclass,
`get_field(shard, 'model_fields')` returns the field descriptor dict,
`get_field(shard, 'triple.__class__.__bases__')` traverses into class hierarchy.

`IMMUTABLE_FIELD_PATHS` is a deny-list of known protected fields — it does not restrict the
universe of accessible paths to schema-declared fields. An `edit_shard_content` caller
(current trust model: callers are internal, but Phase 10 Arq will expose this as a task
queue handler) can supply an arbitrary `field_path`.

Mitigating factors that limit current exploitability:
- `setattr` on Pydantic models raises `ValidationError` for non-declared fields
  (e.g., `setattr(shard, 'model_config', ...)` raises "no field 'model_config'").
- `validate_shard` follows each `set_field` and would catch a corrupted state.
- Dunder `setattr` mostly fails at the Python/C layer (`__class__ assignment` TypeError).

However, `get_field` leaks internal state into the `old_value` slot of `ContentEdit` for
any path that resolves via `getattr` but raises on `setattr`. The leaked value is stored in
the audit chain (rolled back only if `set_field` raises, per the CR-01 discussion).

**Fix:** Validate `field_path` against the model's declared schema before use:

```python
# At the top of get_field and set_field, or in edit_shard_content before calling either:
def _validate_field_path(shard: ShardEnvelope, path: str) -> None:
    """Raise ValueError if path contains non-model-field segments."""
    obj: Any = shard
    for part in path.split("."):
        model_fields = getattr(type(obj), "model_fields", None)
        if model_fields is not None and part not in model_fields:
            raise ValueError(
                f"Field path segment {part!r} is not a declared model field "
                f"on {type(obj).__name__}. Use only schema-declared paths."
            )
        obj = getattr(obj, part)
```

---

### WR-03: `validate_shard` Return Value Discarded — Validated Copy Never Stored

**File:** `src/folio_insights/revision/content_edit.py:219`

**Issue:** `validate_shard(shard)` creates a **new** `ShardEnvelope` object via
`type(shard).model_validate(shard.model_dump())` and returns it. The call at line 219
discards the return value. `await store.put(shard_iri, shard)` on line 221 writes the
**original mutated object**, not the freshly-validated copy.

In practice this is currently benign for the raise-or-not semantics: if `validate_shard`
raises, the exception propagates and `store.put` is never reached; if it succeeds, the two
objects are semantically equivalent for well-behaved inputs. However:

1. Pydantic `model_validate` can apply coercions (e.g. `str` → `int` for lenient fields,
   timezone normalization). The stored object is the pre-coercion version.
2. If CR-01 is fixed by the deep-copy approach (recommended), the return value of
   `validate_shard` becomes the authoritative validated copy that should be stored.
3. Discarding the return value of a function documented as "Re-run FULL model validation …
   and return the re-validated copy" is a code-smell that will mislead future readers.

**Fix:**
```python
# Replace line 219:
validated_shard = validate_shard(shard)  # raises on bad state

await store.put(shard_iri, validated_shard)   # store the validated copy
return edit
```

(If the CR-01 deep-copy fix is adopted, substitute `working` for `shard` throughout and
apply the same pattern to the working copy.)

---

## Info

### IN-01: `shapes` Graph Re-Parsed From Disk on Every `validate_content_edit_shape` Call

**File:** `src/folio_insights/revision/shape_validation.py:111-112`

**Issue:** `validate_content_edit_shape` parses `content_edit_shape.ttl` from disk on
every invocation via `shapes.parse(str(_SHAPE_PATH), format="turtle")`. If this validator
is called in a hot path (e.g., after every `edit_shard_content` call), repeated disk I/O
and rdflib parse overhead accumulates. Performance is out of v1 scope, but the pattern is
worth noting because it also means test failures will occur silently if the TTL file is
missing at runtime (the `_SHAPE_PATH` existence is only validated at call time, not at
module import).

**Fix (optional):** Cache the parsed shapes graph at module level:

```python
import functools

@functools.cache
def _load_shapes() -> Graph:
    g = Graph()
    g.parse(str(_SHAPE_PATH), format="turtle")
    return g

def validate_content_edit_shape(shard: ShardEnvelope) -> ValidationResult:
    shapes = _load_shapes()          # parsed once, cached thereafter
    data_graph = _build_edit_graph(shard)
    ...
```

---

_Reviewed: 2026-05-27T17:15:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
