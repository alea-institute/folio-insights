---
phase: 07-governance-model-3-1
verified: 2026-05-30T23:45:00Z
status: human_needed
score: 13/13 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Interactive retraction flow (D-17 default mode)"
    expected: "Running `folio-insights governance retract <iri>` (without --preview or --apply) prints a grouped table of dependents classified as {auto_rederive, aporetic, review_needed} and prompts `Confirm retraction of N shards? [y/N]` before committing to the log"
    why_human: "Interactive rich.prompt confirm flow requires a live TTY; cannot verify the terminal UX or the grouped-table rendering with grep or pytest"
  - test: "sign->verify round-trip for did:key end-to-end (CR-01 acceptability)"
    expected: "A governance CLI command (e.g. governance role-assert) completes successfully with a real did:key keypair: sign_attestation + verify_attestation both agree, and the event appends cleanly to the log"
    why_human: "The fixer noted that did:web/did:plc need Phase 13 persistent caches to fully validate; the Phase-7-acceptable baseline is did:key only, which requires a live key generation in a real process context"
---

# Phase 7: Governance Model (§3.1) Verification Report

**Phase Goal:** Ship the 4-tier role model, PROV-O governance log, and three-way disambiguation machinery that makes v2.0 governed-by-design — scoped to CLI + library + API contracts (web surfaces defer post-Phase-14 per D-03).
**Verified:** 2026-05-30T23:45:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | [D-13] `SignedAction` Literal has exactly 13 values including `role_revocation` as the final value | VERIFIED | `python -c "from typing import get_args; from folio_insights.shards.envelope import SignedAction; print(len(get_args(SignedAction)))"` → `13`; `get_args(SignedAction)[-1]` → `"role_revocation"` |
| 2 | [D-06] `GovernanceEvent` Pydantic discriminated union dispatches across 13 event classes on `action` discriminator | VERIFIED | `TypeAdapter(GovernanceEvent)` compiles; `RoleRevocationEvent is not RoleAssertionEvent` → True; union defined with `Field(discriminator="action")` in `governance/events.py:282-299` |
| 3 | [D-04] No module under `governance/` imports aiosqlite/rdflib/pyoxigraph/oxrdflib except `shape_validation.py` | VERIFIED | `tests/governance/test_dep_leak_guard.py` 5/5 PASS: all 4 forbidden modules refused + `shape_validation.py` exemption confirmed |
| 4 | [D-13] `RoleRevocationEvent` is structurally distinct from `RoleAssertionEvent` (different class, different fields: `revoked_role` vs `role`) | VERIFIED | Separate class definitions in `events.py:155-165` vs `events.py:148-152`; discriminator Literals differ; `test_role_revocation_distinct_event.py` PASS |
| 5 | [D-04/D-06] `GovernanceLog` Protocol + `InMemoryGovernanceLog` in `log.py`; `append()` is the single write entry; no public mutator beyond `append` | VERIFIED | `test_governance_log_protocol_contract.py` 8/8 PASS: Protocol shape confirmed, no public mutators present, `iter_events` async-generator convention documented (CR-02) |
| 6 | [D-05] `fi:GovernanceLogShape` SHACL refuses duplicate positions / signed_at moving backward / position gaps + append-only Protocol contract | VERIFIED | `test_governance_log_shape.py` 5/5 PASS (monotonic, duplicate, backward, gap all tested); `test_governance_log_is_append_only.py` 3/3 PASS |
| 7 | [D-05] SQLite `BEFORE UPDATE/DELETE → RAISE FAIL` trigger documented as Phase 13 forward-travel; NOT in Phase 7 | VERIFIED | `log.py:43-47` explicitly documents; module docstring states "D-05 forward-travel (NOT in this plan)"; `test_governance_log_protocol_contract.py` tests the in-phase gate only |
| 8 | [D-09/D-10/D-11/D-12/D-13] F6 corpus-admin lockout defense closed: genesis carve-out + last-admin lockout + no break-glass + distinct RoleRevocation event | VERIFIED | `test_genesis_self_signed_carveout.py` 3/3 PASS; `test_last_admin_self_revocation_refused.py` 2/2 PASS; verbatim error string `"revocation would leave the corpus with 0 active corpus_admins; appoint a successor first"` present at `log.py:364` |
| 9 | [D-19] Central `authorize()` is first step for every governance CLI command; genesis carve-out is structural inside `authorize()`, NOT a CLI bypass | VERIFIED | `test_authorize_called_first.py` 11/11 PASS (promote, role_assert, role_revoke, corpus.py, contest, supersede, resolve_contest, retract, export, show — all 10 command files + corpus_init uses GENESIS_ACTION constant); `GENESIS_ACTION` imported in `corpus/cli/corpus.py:38` |
| 10 | [D-16] Three-way disambiguation: `contest.py`, `supersede.py`, `retract.py` are structurally distinct — no cross-imports, no shared base class, no shared Click impl function | VERIFIED | `test_grep_guard_three_way_disambiguation.py` 8/8 PASS (all 3 modules × 3 checks + constant test — NOT skipped); retract.py exists so `importorskip` gate fully active |
| 11 | [D-20/D-21] Promotion validates cite-resolvable + non-empty + non-self citations; reviewer specifies `epistemic_status` via `--status`; validator enforces per-status table | VERIFIED | `test_promotion_requires_citation.py` 4/4 PASS; `test_promotion_status_kind.py` 5/5 PASS; `test_unsigned_promotion_rejected.py` 1/1 PASS; `promote.py:78+` implements D-20 + D-21 |
| 12 | [D-17] Retract cascade preview: `--preview` writes timestamped JSON; `--apply` raises `NotImplementedError` until Phase 13 wires persistent store; `PreviewStale` check real | VERIFIED | `test_preview_stale_refusal.py` 5/5 PASS; `test_cascade_preview_classification.py` 11/11 PASS; `cli/retract.py:202` raises `NotImplementedError` with Phase 13 reference (WR-03 fix); D-18 classifier correct |
| 13 | [D-22/GOV-07] `python -m folio_insights.rfc.lint .planning/rfcs/` exits 0; RFC lifecycle linter enforces filename + status DAG across git history | VERIFIED | Linter exits 0 on `.planning/rfcs/`; `tests/rfc/` 40/40 PASS (frontmatter schema, filename monotonic, status DAG, body-only edit); `RFC-TEMPLATE.md` contains `rfc: 0` (golden fixture) |

