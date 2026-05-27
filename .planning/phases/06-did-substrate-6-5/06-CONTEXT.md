# Phase 6: DID Substrate (§6.5) - Context

**Gathered:** 2026-05-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship the **DID-signed attestation crypto backbone** (REQ **DID-01..DID-07**, **SEC-05**,
**SEC-06**) as the security substrate every later write action signs against. PRD §6.5 /
§21.10 = "every reviewer action is cryptographically signed by the reviewer's DID;
downstream systems weigh as they see fit."

This phase was **deliberately scoped down to the critical-path backend + CLI** (see D-01).
The web UI, the P2 stretch sub-phases, and did:plc write-side onboarding all travel
forward to later phases (see `<deferred>`). What Phase 6 delivers:

1. **JCS canonical content hash** — swap RFC-8785 `jcs.canonicalize()` into the Phase 5
   `canonical_content_hash()` seam; order-independent over `model_dump(exclude={"signatures",
   "content_edits"})` (DID-03).
2. **Sign + verify for did:key and did:web** at full fidelity, incl. signing-time key
   capture + historical-key resolution so signatures survive key rotation (DID-02, DID-04,
   SEC-05). **did:plc resolve + verify only** (no genesis/rotation writes — D-08).
3. **No server-resident signing keys, ever** — signing happens with a CLI local keyfile
   (extends the Phase 1 `~/.folio-insights` ed25519 pattern). Browser-side signing defers
   with the web UI (DID-06, D-07).
4. **`folio-insights did bind` CLI** locking SEC-06 / OAuth-binding defense rules
   (bind to immutable OAuth `sub`; signed proof-of-control with single-use nonce; subject-
   change detection) — the deferred web flow renders this same contract (DID-05, SEC-06).
5. **`AttestedSignature` reshaped** from the Phase 5 permissive stub to the real 6.1
   schema (D-13).
6. **CLI/API "what will I be signing?" preview** — canonical hash + human-readable diff
   for all 8 signed-action types (DID-07, CLI/API form only; styled web preview defers).

