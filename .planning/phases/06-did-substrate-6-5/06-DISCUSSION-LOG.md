# Phase 6: DID Substrate (§6.5) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-27
**Phase:** 6-DID Substrate (§6.5)
**Areas discussed:** P2 stretch scope, Web-UI timing, Key custody model, DID-method depth (+ second-order: exit bar, SEC-06, key cache, AttestedSignature schema)

---

## P2 Stretch Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Defer both P2 | Ship 6.1 core only (critical path, unlocks Phase 7+12); reserve cosigners[] slot; 6.2/6.3 become own phase | ✓ |
| Include 6.3, defer 6.2 | Fold in multi-sig (no new crypto primitive); defer WebAuthn hardware-key E2E | |
| Include all three now | Full DID substrate incl. WebAuthn + N-of-M; ~doubles phase | |

**User's choice:** Defer both P2 (Recommended)
**Notes:** Keeps a research-flagged phase tight; cosigners[] schema slot reserved now so 6.3 doesn't re-break AttestedSignature. → CONTEXT D-01, D-13.

---

## Web-UI Timing

| Option | Description | Selected |
|--------|-------------|----------|
| Backend+CLI now, defer web UI | Ship substrate + CLI + binding/preview API contracts; styled OAuth flow + preview travel to post-Phase-14; amend EC1 & EC5 | ✓ |
| Interim functional UI now | Build un-styled OAuth binding + preview now; restyle in Phase 14/15 | |
| API-only preview now | Preview as JSON/CLI endpoint; web styling later | |

**User's choice:** Backend+CLI now, defer web UI (Recommended)
**Notes:** Viewer is back to adapter-static SPA (Phase 3.5 reversion); Phase 14 owns the design contract + adapter-node. Avoids throwaway pre-design-system UI. → CONTEXT D-02.

---

## Key Custody Model (DID-06)

| Option | Description | Selected |
|--------|-------------|----------|
| CLI local-keyfile now | Extend Phase 1 ~/.folio-insights ed25519 pattern; browser WebCrypto path lands with web UI; server never holds keys | ✓ |
| Both CLI + browser now | Build browser WebCrypto signing this phase regardless of UI timing | |
| Contract-only this phase | Define/audit no-key-at-rest contract; defer physical key location to the consuming surface | |

**User's choice:** CLI local-keyfile now (Recommended)
**Notes:** DID-06 absolute — no server-resident key for any method/surface. CLI keyfile is client-side by construction. → CONTEXT D-07, D-09.

---

## DID-Method Depth

| Option | Description | Selected |
|--------|-------------|----------|
| key+web full; plc resolve/verify | did:key+did:web full sign/verify/rotation; did:plc resolve+verify only; defer plc genesis/rotation writes | ✓ |
| All three full fidelity | Incl. did:plc genesis+rotation writes to PLC directory | |
| key+web only; plc deferred | Drop did:plc entirely; amend EC1 to 2 methods | |

**User's choice:** key+web full; plc resolve/verify (Recommended)
**Notes:** did:plc operation-log writes are the heaviest path + highest-churn rotation case (Pitfall F2); most reviewers are did:web/did:key. All 3 stay verifiable. → CONTEXT D-08.

---

## Second-Order: Amended Acceptance Bar

| Option | Description | Selected |
|--------|-------------|----------|
| Accept as stated | Lock amended Phase-6 bar (STAYS vs TRAVELS FORWARD) into CONTEXT | ✓ |
| Keep CLI preview but lock 8 actions hard | Same + verbatim fixture per action type | |
| Let me adjust | Describe a change | |

**User's choice:** Accept as stated
**Notes:** → CONTEXT D-12 + `<domain>` acceptance bar.

---

## Second-Order: SEC-06 / OAuth Binding

| Option | Description | Selected |
|--------|-------------|----------|
| CLI binding + lock rules now | `did bind` CLI now; bind to OAuth sub, F3 nonce proof-of-control, F7 subject-change; web flow renders later | ✓ |
| Lock data model only, no CLI bind | Schema + rules + tests, no working bind command | |
| Defer all SEC-06 to web phase | Move SEC-06 Phase-6 portion entirely to web phase | |

**User's choice:** CLI binding + lock rules now (Recommended)
**Notes:** SEC-06 is P1 mapped to Phase 6; locking the data model on the critical path keeps it auditable (Phase 19). → CONTEXT D-10.

---

## Second-Order: Historical-Key Cache

| Option | Description | Selected |
|--------|-------------|----------|
| In-memory seam now, Phase 13 fills | DidDocCache protocol over in-memory dict keyed by (did, signed_at); mirrors Phase 5 ShardStore | ✓ |
| Real aiosqlite attestation_cache now | Add real table now (v1 already runs aiosqlite) | |
| Inline did_doc_snapshot per signature | Store snapshot on each AttestedSignature | |

**User's choice:** In-memory seam now, Phase 13 fills (Recommended)
**Notes:** Keeps storage libs out of the new identity/ package (same discipline as Phase 5 revision/). → CONTEXT D-11.

---

## Second-Order: AttestedSignature Schema

| Option | Description | Selected |
|--------|-------------|----------|
| Tighten + add fields + reserve cosigners | extra='forbid'; add signing_key_id/did_doc_snapshot_at/verified; reserve cosigners[]=[] | ✓ |
| Tighten + add, NO cosigners slot | 6.1 fields only; 6.3 adds cosigners later (2nd breaking change) | |
| Keep permissive for now | Add fields but leave extra='allow' | |

**User's choice:** Tighten + add fields + reserve cosigners (Recommended)
**Notes:** One breaking reshape now, none later; Phase 5 stub explicitly anticipated the Phase 6 tighten-to-forbid. → CONTEXT D-13.

---

## Claude's Discretion

Deferred to researcher/planner (phase is research-flagged):
- New `identity/` package layout (signer/verifier/resolver + DidDocCache + binding).
- Exact JCS pre-normalization recipe + cyberphone cross-impl golden-test fixtures (D-12).
- CLI surface beyond `did bind` (`did generate/sign/verify` Click subgroup, Phase 1 idiom).
- did:web `.well-known/did.json` proof-of-control + caching mechanics (SEC-06/rotation).
- Whether the one focused attestation SHACL shape ships here or waits for Phase 11.
- `sign_attestation`/`verify_attestation` signatures filling Phase 5's frozen `edit_shard_content(..., signing_key)` seam.

## Deferred Ideas

- 6.2 hardware-key (WebAuthn/Ledger/YubiKey) — DID-08, P2, own phase.
- 6.3 multi-sig N-of-M — DID-09, P2, own phase (cosigners[] slot reserved now).
- Web OAuth→DID binding flow + styled preview + browser WebCrypto signing — post-Phase-14.
- did:plc genesis/rotation writes — AT-Proto-onboarding phase.
- Persistent historical-key storage — Phase 13 (fills DidDocCache seam).
- Governance/promotion/contest authorization consuming signatures — Phase 7.
- Full SHACL fi:SignedActionShape verification-at-ingest suite — Phase 11.
- F6 corpus-admin role-lockout defense — Phase 7 (noted from research).
