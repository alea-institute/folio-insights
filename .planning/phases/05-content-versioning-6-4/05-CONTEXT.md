# Phase 5: Content Versioning (§6.4) - Context

**Gathered:** 2026-05-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Harden the **already-built** `ContentEdit` chain (REQ **SHARD-09**) into a real
content-versioning discipline under the immutable hex32 shard IRIs from Phase 4.
PRD §6.4 / §21.7 = "mutable content with append-only audit log; the ID never changes."

Phase 2 (D-08) already shipped the `ContentEdit` frozen sub-model + `add_edit()`
(mutate-in-place + append) in `shards/audit.py`; that module's own comments
enumerate the Phase 5 to-do list. Phase 5 delivers, against the three exit criteria:

1. **`edit_shard_content()` write path** matching the PRD §6.4 signature (async,
   store-backed, DID-signed) — with Phase 6/13 dependencies stubbed (see D-01..D-05).
2. **Forward-only / append-only enforcement** at two layers: a Pydantic
   `@model_validator` (works today, no RDF) **and** a real pyshacl TTL shape +
   `validate_content_edit_shape()` defense-in-depth (exit criterion 2 — "SHACL guard").
3. **`get_shard_at(iri, t)`** historical reconstruction by reverse-replay, correct
   across a 10-edit fixture (exit criterion 3).

**NOT in scope:**
- Real DID signing / ed25519 / JCS canonicalization — **Phase 6** (DID Substrate).
  Phase 5 ships the signature *slot* + a placeholder `sign_attestation` stub.
- Real persistent storage (Oxigraph / named graphs) — **Phase 13**. Phase 5 ships
  an in-memory dict store behind a thin interface Phase 13 swaps out.
- The full SHACL-Hybrid shape suite + Pydantic-to-SHACL generator — **Phase 11**.
  Phase 5 ships only the *one focused* append-only/forward-only shape it needs.
- Supersession-chain workflow / promotion / contest mechanics — **Phase 7**
  (the `supersedes`/`superseded_by` link pair exists on the envelope but its
  workflow is governance scope).
</domain>

<decisions>
## Implementation Decisions

### Edit API Scope & Stub Boundaries
- **D-01:** Build the **full PRD §6.4 `edit_shard_content()` signature now**, with
  Phase 6/13 dependencies stubbed — not a thinner in-memory-only helper. The
  signature mirrors PRD §6.4: `edit_shard_content(shard_iri, field_path, new_value,
  editor_did, rationale, signing_key) -> ContentEdit`. Rationale: lock the call-site
  contract once so Phase 6 (signing) and Phase 13 (storage) fill stubs *behind* the
  interface without churning callers.
- **D-02:** **In-memory dict store** keyed by `shard_iri`, implementing `get/put`,
  behind a thin interface (e.g. a `ShardStore` protocol/ABC). This keeps the PRD's
  by-IRI signature honest (`edit_shard_content(shard_iri, ...)` and
  `get_shard_at(iri, t)` both look up by IRI) and gives `get_shard_at` a real lookup.
  **Phase 13 swaps Oxigraph in behind the same interface.**
- **D-03:** Keep the write path **`async def`** matching the PRD signature, so Phase 10
  (Arq) and Phase 13 (async Oxigraph) slot in without signature churn. Tests use
  `pytest-asyncio` (add to dev deps if not already present).

