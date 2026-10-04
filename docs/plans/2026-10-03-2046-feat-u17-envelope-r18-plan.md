---
title: U17 Shard Envelope Migration to the R18 Disposition - Plan
type: feat
date: 2026-10-03
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# U17 Shard Envelope Migration to the R18 Disposition - Plan

## Goal Capsule

- Objective: Give the shipped shard envelope an explicit, frozen schema version and one sanctioned, versioned record adapter. The adapter migrates current records forward, rejects unsupported versions, and preserves IDs, explicit nulls and the original signed bytes. Phase 13 storage can then persist the envelope without freezing a vocabulary that R18 keeps revisable.
- Authority: Damien's 2026-10-03 answer "U17 envelope, then Phase 13 storage" (Decision Sheet `folio-insights-2026-10-03-2047-history-scrub-and-phase13`, q3-next-work) authorizes planning and implementing U17 on a branch. It does not authorize a production migration or a deployment.
- Inputs: migration-plan U17 (`docs/plans/2026-09-27-1930-refactor-v2-gsd-to-ce-migration-plan.md`), the [confirmed R18 record](../reviews/2026-09-30-r18-disposition.md), the Phase 13 plan's Risks and Dependencies section and its U1 (`docs/plans/2026-09-30-0913-feat-phase13-storage-plan.md`), and PRD §6–§7.
- Stop conditions: An existing test regresses, a legacy record's ID or explicit null changes on migration, or a signature verifies over transformed content.
- Delivery: Branch `feat/u17-envelope-r18`. The orchestrator owns push, review and integration. Phase 13 storage does not start here.

## Product Contract

### Summary

R18 accepts every packet group except two. The taxonomy group is `revised` and stays revisable. The evidence-plan group is `revised` and concerns annotation, not the envelope. For the envelope, the accepted groups say three things:

- Freeze identity: identifiers, document binding, `schema_version` stamps, span mechanics and reference positions.
- Keep the controlled vocabularies revisable between cycles, "with a schema version and migration".
- Treat `null` as data, not as absence.

The envelope already freezes its six identity-and-origin fields. It lacks the other two things. It has no schema version, so a stored record cannot say which vocabulary it was written under. It has no migration path, so changing a vocabulary later would break every stored record. U17 adds both, and stops there.

### Sizing from R18

| R18 group | Disposition | What U17 does |
|---|---|---|
| Identity and reference boundary | accepted | Adds a frozen `schema_version` stamp to the envelope, alongside the six frozen identity fields. Leaves identity minting unchanged. |
| Proposition ledger fields and null semantics | accepted | Version-2 records must carry nullable envelope keys explicitly. Migration keeps explicit nulls as nulls. |
| Working proposition taxonomy | revised | Nothing to freeze. The version stamp is the hook that later taxonomy revisions migrate through. |
| Actor/adjudication, disposition, citation-edge vocabularies | accepted (revisable) | Same hook: change only with a version bump and a registered migration. The envelope carries none of these vocabularies today. |
| Shape descriptors and application-level composites | accepted | Not implemented in U17. See Open Question 1. The current subtypes stay as application types, and their vocabularies become revisable through the same versioning. |
| Axiom lifecycle status | accepted (design-only) | None. |
| Interchange record and migration policy | accepted | Versioned records plus a forward-only, copying `migrate` path modelled on `folio_propositions.migrate_record`. Unknown versions are rejected. |
| Annotation-testing and Phase A evidence plan | revised | None. It concerns annotation, not the envelope. |

### Requirements

- R1. Every envelope carries an integer `schema_version`. It is frozen, it is part of the identity boundary, and in-memory models only accept the current version.
- R2. One record adapter loads stored shard records of any supported version and dumps current-version records. Supported versions are legacy 1, which is the unstamped shape shipped through Phase 8, and current 2.
- R3. The adapter rejects unsupported versions with a typed error: missing a migration path, non-integer, boolean, below 1, or newer than current. It never guesses.
- R4. Migration copies its input and never mutates it. It is forward-only, and it preserves the shard IRI, the provenance hash, every other identity field and every explicit null.
- R5. The adapter keeps the exact original record bytes and the source version alongside the migrated shard.
- R6. Transformed content never inherits an old signature. A content-changing migration must make every pre-migration signature fail verification over the migrated content, and it must clear any cached `verified` flag on loaded legacy records. A content-preserving migration keeps existing signatures verifiable.
- R7. Existing shard JSON entry points go through the adapter. Today that is the identity CLI's shard loader.

