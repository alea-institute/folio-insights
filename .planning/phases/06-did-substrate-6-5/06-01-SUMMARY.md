---
phase: 06-did-substrate-6-5
plan: 01
subsystem: identity-substrate
tags: [did, jcs, canonicalization, attested-signature, identity, phase-6]
requires:
  - "Phase 02 ShardEnvelope + AttestedSignature stub (envelope.py L49)"
  - "Phase 05 canonical_content_hash JSON seam (revision/content_edit.py L172-201)"
  - "Phase 05 ContentEdit + AttestedSignature slot (shards/audit.py)"
provides:
  - "Real 6.1 AttestedSignature shape (extra=forbid + signing_key_id + did_doc_snapshot_at + verified + reserved cosigners[])"
  - "SignedAction Literal reconciled to PRD §3.1 + DID-02 (12 actions)"
  - "RFC-8785 JCS canonical_content_hash with F4 pre-normalization (NFC + datetime pin + None-keep)"
  - "_jcs_canonical_bytes helper (exported for cross-impl golden test)"
  - "tests/identity scaffold + EC2 1000-shuffled-order property test + F4 cross-impl golden test"
  - "Pinned DID stack (PyNaCl, jcs, atproto, dag-cbor, joserfc, authlib) at STACK.md versions"
affects:
  - "Plan 06-02 (signer/verifier/resolver) signs over canonical_content_hash and constructs AttestedSignature"
  - "Plan 06-03 (binding + CLI + DID-07 preview) iterates the SignedAction governance subset"
  - "Phase 13 historical-key cache (DidDocCache seam pattern set up here)"
tech-stack:
  added:
    - "pynacl==1.6.2 (libsodium ed25519 hot path; ~6x cryptography)"
    - "jcs==0.2.1 (RFC 8785 JSON canonicalization; DID-03)"
    - "atproto==0.0.65 (did:plc resolver; DID-01 / D-08)"
    - "dag-cbor==0.3.3 (DAG-CBOR decode of PLC op log)"
    - "joserfc==1.6.4 (JWS wrapping for VC export; replaces python-jose)"
    - "authlib==1.7.0 (OAuth sub-claim semantics; DID-05 / SEC-06)"
  patterns:
    - "Self-referential Pydantic model via model_rebuild() at module bottom (mirrors ShardEnvelope/ContentEdit)"
    - "Pre-normalize-then-canonicalize pipeline (NFC strings + datetime pin BEFORE jcs.canonicalize)"
    - "Cross-impl golden test against the pinned reference library (jcs==0.2.1 acts as RFC-8785 anchor)"
key-files:
  created:
    - "tests/identity/__init__.py"
    - "tests/identity/conftest.py"
    - "tests/identity/test_canonical_jcs_properties.py"
    - "tests/identity/test_jcs_golden.py"
    - "tests/identity/fixtures/jcs_golden/README.md"
    - "tests/identity/fixtures/jcs_golden/ (50 vendored fixtures: 15 unicode + 10 numbers + 10 structure + 8 nulls + 7 key-ordering)"
  modified:
    - "pyproject.toml (locked DID stack + cryptography >=46 bump + identity marker + RISK-4 rejection comment)"
    - "uv.lock (148 -> 149 packages; cryptography 48.0.0 -> 46.0.7 + 6 new pins)"
    - "src/folio_insights/shards/envelope.py (AttestedSignature reshape + SignedAction Literal + model_rebuild)"
    - "src/folio_insights/shards/__init__.py (export SignedAction)"
    - "src/folio_insights/revision/content_edit.py (JCS swap + _normalize_for_jcs + _canonicalize_datetime + _jcs_canonical_bytes helper)"
