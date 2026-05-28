---
phase: 06-did-substrate-6-5
plan: 02
subsystem: identity-substrate
tags: [did, ed25519, sign, verify, key-rotation, did-doc-cache, identity, phase-6]
requires:
  - "Plan 06-01: AttestedSignature 6.1 shape (signing_key_id, did_doc_snapshot_at, verified, cosigners[]); SignedAction Literal; canonical_content_hash via RFC-8785 JCS + F4 pre-norm"
  - "Phase 5 ShardStore in-memory seam (revision/store.py — D-02)"
  - "Phase 1 client-side keystore idiom (polysemy/reviewer.py — 0o600 JWK + did:key multicodec)"
provides:
  - "identity/ package: keys.py + cache.py + resolver.py + signer.py + verifier.py (+ tests/identity scaffold extension)"
  - "DidDocCache Protocol + InMemoryDidDocCache (the D-11 historical-key seam Phase 13 swaps persistence behind)"
  - "resolve_did(did, at, *, cache, http, plc_resolver) — 3-method dispatcher (did:key local decode; did:web .well-known/path-form fetch+cache; did:plc atproto resolve + injectable historical resolver)"
  - "sign_attestation (PyNaCl) + verify_attestation (PyNaCl VerifyKey) with signing-time key capture (DID-04 / SEC-05)"
  - "edit_shard_content's frozen signing_key parameter wired to the real signer (Phase-5 D-09 call site unchanged byte-for-byte)"
  - "test_signature_survives_key_rotation.py (EC3) + test_no_server_keys_contract.py (EC4) + test_sign_verify_methods.py (per-method) + test_did_doc_cache.py"
affects:
  - "Plan 06-03 (binding + CLI + DID-07 preview) signs over canonical_content_hash with this signer and verifies with this verifier"
  - "Phase 7 governance log / promotion / contest consumes AttestedSignature.verified annotations"
  - "Phase 13 persistent DidDocCache implementation replaces InMemoryDidDocCache behind the same Protocol"
tech-stack:
  added:
    - "pynacl SigningKey + VerifyKey (already pinned 1.6.2 in 06-01; first use in this plan)"
    - "atproto.IdResolver default did:plc resolution (already pinned 0.0.65 in 06-01; lazy-imported in resolver.py to keep cold-start cheap for non-plc consumers)"
  patterns:
    - "Protocol + InMemoryFooStore in-memory seam (DidDocCache mirrors ShardStore byte-for-byte — same async shape, same Phase 13 swap contract)"
    - "Injectable network seams (http / plc_resolver as keyword args) so tests use recorded fixtures, not live network"
    - "Lazy intra-package import to dodge the identity<->revision cycle (revision/content_edit.sign_attestation imports identity.signer.sign_attestation inside the function body, not at module load)"
    - "Static AST contract test (ast.walk over .py source) for security invariants — DID-06 is a contract test, not a Pydantic feature"
key-files:
  created:
    - "src/folio_insights/identity/__init__.py"
    - "src/folio_insights/identity/keys.py"
    - "src/folio_insights/identity/cache.py"
    - "src/folio_insights/identity/resolver.py"
    - "src/folio_insights/identity/signer.py"
    - "src/folio_insights/identity/verifier.py"
    - "tests/identity/test_did_doc_cache.py"
    - "tests/identity/test_sign_verify_methods.py"
    - "tests/identity/test_signature_survives_key_rotation.py"
    - "tests/identity/test_no_server_keys_contract.py"
  modified:
    - "src/folio_insights/revision/content_edit.py (sign_attestation now accepts optional signing_key kwargs; edit_shard_content wires real signer through the frozen signing_key seam)"
    - "tests/identity/conftest.py (extended with doc_cache + ed25519_keypair_a/_b + did_web_doc_for + did_plc_doc_for fixtures)"