### Scope Boundaries

- In scope: `shards/envelope.py`, a new `shards/records.py`, `revision/content_edit.py` (gate and hash exclusion), `identity/cli.py` (loader), tests, and a PRD §6.1 pointer.
- Out of scope: Phase 13 storage, journals, RDF projection, and an RDF adapter for envelopes, which do not exist yet. Also out of scope: span offsets, folio-propositions composite adapters, subtype restructuring, and any production data conversion.
- Synthetic data only. No book-derived fixtures.

## Planning Contract

### Key Technical Decisions

- KTD1. **Version numbering.** `ENVELOPE_SCHEMA_VERSION = 2`. Unstamped records are legacy version 1, read as "absent stamp means 1". This mirrors folio-propositions' integer `schema_version`. It is separate from `vocab_version`, which pins the RDF vocabulary (CalVer) and stays as it is. Governs R1, R2.
- KTD2. **The stamp is excluded from the content hash.** `schema_version` describes the record's representation, not its content, just as `transaction_time` does. Excluding it means a content-preserving migration (1→2) leaves `canonical_content_hash` unchanged, so every existing signature still verifies. A migration that changes content changes the hashed bytes, so old signatures fail through the verifier's existing recompute-and-compare step. Rule for future migrations: a step that reinterprets a value must change its bytes, for example by renaming a Literal, and must not keep the same bytes under a new meaning. The registry records this rule. Governs R6.
- KTD3. **Declared content preservation.** Each migration step declares `content_preserving`. Loading a legacy record always resets every signature's cached `verified` annotation to `None`, including nested cosigners. A stored "verified" flag therefore never survives a version change, whatever the step declares. Signatures stay in the append-only list, because removing them would break that contract, and the verifier decides their validity. Governs R6.
- KTD4. **Strict null presence on version 2.** A version-2 record must contain the nullable envelope keys `valid_time_start`, `valid_time_end`, `supersedes` and `superseded_by`, even when their value is `null`. Absence is a malformed record. The 1→2 migration writes absent keys as explicit `null` and leaves present nulls untouched. Python constructors keep their defaults. The rule applies to stored records, not to in-memory construction. Governs R4.
- KTD5. **Pure-model placement.** The adapter lives in `shards/records.py` and uses only stdlib and Pydantic, so it obeys the dep-leak guard. It never imports `revision/` or `identity/`. Phase 13's `storage/` package will call it. Governs R2, R5.
- KTD6. **Immutability on two belts.** `schema_version` is `Field(frozen=True)` and is also listed in `IMMUTABLE_FIELD_PATHS`, so `edit_shard_content` refuses it before any mutation. Governs R1.

### Open questions for Damien

These are product-judgment readings of R18. U17 takes the conservative reading, which freezes identity fields only (the PRD HOLD fallback), and continues. None of them blocks Phase 13.

1. **Subtypes as shared-model configurations.** R18 accepts "the five shard subtypes become configurations or composites of the shared model". Under `shard-mapping.md`, `conflicting_authorities` would become a cross-document composite, and `disputed_proposition` an application-level thread of `Proposition` nodes. U17 keeps the five Pydantic subtypes as application types and does not build a folio-propositions adapter. Should a later unit restructure them, or add an export adapter to `PropositionDocumentRecord`?
2. **Span offsets.** R18 freezes "span mechanics", which upstream means the atomic `start_char`/`end_char`/`text` group. The envelope has only `source_span` text, and that text is part of the minted identity. U17 adds no offset fields. Should a later schema version add an optional, atomic offset group?

## Implementation Units

### U1. Envelope schema-version stamp

- Goal: Make every envelope declare its schema version and refuse any other version in memory.
- Requirements: R1. Decisions: KTD1, KTD2, KTD6.
- Files: `src/folio_insights/shards/envelope.py`, `src/folio_insights/shards/__init__.py`, `src/folio_insights/revision/content_edit.py`, `tests/shards/test_envelope_schema_version.py`.
- Approach: Add the module constant `ENVELOPE_SCHEMA_VERSION = 2`, and declare `schema_version: int = Field(default=ENVELOPE_SCHEMA_VERSION, frozen=True)` with a strict-int validator that equals the current version. Add `schema_version` to `IMMUTABLE_FIELD_PATHS` and `_HASH_EXCLUDED_FIELDS`.
- Test scenarios:
  - A default construction carries 2.
  - Values 1 and 3, and the bool `True`, are rejected on construction.
  - Assignment raises `frozen_field`.
  - `edit_shard_content(..., "schema_version", ...)` is refused and leaves the store unchanged.
  - The content hash is equal with and without the stamp in the dump.
  - Every subtype round-trips with its stamp.

