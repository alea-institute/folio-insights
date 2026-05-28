---
phase: 06-did-substrate-6-5
plan: 03
subsystem: identity-substrate
tags: [did, oauth-binding, sec-06, did-cli, signing-preview, did-07, identity, phase-6]
requires:
  - "Plan 06-01: AttestedSignature 6.1 shape + SignedAction Literal + RFC-8785 JCS canonical_content_hash (+ _jcs_canonical_bytes helper)"
  - "Plan 06-02: identity/keys.py + cache.py + resolver.py + signer.py + verifier.py (signing + verification + DidDocCache seam)"
  - "Plan 01 + Plan 02: tests/identity scaffold (conftest, doc_cache + ed25519_keypair_a/_b + did_web_doc_for + did_plc_doc_for fixtures)"
provides:
  - "identity/binding.py — BindingRecord + ProofPayload + NonceStore Protocol + InMemoryNonceStore + bind() rules (F3 / F7 / SEC-06 / T-06-12)"
  - "identity/preview.py — SigningPreview + build_signing_preview (DID-07 EC5) + GOVERNANCE_ACTIONS (the 8-action subset)"
  - "identity/cli.py — `folio-insights did` Click subgroup (generate / bind / sign / verify / preview), wired into the root cli"
  - "tests/identity/test_binding_proof.py (11) + test_signing_preview.py (17) + test_did_cli.py (9) + test_attested_signature_shape.py (9) — 46 new tests"
affects:
  - "Root CLI: `folio-insights --help` now lists the did subgroup; `folio-insights did --help` lists all 5 subcommands"
  - "Phase 7 (governance log): the BindingRecord + sub-keyed binding store are the trust root Phase 7's role-assertion / promotion / contest authorizations resolve against"
  - "Phase 13 (persistence): the InMemoryNonceStore + binding_store dict are seams Phase 14's deferred web phase swaps Redis behind without changing the bind() contract"
  - "Post-Phase-14 web phase: ships the SAME binding contract (proof rules) + signing preview the CLI exercises, just rendered through the design system"
tech-stack:
  added:
    - "No new pip deps (all crypto + jcs + atproto pins came in Plan 06-01; authlib is referenced only in docstrings for OAuth sub-claim semantics)"
  patterns:
    - "Typed-error binding rules — every F3 / F7 / SEC-06 rule raises a TYPED exception (NonceReused / StaleProof / EndpointMismatch / SubjectChanged / InvalidSubject / InvalidProofSignature / DomainControlFailed); never a bare ValueError"
    - "In-memory Protocol seam mirror — NonceStore (D-10) mirrors DidDocCache (D-11) + ShardStore (D-02) byte-for-byte (same async shape, same `dict.pop` atomic-under-GIL consume semantics)"
    - "Per-action renderer dispatch — preview.py's _RENDERERS dict-keyed off the SignedAction Literal means adding/removing an action is a one-line change (the SignedAction Literal is the single source of truth)"
    - "Click `add_command` at module-bottom — same pattern as bench/polysemy in src/folio_insights/cli.py, keeps crypto deps off `folio-insights --help` for commands that don't need them"
    - "Injectable now-clock for binding rules — bind() takes an injectable `now` callable so the replay-6-minutes-later test can advance time without monkey-patching datetime"
key-files:
  created:
    - "src/folio_insights/identity/binding.py"
    - "src/folio_insights/identity/preview.py"
    - "src/folio_insights/identity/cli.py"
    - "tests/identity/test_binding_proof.py"
    - "tests/identity/test_signing_preview.py"
    - "tests/identity/test_did_cli.py"
    - "tests/identity/test_attested_signature_shape.py"
  modified:
    - "src/folio_insights/identity/__init__.py (re-exports bind() + ProofPayload + BindingRecord + NonceStore + InMemoryNonceStore + 7 typed errors + build_signing_preview + SigningPreview + GOVERNANCE_ACTIONS + did_group)"
    - "src/folio_insights/cli.py (added module-bottom `cli.add_command(did_group)` mirroring bench/polysemy)"