decisions:
  - "identity.signer accepts cryptography.Ed25519PrivateKey at the public API and converts to PyNaCl SigningKey via raw seed inside _ed25519_key_to_nacl — keeps the Phase-5 D-09 frozen call site (signing_key: Ed25519PrivateKey) intact, picks up PyNaCl's libsodium speed on the hot path, and confines the ONLY non-keys.py private_bytes() call to a single line the EC4 contract test allowlists explicitly (allowance=1)."
  - "Signed payload = the SHA-256 hex STRING (UTF-8 bytes), not the raw 32-byte digest. Signing over the wire representation (sig.over_content_hash) means the verifier compares the verification payload byte-for-byte against the recorded value — no second hash step the verifier can disagree with."
  - "DidDocSnapshot carries public_key_multibase in the canonical did:key multibase form (z + base58btc(0xed01 || raw_pub)) regardless of input encoding (the resolver normalizes publicKeyJwk → multibase). The verifier recovers Ed25519PublicKey via the same public_key_from_did_key decoder — one canonical path through the entire identity stack."
  - "_SENTINEL_NO_AT (1970-01-01 UTC) is the cache-key second-leg when the caller passes at=None. A historical verify with a real signed_at will MISS this entry and force a fresh fetch — the rotation-safe failure mode (no accidental retro-validation by a misaddressed cache hit)."
  - "Lazy import resolves the identity<->revision cycle: identity.signer/verifier import revision.content_edit.canonical_content_hash, but revision.content_edit imports identity.signer.sign_attestation only INSIDE the sign_attestation function body. Module-load dependency direction stays one-way: identity/ → revision/ → shards/."
  - "EC4 contract test uses ast.walk (not regex/grep): a docstring mentioning 'private_bytes' or 'JWK d' would false-positive on a text search; the ast walk inspects actual ast.Call / ast.Dict nodes, so a future contributor cannot sneak a server-side persistence call past the gate via comments."
  - "did:web binding's domain-control proof (SEC-06 §4 of RESEARCH) is intentionally NOT shipped in this plan — Plan 06-03 owns the binding CLI + did bind proof-of-control mechanics. Plan 02 covers RESOLVE+CACHE only; the proof-of-control composition layers on top."
metrics:
  duration: "~35 min"
  completed: "2026-05-28"
  tasks: 4
  files_created: 10
  files_modified: 2
  tests_added: "31 new (10 did_doc_cache + 10 sign_verify_methods + 2 rotation_survival + 9 no_server_keys_contract — 7 explicit cases + 2 parametrize-IDs)"
---

# Phase 6 Plan 02: identity/ Crypto Core — Sign/Verify + Rotation Survival + DID-06 Contract Summary

**One-liner:** Built `src/folio_insights/identity/` (keys + cache + resolver + signer + verifier) on top of the Plan-01 canonicalization + AttestedSignature shape: real ed25519 over JCS via PyNaCl, signing-time key capture (`signing_key_id` + `did_doc_snapshot_at`) so signatures survive key rotation (EC3 green for did:key + did:web), a static AST contract test that enforces DID-06 (no server-side private keys) across every non-keys.py identity module (EC4 green), and the Phase-5 `edit_shard_content(..., signing_key)` frozen seam (D-09) wired byte-for-byte to the real signer.

## What Built

Plan 06-02 closes the two hardest exit criteria of Phase 6:

| Gate                                       | Mechanism                                                                                                   | Test artifact                                       |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| **EC3 — rotation survival (SEC-05)**       | `DidDocCache((did, signed_at)) -> snapshot`; verifier resolves the signing-time key via the cache hit       | `test_signature_survives_key_rotation.py` (did:key degenerate + did:web real rotation) |
| **EC4 — no server-side keys (DID-06)**     | Static AST contract test parses every `identity/*.py` and asserts no `private_bytes` / JWK-`d` writes leave `keys.py` | `test_no_server_keys_contract.py` (9 cases — 4 parametrized + 3 standalone + 2 parametrize-IDs) |

