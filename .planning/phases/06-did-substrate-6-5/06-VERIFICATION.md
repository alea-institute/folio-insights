---
phase: 06-did-substrate-6-5
verified: 2026-05-29T03:30:00Z
status: human_needed
score: 10/11 must-haves verified
overrides_applied: 0
deferred:
  - truth: "Playwright OAuth→DID binding covers all 3 paths (EC1 second clause)"
    addressed_in: "Post-Phase-14 web phase"
    evidence: "CONTEXT.md D-02: 'Playwright OAuth→DID binding across 3 paths + styled preview screenshot test → post-Phase-14 web phase.' ROADMAP EC1 full clause deferred by documented scope decision."
human_verification:
  - test: "Run `folio-insights did generate --method=key` and then `folio-insights did preview --action=promote --shard-json=<path>` on a real shard JSON file to confirm the preview renders a 64-char hex content_hash and a human-readable promote description."
    expected: "Output includes a 64-character hexadecimal string and a PROMOTE line with shard IRI and epistemic_status."
    why_human: "CliRunner tests cover the path, but the terminal UX (Rich formatting, field alignment) can only be confirmed by a human in an actual terminal session."
  - test: "Confirm `folio-insights --help` lists the `did` subgroup and `folio-insights did --help` lists all five subcommands: generate, bind, sign, verify, preview."
    expected: "Both help texts render cleanly; no import errors; did subgroup is visible in the root command listing."
    why_human: "Exit code + output content is tested by CliRunner; visual formatting of the help output in a real terminal is not."
---

# Phase 6: DID Substrate (§6.5) Verification Report

**Phase Goal:** Ship DID-signed attestations as the security substrate for every v2.0 write action, including hardware-key and multi-sig paths.
**Verified:** 2026-05-29T03:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification.

