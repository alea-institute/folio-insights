---
phase: 6
slug: did-substrate-6-5
title: "Phase 6 — DID Substrate (§6.5) Research"
date: 2026-05-27
status: complete
scope: 6.1 core (P1) — backend + CLI only; 6.2/6.3 + web UI deferred
research_flagged: true
---

# Phase 6: DID Substrate (§6.5) — Research

> **How this was produced:** two long Opus subagent runs dropped their network
> connection mid-research (infra socket drops at ~4.5 min and ~3 min), writing
> nothing to disk. To unblock planning, the orchestrator produced this document
> inline by reading the live seams (`shards/envelope.py`, `revision/content_edit.py`,
> `shards/audit.py`, `services/shacl_validator.py`, `revision/shape_validation.py`,
> `polysemy/reviewer.py`, `pyproject.toml`), `06-CONTEXT.md`, `REQUIREMENTS.md`,
> `research/PITFALLS.md`, and `research/STACK.md`. Findings are grounded in those
> files (cited inline), not recalled.

**Question answered:** *What do I need to know to PLAN Phase 6 well?*

This phase ships the **DID-signed attestation crypto backbone** (backend + CLI). Web
UI, hardware-key (6.2/DID-08), and multi-sig (6.3/DID-09) are deferred per
`06-CONTEXT.md` D-01/D-02. In-phase REQ-IDs: **DID-01, DID-02, DID-03, DID-04,
DID-06, DID-07, SEC-05, SEC-06**, plus the **CLI portion of DID-05** (web flow defers).

---

## 0. TL;DR for the Planner

