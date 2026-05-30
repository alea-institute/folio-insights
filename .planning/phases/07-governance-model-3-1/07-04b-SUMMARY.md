---
phase: 07-governance-model-3-1
plan: 04b
subsystem: promotion-validator-and-governance-cli
tags: [governance, promotion, cli, corpus-init, authorize-first, D-19, D-20, D-21, GOV-03, CORPUS-05]
requires:
  - "governance/events.PromotionEvent (07-01 — Field(min_length=1) on cited_iris)"
  - "governance/events._BaseEvent.signature_payload() (07-04a — JCS canonical hash)"
  - "governance/authorize.authorize + Allow/Deny (07-04a — D-19 central gate, corpus_init carve-out)"
  - "governance/log.GovernanceLog.append + InMemoryGovernanceLog (07-03 + 07-04a — role-event append finalized)"
  - "governance/shape_validation.validate_promotion_shape stub (07-01 — NotImplementedError stub replaced here)"
  - "revision/store.ShardStore + InMemoryShardStore (Phase 5 — by-IRI shard persistence seam)"
  - "shards/subtypes.ConflictingAuthoritiesShard (Phase 2/3 — closest analog to PLAN's AuthorityShard for D-21)"
  - "identity/keys.load_signing_key + generate_keypair + KEY_PATH (Phase 6 keystore)"
  - "identity/signer.sign_attestation (Phase 6 ed25519 over JCS canonical payload)"
  - "identity/cli._derive_didkey_from_signing_key (Phase 6 CLI helper re-used)"
provides:
  - "governance/promote.validate_promotion(event, *, store) -> None — D-20 cite-resolvable + D-21 status-kind cross-check"
  - "governance/promote.PromotionEvent (re-export from events.py)"
  - "governance/shapes/promotion_shape.ttl — fi:PromotionShape SHACL belt (sh:in 3-status + sh:minCount citedIri)"
  - "governance/shape_validation.validate_promotion_shape (real body) + _build_promotion_graph"
  - "governance/cli/__init__.governance_group — @click.group(name='governance')"
  - "governance/cli/promote.promote_cmd — authorize → validate_promotion → sign → append → emit"
  - "governance/cli/role_assert.role_assert_cmd — authorize → sign → append → emit"
  - "governance/cli/role_revoke.role_revoke_cmd — authorize → sign → append → emit; D-11 WouldLockoutCorpusAdmin verbatim re-emit"
  - "governance/cli/_state.GOVERNANCE_LOG — process-local InMemoryGovernanceLog singleton shared with corpus/cli"
  - "corpus/cli/__init__.corpus_group — @click.group(name='corpus')"
  - "corpus/cli/corpus.corpus_init_cmd — authorize(action='corpus_init') FIRST → genesis row 0 self-signed corpus_admin"
  - "7 test files (3 Task 1 + 4 Task 2) covering D-20 / D-21 / SHACL polarity / CORPUS-05 / D-19 source-scan / orig EC3 amended bar"
affects:
  - "cli.py — module-bottom registration of governance_group + corpus_group on root cli"
  - "governance/shape_validation.py — validate_promotion_shape NotImplementedError replaced with real body"
  - "pyproject.toml — register pytest.mark.corpus marker"
tech-stack:
  added: []
  patterns:
    - "Click command body: synchronous setup (load key, derive DID) THEN asyncio.run(_run()) where _run() awaits authorize() FIRST (D-19)"
    - "Defense-in-depth bind check at CLI: signer_did != admin_did refused BEFORE authorize() runs (clearer diagnostic than authorize() genesis_mismatch Deny)"
    - "Process-local InMemoryGovernanceLog singleton at governance/cli/_state.GOVERNANCE_LOG — shared between governance and corpus CLI commands within a Python process"
    - "Autouse pytest fixture pattern for resetting module-level state between CliRunner invocations (tests/corpus/test_corpus_init_genesis.py)"
    - "AST-walk regression test pattern: parse each Click command file, find @<group>.command-decorated functions, assert first Await(Call(Name('authorize'))) precedes any Await(Call(Attribute('append'))) — covers all 4 CLI command files (Issue #3 closure)"
    - "Placeholder signature → compute canonical payload hash → sign with sign_attestation → model_copy(update={'signature': real_sig}) — Phase 6 seam idiom for events that carry their own signature"
    - "Plain Literal (no xsd:string datatype) on fi:newStatus in promotion_shape.ttl — sh:in matches plain Literals under pyshacl 0.31.0 (07-04a bad4055 precedent)"