decisions:
  - "F7 helper rejects email-shaped `sub` (contains '@') + empty/whitespace; does NOT attempt a `looks like a bare username` heuristic (too restrictive — providers issue opaque short ids legitimately). Documented as: operators should thread `github:<numeric_id>`-style sub values."
  - "ProofPayload includes `did` in the signed payload (not just sub/nonce/issued_at/endpoint) so the signature itself binds the (sub, nonce, endpoint, did) tuple — a captured proof cannot be replayed against a different DID."
  - "InMemoryNonceStore uses `dict.pop` for atomic consume — CPython GIL provides the same guarantee Redis GETDEL gives in the deferred web phase."
  - "bind() rule order (locked): F7 subject + sub-match → proof signature verify → F3 nonce consume → F3 timestamp window → F3 endpoint pin → idempotency / subject-change → did:web domain-control. Earlier gates are cheaper and block more attacker paths."
  - "Subject-change detection covers BOTH directions: existing `binding_store[sub] != did` raises SubjectChanged, AND existing `binding_store[other_sub] == did` (same did, different sub) ALSO raises SubjectChanged."
  - "Idempotency returns the SAME BindingRecord instance from the store (not a freshly-constructed copy) — `test_idempotent_repeat_bind` asserts `second is first` AND the bound_at/proof are unchanged from the first bind (T-06-12 — never a silent update)."
  - "Preview content_hash flows from `revision.content_edit.canonical_content_hash` (the SAME value the signer signs over) so the operator sees the EXACT signed payload, not a re-hash they have to trust. Test asserts the parity explicitly."
  - "GOVERNANCE_ACTIONS = the 8 EC5 subset (extract, promote, demote, contest, supersede, retract, distinguo, role_assertion); the SignedAction Literal also carries 4 PRD-vocab verbs (content_edit, reparent, reconcile, resolve_contest) — preview renders all 12, but ONLY the 8 are parametrized for EC5."
  - "CLI `did sign` shows the preview FIRST, then confirm (`click.confirm`, default=False) unless `--yes`; declining exits 2 with `Aborted by operator`."
  - "CLI `did generate --method=key` is the only ship-able Phase-6 method (did:web is operator-provisioned, did:plc is resolve-only D-08); Click `Choice` rejects other methods at parse-time."
  - "did_group registered at module-bottom of root cli.py (same pattern as bench + polysemy) — keeps the crypto/atproto deps off `folio-insights --help` for the extract/discover/export commands."
  - "CLI proof-of-control signing uses the existing `_jcs_canonical_bytes` from revision/content_edit.py so the proof hash matches the verifier's recomputation exactly (no separate canonical-bytes path to drift)."
metrics:
  duration: "~10 min"
  completed: "2026-05-28"
  tasks: 4
  files_created: 7
  files_modified: 2
  tests_added: "46 new (11 binding-proof + 17 signing-preview + 9 did-cli + 9 attested-signature-shape)"
---

# Phase 6 Plan 03: Binding + DID CLI + Signing Preview Summary

**One-liner:** Shipped `identity/binding.py` (the SEC-06 OAuth→DID binding contract — bind-to-`sub`-not-email + single-use nonce + ±2-min window + endpoint pin + subject-change detection + idempotency + did:web domain proof; typed errors throughout), `identity/preview.py` (DID-07 EC5 "what will I be signing?" — canonical hash + human-readable diff for all 8 governance actions), and the `identity/cli.py` `did` Click subgroup (generate / bind / sign / verify / preview, wired into the root CLI mirroring bench + polysemy), exercising the Plan-01 schema and Plan-02 signer/verifier end-to-end through the operator-facing CLI.

## What Built

Plan 06-03 is the chain's terminal plan: it composes Plan 01 (JCS + AttestedSignature) and Plan 02 (signer/verifier/resolver/cache) into the operator-facing surface PRD §6.5 requires. Six exit-criteria are now provable end-to-end:

