---
phase: 06-did-substrate-6-5
fixed_at: 2026-05-29T02:30:00Z
review_path: .planning/phases/06-did-substrate-6-5/06-REVIEW.md
iteration: 1
findings_in_scope: 13
fixed: 13
skipped: 0
status: all_fixed
---

# Phase 6: Code Review Fix Report

**Fixed at:** 2026-05-29T02:30:00Z
**Source review:** `.planning/phases/06-did-substrate-6-5/06-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 13 (4 critical, 9 warning)
- Fixed: 13
- Skipped: 0
- Test result: `uv run pytest tests/identity tests/shards tests/revision -q` → 394 passed (up from 366 baseline; 28 new regression tests added).
- Info findings IN-01..IN-05 deliberately out of scope per `--fix` scope (critical_warning).

## Fixed Issues

### CR-01: bind() does not verify the proof signature is bound to THIS proof payload — F7 takeover bypass

**Files modified:** `src/folio_insights/identity/binding.py`, `tests/identity/test_binding_proof.py`
**Commit:** 7541cd0
**Applied fix:** Added two gates inside `bind()` BEFORE the existing `verify_attestation` call:

  - **(a) Signer DID equality** — `signature.did != did` raises `InvalidProofSignature`. The signature has to attest to the bound DID, not just any DID the attacker controls.
  - **(b) Signed hash equality** — recomputes `SHA-256(_jcs_canonical_bytes(proof.model_dump(mode="json")))` and rejects if `signature.over_content_hash` does not match. Closes the bypass where an attacker signs an unrelated hash with their own key.

Added three regression tests covering the gaps:
  - `test_signature_did_mismatch_rejected`
  - `test_signature_hash_does_not_cover_proof_rejected`
  - `test_attacker_cannot_bind_victim_sub_with_own_did` (the full F7 takeover scenario from the review)

### CR-02: Default did:plc resolver silently ignores `at` — Pitfall F2 silent-wrong-key

**Files modified:** `src/folio_insights/identity/resolver.py`, `tests/identity/test_did_doc_cache.py`
**Commit:** 5e3b7b2
**Applied fix:** `_default_plc_resolve` now raises `UnresolvableDidError` when called with `at != None`. The default implementation cannot walk the PLC op log to pin historical state (D-08: resolve/verify only, no genesis/rotation writes), so returning the current doc against a historical `signed_at` is exactly the F2 silent-wrong-key failure mode. Callers MUST inject a custom `plc_resolver` for historical lookups.

Added two regression tests: `test_default_plc_resolver_refuses_historical_at` and `test_default_plc_resolver_used_when_at_is_none` (boundary — current-head resolution still flows via monkeypatched `atproto.IdResolver`).

### CR-03: `_default_http_get` has no response-size limit — did:web DoS / memory exhaustion

**Files modified:** `src/folio_insights/identity/resolver.py`, `tests/identity/test_did_doc_cache.py`
**Commit:** 36a5bc7
**Applied fix:** Replaced the single-shot `await client.get(url); resp.json()` with `async with client.stream("GET", url)` and chunk-counting:

  - Enforces `url.startswith("https://")` (defense in depth — `_did_web_url` already does, but defends future code paths or custom http callables).
  - `follow_redirects=False`, `verify=True` explicit.
  - Streams `aiter_bytes()`, aborts past `_MAX_DID_WEB_BYTES = 1 MiB` with `UnresolvableDidError`.

Added three regression tests: `test_did_web_non_https_url_refused`, `test_did_web_response_too_large_rejected`, `test_did_web_response_within_cap_succeeds`.

### CR-04: `cli.py` and `__init__.py` couple every identity import to `click`

**Files modified:** `src/folio_insights/identity/__init__.py`
**Commit:** 8043969
**Applied fix:** Removed `from folio_insights.identity.cli import did_group` and the `did_group` entry from `__all__`. The root CLI at `src/folio_insights/cli.py` already imports `did_group` directly (`from folio_insights.identity.cli import did_group as _did_group; cli.add_command(_did_group)`) — registration is unchanged from the user's perspective.

Verified by `python -c "from folio_insights.identity import sign_attestation"`: `identity.cli` is no longer in `sys.modules` after importing the signer. (`click` itself stays in `sys.modules` because other top-level package imports — root CLI, polysemy CLI — pull it in, but it is no longer reachable through the identity hot path.)

### WR-01: `bind()` consumes the nonce BEFORE timestamp / endpoint checks — DoS amplification

**Files modified:** `src/folio_insights/identity/binding.py`, `tests/identity/test_binding_proof.py`
**Commit:** fdac13b
**Applied fix:** Reordered the gates inside `bind()` so the pure-compare gates (timestamp F3 skew window, endpoint pin) run BEFORE the irreversible nonce consume. Updated the docstring's "IN ORDER" list to reflect the new step numbering. Added two regression tests: `test_stale_proof_does_not_consume_nonce` and `test_endpoint_mismatch_does_not_consume_nonce` — each asserts the nonce remains consumable after the bind fails.

### WR-02: `load_signing_key` POSIX-mode check is incorrect on Windows

**Files modified:** `src/folio_insights/identity/keys.py`, `tests/identity/test_keys_load_signing_key.py`
**Commit:** f44ad8d
**Applied fix:** Branched the POSIX bit-mask check on `os.name`:
  - `posix` → existing behavior (refuse 0o644/0o666/etc.).
  - `nt` → emit `UserWarning` directing the operator to rely on NTFS ACLs.
  - Other → silent skip.

Added a new test module `tests/identity/test_keys_load_signing_key.py` with three tests: POSIX 0o600 loads, POSIX 0o644 rejected (skipped on non-POSIX), simulated Windows (monkeypatched `os.name == "nt"`) emits warning and loads.

### WR-03: F7 subject check accepts plain usernames — weak F7 surface

**Files modified:** `src/folio_insights/identity/binding.py`, `tests/identity/test_binding_proof.py`
**Commit:** b74874f
**Applied fix:** Added a `_SUSPECT_USERNAME` regex (`^[a-zA-Z][a-zA-Z0-9_-]{0,14}$`) and reject when it matches AND the value contains neither `:` (provider-prefix marker) nor `|` (auth0 style). Accepts numeric-only ids (which don't start with a letter), provider-prefixed ids, and opaque ≥16-char strings.

Added two tests: `test_bare_username_sub_refused` (alice → InvalidSubject) and `test_provider_prefixed_numeric_sub_accepted` (`github:12345` boundary still binds).

### WR-04: `_default_plc_resolve` blocks the event loop with a sync call

**Files modified:** `src/folio_insights/identity/resolver.py`
**Commit:** 44f510b
**Applied fix:** `doc = await asyncio.to_thread(resolver.did.resolve, did)` — the blocking `atproto` call now runs in a worker thread so the event loop remains free for other coroutines.

### WR-05: `did:web` URL derivation does not handle percent-encoded ports per W3C spec

**Files modified:** `src/folio_insights/identity/resolver.py`, `tests/identity/test_did_doc_cache.py`
**Commit:** fcf9901
**Applied fix:** `_did_web_url` now uses `urllib.parse.unquote` on the first segment so `did:web:example.org%3A8443` → `https://example.org:8443/.well-known/did.json` per the W3C spec. Also added an SSRF host blocklist: `localhost`, `127.0.0.1`, `::1`, `0.0.0.0`, and any `169.254.*` link-local address raise `UnresolvableDidError`. Five tests cover both: percent-encoded port, root-form, path-form, and parametrized blocklist (localhost, 127.0.0.1, 0.0.0.0, 169.254.169.254, 169.254.1.2).

