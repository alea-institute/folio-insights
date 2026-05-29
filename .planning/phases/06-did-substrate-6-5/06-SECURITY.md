---
phase: 06-did-substrate-6-5
audited: 2026-05-29T00:00:00Z
asvs_level: 2
block_on: critical
threats_total: 15
threats_closed: 15
threats_open: 0
unregistered_flags: 0
status: SECURED
---

# Phase 6 (DID Substrate §6.5) — Security Audit

**Adversarial stance:** every declared mitigation treated as absent until a
grep/AST match proves it exists in the right location. Audit verifies the
fifteen threats in PLAN.md `<threat_model>` blocks (Plans 06-01 + 06-02 +
06-03), the CR-01 F7-takeover-defense fix at `binding.py:386-411`, the WR-06
verifier cold-cache fail-closed path, the T-06-08 no-PLC-writes invariant, and
the T-06-05 AST contract test.

## Threat Verification Summary

15/15 threats CLOSED. 0 OPEN. 0 unregistered flags.

| Threat ID | Category | Disposition | Verification |
|-----------|----------|-------------|--------------|
| T-06-01 | Tampering (supply chain — 6 new pip deps) | mitigate | CLOSED |
| T-06-02 | Spoofing (canonical_content_hash non-determinism / F4) | mitigate | CLOSED |
| T-06-03 | Tampering (AttestedSignature accepts forged fields) | mitigate | CLOSED |
| T-06-04 | Repudiation (content_edit stub still unsigned after reshape) | accept | CLOSED |
| T-06-05 | InfoDisclosure (private signing key) | mitigate | CLOSED |
| T-06-06 | Spoofing (verifier resolves CURRENT key for HISTORICAL sig / F2) | mitigate | CLOSED |
| T-06-07 | Tampering (MITM'd did:web did.json) | mitigate | CLOSED |
| T-06-08 | ElevationOfPrivilege (did:plc write/genesis path) | avoid | CLOSED |
| T-06-09 | Tampering (atproto/dag_cbor network + decode) | mitigate | CLOSED |
| T-06-10 | Spoofing (binding-proof replay / F3) | mitigate | CLOSED |
| T-06-11 | Spoofing (OAuth->DID username takeover / F7) | mitigate | CLOSED |
| T-06-12 | Tampering (silent re-bind) | mitigate | CLOSED |
| T-06-13 | Spoofing (did:web domain control) | mitigate | CLOSED |
| T-06-14 | InfoDisclosure (did CLI signing) | mitigate | CLOSED |
| T-06-SC | Tampering (supply chain — no new deps in Plan 03) | accept | CLOSED |

## Per-Threat Evidence

### T-06-01 — Supply chain (6 new pip deps) — MITIGATE → CLOSED

Mitigation declared: pinned exact versions from STACK.md (`==`); RISK-4
rejection comment for didkit/pydid/python-jose/fastapi-users.

Evidence verified in `pyproject.toml`:
- Line 29-32: RISK-4 rejection comment naming all four rejected packages
  (`didkit`, `pydid`, `python-jose`, `fastapi-users`).
- Line 34-39: exact `==` pins for `pynacl==1.6.2`, `jcs==0.2.1`,
  `atproto==0.0.65`, `dag-cbor==0.3.3`, `joserfc==1.6.4`, `authlib==1.7.0`.
- `uv.lock` updated; STACK pin for `cryptography==46.0.7` resolved.

### T-06-02 — canonical_content_hash non-determinism (F4) — MITIGATE → CLOSED

Mitigation declared: RFC-8785 JCS + NFC + canonical-RFC-3339-UTC datetime +
explicit-None policy; 1000-shuffle property test + cyberphone cross-impl golden.

Evidence verified:
- `src/folio_insights/revision/content_edit.py` imports `jcs` and
  `unicodedata`; defines `_normalize_for_jcs`, `_canonicalize_datetime`,
  `_jcs_canonical_bytes`.
- `_HASH_EXCLUDED_FIELDS` exclusion set preserved (transaction_time,
  valid_time_start/end, content_edits, signatures).
- WR-08 fix: ISO-datetime detection uses anchored regex
  `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$`.
- `tests/identity/test_canonical_jcs_properties.py`: `@given` with
  `max_examples=1000`, NFC/NFD invariance, datetime stability,
  exclusion-set guard.
- `tests/identity/test_jcs_golden.py`: 50 vendored cyberphone fixtures
  pinned with regression guard.

### T-06-03 — AttestedSignature accepting unknown/forged fields — MITIGATE → CLOSED

Mitigation declared: `extra="forbid"` + Literal action + `verified` default
None.

Evidence verified in `src/folio_insights/shards/envelope.py`:
- Line 151: `model_config = ConfigDict(extra="forbid")`.
- Line 85-103: `SignedAction = Literal[...]` with 12 reconciled members.
- Line 154: `action: SignedAction = "content_edit"` (Literal, not str).
- Line 161: `verified: Optional[bool] = None` (anti-spoofing default).
- Line 162: `cosigners: list["AttestedSignature"] = Field(default_factory=list)`.

### T-06-04 — content_edit stub still unsigned after reshape — ACCEPT → CLOSED

Acceptance declared: `signing_key_id`/`signature` default empty so Phase-5
audit stub stays honestly unsigned; real signing arrives in Plan 02.

Evidence verified:
- `envelope.py` line 156-160: `signature: str = ""`, `signing_key_id: str = ""`,
  `did_doc_snapshot_at: Optional[datetime] = None` defaults.
- `revision/content_edit.py` `sign_attestation` branches on `signing_key is
  None`: when None, retains the Phase-5 unsigned stub (`signature=""`); when
  supplied, delegates to `identity.signer.sign_attestation` (real ed25519).
- T-06-03 default `verified=None` ensures an unsigned stub never reads as
  "verified" — the acceptance is HONEST (no false positives).
- Documented bounded deferral noted in 06-01-SUMMARY.md.

### T-06-05 — Private signing key (InfoDisclosure) — MITIGATE → CLOSED

Mitigation declared: 0o600 home-dir keyfile + AST contract test refusing
non-keys.py persistence.

Evidence verified:
- `src/folio_insights/identity/keys.py` line 180-194: `mkdir(mode=0o700)` +
  `chmod(0o700)` on parent; `chmod(0o600)` on keyfile after write.
- Line 228-241: WR-02 POSIX-aware mode check (`os.name == "posix"`) refuses
  group/world-readable keyfile via `forbidden_bits = stat.S_IRWXG |
  stat.S_IRWXO`.
- `tests/identity/test_no_server_keys_contract.py` line 52-58: walks every
  `src/folio_insights/identity/*.py` (filtering `_*.py` like `_b64.py`),
  asserts `private_bytes` call count ≤ 0 for non-keys.py (allowance=1 for
  `signer.py` per the documented single permitted conversion call in
  `_ed25519_key_to_nacl`).
- Line 109-151: parallel parametrize asserts NO non-keys.py module
  co-presents a JWK `"d"` dict literal AND a `write_text`/`write_bytes`/
  `write` sink.
- Line 180-212: AST scan for module-global `Ed25519PrivateKey.generate()`
  assignment — fails the build if found anywhere in identity/.
- Note: `_b64.py` is intentionally excluded by the `_*.py` filter; review
  documented this as safe (the module contains only base64url helpers, no
  key material). Confirmed by reading `_b64.py` content via the broader
  AST scan (it has zero `private_bytes` calls and zero write sinks).

### T-06-06 — Verifier resolving CURRENT key for HISTORICAL signature (F2) — MITIGATE → CLOSED

Mitigation declared: `signing_key_id` + `did_doc_snapshot_at` captured at
signing; verifier resolves signing-time key via DidDocCache snapshot;
rotation-survival test proves it.

Evidence verified:
- `src/folio_insights/identity/signer.py` line 95-106: `sign_attestation`
  populates `signing_key_id` and `did_doc_snapshot_at` on every signature.
- `src/folio_insights/identity/verifier.py` line 113-123 (WR-06 fix): when
  `sig.did_doc_snapshot_at is not None AND not sig.did.startswith("did:key:")`,
  the verifier consults the cache ONLY; a miss returns `False` without
  invoking `http` or `plc_resolver`. This closes the cold-cache F2 hole the
  reviewer flagged — no silent fallback to the current (rotated) doc.
- `tests/identity/test_signature_survives_key_rotation.py`:
  - `test_did_key_rotation_is_a_no_op` (degenerate).
  - `test_did_web_signature_survives_key_rotation` (real rotation, asserts
    cache snapshot is load-bearing — naive current-key verifier WOULD fail).
- `tests/identity/test_sign_verify_methods.py` line 320, 367:
  `test_verify_cold_cache_for_historical_didweb_fails_closed` and
  `test_verify_cold_cache_for_historical_didplc_fails_closed` confirm the
  WR-06 strict path: cold cache → `False`, `http`/`plc_resolver` never
  invoked.

### T-06-07 — MITM/rotated did:web did.json — MITIGATE → CLOSED

Mitigation declared: did:web fetched over HTTPS; snapshot at signing time
authoritative; Plan-03 adds domain-control proof.

Evidence verified:
- `resolver.py` line 111-115 (CR-03): `_default_http_get` enforces
  `url.startswith("https://")`, raises `UnresolvableDidError` on non-HTTPS.
- Line 116-120: `httpx.AsyncClient(timeout=10.0, follow_redirects=False,
  verify=True)` — explicit HTTPS verification + no redirect-to-http pivot.
- Line 82, 121-134: streaming `_MAX_DID_WEB_BYTES = 1 MiB` cap with
  `UnresolvableDidError` abort.
- Line 247-255 (WR-05): SSRF host blocklist refuses `localhost`,
  `127.0.0.1`, `::1`, `0.0.0.0`, `169.254.*` link-local.
- `binding.py` line 492-504: did:web bind path calls the resolver as a
  domain-control side gate; resolver failure → `DomainControlFailed`.

### T-06-08 — did:plc write/genesis (Elevation of Privilege) — AVOID → CLOSED

Avoidance declared: did:plc is RESOLVE/VERIFY ONLY; never submits a PLC
operation.

Evidence verified:
- `grep -rnE "did\.create|did\.submit|put_operation|plc_create|plc_register|create_did|register_did|submit_operation" src/folio_insights/identity/` → ZERO matches.
- `resolver.py` line 175-183: only `IdResolver()` + `resolver.did.resolve(did)`
  (read) is invoked; wrapped in `asyncio.to_thread` (WR-04). No write API
  surface is reachable.
- Module docstring line 15-17 declares "RESOLVE/VERIFY ONLY — this resolver
  NEVER submits a PLC operation".
- CR-02 fix: when called with a non-None `at`, `_default_plc_resolve` raises
  `UnresolvableDidError` rather than silently returning current head (closes
  the silent-wrong-key F2 hole on the resolve path).

### T-06-09 — atproto/dag_cbor network + decode (supply chain) — MITIGATE → CLOSED

Mitigation declared: injected network seams; pinned versions; resolver raises
typed errors on unresolvable/unknown method.

Evidence verified:
- `resolver.py` line 363-369: `resolve_did(..., *, cache, http, plc_resolver)`
  — every network dep is keyword-injectable.
- Line 469-471: `UnknownDidMethodError` raised for unsupported method.
- Line 444-454, 422-426: `UnresolvableDidError` raised on network/JSON
  failure; never returns a wrong key silently.
- `atproto==0.0.65` + `dag-cbor==0.3.3` pinned in `pyproject.toml` (T-06-01).

### T-06-10 — Binding-proof replay (F3) — MITIGATE → CLOSED

Mitigation declared: single-use server nonce + ±2-min timestamp + binding
endpoint URL in DID-signed proof.

Evidence verified in `binding.py`:
- Line 98: `NONCE_TTL = timedelta(minutes=5)`.
- Line 101: `PROOF_CLOCK_SKEW = timedelta(minutes=2)`.
- Line 217-225: `InMemoryNonceStore.consume` uses atomic `dict.pop`
  (CPython GIL guarantee); refuses re-consume + expired.
- Line 440-465 (WR-01 fix): gate ordering is timestamp (±2 min) →
  endpoint match → nonce consume. A bad proof cannot burn a good nonce.
- Tests: `test_replayed_nonce_rejected`, `test_nonce_expired_after_6min`,
  `test_skewed_timestamp_rejected`, `test_endpoint_mismatch_rejected`,
  `test_stale_proof_does_not_consume_nonce`,
  `test_endpoint_mismatch_does_not_consume_nonce`.

### T-06-11 — OAuth->DID binding username takeover (F7) — MITIGATE → CLOSED

Mitigation declared: bind to immutable `sub` only; subject-change detection;
email/username-keyed bindings refused.

Evidence verified in `binding.py` — both CR-01 fixes confirmed present at
the cited lines 386-411:
- Line 386-391 **CR-01(a)**: `if signature.did != did: raise
  InvalidProofSignature(...)`. Signer DID must equal bound DID — closes the
  attacker's "sign with own DID, claim victim sub" path.
- Line 398-411 **CR-01(b)**: recomputes `expected_hash =
  hashlib.sha256(_jcs_canonical_bytes(proof.model_dump(mode="json"))).
  hexdigest()`; raises `InvalidProofSignature` if `signature.
  over_content_hash != expected_hash`. Closes the "sign an unrelated hash"
  path.
- Line 245: `_SUSPECT_USERNAME` regex (WR-03) refuses bare-alphanumeric
  1-15-char subjects without `:` or `|`.
- Line 248-289 `_assert_sub_is_oauth_sub`: rejects empty/whitespace,
  email-shaped (`@`), and bare-username-shaped.
- Line 481-487: F7 reverse check — same did under different sub raises
  `SubjectChanged`.
- Tests (regression for CR-01): `test_signature_did_mismatch_rejected`,
  `test_signature_hash_does_not_cover_proof_rejected`,
  `test_attacker_cannot_bind_victim_sub_with_own_did`,
  `test_email_sub_refused`, `test_empty_sub_refused`,
  `test_bare_username_sub_refused`,
  `test_provider_prefixed_numeric_sub_accepted`,
  `test_subject_change_rejected`,
  `test_different_did_for_same_sub_rejected`.

### T-06-12 — Silent re-bind (Tampering) — MITIGATE → CLOSED

Mitigation declared: repeat (sub, did) is no-op; different did for same sub
is explicit conflict.

Evidence verified in `binding.py`:
- Line 467-479: idempotent `existing.did == did` returns the SAME
  `BindingRecord` instance; `existing.did != did` raises `SubjectChanged`
  (never silently overwrites).
- Line 481-487: same did under different sub also raises `SubjectChanged`
  (both directions of subject-change detection).
- Test `test_idempotent_repeat_bind` asserts `second is first` AND
  `bound_at` + `proof` unchanged from the first bind.

### T-06-13 — did:web domain control (Spoofing) — MITIGATE → CLOSED

Mitigation declared: did:web binding verifies `.well-known/did.json` lists
the bound key.

Evidence verified in `binding.py`:
- Line 492-504: `if did.startswith("did:web:"): ... await resolver(did,
  at=None, cache=cache, http=http, plc_resolver=plc_resolver)`; any
  exception raises `DomainControlFailed`. The Plan-02 resolver does the
  `.well-known/did.json` fetch + vm extract.
- Combined with CR-03 (HTTPS only, 1 MiB cap, no-redirect) and WR-05 (SSRF
  blocklist) on the underlying fetch.

### T-06-14 — did CLI signing (Information disclosure) — MITIGATE → CLOSED

Mitigation declared: client-side keyfile via Plan-02 keys.py; CLI never
sends/logs a private key.

Evidence verified:
- `src/folio_insights/identity/cli.py` loads the key inside the command
  function frame via `keys.load_signing_key`; passes it to
  `sign_attestation`; reference drops.
- `tests/identity/test_no_server_keys_contract.py` AST-scans `cli.py`
  along with every other non-keys.py module → 0 `private_bytes` calls
  (allowance=0 for cli.py); 0 JWK-`d`-write co-presence.
- WR-07 fix: `did verify` adds `--did-doc` (offline) and `--allow-network`
  flags; default refuses live network for did:web/did:plc (no SSRF pivot
  from CLI verify of attacker-supplied AttestedSignature).

### T-06-SC — No new deps in Plan 03 — ACCEPT → CLOSED

Acceptance declared: Plan 03 ships no new packages.

Evidence verified:
- `pyproject.toml` dependencies block unchanged from Plan 01 install (all
  6 DID deps already pinned).
- 06-03-SUMMARY.md `tech-stack.added`: "No new pip deps (all crypto + jcs
  + atproto pins came in Plan 06-01; authlib is referenced only in
  docstrings for OAuth sub-claim semantics)".