1. **New `src/folio_insights/identity/` package.** Crypto + atproto + jcs live here,
   NOT in `shards/` (the `tests/shards/test_dep_leak_guard.py` boundary that forced
   Phase 5's `revision/` package applies identically). Suggested module split in §7.
2. **Add 6 dependencies** (needs operator sign-off — see §1). Only `cryptography>=41`
   + `base58>=2.1` exist today (Phase 1 did:key spike). Add `PyNaCl==1.6.2`,
   `atproto==0.0.65`, `dag-cbor==0.3.3`, `jcs==0.2.1`, `joserfc==1.6.4`,
   `authlib==1.7.0` (authlib is for the binding-proof/OAuth-`sub` contract; the web
   OAuth *flow* defers, but the CLI binding model references `sub` semantics).
3. **JCS swap is a one-line seam BUT the pre-normalization is the hard part** (F4,
   BLOCKING). Keep `canonical_content_hash()` in `revision/content_edit.py` (the D-12
   seam); replace the `json.dumps` line with an NFC + canonical-datetime + JCS recipe
   (§2). Prove it with the 1000-shuffled-order property test **and** a ~50-input
   cross-impl golden test vs cyberphone/json-canonicalization.
4. **`AttestedSignature` reshape touches 4+ construction sites** and has a real
   **`action`-Literal conflict** with the existing `action="content_edit"` calls — the
   planner must reconcile it (§9). This is one breaking reshape; do it once.
5. **Rotation-survival differs per method** (§3): did:key is trivial (key ∈ DID),
   did:web needs a snapshotted did.json, did:plc needs op-log pinning. The
   `DidDocCache` seam (in-memory now, Phase 13 persistence) is what makes EC3 provable.
6. **DID-06 (no server keys) is a contract test, not a feature.** The signer takes a
   key parameter; the security-contract test asserts no code path persists a private
   key (§6).
7. **Recommend deferring a SHACL attestation shape to Phase 11** — Phase 6's honest
   verification gate is cryptographic `verify(sign(x))` + Pydantic `extra="forbid"`,
   not SHACL. Don't fake structural verification (§10).

---

## 1. Dependencies (operator sign-off required)

`pyproject.toml` today (lines 6–27) carries the identity-relevant libs:
```
"cryptography>=41",   # A1: ed25519 did:key (Phase 1 spike)
"base58>=2.1",        # A2: did:key z-multibase
"pyshacl>=0.31.0", "rdflib>=7.6.0", "aiosqlite>=0.20.0", "click>=8.0.0", ...
```

**Must add (locked by STACK.md §6.5 / RISK-4 — do NOT re-litigate):**

| Package | Pin (STACK.md) | Why this phase needs it |
|---------|----------------|--------------------------|
| `PyNaCl` | `1.6.2` | Fast libsodium ed25519 sign/verify hot path (~6× `cryptography`). STACK L47. |
| `jcs` | `0.2.1` | RFC 8785 canonicalization of the content hash (DID-03/D-12). STACK L51. |
| `atproto` | `0.0.65` | did:plc resolver: `IdResolver().did.resolve(did)` + PLC op-log (DID-01/D-08). STACK L49. |
| `dag-cbor` | `0.3.3` | DAG-CBOR decode of did:plc operations for historical-key pinning. STACK L50. |
| `joserfc` | `1.6.4` | JWS wrapping if/when attestations export as VCs; replaces python-jose. STACK L48. |
| `authlib` | `1.7.0` | OAuth `sub`-claim semantics for the binding contract (DID-05/SEC-06). STACK L62. |

- `cryptography` is pinned loosely (`>=41`); STACK wants `46.0.7`. Recommend bumping to
  `>=46` for the did:web verify path; planner confirms no other consumer breaks.
- **Deliberately rejected** (STACK L53–56, L279–283): `didkit`, `pydid`, `python-jose`,
  `py-ed25519-bindings`, `fastapi-users`. The dep manifest should make rejection visible
  (DID-01 acceptance: "explicit rejection of didkit/pydid/python-jose/fastapi-users").
- `itsdangerous`/`structlog`/Redis nonce-store are **web/server-phase** concerns —
  defer with the web UI; the CLI binding uses an in-memory/seam nonce store (§5).

> **ACTION FOR PLANNER:** the dependency-add task should be `autonomous: false` (or
> flagged) — adding pip deps requires operator approval per project policy.

---

## 2. JCS Canonicalization Recipe (DID-03 / D-12 / Pitfall F4 — BLOCKING)

The seam is one line. `revision/content_edit.py:200`:
```python
canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
return hashlib.sha256(canon.encode("utf-8")).hexdigest()
```
The exclusion set (`_HASH_EXCLUDED_FIELDS`, L161) and signature stay **unchanged**
(D-12 seam): `transaction_time, valid_time_start, valid_time_end, content_edits,
signatures`.

**Why a naive swap fails (F4, PITFALLS #5/#4).** `model_dump()` is *non-canonical*:
datetimes vary (`...Z` vs `+00:00`, precision), floats serialize at full precision (not
IEEE-754 minimal), `None` inclusion is ambiguous, and Unicode is not NFC-normalized
(smart quotes / em-dash / NBSP in `sense`/`reference`/`source_span` hash differently
signer vs verifier). `jcs.canonicalize()` fixes *number* and *key-ordering*
determinism but does **not** NFC-normalize strings or fix datetime string format —
those are the caller's job.

**Recommended recipe** — a single `shard_canonical_bytes(shard) -> bytes` helper kept
in `revision/` (jcs import is allowed there; `shards/` stays crypto/RDF-free):

1. `payload = shard.model_dump(mode="json", exclude=_HASH_EXCLUDED_FIELDS)`
   — `mode="json"` already renders enums/Literals → str and datetimes → ISO strings,
   floats stay native floats (jcs will minimal-encode them).
2. **Pin datetime format.** `mode="json"` datetime output is not guaranteed canonical
   across Pydantic versions. Add a `@field_serializer` (or model serializer) that emits
   **RFC-3339 UTC, `Z` suffix, fixed precision** (recommend microseconds dropped to a
   stable form, or always-6-digit) for every `datetime` that survives the exclusion set
   (`extracted_at`, and any subtype/datetime fields). Decide one representation and lock
   it — the golden test (below) is what proves it.
3. **NFC-normalize recursively.** Walk the dict; `unicodedata.normalize("NFC", s)` on
   every string **key and value**. RFC 8785 does not normalize Unicode; this must
   happen before `jcs.canonicalize`.
4. **Explicit None policy.** Pick one and lock it: either `exclude_none=False` (keep
   `null`s — jcs serializes them deterministically) OR strip None recursively. PITFALLS
   #4 recommends *stripping* to avoid ambiguity; either is fine if signer == verifier.
   Recommend **keep** (don't strip) — stripping loses the distinction between "absent"
   and "explicitly null" for Optional bitemporal-adjacent fields. Lock it, test it.
5. `return jcs.canonicalize(normalized_payload)` (returns `bytes`).
   Then `hashlib.sha256(<bytes>).hexdigest()`.

`jcs.canonicalize` sorts keys by UTF-16 code units and minimal-encodes numbers per
RFC 8785 — so drop the manual `sort_keys`/`separators`.

**Floats:** `confidence: float` (envelope L188) is the live float field. jcs emits
shortest round-trip (`0.1`→`"0.1"`, `1.0`→`"1"`). Deterministic as long as both sides
pass a native float, not a pre-stringified one. Don't `str()` floats before jcs.

**Tests (this is the discipline that proves F4 is closed):**
- **Property test** (`hypothesis`, already a dev dep; Phase 2/4 idiom): build 1000
  random shards, shuffle field-insertion order / dict key order, assert
  `verify(sign(x))` holds and `canonical_content_hash` is order-independent. (EC2 — the
  in-phase gate.)
- **Cross-impl golden test:** ~50 hand-picked inputs (Unicode edge cases: NBSP, em-dash,
  combining accents, emoji; floats: 0.0, 1.0, 1e-7, negative; nested dicts; null) →
  compare our `shard_canonical_bytes` output against the reference vectors from
  [cyberphone/json-canonicalization](https://github.com/cyberphone/json-canonicalization)
  test data. Store fixtures under `tests/identity/fixtures/jcs_golden/`.

---

## 3. Signing-Time Key Capture & Historical-Key Resolution (DID-04 / SEC-05 / F2)

Every `AttestedSignature` records `signing_key_id` (DID URL + `#keyfragment`) and
`did_doc_snapshot_at` (D-13). Verification resolves the key **as of `signed_at`**, not
the DID's current key (F2). Resolution differs per method:

| Method | Resolve current | Historical key at `signed_at` | Rotation risk |
|--------|-----------------|-------------------------------|---------------|
| **did:key** | Decode the multibase key embedded in the DID (Phase 1 `reviewer.py` L49-51 pattern: `did:key:z` + base58btc(`0xed01` ‖ raw_pub)). | **Trivial** — the key *is* the DID; it cannot rotate (a new key = a new DID). `signing_key_id` = `<did>#<fragment>`; snapshot is a no-op. | None. |
| **did:web** | `GET https://<domain>/.well-known/did.json` (or path form `…/<path>/did.json`); read `verificationMethod`. | **Snapshot the did.json at signing time** into `DidDocCache` keyed by `(did, signed_at)`; verify against the snapshot, never a live re-fetch. | High — operator rotates by editing did.json. Snapshot is mandatory. |
| **did:plc** | `atproto.IdResolver().did.resolve(did)` → DID doc with signing key (STACK L49). | **Pin from the PLC op log:** `GET https://plc.directory/<did>/log/audit` returns the ordered, timestamped operation log; DAG-CBOR-decode (`dag-cbor`) and select the key valid at `signed_at`. **Resolve/verify only — NO genesis/rotation writes** (D-08). | High (highest-churn) — that's why writes defer (Pitfall F2). |

**`DidDocCache` (D-11) — the seam that makes EC3 provable.** Mirror Phase 5's
`ShardStore` (in-memory `dict` behind a `Protocol`/ABC, async interface; see
`revision/store.py`). Key = `(did, signed_at)` → cached did.json / PLC op snapshot +
key fingerprint. In-memory now; **Phase 13 swaps aiosqlite/Oxigraph behind the identical
interface**. Keeps storage libs out of `identity/` (same dep-discipline as Phase 5).

**`test_signature_survives_key_rotation.py` (EC3 / SEC-05):** sign with key A → record
`signing_key_id`/`did_doc_snapshot_at` → simulate rotation to key B (mutate the
resolver's "current" doc / cache a new snapshot) → assert the **historical** verify
still passes against the snapshot, and a *naive current-key* verify would fail. Do this
for **did:key (degenerate) + did:web (real rotation)**; did:plc gets resolve/verify
coverage via a recorded op-log fixture.

---

## 4. did:web Proof-of-Control (SEC-06)

For did:web, binding requires **domain-control proof**: the binder must serve a
`/.well-known/did.json` (or the path-scoped `did.json`) containing the bound
verificationMethod under the claimed domain. Mechanics:
- Resolve `did:web:example.org` → `https://example.org/.well-known/did.json`;
  `did:web:example.org:user:alice` → `https://example.org/user/alice/did.json`.
- Proof-of-control = the did.json is reachable over HTTPS at the derived URL AND lists
  the public key whose private half signs the binding proof (§5). For Phase 6 CLI this
  is an `httpx` GET + key-match check; DNS-TXT is an optional secondary signal.
- **Cache** the fetched did.json in `DidDocCache` (TTL + snapshot-at-signing). A live
  re-fetch on every verify is both slow and rotation-unsafe.
- Use `cryptography` for the verify of arbitrary keys; `PyNaCl` for ed25519 hot path.

---

## 5. OAuth→DID Binding CLI (DID-05 CLI portion / SEC-06 / Pitfall F3, F7)

`folio-insights did bind` creates the binding record and **locks the defense rules** so
the deferred web flow only renders the same contract (D-10). The web OAuth *flow* and
Redis nonce store defer; the CLI ships the **data model + rules + an in-memory/seam
nonce store**.

**Binding record (Pydantic, `extra="forbid"`):** `(oauth_sub, did, bound_at,
proof_signature, binding_endpoint, nonce_id)`. **Bind to the immutable OAuth `sub`
claim — never `email`/username** (F7; PITFALLS table "use `sub` never `email`").

**Proof-of-control payload (signed by the DID's private key):** MUST carry
1. OAuth `sub` (or session id), 2. **server-issued single-use nonce, 5-min TTL**,
3. **timestamp within ±2 min** of server clock, 4. **binding-endpoint URL** (F3).
Nonce store: atomic get-delete on use (Redis `GETDEL` in the web phase; an in-memory
`dict` + TTL behind a `NonceStore` protocol/seam now). Replay → "nonce already consumed".

**Subject-change detection (F7):** if a later bind sees the same `did` under a *different*
`sub`, the old binding is unbound and re-binding via fresh signed proof is required.
Surface a warning ("your OAuth subject changed…").

**Idempotency:** a second bind for the same `(sub, did)` pair is a **no-op or explicit
conflict — never a silent update**.

**did:web** binding additionally requires the §4 domain-control proof.

> Phase 19 audits SEC-06 end-to-end; Phase 6 locks the data model + rules on the critical
> path. Do not build the web OAuth flow or PKCE/state here — only the binding contract
> the CLI exercises and the web phase will reuse.

---

## 6. No-Server-Side-Keys Invariant (DID-06 / D-07 / D-09)

DID-06 is **absolute** and is enforced as a *contract test*, not a feature:

- The CLI signer loads an `Ed25519PrivateKey` from the **local keyfile** extending Phase
  1's pattern (`polysemy/reviewer.py`: `~/.folio-insights/reviewer.jwk` mode `0600`,
  dir `0700`, `reviewer.did` cache, JWK persistence; `Path.home()`). Phase 6 adds
  `did generate`/`did sign` reuse of this keystore.
- `edit_shard_content(..., signing_key, store)` (the **frozen Phase 5 call site**,
  `content_edit.py:244-279`) gets the real signer wired through `signing_key` — which is
  the locally-loaded private key, supplied by the CLI. The signature functions **accept**
  a key and **never persist** one.
- **Security-contract test (EC4):** assert no code path under `identity/` (or anywhere
  server-reachable) writes/serializes a private key — e.g. a test that (a) greps the
  package for private-key serialization (`private_bytes`, JWK `"d"` writes) and confines
  them to the *local keystore* module, and (b) asserts the signer/verifier/binding APIs
  take public material + a key *parameter* only. Browser WebCrypto signing (server
  computes hash, browser signs, posts signature back) is the deferred web seam — note it,
  don't build it.

---

## 7. Recommended `identity/` Package Layout (Claude's Discretion — planner finalizes)

```
src/folio_insights/identity/
  __init__.py        # curated public exports (sign_attestation, verify_attestation, resolve_did, DidDocCache, BindingRecord)
  keys.py            # local keystore: ed25519 gen/load, JWK<->raw, did:key derivation (extends polysemy/reviewer.py)
  resolver.py        # resolve_did(did, at: datetime|None): did:key decode | did:web httpx+cache | did:plc atproto+op-log
  cache.py           # DidDocCache Protocol/ABC + InMemoryDidDocCache keyed by (did, signed_at) — mirrors revision/store.py
  signer.py          # sign_attestation(content_hash, key, did, action, ...) -> AttestedSignature (real ed25519)
  verifier.py        # verify_attestation(shard, sig) -> bool ; resolves signing-time key via resolver+cache
  binding.py         # BindingRecord + ProofPayload models; NonceStore protocol + InMemoryNonceStore; bind() rules (§5)
  cli.py             # `did` Click subgroup: generate / bind / sign / verify / preview (the polysemy/cli.py group idiom)
```
- **JCS canonicalization stays in `revision/content_edit.py`** (the D-12 seam — "swap
  into the single line"; `revision/` already allows non-`shards` deps). `identity/`
  imports `canonical_content_hash` from `revision/`. Dep direction:
  `identity/ → revision/ → shards/` (clean; no cycle).
- **`AttestedSignature` stays in `shards/envelope.py`** (it's pure Pydantic — see §9).
  `identity/` constructs and verifies it but does not move it (that would re-break the
  envelope's `signatures: list[AttestedSignature]` field and the dep-leak guard).
- Wire the CLI subgroup into `cli.py` via `cli.add_command(did_group)` (the
  `@click.group()` pattern at `cli.py:32`).

---

## 8. CLI Surface (DID-05/DID-07 CLI form; polysemy idiom)

Mirror `polysemy detect/review/audit` (a Click subgroup with rich prompts):
- `did generate --method=key` — generate + persist ed25519 keypair → print did:key.
- `did bind` — create the OAuth-`sub`→DID binding with the §5 proof-of-control.
- `did sign --action <one-of-8> --shard <iri>` — compute canonical hash, **show the
  DID-07 preview first** (hash + human-readable diff), then sign.
- `did verify <shard|attestation>` — resolve signing-time key, verify; print verdict.
- `did preview --action <type> --shard <iri>` (or `did sign --dry-run`) — the DID-07
  "what will I be signing?" preview for **all 8 signed-action types** (EC5). CLI/API
  form only; the styled web preview defers.

---

## 9. `AttestedSignature` Reshape (D-13) — Touch-Point Map + the `action` Conflict

Current stub (`shards/envelope.py:49-66`): `extra="allow"`; fields `did, action: str,
signed_at, signature, over_content_hash`.

**Target 6.1 shape (D-13):**
- `model_config = ConfigDict(extra="forbid")` (tighten — the stub anticipated this).
- Add `signing_key_id: str` (DID URL + `#fragment`), `did_doc_snapshot_at: datetime`,
  `verified: bool | None = None` (cache annotation, None until verification runs).
- Reserve `cosigners: list[...] = Field(default_factory=list)` (present-but-empty for
  deferred 6.3 — so multi-sig adds behavior without a second breaking reshape).
- Keep `did`, `signed_at`, `signature`, `over_content_hash`, and turn **`action` into
  the 8-value Literal**.

**⚠ BLOCKING reconciliation the planner must resolve — the `action` Literal vs
`action="content_edit"`:** DID-02 lists **8** signed actions — `extract, promote, demote,
contest, supersede, retract, distinguo, role-assertion`. But the live Phase-5 code
constructs `AttestedSignature(action="content_edit", …)` in **two** places:
- `revision/content_edit.py:215` (`sign_attestation`), and
- `shards/audit.py:127` (`add_edit`).

`"content_edit"` is **not** one of the 8. With `action` as an 8-value Literal +
`extra="forbid"`, those calls **fail to construct**. The planner must pick one and apply
it everywhere:
- **(A)** Treat a content edit as a 9th action value (`action` Literal = the 8 + an edit
  value). Simplest; but DID-07 says "all **8** signed-action types", so a 9th muddies EC5.
- **(B)** Map the edit path to one of the 8 (the audited edit is itself a write action) —
  e.g. content edits sign under the most specific governance action and the `field_path`
  carries the "what". Cleanest against DID-07 but needs a mapping decision.
- **(C)** Give the edit path its own non-Literal lane (a separate signature shape or an
  `action` union) — most code, least recommended.
- **Recommend (A or B);** decide in planning, not execution.

**Required-vs-defaulted fields under `extra="forbid"`:** if `signing_key_id` /
`did_doc_snapshot_at` are **required**, EVERY construction site must supply them. The
unsigned `add_edit` convenience wrapper (`audit.py`) currently ships an empty stub — it
must either (a) get sensible defaults (`signing_key_id: str = ""`,
`did_doc_snapshot_at: datetime | None = None`), or (b) be updated to real-sign / be
deprecated. Recommend **Optional with defaults** so the sync wrapper still constructs an
honestly-unsigned record (`signature=""`, `verified=None`) while the real
`edit_shard_content` path produces a fully-populated signed one.

**Full construction-site touch-list (the "one breaking reshape"):**
1. `shards/envelope.py:49` — the class definition (the reshape itself).
2. `revision/content_edit.py:207-221` — `sign_attestation` (fill real ed25519 + new fields).
3. `revision/content_edit.py:304-312` — `edit_shard_content` builds the `ContentEdit`
   whose `.signature` is the attestation (now real, via the wired `signing_key`).
4. `shards/audit.py:119-134` — `add_edit`'s inline `AttestedSignature(...)` stub.
5. Test builders/fixtures: `tests/shards/conftest.py`, `tests/shards/fixtures/`,
   `tests/revision/conftest.py`, and any test constructing `AttestedSignature` or a
   `ContentEdit` (grep `AttestedSignature(` and `ContentEdit(` across `tests/`).
6. `tests/shards/test_envelope_roundtrip.py` — round-trip must tolerate the new shape;
   `extra="forbid"` will now reject unknown keys (the stub's `extra="allow"` masked this).

`AttestedSignature` **stays pure-Pydantic** (no crypto import in `envelope.py`) so the
`shards/` dep-leak guard (`tests/shards/test_dep_leak_guard.py`) stays green. The signing
*logic* lives in `identity/`, which imports the model.

---

## 10. Focused SHACL Attestation Shape — Recommend DEFER to Phase 11

CONTEXT lists this under Claude's Discretion ("keep it honest, don't fake verification").

**Recommendation: do NOT ship a SHACL attestation shape in Phase 6.** The honest Phase-6
verification gate is **cryptographic** (`verify(sign(x))`) + **Pydantic** (`extra="forbid"`
+ the 8-value Literal already enforce structure). A SHACL shape over the attestation would
either duplicate what Pydantic enforces or assert presence-of-fields that the schema
already guarantees — i.e. ceremony, not verification. The pattern (`revision/
shape_validation.py` `validate_content_edit_shape` + `_build_edit_graph`) is available to
mirror **if** Phase 11's full `fi:SignedActionShape` verification-at-ingest suite needs
it; ship it there, over the RDF ingest path, where it adds real defense-in-depth. The
`cosigners[]` N-of-M shape is explicitly **6.3-deferred**. Flag this recommendation for
the operator; if they want a token shape now, scope it to a single sh:sparql assertion
(e.g. `over_content_hash` non-empty ⇒ `signature` non-empty) and label it defense-in-depth.

---

## 11. Pitfall Ledger (research/PITFALLS.md → Phase 6 actions)

| Pitfall | Severity | Phase-6 action |
|---------|----------|----------------|
| **F4** JCS on `model_dump()` non-determinism | **BLOCKING** | §2 recipe: NFC + canonical datetime + locked None policy + jcs; 1000-shard property test + ~50-input cross-impl golden test. |
| **F2** rotation breaks historical sigs | HIGH | §3 signing-time capture + `DidDocCache` snapshot + op-log pinning; `test_signature_survives_key_rotation.py` (did:key+did:web). |
| **F3** OAuth→DID binding replay | HIGH | §5 nonce(5-min,single-use)+timestamp(±2min)+endpoint-URL in signed proof; replay → "nonce consumed". CLI seam now; Redis in web phase. |
| **F7** GitHub username takeover | HIGH | §5 bind to immutable `sub`; subject-change detection + re-bind. |
| **F6** corpus-admin role lockout | (noted) | **Phase 7** governance — out of scope here; do not lose it. |

---

## Validation Architecture

*(Nyquist — observable signals + minimum sampling that proves each acceptance criterion.
This section seeds `06-VALIDATION.md`.)*

| Acceptance criterion (CONTEXT amended bar) | Observable signal | Minimum sampling strategy | Test artifact |
|--------------------------------------------|-------------------|---------------------------|---------------|
| **EC2** JCS order-independence | `verify(sign(x))` true under shuffled field/key order; `canonical_content_hash` equal across shuffles | `hypothesis` property test, **1000 random shards**, randomized dict/insertion order + Unicode-noise transform | `tests/identity/test_canonical_jcs_properties.py` |
| **JCS cross-impl correctness** (F4 discipline) | our `shard_canonical_bytes` == reference canonical bytes | **~50 golden inputs** (Unicode/float/null/nesting edges) vs cyberphone/json-canonicalization vectors | `tests/identity/fixtures/jcs_golden/` + `test_jcs_golden.py` |
| **EC3 / SEC-05** rotation survival | historical verify passes against signing-time snapshot; naive current-key verify fails | did:key (degenerate) + did:web (real rotation) + did:plc (recorded op-log fixture); sign→rotate→verify | `tests/identity/test_signature_survives_key_rotation.py` |
| **EC4 / DID-06** no server keys | no code path persists a private key server-side; APIs take key as param | static contract test (grep private-key serialization, confine to local keystore) + signer/verifier signature audit | `tests/identity/test_no_server_keys_contract.py` |
| **`pytest tests/identity/` green** across methods | full sign/verify did:key + did:web; resolve/verify did:plc | one happy-path + edge test per method; did:plc uses recorded resolver fixtures (no live network) | `tests/identity/test_sign_verify_didkey.py`, `_didweb.py`, `_didplc_resolve.py` |
| **EC5 / DID-07** preview | canonical hash + human-readable diff renders for **all 8** signed-action types | parametrized over the 8 `action` Literals; assert hash + diff present (CLI/API form) | `tests/identity/test_signing_preview.py` |
| **SEC-06 / F3** binding replay defense | replayed proof (stale nonce / >±2 min / reused) is rejected | replay 6 min later → "nonce already consumed"; subject-change → re-bind required; idempotent re-bind | `tests/identity/test_binding_proof.py` |
| **DID-02** every write action signs | each of the 8 actions yields an `AttestedSignature` with populated `signing_key_id`/`did_doc_snapshot_at` | parametrized over 8 actions; assert non-empty signature + key id | `tests/identity/test_attested_signature_shape.py` |

**Why this sampling is sufficient (Nyquist):** the JCS property test at n=1000 with
randomized order + Unicode noise is the highest-frequency failure surface (F4) and is
sampled densely; the cross-impl golden test pins the *absolute* canonical form (property
tests prove internal consistency, golden tests prove external correctness — both are
required). Rotation, no-server-key, and replay each have a single decisive observable, so
one targeted test per method/branch saturates them. The 8-action preview and 8-action
signing are exhaustively parametrized (the population is finite = 8).

---

## Open Questions for the Planner (decide in plan, not execution)

1. **`action` Literal reconciliation** (§9) — option (A) 9th value, (B) map edits to one
   of 8, or (C) separate lane. **Recommend A or B.**
2. **Required vs Optional** for `signing_key_id`/`did_doc_snapshot_at` (§9) —
   **recommend Optional+defaults** so the unsigned `add_edit` path stays honest.
3. **None policy in JCS** (§2 step 4) — keep vs strip. **Recommend keep**; lock + test.
4. **did:plc op-log access** — `atproto` client method vs direct `httpx` GET to
   `plc.directory/<did>/log/audit` + `dag-cbor` decode. Validate which `atproto==0.0.65`
   exposes; fall back to httpx+dag-cbor if the client lacks a historical accessor.
5. **SHACL shape** (§10) — **recommend defer to Phase 11**; confirm with operator.
6. **`cryptography` bump** to `>=46` — confirm no consumer regression.