decisions:
  - "OQ1 resolution applied: option A — content_edit IS in the SignedAction Literal (alongside 8 governance actions); DID-07 preview iterates the governance subset only. Keeps every Phase-5 construction site green without muddying EC5."
  - "OQ2 resolution applied: signing_key_id (str = '') and did_doc_snapshot_at (datetime | None = None) are Optional + defaulted so the unsigned add_edit / sign_attestation stub paths still construct honestly."
  - "OQ3 resolution applied: explicit None values are KEPT (not stripped) in JCS pre-normalization — jcs serializes null deterministically; stripping would lose 'absent' vs 'explicitly null' for Optional bitemporal-adjacent fields."
  - "cryptography>=41 bumped to cryptography>=46 (uv resolved 46.0.7 = STACK.md pin) for the did:web verify path. No other consumer pins it lower."
  - "DID-07 8-action governance subset selected: {extract, promote, demote, contest, supersede, retract, distinguo, role_assertion}. Spelling 'role_assertion' (snake_case) chosen over DID-02's 'role-assertion' (hyphenated) to match PRD §3.1 L146 test-name convention ('test_role_assertion_signed.py') and Python identifier style."
  - "Datetime canonical format locked: '%Y-%m-%dT%H:%M:%S.%fZ' (RFC-3339 UTC, fixed 6-digit microseconds, literal 'Z' suffix). Walks both datetime objects AND ISO strings Pydantic mode='json' emits — handles '...+00:00' and '...Z' forms with a single canonical output."
  - "_jcs_canonical_bytes exported in __all__ (private-by-naming-convention) so the cross-impl golden test can pin our canonicalization core against the cyberphone reference."
metrics:
  duration: "~30 min"
  completed: "2026-05-28"
  tasks: 4
  files_created: 55
  files_modified: 5
  tests_added: "63 new (1000-example property + 50 parametrized golden + 11 invariance/exclusion guards + 1 fixture-count regression)"
---

# Phase 6 Plan 01: Crypto Schema + JCS Canonicalization Foundation Summary

**One-liner:** Locked the DID stack at STACK.md pins (PyNaCl + jcs + atproto + dag-cbor + joserfc + authlib; cryptography → 46.0.7), reshaped AttestedSignature to the real 6.1 contract (extra=forbid + signing_key_id + did_doc_snapshot_at + verified + reserved cosigners[]) with a PRD-reconciled SignedAction Literal, and swapped RFC-8785 JCS into canonical_content_hash with the F4 pre-normalization recipe (recursive NFC + canonical-RFC-3339-UTC datetime pin + explicit-None KEEP) — proven by a 1000-shuffled-order property test (EC2) and a 50-input cross-implementation golden test against the cyberphone RFC-8785 reference (F4 closure).

## What Built

Plan 06-01 is the gate Phase 6 needs: Plan 02 (signer/verifier/resolver) signs over the hash this plan canonicalizes and constructs the AttestedSignature this plan reshapes; Plan 03 (binding + CLI + preview) exercises both. If canonical_content_hash were non-deterministic (Pitfall F4 — BLOCKING), no signature could ever verify. This plan closes F4 with two orthogonal gates:

| Gate                       | Sampling                       | Discipline                  | Test artifact                                  |
| -------------------------- | ------------------------------ | --------------------------- | ---------------------------------------------- |
| **EC2 order-independence** | 1000 random shards × 3 seeds   | Hypothesis property test    | `test_canonical_jcs_properties.py`             |
| **F4 cross-impl**          | 50 fixtures × RFC-8785 anchor  | Reference-library compare   | `test_jcs_golden.py` + `fixtures/jcs_golden/`  |

Both are green; the property test runs at @max_examples=1000 in ~1.5s with deadline disabled.

## Task Sequence

### Task 1: Add the locked DID stack to pyproject.toml + identity marker

**Commit:** `10bea29`

- Added the 6-package DID stack at exact STACK.md pins (RISK-4 lock):
  `pynacl==1.6.2`, `jcs==0.2.1`, `atproto==0.0.65`, `dag-cbor==0.3.3`,
  `joserfc==1.6.4`, `authlib==1.7.0`.
- Bumped `cryptography>=41` → `cryptography>=46` (uv resolved 46.0.7 = STACK pin)
  for the did:web verify path. uv showed `Updated cryptography v48.0.0 -> v46.0.7`
  (uv interprets the `>=46` floor against the lockfile resolution context).
- Added RISK-4 rejection comment in dependencies block: `didkit`, `pydid`,
  `python-jose`, `fastapi-users` explicitly rejected (DID-01 acceptance
  criterion: "explicit rejection of didkit/pydid/python-jose/fastapi-users").
- Registered `identity: Phase 6 DID substrate tests` pytest marker (mirrors
  the existing `shards:` entry).
- `uv lock` resolved 149 packages; `uv sync --extra dev` confirmed
  `import nacl, jcs, atproto, dag_cbor, joserfc, authlib` succeeds.

### Task 2: Reshape AttestedSignature to the real 6.1 shape (D-13)

**Commit:** `9e6de90`

