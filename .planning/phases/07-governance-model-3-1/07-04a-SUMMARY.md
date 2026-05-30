---
phase: 07-governance-model-3-1
plan: 04a
subsystem: roles-authorize-substrate
tags: [governance, roles, authorize, genesis, lockout-defense, F6-closure, D-10, D-11, D-13, D-19]
requires:
  - "governance/events.GovernanceEvent (13-class discriminated union, from 07-01)"
  - "governance/shape_validation.ValidationResult + role_assertion/role_revocation stub validators (from 07-01)"
  - "governance/log.GovernanceLog + InMemoryGovernanceLog (from 07-03; this plan finalizes append() for role events)"
  - "identity/verifier.verify_attestation (Phase 6 D-13 signature gate; consumed, not re-implemented)"
  - "identity/cache.DidDocCache (windowed-by-(did, signed_at) discipline; mirrored here for active_roles_at)"
provides:
  - "governance/roles.active_roles_at(corpus, asof, *, log) -> dict[did, set[role]] (D-13 / F2 closure)"
  - "governance/roles.active_roles_for_did (convenience wrapper)"
  - "governance/authorize.authorize(did, action, corpus, *, log, admin_did, asof) -> Allow | Deny (D-19 central gate)"
  - "governance/authorize.Allow + Deny Pydantic types (frozen, extra='forbid')"
  - "governance/authorize._ACTION_PERMISSIONS table (extractor/reviewer/arbiter/corpus_admin)"
  - "governance/authorize.GENESIS_ACTION constant = 'corpus_init' (Issue #3 fix; CLI in 07-04b imports)"
  - "governance/log.NotAuthorized + WouldLockoutCorpusAdmin + InvalidSignature exceptions"
  - "governance/log.InMemoryGovernanceLog.append() finalized for RoleAssertionEvent + RoleRevocationEvent (D-10 carve-out + D-11 lockout + signer-must-be-admin)"
  - "governance/log.InMemoryGovernanceLog.query_active_roles_at() wired (delegates to roles.active_roles_at)"
  - "governance/events._BaseEvent.signature_payload() (JCS-canonical sans-signature hash bytes; consumed by sign_attestation / verify_attestation)"
  - "governance/shapes/role_assertion_shape.ttl (fi:RoleAssertionShape — sh:in role Literal + sh:sparql non-genesis-must-be-signed-by-admin)"
  - "governance/shapes/role_revocation_shape.ttl (fi:RoleRevocationShape — sh:sparql D-11 last-admin lockout via sub-select count)"
  - "governance/shape_validation.validate_role_assertion_shape + validate_role_revocation_shape (real bodies; pyshacl.validate over per-event data graph + role-context graph)"
  - "9 test files (7 Task 1 + 2 Task 2) covering positive + negative polarities"
affects:
  - "governance/__init__.py (re-exports roles + authorize + log exceptions)"
  - "governance/log.py (NotImplementedError stub replaced; query_active_roles_at wired)"
  - "governance/events.py (signature_payload() helper added to _BaseEvent)"
  - "governance/shape_validation.py (NotImplementedError stubs replaced + role-context graph builder)"
tech-stack:
  added: []
  patterns:
    - "Windowed-by-signed_at active-roles walk (mirrors identity/cache.DidDocCache.get((did, signed_at)) F2-closure discipline)"
    - "Frozen Pydantic Allow/Deny result types (mirrors identity/cache.DidDocSnapshot extra='forbid' discipline)"
    - "Action-permission table as module-level frozenset (extractor / reviewer / arbiter / corpus_admin)"
    - "Genesis carve-out STRUCTURALLY inside authorize() — action='corpus_init' bookkeeping name (Issue #3 fix; no CLI exemption)"
    - "Code-suspenders before SHACL-belt: NotAuthorized + WouldLockoutCorpusAdmin raised before the more-generic SHACL ValueError so the specific exception types carry their D-10/D-11/D-19 contracts intact"
    - "Per-event data-graph builder pattern (mirrors revision/shape_validation._build_edit_graph)"
    - "SHACL sub-select counting active corpus_admins for D-11 (rdflib 7.6.0 + pyshacl 0.31.0)"
    - "Lazy import of roles.py from log.py to break the (log → roles → log) circular reference at module load"