**Scope note:** Phase 6 scope is §6.5 core (6.1). DID-08 (hardware-key, 6.2) and DID-09 (multi-sig, 6.3) are P2 sub-phases deferred per ROADMAP.md. The CONTEXT.md D-02 decision further defers the Playwright OAuth→DID web flow to post-Phase-14. All technical implementation of 6.1 core was followed by a 13-finding code review (CR-01..CR-04, WR-01..WR-09) with all findings fixed, bringing the test count from 366 to 394.

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | `pytest tests/identity/` is green across did:key / did:web / did:plc (EC1 pytest clause) | VERIFIED | 176 identity tests pass; parametrized over all 3 DID methods in test_sign_verify_methods.py |
| 2 | `verify(sign(x))` passes across shuffled field orders for 1000 random shards (EC2, JCS order-independence) | VERIFIED | test_canonical_jcs_properties.py: @given(max_examples=1000) property test green; 66 identity property+golden tests pass |
| 3 | `test_signature_survives_key_rotation.py` is green — historical signing_key_id + did_doc_snapshot_at replay works (EC3, SEC-05) | VERIFIED | 2 tests green: did:key (degenerate) + did:web (real rotation with key-B swap, proves cache is load-bearing) |
| 4 | Security review confirms no server-side signing keys for any DID (EC4, DID-06) | VERIFIED | test_no_server_keys_contract.py: AST-walks identity/*.py confirming zero private_bytes() outside keys.py (allowance=1 in signer for _ed25519_key_to_nacl); 9 contract tests green |
| 5 | "What will I be signing?" preview renders for all 8 signed-action types (EC5, DID-07) | VERIFIED | test_signing_preview.py parametrized over GOVERNANCE_ACTIONS (8); test_attested_signature_shape.py parametrized over same 8; both green |
| 6 | bind() verifies signature.did == did AND signature.over_content_hash matches JCS hash of proof payload (CR-01 / SEC-06 / F7) | VERIFIED | binding.py lines 386-411: signature.did != did → InvalidProofSignature; SHA-256(_jcs_canonical_bytes(proof)) mismatch → InvalidProofSignature; 3 regression tests green (test_signature_did_mismatch_rejected, test_signature_hash_does_not_cover_proof_rejected, test_attacker_cannot_bind_victim_sub_with_own_did) |
| 7 | The locked DID stack (PyNaCl + jcs + atproto + dag-cbor + joserfc + authlib) is installed at exact STACK.md pins with rejection comment for didkit/pydid/python-jose/fastapi-users (DID-01) | VERIFIED | pyproject.toml contains all 6 exact pins; rejection comment present; `import nacl, jcs, atproto, dag_cbor, joserfc, authlib` exits 0 |
| 8 | AttestedSignature has extra=forbid + signing_key_id + did_doc_snapshot_at + verified + reserved cosigners[] + SignedAction Literal (DID-02, D-13) | VERIFIED | envelope.py: ConfigDict(extra="forbid"); all 4 new fields present with correct defaults; SignedAction Literal has 12 members (8 governance + 4 PRD-vocab); bogus field and invalid action both raise ValidationError |
| 9 | canonical_content_hash uses RFC-8785 JCS with NFC + datetime pin + None-keep recipe; exclusion set unchanged (DID-03, D-12) | VERIFIED | content_edit.py imports jcs and unicodedata; _jcs_canonical_bytes + _normalize_for_jcs + _canonicalize_datetime helpers present; _HASH_EXCLUDED_FIELDS unchanged; 50 golden fixtures pass cross-impl check |
| 10 | The `folio-insights did` CLI subgroup (generate/bind/sign/verify/preview) is wired into the root CLI (DID-05 CLI portion) | VERIFIED | cli.py line 638-640: `from folio_insights.identity.cli import did_group as _did_group; cli.add_command(_did_group)`; CliRunner invoke of `did --help` exits 0; all 5 subcommands present |
| 11 | Playwright OAuth→DID binding covers all 3 paths (EC1 / DID-05 web clause) | DEFERRED | CONTEXT.md D-02 explicitly defers to post-Phase-14 web phase; not a scope failure |

**Score:** 10/11 truths verified (1 deferred by documented scope decision)

### Deferred Items

Items not yet met but explicitly addressed in a later milestone phase.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Playwright OAuth→DID binding covers all 3 binding paths | Post-Phase-14 web phase | CONTEXT.md D-02: "Playwright OAuth→DID binding across 3 paths + styled preview screenshot test → post-Phase-14 web phase." The CLI backend contract ships now; the web surface defers with the design system. |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/folio_insights/shards/envelope.py` | Real 6.1 AttestedSignature (extra=forbid, signing_key_id, did_doc_snapshot_at, verified, cosigners[], action Literal) | VERIFIED | All fields present; SignedAction Literal has 12 members; dep-leak guard green (no crypto import) |
| `src/folio_insights/revision/content_edit.py` | JCS canonical_content_hash with NFC + datetime + None pre-normalization | VERIFIED | Imports jcs and unicodedata; jcs.canonicalize called via _jcs_canonical_bytes; _HASH_EXCLUDED_FIELDS unchanged |
| `src/folio_insights/identity/__init__.py` | identity package exports (sign_attestation, verify_attestation, resolve_did, DidDocCache, etc.) | VERIFIED | All required symbols exported; did_group dropped from __init__ (CR-04 fix) |
| `src/folio_insights/identity/keys.py` | Client-side local ed25519 keystore (0600/0700, did:key round-trip) | VERIFIED | generate_keypair, load_signing_key, did_key_from_public, public_key_from_did_key all present; 0o600/0o700 enforcement confirmed |
| `src/folio_insights/identity/cache.py` | DidDocCache Protocol + InMemoryDidDocCache keyed by (did, datetime) | VERIFIED | @runtime_checkable Protocol with async get/put; InMemoryDidDocCache dict-backed; DidDocSnapshot Pydantic model |
| `src/folio_insights/identity/resolver.py` | 3-method resolver with did:key/web/plc branches + SSRF guards + size limit | VERIFIED | did:web branch with _MAX_DID_WEB_BYTES=1MiB cap (CR-03); localhost/link-local SSRF blocklist (WR-05); CR-02: historical at raises for default plc resolver |
| `src/folio_insights/identity/signer.py` | Real ed25519 sign_attestation with signing-time key capture | VERIFIED | PyNaCl SigningKey; populates signing_key_id + did_doc_snapshot_at; verified=None |
| `src/folio_insights/identity/verifier.py` | verify_attestation resolving signing-time key via DidDocCache (WR-06 strict cache path) | VERIFIED | WR-06: did:web/did:plc with did_doc_snapshot_at → cache-only; no live re-fetch on miss; returns False (fail-closed) |
| `src/folio_insights/identity/binding.py` | BindingRecord + ProofPayload + NonceStore + bind() with F3/F7/SEC-06 rules + CR-01 takeover defense | VERIFIED | All typed errors present; CR-01 gate (signature.did == did AND hash match) before verify_attestation; WR-01 gate ordering (timestamp/endpoint before nonce consume) |
| `src/folio_insights/identity/preview.py` | build_signing_preview for all 8 governance action types (EC5) | VERIFIED | GOVERNANCE_ACTIONS tuple has 8 entries; _RENDERERS covers all 12 SignedAction members; canonical_content_hash called |
| `src/folio_insights/identity/cli.py` | did Click subgroup: generate/bind/sign/verify/preview | VERIFIED | @click.group(name="did"); all 5 subcommands present; WR-07: verify refuses network without --allow-network or --did-doc |
| `src/folio_insights/identity/_b64.py` | Shared base64url helpers (WR-09 DRY fix) | VERIFIED | Module exists; signer.py and verifier.py both import from _b64 |
| `src/folio_insights/cli.py` | did subgroup wired into root CLI | VERIFIED | cli.add_command(_did_group) at module bottom |
| `tests/identity/test_canonical_jcs_properties.py` | 1000-shuffled-order JCS property test (EC2) | VERIFIED | @given(max_examples=1000); NFD/NFC invariance; datetime stability; exclusion-set guard |
| `tests/identity/test_jcs_golden.py` | Cross-impl golden test vs 50 cyberphone fixtures (F4) | VERIFIED | 50 fixture files present; parametrized test; fixture-count regression guard |
| `tests/identity/test_signature_survives_key_rotation.py` | EC3 rotation-survival (did:key + did:web) | VERIFIED | 2 tests; did:web rotation: sign with A, swap to B, historical verify via cache still passes |
| `tests/identity/test_no_server_keys_contract.py` | EC4 no-server-key AST contract test | VERIFIED | ast.walk over identity/*.py; allowance=1 for signer; 9 cases green |
| `tests/identity/test_binding_proof.py` | F3/F7/SEC-06 binding proof tests (incl. CR-01 regressions) | VERIFIED | 18 test functions; nonce replay, timestamp skew, endpoint mismatch, email sub, subject change, idempotency, CR-01 takeover scenario |
| `tests/identity/test_signing_preview.py` | EC5 preview for all 8 governance actions | VERIFIED | 7 test functions; parametrized over GOVERNANCE_ACTIONS; content_hash parity with signer |
| `tests/identity/test_attested_signature_shape.py` | Per-action AttestedSignature shape (DID-02) | VERIFIED | Parametrized over 8 governance actions; non-empty signature + signing_key_id + over_content_hash + verified=None |
| `tests/identity/test_sign_verify_methods.py` | Per-method sign/verify (did:key, did:web, did:plc) | VERIFIED | Parametrized over 3 DID methods; round-trip True; tampered False; signing_key_id populated |
| `tests/identity/test_did_cli.py` | did CLI tests via CliRunner | VERIFIED | 9 tests; did --help; generate; preview; sign→verify round-trip; sign-abort on decline (exit 2) |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `src/folio_insights/cli.py` | did subgroup | `cli.add_command(_did_group)` | WIRED | Lines 638-640 confirmed |
| `src/folio_insights/identity/binding.py` | CR-01 replay defense | `signature.did != did` check + SHA-256(_jcs_canonical_bytes(proof)) hash comparison | WIRED | Lines 386-411; both gates before verify_attestation |
| `src/folio_insights/identity/binding.py` | WR-01 gate ordering | timestamp/endpoint before nonce consume | WIRED | Step 3 (timestamp) → step 4 (endpoint) → step 5 (nonce consume); WR-01 comment in code |
| `src/folio_insights/identity/verifier.py` | signing-time DID doc | DidDocCache.get((did, signed_at)) — strict cache-only for did:web/did:plc | WIRED | WR-06: lines 113-123; no fallback to live http on cache miss for historical signatures |
| `src/folio_insights/revision/content_edit.py` | real ed25519 signing | `sign_attestation(signing_key=...)` delegates to `identity.signer.sign_attestation` via lazy import | WIRED | Lines 378-387; lazy import dodges identity↔revision cycle |
| `src/folio_insights/identity/signer.py` | PyNaCl ed25519 | SigningKey(raw_seed).sign(content_hash.encode("utf-8")).signature | WIRED | Line 96 in signer.py; base64url-no-pad encoded |
| `src/folio_insights/revision/content_edit.py` | RFC-8785 JCS | jcs.canonicalize via _jcs_canonical_bytes with NFC + datetime pre-norm | WIRED | canonical_content_hash calls _jcs_canonical_bytes which calls jcs.canonicalize |
| `src/folio_insights/identity/resolver.py` | CR-02 plc historical at guard | `if at is not None: raise UnresolvableDidError(...)` in _default_plc_resolve | WIRED | Lines 158-169; historical at refuses silently returning current doc |
| `src/folio_insights/identity/resolver.py` | CR-03 did:web size cap | `_MAX_DID_WEB_BYTES = 1 MiB`; streaming aiter_bytes with abort | WIRED | follow_redirects=False, verify=True, 1 MiB streaming cap |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `signer.sign_attestation` | `sig_bytes` (ed25519 signature) | `nacl_key.sign(content_hash.encode("utf-8")).signature` | Yes — PyNaCl libsodium ed25519 signing; non-empty 64-byte signature | FLOWING |
| `canonical_content_hash` | `payload` hash | `jcs.canonicalize(_normalize_for_jcs(model_dump(...)))` | Yes — real JCS canonicalization + SHA-256; 64-char hex output | FLOWING |
| `bind()` | `BindingRecord` | proof signature verified + nonce consumed + binding_store populated | Yes — typed error on every failure path; BindingRecord only written on full success | FLOWING |
| `build_signing_preview` | `content_hash` | `canonical_content_hash(shard)` | Yes — same function the signer signs over; parity asserted in test | FLOWING |
| `verify_attestation` | boolean result | `VerifyKey(raw_pub).verify(verify_hash.encode("utf-8"), sig_bytes)` | Yes — PyNaCl VerifyKey; returns False on BadSignatureError (never raises) | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| EC1: pytest tests/identity/ green | `uv run pytest tests/identity -q` | 176 passed | PASS |
| EC2: 1000-shuffle JCS order-independence | `uv run pytest tests/identity/test_canonical_jcs_properties.py -q` | 66 passed in 1.52s | PASS |
| EC3: rotation survival | `uv run pytest tests/identity/test_signature_survives_key_rotation.py -q` | 2 passed | PASS |
| EC4: no server-side keys | `uv run pytest tests/identity/test_no_server_keys_contract.py -q` | 9 passed | PASS |
| EC5: 8-action preview | `uv run pytest tests/identity/test_signing_preview.py -q` | 17 passed (includes parametrize) | PASS |
| CR-01 takeover defense | `uv run pytest tests/identity/test_binding_proof.py -q` | 18 passed | PASS |
| DID stack imports | `uv run python -c "import nacl, jcs, atproto, dag_cbor, joserfc, authlib"` | exits 0 | PASS |
| did CLI wired | `uv run python -c "from click.testing import CliRunner; from folio_insights.cli import cli; r=CliRunner().invoke(cli,['did','--help']); assert r.exit_code==0 and 'bind' in r.output"` | exits 0; all 5 subcommands present | PASS |
| Full suite 394-passing baseline | `uv run pytest tests/identity tests/shards tests/revision -q` | 394 passed, 1 pre-existing warning | PASS |
| Dep-leak guard | `uv run pytest tests/shards/test_dep_leak_guard.py -x` | 5 passed | PASS |
| AttestedSignature extra=forbid | `uv run python -c "from folio_insights.shards.envelope import AttestedSignature; AttestedSignature(bogus=1)"` | raises ValidationError | PASS |
| action Literal enforcement | `uv run python -c "from folio_insights.shards.envelope import AttestedSignature; AttestedSignature(action='not_a_real_action')"` | raises ValidationError | PASS |

---

### Probe Execution

Step 7c: SKIPPED — no probe scripts declared in PLAN files and no `scripts/*/tests/probe-*.sh` found for this phase. Verification covered by behavioral spot-checks above.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| DID-01 | Plans 01-02 | did:key + did:web + did:plc via PyNaCl/jcs/atproto/dag-cbor/joserfc/authlib; explicit rejection of didkit/pydid/python-jose/fastapi-users | SATISFIED | 6 exact-pinned deps in pyproject.toml; rejection comment; import check passes; all 3 DID methods tested |
| DID-02 | Plans 01-03 | Every write action produces AttestedSignature over canonical content hash | SATISFIED | SignedAction Literal with 12 members; test_attested_signature_shape.py parametrized over all 8 governance actions; sign_attestation produces non-empty signatures |
| DID-03 | Plan 01 | canonical_content_hash via jcs.canonicalize(model_dump(exclude=...)); order-independent | SATISFIED | RFC-8785 JCS in canonical_content_hash; 1000-shuffle property test + 50-input golden test both green |
| DID-04 | Plan 02 | Every AttestedSignature records signing_key_id and did_doc_snapshot_at | SATISFIED | signer.py populates both fields; verifier resolves signing-time key via (did, did_doc_snapshot_at) cache lookup |
| DID-05 | Plan 03 | DID-binding onboarding flow — backend/CLI contract delivered | PARTIAL (deferred) | CLI `did bind` locks SEC-06 contract; Playwright web flow deferred per CONTEXT.md D-02 to post-Phase-14 (no later ROADMAP phase formally assigned) |
| DID-06 | Plans 02-03 | Server-side signing key storage forbidden; all signing client-side | SATISFIED | test_no_server_keys_contract.py: AST scan confirms no private_bytes() outside keys.py; load_signing_key refuses world-readable keys (WR-02) |
| DID-07 | Plans 02-03 | "What will I be signing?" preview for all 8 signed-action types | SATISFIED | build_signing_preview handles all 12 SignedAction members; EC5 test parametrized over 8 governance actions; content_hash parity with signer verified |
| DID-08 | Deferred | Hardware-key signing (P2, Phase 6.2) | DEFERRED (P2) | cosigners[] reserved in AttestedSignature; explicitly out of Phase 6.1 scope |
| DID-09 | Deferred | Multi-sig attestations (P2, Phase 6.3) | DEFERRED (P2) | cosigners[] reserved in AttestedSignature; explicitly out of Phase 6.1 scope |
| SEC-05 | Plan 02 | DID key rotation: historical signatures verify after rotation; signing-time key captured | SATISFIED | test_signature_survives_key_rotation.py green; WR-06: verifier strict cache-only path for historical did:web/did:plc; EC3 gate closed |
| SEC-06 | Plan 03 | GitHub-username-takeover defense: sub-bound, nonce, domain proof; F7 squatter defense | SATISFIED | bind() enforces: sub-only (WR-03 username heuristic), nonce+timestamp+endpoint (F3), subject-change, idempotency, did:web domain proof; CR-01 signature.did==did + hash-over-proof gate |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/folio_insights/identity/preview.py` | 281 | "placeholder" in docstring | Info | Documentation text only — describes fallback renderer behavior when `change` dict is None; not a stub |
| `src/folio_insights/revision/content_edit.py` | 369-374 | `sign_attestation(signing_key=None)` returns `signature=""` | Info | Intentional T-06-04 ACCEPTED pattern — Phase-5 unsigned audit stub; documented in Plan 01 threat model; clearly bounded by the `signing_key is None` branch check |