### WR-06: `verify_attestation` falls back to fetching the CURRENT did:web doc on cache miss — silent F2 hole

**Files modified:** `src/folio_insights/identity/verifier.py`, `tests/identity/test_sign_verify_methods.py`
**Commit:** a30616a
**Applied fix:** Made the verifier strict on the snapshot-required path: when `sig.did_doc_snapshot_at is not None` AND `sig.did` starts with `did:web:` or `did:plc:`, the verifier consults the cache ONLY. A miss returns `False` without ever invoking `http` or `plc_resolver`. did:key signatures bypass the strict check (the key IS the DID; rotation impossible).

Updated four pre-existing tests (`test_did_web_sign_verify_round_trip`, `test_did_plc_sign_verify_round_trip`, parametrized `did:web`/`did:plc`) to pre-seed the cache via a new async helper `_seed_snapshot`. Added two new tests: `test_verify_cold_cache_for_historical_didweb_fails_closed` and `test_verify_cold_cache_for_historical_didplc_fails_closed` — each asserts (i) verify returns `False`, (ii) the `http` / `plc_resolver` seam is never invoked (tracking lists stay empty).

**Note:** This is a behavioral change — Phase 13 (persistence) will need to populate the `DidDocCache` at sign time so the cache is warm when historical verification runs. The existing rotation-survival test already followed this pattern; the new strict path makes it mandatory.

