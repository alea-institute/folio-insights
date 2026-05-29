---
phase: 06-did-substrate-6-5
reviewed: 2026-05-28T20:19:34Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - src/folio_insights/identity/__init__.py
  - src/folio_insights/identity/binding.py
  - src/folio_insights/identity/cache.py
  - src/folio_insights/identity/cli.py
  - src/folio_insights/identity/keys.py
  - src/folio_insights/identity/preview.py
  - src/folio_insights/identity/resolver.py
  - src/folio_insights/identity/signer.py
  - src/folio_insights/identity/verifier.py
  - src/folio_insights/revision/content_edit.py
  - src/folio_insights/shards/__init__.py
  - src/folio_insights/shards/envelope.py
  - tests/identity/__init__.py
  - tests/identity/conftest.py
  - tests/identity/test_attested_signature_shape.py
  - tests/identity/test_binding_proof.py
  - tests/identity/test_canonical_jcs_properties.py
  - tests/identity/test_did_cli.py
  - tests/identity/test_did_doc_cache.py
  - tests/identity/test_jcs_golden.py
  - tests/identity/test_no_server_keys_contract.py
  - tests/identity/test_sign_verify_methods.py
  - tests/identity/test_signature_survives_key_rotation.py
  - tests/identity/test_signing_preview.py
findings:
  critical: 4
  warning: 9
  info: 5
  total: 18
status: partial
fix_iteration: 1
fixed:
  critical: 4
  warning: 9
  skipped:
  - "IN-01..IN-05 (info findings — out of scope per --fix scope)"
---

# Phase 6: Code Review Report

**Reviewed:** 2026-05-28T20:19:34Z
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

Phase 6 ships the DID-signed attestation substrate: ed25519 sign/verify, JCS canonicalization (RFC-8785), did:key / did:web / did:plc resolution, OAuth→DID binding, and the DID-07 preview. The JCS pipeline is solidly proved (1000-shuffle property test + ~50-input cyberphone cross-impl golden test); the ed25519 sign/verify round-trip is well-exercised across all three DID methods; key-rotation survival (EC3) has a real did:web test, not just a tautology.

However, the binding contract — the F7 GitHub-takeover defense — has a **critical hole**: `bind()` never verifies that the proof signature actually attests to the proof payload, nor that the signer DID matches the bound DID. An attacker who knows (or guesses) a victim's OAuth `sub` can claim it for their own DID without ever possessing the victim's key. This bypasses the entire SEC-06 / F7 design. Two further critical issues compound this: the default did:plc resolver silently ignores the historical `at` parameter (Pitfall F2 silent-wrong-key), and the did:web fetcher has no response size limit (denial-of-service / memory exhaustion via a malicious DID host).

The other findings are quality-grade: incomplete platform handling in `load_signing_key`, fragile CLI output parsing, event-loop blocking in the default PLC resolver, and minor code duplication.

## Critical Issues

### CR-01: `bind()` does not verify the proof signature is bound to THIS proof payload — F7 takeover bypass

**File:** `src/folio_insights/identity/binding.py:343-354`
**Issue:** The bind contract is supposed to defeat the GitHub-username-takeover vector (F7 / SEC-06): an attacker must not be able to bind a victim's OAuth `sub` to a DID the attacker controls. The current implementation has two missing checks that, together, allow exactly that:

1. `bind()` never recomputes `sha256(jcs(proof.model_dump(mode="json")))` and compares it to `signature.over_content_hash`. The verifier only checks "is this signature valid over `signature.over_content_hash`?" — it does NOT check that the signed hash is the hash of the proof payload presented to `bind()`.
2. `bind()` never asserts `signature.did == did` (the signer DID equals the DID being bound). The function only enforces `proof.did == did`, but `proof` is unauthenticated input — only the `AttestedSignature` carries cryptographic provenance.

**Attack:** An attacker who knows a victim's OAuth `sub` (e.g., GitHub numeric IDs are enumerable) can:
1. Generate a fresh ed25519 keypair `(sk_atk, pk_atk)` and derive `did_atk = did_key_from_public(pk_atk)`.
2. Obtain a server nonce via the public `nonce_store.issue()` endpoint.
3. Build `proof = ProofPayload(sub=victim_sub, nonce=N, issued_at=now, binding_endpoint=ep, did=did_atk)`.
4. Sign ANY hash with `sk_atk` (e.g., `h = sha256(b"unrelated")`) and submit `AttestedSignature(did=did_atk, signature=sig_of_h, over_content_hash=h, ...)`.
5. `verify_attestation` resolves `did_atk` (the embedded key IS `pk_atk`), confirms the signature is valid over `h`. Returns True.
6. `bind()` checks `proof.sub == victim_sub` (yes), `proof.did == did_atk` (yes), nonce/timestamp/endpoint gates pass. The bind succeeds.