### U2. Versioned record adapter and migration

- Goal: Provide one sanctioned load/dump path that migrates legacy records and rejects unsupported versions.
- Requirements: R2–R6. Decisions: KTD1–KTD5.
- Files: new `src/folio_insights/shards/records.py`, `src/folio_insights/shards/__init__.py`, new `tests/shards/test_envelope_records.py`.
- Approach:
  - `dump_shard_record(shard) -> bytes` writes compact JSON from `model_dump(mode="json")`, with explicit nulls and the stamp.
  - `load_shard_record(raw: bytes | str | Mapping, *, migrations=MIGRATIONS) -> LoadedShardRecord` reads the version and validates it, checks null-key presence for the current version, and applies consecutive registered `EnvelopeMigration(from, to, content_preserving, apply)` steps on deep copies. On a legacy load it resets cached `verified` flags, then validates through the discriminated `Shard` union.
  - The result is frozen and holds the shard, `source_schema_version`, `original_bytes`, `migrated` and `content_preserved`.
  - Errors: `UnsupportedEnvelopeVersion` and `MalformedEnvelopeRecord`, both `ValueError` subclasses.
- Test scenarios:
  - A synthetic legacy record without a stamp migrates to 2. IRI, provenance hash and identity fields are byte-equal. An explicit `null` stays `null`. Absent nullable keys become explicit `null`. The input mapping is unchanged.
  - The original bytes equal the input bytes exactly.
  - A version-2 dump→load round-trips equal, and `migrated` is false.
  - A version-2 record missing `supersedes` is malformed.
  - Versions 0, -1, 3, `"2"`, `true`, `null` and a version with no path all raise `UnsupportedEnvelopeVersion`.
  - A real ed25519 signature over a legacy record's content verifies after the 1→2 migration.
  - A synthetic content-changing step makes that signature fail verification, and its `verified=True` cache is reset to `None`.
  - Every subtype loads through the adapter.

### U3. Route shard JSON entry points through the adapter, and point the PRD at it

- Goal: Make sure no shipped entry point bypasses versioning.
- Requirements: R7.
- Files: `src/folio_insights/identity/cli.py`, `tests/identity/test_did_cli.py` (or a new focused test), `PRD-v2.0-draft-2.md` §6.1.
- Approach:
  - Replace the identity CLI's `TypeAdapter(Shard)` loader with `load_shard_record`.
  - Unsupported versions exit with a clear error.
  - Add a short §6.1 note: envelope schema version 2, the legacy version-1 migration, and the adapter as the only sanctioned record path.
- Test scenarios:
  - The CLI preview of a legacy (unstamped) synthetic shard file succeeds and reports the same content hash as before.
  - A file stamped `schema_version: 99` exits non-zero with "unsupported".

## Verification Contract

Use env `FOLIO_INSIGHTS_FOLIO_ENRICH_PATH="/home/damienriehl/Coding Projects/folio-enrich/backend"`, `PYTHONPATH=src:.`, and the folio-insights venv interpreter.

- `timeout 900 python -m pytest -q -m "not gate5 and not slow" --benchmark-skip -p no:cacheprovider`. Baseline is 1028 passed and 34 skipped. Expect no regressions, plus the new tests.
- `python -m pytest tests/bench/test_gate1_rdf12.py -q`.
- `ruff check` on the changed files.
- `git status --short --ignored output` shows nothing new.

## Definition of Done

- U1–U3 pass their scenarios, the full suite has no regressions, and ruff is clean on the changed files.
- The two open questions are recorded here and reported to the orchestrator.
- Phase 13 handoff: the storage journal persists `original_bytes` and `source_schema_version` exactly as `load_shard_record` returns them. Projection and export call the adapter and never call `TypeAdapter(Shard)` directly. Any future vocabulary revision lands as a version bump plus a registered migration that declares `content_preserving`. An RDF adapter for envelopes is new Phase 13 work, and it must carry `schema_version`. No production migration happens without the snapshot and restore rehearsal named in the Phase 13 plan.