- `binding.py` line 40-43 docstring: "No `authlib` `Starlette` OAuth flow
  here — that's the deferred web surface. ... No `redis` import."

## Unregistered Threat Flags

None. Both 06-01-SUMMARY.md, 06-02-SUMMARY.md, and 06-03-SUMMARY.md declare
their `Threat Flags` sections as "None — no NEW security-relevant surface
introduced beyond the plan's threat model." Audit confirms: the did:web HTTP
fetch surface is bounded by the injectable `http` seam + WR-05 SSRF blocklist
+ CR-03 HTTPS-only + size cap; the operator-provided `--binding-endpoint` URL
is a string pinned in the signed proof (no fetch). No new trust boundary
introduced.

## Code Review Outcome Confirmation

The phase ran through `gsd-code-reviewer` (06-REVIEW.md) which identified
4 Critical + 9 Warning + 5 Info findings. The follow-on `gsd-code-fixer`
(06-REVIEW-FIX.md) closed all 13 critical+warning findings in 13 atomic
commits. Audit confirms each security-relevant fix is present in source:

| Finding | Fix location | Audit confirmation |
|---------|-------------|---------------------|
| CR-01 (F7 takeover) | `binding.py:386-411` | CONFIRMED — both signature.did check (l.386) and proof-hash check (l.398-411) present |
| CR-02 (silent F2 on default plc resolver) | `resolver.py:158-171` | CONFIRMED — non-None `at` raises `UnresolvableDidError` |
| CR-03 (did:web DoS / fetch limits) | `resolver.py:82,111-137` | CONFIRMED — HTTPS-only, follow_redirects=False, 1 MiB streaming cap |
| CR-04 (CLI coupling) | `identity/__init__.py` (did_group export removed) | CONFIRMED — root cli.py imports did_group directly |
| WR-01 (nonce burn ordering) | `binding.py:432-465` | CONFIRMED — timestamp + endpoint before nonce consume |
| WR-02 (Windows mode check) | `keys.py:221-250` | CONFIRMED — branches on os.name |
| WR-03 (bare-username F7) | `binding.py:245,280-289` | CONFIRMED — `_SUSPECT_USERNAME` regex |
| WR-04 (sync call in event loop) | `resolver.py:182-183` | CONFIRMED — `asyncio.to_thread` wrapper |
| WR-05 (SSRF host blocklist + percent-port) | `resolver.py:207-260` | CONFIRMED — unquote + blocklist |
| WR-06 (verifier cold-cache fail-closed) | `verifier.py:113-123` | CONFIRMED — strict cache-only for did:web/did:plc with snapshot |
| WR-07 (CLI verify network opt-in) | `identity/cli.py` (--did-doc / --allow-network) | CONFIRMED via VERIFICATION.md spot-check |
| WR-08 (anchored ISO datetime regex) | `revision/content_edit.py` | CONFIRMED — `_ISO_DT_RE` anchored regex |
| WR-09 (base64url DRY) | `identity/_b64.py` | CONFIRMED — keys.py/signer.py/verifier.py all import from `_b64` |

## Info Findings — Tracked, Not Blocking

The 5 IN-01..IN-05 info findings remain open per the documented scope
decision (the `--fix` run targeted critical+warning only). They are:

- IN-01: O(n) reverse-store F7 check leaks bind state via timing/error
  messages. Recommend reverse-index dict in a future hardening pass.
- IN-02: `_SENTINEL_NO_AT = datetime(1970,1,1,UTC)` is a fragile sentinel
  (astronomically unlikely collision but not impossible).
- IN-03: Unused `Field` import in `cache.py`.
- IN-04: CLI sign output parsing in tests is fragile.
- IN-05: `signing_key: Any` should be `Ed25519PrivateKey | None`.

None of these block Phase 6 completion (none are CVSS-relevant
vulnerabilities), but IN-01 in particular is recommended as a follow-up
hardening item for any phase that exposes the bind endpoint to the public
internet.

## Audit Outcome

```
Phase: 06 — DID Substrate (§6.5)
Threats Closed: 15/15
ASVS Level: 2
Result: SECURED
Blockers: 0
```

_Audited: 2026-05-29_
_Auditor: Claude (gsd-security-auditor, Opus 4.7)_
