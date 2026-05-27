# Phase 5: Content Versioning (§6.4) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-27
**Phase:** 5-Content Versioning (§6.4)
**Areas discussed:** Edit API scope, ContentEdit schema, SHACL depth, get_shard_at reconstruction, stub boundaries (store / async / signature / immutable set)

---

## Edit API scope

| Option | Description | Selected |
|--------|-------------|----------|
| Harden in-memory, defer rest | Harden existing in-memory add_edit() + add get_shard_at(); defer async store-backed DID-signed edit_shard_content() to Phase 6/13 | |
| Build full PRD signature w/ stubs | Build the PRD's async edit_shard_content(shard_iri, field_path, ..., signing_key) now, with store + sign_attestation stubbed | ✓ |
| You decide | Planner chooses the scope boundary | |

**User's choice:** Build full PRD signature w/ stubs
**Notes:** Lock the PRD §6.4 call-site contract now so Phase 6 (signing) and Phase 13 (storage) fill stubs behind the interface without churning callers. → CONTEXT D-01.

---

## ContentEdit schema gaps

| Option | Description | Selected |
|--------|-------------|----------|
| Dotted field_path | Replace/augment flat field_name with dotted field_path (enables triple.object edits while subject/predicate stay immutable) | ✓ |
| rationale field | Add PRD's `rationale` string to every ContentEdit | ✓ |
| signature placeholder | Add nullable signature slot now (Phase 6 fills it) | ✓ |
| Keep flat field_name | Ship none; keep minimal Phase 2 shape | |

**User's choice:** All three — dotted field_path + rationale + signature placeholder
**Notes:** Close every Phase-2→PRD §6.4 schema gap now. → CONTEXT D-04, D-05.

---

## SHACL depth ("SHACL guard")

| Option | Description | Selected |
|--------|-------------|----------|
| Pydantic now + real TTL shape | Pydantic @model_validator (works today) AND a focused pyshacl TTL shape + validate_content_edit_shape() defense-in-depth | ✓ |
| Pydantic only, defer TTL | Runtime validator only; defer SHACL TTL to Phase 11 | |
| Full SHACL only | Real pyshacl TTL as single source of truth (pulls Phase 13 RDF forward) | |

**User's choice:** Pydantic now + real TTL shape
**Notes:** Exit criterion 2 ("SHACL guard") read literally — a real shape must exist in Phase 5 alongside the validator, mirroring the Phase 1 distinguo validate_*_shape() pattern. → CONTEXT D-07, D-08.

---

## get_shard_at(iri, t) reconstruction

| Option | Description | Selected |
|--------|-------------|----------|
| Reverse-replay + strict edges | Start from current; undo old_value for every edit with edited_at > t. t before extracted_at → None; ties by list order; unknown IRI → None/clear raise | ✓ |
| Forward-replay from original | Rebuild original-as-extracted, re-apply edits up to t | |
| You decide | Planner picks direction + edge semantics | |

**User's choice:** Reverse-replay + strict edges
**Notes:** get_shard_at(iri, extracted_at) returns exact-as-extracted (PRD §21.7 guarantee); reconstruction must not mutate the stored shard. → CONTEXT D-09.

---

## Stub boundaries (follow-up after ambitious-scope choice)

### Stub store
| Option | Description | Selected |
|--------|-------------|----------|
| In-memory dict store | Minimal dict store keyed by shard_iri (get/put) behind a thin interface Phase 13 swaps for Oxigraph | ✓ |
| Pass shard object directly | edit_shard_content(shard, ...) / get_shard_at(shard, t); no store | |
| You decide | Planner picks the store boundary | |

**User's choice:** In-memory dict store → CONTEXT D-02

### Async?
| Option | Description | Selected |
|--------|-------------|----------|
| Keep async (match PRD) | `async def` matching PRD; Phase 10 Arq + Phase 13 async Oxigraph slot in cleanly | ✓ |
| Sync now, async later | Sync function now, refactor later | |

**User's choice:** Keep async (match PRD) → CONTEXT D-03

### Signature stub
| Option | Description | Selected |
|--------|-------------|----------|
| Reuse AttestedSignature + real hash | ContentEdit.signature reuses AttestedSignature stub; canonical_content_hash computes a REAL deterministic JSON hash now; sign_attestation returns placeholder (signature="") | ✓ |
| Reuse AttestedSignature, hash stubbed too | Same shape, but hash also placeholder until Phase 6 | |
| Plain nullable string | signature is Optional[str]=None; Phase 6 replaces type | |

**User's choice:** Reuse AttestedSignature + real hash → CONTEXT D-05

### Immutable set
| Option | Description | Selected |
|--------|-------------|----------|
| Full PRD set, central constant | IMMUTABLE_FIELD_PATHS = 6 frozen identity fields + triple.subject + triple.predicate + content_edits + signatures; raise before any mutation | ✓ |
| Pydantic-frozen only | Rely on the 6 frozen fields only (allows triple.subject/predicate edits) | |
| You decide | Planner derives the set | |

**User's choice:** Full PRD set, central constant → CONTEXT D-06

---

## Claude's Discretion

- Module layout: new `revision/content_edit.py` package vs extending `shards/audit.py`.
- Dotted-path `get_field`/`set_field` helper implementation.
- Keep `add_edit()` as a thin sync wrapper vs deprecate (tests must stay green).
- Whether `validate_shard()` post-edit re-validation is a real hook now or a thin pass-through pending Phase 11 (must stay honest).
- Mechanical migration blast radius for `field_name`→`field_path` + new required `rationale`/`signature` fields.

## Deferred Ideas

- Real ed25519/JCS `sign_attestation` — Phase 6.
- Persistent Oxigraph storage + named graphs — Phase 13.
- Full SHACL-Hybrid shape suite + Pydantic-to-SHACL generator — Phase 11.
- Supersession / promotion / contest workflow — Phase 7.
- Arq async orchestration of edits — Phase 10.