### WR-07: `verify_cmd` ignores http/plc resolver overrides — CLI verify silently hits network

**Files modified:** `src/folio_insights/identity/cli.py`
**Commit:** fcb16c3
**Applied fix:** Added two Click flags to `did verify`:

  - `--did-doc <path>`: load a recorded `did.json` from disk and stub the http callable to return it (offline did:web verify).
  - `--allow-network`: explicit opt-in. Without either flag, the CLI passes a `_refuse_network` http callable that raises with a clear "WR-07: CLI does not touch the network by default" message.

did:key signatures verify cleanly with no flags (no http needed). did:web / did:plc require an explicit decision from the operator.

### WR-08: `_normalize_for_jcs` mis-detects non-datetime strings as ISO datetimes

**Files modified:** `src/folio_insights/revision/content_edit.py`, `tests/identity/test_canonical_jcs_properties.py`
**Commit:** d2f9ba4
**Applied fix:** Replaced the loose positional shape check (length ≥19, `-`/`-`/`T`/`:`/`:` at fixed offsets) with an anchored module-level `_ISO_DT_RE` regex. The `Z` suffix is now stripped ONCE at the end (`nfc[:-1] + "+00:00"`) only when `nfc.endswith("Z")`, never via blanket `replace`. Added three tests: malformed `"2020-Z1-01T00:Z0:00Z"` stays a string; legitimate Z-suffix form canonicalizes; legitimate `+00:00` form also canonicalizes.

### WR-09: `_b64url_nopad_encode` / `_b64url_nopad_decode` duplicated across modules

**Files modified:** `src/folio_insights/identity/_b64.py` (new), `src/folio_insights/identity/keys.py`, `src/folio_insights/identity/signer.py`, `src/folio_insights/identity/verifier.py`
**Commit:** b64d5a4
**Applied fix:** Created `src/folio_insights/identity/_b64.py` with the two helpers. Updated keys.py, signer.py, verifier.py to import from `_b64`. The underscore filename keeps the helper module out of the `test_no_server_keys_contract` AST walk (it filters `glob("*.py")` to exclude `_*.py`); the contract surface is unchanged because none of `_b64.py`'s functions touch private-key material.

## Skipped Issues

None — all 13 in-scope findings were fixed.

The five Info findings (IN-01..IN-05) were deliberately out of scope per the `--fix` request (critical_warning scope). They remain documented in `06-REVIEW.md` for follow-up; in summary:

- **IN-01** Reverse-store F7 check is O(n) and leaks bind state — needs a reverse-index dict.
- **IN-02** `_SENTINEL_NO_AT = datetime(1970, 1, 1, tzinfo=UTC)` is a fragile sentinel — astronomically unlikely collision but design-fragile.
- **IN-03** Unused `Field` import in cache.py — minor.
- **IN-04** CLI sign output parsing in tests is fragile — would benefit from a `--out` flag.
- **IN-05** `signing_key: Any` should be `Ed25519PrivateKey | None`.

---

_Fixed: 2026-05-29T02:30:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