Now `binding_store[victim_sub] = did_atk`. When the legitimate victim attempts to bind their real DID under the same sub, they hit `SubjectChanged`. The attacker has hijacked the sub. Worse: any system that downstream trusts `sub → did` mappings now grants the attacker authority that should belong to the victim.

The `verify_attestation` docstring already hints that the verifier is "fail-closed" on the SIGNATURE only — it is the caller's responsibility to bind the signature to a particular payload. Bind doesn't.

The existing test `test_invalid_proof_signature_rejected` does NOT catch this: it signs with the WRONG key but keeps `signature.did = did_bound` so the verifier resolves the wrong public key. The attacker in this scenario sets `signature.did = did_atk` (their OWN DID), so verification succeeds.

**Fix:**
```python
# In bind(), after the F7 subject check, BEFORE verify_attestation:
import hashlib
from folio_insights.revision.content_edit import _jcs_canonical_bytes

# 1a. Signer DID must equal bound DID — the signature attests to THIS DID.
if signature.did != did:
    raise InvalidProofSignature(
        f"Proof signature.did {signature.did!r} does not match bound did "
        f"{did!r}; refusing to bind."
    )

# 1b. Signature must attest to THIS proof payload, not some other hash.
expected_hash = hashlib.sha256(
    _jcs_canonical_bytes(proof.model_dump(mode="json"))
).hexdigest()
if signature.over_content_hash != expected_hash:
    raise InvalidProofSignature(
        f"Proof signature.over_content_hash {signature.over_content_hash!r} "
        f"does not match hash of proof payload {expected_hash!r}; signature "
        "does not attest to this proof."
    )
```

Add regression tests:
* `test_signature_did_mismatch_rejected` — `signature.did != did` → `InvalidProofSignature`.
* `test_signature_hash_does_not_cover_proof_rejected` — valid signature over an unrelated hash → `InvalidProofSignature`.
* `test_attacker_cannot_bind_victim_sub_with_own_did` — the full takeover scenario above, asserting `bind()` rejects.

---

### CR-02: Default did:plc resolver silently ignores `at` — Pitfall F2 silent-wrong-key

**File:** `src/folio_insights/identity/resolver.py:82-108`
**Issue:** The resolver's contract — restated at the top of the module — is that "the resolver NEVER returns a wrong key silently (T-06-09)". For did:plc, the verifier passes `at=sig.did_doc_snapshot_at` so verification resolves the **signing-time** key, not the current key (SEC-05 / F2). The default `_default_plc_resolve` accepts `at` as a parameter and **discards it**:

```python
async def _default_plc_resolve(did: str, at: datetime | None) -> dict:
    ...
    resolver = IdResolver()
    doc = resolver.did.resolve(did)   # ← ignores `at`
```

If the operator does not inject a custom `plc_resolver` and the PLC operator has rotated keys since signing, verification resolves the **current** doc against a historical `signed_at` — and either returns False (when the rotation invalidates the signature) or returns True against the WRONG key (if the current key happens to verify the historical hash, e.g. via a deliberate rotation-revert attack). Both outcomes are exactly the F2 silent-wrong-key the design promises to prevent.

The docstring says "callers SHOULD inject a custom resolver", but the resolver is reachable as the public default; the only way to know a caller forgot is if verification mysteriously fails after a rotation. The module-level promise ("resolver NEVER returns a wrong key silently") is broken by the default.

**Fix:** Either (a) raise `UnresolvableDidError` when `at` is provided and the default cannot honor it, or (b) walk the PLC op log to pin to `at`:

```python
async def _default_plc_resolve(did: str, at: datetime | None) -> dict:
    if at is not None:
        raise UnresolvableDidError(
            f"Default did:plc resolver cannot pin historical at={at!r}; "
            "inject a custom plc_resolver that walks the plc.directory "
            "op log (Pitfall F2 / D-08)."
        )
    from atproto import IdResolver
    resolver = IdResolver()
    doc = resolver.did.resolve(did)
    ...
```

Add a test: `test_default_plc_resolver_refuses_historical_at` — calling `resolve_did("did:plc:...", at=t)` without injecting a resolver raises `UnresolvableDidError`.

---

### CR-03: `_default_http_get` has no response-size limit — did:web DoS / memory exhaustion