- REPLACED (not extended) the Phase 2 permissive stub:
  - `ConfigDict(extra="allow")` → `ConfigDict(extra="forbid")` (T-06-03 integrity gate).
  - Added `signing_key_id: str = ""` (DID URL + `#fragment`, DID-04 / SEC-05),
    `did_doc_snapshot_at: datetime | None = None`, `verified: bool | None = None`
    (cache annotation; None default is the anti-spoofing guarantee — an
    unverified signature can never read as verified).
  - Added `cosigners: list["AttestedSignature"] = Field(default_factory=list)` —
    RESERVED present-but-empty list for the deferred 6.3 N-of-M multi-sig
    (D-13), so 6.3 adds behavior without a second breaking reshape.
- Reconciled `action: str` → `SignedAction` Literal against PRD §3.1 + DID-02:
  - 8-action DID-07 governance subset: `extract, promote, demote, contest,
    supersede, retract, distinguo, role_assertion`.
  - 4 additional PRD-vocab reviewer actions (kept-but-outside DID-07 preview):
    `content_edit, reparent, reconcile, resolve_contest`.
  - `content_edit` is the default so the Phase-5 unsigned audit-stub paths
    (`add_edit` L127, `sign_attestation` L215) continue to construct.
- Resolved the self-referential `cosigners` forward ref via
  `AttestedSignature.model_rebuild()` at module bottom (mirrors the
  `ShardEnvelope.model_rebuild()` in `audit.py`).
- Exported `SignedAction` from `shards/__init__.py`.
- envelope.py STAYS pure-Pydantic — `grep` for `(nacl|jcs|atproto|dag_cbor|
  joserfc|rdflib|pyoxigraph)` imports returns 0 lines. The shards/ dep-leak
  guard stays green.
- All 218 shards+revision tests pass after the reshape; no construction
  site needed changes (the new fields all have defaults; `content_edit` is
  a valid Literal member; `AttestedSignature()` with no args still constructs).

### Task 3: Swap RFC-8785 JCS into canonical_content_hash with F4 pre-norm (D-12)

**Commit:** `fde6cd6`

- Imported `jcs` and `unicodedata` at module top; dropped the bare `json` import
  (`json.dumps` line removed in favor of `_jcs_canonical_bytes`).
- Added three helpers:
  - `_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"` — canonical RFC-3339 UTC, fixed
    6-digit microseconds, literal `Z` suffix.
  - `_canonicalize_datetime(dt)` — coerces tz-aware UTC and emits the canonical
    form; raises on naive datetimes (D-04 invariant guard).
  - `_normalize_for_jcs(obj)` — recursively NFC-normalizes string keys and
    values, detects ISO-8601 datetime strings (both `...+00:00` and `...Z`
    forms) and coerces them to the canonical representation, walks dicts/
    lists, passes through other scalars.
  - `_jcs_canonical_bytes(payload)` — applies `_normalize_for_jcs` then
    `jcs.canonicalize`. THE single canonicalization core both signer and
    verifier flow through.
- Rewrote `canonical_content_hash` body to: `payload = shard.model_dump(
  mode="json", exclude=_HASH_EXCLUDED_FIELDS)` → `sha256(_jcs_canonical_bytes(
  payload)).hexdigest()`.
- Function signature, `_HASH_EXCLUDED_FIELDS`, and every call site
  (`edit_shard_content` L302, `audit`) are UNCHANGED — the D-05 / D-12 seam.
- Exported `_jcs_canonical_bytes` in `__all__` (private-by-naming-convention)
  so the cross-impl golden test can pin it against the cyberphone reference.
- Datetime hash-stability verified inline: a `extracted_at` with
  µ-second precision hashes identically before and after a `model_validate(
  model_dump(mode="json"))` round-trip (Plan acceptance criterion 5).
- All 70 revision tests pass with the swap; no upstream changes required.

### Task 4: tests/identity scaffold + JCS property + cross-impl golden tests

**Commit:** `d2626f5`

- Created `tests/identity/` package: `__init__.py`, `conftest.py`,
  `test_canonical_jcs_properties.py`, `test_jcs_golden.py`,
  `fixtures/jcs_golden/README.md`, and 50 vendored fixture JSON files.