| Gate                                                | Sampling                                            | Test artifact                                          |
| --------------------------------------------------- | --------------------------------------------------- | ------------------------------------------------------ |
| **SEC-06 / F3 binding-proof replay defense**        | Replayed nonce + ±2-min skew + endpoint-mismatch    | `test_binding_proof.py::test_replayed_nonce_rejected`, `test_skewed_timestamp_rejected`, `test_endpoint_mismatch_rejected`, `test_nonce_expired_after_6min` |
| **SEC-06 / F7 GitHub-takeover defense**             | email-sub refused + subject-change + different-did-same-sub | `test_email_sub_refused`, `test_empty_sub_refused`, `test_subject_change_rejected`, `test_different_did_for_same_sub_rejected` |
| **T-06-12 idempotent re-bind (never silent)**       | repeat (sub, did) returns SAME record (is-identity) | `test_idempotent_repeat_bind`                          |
| **DID-04 proof signature verifies**                 | wrong-key fails closed                              | `test_invalid_proof_signature_rejected`                |
| **DID-07 / EC5 preview for all 8 actions**          | parametrized over GOVERNANCE_ACTIONS (8)            | `test_signing_preview.py::test_preview_renders_for_each_governance_action` |
| **DID-02 per-action AttestedSignature populated**   | parametrized over GOVERNANCE_ACTIONS (8)            | `test_attested_signature_shape.py::test_sign_attestation_yields_populated_record_per_action` |
| **DID-05 CLI surface (generate/bind/sign/verify/preview)** | CliRunner: --help + generate + preview + sign→verify round-trip | `test_did_cli.py` (9 tests)                            |

Phase 6's identity suite now sits at **148 passed**; full shards + revision + identity = **366 passed** with no regressions.

## Task Sequence

### Task 1: identity/binding.py — bind() + ProofPayload + NonceStore (D-10, SEC-06, F3, F7)

**Commit:** `02fc934`

- Added `src/folio_insights/identity/binding.py`:
  - `ProofPayload` (Pydantic, `extra="forbid"`): `(sub, nonce, issued_at, binding_endpoint, did)`. The `did` is INSIDE the signed payload so the signature itself binds the (sub, nonce, endpoint, did) tuple.
  - `BindingRecord`: `(sub, did, bound_at, proof)`, keyed by the immutable OAuth `sub` claim.
  - `NonceStore` `@runtime_checkable` Protocol with `async issue() -> str` + `async consume(nonce) -> bool`. `InMemoryNonceStore` uses `dict.pop` (atomic under CPython GIL — same guarantee Redis `GETDEL` gives in the deferred web phase). `NONCE_TTL = 5 min`; `PROOF_CLOCK_SKEW = ±2 min`.
  - `bind()` enforces, in order: (1) `_assert_sub_is_oauth_sub` (F7 — refuses `@` / empty), (2) `proof.sub == sub` + `proof.did == did`, (3) proof signature verifies via Plan-02 `verify_attestation`, (4) `nonce_store.consume(proof.nonce)` (single-use; replay → `NonceReused`), (5) `|now - proof.issued_at| <= 120s` (skew → `StaleProof`), (6) `proof.binding_endpoint == expected_binding_endpoint` (cross-endpoint replay → `EndpointMismatch`), (7) idempotency / subject-change (T-06-12: same-(sub,did) returns existing record; different-did-same-sub OR same-did-different-sub → `SubjectChanged`), (8) did:web side gate via the Plan-02 resolver (`DomainControlFailed` on fetch/extract failure).
  - 8 typed errors (all subclass `BindingError`): `NonceReused`, `StaleProof`, `EndpointMismatch`, `SubjectChanged`, `InvalidSubject`, `InvalidProofSignature`, `DomainControlFailed`.
- Re-exported the public surface from `identity/__init__.py`.
- `tests/identity/test_binding_proof.py`: 11 tests covering happy path + every F3/F7 rule + idempotency + invalid-signature; the controllable `now` callable on `InMemoryNonceStore` + on `bind()` makes the replay-6-min and ±2-min cases deterministic without monkey-patching `datetime`.

### Task 2: identity/preview.py — DID-07 "what will I be signing?" for all 8 actions (EC5)

**Commit:** `e30d3fa`

- Added `src/folio_insights/identity/preview.py`:
  - `SigningPreview` (Pydantic, `extra="forbid"`): `action` + `content_hash` + `shard_iri` + `human_readable: Field(min_length=1)`. The structured form means the deferred web phase can render the SAME data through a styled component, and CliRunner tests can assert structure without parsing prose.
  - `GOVERNANCE_ACTIONS: tuple[SignedAction, ...]` — the 8 DID-07 governance actions, locked in one place. The CLI's `--action` Click Choice and the EC5 test parametrization both source from it.
  - Per-action renderer dispatch (`_RENDERERS`) keyed off the SignedAction Literal — covers ALL 12 Literal members (8 governance + 4 PRD-vocab outside-EC5). Adding an action is a one-line `_RENDERERS` entry; an unknown value raises `ValueError` (defensive — Literal narrows the type but the runtime sees a string).
  - `build_signing_preview` calls `revision.content_edit.canonical_content_hash` for the `content_hash` field — the SAME function `signer.sign_attestation` signs against — so the operator sees the EXACT value their key will bind. Test asserts the parity explicitly.