**File:** `src/folio_insights/identity/resolver.py:74-79`
**Issue:** The default did:web fetcher reads the entire response body into memory via `resp.json()`. There is no `max_response_size` cap, no streaming check, and no content-type allow-list. A malicious or compromised did:web host (or a host the operator was tricked into resolving) can:

* Return gigabytes of bytes → process OOM.
* Return slow-trickle content within the 10-second timeout per chunk → resource exhaustion.
* Return content of type `text/html` that happens to parse as JSON → unexpected control flow.

The phase-6 prompt explicitly calls out "did:web HTTPS fetch (TLS verification, fetch size limits)" as a review focus. TLS verification is fine (httpx defaults to verify=True), but no size limit is enforced.

Additionally:
* No explicit HTTPS-scheme assertion. `_did_web_url` always produces `https://`, but if any future code path or operator override passes a custom `http` callable that follows a redirect to `http://`, there's no defense. (Httpx default `follow_redirects=False` mitigates this today, but the contract should be explicit.)
* No restriction on the resolved hostname. `did:web:localhost` resolves to `https://localhost/.well-known/did.json` — server-side resolution of attacker-controlled DIDs becomes an SSRF vector against internal services if the resolver is ever invoked from a server-side context.

**Fix:**
```python
_MAX_DID_WEB_BYTES = 1 * 1024 * 1024  # 1 MiB — DID docs are kilobytes

async def _default_http_get(url: str) -> dict:
    if not url.startswith("https://"):
        raise UnresolvableDidError(
            f"did:web fetch requires https://, got {url!r}"
        )
    async with httpx.AsyncClient(
        timeout=10.0,
        follow_redirects=False,
        verify=True,
    ) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > _MAX_DID_WEB_BYTES:
                    raise UnresolvableDidError(
                        f"did:web response from {url!r} exceeds "
                        f"{_MAX_DID_WEB_BYTES} bytes; refusing to load."
                    )
                chunks.append(chunk)
            import json as _json
            return _json.loads(b"".join(chunks))
```

Also consider an opt-in SSRF allow-list / blocklist for resolver hosts in server-side contexts; at minimum, document in `resolve_did` that callers in server contexts MUST supply a vetted `http` callable rather than relying on the default.

Add tests:
* `test_did_web_response_too_large_rejected` — fake http returns >1 MiB → `UnresolvableDidError`.
* `test_did_web_non_https_url_refused` — non-HTTPS URL → `UnresolvableDidError`.

---

### CR-04: `cli.py` and `__init__.py` couple every identity import to `click`

**File:** `src/folio_insights/identity/__init__.py:61`
**Issue:** The package init imports `from folio_insights.identity.cli import did_group`, which pulls `click` into the import graph of every consumer of `identity/` — including the signer/verifier hot paths. Worse, the imports flow `identity → cli → click → revision.content_edit` (via `_jcs_canonical_bytes`), and `cli.py` is also a security-sensitive surface (handles key material). Coupling them means:

* A bug in `click`'s parser (or a transitive dep) becomes a bug surface for `identity.sign_attestation` callers.
* `tests/identity/test_no_server_keys_contract.py` parses every `identity/*.py` for AST patterns — `cli.py` now sits in that contract surface, increasing the attack-surface footprint of the EC4 invariant.
* Removing the CLI from a deployment that uses only `identity.signer` is not possible without ripping the import out of `__init__.py`.

While `click` is benign, the project's stated dep-isolation discipline (shards/ stays crypto-free; revision/ does not import identity/) is undermined by `__init__.py` eager-importing the CLI. **This also breaks the no-server-keys contract test** if `cli.py` itself ever picks up a `private_bytes` call site (it currently doesn't, but only because the helper `_derive_didkey_from_signing_key` defers the import inside the function body — a fragile arrangement).

**Fix:** Move the CLI import out of `__init__.py` and have the root CLI register the command via a direct import:

```python
# In src/folio_insights/cli.py (the root CLI):
from folio_insights.identity.cli import did_group
cli.add_command(did_group)
```

Remove from `src/folio_insights/identity/__init__.py:61`:
```python
# DELETE:
from folio_insights.identity.cli import did_group
# And remove "did_group" from __all__.
```

Verify by running `python -c "from folio_insights.identity import sign_attestation"` and asserting `click` is not in `sys.modules`.

This also clarifies the no-server-keys contract scope — `cli.py` may still be reviewed by the AST test, but the import direction now flows root-CLI → identity-CLI → identity, not identity → identity-CLI.

## Warnings

### WR-01: `bind()` consumes the nonce BEFORE timestamp / endpoint checks — DoS amplification