key-files:
  created:
    - src/folio_insights/governance/promote.py
    - src/folio_insights/governance/shapes/promotion_shape.ttl
    - src/folio_insights/governance/cli/__init__.py
    - src/folio_insights/governance/cli/_state.py
    - src/folio_insights/governance/cli/promote.py
    - src/folio_insights/governance/cli/role_assert.py
    - src/folio_insights/governance/cli/role_revoke.py
    - src/folio_insights/corpus/__init__.py
    - src/folio_insights/corpus/cli/__init__.py
    - src/folio_insights/corpus/cli/corpus.py
    - tests/governance/test_promotion_requires_citation.py
    - tests/governance/test_promotion_status_kind.py
    - tests/governance/test_promotion_shape.py
    - tests/governance/test_unsigned_promotion_rejected.py
    - tests/governance/test_authorize_called_first.py
    - tests/corpus/__init__.py
    - tests/corpus/test_corpus_init_genesis.py
  modified:
    - src/folio_insights/cli.py
    - src/folio_insights/governance/shape_validation.py
    - pyproject.toml
decisions:
  - "D-19 EVERY CLI command's first awaited step is authorize() — including corpus init (Issue #3 closure). The AST regression test (test_authorize_called_first.py) parametrizes over all 4 command files; NO CLI exemption."
  - "D-20 enforcement layers: (1) PromotionEvent.cited_iris Field(min_length=1) at Pydantic construction; (2) validate_promotion in promote.py for cite-resolvability + non-self-citation (cross-shard); (3) fi:PromotionShape sh:minCount 1 on fi:citedIri at log layer."
  - "D-21 status-kind cross-check uses a per-status table in promote.py. authority_only requires a ConflictingAuthoritiesShard cited (PLAN's 'AuthorityShard' has no Phase 2 class analog — see Deviations below) OR envelope.epistemic_status=='authority_only'. demonstrable requires the cited shard's epistemic_status in {demonstrable, per_se_nota_*, authority_only}. per_se_nota_quoad_nos has no depth check (axiomatic)."
  - "Genesis bootstrap STRUCTURAL inside authorize() — corpus init passes action='corpus_init' as a first-class authorize() call. The CLI ADDS a defense-in-depth bind check (signer_did != admin_did → refuse before authorize()) so the operator sees a clearer diagnostic than the generic genesis_mismatch Deny."
  - "Process-local GOVERNANCE_LOG singleton lives at governance/cli/_state.GOVERNANCE_LOG (NOT in __init__.py) — keeps the import surface of governance/cli/__init__.py small and avoids the (cli/__init__ → cli/promote → cli/__init__) circular import risk."
  - "WouldLockoutCorpusAdmin re-emit verbatim at the CLI layer in role_revoke.py — preserves the D-11 contract the test asserts character-for-character, even when surfaced through the CLI."
  - "Pre-signature canonical hash pattern: build event with placeholder signature → compute signature_payload() → sign_attestation over the payload hash → model_copy({'signature': real_sig}) → append. This is required because signature_payload() excludes the signature itself from the canonical hash, but the event needs to carry its own signature for the log append."
metrics:
  duration_minutes: 30
  completed: 2026-05-30
---

# Phase 07 Plan 04b: Promotion Validator + Governance CLI Summary