**Acceptance bar for THIS phase (amended from ROADMAP's original 5 exit criteria — D-12):**
- **STAYS:**
  - `verify(sign(x))` JCS property test green across **1000 shuffled-field-order** shards (orig EC2).
  - `test_signature_survives_key_rotation.py` green for **did:key + did:web** historical keys (orig EC3, SEC-05).
  - Security-contract check: **no signing key is ever server-resident** for any DID (orig EC4, DID-06).
  - `pytest tests/identity/` green — did:key + did:web full sign/verify; **did:plc resolve/verify**.
  - Preview (CLI/API form) renders canonical hash + diff for **all 8 signed-action types** (orig EC5, DID-07).
- **TRAVELS FORWARD (explicitly NOT Phase 6):**
  - Playwright OAuth→DID binding across 3 paths + styled preview screenshot test → post-Phase-14 web phase.
  - WebAuthn virtual-authenticator E2E (6.2) + N-of-M multi-sig (6.3) → deferred P2 phase.
  - did:plc genesis + operation-log rotation **writes** → AT-Proto-onboarding phase.

**NOT in scope (carried to other phases):**
- Hardware-key signing (Ledger / YubiKey / WebAuthn) — **6.2 (P2)**, deferred phase. DID-08.
- Multi-signature N-of-M co-sign (schema + SHACL + UI) — **6.3 (P2)**, deferred phase. DID-09.
  (The `cosigners[]` schema slot IS reserved now — D-13 — so 6.3 doesn't re-break the schema.)
- The **web** OAuth→DID binding flow + styled signing-preview component + browser WebCrypto
  signing — **post-Phase-14** (after the design contract). DID-05/DID-07 web surfaces.
- **did:plc genesis/rotation writes** to the PLC directory — AT-Proto-onboarding phase.
- Persistent storage for the historical-key cache (real aiosqlite/Oxigraph) — **Phase 13**
  fills the `DidDocCache` seam shipped here (D-11).
- The governance log / promotion / contest workflow that *consumes* these signatures —
  **Phase 7**. Phase 6 ships the signing+verify primitives; Phase 7 wires authorization.
- Full SHACL `fi:SignedActionShape` verification-at-ingest shape suite — **Phase 11**
  (Phase 6 may ship the one focused attestation shape it needs, mirroring Phase 5's pattern).
</domain>

<decisions>
## Implementation Decisions

### Scope & Phase Shape
- **D-01:** **Ship 6.1 core (P1) only; defer 6.2 hardware-key + 6.3 multi-sig** to their own
  later phase (e.g. a decimal 6.x or v2.1). 6.1 is on the critical path and unlocks Phase 7
  (governance) + Phase 12 (observability); the two P2 sub-phases are self-contained and would
  roughly double a phase that's already research-flagged.
- **D-02:** **Web UI defers to a post-Phase-14 surface.** OAuth→DID binding *flow* and the
  *styled* "what will I be signing?" preview need the design system (Phase 14) and adapter-node
  (the viewer is back to adapter-static SPA per Phase 3.5). Building them now is throwaway work.
  Phase 6 ships the **backend substrate + CLI + binding/preview API contracts** so the deferred
  web phase only renders them.

### DID Methods & Depth
- **D-08:** **did:key + did:web full fidelity; did:plc resolve/verify only.** did:key and
  did:web get full sign / verify / rotation-survival. did:plc gets resolve + verify of *existing*
  DIDs (via `atproto` IdResolver + operation-log pinning for historical-key lookup at `signed_at`),
  but **did:plc genesis + rotation *writes* defer** — they're the heaviest path and highest-churn
  rotation case (Pitfall F2), and most reviewers are did:web (institutional) or did:key (individual).
  All 3 methods stay verifiable; only the plc write path is trimmed.

### Key Custody (DID-06 — no server keys, ever)
- **D-07:** **CLI local-keyfile signing now**, extending the Phase 1 `~/.folio-insights`
  ed25519 pattern (0600/0700, key outside the repo). This is client-side by construction
  (the operator's machine, not the server). **Browser WebCrypto signing defers with the web
  UI** (D-02): when it lands, the server computes the canonical hash, the browser signs, and
  posts the signature back — the server never sees a private key. DID-06 holds for both surfaces.
- **D-09:** The Phase 5 frozen call-site `edit_shard_content(..., signing_key)` contract
  (D-01 of Phase 5) is honored. For the CLI path, `signing_key` is the locally-loaded
  `Ed25519PrivateKey`; the **no-key-at-rest-on-server** rule is the audited invariant
  (a security-contract test asserts no code path persists a private key server-side).

### SEC-06 / OAuth-Binding Defense
- **D-10:** **`folio-insights did bind` CLI ships now**, creating the binding record and
  locking the defense rules so the deferred web flow just renders the same contract:
  - **Bind to the immutable OAuth `sub` claim**, never `email` or username (F7 — GitHub
    username-takeover defense; SEC-06).
  - **Signed proof-of-control** payload carries a server-issued **single-use nonce** (5-min
    TTL) + timestamp within ±2 min + binding-endpoint URL (F3 — replay defense).
  - **Subject-change detection**: re-binding required (old DID unbound) if the OAuth `sub`
    changes (F7). For did:web, binding requires DNS / `.well-known` proof of domain control.
  - Idempotency: a second bind for the same `(sub, DID)` pair is a no-op / explicit conflict,
    never a silent update.
  Phase 19 audits SEC-06 end-to-end; this phase locks its data model + rules on the critical path.

### Historical-Key Cache (DID-04 / SEC-05 / Pitfall F2)
- **D-11:** **In-memory `DidDocCache` seam now; Phase 13 fills persistence.** Mirror Phase 5's
  `ShardStore` decision (D-02): a thin protocol/ABC over an in-memory dict keyed by `(did,
  signed_at)`, caching the did.json (or PLC op) current at signing + key fingerprints. Enough
  to prove rotation-survival (EC3) and lock the interface; Phase 13 swaps in real aiosqlite/
  Oxigraph-backed storage behind the identical interface. Keeps storage libs out of the new
  `identity/` package (same dep-discipline that forced Phase 5's `revision/` boundary).
- Every `AttestedSignature` records **`signing_key_id`** (DID URL + `#keyfragment`) +
  **`did_doc_snapshot_at`** so verification resolves the *signing-time* key, not the DID's
  current key (DID-04). Verification is cached as a **`verified`** annotation (D-13).

### Canonical Content Hash (DID-03 / Pitfall F4)
- **D-12 (also the acceptance-bar amendment — see `<domain>`):** Swap **`jcs.canonicalize()`
  (RFC 8785)** into the single Phase 5 `canonical_content_hash` `json.dumps` line, over
  `model_dump(exclude={"signatures", "content_edits"})`. Pitfall F4 is BLOCKING — do **not**
  hash raw `model_dump()`: enforce NFC on string fields, RFC-3339-UTC datetimes, IEEE-754
  minimal floats, explicit None handling, *then* JCS. Researcher/planner own the exact recipe;
  a **cross-implementation golden test** (vs. the cyberphone/json-canonicalization reference on
  ~50 inputs) is the discipline that proves it. The `verify(sign(x))`-across-shuffled-orders
  property test (1000 shards) is the in-phase gate.

### AttestedSignature Schema Reshape
- **D-13:** **Replace** the Phase 5 permissive stub (`extra="allow"`) with the real 6.1 shape:
  - `model_config = ConfigDict(extra="forbid")` (tighten now — Phase 5 stub explicitly anticipated this).
  - Add **`signing_key_id`** (DID URL + `#keyfragment`), **`did_doc_snapshot_at`** (datetime),
    **`verified`** (Optional bool — cache annotation, None until verification runs).
  - **Reserve `cosigners: list[...] = Field(default_factory=list)`** for the deferred 6.3
    multi-sig — present-but-empty now so 6.3 adds behavior without a second breaking reshape.
  - Keep the existing `did` / `action` (8-value Literal) / `signed_at` / `signature` /
    `over_content_hash` fields. This is **one** breaking reshape; touch points are every
    construction site (the Phase 5 `sign_attestation` stub, `content_edit.py`, test builders).

### Claude's Discretion (researcher / planner own these — phase is research-flagged)
- The new package layout (PRD/research imply a `src/folio_insights/identity/` package for the
  signer/verifier/resolver + `DidDocCache` + binding logic, keeping crypto/storage deps out of
  `shards/`). Planner decides exact module split.
- The exact JCS pre-normalization recipe + the cyberphone cross-impl golden-test fixtures (D-12).
- The CLI surface beyond `did bind` (PRD §cli implies `did generate --method=key`, `did sign`,
  `did verify`); planner shapes the Click subgroup, reusing the Phase 1 `polysemy` CLI idiom.
- did:web `.well-known/did.json` proof-of-control mechanics + caching for SEC-06 / rotation.
- Whether the one focused attestation SHACL shape (mirroring Phase 5's `validate_content_edit_shape`)
  ships here or waits for Phase 11 — keep it honest, don't fake verification that isn't happening.
- The `sign_attestation` / `verify_attestation` signatures replacing the Phase 5 unsigned stub,
  filling the seam behind Phase 5's frozen `edit_shard_content(..., signing_key)` contract.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### DID substrate spec (DID-01..DID-09, SEC-05, SEC-06)
- `.planning/REQUIREMENTS.md` rows **DID-01..DID-09** (lib picks + acceptance), **SEC-05**
  (rotation survival), **SEC-06** (GitHub-takeover defense), **RISK-4** (identity stack picks).
- `PRD-v2.0-draft-2.md` **§6.5** (DID-signed attestations: 3 methods, `canonical_content_hash`
  recipe, `fi:SignedActionShape`, §6.5 acceptance tests) — **read before planning**.
- `PRD-v2.0-draft-2.md` **§6.4** (lines ~580-668) — the frozen `edit_shard_content(...,
  signing_key)` signature + immutable/mutable field lists the signing seam plugs into.
- `PRD-v2.0-draft-2.md` **§3.1** (roles: extractor/reviewer/arbiter/corpus_admin + typical DID
  form per role; §3.1.5 governance log) — authorization context consumed by Phase 7, but the
  8 signed `action` Literals live here.
- `PRD-v2.0-draft-2.md` **§16 R5** + **§21.10** — "no server-side signing keys" anti-feature
  (DID-06) and the downstream-weighted trust model.

### Research (this phase is research-flagged — these ground the risks)
- `.planning/research/PITFALLS.md` **F2** (key-rotation breaks historical sigs — capture
  `signing_key_id`, cache snapshots, plc op-log pinning), **F3** (OAuth-binding replay — nonce/
  PKCE/DPoP), **F4** (JCS on `model_dump()` non-determinism — BLOCKING), **F7** (GitHub
  username takeover — bind to `sub`). Also F6 (corpus-admin role lockout — Phase 7, noted).
- `.planning/research/STACK.md` + `.planning/research/SUMMARY.md` §Stack — the locked identity
  crypto stack: `PyNaCl + cryptography + atproto + dag-cbor + jcs + joserfc + authlib 1.7`;
  **reject** `didkit` / `pydid` / `python-jose` / `fastapi-users`.

### Existing code to extend / reuse
- `src/folio_insights/shards/envelope.py` (line 49) — `AttestedSignature` permissive stub to
  **REPLACE** (D-13); the 8-value `action` Literal already exists at the PRD shape.
- `src/folio_insights/revision/content_edit.py` (lines ~172, ~207) — the real
  `canonical_content_hash()` (swap JCS in — D-12) + the unsigned `sign_attestation()` stub to
  fill; honors Phase 5's frozen `edit_shard_content(..., signing_key)` call site.
- `src/folio_insights/shards/audit.py` (line ~33) — the Phase 6 to-do comment block
  ("fill `sign_attestation` with real ed25519 + JCS") is the in-code spec.
- **Phase 1 reviewer-DID pattern** — the ed25519 keyfile at `$HOME/.folio-insights/` (0600/0700,
  `.gitignore`'d) is the CLI local-keyfile signing model D-07 extends. (See Phase 1
  `01-CONTEXT.md` / `reviewer.py` per PROJECT.md Key Decisions.)
- `src/folio_insights/services/shacl_validator.py` + `src/folio_insights/revision/
  content_edit_shape.ttl` — the pyshacl load/validate + `validate_*_shape()` pattern to mirror
  if a focused attestation shape ships here.

### Prior decisions (carried forward)
- `.planning/phases/05-content-versioning-6-4/05-CONTEXT.md` — D-05 (`canonical_content_hash`
  real-now JSON, "Phase 6 swaps JCS in" seam) + D-02 (in-memory `ShardStore` seam pattern that
  D-11's `DidDocCache` mirrors).
- `.planning/phases/02-shard-envelope/02-CONTEXT.md` — the `AttestedSignature` stub + 6 frozen
  identity fields + `extra="forbid"` envelope discipline.
- `.planning/phases/04-iri-scheme-6-3/04-CONTEXT.md` — immutable shard IRIs (signatures cover
  content, never change the IRI).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`canonical_content_hash()` + `sign_attestation()` seams** (`revision/content_edit.py`) —
  real deterministic hash + unsigned stub already shaped; Phase 6 swaps JCS in (D-12) and fills
  the signer behind Phase 5's frozen call site.
- **`AttestedSignature` stub** (`shards/envelope.py:49`) — replace, don't extend (D-13).
- **Phase 1 ed25519 reviewer keyfile** (`~/.folio-insights/`, 0600/0700, gitignored) — the
  client-side CLI signing pattern D-07 extends; PyNaCl/cryptography already proven there.
- **pyshacl plumbing** (`services/shacl_validator.py`) — reuse if a focused attestation shape ships.

### Established Patterns
- **New-package dep-isolation** — Phase 5 was *forced* into a `revision/` package because the
  `shards/` dep-leak guard forbids storage/RDF libs. The new `identity/` package must respect
  the same boundary: crypto + atproto + storage stay out of `shards/`.
- **In-memory seam → Phase 13 swap** — Phase 5's `ShardStore` protocol (D-02) is the template
  for D-11's `DidDocCache` (in-memory now, persistent later).
- **Click subgroup CLI** — Phase 1's `polysemy detect/review/audit` rich-prompt idiom is the
  template for the `did generate/bind/sign/verify` subgroup.
- **Hypothesis property tests** — Phase 2/4 determinism style is the template for the
  `verify(sign(x))`-across-shuffled-orders gate (D-12).

### Integration Points
- `DidDocCache` (D-11) is the seam **Phase 13** (persistent storage) replaces.
- `sign_attestation` / `canonical_content_hash` (D-12/D-13) fill the seams **Phase 5** left;
  the **browser WebCrypto** signing path (D-07) is the seam the **post-Phase-14 web phase** fills.
- The binding record + role-aware authorization is consumed by **Phase 7** (governance log,
  promotion gates) and audited by **Phase 19** (SEC-03/05/06).
</code_context>

<specifics>
## Specific Ideas

- Operator deliberately **scoped Phase 6 down to the critical-path crypto backbone** (backend +
  CLI), pushing every web-UI-bound and P2 item forward — to keep a research-flagged phase tight
  and avoid building throwaway pre-design-system UI.
- **DID-06 is absolute**: no signing key ever lives on the server, for any DID method or surface.
  The CLI local keyfile (Phase 1 pattern) and the future browser WebCrypto path both honor it.
- **SEC-06's data model lands now via CLI** even though its web flow defers — bind to OAuth `sub`,
  signed proof-of-control with a single-use nonce, subject-change detection — so the contract is
  locked and auditable on the critical path, not invented later under the web phase's time pressure.
- The amended exit bar (D-12 `<domain>`) is explicit about what STAYS vs TRAVELS FORWARD so the
  verifier doesn't fail Phase 6 against the original ROADMAP's web-UI-bound criteria.
</specifics>

<deferred>
## Deferred Ideas

- **6.2 hardware-key signing** (Ledger / YubiKey / WebAuthn for did:key; virtual-authenticator
  E2E) — DID-08, P2. Its own later phase (decimal 6.x or v2.1).
- **6.3 multi-sig attestations** (N-of-M co-sign schema + SHACL shape + UI; 2-of-3 promotion
  succeeds / 1-of-3 fails) — DID-09, P2. Same deferred phase. **`cosigners[]` slot reserved now**
  (D-13) so it doesn't re-break the schema.
- **Web OAuth→DID binding flow + styled "what will I be signing?" preview + browser WebCrypto
  signing** — DID-05/DID-07 web surfaces; **post-Phase-14** (after design contract + adapter-node).
  Carries the Playwright-3-paths + preview-screenshot exit criteria forward.
- **did:plc genesis + operation-log rotation writes** — the AT-Proto-onboarding path; defers to
  when federated AT Proto onboarding actually matters. Phase 6 keeps did:plc *resolve/verify*.
- **Persistent historical-key storage** (real aiosqlite/Oxigraph `attestation_cache`) — Phase 13
  fills the `DidDocCache` seam (D-11).
- **Governance log / promotion / contest authorization** that consumes these signatures —
  **Phase 7**. **Full SHACL `fi:SignedActionShape` verification-at-ingest suite** — **Phase 11**.
- **F6 corpus-admin role-lockout defense** (refuse self-revocation, break-glass project-admin DID)
  — surfaced in research; belongs to **Phase 7** governance, noted so it isn't lost.

### Reviewed Todos (not folded)
None — STATE pending-todos = none.
</deferred>

---

*Phase: 6-DID Substrate (§6.5)*
*Context gathered: 2026-05-27*