**File:** `src/folio_insights/identity/binding.py:356-380`
**Issue:** The ordering in `bind()` is: (1) F7 subject, (2) signature verify, (3) **nonce consume**, (4) timestamp window, (5) endpoint match. The docstring documents this order as deliberate. But it means a captured signed proof — even one with a wrong timestamp or wrong endpoint that will be rejected — burns the nonce before the gate fires. Concretely: an attacker who observes a freshly-issued nonce (e.g., from logs, or a victim's network) can submit any signed proof carrying that nonce with a deliberately stale timestamp; the nonce is consumed and the legitimate user's bind fails with `NonceReused`.

The right ordering is: cheap, non-stateful gates BEFORE the irreversible state mutation. Timestamp and endpoint are cheap, stateless string compares; nonce consume is irreversible.

**Fix:** Reorder to validate timestamp + endpoint BEFORE consuming the nonce:

```python
# Step 4: F3 timestamp window — pure compare, no state mutation.
skew = abs(current - proof.issued_at)
if skew > PROOF_CLOCK_SKEW:
    raise StaleProof(...)

# Step 5: F3 endpoint binding — pure compare.
if proof.binding_endpoint != expected_binding_endpoint:
    raise EndpointMismatch(...)

# Step 3 (moved): F3 single-use nonce — IRREVERSIBLE; runs last among the
# proof-payload gates so a bad proof doesn't burn a good nonce.
consumed = await nonce_store.consume(proof.nonce)
if not consumed:
    raise NonceReused(...)
```

Update the `bind()` docstring to reflect the new order.

---

### WR-02: `load_signing_key` POSIX-mode check is incorrect on Windows

**File:** `src/folio_insights/identity/keys.py:222-235`
**Issue:** The docstring says the POSIX mode check "is skipped on platforms without POSIX mode bits (e.g. plain Windows)", but the code does NOT actually skip:

```python
mode = key_path.stat().st_mode
forbidden_bits = stat.S_IRWXG | stat.S_IRWXO
if mode & forbidden_bits:
    raise PermissionError(...)
```

On Windows, `Path.stat().st_mode` returns a synthesized POSIX-style mode where files default to `0o666` (read+write for owner/group/other), so `mode & forbidden_bits` is always non-zero and **every Windows key load raises `PermissionError`** unsolvable by `chmod`. Either:
* The keystore is unusable on Windows (defeating cross-platform parity), or
* The operator is forced to monkey-patch the check, which removes the protection on Linux too.

**Fix:**
```python
import os
import sys

# POSIX mode check — refuse a world/group-readable keyfile on POSIX platforms.
# On Windows, st_mode is synthesized; skip the bit-mask check there and rely on
# NTFS ACLs (operator responsibility — surface a warning).
if os.name == "posix":
    try:
        mode = key_path.stat().st_mode
    except OSError as exc:
        raise OSError(f"could not stat {key_path}: {exc}") from exc
    forbidden_bits = stat.S_IRWXG | stat.S_IRWXO
    if mode & forbidden_bits:
        raise PermissionError(...)
elif os.name == "nt":
    import warnings
    warnings.warn(
        f"On Windows, POSIX mode bits on {key_path} are synthesized; rely on "
        "NTFS ACLs to restrict access (DID-06).",
        stacklevel=2,
    )
```

Add a test (skipped on non-Windows): `test_load_signing_key_windows_warns_no_posix_mode`.

---

### WR-03: F7 subject check accepts plain usernames — weak F7 surface

**File:** `src/folio_insights/identity/binding.py:231-261`
**Issue:** `_assert_sub_is_oauth_sub` rejects only "contains `@`" (email) and empty/whitespace. A plain GitHub-style username like `"alice"`, `"bob"`, or `"corpadmin"` passes. The docstring acknowledges this is "conservative" but the F7 GitHub-username-takeover vector is the exact reason to require an OAuth-`sub`-shaped value: GitHub `sub` claims look like `12345` (numeric) or `github:12345` (provider-prefixed), NOT `alice`.

An operator who naively passes the GitHub username instead of the numeric ID into `bind(sub=username, ...)` is exactly the F7 mistake the function is supposed to catch. The check should require either:
* A provider-prefixed form (`github:`, `google:`, `microsoft:`, …), or
* A numeric-only id, or
* An opaque ≥16-char identifier.

**Fix:** Strengthen the heuristic and emit a warning at minimum:

```python
import re

# Conservative: plain lowercase alpha strings shorter than 16 chars are
# suspect — they look like usernames, not opaque sub claims.
_SUSPECT_USERNAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,15}$")

def _assert_sub_is_oauth_sub(sub: str) -> None:
    if not sub or not sub.strip():
        raise InvalidSubject("Binding subject must be the OAuth `sub` claim ...")
    if "@" in sub:
        raise InvalidSubject(f"Binding subject {sub!r} looks like an email ...")
    if _SUSPECT_USERNAME.match(sub) and ":" not in sub:
        raise InvalidSubject(
            f"Binding subject {sub!r} looks like a bare username — bind to the "
            "provider-prefixed OAuth `sub` (e.g. 'github:12345'), NEVER a "
            "username (F7 / GitHub-takeover defense)."
        )
```

Add test: `test_bare_username_sub_refused` — `bind(sub="alice", ...)` raises `InvalidSubject`.

---

### WR-04: `_default_plc_resolve` blocks the event loop with a sync call

**File:** `src/folio_insights/identity/resolver.py:94-95`
**Issue:** `_default_plc_resolve` is declared `async`, but the body calls `resolver.did.resolve(did)` synchronously. This is a blocking network I/O call inside the asyncio event loop, stalling every other coroutine for the duration of the PLC fetch. Even ignoring the CR-02 silent-wrong-key bug, this is a correctness concern for callers using `asyncio.gather` over multiple verifies.

**Fix:** Either:
* Wrap in `asyncio.to_thread`: `doc = await asyncio.to_thread(resolver.did.resolve, did)`, or
* Use `atproto`'s async client if available.

```python
import asyncio
...
doc = await asyncio.to_thread(resolver.did.resolve, did)
```

(Note: this addresses the blocking concern only; CR-02 still requires explicit handling of `at`.)

---

### WR-05: `did:web` URL derivation does not handle percent-encoded ports per W3C spec

**File:** `src/folio_insights/identity/resolver.py:114-132`
**Issue:** Per W3C did:web spec, a port is encoded as `%3A` after the domain (e.g., `did:web:example.org%3A8443`), not as a colon-separated component. The current `_did_web_url`:

```python
parts = body.split(":")
domain = parts[0]
if len(parts) == 1:
    return f"https://{domain}/.well-known/did.json"
path = "/".join(parts[1:])
return f"https://{domain}/{path}/did.json"
```

…splits on `:` indiscriminately. A DID like `did:web:example.org:8443` becomes `https://example.org/8443/did.json` (treating the port as a path segment), not `https://example.org:8443/.well-known/did.json`. Similarly, `did:web:example.org%3A8443:user:alice` becomes `https://example.org%3A8443/user/alice/did.json` (which works but the host contains an unresolved percent-encoded char).

**Fix:** URL-decode the domain segment and detect a percent-encoded port:

```python
from urllib.parse import unquote

def _did_web_url(did: str) -> str:
    body = did.removeprefix("did:web:")
    if not body:
        raise UnresolvableDidError(f"empty did:web identifier in {did!r}")
    parts = body.split(":")
    # Per W3C: domain may contain percent-encoded port (e.g. "example.org%3A8443").
    domain = unquote(parts[0])
    # Reject unsafe hosts (SSRF defense; opt-in for server-side contexts).
    if domain in {"localhost", "127.0.0.1", "::1"} or domain.startswith("169.254."):
        raise UnresolvableDidError(
            f"refusing to resolve did:web for unsafe host {domain!r}"
        )
    if len(parts) == 1:
        return f"https://{domain}/.well-known/did.json"
    path = "/".join(parts[1:])
    return f"https://{domain}/{path}/did.json"
```

Add tests: `test_did_web_port_in_domain`, `test_did_web_localhost_refused`.

---

### WR-06: `verify_attestation` falls back to fetching the CURRENT did:web doc on cache miss — silent F2 hole

**File:** `src/folio_insights/identity/verifier.py:107-117`
**Issue:** When verifying a historical signature against did:web, the verifier passes `at=sig.did_doc_snapshot_at` to `resolve_did`. If the `DidDocCache` has the snapshot at that key, the verifier resolves the historical key (rotation-safe). If the cache MISSES (e.g., a fresh process started after the signing was recorded, or the persistence-phase has not run yet), the resolver falls through to `_default_http_get` and fetches **the CURRENT did.json** — which after rotation publishes a DIFFERENT key. The signature then fails to verify, and the caller sees `False`.

This is correctly fail-closed for the rotated case, but two latent issues:
1. The verifier silently does network I/O on cache miss — not what the docstring promises ("the cache short-circuits the historical lookup").
2. If a malicious did:web operator can predict the cache state, they could rotate to a key that happens to verify a chosen-prefix signature (a stretch, but the design intent is "snapshot OR fail", not "snapshot OR current").

The existing rotation-survival test (`test_did_web_signature_survives_key_rotation`) pre-seeds the cache, so the cold-cache path is uncovered.

**Fix:** Make the verifier strict — if `sig.did_doc_snapshot_at` is non-None AND the cache misses for `(sig.did, sig.did_doc_snapshot_at)`, fail closed without re-fetching:

```python
# In verifier.py, between resolve and signature check:
if sig.did_doc_snapshot_at is not None and not sig.did.startswith("did:key:"):
    # Snapshot-required path: cache miss means we cannot prove the
    # signing-time key without the snapshot. Fail closed rather than
    # silently fetching the CURRENT (possibly rotated) doc.
    cached = await cache.get((sig.did, sig.did_doc_snapshot_at))
    if cached is None:
        return False
    snapshot = cached
else:
    try:
        snapshot = await resolver(
            sig.did, at=sig.did_doc_snapshot_at,
            cache=cache, http=http, plc_resolver=plc_resolver,
        )
    except Exception:
        return False
```

Add test: `test_verify_cold_cache_for_historical_didweb_fails_closed`.

---

### WR-07: `verify_cmd` ignores http/plc resolver overrides — CLI verify silently hits network

**File:** `src/folio_insights/identity/cli.py:319-335`
**Issue:** `verify_cmd` always builds a fresh `InMemoryDidDocCache` and calls `verify_attestation(shard, sig, cache=cache)` with no `http=` or `plc_resolver=` override. For a did:web signature, the verifier will fall through to `_default_http_get` and attempt a live HTTPS fetch — without any operator opt-in. For an air-gapped or offline operator, this is a surprising network call (and an SSRF vector if the operator was tricked into verifying an attacker-supplied AttestedSignature with `did:web:internal.corp`).

**Fix:** Add `--did-doc` / `--allow-network` flags and refuse the live fetch by default:

```python
@click.option("--did-doc", type=click.Path(exists=True, path_type=Path),
              help="Path to a recorded did.json (offline did:web verify).")
@click.option("--allow-network", is_flag=True, default=False,
              help="Permit live did:web / did:plc resolution. Off by default.")
def verify_cmd(shard_json, signature_json, did_doc, allow_network):
    ...
    if did_doc is not None:
        recorded = json.loads(did_doc.read_text())
        async def http(_url):
            return recorded
    elif allow_network:
        http = None
    else:
        async def http(url):
            raise RuntimeError(
                f"verify needs network for {url} but --allow-network is off"
            )
    ok = asyncio.run(verify_attestation(shard, sig, cache=cache, http=http))
```

---

### WR-08: `_normalize_for_jcs` mis-detects non-datetime strings as ISO datetimes

**File:** `src/folio_insights/revision/content_edit.py:252-266`
**Issue:** The ISO-datetime detector matches any string of length ≥19 whose positions 4/7/10/13/16 are `-`, `-`, `T`, `:`, `:` and that ends with `Z` or has `+`/`-` after position 19. False positives:
* `"2020-01-01T00:00:00 free-text-after"` — passes positional check, fails `fromisoformat`, falls through to NFC. OK.
* `"2020-01-01T00:00:00Z extra"` — positional check passes (ends with... actually `nfc.endswith("Z")` would be False because of " extra"). False positive avoided here.
* `"abcd-ef-ghTij:kl:mn"` — positions match but `fromisoformat` raises. Falls through. OK.

The failures are bounded by `fromisoformat` rejection, but the code does `nfc.replace("Z", "+00:00")` BEFORE attempting `fromisoformat` — so a string like `"2020-Z1-01T00:Z0:00Z"` (an absurd value containing `Z`) would have its inner `Z`s replaced, which could produce a parseable-looking ISO. Low risk but the pre-replace is over-eager.

**Fix:** Tighten the shape check (use a regex anchored to the expected format) and only `replace("Z", "+00:00")` at the END:

```python
import re
_ISO_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)

if _ISO_DT_RE.match(nfc):
    try:
        if nfc.endswith("Z"):
            parsed = datetime.fromisoformat(nfc[:-1] + "+00:00")
        else:
            parsed = datetime.fromisoformat(nfc)
        if parsed.tzinfo is not None:
            return _canonicalize_datetime(parsed)
    except ValueError:
        pass
return nfc
```

---

### WR-09: `_b64url_nopad_encode` / `_b64url_nopad_decode` duplicated across modules

**File:** `src/folio_insights/identity/keys.py:53-61`, `src/folio_insights/identity/signer.py:37-39`, `src/folio_insights/identity/verifier.py:38-41`
**Issue:** The base64url-no-pad helpers are reimplemented identically in three modules. If one implementation drifts (e.g., a Pydantic-versioning-induced bytes/str fix), signer and verifier disagree silently and **every signature stops verifying**. Centralize.

**Fix:** Move the two helpers into a single private module (`src/folio_insights/identity/_b64.py`) and import from there:

```python
# src/folio_insights/identity/_b64.py
import base64

def b64url_nopad_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def b64url_nopad_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)
```

Update keys.py, signer.py, verifier.py to import from `_b64`. Drop the per-module definitions.

## Info

### IN-01: `binding.py` reverse-store F7 check is O(n) and leaks bind state

**File:** `src/folio_insights/identity/binding.py:395-402`
**Issue:** The reverse F7 check iterates all bindings:
```python
for other_sub, rec in binding_store.items():
    if rec.did == did and other_sub != sub:
        raise SubjectChanged(...)
```
This leaks "did X is bound to sub Y" via timing or error-message variance to anyone who can call `bind()`. An attacker who suspects a victim's DID can attempt to bind with a random sub and observe the `SubjectChanged` raise to confirm the DID is bound somewhere.

**Fix:** Maintain a reverse-index `dict[did, sub]` updated atomically with `binding_store`, and a generic-language error message:
```python
if did in did_to_sub_index and did_to_sub_index[did] != sub:
    raise SubjectChanged("Binding rejected by policy.")  # no sub disclosure
```

---

### IN-02: `_SENTINEL_NO_AT = datetime(1970, 1, 1, tzinfo=UTC)` collides with legitimate keys

**File:** `src/folio_insights/identity/resolver.py:351`
**Issue:** Using a real datetime as a "no `at` provided" sentinel means a legitimate cache entry at `signed_at=1970-01-01T00:00:00Z` would collide with the no-`at` snapshot. The collision is astronomically unlikely in practice but the design is fragile.

**Fix:** Either use `None` as the second tuple leg (and update the `DidDocCache` Protocol to accept `tuple[str, datetime | None]`), or use a private sentinel object:
```python
# In cache.py:
class _NoAtSentinel:
    """Marker for 'no signing-time pin provided'."""
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
NO_AT = _NoAtSentinel()
```

---

### IN-03: Unused import: `Field` in `cache.py`

**File:** `src/folio_insights/identity/cache.py:26`
**Issue:** `from pydantic import BaseModel, ConfigDict, Field` — `Field` is used only for `raw_doc: dict | None = Field(default=None)`, which is equivalent to `raw_doc: dict | None = None`. Either keep the explicit `Field` form for clarity or drop the import.

**Fix:** Drop `Field` from the import (`raw_doc: dict | None = None`) or keep as-is and accept the minor verbosity. No correctness impact.

---

### IN-04: CLI sign output parsing in tests is fragile

**File:** `tests/identity/test_did_cli.py:173-179`
**Issue:** `test_did_sign_then_verify_round_trip` extracts the signature JSON by searching for the first `{` in stdout. It works today because the preview text contains no `{`. If a future preview formatter prints (say) `{old} -> {new}` for a content_edit-style action — which `_render_content_edit` already does via `repr` — the test breaks subtly: the first `{` could be in the preview, and JSON parsing fails.

**Fix:** Separate signature output from human-readable preview, e.g. write the JSON to `--out` file:
```python
@click.option("--out", type=click.Path(path_type=Path),
              help="Write the AttestedSignature JSON to this file.")
def sign_cmd(..., out: Path | None) -> None:
    ...
    if out is not None:
        out.write_text(sig.model_dump_json(indent=2))
    else:
        click.echo(sig.model_dump_json(indent=2))
```
Then tests can read `out` directly without parsing stdout.

---

### IN-05: `revision/content_edit.py` accepts `signing_key: Any` instead of `Ed25519PrivateKey | None`

**File:** `src/folio_insights/revision/content_edit.py:328-335, 399-407`
**Issue:** Both `sign_attestation` (the revision-side wrapper) and `edit_shard_content` declare `signing_key: Any`. The downstream signer expects an `Ed25519PrivateKey` and will fail at `private_bytes(...)` call time with an obscure `AttributeError`. Use the precise type so callers get a static-checker error:

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
...
def sign_attestation(
    editor_did: str,
    over_content_hash: str,
    *,
    signing_key: Ed25519PrivateKey | None = None,
    ...
) -> AttestedSignature: ...

async def edit_shard_content(
    ...
    signing_key: Ed25519PrivateKey | None,
    ...
) -> ContentEdit: ...
```

The current `Any` was justified as "Phase-5 frozen seam (D-09)" but Phase 6 wired the real signer through it — the seam is no longer mock-shaped.

---

_Reviewed: 2026-05-28T20:19:34Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---

## Resolution

All 4 Critical + 9 Warning findings fixed in iteration 1 (2026-05-29). Info
findings (IN-01..IN-05) were not in scope for this `--fix` run.

| ID    | Status | Commit  | Notes |
|-------|--------|---------|-------|
| CR-01 | fixed  | 7541cd0 | F7 takeover defense: bind() now enforces signature.did == bound did AND signature.over_content_hash == SHA-256(JCS(proof)). 3 regression tests (signature_did_mismatch, signature_hash_does_not_cover_proof, attacker_cannot_bind_victim_sub_with_own_did). |
| CR-02 | fixed  | 5e3b7b2 | Default did:plc resolver raises UnresolvableDidError when a non-None historical `at` is passed. 2 regression tests (refuses historical at; current-head path still works via monkeypatched atproto). |
| CR-03 | fixed  | 36a5bc7 | Default did:web fetcher enforces https://, follow_redirects=False, and a 1 MiB streaming response cap via httpx AsyncClient.stream(). 3 regression tests (non-HTTPS refused, oversize rejected, in-cap succeeds). |
| CR-04 | fixed  | 8043969 | Removed `from folio_insights.identity.cli import did_group` and the `did_group` export from `identity/__init__.py`. Root cli.py already registers the subgroup directly, so the public CLI surface is unchanged. |
| WR-01 | fixed  | fdac13b | Reordered bind() gates: timestamp (F3 skew) and endpoint pin run BEFORE nonce consume. Updated docstring. 2 regression tests confirm stale / wrong-endpoint proofs do NOT burn the nonce. |
| WR-02 | fixed  | f44ad8d | load_signing_key branches on os.name: POSIX bit-mask enforced on POSIX, warning emitted on Windows (NTFS ACLs are operator responsibility), silent skip elsewhere. 3 tests (POSIX 0o600 OK, POSIX 0o644 rejected, simulated Windows warns). |
| WR-03 | fixed  | b74874f | _assert_sub_is_oauth_sub now rejects plain-alpha 1-15-char subjects without ``:``/``|`` (bare-username F7 form). 2 regression tests (alice refused; github:12345 still accepted). |
| WR-04 | fixed  | 44f510b | _default_plc_resolve wraps the blocking `resolver.did.resolve(did)` call in `asyncio.to_thread` so the event loop is not stalled during PLC fetches. |
| WR-05 | fixed  | fcf9901 | _did_web_url uses urllib.parse.unquote on the domain segment (handles `%3A` ports) and refuses loopback / link-local hosts (localhost, 127.0.0.1, ::1, 0.0.0.0, 169.254.x.x). 5 regression tests. |
| WR-06 | fixed: requires human verification | a30616a | verifier short-circuits to cache-only when `sig.did_doc_snapshot_at` is non-None AND DID is did:web/did:plc: cache miss returns False without consulting http/plc_resolver. Updated 4 existing tests to pre-seed cache; added 2 new cold-cache fail-closed tests. Logic change — please confirm Phase 13 persistence layer's plan to pre-seed the cache at sign time is consistent with this strict path. |
| WR-07 | fixed  | fcb16c3 | `did verify` CLI: added `--did-doc` (offline) and `--allow-network` flags. By default the CLI rejects any did:web/did:plc resolution that would hit the network (raises inside an injected http that always errors). did:key verification still works unconditionally. |
| WR-08 | fixed  | d2f9ba4 | _normalize_for_jcs uses an anchored regex (`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$`) and replaces `Z` only at the END (not via blanket replace). 3 regression tests (malformed lookalike stays string; Z-suffix and +00:00 forms both canonicalize). |
| WR-09 | fixed  | b64d5a4 | Centralized `_b64url_nopad_encode` / `_b64url_nopad_decode` in `src/folio_insights/identity/_b64.py`; keys.py, signer.py, verifier.py import from there. The `_b64.py` underscore prefix keeps it out of the no-server-keys AST contract surface. |
| IN-01..05 | skipped | n/a   | Info findings out of scope per `--fix` scope (critical_warning). |

Final test result: `uv run pytest tests/identity tests/shards tests/revision -q` → 394 passed, 1 warning (pre-existing Pydantic serializer warning unrelated to phase 6).

