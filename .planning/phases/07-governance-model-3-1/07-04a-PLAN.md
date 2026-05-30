---
phase: 07-governance-model-3-1
plan: 04a
type: execute
wave: 3
depends_on: [07-01, 07-03]
files_modified:
  - src/folio_insights/governance/roles.py
  - src/folio_insights/governance/authorize.py
  - src/folio_insights/governance/log.py
  - src/folio_insights/governance/shape_validation.py
  - src/folio_insights/governance/shapes/role_assertion_shape.ttl
  - src/folio_insights/governance/shapes/role_revocation_shape.ttl
  - tests/governance/test_role_assertion_signed.py
  - tests/governance/test_active_roles_query.py
  - tests/governance/test_active_roles_rotation_safe.py
  - tests/governance/test_genesis_self_signed_carveout.py
  - tests/governance/test_last_admin_self_revocation_refused.py
  - tests/governance/test_authorize_central.py
  - tests/governance/test_authorize_genesis_carve_out.py
  - tests/governance/test_role_assertion_shape.py
  - tests/governance/test_role_revocation_shape.py
autonomous: true
requirements: [GOV-01]
deferred: [GOV-09, GOV-10]
tags: [governance, roles, authorize, genesis, lockout-defense, F6-closure]

must_haves:
  truths:
    - "[D-09] F6 (corpus-admin role-lockout defense) closed in Phase 7 via the coordinated D-10/D-11/D-12/D-13 combo (genesis carve-out + last-admin refusal + no-break-glass + distinct RoleRevocation event)"
    - "[D-10] Genesis bootstrap structural exception: position=0 AND self-signed AND role=corpus_admin AND signer_did == subject_did AND log has zero existing rows. Every other case is refused by SHACL + code."
    - "[D-10/D-19] corpus init calls authorize() with action=\"corpus_init\"; authorize() returns Allow only when the corpus has zero log rows AND the requested DID matches the --admin-did flag AND action == \"corpus_init\" (genesis bootstrap carve-out). No CLI command is exempt from the authorize-first rule."
    - "[D-11] Last-admin self-revocation hard-refused with verbatim error: `revocation would leave the corpus with 0 active corpus_admins; appoint a successor first`"
    - "[D-12] No corpus-level break-glass mechanism — fork-the-corpus (Phase 18.5) is the remedy (captured as deferred idea)"
    - "[D-13] Active-roles query = role_assertions windowed by `signed_at <= asof` minus role_revocations windowed by `signed_at <= asof` (rotation-safe via Phase 6 DidDocCache; closes Pitfall F2 for role queries)"
    - "[D-19] Central `authorize(did, action, corpus, *, log) → Allow | Deny(reason)` in `governance/authorize.py`; every CLI command calls it as the first step after parsing; SHACL is the belt-and-suspenders second check; genesis carve-out is structural inside `authorize()` itself (no CLI-level exemption)."
    - "[D-01/D-03] GOV-09 + GOV-10 + all web UI surfaces deferred post-Phase-14; Phase 7 ships CLI + library + thin HTTP API contract only. Plans target CLI end-to-end CLI for the amended exit bar (D-05)."
  artifacts:
    - path: "src/folio_insights/governance/roles.py"
      provides: "RoleAssertion + RoleRevocation event handling + active_roles_at(corpus, asof) windowed query"
      contains: "active_roles_at"
    - path: "src/folio_insights/governance/authorize.py"
      provides: "Central authorize(did, action, corpus, *, log) -> Allow | Deny(reason); action-permission table; genesis carve-out for action==corpus_init when log rows == 0"
      contains: "def authorize"
    - path: "src/folio_insights/governance/shapes/role_assertion_shape.ttl"
      provides: "fi:RoleAssertionShape with genesis carve-out + non-genesis-must-be-signed-by-admin"
      contains: "fi:RoleAssertionShape"
    - path: "src/folio_insights/governance/shapes/role_revocation_shape.ttl"
      provides: "fi:RoleRevocationShape with D-11 last-admin lockout refusal"
      contains: "fi:RoleRevocationShape"
  key_links:
    - from: "src/folio_insights/governance/log.py::append()"
      to: "src/folio_insights/identity/verifier.py::verify_attestation"
      via: "Phase 6 D-13 signature verification (consume, do not re-implement)"
      pattern: "verify_attestation"
    - from: "src/folio_insights/governance/log.py::append()"
      to: "src/folio_insights/governance/roles.py::active_roles_at"
      via: "D-11 last-admin check + D-19 belt-and-suspenders role lookup"
      pattern: "active_roles_at"
    - from: "src/folio_insights/governance/authorize.py::authorize"
      to: "src/folio_insights/governance/roles.py::active_roles_for_did"
      via: "lookup roles for principal at asof; genesis case bypasses lookup when log rows == 0"
      pattern: "active_roles_for_did"