**Score:** 13/13 truths verified

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `GOVERNANCE.md` prose files | Phase 18 | ROADMAP.md: "Phase 18: Community Artifacts + Docs (parallel) — CONTRIBUTING, CoC, GOVERNANCE, RFC, mkdocs"; D-02 in CONTEXT.md; Phase 7 ships only RFC-TEMPLATE.md (linter fixture) |
| 2 | Persistent `<corpus>/governance.ttl` writer + `.governance.sqlite` + `BEFORE UPDATE/DELETE → RAISE FAIL` SQLite trigger | Phase 13 | D-05/D-07 in CONTEXT.md; `log.py` module docstring explicitly documents the Phase 13 swap point; `GovernanceLog` Protocol is the seam |
| 3 | `retract --apply` mode (full re-apply of previewed cascade) | Phase 13 | WR-03 fix: `cli/retract.py:202` raises `NotImplementedError` with explicit Phase 13 message; preview mode and interactive mode both functional in Phase 7 |
| 4 | GOV-09 governance-log timeline viewer UI + GOV-10 warrant trace-back UI (both P2) | Post-Phase-14 web phase | D-01 in CONTEXT.md; ROADMAP.md lists both as P2 stretch deferred per D-01 |
| 5 | Full `fi:SignedActionShape` SHACL verification-at-ingest suite | Phase 11 | CONTEXT.md "NOT in scope" section; Phase 7 ships focused per-event shapes only |
| 6 | did:web / did:plc sign→verify end-to-end (requires persistent DID caches) | Phase 13 | CR-01 fixer note: did:key round-trip works; did:web/did:plc need Phase 13 DidDocCache persistence |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/folio_insights/governance/events.py` | 13 GovernanceEvent classes + Annotated Union with `discriminator="action"` | VERIFIED | 13 classes defined; `GovernanceEvent` union at line 282; `__all__` complete |
| `src/folio_insights/governance/__init__.py` | Barrel re-export of GovernanceEvent + every event class | VERIFIED | Imports from `governance.events`; D-04 boundary docstring present |
| `src/folio_insights/governance/log.py` | GovernanceLog Protocol + InMemoryGovernanceLog; single `append()` write entry | VERIFIED | Protocol with 5 methods; no public mutators beyond `append`; all exception types present (`NotAuthorized`, `WouldLockoutCorpusAdmin`, `InvalidSignature`) |
| `src/folio_insights/governance/authorize.py` | Central `authorize(did, action, corpus, *, log) -> Allow | Deny`; genesis carve-out structural | VERIFIED | `GENESIS_ACTION = "corpus_init"` exported; carve-out at lines 183-193; action-permission table complete |
| `src/folio_insights/governance/roles.py` | `active_roles_at()` + `active_roles_for_did()` windowed by `signed_at <= asof` | VERIFIED | Both functions present; F2 pitfall addressed via windowed query; D-04 boundary maintained |
| `src/folio_insights/governance/contest.py` | ContestEvent + validate_contest + D-16 standalone (no cross-imports) | VERIFIED | WR-02 docstring contract present; no imports from supersede/retract |
| `src/folio_insights/governance/supersede.py` | SupersessionEvent + validate_supersession + D-16 standalone | VERIFIED | No imports from contest/retract |
| `src/folio_insights/governance/retract.py` | RetractionEvent + build_cascade_preview + commit_cascade + PreviewStale + classify_dependent | VERIFIED | All 5 symbols present; D-18 classifier with 3 buckets; `PreviewStale` wired in `commit_cascade` |
| `src/folio_insights/governance/promote.py` | D-20 cite-resolvable + D-21 status-kind cross-check | VERIFIED | `validate_promotion()` at line 78; both D-20 and D-21 checks implemented |
| `src/folio_insights/governance/shape_validation.py` | ValidationResult + SHACL validators + `serialize_log_as_turtle` | VERIFIED | All validators implemented (not stubs); `serialize_log_as_turtle` at line 669 emits PROV-O Turtle |
| `src/folio_insights/governance/shapes/` | 8 TTL SHACL shapes | VERIFIED | All 8 present: governance_log_shape.ttl, role_assertion_shape.ttl, role_revocation_shape.ttl, promotion_shape.ttl, contest_shape.ttl, contest_resolution_shape.ttl, supersession_shape.ttl, retraction_shape.ttl |
| `src/folio_insights/governance/cli/_signing.py` | sign_and_verify_event helper wired in all signing CLI commands (CR-01) | VERIFIED | Imported in: promote.py, role_assert.py, role_revoke.py, contest.py, supersede.py, resolve_contest.py (6 CLI commands) |
| `src/folio_insights/rfc/lint.py` | `def main(directory: Path) -> int`; exits 0 on clean, 1 on violation | VERIFIED | `python -m folio_insights.rfc.lint .planning/rfcs/` exits 0 |
| `src/folio_insights/rfc/frontmatter.py` | `class RFCFrontmatter(BaseModel)` | VERIFIED | Pydantic model; all tests pass |
| `src/folio_insights/rfc/git_history.py` | `subprocess.run` git log walker | VERIFIED | Present; used by status DAG test |
| `.planning/rfcs/RFC-TEMPLATE.md` | Golden fixture with `rfc: 0` | VERIFIED | File present; `rfc: 0` at line 2 |
| `src/folio_insights/corpus/cli/corpus.py` | `corpus_group` CLI + genesis flow via `authorize()` with `GENESIS_ACTION` | VERIFIED | `GENESIS_ACTION` imported at line 38; `action=GENESIS_ACTION` at line 108 |
| `tests/governance/test_grep_guard_three_way_disambiguation.py` | D-16 grep-guard 8 tests, none skipped | VERIFIED | 8/8 PASS; `importorskip` gate active because `retract.py` exists |
| `tests/governance/test_authorize_called_first.py` | D-19 AST regression for all 10 CLI command files | VERIFIED | 11/11 PASS (10 CLI files + corpus_init action constant test) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `governance/events.py` | `shards/envelope.py` | `AttestedSignature` import + `SignedAction` Literal coverage | VERIFIED | `from folio_insights.shards.envelope import AttestedSignature` at events.py:35 |
| `governance/log.py` | `governance/events.py` | `GovernanceEvent` type in `append()` signature | VERIFIED | `from folio_insights.governance.events import GovernanceEvent, RoleAssertionEvent, RoleRevocationEvent` at log.py:59-63 |
| `governance/log.py::append()` | `governance/shape_validation.py` | Lazy import of `validate_governance_log_shape` | VERIFIED | Lazy import at log.py:204-208 (D-04 boundary via lazy import pattern) |
| `governance/log.py::append()` | `identity/verifier.py::verify_attestation` | Via `cli/_signing.py` (CR-01) | VERIFIED | `sign_and_verify_event` in `_signing.py:98` calls `verify_attestation`; all 6 signing CLI commands import it |
| `governance/authorize.py::authorize` | `governance/roles.py::active_roles_for_did` | Standard role-based authorization | VERIFIED | `from folio_insights.governance.roles import active_roles_for_did` at authorize.py:48 |
| All 10 CLI commands | `governance/authorize.py::authorize` | D-19 first-await rule | VERIFIED | AST regression test 11/11 PASS; grep confirms pattern in all files |
| `corpus/cli/corpus.py` | `governance/authorize.py::GENESIS_ACTION` | Import of constant (CR-03) | VERIFIED | `GENESIS_ACTION` imported at corpus.py:38; used at corpus.py:108 |
| `governance/cli/export.py` | `governance/shape_validation.py::serialize_log_as_turtle` | D-08 on-demand Turtle export | VERIFIED | `test_governance_export_cli.py` 4/4 PASS including `test_export_cli_does_not_import_rdflib` |
| `governance/retract.py::build_cascade_preview` | `governance/retract.py::commit_cascade` | D-17 shared preview-builder | VERIFIED | `commit_cascade` calls `build_cascade_preview` at retract.py:378; `PreviewStale` raised on state change |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `InMemoryGovernanceLog` | `_by_corpus: dict[str, list[GovernanceEvent]]` | `append()` writes; `iter_events()` reads | Yes — dict populated on every append | FLOWING |
| `serialize_log_as_turtle` | `events: list[GovernanceEvent]` | Caller passes `list(log._by_corpus[corpus])` | Yes — real events from governance log | FLOWING |
| `active_roles_at()` | role assertions and revocations | `log.iter_events(corpus)` | Yes — walks real log history | FLOWING |
| `build_cascade_preview()` | `CascadePreview.groups` | `store.get_dependents()` + `classify_dependent()` | Yes — real shard dependency walk | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 210 governance+rfc+corpus tests pass | `python -m pytest tests/governance/ tests/rfc/ tests/corpus/ -q` | `210 passed in 10.91s` | PASS |
| RFC linter exits 0 on clean RFC directory | `python -m folio_insights.rfc.lint .planning/rfcs/` | Exit code 0 | PASS |
| SignedAction has 13 values with role_revocation last | Python one-liner | `13`, `True`, `"role_revocation"` | PASS |
| GovernanceEvent TypeAdapter compiles | Python one-liner | No error | PASS |
| Grep-guard 8/8 — none skipped | `pytest tests/governance/test_grep_guard_three_way_disambiguation.py` | `8 passed in 0.16s` | PASS |
| Authorize-first AST regression 11/11 | `pytest tests/governance/test_authorize_called_first.py` | `11 passed in 0.17s` | PASS |
| D-11 verbatim lockout error string present | `grep` in log.py:364 | Verbatim string confirmed | PASS |
| D-08 Turtle export CLI test | `pytest tests/governance/test_governance_export_cli.py` | `4 passed in 0.48s` | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| GOV-01 | 07-04a | 4-tier role model: extractor/reviewer/arbiter/corpus_admin scoped per corpus via signed fi:RoleAssertion | SATISFIED | `test_role_assertion_signed.py`, `test_active_roles_query.py`, `test_active_roles_rotation_safe.py` all PASS |
| GOV-02 | 07-03 | PROV-O governance log append-only (AMENDED: SHACL + Protocol contract; SQLite trigger defers to Phase 13) | SATISFIED (AMENDED) | `test_governance_log_shape.py` 5/5, `test_governance_log_protocol_contract.py` 8/8 PASS |
| GOV-03 | 07-04b | Promotion requires reviewer role + citation + DID-signed fi:Promotion; unsigned rejected CLI end-to-end | SATISFIED | `test_promotion_requires_citation.py`, `test_promotion_status_kind.py`, `test_unsigned_promotion_rejected.py` all PASS |
| GOV-04 | 07-05a | Three-way disambiguation: distinct codepaths (D-16 grep-guard) + distinct CLI subcommands | SATISFIED | Grep-guard 8/8 PASS; 3 CLI subcommands exist under governance group |
| GOV-05 | 07-05a | Contest workflow: 3 resolution paths (arbiter/distinguo/aporetic); no majority-vote | SATISFIED | `test_no_majority_vote_resolution.py` 4/4, `test_arbiter_can_resolve_contest.py`, `test_distinguo_resolution.py`, `test_aporetic_acceptance.py` PASS |
| GOV-06 | 07-05b | Retraction cascade preview: {auto_rederive, aporetic, review_needed} + interactive + --preview + --apply | SATISFIED (--apply deferred to Phase 13 per WR-03) | `test_preview_stale_refusal.py` 5/5, `test_cascade_preview_classification.py` 11/11 PASS |
| GOV-07 | 07-02 | RFC process: NNNN-title.md lifecycle linter green in CI | SATISFIED | RFC linter exits 0; `tests/rfc/` 40/40 PASS |
| GOV-08 | 07-02 (partial) | Community artifacts: RFC-TEMPLATE.md ships; CONTRIBUTING/CoC/GOVERNANCE.md deferred to Phase 18 per D-02 | PARTIAL (D-02 intentional) | RFC-TEMPLATE.md present with `rfc: 0`; prose files deferred to Phase 18 per ROADMAP + D-02 |
| GOV-09 | — (deferred) | P2 — governance log timeline viewer UI | DEFERRED (D-01) | Post-Phase-14 web phase per CONTEXT.md D-01 |
| GOV-10 | — (deferred) | P2 — warrant trace-back UI | DEFERRED (D-01) | Post-Phase-14 web phase per CONTEXT.md D-01 |
| CORPUS-05 | 07-04b | Corpus-admin role-assertion flow (DID-signed fi:RoleAssertion) | SATISFIED | `test_corpus_init_genesis.py` 4/4 PASS; genesis carve-out + admin appointment tested |

**Note on GOV-08:** D-02 decision is explicit and documented in CONTEXT.md, DISCUSSION-LOG.md, and the ROADMAP Phase 7 REQ-IDs list. Phase 7 plan 07-02 claims `requirements_completed: [GOV-07, GOV-08]` because the linter mechanism + RFC-TEMPLATE.md is Phase 7's owned portion of GOV-08; the prose files are Phase 18's owned portion. This is a pre-decided scope split, not a gap.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `cli/retract.py` | 202 | `raise NotImplementedError` in `--apply` branch | INFO (intentional) | WR-03 fix: intentionally disabled until Phase 13 wires persistent ShardStore; message points at Phase 13. Preview and interactive modes fully functional. |

No TBD, FIXME, XXX, or HACK markers found in any Phase 7 source files. The single `NotImplementedError` is a documented, intentional, reviewer-approved Phase 13 deferral (WR-03).

### Human Verification Required

### 1. Interactive Retraction Flow (D-17 default mode)

**Test:** Run `folio-insights governance retract <iri>` (without --preview or --apply) against a seeded in-memory corpus with some dependents. Observe the terminal output.
**Expected:** A rich table appears showing dependents grouped into {auto_rederive, aporetic, review_needed} buckets, followed by a prompt `Confirm retraction of N shards (auto_rederive: A, aporetic: B, review_needed: C)? [y/N]`. Entering `y` commits; entering `N` or Ctrl-C aborts without appending to the log.
**Why human:** Interactive rich.prompt confirm flow requires a live TTY. `pytest` captures stdout and cannot test the actual terminal prompt interaction. The programmatic confirm logic is unit-tested (`test_cascade_preview_shared_builder.py`) but the full UX requires a human to run the CLI in a terminal.

### 2. did:key End-to-End Sign→Verify Round-Trip (CR-01 Acceptability)

**Test:** Set up a did:key keypair (`folio-insights did generate-key` or equivalent Phase 6 keygen). Run a governance CLI command that signs (e.g., `governance role-assert --did did:key:... --role reviewer --subject did:key:...`) against an in-memory corpus seeded with a genesis admin for the operator's DID.
**Expected:** The command succeeds: `sign_attestation` produces a valid signature, `verify_attestation` confirms it, the RoleAssertionEvent appends to the log, and the exit code is 0.
**Why human:** The CR-01 fixer noted that did:web and did:plc resolution requires Phase 13's persistent DidDocCache to fully validate; the Phase-7-acceptable baseline is did:key only. A full round-trip test requires a live key on disk and a real process context beyond what the in-memory test fixtures exercise.

---

## Gaps Summary

No programmatically-detectable gaps. All 13 must-haves from plan frontmatter and ROADMAP success criteria are VERIFIED. The two items requiring human verification (interactive TTY flow and did:key end-to-end round-trip) are behavioral acceptance items that cannot be assessed by grep or pytest in this environment.

The following are explicitly accepted Phase 7 limitations per pre-decided scope (not gaps):
- `retract --apply` raises `NotImplementedError` (WR-03; Phase 13 wires the persistent shard store)
- GOV-08 prose community files absent (D-02; Phase 18 owns CONTRIBUTING/CoC/GOVERNANCE.md)
- GOV-09/GOV-10 timeline viewer and warrant trace-back UI absent (D-01; P2 deferred post-Phase-14)
- did:web/did:plc DID resolution not fully validated (Phase 13 wires persistent DidDocCache)

Test suite status: 210/210 governance+rfc+corpus tests pass. The 2 failures in `tests/bench/test_gate5_digest.py` are pre-existing Docker/Dagger infrastructure failures (commit `fc72712`, pre-Phase-7) unrelated to governance; they require a Docker daemon to run.

---

_Verified: 2026-05-30T23:45:00Z_
_Verifier: Claude (gsd-verifier)_