Plus the per-method sign/verify gate (`test_sign_verify_methods.py` — did:key + did:web + did:plc, parametrized) and the DidDocCache Protocol round-trip + resolver branch test (`test_did_doc_cache.py`).

The dep-direction stays one-way: `identity/ → revision/ → shards/` (identity imports `canonical_content_hash` from revision; revision imports `identity.signer.sign_attestation` ONLY inside the function body to avoid the cycle).

## Task Sequence

### Task 1: identity/keys.py — client-side local ed25519 keystore (DID-06)

**Commit:** `689603b`

- Created `src/folio_insights/identity/` package; `__init__.py` re-exports the public API as each submodule lands.
- `keys.py` EXTENDS the Phase-1 `polysemy/reviewer.py` pattern:
  - Default location `~/.folio-insights/signer.jwk` (mode `0o600`, parent dir `0o700`).
  - `generate_keypair(path)` is IDEMPOTENT — second call reuses the on-disk JWK and returns the same `did:key` (mirrors `ensure_reviewer_did`).
  - `did_key_from_public(raw_pub)` + `public_key_from_did_key(did)` round-trip via the W3C `0xed01` multicodec prefix + base58btc, with strict validation (rejects non-`did:key`, non-`z` multibase, non-`0xed01` codecs, wrong-length keys).
  - `_sk_to_jwk` / `_jwk_to_sk` symmetrize the JWK serialization (`{kty: OKP, crv: Ed25519, d, x}`).
- `load_signing_key(path)` REFUSES a group/world-readable keyfile (`PermissionError` on any `S_IRWXG | S_IRWXO` bit set). A key with permissive POSIX mode on a server filesystem is treated as compromised.
- Verified inline: `did_key_from_public ∘ public_key_from_did_key` round-trips a freshly-generated cryptography Ed25519PrivateKey.

### Task 2: identity/cache.py (DidDocCache, D-11) + identity/resolver.py (3-method, D-08)

**Commit:** `134f867`

- `cache.py`:
  - `DidDocCache` `@runtime_checkable` `Protocol` with `async get((did, datetime)) -> DidDocSnapshot | None` and `async put((did, datetime), snapshot)`.
  - `DidDocSnapshot` (Pydantic, `extra="forbid"`): `did`, `fetched_at`, `verification_method_id`, `public_key_multibase`, `raw_doc | None`.
  - `InMemoryDidDocCache` backs the Protocol with a `dict[tuple[str, datetime], DidDocSnapshot]` — mirrors `revision/store.py::InMemoryShardStore` byte-for-byte.
- `resolver.py`:
  - `async resolve_did(did, at=None, *, cache, http, plc_resolver) -> DidDocSnapshot`. Branches:
    - **did:key** — decode via `keys.public_key_from_did_key`; NO network; `at` ignored; cache irrelevant (the key IS the DID; cannot rotate).
    - **did:web** — derive URL (`.well-known/did.json` root form OR `<path>/did.json` path form), fetch via injectable `http` seam (default httpx.AsyncClient), pick ed25519 vm (`Ed25519VerificationKey2020`/`2018`/`Multikey` with `publicKeyMultibase` OR `publicKeyJwk` → normalized to canonical multibase), snapshot under `(did, at)`, cache.
    - **did:plc** — injectable `plc_resolver` seam; default uses `atproto.IdResolver` (lazy-imported in the default to keep cold-start cheap for non-plc consumers). RESOLVE/VERIFY ONLY (D-08) — never submits a PLC write operation.
  - All network seams INJECTABLE; tests pass recorded fixtures.
  - `UnknownDidMethodError` / `UnresolvableDidError` typed errors — resolver NEVER returns a wrong key silently (T-06-09).