---

<objective>
Ship the role + authorization substrate that closes F6 (corpus-admin lockout defense from Phase 6) at the LIBRARY LAYER via FOUR coordinated decisions: D-10 (genesis self-signed row 0 + corpus_init carve-out inside authorize()), D-11 (last-admin self-revocation hard-refused), D-12 (no break-glass — fork-the-corpus is remedy), D-13 (distinct RoleRevocation event). Ship the central `authorize(did, action, corpus, *, log)` (D-19) as the single fact-of-truth every CLI command calls — and make the genesis bootstrap a STRUCTURAL exception inside `authorize()` itself, not a CLI-level exemption (Issue #3 fix).

Purpose: This plan ships ONLY the library-layer governance primitives — `roles.py`, `authorize.py`, and the genesis-aware `log.py::append()` body — plus the two role SHACL shapes and their per-event validators. The CLI surface (promote/assert-role/revoke-role/corpus init commands) lands in 07-04b. Splitting per Issue #5 keeps each plan under the 26-file blocker threshold.

Output: `governance/{roles,authorize}.py`; 2 SHACL TTL shapes; the genesis-aware `append()` body filled in (replacing the 07-03 NotImplementedError stubs for role events); 9 test files covering positive + negative polarities across the role/auth contract.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/07-governance-model-3-1/07-CONTEXT.md
@.planning/phases/07-governance-model-3-1/07-RESEARCH.md
@.planning/phases/07-governance-model-3-1/07-PATTERNS.md
@.planning/phases/07-governance-model-3-1/07-01-SUMMARY.md
@.planning/phases/07-governance-model-3-1/07-03-SUMMARY.md
@src/folio_insights/governance/events.py
@src/folio_insights/governance/log.py
@src/folio_insights/governance/shape_validation.py
@src/folio_insights/governance/shapes/governance_log_shape.ttl

<interfaces>
<!-- Phase 6 primitives Phase 7 consumes; D-13 / D-19 contracts; D-10 / D-11 carve-outs. -->

From src/folio_insights/identity/verifier.py:52-83 (verify_attestation — Phase 6 D-13 contract; consume, do not re-implement):
```python
async def verify_attestation(payload: bytes, sig: AttestedSignature, *, cache: DidDocCache) -> bool: ...
```

From src/folio_insights/identity/signer.py (sign_attestation — Phase 6 D-13 contract):
```python
def sign_attestation(content_hash: str, sk: Ed25519PrivateKey, did: str, action: SignedAction, *, signing_key_id: str, did_doc_snapshot_at: datetime | None, now: datetime) -> AttestedSignature: ...
```

CRITICAL — verbatim error string for D-11:
```
revocation would leave the corpus with 0 active corpus_admins; appoint a successor first
```

D-19 action-permission table (from PATTERNS.md lines 226-229):
- `extractor` -> `{extract, content_edit}`
- `reviewer` -> above + `{promote, demote, contest, supersede, retract, distinguo, content_edit, reparent, reconcile}`
- `arbiter` -> above + `{resolve_contest}`
- `corpus_admin` -> above + `{role_assertion, role_revocation}`

GENESIS CARVE-OUT inside authorize() (Issue #3 — bookkeeping action, not a CLI exemption):
- `action == "corpus_init"` AND `(await log.latest_position(corpus) == -1)` AND `did == admin_did` (the caller binds did==admin_did) → return `Allow(reason="genesis bootstrap — position=0 self-signed corpus_admin assertion")`.
- Any other combination at the genesis position (rows=0 with mismatched DID OR action != corpus_init) → `Deny(reason="genesis_mismatch")`.
- `action == "corpus_init"` at rows > 0 → `Deny(reason="corpus_already_initialized")`.

Note: `corpus_init` is an authorization action name only; it is NOT a `SignedAction` Literal value and is NOT a `GovernanceEvent` class. The genesis event actually written to the log is a `RoleAssertionEvent` with `action="role_assertion"`. `corpus_init` exists solely so `authorize()` can recognize the bookkeeping bootstrap step and gate the carve-out without inventing a per-CLI exemption.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Ship `roles.py` + `authorize.py` (with corpus_init genesis carve-out) + finalize `log.py::append()` body for role events + Phase 6 signature verification</name>
  <files>src/folio_insights/governance/roles.py, src/folio_insights/governance/authorize.py, src/folio_insights/governance/log.py, tests/governance/test_active_roles_query.py, tests/governance/test_active_roles_rotation_safe.py, tests/governance/test_genesis_self_signed_carveout.py, tests/governance/test_last_admin_self_revocation_refused.py, tests/governance/test_authorize_central.py, tests/governance/test_authorize_genesis_carve_out.py, tests/governance/test_role_assertion_signed.py</files>
  <read_first>
    - src/folio_insights/governance/log.py (from 07-03 — the NotImplementedError stubs for RoleAssertionEvent / RoleRevocationEvent + active_roles_at; this task fills them in)
    - src/folio_insights/governance/events.py (from 07-01 — RoleAssertionEvent + RoleRevocationEvent classes)
    - src/folio_insights/identity/cache.py (FULL — DidDocCache windowed-by-time analog for active_roles_at; mirror the (key, asof) discipline)
    - src/folio_insights/identity/verifier.py (FULL — Phase 6 verify_attestation contract; D-13 reshape)
    - src/folio_insights/identity/signer.py (FULL — Phase 6 sign_attestation contract)
    - .planning/phases/07-governance-model-3-1/07-RESEARCH.md lines 562-622 (Pattern 3 — full append() body with genesis carve-out + last-admin refusal); lines 1376-1383 (active-roles query semantics)
    - .planning/phases/07-governance-model-3-1/07-PATTERNS.md lines 188-251 (authorize.py + roles.py pattern assignments — Allow/Deny Pydantic types, action-permission table)
    - .planning/phases/07-governance-model-3-1/07-CONTEXT.md `<decisions>` D-10, D-11, D-12, D-13, D-19 (full carve-out + lockout refusal + active-roles semantics + central authorize)
  </read_first>
  <behavior>
    - Test 1 (active_roles_at — windowed): assert role at t0; revoke role at t1; query at t0.5 returns active; query at t1.5 returns inactive; query at t0 returns active (boundary inclusive on `signed_at <= asof`).
    - Test 2 (active_roles_at — rotation-safe, F2 closure): even when the signer's DID key was rotated between t0 and t1, query at t0 returns the role active (the role assertion at t0 was valid at signing time; subsequent key rotation does not retroactively invalidate it).
    - Test 3 (genesis carve-out positive — D-10): append a self-signed RoleAssertionEvent at position=0 granting role=corpus_admin to its own signer DID succeeds; `await log.latest_position("c1") == 0` after.
    - Test 4 (genesis carve-out negative — non-genesis self-signed refused): append a self-signed RoleAssertionEvent at any position >= 1 (where the would-be signer has no active corpus_admin role) fails with `NotAuthorized` (the SHACL `fi:RoleAssertionShape` refuses non-genesis self-signed assertions).
    - Test 5 (genesis carve-out negative — non-corpus_admin role at row 0 refused): append a self-signed RoleAssertion at position=0 granting role=reviewer (not corpus_admin) fails — the carve-out is ONLY for `role=corpus_admin`.
    - Test 6 (last-admin lockout — D-11): genesis admin tries to revoke their own corpus_admin role; `append()` raises `WouldLockoutCorpusAdmin` with the verbatim error string `revocation would leave the corpus with 0 active corpus_admins; appoint a successor first`.
    - Test 7 (lockout OK if successor exists): genesis admin appoints a second corpus_admin; THEN revokes themselves — succeeds.
    - Test 8 (authorize central — table-driven): for each `(role, action) in {(extractor,extract): Allow, (extractor,promote): Deny, (reviewer,promote): Allow, (reviewer,role_assertion): Deny, (corpus_admin,role_assertion): Allow, ...}`, assert `authorize(did, action, corpus, log=log)` returns the expected result. >=12 table rows.
    - Test 9 (authorize returns typed result — never raises): an unknown DID returns `Deny(reason="no_active_role")`; an unknown action returns `Deny(reason=...)`; authorize NEVER raises.
    - Test 10 (D-10/D-19 genesis carve-out inside authorize — POSITIVE): on an empty log (`latest_position == -1`), `authorize(admin_did, action="corpus_init", corpus, log=log)` where `admin_did` is the operator-supplied DID returns `Allow(reason="genesis bootstrap — position=0 self-signed corpus_admin assertion")`.
    - Test 11 (D-10/D-19 genesis carve-out — NEGATIVE rows>0): on a non-empty log, `authorize(admin_did, action="corpus_init", corpus, log=log)` returns `Deny(reason="corpus_already_initialized")` regardless of DID.
    - Test 12 (D-10/D-19 genesis carve-out — NEGATIVE wrong DID): on an empty log, `authorize("did:fi:eve", action="corpus_init", corpus, log=log)` where the caller intended `admin_did="did:fi:alice"` returns `Deny(reason="genesis_mismatch")`. (The CLI layer in 07-04b binds the caller's DID == --admin-did flag value before calling authorize; this test simulates the bypass attempt.)
    - Test 13 (D-10/D-19 genesis carve-out — NEGATIVE non-corpus_init action at rows=0): `authorize(did, action="promote", corpus, log=empty_log)` returns `Deny(reason="no_active_role")` (the carve-out is action-specific).
    - Test 14 (RoleAssertion signed end-to-end): genesis admin signs a RoleAssertion granting reviewer to another DID; `verify_attestation` succeeds; `log.append(role_event)` succeeds; `active_roles_at(corpus, now)` returns `{genesis_did: {"corpus_admin"}, new_reviewer: {"reviewer"}}`.
  </behavior>
  <action>
    Create `src/folio_insights/governance/roles.py`:
    - Module docstring citing D-10/D-11/D-13/Pitfall F2 + the windowed-query analog `identity/cache.py:67-73`.
    - Re-export `RoleAssertionEvent` + `RoleRevocationEvent` from events.py (convenience).
    - `async def active_roles_at(corpus: str, asof: datetime, *, log: GovernanceLog) -> dict[str, set[str]]:` walks `log.iter_events(corpus)`; for each event with `signature.signed_at <= asof`, if it is a RoleAssertionEvent, add `(subject_did -> role)`; if it is a RoleRevocationEvent, remove `(subject_did -> revoked_role)`. Returns `dict[did -> set[role]]`. Handle re-assertion-after-revocation correctly: a revoke at t1 followed by re-assert at t2 means active at t2 (set semantics + chronological scan handles this).
    - Convenience wrapper `async def active_roles_for_did(corpus: str, did: str, asof: datetime, *, log: GovernanceLog) -> set[str]` (per RESEARCH Open Question 4).

    Create `src/folio_insights/governance/authorize.py`:
    - Module docstring citing D-19 (central authorization; SHACL is belt-and-suspenders; D-10 genesis carve-out is structural inside this module, NOT a CLI-level exemption — fixes Issue #3 from checker pass 1).
    - Pydantic types: `class Allow(BaseModel)` with `ConfigDict(extra="forbid", frozen=True)`, optional `reason: str | None = None`; `class Deny(BaseModel)` with `ConfigDict(extra="forbid", frozen=True)` + `reason: str`; `AuthorizeResult = Allow | Deny`.
    - Module-level `_ACTION_PERMISSIONS: dict[str, frozenset[str]]` action-permission table per the interfaces section above.
    - **Genesis carve-out string**: a module-level constant `_GENESIS_ACTION = "corpus_init"`. This is the SINGLE place the string lives; the CLI in 07-04b imports it.
    - `async def authorize(did: str, action: str, corpus: str, *, log: GovernanceLog, admin_did: str | None = None, asof: datetime | None = None) -> AuthorizeResult:` body:
      1. Resolve `asof or datetime.now(UTC)`.
      2. **Genesis carve-out first** (so every CLI hits the same gate):
         - if `action == _GENESIS_ACTION`:
           - current_pos = `await log.latest_position(corpus)`
           - if current_pos >= 0: return `Deny(reason="corpus_already_initialized")`.
           - if `admin_did is None`: return `Deny(reason="genesis_admin_did_required")`.
           - if `did != admin_did`: return `Deny(reason="genesis_mismatch")`.
           - return `Allow(reason="genesis bootstrap — position=0 self-signed corpus_admin assertion")`.
      3. Standard path: `roles = await active_roles_for_did(corpus, did, asof, log=log)`; if empty return `Deny(reason="no_active_role")`; for each role in roles, if `action in _ACTION_PERMISSIONS[role]`, return `Allow()`; return `Deny(reason=f"role_lacks_action:{action}")`.
    - NEVER raises — typed result is the only failure mode (mirrors verify_attestation discipline).

    Edit `src/folio_insights/governance/log.py` `append()` body:
    - Replace the 07-03 `NotImplementedError` raise for RoleAssertionEvent / RoleRevocationEvent with the full Pattern 3 body from RESEARCH lines 571-621:
      1. SHACL per-event shape validation (call the new per-event validators added in Task 2 below).
      2. Existing SHACL `fi:GovernanceLogShape` check (already in 07-03).
      3. Position assignment via `model_copy(update={"position": next_pos})`.
      4. Genesis carve-out check at the LOG-APPEND layer (defense in depth — authorize.py also enforces): `is_genesis = (next_pos == 0 AND isinstance(event, RoleAssertionEvent) AND event.role == "corpus_admin" AND event.subject_did == event.signature.did)`. If `is_genesis`, SKIP signature verification AND SKIP signer-must-be-admin check.
      5. Non-genesis path: call `await verify_attestation(event.signature_payload(), event.signature, cache=...)` (consume Phase 6; do NOT re-implement). The `signature_payload()` method is a new helper on each event class — add it to events.py as a `def signature_payload(self) -> bytes` method returning the JCS-canonical hash of the event content excluding the signature itself. Small retroactive edit to events.py acceptable.
      6. Non-genesis RoleAssertion check: if `isinstance(event, RoleAssertionEvent) and not is_genesis`, verify the signer DID has `corpus_admin` in `active_roles_for_did(corpus, event.signature.did, event.signature.signed_at, log=self)`; if not, raise `NotAuthorized(f"signer {event.signature.did} is not a corpus_admin at {event.signature.signed_at}")`.
      7. D-11 last-admin lockout check: if `isinstance(event, RoleRevocationEvent) and event.revoked_role == "corpus_admin"`, call `active_roles_at(corpus, event.signature.signed_at, log=self)`; collect set of DIDs with `"corpus_admin"`; if `event.subject_did in admins_now and len(admins_now) == 1`, raise `WouldLockoutCorpusAdmin("revocation would leave the corpus with 0 active corpus_admins; appoint a successor first")`. Verbatim error string locked.
      8. Persist + return event.
    - Define exception classes at the top of `log.py`: `class NotAuthorized(ValueError)`, `class WouldLockoutCorpusAdmin(ValueError)`, `class InvalidSignature(ValueError)`.
    - Fill in the `query_active_roles_at` Protocol body in `InMemoryGovernanceLog` by delegating to `roles.active_roles_at(corpus, asof, log=self)` (lazy import to avoid circularity).

    Create the 7 test files per Tests 1-14 above:
    - `tests/governance/test_active_roles_query.py` — Tests 1, 7
    - `tests/governance/test_active_roles_rotation_safe.py` — Test 2 (F2 closure); construct a synthetic Phase 6 DidDocCache with two key snapshots; assert active_roles_at at the early signing time succeeds
    - `tests/governance/test_genesis_self_signed_carveout.py` — Tests 3, 4, 5 (log-layer carve-out)
    - `tests/governance/test_last_admin_self_revocation_refused.py` — Tests 6, 7 (verbatim error string assertion)
    - `tests/governance/test_authorize_central.py` — Tests 8, 9; table-driven via `pytest.mark.parametrize`
    - `tests/governance/test_authorize_genesis_carve_out.py` — Tests 10, 11, 12, 13 (authorize()-layer carve-out — Issue #3 closure). Use parametrize for the 4 cases; assert the exact `reason:` strings.
    - `tests/governance/test_role_assertion_signed.py` — Test 14 (end-to-end happy path)
  </action>
  <verify>
    <automated>uv run pytest tests/governance/test_active_roles_query.py tests/governance/test_active_roles_rotation_safe.py tests/governance/test_genesis_self_signed_carveout.py tests/governance/test_last_admin_self_revocation_refused.py tests/governance/test_authorize_central.py tests/governance/test_authorize_genesis_carve_out.py tests/governance/test_role_assertion_signed.py -x -q</automated>
  </verify>
  <acceptance_criteria>
    - `python -c "from folio_insights.governance.roles import active_roles_at, active_roles_for_did; from folio_insights.governance.authorize import authorize, Allow, Deny; from folio_insights.governance.log import WouldLockoutCorpusAdmin, NotAuthorized; print('ok')"` prints `ok`.
    - `grep -c "revocation would leave the corpus with 0 active corpus_admins; appoint a successor first" src/folio_insights/governance/log.py` >= 1 (verbatim D-11 error string in code).
    - `grep -c "corpus_already_initialized" src/folio_insights/governance/authorize.py` >= 1 (verbatim D-10 deny reason).
    - `grep -c "genesis bootstrap" src/folio_insights/governance/authorize.py` >= 1 (verbatim D-10 allow reason).
    - `grep -rn "import aiosqlite\|import rdflib\|import pyoxigraph" src/folio_insights/governance/roles.py src/folio_insights/governance/authorize.py src/folio_insights/governance/log.py | grep -v "^#"` returns empty (D-04 boundary).
    - `uv run pytest tests/governance/test_last_admin_self_revocation_refused.py -x` exits 0 and the test assertion matches the verbatim error string.
    - `uv run pytest tests/governance/test_genesis_self_signed_carveout.py -x` exits 0 with >=3 tests (positive carve-out + 2 negative polarity refusals).
    - `uv run pytest tests/governance/test_authorize_genesis_carve_out.py -x` exits 0 with >=4 parametrized cases (rows=0+match→Allow, rows>0→Deny, rows=0+mismatch DID→Deny, non-corpus_init action at rows=0→Deny).
    - `uv run pytest tests/governance/test_authorize_central.py -x` exits 0 with >=12 parametrized rows covering all `(role, action)` table cells.
    - Behavior: a self-signed RoleAssertion at row 0 with role=corpus_admin succeeds; the same at row 1 (without an active admin signer) fails with NotAuthorized.
    - Behavior: `authorize("did:fi:bob", "promote", "c1", log=log)` returns `Deny(reason=...)` when bob has no active role; returns `Allow()` when bob holds reviewer.
    - Behavior: `authorize(admin_did, "corpus_init", "c1", log=empty_log, admin_did=admin_did)` returns `Allow(reason=<contains "genesis bootstrap">)`; same call on a non-empty log returns `Deny(reason="corpus_already_initialized")`.
  </acceptance_criteria>
  <done>Roles + authorize ship with: (a) windowed active-roles query, (b) central authorize() with the genesis carve-out structurally embedded (Issue #3 fix — no CLI is exempt from the authorize-first rule because the bootstrap case is recognized INSIDE authorize itself via action="corpus_init"), (c) log.py::append() finalized for role events with D-10 carve-out + D-11 lockout refusal + Phase 6 signature verification. 7 test files cover the contract.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Ship `role_assertion_shape.ttl` + `role_revocation_shape.ttl` + per-event SHACL validator bodies + role-shape polarity tests</name>
  <files>src/folio_insights/governance/shapes/role_assertion_shape.ttl, src/folio_insights/governance/shapes/role_revocation_shape.ttl, src/folio_insights/governance/shape_validation.py, tests/governance/test_role_assertion_shape.py, tests/governance/test_role_revocation_shape.py</files>
  <read_first>
    - src/folio_insights/revision/content_edit_shape.ttl (Phase 5 SHACL polarity precedent)
    - src/folio_insights/governance/shape_validation.py (from 07-01 — the NotImplementedError stubs to fill in for role events)
    - src/folio_insights/governance/shapes/governance_log_shape.ttl (from 07-03 — the canonical fi:hasActiveRoleAt materialization pattern)
    - src/folio_insights/governance/log.py (from Task 1 of this plan — the consumer that calls validate_role_assertion_shape / validate_role_revocation_shape)
    - .planning/phases/07-governance-model-3-1/07-RESEARCH.md lines 928-991 (RoleAssertionShape + RoleRevocationShape skeletons)
    - .planning/phases/07-governance-model-3-1/07-PATTERNS.md lines 322-355 (TTL header pattern)
  </read_first>
  <behavior>
    - Test 1 (RoleAssertionShape positive): valid genesis-row-0 self-signed corpus_admin assertion -> conforms=True.
    - Test 2 (RoleAssertionShape negative — non-genesis self-signed): position > 0 + signer == subject + signer has no active corpus_admin role -> conforms=False.
    - Test 3 (RoleAssertionShape negative — non-corpus_admin role at row 0): position == 0 + role == "reviewer" -> conforms=False (carve-out is corpus_admin only).
    - Test 4 (RoleRevocationShape positive): valid revocation where a successor admin exists -> conforms=True.
    - Test 5 (RoleRevocationShape negative — last-admin lockout): revocation in a graph where only one corpus_admin is active -> conforms=False with message referencing the lockout (the SHACL belt mirrors the code suspenders).
  </behavior>
  <action>
    Create `src/folio_insights/governance/shapes/role_assertion_shape.ttl` per RESEARCH lines 928-963:
    - Header comment block per PATTERNS.md template; cite D-10 + D-19; include `# Polarity spiked against pyshacl 0.31.0` note.
    - `fi:RoleAssertionShape a sh:NodeShape ; sh:targetClass fi:RoleAssertion` with:
      - `sh:property [ sh:path fi:role ; sh:in ("extractor" "reviewer" "arbiter" "corpus_admin") ; sh:minCount 1 ; sh:maxCount 1 ]`
      - `sh:property [ sh:path fi:subjectDid ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ]`
      - `sh:sparql` constraint enforcing "non-genesis must be signed by a current corpus_admin" — bad case: (position != 0 OR signer != subject OR role != corpus_admin), AND signer does NOT hold corpus_admin at signed_at. The data graph builder (in shape_validation.py below) emits `fi:hasActiveRoleAt` triples so the SPARQL can look up the signer's role at signed_at.

    Create `src/folio_insights/governance/shapes/role_revocation_shape.ttl` per RESEARCH lines 967-991:
    - `fi:RoleRevocationShape a sh:NodeShape ; sh:targetClass fi:RoleRevocation` with `sh:sparql` constraint enforcing D-11 last-admin refusal: bad case = `revoked_role = "corpus_admin"` AND COUNT of active admins at signed_at == 1 AND subject_did is the lone admin.

    Edit `src/folio_insights/governance/shape_validation.py`:
    - Replace `validate_role_assertion_shape` and `validate_role_revocation_shape` NotImplementedError stubs with real bodies (mirror `validate_governance_log_shape` from 07-03 Task 1).
    - For the SHACL `sh:sparql` constraints that reference `fi:hasActiveRoleAt`, the data-graph builder must materialize the active-roles context: walk the log history up to the event's signed_at and emit `<signer_did> fi:hasActiveRoleAt ("corpus_admin" <signed_at_value>) .` triples for each active assertion. Helper `_build_role_context_graph(history, event)` keeps this isolated.

    Create 2 test files:
    - `tests/governance/test_role_assertion_shape.py` — Tests 1-3 (positive + 2 negative polarity)
    - `tests/governance/test_role_revocation_shape.py` — Tests 4-5 (positive + negative; assert lockout-reference message)
  </action>
  <verify>
    <automated>uv run pytest tests/governance/test_role_assertion_shape.py tests/governance/test_role_revocation_shape.py -x -q</automated>
  </verify>
  <acceptance_criteria>
    - `rdflib.Graph().parse("src/folio_insights/governance/shapes/role_assertion_shape.ttl", format="turtle")` and `...role_revocation_shape.ttl` both parse without error.
    - `python -c "from folio_insights.governance.shape_validation import validate_role_assertion_shape, validate_role_revocation_shape; print('ok')"` prints `ok` (no NotImplementedError on import).
    - `uv run pytest tests/governance/test_role_assertion_shape.py -x` exits 0 with >=3 tests.
    - `uv run pytest tests/governance/test_role_revocation_shape.py -x` exits 0 with >=2 tests.
    - Behavior: `validate_role_revocation_shape(<event_that_would_lockout>)` returns `conforms=False` with a violation message referencing the lockout (SHACL belt + code suspenders both refuse).
    - `grep -rn "import aiosqlite\|import rdflib\|import pyoxigraph" src/folio_insights/governance/ | grep -v shape_validation.py | grep -v "^#"` returns empty (D-04 boundary preserved).
  </acceptance_criteria>
  <done>Two SHACL shapes (role_assertion, role_revocation) ship; per-event validators replace 07-01 stubs; positive + negative polarity tests prove SHACL belt mirrors code suspenders for D-10 (carve-out) and D-11 (last-admin refusal).</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Caller (CLI in 07-04b / future API) -> `authorize()` (D-19 central gate; D-10 genesis carve-out structural inside this function) | Single gate. No CLI is exempt; `corpus init` calls `authorize()` with `action="corpus_init"` and the genesis case is recognized inside `authorize()` itself. |
| Genesis bootstrap (`action="corpus_init"` at rows==0) -> log row 0 (D-10 carve-out) | The ONE structural exception. SHACL refuses any other self-signed assertion; carve-out matches `position=0 AND self-signed AND role=corpus_admin AND log_rows==0` exactly. |
| RoleRevocation (subject_did=signer) -> `append()` last-admin check (D-11) | SHACL belt + code suspenders both refuse if revocation would leave 0 active admins. Verbatim error string locked. |
| `governance/log.py::append()` -> Phase 6 `verify_attestation` | Single fact-of-truth for signature verification; Phase 7 does NOT re-implement. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-7-01 | Elevation | CLI command bypasses role check via undocumented `corpus init` exemption | mitigate | Issue #3 fix: `authorize()` recognizes `action="corpus_init"` as a structural bookkeeping case (Allow iff rows==0 AND did==admin_did). CLI in 07-04b calls authorize() with this action; no CLI is exempt. test_authorize_genesis_carve_out.py asserts the 4 polarity cases. **HIGH severity** — original plan silently exempted corpus init. |
| T-7-02 | Spoofing | Non-admin forges a RoleAssertion granting themselves a role | mitigate | (a) `fi:RoleAssertionShape` SHACL `sh:sparql` refuses non-genesis self-signed AND non-admin-signed assertions; (b) `log.append()` code path verifies the signer holds corpus_admin at signature.signed_at; (c) genesis carve-out is the ONLY exception. **HIGH severity**. |
| T-7-04 | Denial of Service | Last-admin self-revocation locks out the corpus | mitigate | (a) `fi:RoleRevocationShape` SHACL belt refuses; (b) `log.append()` code suspenders raise `WouldLockoutCorpusAdmin` with verbatim error string; (c) no break-glass (D-12). **HIGH severity** — closes F6. |
| T-7-05 | Tampering | Replay of an old `RoleRevocation` event to demote a current admin | mitigate | (a) Position-monotonic SHACL (07-03) refuses position re-use; (b) Active-roles query windows by `signed_at <= asof` (D-13); (c) `verify_attestation` validates signature chain. |
| T-7-12 | Tampering | direct aiosqlite/rdflib/pyoxigraph import in roles.py/authorize.py | mitigate | dep-leak guard (07-01) covers all new files; acceptance criterion runs `grep`. |
| T-7-SC | Tampering | new pip dep | accept | Zero new packages this plan. |
</threat_model>

<verification>
- `uv run pytest tests/governance -x -q` exits 0 cumulatively (07-01 + 07-03 + 07-04a).
- `uv run pytest tests/ -q` exits 0 (no regression in upstream Phases 1/2/5/6).
- `grep -c "revocation would leave the corpus with 0 active corpus_admins; appoint a successor first" src/folio_insights/governance/log.py` >= 1.
- `grep -c "corpus_already_initialized\|genesis_mismatch\|genesis_admin_did_required" src/folio_insights/governance/authorize.py` >= 3.
- `grep -rn "import aiosqlite\|import rdflib\|import pyoxigraph" src/folio_insights/governance/ | grep -v shape_validation.py | grep -v "^#"` returns empty.
- `ruff check src/folio_insights/governance/` exits 0.
- `ls src/folio_insights/governance/shapes/*.ttl | wc -l` returns 3 (governance_log + role_assertion + role_revocation; the other 5 ship in 07-04b/07-05a/07-05b).
</verification>

<success_criteria>
- D-10/D-11/D-12/D-13 four-decision F6 closure verified at the library layer; genesis carve-out is structurally inside `authorize()` (Issue #3 fix).
- D-19 central `authorize()` is the single gate; even `corpus init` goes through it via `action="corpus_init"`.
- 2 new SHACL TTL shapes ship (role_assertion, role_revocation) with positive + negative polarity tests.
- `governance/` package boundary intact across new modules.
- Substrate ready for 07-04b (CLI + promotion) and 07-05a/b (three-way disambiguation + retract + export).
</success_criteria>

<output>
Create `.planning/phases/07-governance-model-3-1/07-04a-SUMMARY.md` when done with: files created (2 src + 2 TTL + log.py edit + shape_validation.py edit + 7 test files), test counts, the action-permission table dump, the F6-closure decision combo confirmation (D-10/D-11/D-12/D-13), and confirmation that authorize() now embeds the genesis carve-out structurally.
</output>
</content>
</invoke>