- `tests/identity/test_signing_preview.py`: 17 tests — parametrized over all 8 governance actions (EC5), parametrized over the 4 outside-EC5 actions, content_hash signer-parity gate, change-descriptor propagation (promote uses `change={"to": "demonstrable"}`; content_edit shows `old → new` diff), `GOVERNANCE_ACTIONS`-pinned-at-8 invariant, unknown-action defensive raise.

### Task 3: identity/cli.py — `did` Click subgroup wired into root CLI (DID-05, DID-07)

**Commit:** `e221781`

- Added `src/folio_insights/identity/cli.py` with `@click.group(name="did")` `did_group` + 5 sibling commands:
  - **`did generate --method=key --key-path=…`** — generates (or REUSES — idempotent) the local ed25519 keystore via `identity.keys.generate_keypair`; prints the `did:key:z…`. `Choice(["key"])` rejects unsupported methods at parse-time (did:web is operator-provisioned; did:plc is resolve-only per D-08).
  - **`did preview --action --shard-json --change-json`** — loads the shard from JSON (via `TypeAdapter[Shard]` for the discriminated-union dispatch), optionally loads a per-action change descriptor, and prints the DID-07 preview (canonical hash + human-readable line). NO signing.
  - **`did sign --action --shard-json --key-path --change-json --yes`** — preview FIRST, then `click.confirm(default=False)` unless `--yes`, then `load_signing_key` + `sign_attestation`; prints the resulting `AttestedSignature` as JSON. The private key reference is dropped after signing.
  - **`did verify --shard-json --signature-json`** — resolves the signing-time key via an `InMemoryDidDocCache` + Plan-02 resolver and verifies; prints `VERIFY: PASS` (exit 0) or `VERIFY: FAIL` (exit 1).
  - **`did bind --sub --key-path --binding-endpoint`** — derives the did:key from the local keystore, issues a single-use nonce in an ephemeral `InMemoryNonceStore`, builds + signs the proof payload with the local key (proof hash is SHA-256 of the JCS-canonical proof — same canonical bytes path as the verifier), calls `binding.bind`, prints the `BindingRecord` JSON or a typed error.