key-files:
  created:
    - src/folio_insights/governance/roles.py
    - src/folio_insights/governance/authorize.py
    - src/folio_insights/governance/shapes/role_assertion_shape.ttl
    - src/folio_insights/governance/shapes/role_revocation_shape.ttl
    - tests/governance/test_active_roles_query.py
    - tests/governance/test_active_roles_rotation_safe.py
    - tests/governance/test_genesis_self_signed_carveout.py
    - tests/governance/test_last_admin_self_revocation_refused.py
    - tests/governance/test_authorize_central.py
    - tests/governance/test_authorize_genesis_carve_out.py
    - tests/governance/test_role_assertion_signed.py
    - tests/governance/test_role_assertion_shape.py
    - tests/governance/test_role_revocation_shape.py
  modified:
    - src/folio_insights/governance/log.py
    - src/folio_insights/governance/events.py
    - src/folio_insights/governance/shape_validation.py
    - src/folio_insights/governance/__init__.py
decisions:
  - "D-10 STRUCTURAL inside authorize() (Issue #3 fix): action='corpus_init' is the bookkeeping action name; authorize() recognizes it, checks (rows==-1 AND did==admin_did) and returns Allow. NO CLI-level exemption — 07-04b's corpus init CLI command passes through this gate."
  - "D-11 verbatim error string locked: 'revocation would leave the corpus with 0 active corpus_admins; appoint a successor first' — single grep-able line; tested character-for-character."
  - "D-13 active-roles semantics: signed_at <= asof window; chronological walk applies assertions minus revocations using set semantics (re-assertion after revocation handled correctly)."
  - "D-19 central authorize() NEVER raises — returns Allow | Deny; mirrors verify_attestation boolean discipline."
  - "Code-suspenders precedence: NotAuthorized + WouldLockoutCorpusAdmin run BEFORE per-event SHACL belt. The SHACL belt is defense-in-depth but the code-layer exceptions carry the D-10/D-11/D-19 semantic contracts the tests assert directly."
  - "Genesis carve-out is recognized at TWO layers: (1) authorize() via action='corpus_init', (2) log.append() via (position==0 AND role==corpus_admin AND signer==subject). Both layers refuse non-genesis self-signed assertions; the SHACL shape mirrors the second layer via its sh:sparql NOT_GENESIS clause."
  - "Lazy import of roles.active_roles_at from inside log.py append() — breaks the circular reference at module load while preserving the D-04 boundary on log.py's source text (no rdflib/pyshacl import strings under governance/ except in shape_validation.py)."
metrics:
  duration_minutes: 35
  completed: 2026-05-30
---

# Phase 07 Plan 04a: Role + Authorization Substrate Summary