### ContentEdit Schema Enrichment
- **D-04:** Enrich `ContentEdit` to the **full PRD §6.4 shape**, closing all three
  Phase-2 gaps:
  - **Dotted `field_path`** (e.g. `"triple.object"`, `"sense"`) replacing/augmenting
    flat `field_name`. Enables editing `triple.object` (re-parenting — a core PRD
    decision-#4 use case) while `triple.subject` / `triple.predicate` stay immutable.
    Requires dotted get/set-field helpers (see D-09).
  - **`rationale: str`** on every edit — governance/audit (Phase 7) wants the "why".
  - **`signature` placeholder** — see D-05.
- **D-05:** `ContentEdit.signature` **reuses the existing `AttestedSignature` stub**
  (the Phase 6 placeholder already on the envelope: `did`/`action`/`signed_at`/
  `signature`/`over_content_hash`). The stubbed `sign_attestation(...)` returns a
  placeholder `AttestedSignature` with `action="content_edit"`, `over_content_hash`
  set, and `signature=""`. **`canonical_content_hash()` computes a REAL deterministic
  JSON hash now** (over the pre-edit shard) — Phase 6 swaps the JCS canonicalization
  in. So the audit-record shape and the pre-edit content hash are real on day one;
  only the cryptographic signature is deferred.

### Immutable-Field Enforcement
- **D-06:** **Authoritative immutable set = the full PRD §6.4 set, as one central
  constant** (e.g. `IMMUTABLE_FIELD_PATHS`): the **6** Pydantic-frozen identity fields
  (`shard_iri`, `provenance_hash`, `source_uri`, `source_span`, `extracted_at`,
  `first_extractor_did`) **PLUS** `triple.subject`, `triple.predicate` (identity-defining),
  **PLUS** the append-only lists themselves (`content_edits`, `signatures`).
  `edit_shard_content` raises (clear error, before any mutation) if `field_path` is in
  this set. Pydantic-`frozen` (6 fields) is necessary but **not sufficient** — this
  constant is the single source of truth, and the SHACL shape (D-07) mirrors it.

### Forward-only / Append-only Enforcement ("SHACL guard")
- **D-07:** Enforce at **two layers** (exit criterion 2 satisfied literally):
  1. **Pydantic `@model_validator`** on the shard (works today, no RDF): rejects
     "edits to past versions" — `content_edits` must be append-only and
     monotonic-in-`edited_at` (a new edit's `edited_at` ≥ the last edit's; no
     mutation/removal of existing entries).
  2. **Real pyshacl TTL shape + `validate_content_edit_shape()`** as
     defense-in-depth, mirroring the Phase 1 **distinguo** `validate_*_shape()`
     pattern the `audit.py` comment cites. Runs over a serialized fixture
     (minimal RDF mapping local to this phase — does NOT pull the Phase 13 store
     forward; just enough to feed pyshacl).
- **D-08 (semantics of "edit to a past version"):** Two things are forbidden:
  (a) **mutating or deleting any existing `ContentEdit` entry** (history is
  immutable — the list is append-only), and (b) **appending an edit whose
  `edited_at` precedes the latest edit's `edited_at`** (no back-dated inserts).
  Both the validator and the SHACL shape enforce both.

### `get_shard_at(iri, t)` Reconstruction
- **D-09:** **Reverse-replay with strict edges.** Reconstruct by starting from the
  current shard state and **undoing every edit with `edited_at > t`** (apply
  `old_value` in reverse-chronological order via the dotted-path set-field helper).
  Edge cases:
  - **`t` before `extracted_at`** → return **`None`** (the shard didn't exist yet).
  - **Time ties** (equal `edited_at`) → broken by **list order** (append order is
    the tiebreak; an edit at exactly `t` is *included* as having-happened-by-`t`).
  - **Unknown IRI** → `None` (or a clearly-typed raise — planner's call, but it must
    be unambiguous, not a silent wrong answer).
  - Reconstruction must **not mutate** the stored/current shard (work on a copy).
  - `get_shard_at(iri, extracted_at)` returns the **exact-as-extracted** state
    (the PRD §21.7 tradeoff-note guarantee).

### Claude's Discretion
- Exact module layout: PRD suggests `src/folio_insights/revision/content_edit.py`.
  Planner decides whether the new write path + store live in a new `revision/`
  package or extend `shards/audit.py` — honoring D-01..D-09.
- The dotted-path `get_field`/`set_field` helpers (parse `"triple.object"` →
  nested attr access). Must respect D-06 (immutable paths) and the `Triple`
  submodel's mutability (`Triple` is `extra="forbid"`, not frozen — so
  `triple.object` is assignable, but the edit gate blocks `triple.subject`/`.predicate`).
- Whether to keep `add_edit()` as a thin **sync** convenience wrapper over the new
  async path or deprecate it — provided the existing `test_audit_log.py` semantics
  (or their migrated equivalents) stay green.
- Whether `validate_shard()` (the PRD post-edit re-validation call) is a real
  hook now or a thin pass-through pending Phase 11 — keep it honest, don't fake
  validation that isn't happening.

### Migration consequences (mechanical — planner enumerates blast radius)
- Renaming/augmenting `field_name` → `field_path` re-shapes `ContentEdit`. Touch
  points: `shards/audit.py` (`ContentEdit`, `add_edit`), `tests/shards/test_audit_log.py`
  (uses `field_name`), and any fixtures referencing `content_edits` entries
  (`tests/shards/fixtures/*.json`, `tests/shards/conftest.py`).
- Adding `rationale` (required) + `signature` to `ContentEdit` updates every
  construction site, including the `add_edit` wrapper and test builders.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Content versioning spec (SHARD-09)
- `.planning/REQUIREMENTS.md` (row **SHARD-09**) — acceptance criteria:
  `test_content_edit_audit_append_only.py` passes; SHACL guard rejects edits to
  past versions; `get_shard_at(iri, t)` retrieves historical state.
- `PRD-v2.0-draft-2.md` **§6.4** — content versioning under immutable IDs
  (decision #7): the `edit_shard_content()` write path (authoritative signature),
  the immutable-field list, and the mutable-field list. **Read before planning.**
- `PRD-v2.0-draft-2.md` **§21.7** — the resolved design ("mutable content with
  append-only audit log"), rationale, and the `get_shard_at(iri, extracted_at)`
  exact-as-extracted tradeoff guarantee.

### Existing code to extend / reuse (Phase 2)
- `src/folio_insights/shards/audit.py` — `ContentEdit` frozen sub-model + `add_edit()`.
  **The to-do comment block (lines 22-37, 68-74) is the Phase 5 spec in code.** EXTEND.
- `src/folio_insights/shards/envelope.py` — `ShardEnvelope` (15 fields), the **6
  `Field(frozen=True)` identity fields** (D-07 set), the `Triple` submodel
  (`triple.subject`/`.predicate`/`.object`), bitemporal fields
  (`valid_time_start/end`, `transaction_time`), `content_edits` list, and the
  `AttestedSignature` Phase-6 stub (reused by D-05). `ShardEnvelope.model_rebuild()`
  at `audit.py` bottom resolves the `content_edits` forward-ref — preserve it.
- `tests/shards/test_audit_log.py` — current append/capture-order/frozen-field
  tests; migrate as `field_name`→`field_path` lands. The new
  `test_content_edit_audit_append_only.py` (exit criterion 1) is additive.
- `tests/shards/conftest.py` (`_sample_shard` / `_SUBTYPE_DEFAULTS`) — test builder
  used across Phase 2/3 audit tests; extend for the new ContentEdit shape.

### SHACL infrastructure (for D-07)
- `src/folio_insights/services/shacl_validator.py` + `src/folio_insights/export/shapes.ttl`
  — the existing v1 pyshacl validation entry points and shape file. Reference for
  how shapes are loaded/run; the new append-only/forward-only shape mirrors the
  Phase 1 distinguo `validate_*_shape()` defense-in-depth pattern.

### Prior decisions (carried forward)
- `.planning/phases/02-shard-envelope/02-CONTEXT.md` — D-07 (6 frozen identity
  fields) and D-08 (ContentEdit + add_edit "mutable-with-audit"; explicitly defers
  forward-only SHACL gate + transactional hardening to Phase 5).
- `.planning/phases/04-iri-scheme-6-3/04-CONTEXT.md` — immutable hex32 IRIs + global
  content-addressed registry. Edits **never** change the shard IRI (the asymmetry
  this phase enforces).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`ContentEdit` + `add_edit()`** (`shards/audit.py`) — the audit record + helper
  already exist; Phase 5 enriches the record (D-04) and replaces the minimal helper
  with the full `edit_shard_content()` path (D-01).
- **`AttestedSignature` stub** (`shards/envelope.py`) — reused as the `ContentEdit.signature`
  type (D-05); no new placeholder type needed.
- **6 `Field(frozen=True)` identity fields** — Pydantic already blocks assignment;
  Phase 5's central `IMMUTABLE_FIELD_PATHS` (D-06) extends the guarantee to
  `triple.subject`/`.predicate` + append-only lists.
- **pyshacl plumbing** (`services/shacl_validator.py`, `export/shapes.ttl`) — reuse
  the load/validate pattern for the new content-edit shape (D-07).

### Established Patterns
- **Pure-Pydantic + stdlib in `shards/`** — Phase 2 deliberately kept storage libs
  out of the shards package. Phase 5's in-memory store (D-02) + minimal RDF-for-SHACL
  (D-07) should respect that boundary (no Oxigraph/aiosqlite leak into `shards/`).
- **`@model_validator(mode="after")`** — Phase 3 colocated 4 subtype validators in
  `subtypes.py`; the forward-only validator (D-07.1) follows that idiom.
- **Hypothesis property tests** (Phase 2/4 determinism) — candidate for the
  reverse-replay invariant (`get_shard_at(iri, latest) == current`;
  `get_shard_at(iri, extracted_at) == as-extracted`).
- **`validate_*_shape()` defense-in-depth** — Phase 1 distinguo pattern the audit.py
  comment explicitly tells Phase 5 to mirror for `validate_content_edit_shape()`.

### Integration Points
- The new in-memory `ShardStore` (D-02) is the seam Phase 13 (Oxigraph) replaces.
- `sign_attestation` / `canonical_content_hash` (D-05) are the seams Phase 6 (DID
  substrate, JCS) replaces.
- `validate_shard()` post-edit re-validation is the seam Phase 11 (SHACL Hybrid)
  fills out.
</code_context>

<specifics>
## Specific Ideas

- Operator chose the **ambitious scope**: build the full PRD `edit_shard_content()`
  contract now (with stubs) rather than a minimal in-memory helper — explicitly to
  freeze the call-site contract before Phase 6/13 fill the stubs.
- "SHACL guard" is read **literally**: a real pyshacl TTL shape must exist in Phase 5
  (alongside the Pydantic validator), not deferred wholesale to Phase 11.
- `canonical_content_hash` should be **real now** (deterministic JSON), even though
  the cryptographic signature is a Phase 6 stub — the operator wants the content
  hash meaningful from day one.
</specifics>

<deferred>
## Deferred Ideas

- **Real ed25519 / JCS `sign_attestation`** — Phase 6 (DID Substrate); Phase 5 ships
  the slot + placeholder.
- **Persistent Oxigraph storage + named graphs** — Phase 13; Phase 5 ships the
  in-memory `ShardStore` interface.
- **Full SHACL-Hybrid shape suite + Pydantic-to-SHACL generator** — Phase 11; Phase 5
  ships one focused content-edit shape.
- **Supersession / promotion / contest workflow** over `supersedes`/`superseded_by`
  — Phase 7 (Governance). Phase 5 only touches the content-edit audit log.
- **Arq async orchestration** of edits — Phase 10; Phase 5 keeps the path `async def`
  so it slots in cleanly.

### Reviewed Todos (not folded)
None — STATE pending-todos = none.
</deferred>

---

*Phase: 5-Content Versioning (§6.4)*
*Context gathered: 2026-05-27*