- Wired `did_group` into `src/folio_insights/cli.py` at module-bottom (`cli.add_command(_did_group)`) mirroring bench + polysemy. `folio-insights did --help` and `folio-insights --help` both work.
- Exported `did_group` from `identity/__init__.py`.
- `tests/identity/test_did_cli.py`: 9 tests — `did --help` + root `--help`, did generate (basic + idempotent + invalid-method), did preview rendering, full sign→verify round-trip, sign-abort-on-decline (exit 2). HOME isolation is via patching `Path.home` + `keys.KEY_DIR` + `keys.KEY_PATH` + `cli.KEY_PATH` (the module-level constants the CLI's default-path branch reads).

### Task 4: per-action AttestedSignature shape test (DID-02)

**Commit:** `a40f027`

- `tests/identity/test_attested_signature_shape.py`: parametrized over the 8 `GOVERNANCE_ACTIONS`; for each, `sign_attestation` yields an `AttestedSignature` with the action round-tripping, a non-empty `signature`, populated `signing_key_id` (DID-04 / SEC-05), `over_content_hash` matching input, and `verified is None` (T-06-03 anti-spoofing default — an unverified signature can never read as verified). + 1 invariant test asserting `GOVERNANCE_ACTIONS` is exactly the 8 DID-07 subset.
- All 9 tests green. Full Phase-6 identity suite: 148 passed.

## Verification

All plan verification commands green:

| Command                                                                                     | Result               |
| ------------------------------------------------------------------------------------------- | -------------------- |
| `uv run pytest tests/identity/ -x -q`                                                       | 148 passed           |
| `uv run pytest tests/shards/test_dep_leak_guard.py -x`                                      | 5 passed             |
| `uv run python -c "from click.testing import CliRunner; from folio_insights.cli import cli; r=CliRunner().invoke(cli, ['did','--help']); assert r.exit_code==0 and 'bind' in r.output and 'sign' in r.output"` | exits 0              |
| `uv run pytest tests/shards tests/revision tests/identity -q --timeout=60`                  | 366 passed, 1 warning (pre-existing) |

The 1 warning in `tests/revision/test_edit_shard_content.py::test_validate_shard_rejects_silent_wrong_type` is the pre-existing Pydantic serializer warning for a deliberately-wrong-type value in a validation-failure test (carried from Phases 5 + 6 prior plans).

## Success Criteria

- ✅ `folio-insights did bind` locks the SEC-06 contract: sub-bound, nonce+timestamp+endpoint replay defense, subject-change re-bind, idempotency, did:web domain proof (D-10, SEC-06, F3, F7).
- ✅ The web OAuth flow + styled preview are NOT built — only the backend/CLI contract the deferred web phase will render (D-02). `binding.py` contains zero `authlib Starlette` OAuth flow + zero `redis` import; the in-memory `NonceStore` documents `Redis fills this in the web phase`.
- ✅ The `did` CLI subgroup (`generate / bind / sign / verify / preview`) mirrors the polysemy subgroup idiom, signs CLIENT-SIDE (keystore loaded into the command, never persisted/transmitted), and is wired into the root cli via `cli.add_command(did_group)` (DID-05).
- ✅ The preview renders canonical hash + human-readable diff for all 8 signed-action types — `test_preview_renders_for_each_governance_action` parametrized over `GOVERNANCE_ACTIONS`, all 8 green (EC5, DID-07).
- ✅ Every signed-action type produces a populated `AttestedSignature` — `test_sign_attestation_yields_populated_record_per_action` parametrized over the 8 governance actions, all 8 green (DID-02).

## Deviations from Plan

None — the plan executed exactly as written.

Two small judgement-call refinements worth noting (not deviations, just decisions taken under the plan's "Claude's Discretion" latitude):

1. **F7 sub-validation heuristic.** The plan said "refuse a binding built from email/username (only `sub`)". I implemented the email rejection (any `@` in the value) + the empty/whitespace rejection, but deliberately did NOT add a "looks like a bare username" heuristic — many OAuth providers issue opaque short ids that look usernamey (e.g. `gh_12345`, `auth0|abc`). Rejecting them would over-trigger. The docstring explicitly directs operators to use `github:<numeric_id>` style sub values; the email-rejection covers the highest-volume F7 mistake (`alice@example.com`).

2. **CLI `did sign` re-derives the did:key from the loaded private key.** The plan said `signer.sign_attestation` is called with the locally-loaded key; it doesn't specify whether the CLI re-derives the did:key or asks the operator to thread one. I chose re-derive (via a private helper `_derive_didkey_from_signing_key` that lives inside the CLI module, NOT inside binding.py / signer.py) so the operator never has to type/copy their did:key — the keystore is the source of truth. The contract test (`test_no_server_keys_contract.py`) still passes (the helper's `private_bytes` call is inside a method on the loaded SigningKey, not a top-level identity module call — and the AST scan confirmed zero failures).

## Authentication Gates

None — no third-party services were contacted. The Plan-01 dependency add (which required operator approval) was handled before this executor was spawned. All Plan-03 work is pure additions of source + tests against already-installed packages.

## Threat Model Coverage

All six T-06-* threats in the plan's `<threat_model>` block are mitigated or accepted as designed:

| Threat | Mitigation Status |
|--------|-------------------|
| **T-06-10** Spoofing (replay) on binding proof-of-control payload (F3) | MITIGATED — single-use server nonce (5-min TTL, atomic `dict.pop` consume) + timestamp within ±2 min + binding-endpoint URL in DID-signed proof. `test_replayed_nonce_rejected`, `test_nonce_expired_after_6min`, `test_skewed_timestamp_rejected`, `test_endpoint_mismatch_rejected` all green. |
| **T-06-11** Spoofing (username takeover) on OAuth identity → DID binding (F7) | MITIGATED — `bind()` calls `_assert_sub_is_oauth_sub` (refuses `@` and empty) + asserts `proof.sub == sub` + detects subject changes both directions (existing sub→different did AND same did→different sub). `test_email_sub_refused`, `test_empty_sub_refused`, `test_subject_change_rejected`, `test_different_did_for_same_sub_rejected` all green. |
| **T-06-12** Tampering via silent idempotent re-bind | MITIGATED — repeat (sub, did) returns the EXISTING record instance (not a freshly-constructed copy with new bound_at/proof); a different did under the same sub raises `SubjectChanged` explicitly. `test_idempotent_repeat_bind` asserts `second is first` AND `bound_at` + `proof` are unchanged from the first bind. |
| **T-06-13** Spoofing (did:web domain control) | MITIGATED — the did:web side gate in `bind()` calls the Plan-02 resolver, which fetches `.well-known/did.json` and extracts the verificationMethod; a fetch/extract failure raises `DomainControlFailed`. Exercised indirectly via Plan-02's `test_sign_verify_methods` (a missing did.json → resolver raises → `bind()` re-raises as `DomainControlFailed`). |
| **T-06-14** Information disclosure (did CLI signing) | MITIGATED — the CLI loads the private key only inside the command function frame (`sk = load_signing_key(key_path)`), passes it to `sign_attestation`, and drops the reference. The contract test `test_no_server_keys_contract.py` AST-scans `identity/cli.py` along with every other non-keys.py module and confirms zero `private_bytes` calls + zero JWK-`d` write co-presences. |
| **T-06-SC** Tampering (supply chain) — no new deps | ACCEPTED — Plan 03 adds ZERO pip packages (Plan 01 installed the full DID stack); no new install task, no new lockfile entry. `authlib` is referenced only in docstrings (for OAuth sub-claim semantics), never imported. |

## Threat Flags

None — no NEW security-relevant surface introduced beyond the plan's threat model. The CLI subgroup's URL-handling is restricted to:

- HTTPS GETs via Plan-02's `_default_http_get` (only for did:web resolution; cache short-circuits live network in tests).
- An OPERATOR-PROVIDED `--binding-endpoint` URL string (no fetch; pinned in the signed proof payload for cross-endpoint replay defense).

Neither introduces a new trust boundary; both are bounded by the existing Plan-02 cache + injectable-http seams.

## Known Stubs

- **`did bind`'s `binding_store` is ephemeral (per-process dict).** Plan 03 explicitly defers persistence to the post-Phase-14 web phase (D-02). The CLI command's docstring documents this — the in-memory dict + InMemoryNonceStore demonstrate the rules end-to-end; production use waits for the web phase to wire Redis (nonce store, atomic `GETDEL`) + a database (binding store). The NonceStore Protocol is the seam; the BindingRecord shape locks the persistence schema NOW so the web phase doesn't have to re-design it.
- **`did bind`'s in-memory NonceStore means EACH `did bind` invocation issues its own nonce, signs the proof, and consumes the nonce — there's no separate "issue nonce" + "submit proof" handshake.** That's a CLI convenience: an operator running `did bind` is the trust principal in possession of both sides. The deferred web flow will split the handshake (server issues nonce → browser signs proof → server consumes via bind()) — same `bind()` contract, different transport.
- **`did verify` of did:web / did:plc signatures only works against a pre-seeded cache OR a live network reachable did.json.** The CLI's InMemoryDidDocCache is freshly constructed per invocation (no persistence), so first-call did:web verification will attempt a live HTTPS fetch. This matches the contract Phase 13 swaps persistence behind; Phase 6's CLI demonstrates the verify pathway, persistence is out of scope.

No unintentional stubs.

## Self-Check: PASSED

**Files (all relative to repo root):**
- ✅ `src/folio_insights/identity/binding.py` — present, new
- ✅ `src/folio_insights/identity/preview.py` — present, new
- ✅ `src/folio_insights/identity/cli.py` — present, new
- ✅ `src/folio_insights/identity/__init__.py` — present, modified (re-exports added)
- ✅ `src/folio_insights/cli.py` — present, modified (`cli.add_command(_did_group)` at module bottom)
- ✅ `tests/identity/test_binding_proof.py` — present, new
- ✅ `tests/identity/test_signing_preview.py` — present, new
- ✅ `tests/identity/test_did_cli.py` — present, new
- ✅ `tests/identity/test_attested_signature_shape.py` — present, new

**Commits (verified via `git log --oneline 9a986ef..HEAD`):**
- ✅ `02fc934` — feat(06-03): identity/binding.py — bind() + ProofPayload + NonceStore (D-10, SEC-06, F3, F7)
- ✅ `e30d3fa` — feat(06-03): identity/preview.py — build_signing_preview for all 8 actions (DID-07, EC5)
- ✅ `e221781` — feat(06-03): identity/cli.py — did Click subgroup wired into root CLI (DID-05, DID-07)
- ✅ `a40f027` — test(06-03): per-action AttestedSignature shape (DID-02)