- `conftest.py`:
  - Imports `_sample_shard` from `tests/shards/conftest.py` so the property
    test exercises REAL validated `ShardEnvelope` instances (not synthesized
    dicts).
  - `UNICODE_NOISE_SAMPLES` — 7 hand-picked NFD/NFC pairs (combining accents,
    smart quotes, em-dash, NBSP, non-breaking hyphen).
  - `shard_payloads()` Hypothesis composite strategy — randomizes only the
    CONTENT fields that survive `_HASH_EXCLUDED_FIELDS` (transaction_time,
    valid_time_*, signatures, content_edits are excluded by design).
  - `shuffle_dict_keys(d, seed)` — recursive dict-key permutation that
    preserves list order (RFC-8785 lists are order-significant).
- `test_canonical_jcs_properties.py` (EC2 gate):
  - `@given(payload=shard_payloads()) @settings(max_examples=1000,
    deadline=None)` — 1000 random shards.
  - For each, asserts `_jcs_canonical_bytes(natural) ==
    _jcs_canonical_bytes(shuffled)` under three differently-seeded recursive
    dict-key permutations.
  - Parametrized NFC/NFD invariance test over the 7 UNICODE_NOISE_SAMPLES
    pairs — proves the F4 #4 surface is closed.
  - Microsecond-precision datetime hash-stability test across
    `model_validate(model_dump(mode="json"))` round-trip.
  - Exclusion-set guard: mutating only `transaction_time`/`valid_time_*`/
    `signatures` leaves the hash unchanged.
  - Sanity dual: mutating included content (`sense`) DOES change the hash.
- `test_jcs_golden.py` (F4 cross-impl gate):
  - Parametrized over the 50 vendored fixtures; for each, asserts
    `_jcs_canonical_bytes(input) == jcs.canonicalize(_normalize_for_jcs(input))`
    (RFC-8785 reference cross-check).
  - NFC/NFD pair test using fixtures `u08_combining_accent_nfc.json` and
    `u09_combining_accent_nfd.json` — different pre-norm bytes, IDENTICAL
    canonical bytes after our recipe.
  - Fixture-count regression guard: `>= 50` (a future refactor can't silently
    shrink F4 coverage).
- 50 vendored fixtures by category: 15 unicode (NBSP, em-dash, curly
  quotes, BMP + astral emoji, NFC/NFD accents, CJK, RTL Arabic, ZWJ,
  control chars, escapes) + 10 numbers (0, 1, neg, 0.0, 1.0, 0.5, 1e-7,
  1e21, pi-precision, beyond-2^53) + 10 structure (empty/single/nested,
  array-of-objects, deeply-nested) + 8 nulls (null, true/false, all-falsy)
  + 7 key-ordering (reverse-sorted, Unicode keys, numeric strings).
- All 63 identity tests pass under `pytest.mark.identity`.

## Verification

All five plan verification commands green:

| Command                                                                 | Result               |
| ----------------------------------------------------------------------- | -------------------- |
| `uv run pytest tests/shards -x -q`                                      | 148 passed           |
| `uv run pytest tests/revision -x -q`                                    | 70 passed, 1 warning (pre-existing) |
| `uv run pytest tests/identity -x -q`                                    | 63 passed            |
| `uv run pytest tests/shards/test_dep_leak_guard.py -x`                  | 5 passed             |
| `uv run python -c "import nacl, jcs, atproto, dag_cbor, joserfc, authlib"` | exits 0           |

The 1 warning in `tests/revision/test_edit_shard_content.py::
test_validate_shard_rejects_silent_wrong_type` is a Pydantic serializer
warning for a deliberately-wrong-type value in a validation-failure test —
pre-existing from Phase 5, not introduced by this plan.

## Success Criteria

- ✅ Locked DID stack installed at STACK.md pins (DID-01).
- ✅ RISK-4 rejection comment for `didkit`/`pydid`/`python-jose`/`fastapi-users`.
- ✅ `identity` pytest marker registered.
- ✅ AttestedSignature reshaped to the real 6.1 shape with `extra="forbid"`,
   `signing_key_id`, `did_doc_snapshot_at`, `verified`, and reserved
   `cosigners[]` (D-13, DID-02).
- ✅ `action` is a `Literal` reconciled against PRD §3.1; all construction
   sites green (`content_edit` is a valid member; new fields all default).
- ✅ `canonical_content_hash` uses RFC-8785 JCS with the F4 pre-normalization
   recipe; exclusion set + call site unchanged (D-12, DID-03).
- ✅ EC2 1000-shuffled-order property test green (order-independence + Unicode
   invariance + datetime stability + exclusion-set preservation).