Shipped the D-20 cite-resolvable + D-21 status-kind cross-check promotion
validator at the library layer, the four CLI subcommands (`governance
promote` / `assert-role` / `revoke-role` + `corpus init`) that consume the
07-04a `authorize()` + `governance_log.append()` substrate, and the D-19
AST-level source-scan regression test that enforces `authorize()` is the
FIRST awaited step of EVERY CLI command — including `corpus init` (Issue
#3 closure: no CLI exemption). Closes GOV-03 (promotion attestation) +
CORPUS-05 (corpus init genesis) acceptance.

## What Shipped

### 1. `governance/promote.py` — D-20 + D-21 validator

```python
async def validate_promotion(event: PromotionEvent, *, store: ShardStore) -> None:
    # D-20: cite-resolvable + non-self-citation
    for iri in event.cited_iris:
        if iri == event.shard_iri:
            raise ValueError("D-20 self-citation refused: ...")
        if await store.get(iri) is None:
            raise ValueError("D-20 unresolvable citation: ...")
    # D-21: per-status epistemic-kind cross-check
    if status == "per_se_nota_quoad_nos":
        return  # axiomatic — no depth check
    if status == "authority_only":
        require_authority_class_or_status(...)
    if status == "demonstrable":
        require_demonstrable_or_stronger(...)
```

Pure-validation discipline: never mutates the store, never appends to the
log. Pydantic `Field(min_length=1)` on `PromotionEvent.cited_iris` is the
first line; this validator is the cross-shard second line; the SHACL belt
in `promotion_shape.ttl` is the third.

### 2. `governance/shapes/promotion_shape.ttl` — SHACL belt

`fi:PromotionShape` with two constraints:

1. `sh:property [ sh:path fi:newStatus ; sh:in ( "per_se_nota_quoad_nos" "demonstrable" "authority_only" ) ; sh:minCount 1 ; sh:maxCount 1 ]`
2. `sh:property [ sh:path fi:citedIri ; sh:minCount 1 ]`

CANNOT enforce in SHACL (lives in `validate_promotion`): cite-resolvability
(needs ShardStore), non-self-citation (cross-event lookup), D-21 status-kind
cross-check (needs cited shard's class + envelope).

### 3. `governance/shape_validation.py` — `validate_promotion_shape` wired

The 07-01 `NotImplementedError` stub is replaced with a real body that
loads `promotion_shape.ttl`, builds the data graph via
`_build_promotion_graph(event)`, runs `pyshacl.validate`, parses violations.
Returns `conforms=True` defensively if the TTL hasn't shipped (mirrors
07-04a role-shape precedent).

### 4. Four CLI subcommands (D-15 / D-19)

| Command                          | First await         | Second await         |
| -------------------------------- | ------------------- | -------------------- |
| `governance promote`             | `authorize("promote", ...)` | `validate_promotion` → `log.append` |
| `governance assert-role`         | `authorize("role_assertion", ...)` | `log.append` |
| `governance revoke-role`         | `authorize("role_revocation", ...)` | `log.append` (raises `WouldLockoutCorpusAdmin` on D-11) |
| `corpus init`                    | `authorize(action="corpus_init", admin_did=...)` | `log.append` (genesis row 0) |

Every command's body:
1. Sync setup — Click arg parse + `load_signing_key` + `_derive_didkey_from_signing_key`.
2. `asyncio.run(_run())` where `_run()` awaits `authorize(...)` as the FIRST step.
3. Build event with placeholder signature → compute canonical payload hash → `sign_attestation` → `event.model_copy(update={"signature": real_sig})`.
4. `await log.append(signed_event)` → emit `model_dump_json(indent=2)`.

D-11 lockout refusal in `role_revoke.py` catches `WouldLockoutCorpusAdmin`
and re-emits the verbatim error string to stderr — the D-11 contract
preserved character-for-character at the CLI surface.

### 5. `corpus init` defense-in-depth (Issue #3 closure)

```python
# Bind check BEFORE authorize() — clearer diagnostic than generic genesis_mismatch
if signer_did != admin_did:
    click.echo(f"--admin-did ({admin_did!r}) does not match the DID derived from --key-path ({signer_did!r}).", err=True)
    sys.exit(1)

# THEN authorize() — Issue #3: NO CLI exemption
decision = await authorize(signer_did, action="corpus_init", corpus=corpus_name, log=log, admin_did=admin_did)
```

The genesis carve-out lives inside `authorize()` (07-04a). The CLI's bind
check is purely diagnostic — `authorize()` would also refuse a mismatch
with `Deny(reason="genesis_mismatch")`. Both layers reject; the CLI just
phrases it more directly to the operator.

### 6. `governance/cli/_state.GOVERNANCE_LOG` — shared singleton

```python
GOVERNANCE_LOG: InMemoryGovernanceLog = InMemoryGovernanceLog()
```

Both `corpus init` and the three `governance` subcommands import this
singleton. Within a single Python process, the genesis row written by
`corpus init` is visible to subsequent `governance promote` /
`assert-role` / `revoke-role` calls (and a second `corpus init` against
the same corpus sees the row + returns `corpus_already_initialized`).
Phase 13 wires `<corpus>/.governance.sqlite` behind the `GovernanceLog`
Protocol per D-07.

### 7. `cli.py` registration (D-15)

Module-bottom imports + `cli.add_command(_governance_group)` +
`cli.add_command(_corpus_group)` mirror the Phase 0/1/6 idiom.

### 8. Tests (7 new files; 22 new tests; 101/101 cumulative pass)

| File | Tests | Notes |
|------|-------|-------|
| `test_promotion_requires_citation.py` | 4 | D-20 polarity (resolvable / empty / unresolvable / self-citation) |
| `test_promotion_status_kind.py` | 5 | D-21 per-status table (3 positive + 2 negative) |
| `test_promotion_shape.py` | 3 | SHACL polarity (valid / empty cited / bad status) — uses `model_construct` to bypass Pydantic for SHACL belt exercise |
| `test_unsigned_promotion_rejected.py` | 1 | Orig EC3 amended bar (D-03 CLI-only) |
| `test_authorize_called_first.py` | 5 | D-19 AST regression — 4 parametrized command files + 1 `action="corpus_init"` literal check |
| `test_corpus_init_genesis.py` | 4 | CORPUS-05 (genesis row + second-invocation denied + mismatched DID + missing --admin-did) |

## Test Counts

| Suite | Tests Added | Status |
|-------|-------------|--------|
| tests/governance (this plan) | 18 | 18/18 passing |
| tests/corpus (new package) | 4 | 4/4 passing |
| tests/governance + tests/corpus cumulative | 101 | 101/101 passing |
| tests/ full (excluding pre-existing failures from 07-04a Deferred Issues) | 728 | 728/728 passing |

## Sample `corpus init` JSON output

```json
{
  "corpus": "demo-corpus",
  "position": 0,
  "signature": {
    "did": "did:key:z6MkfogjdRW9kGjMfGjNuRXxHgLmTJZWPs28W6wbVLhgKHfx",
    "action": "role_assertion",
    "signed_at": "2026-05-30T21:18:00.636302Z",
    "signature": "NH32mu06lI4NRH9oOLg38aRWYmdRmWmXc5NCOzyOadS6cYwrCiZ0znMtumHsfgAfN7t73SAgnnjn5WzXcDtyCA",
    "over_content_hash": "dccdeb27438a2c943de1a76ecec5f8ea07ffd71ff6af541a56e51505a0793330",
    "signing_key_id": "did:key:z6Mkfo...#z6Mkfo...",
    "did_doc_snapshot_at": null,
    "verified": null,
    "cosigners": []
  },
  "action": "role_assertion",
  "subject_did": "did:key:z6MkfogjdRW9kGjMfGjNuRXxHgLmTJZWPs28W6wbVLhgKHfx",
  "role": "corpus_admin"
}
```

`position: 0` confirms the genesis row; `subject_did == signature.did`
confirms the self-signed carve-out shape; `role: "corpus_admin"` confirms
the bootstrap role.

## D-19 Source-Scan Coverage

`test_authorize_called_first.py` parametrizes over EXACTLY these 4
command files:

| Command file | Click commands inspected | Authorize action |
|--------------|--------------------------|------------------|
| `src/folio_insights/governance/cli/promote.py` | `promote_cmd` | `"promote"` |
| `src/folio_insights/governance/cli/role_assert.py` | `role_assert_cmd` | `"role_assertion"` |
| `src/folio_insights/governance/cli/role_revoke.py` | `role_revoke_cmd` | `"role_revocation"` |
| `src/folio_insights/corpus/cli/corpus.py` | `corpus_init_cmd` | `"corpus_init"` (Issue #3 closure) |

For each, the AST walk confirms `Await(Call(Name('authorize')))` precedes
any `Await(Call(Attribute('append')))`. The second test
(`test_corpus_init_uses_corpus_init_action`) greps for the literal
`action="corpus_init"` in `corpus/cli/corpus.py` — Issue #3 fix verified
at source level (greppable, not just AST-visible).

## Acceptance Criteria

- [x] `python -c "from folio_insights.governance.promote import validate_promotion, PromotionEvent; from folio_insights.governance.shape_validation import validate_promotion_shape; print('ok')"` → `ok`
- [x] `rdflib.Graph().parse("promotion_shape.ttl", format="turtle")` → 19 triples parsed cleanly
- [x] `uv run pytest tests/governance/test_promotion_requires_citation.py tests/governance/test_promotion_status_kind.py tests/governance/test_promotion_shape.py -x` → 12/12 pass
- [x] `uv run pytest tests/governance/test_unsigned_promotion_rejected.py tests/governance/test_authorize_called_first.py tests/corpus/test_corpus_init_genesis.py -x` → 10/10 pass
- [x] `uv run pytest tests/governance tests/corpus -q` → 101/101 pass
- [x] `uv run folio-insights governance --help` exits 0 listing `promote`, `assert-role`, `revoke-role`
- [x] `uv run folio-insights corpus --help` exits 0 listing `init`
- [x] `grep -rn "import aiosqlite\|import rdflib\|import pyoxigraph" src/folio_insights/governance/promote.py src/folio_insights/governance/cli/ src/folio_insights/corpus/` returns empty (D-04 boundary preserved)
- [x] `grep -c "from folio_insights.governance.cli import" src/folio_insights/cli.py` → 1
- [x] `grep -c "action=\"corpus_init\"" src/folio_insights/corpus/cli/corpus.py` → 2 (Issue #3 fix verified)
- [x] `ruff check src/folio_insights/governance/ src/folio_insights/corpus/` → clean

## TDD Gate Compliance

Both tasks shipped under `tdd="true"` with strict RED → GREEN sequencing:

| Phase  | Commit  | Description |
|--------|---------|-------------|
| RED    | 6c5d4ed | `test(07-04b): add failing tests for promote.validate_promotion + PromotionShape (D-20/D-21)` (12 tests fail at import — `folio_insights.governance.promote` does not exist; `validate_promotion_shape` raises NotImplementedError) |
| GREEN  | 0c793e8 | `feat(07-04b): ship promote.validate_promotion + PromotionShape TTL (D-20/D-21)` (12/12 tests pass; 91/91 cumulative governance suite green) |
| RED    | c9d17f1 | `test(07-04b): add failing tests for governance CLI + corpus init + D-19 source-scan` (9 failures — governance/corpus groups not yet wired into root cli) |
| GREEN  | 0607b19 | `feat(07-04b): ship 4 CLI subcommands + D-19 source-scan + corpus init genesis` (10/10 tests pass; 101/101 cumulative; 728/728 full suite excluding pre-existing) |

REFACTOR phase: not needed — the GREEN implementations match the plan's
PATTERNS structure on first pass.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] PLAN's `AuthorityShard` does not exist in Phase 2/3**

- **Found during:** Task 1 design (writing the D-21 status-kind table).
- **Issue:** The PLAN's D-21 description references an `AuthorityShard`
  subtype, but the Phase 2/3 discriminated-union ships only 5 shard
  subtypes: `SimpleAssertionShard`, `DisputedPropositionShard`,
  `ConflictingAuthoritiesShard`, `GlossShard`, `HypothesisShard`. There is
  no `AuthorityShard` class.
- **Fix:** Treated `ConflictingAuthoritiesShard` (the sic-et-non authority-
  conflict shard) as the Phase 2/3 analog of the plan's `AuthorityShard`.
  The `_AUTHORITY_CLASS_NAMES` frozenset accepts `ConflictingAuthoritiesShard`
  AND any cited shard whose envelope `epistemic_status == "authority_only"`.
  This is the closest interpretation that preserves D-21's intent (an
  `authority_only` promotion must rest on an authoritative basis) without
  silently letting `SimpleAssertionShard` citations through.
- **Files modified:** `src/folio_insights/governance/promote.py`,
  `tests/governance/test_promotion_status_kind.py`
- **Commit:** `0c793e8` (rolled into the Task 1 GREEN commit)

**2. [Rule 3 - Blocking] Process-local InMemoryGovernanceLog test isolation**

- **Found during:** Task 2 GREEN (running test_corpus_init_genesis.py).
- **Issue:** The corpus CLI shares a module-level `GOVERNANCE_LOG`
  singleton across CliRunner invocations in the same Python process.
  Without per-test reset, the first test's genesis row leaked into the
  second test's `first` invocation, causing it to see
  `corpus_already_initialized` instead of `position: 0`.
- **Fix:** Added an autouse fixture `reset_governance_log` to
  `tests/corpus/test_corpus_init_genesis.py` that monkey-patches
  `governance.cli._state.GOVERNANCE_LOG` to a fresh `InMemoryGovernanceLog`
  instance per test.
- **Files modified:** `tests/corpus/test_corpus_init_genesis.py`
- **Commit:** `0607b19` (Task 2 GREEN)

**3. [Rule 3 - Blocking] (sign_attestation signature `action` Literal narrowing)**

- **Found during:** Task 2 GREEN (writing `role_revoke.py`).
- **Issue:** `sign_attestation`'s `action: SignedAction` parameter is
  the Phase 6 `SignedAction` Literal which carries the 13 governance action
  names. Pyright/Pydantic's Literal narrowing on `"role_revocation"` is
  fine at runtime but the type checker may not see the 13-value extension
  (07-01 confirmed 12→13). Added `# type: ignore[arg-type]` comment on
  the one role_revoke.py call site to be explicit.
- **Fix:** `# type: ignore[arg-type]  # 13th Literal added in Phase 7` on
  the `action="role_revocation"` argument.
- **Files modified:** `src/folio_insights/governance/cli/role_revoke.py`
- **Commit:** `0607b19`

### Process Notes

- No `git stash` was used. All worktree-safety guards passed at every commit.
- `corpus init` mismatched-DID test exercises BOTH the CLI bind check AND
  authorize()'s `genesis_mismatch` Deny (whichever fires first). The test
  asserts either diagnostic appears in CLI output — both paths are
  acceptable since both refuse the same shape of input.

## Threat Surface Scan

The plan's `<threat_model>` enumerates T-7-01, T-7-06, T-7-07, T-7-12, T-7-SC.
Each disposition is realized:

| Threat ID | Mitigation Realized |
|-----------|---------------------|
| T-7-01 (Elevation — CLI bypass including corpus init) | Closed: `test_authorize_called_first.py` parametrizes over all 4 command files; AST walk asserts authorize() is the first awaited call in each. The second test asserts `action="corpus_init"` literal in `corpus/cli/corpus.py` — Issue #3 closure verified. |
| T-7-06 (Tampering — promotion without resolvable citations) | Closed: `validate_promotion` raises ValueError on unresolvable IRIs + self-citation; `fi:PromotionShape` SHACL `sh:minCount 1` on `fi:citedIri`; Pydantic `Field(min_length=1)` on `cited_iris`. Three defense layers. |
| T-7-07 (Tampering — promotion epistemic-status inconsistency) | Closed: D-21 per-status table in `validate_promotion`. `test_promotion_status_kind.py` covers 3 positive + 2 negative cases. |
| T-7-12 (Tampering — dep-leak in promote.py / cli/) | Closed: `grep` over `src/folio_insights/governance/promote.py src/folio_insights/governance/cli/ src/folio_insights/corpus/` is empty (excluding the exempt `shape_validation.py`). Phase 7 dep-leak guard (`tests/governance/test_dep_leak_guard.py`) still passes. |
| T-7-SC (new pip dep) | Accepted: zero new packages. |

No NEW security-relevant surface introduced beyond what the plan enumerated.

## Known Stubs

None within scope. The remaining `NotImplementedError` SHACL validators
(`validate_contest_shape`, `validate_contest_resolution_shape`,
`validate_supersession_shape`, `validate_retraction_shape`) ship in
07-05a / 07-05b per the plan's deferred-by-design list.

## Deferred Issues (out of scope; pre-existing)

The 5 pre-Phase-7 failures noted in 07-04a SUMMARY persist (and were NOT
touched by this plan):
- `tests/bench/test_gate5_digest.py` (Dagger digest reproducibility).
- `tests/test_bridge.py` (FileNotFoundError on `folio-enrich/backend`).
- `tests/test_ingestion.py` (5 cases — same folio-enrich missing path).
- 7 `test_*_api.py` files cannot collect due to missing `fastapi` dep.

GOV-09 + GOV-10 + all web UI surfaces remain deferred post-Phase-14 per
D-01 / D-03 (Phase 7 ships CLI + library + thin HTTP API contract only).

## Self-Check: PASSED

**Files created (existence verified):**
- src/folio_insights/governance/promote.py — FOUND
- src/folio_insights/governance/shapes/promotion_shape.ttl — FOUND
- src/folio_insights/governance/cli/__init__.py — FOUND
- src/folio_insights/governance/cli/_state.py — FOUND
- src/folio_insights/governance/cli/promote.py — FOUND
- src/folio_insights/governance/cli/role_assert.py — FOUND
- src/folio_insights/governance/cli/role_revoke.py — FOUND
- src/folio_insights/corpus/__init__.py — FOUND
- src/folio_insights/corpus/cli/__init__.py — FOUND
- src/folio_insights/corpus/cli/corpus.py — FOUND
- tests/governance/test_promotion_requires_citation.py — FOUND
- tests/governance/test_promotion_status_kind.py — FOUND
- tests/governance/test_promotion_shape.py — FOUND
- tests/governance/test_unsigned_promotion_rejected.py — FOUND
- tests/governance/test_authorize_called_first.py — FOUND
- tests/corpus/__init__.py — FOUND
- tests/corpus/test_corpus_init_genesis.py — FOUND

**Files modified (existence verified):**
- src/folio_insights/cli.py — FOUND (governance_group + corpus_group registration added)
- src/folio_insights/governance/shape_validation.py — FOUND (validate_promotion_shape body wired)
- pyproject.toml — FOUND (pytest.mark.corpus marker registered)

**Commits (verified via `git log`):**
- 6c5d4ed — FOUND (RED Task 1: promotion validator + SHACL polarity tests)
- 0c793e8 — FOUND (GREEN Task 1: promote.py + promotion_shape.ttl + validate_promotion_shape)
- c9d17f1 — FOUND (RED Task 2: CLI + corpus init + D-19 source-scan tests)
- 0607b19 — FOUND (GREEN Task 2: 4 CLI commands + corpus init + D-19 regression)