No TBD, FIXME, or XXX markers found in any phase-6-modified file. No unintentional stubs detected.

---

### Human Verification Required

#### 1. Terminal CLI UX — `did generate` and `did preview`

**Test:** Run `folio-insights did generate --method=key` (creates or reuses the local keystore) and `folio-insights did preview --action=promote --shard-json=<path to a minimal shard JSON>` in a real terminal session.
**Expected:** `did generate` prints a `did:key:z…` string. `did preview` prints a 64-character hexadecimal content hash and a PROMOTE human-readable line referencing the shard IRI and epistemic_status.
**Why human:** CliRunner tests confirm exit code 0 and text presence, but cannot verify terminal formatting (Rich rendering, alignment, color) or whether the UX is clear to an operator preparing to sign a governance action.

#### 2. Root CLI help surface

**Test:** Run `folio-insights --help` and `folio-insights did --help` in a real terminal.
**Expected:** `folio-insights --help` lists the `did` subgroup alongside bench/polysemy; `folio-insights did --help` lists all five subcommands (generate, bind, sign, verify, preview) with their one-line descriptions.
**Why human:** Automated CliRunner tests confirm this; human eyes should confirm the help text is readable and non-cryptic for an operator unfamiliar with the DID substrate.

---

### Gaps Summary

No actionable gaps. The one partial requirement (DID-05 Playwright web OAuth binding) is a documented scope deferral per CONTEXT.md D-02, with the backend/CLI contract fully delivered in this phase. The deferred web surface has no later ROADMAP phase explicitly assigned — this is an **INFO-level tracking concern** but not a blocker for Phase 6 completion as scoped.

The 13-finding code review (CR-01..CR-04, WR-01..WR-09, IN-01..IN-05) was completed and all critical + warning findings were fixed before this verification. The 5 INFO findings (IN-01..IN-05) remain as follow-up items in `06-REVIEW.md`; none affect correctness.

---

_Verified: 2026-05-29T03:30:00Z_
_Verifier: Claude (gsd-verifier)_