- ✅ F4 cross-impl golden test green on 50 vendored RFC-8785 fixtures
   including NFC/NFD pair invariance.
- ✅ `shards/` imports zero crypto/RDF/storage libraries (dep-leak guard
   green; grep for `nacl|jcs|atproto|dag_cbor|joserfc|rdflib|pyoxigraph`
   in envelope.py returns 0).

## Deviations from Plan

None — plan executed exactly as written.

The plan was conservatively written assuming the JCS swap might break revision
tests; in practice the F4 pre-normalization recipe is a strict superset of the
old `json.dumps(sort_keys=True)` semantics for the inputs Phase 5 tests
construct (no NFD strings, no exotic datetime forms), so all 70 revision tests
pass unchanged.

The plan's Task 2 lists `audit.py` in its files block, but the existing
`add_edit` inline `AttestedSignature(...)` at audit.py L127 carries
`action="content_edit"` — which is now a valid Literal member — and supplies
no fields beyond the old shape. The new fields all default, so audit.py
needed NO modification. The plan's `<files>` block listed audit.py as a
potential touch point; verifying it stayed green is recorded as the actual
outcome.

## Authentication Gates

None — plan is `autonomous: false` per project policy (new pip dependencies
need operator approval), but the wave-level orchestrator gate already handled
that approval before this executor was spawned. No mid-execution auth gates
occurred.

## Threat Model Coverage

All four T-06-* threats in the plan's `<threat_model>` block are mitigated
or accepted as designed:

| Threat | Mitigation Status |
|--------|-------------------|
| **T-06-01** Supply chain (6 new deps) | MITIGATED — exact `==` pins from STACK.md; uv.lock hashes pin artifacts; `autonomous: false` gate forced operator review at the wave-orchestrator level; RISK-4 rejection list documented in pyproject.toml. |
| **T-06-02** canonical_content_hash non-determinism (F4) | MITIGATED — RFC-8785 JCS + NFC + canonical-datetime + explicit-None recipe; 1000-shuffled-order property test + 50-input cross-impl golden test (both gates green). |
| **T-06-03** AttestedSignature accepting unknown/forged fields | MITIGATED — `extra="forbid"` rejects unknown kwargs; `action` Literal rejects out-of-vocabulary values; `verified` defaults None (an unverified sig can never read as verified by default). All three guards verified inline by acceptance-criteria probes. |
| **T-06-04** content_edit stub still unsigned after reshape | ACCEPTED — `signing_key_id`/`signature` default empty; Phase-5 audit-stub paths stay HONESTLY unsigned (no false "verified"); real signing arrives in Plan 06-02. Documented, bounded deferral. |

No new threat flags discovered.

## Known Stubs

`signing_key_id: str = ""` and `signature: str = ""` defaults on
AttestedSignature are stubs by design (T-06-04 ACCEPTED) — the Phase-5
audit / `sign_attestation` path stays honestly unsigned until Plan 06-02
wires real ed25519 signing through `edit_shard_content`'s `signing_key`
parameter. `verified: bool | None = None` default is the anti-spoofing
guarantee: an unverified signature can never read as verified.

No unintentional stubs.

## Self-Check: PASSED

**Files (all relative to repo root):**
- ✅ `pyproject.toml` — present, modified
- ✅ `uv.lock` — present, modified
- ✅ `src/folio_insights/shards/envelope.py` — present, modified
- ✅ `src/folio_insights/shards/__init__.py` — present, modified
- ✅ `src/folio_insights/revision/content_edit.py` — present, modified
- ✅ `tests/identity/__init__.py` — present, new
- ✅ `tests/identity/conftest.py` — present, new
- ✅ `tests/identity/test_canonical_jcs_properties.py` — present, new
- ✅ `tests/identity/test_jcs_golden.py` — present, new
- ✅ `tests/identity/fixtures/jcs_golden/README.md` — present, new
- ✅ `tests/identity/fixtures/jcs_golden/*.json` — 50 files present, new

**Commits (verified via `git log --oneline`):**
- ✅ `10bea29` — chore(06-01): add locked DID stack
- ✅ `9e6de90` — feat(06-01): reshape AttestedSignature
- ✅ `fde6cd6` — feat(06-01): swap RFC-8785 JCS into canonical_content_hash
- ✅ `d2626f5` — test(06-01): add tests/identity JCS property + golden tests