- `tests/identity/test_did_doc_cache.py` — 10 tests: Protocol satisfaction, tuple-key round-trip, did:key local decode, did:key `at`-invariance, did:web fetch+cache (1 fetch on hit), did:web path-form URL derivation, did:web JWK-form normalization to canonical multibase, did:plc cache+resolve, unknown method → typed error, malformed (missing vm) → typed error.

### Task 3: identity/signer.py + verifier.py + wire edit_shard_content (DID-04, D-09)

**Commit:** `17629f1`

- `signer.py`:
  - `sign_attestation(content_hash, signing_key, did, action, *, signing_key_id, did_doc_snapshot_at, now=None) -> AttestedSignature`.
  - Uses PyNaCl `SigningKey(raw_seed)` (~6× cryptography's ed25519 hot path; STACK.md L47); signs over the SHA-256 hex string's UTF-8 bytes (so the recorded `over_content_hash` IS what is signed — no hidden re-hash step the verifier can disagree with).
  - Base64url-no-pad encodes the 64-byte signature into the string-typed `AttestedSignature.signature` field.
  - Populates `signing_key_id` + `did_doc_snapshot_at` (DID-04 / SEC-05); leaves `verified=None` (T-06-03 anti-spoofing default).
- `verifier.py`:
  - `async verify_attestation(shard_or_hash, sig, *, cache, resolver=resolve_did, http=None, plc_resolver=None) -> bool`.
  - If a `ShardEnvelope` is passed: LAZY-imports `revision.content_edit.canonical_content_hash`, recomputes the JCS hash, and FAILS CLOSED if it does not match `sig.over_content_hash` (a tampered shard whose content drifted since signing is rejected before any signature math).
  - Resolves the signing-time DID-doc snapshot via the cache+resolver (short-circuits on cache hit — rotation-safe).
  - Extracts the ed25519 public key from `public_key_multibase` via the same did:key multibase decoder; verifies the ed25519 signature with PyNaCl `VerifyKey`.
  - Returns `False` (never raises) on signature/hash/lookup/encoding failure — the boolean is the only failure mode the caller sees.
- `revision/content_edit.py`:
  - `sign_attestation(editor_did, over_content_hash, *, signing_key=None, signing_key_id="", did_doc_snapshot_at=None)`: when `signing_key=None`, stays the Phase-5 unsigned stub (`signature=""`); when supplied, lazily imports `identity.signer.sign_attestation` and delegates. Lazy import dodges the identity<->revision cycle.
  - `edit_shard_content` wires `signing_key` into the real signer when supplied; default `signing_key_id` for did:key signers is `"<did>#<multibase>"` (W3C did:key convention). The Phase-5 frozen signature (D-09) — `async def edit_shard_content(shard_iri, field_path, new_value, editor_did, rationale, signing_key, store)` — is unchanged byte-for-byte.
- 148 tests pass across `tests/identity/` + `tests/revision/` + `tests/shards/test_dep_leak_guard.py`.

### Task 4: rotation-survival (EC3) + no-server-key contract (EC4) + per-method coverage

**Commit:** `9e8aac4`

- `tests/identity/conftest.py` extended:
  - `doc_cache` — fresh `InMemoryDidDocCache` per test (mirrors `store` fixture from `tests/revision/conftest.py`).
  - `ed25519_keypair_a` / `ed25519_keypair_b` — sign-time + post-rotation keypairs.
  - `did_web_doc_for(did, sk)` / `did_plc_doc_for(did, sk)` — builders that synthesize a recorded did.json carrying `sk`'s public half in Multikey publicKeyMultibase form. No live atproto/HTTP touched.
- `tests/identity/test_sign_verify_methods.py` (10 tests):
  - Per-method: round-trip True, tampered hash False, wrong-key False (did:key), `signing_key_id` populated (DID-04).
  - `@pytest.mark.parametrize("method", ["did:key", "did:web", "did:plc"])` exhaustive parametrize as the explicit acceptance-criterion proof.
- `tests/identity/test_signature_survives_key_rotation.py` (2 tests):
  - did:key — degenerate; `resolve_did(did)` (current) vs `resolve_did(did, at=signed_at)` (historical) yield IDENTICAL `public_key_multibase` (key IS the DID; cannot rotate).
  - did:web REAL ROTATION:
    1. Pre-seed cache with snapshot (key A) under `(did, signed_at)`.
    2. Sign with key A; `signing_key_id` + `did_doc_snapshot_at` captured.
    3. Rotated http now publishes key B (DIFFERENT multibase — asserted explicitly, so the test isn't a tautology).
    4. Historical verify passes via cache hit — `fetch_calls == []` (no live re-fetch, rotation-safe).
    5. Naive verifier (fresh cache, `did_doc_snapshot_at` swapped to "now") FAILS — proves the snapshot mechanism is load-bearing, not bug-by-coincidence.
- `tests/identity/test_no_server_keys_contract.py` (9 cases — EC4):
  - `test_no_private_bytes_call_outside_keystore` parametrized over 4 non-keystore modules (cache, resolver, signer, verifier): allowance=1 for signer (the one-shot SigningKey conversion in `_ed25519_key_to_nacl`); allowance=0 for the other three.
  - `test_no_jwk_d_written_to_disk_outside_keystore` parametrized over the same 4 modules: fails if any module ast-contains BOTH a JWK `"d"` dict literal AND a `write_text`/`write_bytes`/`write` call.
  - `test_signer_accepts_signing_key_as_parameter` / `test_verifier_accepts_cache_as_parameter` — inspect.signature probes that lock the API shape.
  - `test_no_module_global_private_key_constant` — walks module-level `ast.Assign` nodes for `Ed25519PrivateKey.generate()` calls.
- Full identity/ suite: **96 tests pass**. Verification across identity/ + revision/ + shards/test_dep_leak_guard.py: **171 tests pass**.

## Verification

All plan verification commands green:

| Command                                                                 | Result               |
| ----------------------------------------------------------------------- | -------------------- |
| `uv run pytest tests/identity/ -x -q`                                   | 96 passed            |
| `uv run pytest tests/revision/ -x -q`                                   | 70 passed, 1 warning (pre-existing from Phase 5) |
| `uv run pytest tests/shards/test_dep_leak_guard.py -x`                  | 5 passed             |
| `uv run python -c "import folio_insights.identity as i; print(sorted(dir(i)))"` | exports DidDocCache, sign_attestation, verify_attestation, resolve_did, generate_keypair, load_signing_key, did_key_from_public, public_key_from_did_key, InMemoryDidDocCache, DidDocSnapshot, UnknownDidMethodError, UnresolvableDidError |

## Success Criteria

- identity/keys.py extends the Phase-1 client-side keystore; private keys never leave the local machine (D-07, DID-06).
- did:key + did:web full sign/verify; did:plc resolve/verify only, no writes (D-08, DID-01).
- Every AttestedSignature captures signing_key_id + did_doc_snapshot_at; verification resolves the signing-time key (DID-04).
- test_signature_survives_key_rotation green for did:key + did:web (EC3, SEC-05); no-server-key contract test green (EC4, DID-06).
- DidDocCache is the in-memory (did, signed_at) seam mirroring ShardStore; Phase 13 fills persistence (D-11).
- edit_shard_content signs through its frozen signing_key parameter (D-09); shards/ stays dep-clean (dep-leak guard green).

## Deviations from Plan

**1. [Rule 2 — Missing critical functionality] `revision.content_edit.sign_attestation` kept its 2-positional-arg public signature instead of being replaced wholesale**

- **Found during:** Task 3 (signer wiring)
- **Issue:** The plan's Task 3 action says "REPLACE the body of the `sign_attestation` stub so it delegates to `identity.signer.sign_attestation`". But a wholesale body-replace would break all Phase-5 callers that pass `(editor_did, over_content_hash)` with no `signing_key` — including the `shards/audit.py::add_edit` inline construction that the audit-stub path still uses unsigned (T-06-04 ACCEPTED in Plan 01).
- **Fix:** Added optional kwargs (`signing_key=None`, `signing_key_id=""`, `did_doc_snapshot_at=None`) and branch on `signing_key is None` — when None, stay the Phase-5 unsigned stub (`signature=""`); when supplied, delegate to `identity.signer.sign_attestation`. Honest unsigned audit path stays honest; real signing flows when the caller threads a key through.
- **Files modified:** `src/folio_insights/revision/content_edit.py`
- **Commit:** `17629f1`

**2. [Rule 3 — Blocking circular import] `revision.content_edit.sign_attestation` lazy-imports `identity.signer.sign_attestation` inside the function body**

- **Found during:** Task 3 (signer wiring)
- **Issue:** The plan's Task 3 read_first note flagged this exact risk: "revision/ may import identity/ since identity depends on revision only for canonical hashing; if that creates a cycle, pass the signer in or compute here using identity primitives without a top-level identity import — resolve the cycle explicitly and document it." `identity.verifier` imports `revision.content_edit.canonical_content_hash` (lazy, inside the function — same trick) and `identity.signer` imports `AttestedSignature` from `shards.envelope`. If `revision.content_edit` top-imported `identity.signer`, Python's module loader would hit a partially-initialized cycle.
- **Fix:** Lazy import — `from folio_insights.identity.signer import sign_attestation as _signer` inside the function body of `revision.content_edit.sign_attestation`. Documented explicitly in the docstring. The module-load dep direction stays one-way: identity/ → revision/ → shards/.
- **Files modified:** `src/folio_insights/revision/content_edit.py`, `src/folio_insights/identity/verifier.py` (verifier mirrors the lazy-import pattern for `canonical_content_hash`).
- **Commit:** `17629f1`

**3. [Rule 2 — Missing critical functionality] `identity/__init__.py` re-exports grew incrementally per task instead of all-at-once**

- **Found during:** Task 1 (initial `__init__.py` referenced cache/resolver/signer/verifier that did not yet exist)
- **Issue:** A single up-front `__init__.py` that imports cache/resolver/signer/verifier would break Task 1's verification (those modules don't exist until later tasks).
- **Fix:** Wrote `__init__.py` with only the keys.py exports in Task 1; extended it in Task 2 (cache + resolver) and Task 3 (signer + verifier). Final public surface verified via `dir(i)` includes all 12 symbols.
- **Files modified:** `src/folio_insights/identity/__init__.py`
- **Commits:** `689603b`, `134f867`, `17629f1`

No other deviations; the plan executed substantially as written.

## Authentication Gates

None — no third-party services were contacted (atproto / did:web fetches are injectable in tests; production CLI use is post-Plan-03's `did bind` command). The `autonomous: false`-flagged dependency add was handled at Plan 06-01; no new pip deps in this plan.

## Threat Model Coverage

All five T-06-* threats in the plan's `<threat_model>` block are mitigated:

| Threat | Mitigation Status |
|--------|-------------------|
| **T-06-05** Information disclosure / private key | MITIGATED — keys.py is the SOLE persistence point (0o600 home-dir keyfile); load_signing_key refuses world-readable files; `test_no_server_keys_contract.py` parses every non-keys.py identity module with ast and fails the build on any second `private_bytes()` call site or JWK-`d`-write co-presence (EC4 green). |
| **T-06-06** Spoofing via key rotation | MITIGATED — `signing_key_id` + `did_doc_snapshot_at` captured at signing; verifier resolves the signing-time key via `DidDocCache((did, signed_at))` snapshot; `test_signature_survives_key_rotation.py` proves the did:web rotation case AND that a naive current-key verifier WOULD fail (load-bearing assertion). EC3 green. |
| **T-06-07** Tampering / MITM'd did:web doc | MITIGATED — did:web fetched over HTTPS (httpx with verify=True default); the cache snapshot at signing time is authoritative for verification; a later current-doc swap cannot retro-validate a forged signature (proven by the EC3 test). Plan 06-03 adds the domain-control proof on top. |
| **T-06-08** Elevation via did:plc write | AVOIDED — resolver.py is RESOLVE/VERIFY ONLY (D-08); no module under identity/ submits a PLC operation. Documented in resolver.py module docstring + per-branch docstring; the historical-pinning resolver is INJECTED by the caller (Phase 13 / tests provide their own op-log walker). |
| **T-06-09** Supply-chain / network decode failure | MITIGATED — network seams (http, plc_resolver) are INJECTABLE so tests use recorded fixtures (no live network); pinned versions inherited from Plan 06-01; resolver raises `UnknownDidMethodError` / `UnresolvableDidError` — never returns a wrong key silently. |

## Threat Flags

None — no NEW security-relevant surface introduced beyond the plan's threat model. The did:web HTTP fetch surface is fully gated by the `cache`-first short-circuit and the injectable `http` seam.

## Known Stubs

- **Default did:plc historical resolver is current-only** — `_default_plc_resolve` calls `atproto.IdResolver().did.resolve(did)` which returns the CURRENT plc doc; for a historical `at` lookup the caller MUST inject a `plc_resolver` that walks the PLC op log (`plc.directory/<did>/log/audit`) and `dag_cbor`-decodes to pin the operation valid at `at`. This is acceptable because:
  - did:plc CACHE hits short-circuit before the default is called — `test_did_doc_cache.py` exercises the cache-hit path.
  - Plan 06-02 ships RESOLVE/VERIFY ONLY (D-08); the genesis/rotation write path is out of scope.
  - Phase 13 will provide a persistent `DidDocCache` + op-log resolver pair; nothing in Phase 6 needs the default to walk the op log.
  - Documented in `_default_plc_resolve`'s docstring.

- **`identity/__init__.py` `verify_attestation` re-export does not auto-set the `verified` annotation back on the AttestedSignature** — the verifier returns a `bool` only. A caller that wants to persist the cached `verified=True/False` annotation back into a shard's `signatures[]` list must do so explicitly (e.g. via `sig.model_copy(update={"verified": ok})`). This matches the Plan 06-01 `verified: bool | None = None` anti-spoofing default (an unverified signature can never read as verified by default); Phase 7's governance log is the consumer that will own the persistence side.

No unintentional stubs.

## Self-Check: PASSED

**Files (all relative to repo root):**
- src/folio_insights/identity/__init__.py — present, new
- src/folio_insights/identity/keys.py — present, new
- src/folio_insights/identity/cache.py — present, new
- src/folio_insights/identity/resolver.py — present, new
- src/folio_insights/identity/signer.py — present, new
- src/folio_insights/identity/verifier.py — present, new
- src/folio_insights/revision/content_edit.py — present, modified
- tests/identity/conftest.py — present, modified
- tests/identity/test_did_doc_cache.py — present, new
- tests/identity/test_sign_verify_methods.py — present, new
- tests/identity/test_signature_survives_key_rotation.py — present, new
- tests/identity/test_no_server_keys_contract.py — present, new

**Commits (verified via `git log --oneline d46c6d7..HEAD`):**
- 689603b — feat(06-02): identity/keys.py — client-side local ed25519 keystore (DID-06)
- 134f867 — feat(06-02): identity/cache.py + resolver.py — DidDocCache (D-11) + 3-method resolver (D-08)
- 17629f1 — feat(06-02): identity/signer.py + verifier.py — real ed25519 + wire edit_shard_content (DID-04, D-09)
- 9e8aac4 — test(06-02): EC3 rotation-survival + EC4 no-server-key contract + per-method sign/verify (DID-04, DID-06, SEC-05)