Shipped the role + authorization substrate that closes F6 (corpus-admin lockout defense from Phase 6) at the LIBRARY LAYER via the coordinated D-10 / D-11 / D-12 / D-13 / D-19 decisions. The central `authorize()` is now the single fact-of-truth every CLI command will call (07-04b wires the CLI surface); the genesis bootstrap is a STRUCTURAL exception inside `authorize()` itself via `action="corpus_init"` (Issue #3 closure — no CLI-level exemption). The role-assertion + role-revocation SHACL shapes ship as the belt-and-suspenders second check at storage time.

## What Shipped

### 1. `governance/roles.py` — windowed active-roles query (D-13 / F2 closure)

```python
async def active_roles_at(corpus, asof, *, log) -> dict[did, set[role]]: ...
async def active_roles_for_did(corpus, did, asof, *, log) -> set[role]: ...
```

Walks `log.iter_events(corpus)` and applies assertions minus revocations
windowed by `signature.signed_at <= asof`. The boundary `<=` is **inclusive**
(an assertion at `t0` is active when queried at `t0`). Set semantics handle
re-assertion-after-revocation correctly. Events with `signed_at is None`
(honest-unsigned Phase-5 stubs) are excluded — an unsigned event cannot
window.

The discipline mirrors `identity/cache.DidDocCache.get((did, signed_at))` —
the F2 closure for role queries: key rotation does NOT retroactively
invalidate a role assertion because the walk uses the historical signing
timestamp, not the DID's current key state.

### 2. `governance/authorize.py` — central authorize() gate (D-19)

```python
class Allow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: str | None = None

class Deny(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: str

AuthorizeResult = Union[Allow, Deny]

async def authorize(did, action, corpus, *, log, admin_did=None, asof=None) -> AuthorizeResult: ...
```

**Action-permission table (PRD §3.1):**

| Role         | Allowed actions                                                                                          |
| ------------ | -------------------------------------------------------------------------------------------------------- |
| extractor    | extract, content_edit                                                                                    |
| reviewer     | + promote, demote, contest, supersede, retract, distinguo, reparent, reconcile                          |
| arbiter      | + resolve_contest                                                                                        |
| corpus_admin | + role_assertion, role_revocation                                                                        |

**Genesis carve-out (Issue #3 fix — structural inside authorize()):**

When `action == "corpus_init"`:
- `rows >= 0` → `Deny(reason="corpus_already_initialized")`
- `rows == -1 AND admin_did is None` → `Deny(reason="genesis_admin_did_required")`
- `rows == -1 AND did != admin_did` → `Deny(reason="genesis_mismatch")`
- `rows == -1 AND did == admin_did` → `Allow(reason="genesis bootstrap — position=0 self-signed corpus_admin assertion")`

`corpus_init` is NOT a `SignedAction` Literal and NOT a `GovernanceEvent` class.
It exists solely so `authorize()` can recognize the bookkeeping bootstrap step
and gate the carve-out without inventing a per-CLI exemption.

`authorize()` NEVER raises — typed result is the only failure mode, mirroring
`verify_attestation`'s boolean discipline.

### 3. `governance/log.py` — append() finalized for role events

The 07-03 `NotImplementedError` raise for `RoleAssertionEvent` / `RoleRevocationEvent` is replaced with the full Pattern 3 body from RESEARCH:

- **Genesis carve-out** (log-layer defense-in-depth — `authorize()` is the first gate):
  `(position == 0 AND role == "corpus_admin" AND signer == subject)` → skip
  signature verification, skip signer-must-be-admin.
- **Non-genesis RoleAssertion**:
  1. Refuse self-signed assertions (any row + signer == subject when role != corpus_admin OR position > 0).
  2. **Code suspenders** → `signer must hold corpus_admin at signed_at` → else `NotAuthorized`.
  3. **SHACL belt** → `validate_role_assertion_shape(event, history=history)` → else `ValueError`.
- **RoleRevocation**:
  1. **Code suspenders** → signer must be corpus_admin → else `NotAuthorized`.
  2. **D-11 lockout code check** (verbatim error string) → revoke of last admin → `WouldLockoutCorpusAdmin`.
  3. **SHACL belt** → `validate_role_revocation_shape` → else `ValueError`.
- `query_active_roles_at` delegates to `roles.active_roles_at(corpus, asof, log=self)`.

**Exception hierarchy** (subclasses of `ValueError` for backwards compatibility with the 07-03 SHACL-refusal catch path):
- `NotAuthorized` — signer not an active corpus_admin / non-genesis self-signed refused.
- `WouldLockoutCorpusAdmin` — D-11 / F6 closure; verbatim error string locked.
- `InvalidSignature` — Phase 6 verify_attestation refused (reserved; CLI in 07-04b wires this gate).

### 4. `governance/events.py` — signature_payload() helper

Added `_BaseEvent.signature_payload(self) -> bytes`: returns the JCS-canonical
SHA-256 hex hash of the event's content excluding the signature itself,
encoded as bytes. Consumers (`sign_attestation` / `verify_attestation`) take
the returned bytes (decoded as a string) as their `content_hash` parameter.

### 5. `governance/shapes/role_assertion_shape.ttl` (D-10 belt)

`fi:RoleAssertionShape` with three constraints:

1. `sh:property` — `fi:role` is one of `{extractor, reviewer, arbiter, corpus_admin}` (sh:in + sh:datatype xsd:string).
2. `sh:property` — `fi:subjectDid` is a single non-empty xsd:string.
3. `sh:sparql` — NOT_GENESIS AND signer does NOT hold corpus_admin → conforms=False.

The NOT_GENESIS clause is the inverse of D-10: at least one of
(position != 0 OR role != "corpus_admin" OR signer != subject) holds.

### 6. `governance/shapes/role_revocation_shape.ttl` (D-11 belt)

`fi:RoleRevocationShape` with three constraints:

1. `sh:property` — `fi:revokedRole` is one of the 4 canonical role values.
2. `sh:property` — `fi:subjectDid` is a single non-empty xsd:string.
3. `sh:sparql` — `revokedRole = "corpus_admin"` AND subject is active admin AND COUNT(active admins) == 1 → conforms=False.

The lockout SPARQL uses a SUB-SELECT to count ALL active admins (the earlier
single-pattern approach incorrectly restricted the count to the subject and
always fired even when successors existed; fixed in commit `bad4055`).

### 7. `governance/shape_validation.py`

- `validate_role_assertion_shape(event, *, history=None) -> ValidationResult` — real body.
- `validate_role_revocation_shape(event, *, history=None) -> ValidationResult` — real body.
- `_build_role_assertion_graph(event, history)` + `_build_role_revocation_graph(event, history)` — per-event RDF graph builders.
- `_build_role_context_graph(history, event)` — emits `<signer_did> fi:hasActiveRoleAt [ fi:role "<role>" ; fi:asof "<asof>" ]` triples for each currently-active role assertion at signed_at (walks history applying assertions minus revocations). Powers both shapes' SPARQL constraints.
- `_parse_violations(results_text)` — helper for the violations-list extraction.

Both validators fall through to `conforms=True` if the TTL file doesn't exist (defensive — the code-layer gate then remains active).

### 8. Tests (9 new files; full governance suite = 79/79 passing)

| File | Tests | Notes |
|------|-------|-------|
| `test_active_roles_query.py` | 3 | windowed boundary inclusive; lockout-OK-with-successor; convenience wrapper |
| `test_active_roles_rotation_safe.py` | 1 | F2 closure: role assertion at t0 stays active across key rotation |
| `test_genesis_self_signed_carveout.py` | 3 | row-0 positive; non-genesis self-signed refused; non-corpus_admin at row 0 refused |
| `test_last_admin_self_revocation_refused.py` | 2 | verbatim D-11 string; successor unlocks revocation |
| `test_authorize_central.py` | 24 | 22 parametrized table rows + 2 never-raises (unknown DID + unknown action) |
| `test_authorize_genesis_carve_out.py` | 5 | 4 polarity cases (rows==0+match→Allow, rows>0→Deny, rows==0+mismatch→Deny, non-corpus_init→Deny) + admin_did=None |
| `test_role_assertion_signed.py` | 1 | end-to-end signed RoleAssertion (real ed25519 keypair via did:key + DidDocCache + verify_attestation + log.append) |
| `test_role_assertion_shape.py` | 4 | 2 positive (genesis self-signed + admin-signed reviewer) + 2 negative (non-genesis self-signed + non-corpus_admin at row 0) |
| `test_role_revocation_shape.py` | 2 | successor exists positive + last-admin lockout negative with message reference |

## Test Counts

| Suite | Tests Added | Status |
|-------|-------------|--------|
| tests/governance (this plan) | 45 | 45/45 passing |
| tests/governance (cumulative 07-01 + 07-03 + 07-04a) | n/a | 79/79 passing |
| tests/{shards, identity, revision, polysemy} (regression) | 0 | 443/443 passing |

## Acceptance Criteria

- [x] `python -c "from folio_insights.governance.roles import active_roles_at, active_roles_for_did; from folio_insights.governance.authorize import authorize, Allow, Deny; from folio_insights.governance.log import WouldLockoutCorpusAdmin, NotAuthorized; print('ok')"` → `ok`
- [x] `grep -c "revocation would leave the corpus with 0 active corpus_admins; appoint a successor first" src/folio_insights/governance/log.py` → 1
- [x] `grep -c "corpus_already_initialized" src/folio_insights/governance/authorize.py` → 2 (≥1 required)
- [x] `grep -c "genesis bootstrap" src/folio_insights/governance/authorize.py` → 3 (≥1 required)
- [x] `grep -rn "import aiosqlite|import rdflib|import pyoxigraph" src/folio_insights/governance/ | grep -v shape_validation.py | grep -v "^#"` → empty (D-04 boundary preserved)
- [x] `uv run pytest tests/governance/test_last_admin_self_revocation_refused.py -x` → 2/2 pass (verbatim error string matches character-for-character)
- [x] `uv run pytest tests/governance/test_genesis_self_signed_carveout.py -x` → 3/3 pass
- [x] `uv run pytest tests/governance/test_authorize_genesis_carve_out.py -x` → 5/5 pass (4 polarity cases + admin_did=None)
- [x] `uv run pytest tests/governance/test_authorize_central.py -x` → 24/24 pass (22 parametrized rows)
- [x] `uv run pytest tests/governance/test_role_assertion_shape.py -x` → 4/4 pass (≥3 required)
- [x] `uv run pytest tests/governance/test_role_revocation_shape.py -x` → 2/2 pass (≥2 required)
- [x] `rdflib.Graph().parse("role_assertion_shape.ttl")` → 27 triples; `..role_revocation_shape.ttl` → 27 triples (parse cleanly)
- [x] `ls src/folio_insights/governance/shapes/*.ttl | wc -l` → 3 (governance_log + role_assertion + role_revocation)
- [x] `ruff check src/folio_insights/governance/ tests/governance/` → clean
- [x] `uv run pytest tests/governance -q` → 79/79 pass

## TDD Gate Compliance

Both tasks shipped under `tdd="true"` with strict RED → GREEN sequencing:

| Phase  | Commit  | Description |
|--------|---------|-------------|
| RED    | a92e7e9 | `test(07-04a): add failing tests for roles + authorize + log-layer role event handling` (all 7 files fail at import — roles.py + authorize.py do not exist) |
| GREEN  | e505112 | `feat(07-04a): ship roles.py + authorize.py + log.py role-event body` (38 GREEN + e2e signed test all pass) |
| RED    | 16af434 | `test(07-04a): add failing polarity tests for role_assertion + role_revocation SHACL shapes` (3 negative-polarity tests fall through to conforms=True because TTLs don't ship yet) |
| GREEN  | bad4055 | `feat(07-04a): ship role_assertion + role_revocation SHACL shapes + reorder log gates` (6/6 polarity tests pass; 79/79 full governance suite green) |

REFACTOR phase: not needed (the GREEN implementations match the plan's PATTERNS-mandated structure; the gate-reorder in `bad4055` was necessary to keep the D-10/D-11/D-19 semantic exception contracts intact when the SHACL belt activated).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] sh:in role Literal vs typed Literal mismatch**

- **Found during:** Task 2 GREEN (TTL shapes activated for the first time)
- **Issue:** the `_build_role_assertion_graph` + `_build_role_revocation_graph` builders emitted role values as `Literal(role, datatype=XSD.string)`, but the SHACL `sh:in ( "extractor" ... )` clause matches plain Literals (no datatype). Pyshacl 0.31.0 distinguishes the two, so the `sh:in` constraint fired on every event — even the valid genesis row.
- **Fix:** dropped the explicit `XSD.string` datatype on role / subjectDid / signerDid / revokedRole literals — rdflib emits them as plain Literals that pyshacl matches against the sh:in plain-string list.
- **Files modified:** `src/folio_insights/governance/shape_validation.py`
- **Commit:** `bad4055` (rolled into the Task 2 GREEN commit because it was a one-line fix discovered during the same run)

**2. [Rule 3 - Blocking] D-11 sub-select count semantics**

- **Found during:** Task 2 GREEN (positive successor-exists test failed)
- **Issue:** the initial `role_revocation_shape.ttl` SPARQL counted `?adminDid` filtered to the subject — which is always 1 when the subject is currently an admin. The HAVING `COUNT == 1` therefore fired for every legitimate revocation, not just the lockout case.
- **Fix:** rewrote the SPARQL to use a SUB-SELECT counting ALL active admins, then in the outer query: (a) check the subject IS an active admin, (b) check the total admin count is 1.
- **Files modified:** `src/folio_insights/governance/shapes/role_revocation_shape.ttl`
- **Commit:** `bad4055` (same Task 2 GREEN commit)

**3. [Rule 3 - Blocking] Gate ordering: code suspenders before SHACL belt**

- **Found during:** Task 2 GREEN (D-11 verbatim error string test failed after the SHACL shape shipped — the SHACL belt fired first and raised the generic ValueError instead of the WouldLockoutCorpusAdmin exception the test asserts).
- **Issue:** when the SHACL belt activates, it competes with the code suspenders for "first to refuse". The SHACL belt raises a generic `ValueError("RoleRevocationShape violation ...")` while the code suspenders raise `WouldLockoutCorpusAdmin` (a more semantically-specific subclass of `ValueError` carrying the verbatim D-11 string).
- **Fix:** reordered the gates in both `_handle_role_assertion_append` and `_handle_role_revocation_append` — code suspenders run BEFORE the SHACL belt. The SHACL belt remains as defense-in-depth for any structural violation the code didn't enumerate, but the specific exception types (NotAuthorized + WouldLockoutCorpusAdmin) take precedence with their D-10/D-11/D-19 semantic contracts intact.
- **Files modified:** `src/folio_insights/governance/log.py`
- **Commit:** `bad4055`

**4. [Rule 3 - Blocking] Test fixture: `did_key_for_public_key` does not exist**

- **Found during:** Task 1 GREEN (e2e signed test)
- **Issue:** the test file initially imported `did_key_for_public_key` from `folio_insights.identity.keys`; the actual exported function is `did_key_from_public(raw_pub: bytes) -> str`.
- **Fix:** updated the test helper `_make_did_key` to extract the raw 32-byte public key via `cryptography.hazmat.primitives.serialization` and call `did_key_from_public`.
- **Files modified:** `tests/governance/test_role_assertion_signed.py`
- **Commit:** `e505112` (rolled into Task 1 GREEN)

**5. [Rule 3 - Blocking] uv dev dependencies not installed in fresh venv**

- **Found during:** first pytest invocation
- **Issue:** the worktree's `.venv` was created during `uv sync` but pytest was not installed (it lives under `[project.optional-dependencies] dev`).
- **Fix:** ran `uv pip install -e ".[dev]"` to install pytest + pytest-asyncio + pytest-timeout + hypothesis + ruff into the editable env.
- **Files modified:** none (env-only)
- **Commit:** n/a (env state, not source)

### Process Notes

No `git stash` was used in this plan (unlike 07-03's process deviation). All
worktree-safety guards (`worktree_branch_check`, `pre_commit_head_assertion`)
passed at every commit. Commit-and-push autonomy followed the project's
established convention (no `git push` was attempted because this is a parallel
executor worktree the orchestrator will merge).

## Threat Surface Scan

The plan's `<threat_model>` enumerates T-7-01 through T-7-SC. Each disposition is realized:

| Threat ID | Mitigation Realized |
|-----------|---------------------|
| T-7-01 (Elevation — CLI bypass via undocumented corpus init) | Closed at the `authorize()` layer: `action="corpus_init"` is a structural bookkeeping case inside authorize(). `test_authorize_genesis_carve_out.py` asserts the 4 polarity cases. |
| T-7-02 (Spoofing — non-admin forges a RoleAssertion) | Closed via (a) SHACL `fi:RoleAssertionShape` sh:sparql NOT_GENESIS clause; (b) log.py signer-must-be-admin code suspenders; (c) genesis carve-out is the ONLY structural exception. |
| T-7-04 (DoS — last-admin self-revocation) | Closed via (a) SHACL `fi:RoleRevocationShape` sub-select count belt; (b) log.py `WouldLockoutCorpusAdmin` code suspenders with verbatim D-11 string. |
| T-7-05 (Tampering — replay of RoleRevocation) | Closed structurally by 07-03's monotonic-position + signed_at-non-decreasing invariants + Phase 6 verify_attestation chain. |
| T-7-12 (Tampering — dep-leak in roles.py / authorize.py / log.py) | Closed: grep over governance/ minus shape_validation.py is empty. The 07-01 dep-leak guard test (`test_dep_leak_guard.py`) still passes 5/5. |
| T-7-SC (new pip dep) | Accepted: zero new packages. |

No NEW security-relevant surface was introduced beyond what the plan enumerated.

## Known Stubs

The remaining role-event SHACL validators (`validate_promotion_shape`,
`validate_contest_shape`, `validate_contest_resolution_shape`,
`validate_supersession_shape`, `validate_retraction_shape`) still raise
`NotImplementedError` — their TTL shapes ship in 07-04b / 07-05a / 07-05b
respectively. This is plan-mandated and was documented in 07-01's summary.

## Deferred Issues (out of scope; pre-existing)

The 5 pre-Phase-7 failures noted in 07-01 / 07-03 SUMMARYs persist (and were
NOT touched by this plan):
- `tests/bench/test_gate5_digest.py` (Dagger digest reproducibility).
- `tests/test_bridge.py` (FileNotFoundError on `folio-enrich/backend` directory).
- 7 `test_*_api.py` files cannot collect due to missing `fastapi` dep.

## Self-Check: PASSED

**Files created (existence verified):**
- src/folio_insights/governance/roles.py — FOUND
- src/folio_insights/governance/authorize.py — FOUND
- src/folio_insights/governance/shapes/role_assertion_shape.ttl — FOUND
- src/folio_insights/governance/shapes/role_revocation_shape.ttl — FOUND
- tests/governance/test_active_roles_query.py — FOUND
- tests/governance/test_active_roles_rotation_safe.py — FOUND
- tests/governance/test_genesis_self_signed_carveout.py — FOUND
- tests/governance/test_last_admin_self_revocation_refused.py — FOUND
- tests/governance/test_authorize_central.py — FOUND
- tests/governance/test_authorize_genesis_carve_out.py — FOUND
- tests/governance/test_role_assertion_signed.py — FOUND
- tests/governance/test_role_assertion_shape.py — FOUND
- tests/governance/test_role_revocation_shape.py — FOUND

**Files modified (existence verified):**
- src/folio_insights/governance/log.py — FOUND (NotImplementedError stubs replaced; query_active_roles_at wired; NotAuthorized + WouldLockoutCorpusAdmin + InvalidSignature added)
- src/folio_insights/governance/events.py — FOUND (signature_payload() helper added)
- src/folio_insights/governance/shape_validation.py — FOUND (validate_role_assertion_shape + validate_role_revocation_shape real bodies + role-context graph builder)
- src/folio_insights/governance/__init__.py — FOUND (roles + authorize + log exceptions re-exported)

**Commits (verified via `git log`):**
- a92e7e9 — FOUND (RED: roles + authorize + log-layer role event tests)
- e505112 — FOUND (GREEN: roles.py + authorize.py + log.py role-event body)
- 16af434 — FOUND (RED: SHACL shape polarity tests)
- bad4055 — FOUND (GREEN: TTL shapes + gate reorder + Literal/sub-select fixes)
