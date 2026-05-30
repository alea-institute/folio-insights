# Phase 7: Governance Model (§3.1) - Research

**Researched:** 2026-05-30
**Domain:** Governance substrate — append-only PROV-O log, 4-tier role model, DID-authorized
promotion / contest / supersede / retract codepaths, retraction-cascade preview,
RFC lifecycle linter. **Library-discipline phase**: storage libs (`aiosqlite`,
`rdflib`, `pyoxigraph`) MUST stay OUT of `governance/`. The seam pattern
(Phase 5 `ShardStore`, Phase 6 `DidDocCache`) is the template.
**Confidence:** HIGH on stack + seam patterns + SHACL plumbing (verified against
installed `pyshacl 0.31.0` / `rdflib 7.6.0` / `pydantic 2.7+` already used by
Phases 5–6); HIGH on locked decisions (CONTEXT.md D-01..D-22 lock them); MEDIUM
on cascade-preview SPARQL CONSTRUCT bodies (correctness gated by integration
tests against the Phase 5 supersession links).

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (D-01..D-22)

**Scope & Phase Shape**
- **D-01:** Defer GOV-09 (timeline viewer UI) + GOV-10 (warrant trace-back UI)
  to post-Phase-14. Phase 7 ships the queryable PROV-O log + `warrant:` metadata
  those views render.
- **D-02:** Phase 18 owns the community-artifact prose files
  (CONTRIBUTING.md, CODE_OF_CONDUCT.md, GOVERNANCE.md). Phase 7 ships **only**
  the RFC linter mechanism + `RFC-TEMPLATE.md` (the linter's golden fixture).
- **D-03:** All web surfaces defer post-Phase-14. Phase 7 ships the CLI +
  Python API + thin HTTP API contract.

**Governance-Log Storage Substrate**
- **D-04:** `GovernanceLog` Protocol now; persistent backend in Phase 13.
  `aiosqlite` / `rdflib` / `pyoxigraph` stay OUT of `governance/`.
- **D-05 (acceptance-bar amendment):** `fi:GovernanceLogShape` SHACL is REAL
  now; SQLite trigger travels to Phase 13. In-phase gate = (a) SHACL refuses
  `DELETE`/`UPDATE` on past rows, (b) `GovernanceLog` Protocol contract test.
- **D-06:** Single write entry — `governance_log.append(event: GovernanceEvent)`.
  `GovernanceEvent` is a Pydantic discriminated union over **13 event types**
  (Phase 6's 12-value `SignedAction` Literal + new `role_revocation`).
- **D-07:** On-disk layout (Phase 13): `<corpus_root>/governance.ttl` +
  `<corpus_root>/.governance.sqlite`.
- **D-08:** Turtle export on-demand via `folio-insights governance export <corpus>`.

**Three-Way Disambiguation (GOV-04 — the code-review gate)**
- **D-14:** PRD §21.8 / §21.9 / GOV-04 lock contest / supersede / retract as
  conceptually distinct mechanisms.
- **D-15:** CLI shape `folio-insights governance {contest|supersede|retract}`.
- **D-16:** "No shared codepath" enforced by grep-guard regression test. Three
  modules, three event classes, three SHACL shapes. `AttestedSignature` is the
  only shared primitive.

**Retraction-Cascade Preview UX (GOV-06)**
- **D-17:** Interactive default + `--preview` dry-run + `--apply <report.json>`
  (refuses with `PreviewStale` if underlying state changed).
- **D-18:** Dependents classification heuristic — `auto_rederive` (prefer_latest +
  supersession ≤ now), `aporetic` (no supersession + no reviewer marker),
  `review_needed` (any of contested/aporetic status, human-judgment reconciliation
  strategy, or unresolved `contest_votes[]`).

**Authorization & Promotion (GOV-01 / GOV-03 / GOV-05)**
- **D-19:** Central `authorize(did, action, corpus) → Allow | Deny(reason)` in
  `src/folio_insights/governance/authorize.py`. Every CLI command calls it first.
  SHACL = belt-and-suspenders at storage time.
- **D-20:** Promotion citation depth: non-empty + resolvable to existing shard
  (and not the shard being promoted).
- **D-21:** Reviewer specifies `epistemic_status` via `--status`. Validator
  checks consistency with citation kind (`authority_only` → AuthorityShard;
  `demonstrable` → demonstrable-or-stronger; `per_se_nota_quoad_nos` → no depth
  check).

**Bootstrap & Lockout Defense (closes F6)**
- **D-09:** F6 closure lives in this phase (Phase 6 deferred it).
- **D-10:** Genesis admin via self-signed `RoleAssertion` at log row 0. Carve-out:
  `position=0 AND self-signed AND role=corpus_admin` is the **only** self-signed
  assertion accepted. CLI: `folio-insights corpus init --admin-did did:...`.
- **D-11:** Last-admin self-revocation hard-refused —
  `WouldLockoutCorpusAdmin: revocation would leave the corpus with 0 active
  corpus_admins; appoint a successor first`.
- **D-12:** No corpus-level break-glass. Remedy = fork-the-corpus (Phase 18.5).
- **D-13:** Revocation is a distinct `fi:RoleRevocation` event (NOT a flag).
  Adds `role_revocation` to Phase 6's `SignedAction` Literal (12 → 13 values).
  Active-roles query = assertions minus revocations, windowed by
  `signed_at <= asof`.

**RFC Lifecycle Linter (GOV-07)**
- **D-22:** `python -m folio_insights.rfc.lint` validates frontmatter schema,
  filename `NNNN-kebab-title.md`, monotonic numbering, monotonic status
  transitions across git history (`draft → discussion → {accepted, rejected} →
  implemented`), `rejected` terminal, and "no body-only edit may change status"
  (status diff requires `status_change_reason:` frontmatter OR `Reason:`
  commit-message trailer). Runs in CI. `RFC-TEMPLATE.md` ships as the linter's
  golden fixture.

### Claude's Discretion

- Exact package layout for `src/folio_insights/governance/`
  (`log.py`, `events.py`, `authorize.py`, `roles.py`, `promote.py`,
  `contest.py`, `supersede.py`, `retract.py`, `cli/`, `shapes/`).
  Must respect D-16 grep-guard.
- Exact SHACL turtle bodies for 8 shapes
  (`fi:GovernanceLogShape`, `fi:RoleAssertionShape`,
  `fi:RoleRevocationShape`, `fi:PromotionShape`, `fi:ContestShape`,
  `fi:SupersessionShape`, `fi:RetractionShape`, `fi:ContestResolutionShape`).
  Mirror Phase 5 `revision/content_edit_shape.ttl` style.
- `rfc.lint` linter's git-history walk strategy.
- Exact SPARQL CONSTRUCT for cascade-preview dependents query + D-18
  classification triples.
- Whether to ship a focused `fi:SignedActionShape` now or per-event shapes
  only (defer suite to Phase 11).
- Exact Click command surface for `folio-insights corpus init`.

### Deferred Ideas (OUT OF SCOPE)

- GOV-09 timeline viewer UI + GOV-10 warrant trace-back UI (P2) — post-Phase-14.
- All web flows (signing UI, modals, preview components) — post-Phase-14.
- CONTRIBUTING.md / CODE_OF_CONDUCT.md / GOVERNANCE.md prose — Phase 18.
- Persistent governance-log storage (Turtle writer + SQLite trigger) — Phase 13.
- Full `fi:SignedActionShape` SHACL verification-at-ingest suite — Phase 11.
- Multi-signature role grants (M-of-N corpus_admin) — Phase 6.3 / v2.1.
- Corpus-level break-glass mechanism — NOT shipped (fork-the-corpus is remedy).
- Cascade simulation across multiple cascades with full transactional rollback —
  analyst power tool beyond GOV-06.
- Eager Turtle export `--watch` mode — Phase 13 may add.
- `rfc lint` GitHub PR comment bot — Phase 18 may add.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GOV-01 | 4-tier role model: `extractor`, `reviewer`, `arbiter`, `corpus_admin`; scoped per corpus via signed `fi:RoleAssertion` | `roles.py` Pydantic event class + `fi:RoleAssertionShape` SHACL + `active_roles_at(corpus, asof)` query (§ "Roles & Active-Roles Query" below) |
| GOV-02 | PROV-O governance log per corpus; append-only enforced by SHACL + (Phase 13) SQLite trigger | `GovernanceLog` Protocol + `InMemoryGovernanceLog` (D-04) + `fi:GovernanceLogShape` SHACL (§ "Governance Log Shape" below) |
| GOV-03 | Promotion `hypothesis → attested` requires reviewer role + citation + DID-signed `fi:Promotion` | `promote.py` event class + D-20 citation-depth validator + D-21 status-kind cross-check (§ "Promotion Validators" below) |
| GOV-04 | Three-way disambiguation: distinct codepaths + distinct CLI commands | Three modules `{contest,supersede,retract}.py` + grep-guard test mirroring Phase 1 `detector_confidence` guard (§ "Grep-Guard Regression Test" below) |
| GOV-05 | Contest workflow: position + citation → `contest_votes[]` → resolution via arbiter / distinguo / aporetic (no majority-vote) | `contest.py` (`ContestEvent`) + `resolve_contest.py` (`ContestResolutionEvent`) — 3 resolution paths tested; majority-vote explicitly rejected (§ "Contest Resolution Paths" below) |
| GOV-06 | Retraction cascade preview: `{auto_rederive, aporetic, review_needed}` groups + rollback-before-commit | `retract.py` `build_cascade_preview(...)` SPARQL CONSTRUCT + interactive `--preview` / `--apply` (§ "Cascade Preview Architecture" below) |
| GOV-07 | RFC linter at `.planning/rfcs/NNNN-title.md` with monotonic status lifecycle; no auto-merge | `src/folio_insights/rfc/lint.py` (Pydantic frontmatter + subprocess `git log` walk) + `RFC-TEMPLATE.md` (§ "RFC Linter Strategy" below) |
| GOV-08 | Community artifacts | **Deferred to Phase 18** per D-02. Phase 7 ships RFC-TEMPLATE.md only |
| CORPUS-05 | Corpus-admin role-assertion flow (DID-signed `fi:RoleAssertion` grants roles per §3.1.1) | D-10 `folio-insights corpus init --admin-did` + `roles.py` `assert_role` codepath |
| GOV-09, GOV-10 | P2 web UI items | **Deferred** per D-01 (post-Phase-14) |
</phase_requirements>

## Project Constraints (from CLAUDE.md / Global)

- **Pydantic 2.7+ extra="forbid" envelope discipline** — every new event class
  follows Phase 2 D-13 pattern (no unknown fields slip through).
- **No server-resident signing keys, ever** (Phase 6 DID-06). Phase 7 introduces
  zero new key custody — every signature flows through Phase 6 `sign_attestation`
  with the operator's local `~/.folio-insights/` ed25519 keyfile.
- **No `.env` / secret writes from CI** — covered by Phase 6 contract; reaffirmed
  here for the `corpus init` CLI (genesis admin DID is the operator's existing
  bound DID, not a new generated key).
- **Minimal deps discipline** — `rfc.lint` uses stdlib + `subprocess.run("git
  log ...")` over GitPython (mirrors Phase 1 minimal-deps; new dep would need an
  ADR).
- **Test runner: pytest** with `pytest.mark.<phase>` marker idiom (matches
  `tests/shards/`, `tests/polysemy/`, `tests/identity/`).

---

## Summary

Phase 7 is a **library-discipline phase**: it ships a self-contained
`src/folio_insights/governance/` package whose surface is (1) a single write
seam `governance_log.append(event)`, (2) a central `authorize(did, action,
corpus)` function, (3) three deliberately-disjoint modules
`{contest,supersede,retract}.py` enforced by a grep-guard regression test, and
(4) per-event SHACL shapes layered defense-in-depth over the Pydantic event
classes. The storage backend defers to Phase 13 behind a `GovernanceLog`
Protocol — the same in-memory-seam template Phase 5 used for `ShardStore` and
Phase 6 used for `DidDocCache`. The cascade-preview is the only non-trivial
piece of new algorithmic work; everything else is **composition of existing
primitives** (Phase 6 `sign_attestation` / `verify_attestation`, Phase 5
`canonical_content_hash`, Phase 2 envelope discipline).

**Primary recommendation:** Follow the Phase 5/6 templates verbatim. Ship the
8 SHACL shapes as TTL files under `governance/shapes/` (one per event class,
plus the append-only `fi:GovernanceLogShape`); ship the 12-event Pydantic
discriminated union; ship `subprocess git log` as the rfc.lint git-walk
(zero new deps); enforce D-16 via a grep-guard that mirrors Phase 1's
`detector_confidence` guard and Phase 2's `test_dep_leak_guard.py`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 4-tier role model (GOV-01) | `governance/roles.py` (library) | `governance/cli/role_assert.py` (CLI) | Roles are a corpus-scoped Pydantic event; CLI is a thin renderer over `governance_log.append()` |
| Append-only governance log (GOV-02) | `governance/log.py` Protocol + `InMemoryGovernanceLog` | `governance/shapes/governance_log_shape.ttl` (SHACL defense-in-depth) | D-04 keeps storage libs OUT of `governance/`; Phase 13 swaps backend; SHACL refuses past-row mutation |
| Promotion workflow (GOV-03) | `governance/promote.py` (validator + event) | `governance/authorize.py` (role check first) + `governance/shapes/promotion_shape.ttl` | Validator runs D-20 citation-resolvability + D-21 status-kind cross-check; auth is first step |
| Three-way disambiguation (GOV-04) | Three modules `contest.py` / `supersede.py` / `retract.py` (each fully self-contained) | `governance/cli/{contest,supersede,retract}.py` (three Click commands) | D-16 grep-guard: no cross-imports; `AttestedSignature` is the only shared primitive |
| Contest resolution (GOV-05) | `governance/contest.py` (ContestEvent) + `governance/resolve_contest.py` (ContestResolutionEvent, 3 paths) | SHACL `fi:ContestShape` + `fi:ContestResolutionShape` | 3 paths {arbiter, distinguo, aporetic}; majority-vote explicitly rejected by test |
| Retraction cascade preview (GOV-06) | `governance/retract.py` `build_cascade_preview()` (SPARQL CONSTRUCT + D-18 classifier) | `governance/cli/retract.py` (interactive prompt + `--preview` / `--apply`) | Preview-builder runs against the corpus shard store + governance log; CLI renders + commits |
| Central authorization (D-19) | `governance/authorize.py` `authorize(did, action, corpus)` | Called by every CLI command first; SHACL is belt-and-suspenders | Single source of truth — CLI today, web phase tomorrow call the same function |
| Genesis bootstrap (D-10) | `governance/cli/corpus.py` `corpus init --admin-did` | `governance/shapes/role_assertion_shape.ttl` (genesis carve-out) | Row 0 self-signed; every later row requires existing-admin signature |
| RFC linter (GOV-07) | `src/folio_insights/rfc/lint.py` (stdlib + `subprocess git log`) | `RFC-TEMPLATE.md` (golden fixture) + `.planning/rfcs/` directory | Runs in CI; `python -m folio_insights.rfc.lint .planning/rfcs/` |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pydantic` | `>=2.7.0` | `GovernanceEvent` discriminated union + 12 event classes (`extra="forbid"`) | Already locked Phase 2 / 6; `Literal` discriminator pattern over `action` field |
| `click` | `>=8.0.0` | `folio-insights governance` subgroup + 3 disambiguation commands + `corpus init` | Already in pyproject; Phase 1 `polysemy` + Phase 6 `did` subgroups are templates |
| `pyshacl` | `>=0.31.0` | Per-event TTL shape validation + `fi:GovernanceLogShape` append-only guard | Already locked Phase 5/11; `validate_*_shape()` convention in `services/shacl_validator.py` |
| `rdflib` | `>=7.6.0` | Graph construction for SHACL validation only (NOT imported from `governance/`) | Already locked; called transitively via `services/shacl_validator.py` — keeps D-04 boundary intact |
| stdlib `subprocess` | — | `rfc.lint` git-history walk (`git log --follow --format=...`) | Minimal-deps discipline; GitPython would add a new dep with no justification |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `rich` | already in tree | `rich.prompt.Confirm` cascade-preview interactive prompt; `rich.table` for grouped table render | Cascade preview default UX (mirrors Phase 1 polysemy + Phase 6 `did sign` confirm prompts) |
| Phase 6 `identity.signer` / `verifier` | — | `sign_attestation()` + `verify_attestation()` for every event's `AttestedSignature` | Phase 7 introduces ZERO duplicate verification logic (D-19 belt-and-suspenders is SHACL not crypto) |
| Phase 5 `revision.content_edit.canonical_content_hash` | — | JCS-canonical hash for every event's `over_content_hash` | Single canonicalization point already proven by Phase 6 1000-shard property test |
| stdlib `pathlib` + `re` | — | RFC filename + frontmatter parsing | No YAML dep needed — frontmatter is `---\nkey: value\n---` parsed with simple regex |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `subprocess git log` for rfc.lint | `GitPython` (3.1.x) | GitPython adds a dep + transitive `gitdb`/`smmap`; subprocess is zero-dep and well-tested in CI environments. **Pick subprocess.** [VERIFIED: `git --version` = 2.51.0 on dev box] |
| `subprocess git log` for rfc.lint | Pure-shell pre-commit hook | Loses portability (CI test must run on Linux + macOS dev); a Python module is testable. **Pick Python module.** |
| Pydantic discriminated union (12 classes) | Single `GovernanceEvent` with `action: SignedAction` field | Loses per-event field validation (e.g., `ContestEvent.position: str` required, `PromotionEvent.cited_iris: list[str]` non-empty). Discriminated union is Pydantic-2 canonical for this case. [CITED: pydantic 2 docs — `Annotated[Union[...], Field(discriminator='action')]`] |
| Ship full `fi:SignedActionShape` suite | Per-event shapes only (defer suite to Phase 11) | Phase 5 set the precedent ("ship the focused shape; defer the suite"). Per-event shapes satisfy in-phase tests + are reusable in Phase 11. **Recommend per-event shapes only; defer suite.** [VERIFIED: Phase 5 D-04 pattern in `revision/content_edit_shape.ttl`] |

**Installation:** no new pip installs. All required libraries are already in
`pyproject.toml` from Phases 2 / 5 / 6.

```bash
# No new packages. Verified:
#   pydantic>=2.7.0   ✓ pyproject.toml
#   click>=8.0.0      ✓ pyproject.toml
#   pyshacl>=0.31.0   ✓ pyproject.toml
#   rdflib>=7.6.0     ✓ pyproject.toml
#   rich              ✓ already used by polysemy/cli.py, identity/cli.py
#   jcs==0.2.1        ✓ pyproject.toml (Phase 6)
```

## Package Legitimacy Audit

**Phase 7 installs ZERO new packages.** Every recommended library is already
present in `pyproject.toml` from earlier phases, and has been exercised through
Phases 2 / 5 / 6 in this repo (8 completed phases per STATE.md). No npm/PyPI
slopsquat surface to audit.

| Package | Registry | Status | Disposition |
|---------|----------|--------|-------------|
| `pydantic` (>=2.7.0) | PyPI | Locked Phase 2; exercised continuously | Approved (pre-existing) |
| `click` (>=8.0.0) | PyPI | Locked Phase 1 polysemy; exercised Phase 6 did subgroup | Approved (pre-existing) |
| `pyshacl` (>=0.31.0) | PyPI | Locked Phase 5; live-spiked in Phase 5 RESEARCH | Approved (pre-existing) |
| `rdflib` (>=7.6.0) | PyPI | Locked Phase 5; live-spiked | Approved (pre-existing) |
| `rich` | PyPI | Already used by Phase 1 + Phase 6 CLI | Approved (pre-existing) |

**Packages removed due to slopcheck:** N/A — no new packages.
**Packages flagged as suspicious:** N/A — no new packages.
**slopcheck run:** skipped — no new package install in this phase. If the
planner later identifies a new dep need (e.g., `python-frontmatter` for RFC
parsing), the planner MUST run the Package Legitimacy Gate before recommending
install. Recommended posture: the proposed rfc.lint design uses **stdlib only**
to avoid this need.

## Architecture Patterns

### System Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                      Operator (CLI invocation)                          │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│  src/folio_insights/governance/cli/                                     │
│    promote.py · contest.py · supersede.py · retract.py                  │
│    role_assert.py · role_revoke.py · corpus.py (corpus init)            │
│    governance_export.py                                                 │
│  (Each command: 1) parse args → 2) authorize() → 3) build event →       │
│   4) sign_attestation() → 5) governance_log.append() → 6) render UX)    │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            ▼                      ▼                      ▼
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│ authorize.py         │ │ events.py            │ │ promote.py /         │
│ (D-19 central        │ │ (GovernanceEvent     │ │ contest.py /         │
│  authorization)      │ │  discriminated union │ │ supersede.py /       │
│ • query active       │ │  over 13 classes;    │ │ retract.py /         │
│   roles at now via   │ │  Phase 6 SignedAction│ │ roles.py             │
│   GovernanceLog.     │ │  Literal extended    │ │ (per-event           │
│   query_active_      │ │  12 → 13 by adding   │ │  validators)         │
│   roles_at()         │ │  role_revocation)    │ │ • D-20 cite-resolve  │
│ • action-permission  │ │                      │ │ • D-21 status-kind   │
│   table              │ │                      │ │ • cascade-preview    │
│ • returns            │ │                      │ │   builder (retract)  │
│   Allow|Deny(reason) │ │                      │ │                      │
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘
            │                      │                      │
            └──────────────────────┼──────────────────────┘
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│  governance/log.py                                                      │
│    GovernanceLog Protocol (async; D-04 keeps storage libs OUT)          │
│    InMemoryGovernanceLog (in-phase impl; Phase 13 swaps SQLite behind)  │
│                                                                         │
│   append(event) →                                                       │
│     1. validate per-event SHACL shape (services/shacl_validator)        │
│     2. validate fi:GovernanceLogShape (append-only invariant)           │
│     3. verify_attestation() over event's AttestedSignature (Phase 6)    │
│     4. assign monotonic position (or carve-out: position=0 genesis)     │
│     5. persist + return event with position assigned                    │
└────────────────────┬──────────────────────────────────┬─────────────────┘
                     │                                  │
                     ▼                                  ▼
┌────────────────────────────────────┐  ┌────────────────────────────────┐
│  governance/shapes/  (TTL files)   │  │  identity/ (Phase 6, READ-ONLY) │
│    role_assertion_shape.ttl        │  │    sign_attestation            │
│    role_revocation_shape.ttl       │  │    verify_attestation          │
│    promotion_shape.ttl             │  │    DidDocCache (rotation-safe) │
│    contest_shape.ttl               │  │                                │
│    contest_resolution_shape.ttl    │  └────────────────────────────────┘
│    supersession_shape.ttl          │
│    retraction_shape.ttl            │  ┌────────────────────────────────┐
│    governance_log_shape.ttl        │  │  shards/envelope.py             │
│  (validated via                    │  │    SignedAction Literal         │
│   services/shacl_validator —       │  │    12 → 13 (+role_revocation)   │
│   pyshacl + rdflib live OUTSIDE    │  │  AttestedSignature              │
│   the governance/ boundary)        │  │    (Phase 6 D-13 — UNCHANGED)   │
└────────────────────────────────────┘  └────────────────────────────────┘

           ╔═══════════════════════════════════════════════════════════╗
           ║  Parallel mechanism: RFC linter (GOV-07)                  ║
           ║                                                            ║
           ║  python -m folio_insights.rfc.lint .planning/rfcs/         ║
           ║    │                                                        ║
           ║    ├── parse frontmatter (stdlib regex)                     ║
           ║    ├── validate filename NNNN-kebab-title.md                ║
           ║    ├── subprocess git log --follow --format=%H%n%s%n%b      ║
           ║    │     (walk full history per RFC file)                   ║
           ║    ├── re-parse frontmatter at each commit                  ║
           ║    └── assert monotonic status DAG +                        ║
           ║          "no body-only edit changes status"                 ║
           ║                                                            ║
           ║  RFC-TEMPLATE.md ships as golden fixture                   ║
           ╚═══════════════════════════════════════════════════════════╝
```

### Recommended Project Structure
```
src/folio_insights/governance/
├── __init__.py          # re-export GovernanceLog, GovernanceEvent, authorize, all event classes
├── log.py               # GovernanceLog Protocol + InMemoryGovernanceLog (D-04)
├── events.py            # GovernanceEvent discriminated union + 12 event classes (D-06)
├── authorize.py         # authorize(did, action, corpus) → Allow | Deny(reason)  (D-19)
├── roles.py             # RoleAssertionEvent + RoleRevocationEvent + active_roles_at(corpus, asof)
├── promote.py           # PromotionEvent + validate_promotion() (D-20/D-21)
├── contest.py           # ContestEvent + validate_contest()                  ┓
├── supersede.py         # SupersessionEvent + validate_supersession()        ┃ D-16
├── retract.py           # RetractionEvent + build_cascade_preview()          ┃ NO cross-imports
│                        # + classify_dependent() (D-18) + commit_cascade()   ┛
├── resolve_contest.py   # ContestResolutionEvent + 3 resolution paths (arbiter|distinguo|aporetic)
├── cli/
│   ├── __init__.py      # governance_group = click.Group("governance")
│   ├── promote.py       # folio-insights governance promote ...
│   ├── contest.py       # folio-insights governance contest ...      ┓ D-16
│   ├── supersede.py     # folio-insights governance supersede ...    ┃ each Click cmd
│   ├── retract.py       # folio-insights governance retract ...      ┛ in its own module
│   ├── role_assert.py   # folio-insights governance assert-role ...
│   ├── role_revoke.py   # folio-insights governance revoke-role ...
│   ├── governance_export.py  # folio-insights governance export <corpus>  (D-08)
│   └── corpus.py        # folio-insights corpus init --admin-did ...  (D-10)
└── shapes/
    ├── governance_log_shape.ttl       # fi:GovernanceLogShape (append-only D-05)
    ├── role_assertion_shape.ttl       # fi:RoleAssertionShape (incl. D-10 genesis carve-out)
    ├── role_revocation_shape.ttl      # fi:RoleRevocationShape (incl. D-11 lockout guard)
    ├── promotion_shape.ttl            # fi:PromotionShape
    ├── contest_shape.ttl              # fi:ContestShape
    ├── contest_resolution_shape.ttl   # fi:ContestResolutionShape (3 paths; no majority-vote)
    ├── supersession_shape.ttl         # fi:SupersessionShape
    └── retraction_shape.ttl           # fi:RetractionShape

src/folio_insights/rfc/
├── __init__.py
├── lint.py              # python -m folio_insights.rfc.lint .planning/rfcs/
├── frontmatter.py       # parse + validate (Pydantic model)
└── git_history.py       # subprocess.run("git log ...") walk

.planning/rfcs/
└── RFC-TEMPLATE.md      # golden fixture for the linter (D-02)

tests/governance/
├── test_role_assertion_signed.py
├── test_promotion_requires_citation.py
├── test_demotion_creates_fresh_ttl.py
├── test_contested_state_records_votes.py
├── test_arbiter_can_resolve_contest.py
├── test_governance_log_is_append_only.py        # Protocol contract test (D-05)
├── test_governance_log_exports_as_provo.py
├── test_no_majority_vote_resolution.py          # GOV-05 explicit-rejection
├── test_grep_guard_three_way_disambiguation.py  # D-16
├── test_last_admin_self_revocation_refused.py   # D-11 / F6
├── test_genesis_self_signed_carveout.py         # D-10
├── test_cascade_preview_classification.py       # D-18 (auto_rederive/aporetic/review_needed)
├── test_preview_stale_refusal.py                # D-17 --apply on changed state
├── test_unsigned_promotion_rejected.py          # acceptance bar
├── test_role_revocation_distinct_event.py       # D-13
├── test_signed_action_literal_13_values.py      # envelope.py:85 extension audit
├── test_authorize_central.py                    # D-19 action-permission table
└── test_dep_leak_guard.py                       # NO aiosqlite/rdflib/pyoxigraph in governance/

tests/rfc/
├── test_lint_frontmatter_schema.py
├── test_lint_filename_monotonic.py
├── test_lint_status_monotonic_across_history.py
├── test_lint_body_only_edit_refused.py
└── fixtures/                                    # synthetic .planning/rfcs/ trees + git repos
```

### Pattern 1: GovernanceEvent Discriminated Union (D-06)

**What:** Single Pydantic discriminated union over 12 event subclasses, each
embedding an `AttestedSignature` and discriminated by the
`SignedAction` Literal value on that signature.

**When to use:** Every governance write goes through `governance_log.append(event:
GovernanceEvent)`. The discriminator is the action string.

**Example:**
```python
# Source: pydantic 2 docs (Annotated discriminated unions) — [CITED: docs.pydantic.dev/latest/concepts/unions/#discriminated-unions]
# Pattern adapted from Phase 2 ShardType discriminator (shards/subtypes.py).

from __future__ import annotations
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from folio_insights.shards.envelope import AttestedSignature  # Phase 6 D-13


class _BaseEvent(BaseModel):
    """Shared envelope discipline; NOT a behavior-sharing base class (D-16)."""
    model_config = ConfigDict(extra="forbid")
    corpus: str
    position: int = -1  # assigned by GovernanceLog.append()
    signature: AttestedSignature


class RoleAssertionEvent(_BaseEvent):
    action: Literal["role_assertion"] = "role_assertion"
    subject_did: str
    role: Literal["extractor", "reviewer", "arbiter", "corpus_admin"]


class RoleRevocationEvent(_BaseEvent):
    action: Literal["role_revocation"] = "role_revocation"
    subject_did: str
    revoked_role: Literal["extractor", "reviewer", "arbiter", "corpus_admin"]


class PromotionEvent(_BaseEvent):
    action: Literal["promote"] = "promote"
    shard_iri: str
    new_status: Literal["per_se_nota_quoad_nos", "demonstrable", "authority_only"]
    cited_iris: list[str] = Field(min_length=1)  # D-20 non-empty


class ContestEvent(_BaseEvent):
    action: Literal["contest"] = "contest"
    shard_iri: str
    voter_did: str
    position: str  # the reviewer's textual position


class ContestResolutionEvent(_BaseEvent):
    action: Literal["resolve_contest"] = "resolve_contest"
    shard_iri: str
    resolution_path: Literal["arbiter", "distinguo", "aporetic"]  # GOV-05 — no majority-vote


class SupersessionEvent(_BaseEvent):
    action: Literal["supersede"] = "supersede"
    old_shard_iri: str
    new_shard_iri: str


class RetractionEvent(_BaseEvent):
    action: Literal["retract"] = "retract"
    shard_iri: str
    cascade_preview_hash: str  # commits the preview the operator confirmed (D-17)


# Plus: ExtractEvent, DemotionEvent, DistinguoEvent, ContentEditEvent,
#       ReparentEvent, ReconcileEvent (one each, matching SignedAction Literal).


GovernanceEvent = Annotated[
    Union[
        RoleAssertionEvent, RoleRevocationEvent,
        PromotionEvent, ContestEvent, ContestResolutionEvent,
        SupersessionEvent, RetractionEvent,
        # ... (all 12)
    ],
    Field(discriminator="action"),
]
```

### Pattern 2: `GovernanceLog` Protocol Seam (D-04, mirrors Phase 5 `ShardStore` + Phase 6 `DidDocCache`)

**What:** Thin async `Protocol` over an in-memory dict (in-phase) that Phase 13
swaps `aiosqlite` behind without touching any caller.

**When to use:** Every CLI / API / future-web write through this seam. No
direct dict access anywhere outside `log.py`.

**Example:**
```python
# Source: mirrors src/folio_insights/identity/cache.py + src/folio_insights/revision/store.py
from __future__ import annotations
from datetime import datetime
from typing import AsyncIterator, Protocol, runtime_checkable

from folio_insights.governance.events import GovernanceEvent


@runtime_checkable
class GovernanceLog(Protocol):
    """Append-only governance log seam (D-04). Phase 13 swaps SQLite behind it."""

    async def append(self, event: GovernanceEvent) -> GovernanceEvent:
        """Validate SHACL + AttestedSignature, assign monotonic position, persist."""
        ...

    async def query_active_roles_at(
        self, corpus: str, asof: datetime,
    ) -> dict[str, set[str]]:
        """Return {subject_did → {role, ...}} active at asof (assertions minus revocations).

        D-13: active-roles query = role_assertions windowed by signed_at <= asof,
        minus role_revocations also windowed by signed_at <= asof.
        """
        ...

    async def get_by_position(self, corpus: str, position: int) -> GovernanceEvent | None: ...

    async def iter_events(self, corpus: str) -> AsyncIterator[GovernanceEvent]: ...

    async def latest_position(self, corpus: str) -> int:
        """Return -1 if empty (next append is position 0 — the genesis row)."""
        ...


class InMemoryGovernanceLog:
    """Process-local in-memory GovernanceLog. Reset per construction (test isolation).

    Stdlib + Pydantic ONLY. NO aiosqlite / rdflib / pyoxigraph imports — D-04.
    """
    def __init__(self) -> None:
        self._by_corpus: dict[str, list[GovernanceEvent]] = {}
    # ... (implements Protocol; append-only by construction — no public mutator on past rows)
```

### Pattern 3: Genesis Carve-Out (D-10) + Last-Admin Refusal (D-11) — Append Body

**What:** The single bottleneck `append()` runs all validation. Genesis is the
only branch where self-signed `role_assertion` for `role=corpus_admin` is
accepted, and only at `position=0`. Last-admin self-revocation is hard-refused
inside the same function (the SHACL belt — D-19 belt-and-suspenders — is the
suspenders).

**Example:**
```python
class WouldLockoutCorpusAdmin(ValueError):
    """D-11: revocation would leave corpus with 0 active corpus_admins."""


async def append(self, event: GovernanceEvent) -> GovernanceEvent:
    # 1. SHACL: per-event shape + fi:GovernanceLogShape append-only invariant
    validate_event_shape(event)
    validate_governance_log_shape(self._by_corpus.get(event.corpus, []), event)

    # 2. Position assignment
    next_pos = await self.latest_position(event.corpus) + 1
    event = event.model_copy(update={"position": next_pos})

    # 3. Verify the AttestedSignature.
    #    Genesis carve-out (D-10): position=0 + self-signed + role=corpus_admin.
    is_genesis = (
        next_pos == 0
        and isinstance(event, RoleAssertionEvent)
        and event.role == "corpus_admin"
        and event.subject_did == event.signature.did  # self-signed
    )
    if not is_genesis:
        # Every later row requires existing-admin signature verifiable against the log.
        if not await verify_attestation(event.signature_payload(), event.signature, cache=...):
            raise InvalidSignature(...)
        signer_roles = (await self.query_active_roles_at(
            event.corpus, event.signature.signed_at,
        )).get(event.signature.did, set())
        # authorize() runs in the CLI as first step (D-19); here we re-check for the
        # API/future-web path (defense in depth — D-19 explicit goal).
        if "corpus_admin" not in signer_roles and isinstance(event, RoleAssertionEvent):
            raise NotAuthorized(...)

    # 4. D-11: last-admin self-revocation refusal
    if isinstance(event, RoleRevocationEvent) and event.revoked_role == "corpus_admin":
        admins_now = {
            did for did, roles in (await self.query_active_roles_at(
                event.corpus, event.signature.signed_at,
            )).items()
            if "corpus_admin" in roles
        }
        if event.subject_did in admins_now and len(admins_now) == 1:
            raise WouldLockoutCorpusAdmin(
                "revocation would leave the corpus with 0 active corpus_admins; "
                "appoint a successor first"
            )

    # 5. Persist
    self._by_corpus.setdefault(event.corpus, []).append(event)
    return event
```

### Pattern 4: Cascade-Preview Builder (D-17 / D-18)

**What:** A shared `build_cascade_preview(corpus, shard_iri)` function runs the
SPARQL CONSTRUCT against `(ShardStore, GovernanceLog)`, classifies dependents by
D-18, returns a `CascadePreview` Pydantic model. All three modes (interactive,
`--preview`, `--apply`) call the same builder; only the commit step differs.

**Why this is a single function:** D-17 says all three modes share the
preview-builder — only the commit step (`commit_cascade(preview)`) differs.

**Example skeleton:**
```python
class CascadePreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)  # immutable preview
    retracted_shard_iri: str
    corpus: str
    taken_at: datetime
    underlying_state_hash: str  # for PreviewStale detection on --apply
    auto_rederive: list[str]    # dependent IRIs
    aporetic: list[str]
    review_needed: list[str]


async def build_cascade_preview(
    retracted_iri: str, corpus: str,
    *, store: ShardStore, log: GovernanceLog,
) -> CascadePreview:
    dependents = await _query_dependents(retracted_iri, store)  # SPARQL CONSTRUCT
    classified = {bucket: [] for bucket in ("auto_rederive", "aporetic", "review_needed")}
    for dep_iri in dependents:
        bucket = await _classify_dependent(dep_iri, retracted_iri, store, log)
        classified[bucket].append(dep_iri)
    return CascadePreview(
        retracted_shard_iri=retracted_iri,
        corpus=corpus,
        taken_at=datetime.now(UTC),
        underlying_state_hash=await _hash_underlying_state(retracted_iri, store, log),
        **classified,
    )


async def commit_cascade(preview: CascadePreview, *, log: GovernanceLog,
                         signing_key: Ed25519PrivateKey, did: str) -> RetractionEvent:
    # On --apply: re-run build_cascade_preview, compare underlying_state_hash;
    # raise PreviewStale if changed.
    current = await build_cascade_preview(preview.retracted_shard_iri, preview.corpus,
                                          store=..., log=log)
    if current.underlying_state_hash != preview.underlying_state_hash:
        raise PreviewStale(
            f"underlying state changed since preview taken at {preview.taken_at}; "
            f"re-run --preview"
        )
    # Build RetractionEvent committing the preview hash, sign, append.
    event = RetractionEvent(..., cascade_preview_hash=_hash(preview))
    event_signed = sign_and_attest(event, signing_key, did)
    return await log.append(event_signed)
```

### Anti-Patterns to Avoid

- **Shared `disagree()` helper across contest/supersede/retract** — D-16 grep-guard
  fails CI. Three modules, three event classes, three SHACL shapes. The
  `AttestedSignature` is the ONLY shared primitive.
- **`disagree(kind: Literal["contest", "supersede", "retract"], ...)` single function** —
  same violation; the discriminator pattern hides the three distinct workflows
  behind one entrypoint. **Forbidden.**
- **Direct `aiosqlite` / `rdflib` / `pyoxigraph` imports inside `governance/`** —
  breaks D-04 seam discipline. Phase 13 swaps backend behind the Protocol;
  storage libs live in `services/shacl_validator.py` (validator wrapper) and
  future Phase 13 storage modules, never in `governance/`. Grep-guard test
  mirrors `tests/shards/test_dep_leak_guard.py`.
- **Eager Turtle write on every append** — D-08 says on-demand only. The
  in-phase `InMemoryGovernanceLog` never writes Turtle; Phase 13 wires the
  on-demand export.
- **Authorization scattered across CLI commands** — D-19 says ONE function.
  Every command's first step after parsing is `authorize(did, action,
  corpus)`. Test that every CLI command calls it.
- **Majority-vote resolution path** — GOV-05 + PRD §3.1.3 explicitly reject
  this. The `ContestResolutionEvent.resolution_path` Literal has exactly
  three values; an explicit-rejection test asserts no fourth code path
  exists.
- **GitPython for rfc.lint** — minimal-deps discipline; subprocess `git log`
  with stable `--format=%H%n%P%n%s%n%b%n--END--` works fine and adds no deps.
- **Frontmatter YAML lib dep** — RFC frontmatter is structurally trivial
  (`---` delimited, `key: value` lines). Stdlib regex is sufficient; no
  `python-frontmatter` or `PyYAML` needed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Append-only enforcement | Custom rdflib `before_write` hook from scratch | `fi:GovernanceLogShape` SHACL `sh:sparql` constraint (Phase 5 `content_edit_shape.ttl` is the template) + Phase 13 SQLite trigger | Pattern proven Phase 5; pyshacl 0.31.0 sh:sparql verified live in Phase 5 RESEARCH |
| DID signature verification | Re-implement ed25519 verify in `governance/` | Phase 6 `verify_attestation(payload, sig, cache=...)` | Single fact-of-truth (Phase 6 D-19 precedent for Phase 7's D-19); rotation-survival already proven by 1000-shard property test |
| Canonical content hashing | Re-implement JCS pre-normalization | Phase 5 `revision.content_edit.canonical_content_hash` | F4 pre-normalization recipe is already locked + tested cross-impl against cyberphone reference |
| Frontmatter parsing | Bring in `python-frontmatter` or `PyYAML` | Stdlib regex (`re.compile(r"^---\n(.*?)\n---\n", re.S)`) + per-line `key: value` split | Frontmatter is structurally trivial; saves a dep + slopsquat surface |
| Git history walking | GitPython | `subprocess.run(["git", "log", "--follow", "--format=...", path], check=True, text=True)` | Zero deps; CI portability; well-known semantics |
| Click command discovery | Custom dispatcher | `@click.group()` + `cli.add_command(governance_group)` per Phase 1 polysemy + Phase 6 did | Identical idiom across phases; no new patterns to learn |
| Test environment seeding | Custom git repo builder | `git init` + `git commit` in `tmp_path` via `subprocess.run(...)` | Direct, debuggable; the rfc.lint test fixtures need a real git tree anyway |
| Pydantic discriminated union plumbing | Hand-roll `if action == "..."` dispatch | `Annotated[Union[...], Field(discriminator="action")]` | Pydantic 2 canonical; per-class field validation; runtime + IDE introspection |

**Key insight:** Every primitive Phase 7 needs has been proven in Phases 2 / 5 /
6 — the work is **composition + discipline**, not net-new algorithms. The
exceptions are (a) the cascade-preview SPARQL CONSTRUCT (genuinely new query
work) and (b) the rfc.lint git-history walk (mechanical but new).

## Runtime State Inventory

> Skipping in detail — Phase 7 is a **greenfield-add** phase (no rename / refactor /
> migration). The only "runtime state" concern is the `SignedAction` Literal
> extension at `src/folio_insights/shards/envelope.py:85` (12 → 13 values), and
> that's a code change, not stored-data migration.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no existing governance log to migrate; corpus init writes row 0 | None |
| Live service config | None — no live deployment of governance yet (Phase 7 first ship) | None |
| OS-registered state | None — no scheduled tasks / pm2 processes mention governance | None |
| Secrets/env vars | None — reuses Phase 6 `~/.folio-insights/` ed25519 keyfile; no new env vars | None |
| Build artifacts | **`SignedAction` Literal at `shards/envelope.py:85`** — extending 12 → 13 values (adding `role_revocation`). Audit: 2 callers in tree — `identity/signer.py:36` (imports the Literal), `identity/preview.py` (DID-07 preview iterates the subset). Both accept the new value without code change (Literal is a TypeAlias; subset iteration is hardcoded in `preview.py` and does NOT need to grow per D-13). | Code edit at `envelope.py:85` adding `"role_revocation"`. Audit `grep -rn "SignedAction" src/` confirms only Literal-typed annotations downstream (no exhaustive `match` statement to extend). Add `tests/governance/test_signed_action_literal_13_values.py` asserting `len(get_args(SignedAction)) == 13`. |

## Common Pitfalls

### Pitfall 1: F5 (Append-Only Bypass) — SHACL Enforced, Storage Forgot

**Source:** `.planning/research/PITFALLS.md` F5 (PITFALLS L312-339)

**What goes wrong:** SHACL refuses DELETE on the RDF graph, but the in-memory
dict (Phase 7) and the Phase 13 aiosqlite backend can still drop rows via
direct dict mutation / SQLite UPDATE — bypassing SHACL entirely. Append-only
invariant silently broken; audit log no longer tamper-evident.

**Why it happens:** Conflating "shape says no delete" with "storage can't
delete."

**How to avoid:**
- `InMemoryGovernanceLog` has **no public mutation API on past rows** —
  `append()` is the only mutator; no `update()`, `remove()`, `truncate()`. The
  Protocol contract test enumerates the public surface and asserts none of
  those names exist (D-05 amendment requires both halves: SHACL + Protocol
  contract).
- `fi:GovernanceLogShape` SHACL: `sh:sparql` constraint that flags violations
  when any row's `fi:position` is **missing** in the snapshot (gap = deletion)
  OR when any row's content hash differs from the chain-recorded predecessor
  hash. Mirrors Phase 5 `content_edit_shape.ttl` `sh:sparql` polarity discipline.
- Phase 13 follow-on: SQLite trigger `BEFORE UPDATE/DELETE ON governance_log
  → RAISE FAIL`. Travels forward per D-05; Phase 7 documents the requirement
  but does not implement.
- Hash-chain (optional but recommended): each event's `over_content_hash` 
  includes a hash of the prior event's signature bytes — tampering breaks the
  chain deterministically. Phase 7 can ship this as part of the canonical
  payload; Phase 19 audit re-walks.

**Warning signs:** governance-log event count decreasing between snapshots;
`fi:position` gaps; chain-hash verification failures.

### Pitfall 2: F6 (Corpus-Admin Self-Revocation Lockout)

**Source:** `.planning/research/PITFALLS.md` F6 (PITFALLS L343-362)
+ D-09 / D-10 / D-11 / D-12 / D-13 (CONTEXT.md)

**What goes wrong:** Sole corpus_admin signs a `RoleRevocation` for themselves.
Corpus has 0 active admins. No further role changes possible without forking.

**Why it happens:** Self-referential authorization without a safety net.

**How to avoid:** D-11 closes this. `append()` for a `RoleRevocationEvent`
where `revoked_role == "corpus_admin"` must query active admins at
`signature.signed_at`; if revoking would leave **0** admins, raise
`WouldLockoutCorpusAdmin` (the user-facing error string is locked verbatim:
`"revocation would leave the corpus with 0 active corpus_admins; appoint a
successor first"`). SHACL `fi:RoleRevocationShape` is the belt; the code is
the suspenders.

**Warning signs:** any corpus with `active_admins_count == 1` is one
revocation away from lockout; surfaced as a metric in Phase 12 observability.

### Pitfall 3: F2 (Key-Rotation Resolved at Verification Time)

**Source:** `.planning/research/PITFALLS.md` F2 (PITFALLS L212-240)
+ Phase 6 D-11 / D-13 already mitigated.

**What goes wrong:** Reviewer rotates DID key; verifier checks historical
signature against current key; valid historical attestation reads as invalid.

**Why it happens:** Naive "current key" resolution.

**How to avoid:** Phase 7 **does not re-solve** — every event embeds an
`AttestedSignature` with `signing_key_id` + `did_doc_snapshot_at`, and Phase
6's `verify_attestation` already resolves the signing-time key via
`DidDocCache` (proven by `test_signature_survives_key_rotation.py`). The
active-roles-at-signing query in `roles.py` MUST window by
`signature.signed_at` (NOT `datetime.now()`), so a role asserted in 2026 and
later revoked in 2027 returns "active" for events signed in 2026.5. This is
the windowing semantics the existing Phase 6 cache supports.

**Warning signs:** historical promotions transitioning `verified=True →
False` without content edits; signers with rotated keys producing "no active
role" results in queries at `signed_at`.

### Pitfall 4: F1 (Cascade Collapses Distinction with Supersession)

**Source:** `.planning/research/PITFALLS.md` F1 (PITFALLS L181 area) +
PRD §21.9 (supersession ≠ retraction).

**What goes wrong:** The cascade-preview classifier marks a dependent
`auto_rederive` because a superseding shard exists, but the operator actually
intended retraction (the citation was wrong, not stale). Classifier blurs
F1's locked distinction.

**Why it happens:** D-18 heuristic uses supersession-availability as the
`auto_rederive` signal. But supersession-availability does not mean
"supersession is appropriate"; it just means "a superseding shard exists."

**How to avoid:** D-18 also requires `reconciliation_strategy == "prefer_latest"`
on the dependent — i.e., the dependent has already opted into "trust newer."
Without that flag, the dependent goes to `review_needed`. The grep-guard +
the explicit-rejection test enforce: `auto_rederive` requires BOTH the
supersession existence AND the `prefer_latest` policy.

**Warning signs:** spike in `auto_rederive` cascades for shards whose
reconciliation_strategy is NOT `prefer_latest`; surfaced as a Phase 12 metric.

### Pitfall 5: D-17 Preview-Stale Race

**What goes wrong:** Operator runs `governance retract --preview` → reviews
JSON report → comes back next morning → runs `governance retract --apply
report.json`. In the interim, another reviewer committed a supersession on
one of the dependents; the preview's classification is now stale.

**Why it happens:** `--apply` reads a frozen JSON file; the underlying corpus
graph has moved.

**How to avoid:** D-17 mandates `PreviewStale` refusal. `CascadePreview`
includes `underlying_state_hash` (hash of {dependent_iri → relevant_fields}
across the dependent set). `commit_cascade(preview)` re-runs
`build_cascade_preview(...)` and compares the hash. If different, raise
`PreviewStale` and tell the operator to re-preview. Tests:
`test_preview_stale_refusal.py` simulates two operators racing.

**Warning signs:** Phase 12 metric: `cascade_preview_stale_refusals_total > 0`
in normal operation. Spike means UI/CLI flow needs to shorten the
preview-to-apply window.

### Pitfall 6: U1 (Verification Badge Doesn't Distinguish Current vs Historical Key)

**Source:** `.planning/research/PITFALLS.md` U1 (PITFALLS L875)

**What goes wrong:** UI shows green for both "verified by current DID key" and
"verified by historical DID key" — users can't tell trust levels apart.

**How to avoid:** **Out of Phase 7 scope** (D-03 — web UI deferred), but
locking the data shape now is in scope: every `AttestedSignature.verified`
is `True | False | None`, and the verifier should ALSO emit
`signing_key_status: Literal["current", "rotated_out", "unknown"]` if the
post-Phase-14 web phase wants to render a 3-state badge. Phase 7 can defer
the field; document the gap in `<deferred>` so post-Phase-14 owns it.

**Warning signs:** post-Phase-14 web phase complains that "verified=True" is
not enough information for the badge.

## Code Examples

### SHACL: `fi:GovernanceLogShape` Append-Only (mirrors `content_edit_shape.ttl`)

```turtle
# Source: mirrors src/folio_insights/revision/content_edit_shape.ttl (Phase 5)
# spiked live against pyshacl 0.31.0 / rdflib 7.6.0.
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix fi: <https://folio-insights.example/> .
@prefix prov: <http://www.w3.org/ns/prov#> .

fi:GovernanceLogShape a sh:NodeShape ;
    sh:targetClass fi:GovernanceLog ;

    # 1. Monotonic position: no two events share the same position; no gaps.
    sh:sparql [
        sh:message "Governance log positions must be monotonic and gap-free (append-only D-05)" ;
        sh:select '''
            SELECT $this ?pos1 ?pos2 WHERE {
                $this fi:hasEvent ?e1, ?e2 .
                ?e1 fi:position ?pos1 .
                ?e2 fi:position ?pos2 .
                FILTER(?pos1 = ?pos2 && STR(?e1) != STR(?e2))
            }
        ''' ;
    ] ;

    # 2. Every event must carry a signature; the signature's signed_at must be
    #    monotonically non-decreasing with position (prevents back-dating).
    sh:sparql [
        sh:message "Event signed_at must be monotonically non-decreasing with position" ;
        sh:select '''
            SELECT $this ?e1 ?e2 WHERE {
                $this fi:hasEvent ?e1, ?e2 .
                ?e1 fi:position ?p1 ; fi:signedAt ?t1 .
                ?e2 fi:position ?p2 ; fi:signedAt ?t2 .
                FILTER(?p1 < ?p2 && ?t2 < ?t1)
            }
        ''' ;
    ] .
```

### SHACL: `fi:RoleAssertionShape` (with D-10 Genesis Carve-Out)

```turtle
# fi:RoleAssertionShape — every RoleAssertion must be signed by an existing
# corpus_admin EXCEPT the genesis row (position=0 + self-signed + role=corpus_admin).
# The genesis carve-out is the ONLY structural exception in the log.
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix fi: <https://folio-insights.example/> .

fi:RoleAssertionShape a sh:NodeShape ;
    sh:targetClass fi:RoleAssertion ;
    sh:property [
        sh:path fi:role ;
        sh:in ("extractor" "reviewer" "arbiter" "corpus_admin") ;
        sh:minCount 1 ; sh:maxCount 1 ;
    ] ;
    sh:property [ sh:path fi:subjectDid ; sh:datatype xsd:string ; sh:minCount 1 ; sh:maxCount 1 ] ;
    sh:sparql [
        sh:message "Non-genesis role-assertion must be signed by a corpus_admin (D-10/D-19)" ;
        sh:select '''
            SELECT $this ?signer WHERE {
                $this fi:position ?pos ;
                      fi:subjectDid ?subj ;
                      fi:role ?role ;
                      fi:signature/fi:did ?signer .
                # NOT the genesis carve-out:
                FILTER NOT EXISTS {
                    FILTER(?pos = 0 && ?signer = ?subj && ?role = "corpus_admin")
                }
                # Signer must hold corpus_admin at signature.signed_at.
                FILTER NOT EXISTS {
                    ?signer fi:hasActiveRoleAt ("corpus_admin" ?signedAt) .
                }
            }
        ''' ;
    ] .
```

### SHACL: `fi:RoleRevocationShape` (with D-11 Last-Admin Refusal)

```turtle
# fi:RoleRevocationShape — D-11 refuses any role_revocation that would leave
# the corpus with 0 active corpus_admins. SHACL is the belt; code is the
# suspenders (the user-facing WouldLockoutCorpusAdmin error string is raised
# from authorize.py and the InMemoryGovernanceLog.append() function).
fi:RoleRevocationShape a sh:NodeShape ;
    sh:targetClass fi:RoleRevocation ;
    sh:sparql [
        sh:message "Revocation would leave corpus with 0 active corpus_admins (D-11)" ;
        sh:select '''
            SELECT $this WHERE {
                $this fi:revokedRole "corpus_admin" ;
                      fi:subjectDid ?subj .
                # Count active corpus_admins at signed_at (assertions minus prior revocations).
                {
                    SELECT (COUNT(DISTINCT ?admin) AS ?cnt) WHERE {
                        ?admin fi:hasActiveRoleAt ("corpus_admin" $signedAt) .
                    }
                }
                FILTER(?cnt = 1)
            }
        ''' ;
    ] .
```

### SHACL: `fi:PromotionShape` (D-20 + D-21)

```turtle
# fi:PromotionShape — D-20: cited IRIs non-empty + resolvable; D-21: status
# consistent with citation kind. Resolvability is a code-level validator (the
# shard store lives outside SHACL); SHACL enforces non-empty + status-kind.
fi:PromotionShape a sh:NodeShape ;
    sh:targetClass fi:Promotion ;
    sh:property [
        sh:path fi:newStatus ;
        sh:in ("per_se_nota_quoad_nos" "demonstrable" "authority_only") ;
        sh:minCount 1 ; sh:maxCount 1 ;
    ] ;
    sh:property [
        sh:path fi:citedIri ;
        sh:minCount 1 ;  # D-20: non-empty
    ] ;
    # D-21 status-kind cross-check is in promote.py's validate_promotion(); SHACL
    # cannot reach into the cited shard's authority kind (cross-shard lookup).
    .
```

### Grep-Guard Regression Test (D-16) — Mirrors Phase 2 `test_dep_leak_guard.py`

```python
# Source: mirrors tests/shards/test_dep_leak_guard.py (Phase 2)
"""D-16 grep-guard: contest/supersede/retract must NOT share codepaths.

Fails CI if:
  (a) any of the three modules imports from another,
  (b) any base class beyond GovernanceEvent / _BaseEvent is shared,
  (c) the three Click commands share an implementation function.
"""
from __future__ import annotations
import ast
import pathlib
import pytest

from folio_insights import governance

pytestmark = pytest.mark.governance


THREE_WAY = ("contest", "supersede", "retract")


@pytest.mark.parametrize("module_name", THREE_WAY)
def test_three_way_modules_do_not_cross_import(module_name: str) -> None:
    """Each module must not import from the other two."""
    gov_dir = pathlib.Path(governance.__file__).parent
    source = (gov_dir / f"{module_name}.py").read_text(encoding="utf-8")
    other_modules = [m for m in THREE_WAY if m != module_name]
    for other in other_modules:
        assert f"from folio_insights.governance.{other}" not in source, (
            f"{module_name}.py imports from {other}.py — D-16 forbids "
            "cross-imports among contest/supersede/retract"
        )
        assert f"import folio_insights.governance.{other}" not in source, (
            f"{module_name}.py imports {other}.py — D-16 forbids"
        )


@pytest.mark.parametrize("module_name", THREE_WAY)
def test_three_way_event_classes_share_only_base_event(module_name: str) -> None:
    """Each event class inherits only from _BaseEvent (no shared behavior base)."""
    gov_dir = pathlib.Path(governance.__file__).parent
    source = (gov_dir / f"{module_name}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    event_classes = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and "Event" in n.name
    ]
    for cls in event_classes:
        bases = {ast.unparse(b) for b in cls.bases}
        # Allowed base names: _BaseEvent, BaseModel (Pydantic), and combinations.
        forbidden_shared = {"ContestSupersedeBase", "DisagreementEvent", "DisputeEvent"}
        assert not (bases & forbidden_shared), (
            f"{module_name}.{cls.name} inherits from a shared-disagreement "
            f"base class ({bases & forbidden_shared}) — D-16 forbids any "
            f"behavior-sharing base beyond _BaseEvent / GovernanceEvent"
        )


def test_three_way_click_commands_share_no_impl() -> None:
    """The three Click commands must not delegate to a shared helper function."""
    cli_dir = pathlib.Path(governance.__file__).parent / "cli"
    impls = {}
    for module_name in THREE_WAY:
        source = (cli_dir / f"{module_name}.py").read_text(encoding="utf-8")
        # Heuristic: look for a call to a function defined outside this module
        # that takes (event_type, ...) — the canonical "unified disagreement
        # implementation" smell.
        forbidden_helpers = (
            "execute_disagreement",
            "_dispatch_disagreement",
            "handle_disputed_action",
        )
        for helper in forbidden_helpers:
            assert helper not in source, (
                f"cli/{module_name}.py calls {helper}() — D-16 forbids any "
                "shared Click implementation function across the three commands"
            )
```

### Dep-Leak Guard Test (`tests/governance/test_dep_leak_guard.py`)

```python
"""Phase 13 dep-leak guard: governance/ must not import storage libs (D-04).

Mirrors tests/shards/test_dep_leak_guard.py — the same discipline that kept
shards/ RDF-free in Phase 2 keeps governance/ storage-free in Phase 7.
Phase 13 fills the GovernanceLog Protocol seam with the storage backend.
"""
from __future__ import annotations
import pathlib
import pytest

from folio_insights import governance

pytestmark = pytest.mark.governance

FORBIDDEN = ["aiosqlite", "rdflib", "pyoxigraph", "oxrdflib"]


@pytest.mark.parametrize("module_name", FORBIDDEN)
def test_no_storage_import_in_governance(module_name: str) -> None:
    gov_dir = pathlib.Path(governance.__file__).parent
    for module_file in gov_dir.rglob("*.py"):
        source = module_file.read_text(encoding="utf-8")
        assert f"import {module_name}" not in source, (
            f"{module_file.relative_to(gov_dir)}: D-04 forbids importing "
            f"{module_name} (storage lives in Phase 13 backend behind "
            "GovernanceLog Protocol)"
        )
        assert f"from {module_name}" not in source, (
            f"{module_file.relative_to(gov_dir)}: D-04 forbids "
            f"from {module_name} import ..."
        )
```

### RFC Linter — Git History Walk (D-22)

```python
# Source: minimal-deps; stdlib subprocess + pathlib + re only.
"""python -m folio_insights.rfc.lint .planning/rfcs/

Validates frontmatter schema, filename pattern, monotonic numbering, and
status-transition DAG across full git history. Runs in CI.
"""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


RFC_FILENAME_RE = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]*\.md$")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
ALLOWED_TRANSITIONS = {
    "draft": {"discussion"},
    "discussion": {"accepted", "rejected"},
    "accepted": {"implemented"},
    "rejected": set(),       # terminal
    "implemented": set(),    # terminal
}


class RFCFrontmatter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rfc: int = Field(ge=1)
    title: str
    status: Literal["draft", "discussion", "accepted", "rejected", "implemented"]
    authors: list[str]  # list of DID strings
    created: str        # ISO date
    superseded_by: int | None = None


def parse_frontmatter(text: str) -> RFCFrontmatter:
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("missing frontmatter block")
    body = match.group(1)
    data: dict = {}
    current_list_key: str | None = None
    for line in body.splitlines():
        if line.startswith("- ") and current_list_key is not None:
            data[current_list_key].append(line[2:].strip())
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not value:
            # next lines may be a list
            data[key] = []
            current_list_key = key
        elif value.isdigit():
            data[key] = int(value)
        else:
            data[key] = value
    return RFCFrontmatter.model_validate(data)


def git_log_commits_for_file(path: Path) -> list[dict]:
    """Return [{sha, subject, body, frontmatter_status}, ...] oldest-first."""
    result = subprocess.run(
        ["git", "log", "--follow", "--reverse",
         "--format=%H%n%s%n--BODY--%n%b%n--END--", "--", str(path)],
        check=True, capture_output=True, text=True,
    )
    commits = []
    for entry in result.stdout.split("--END--\n"):
        if not entry.strip():
            continue
        sha_line, rest = entry.split("\n", 1)
        subject, _, body = rest.partition("--BODY--\n")
        # Re-read the file AT this commit:
        try:
            content = subprocess.run(
                ["git", "show", f"{sha_line}:{path}"],
                check=True, capture_output=True, text=True,
            ).stdout
            fm = parse_frontmatter(content)
            commits.append({"sha": sha_line, "subject": subject.strip(),
                            "body": body, "status": fm.status})
        except (subprocess.CalledProcessError, ValueError, ValidationError):
            continue  # file didn't exist or no frontmatter at this commit
    return commits


def validate_rfc_file(path: Path) -> list[str]:
    """Return list of error messages; empty list means PASS."""
    errors: list[str] = []

    # 1. Filename
    m = RFC_FILENAME_RE.match(path.name)
    if not m:
        return [f"{path}: filename must match NNNN-kebab-title.md"]
    file_number = int(m.group(1))

    # 2. Current frontmatter
    try:
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (ValueError, ValidationError) as e:
        return [f"{path}: frontmatter invalid — {e}"]
    if fm.rfc != file_number:
        errors.append(f"{path}: rfc:{fm.rfc} does not match filename {file_number:04d}")

    # 3. History walk + monotonic transition DAG
    history = git_log_commits_for_file(path)
    prev_status = None
    for entry in history:
        cur = entry["status"]
        if prev_status is not None and cur != prev_status:
            if cur not in ALLOWED_TRANSITIONS.get(prev_status, set()):
                errors.append(
                    f"{path} commit {entry['sha'][:8]}: forbidden status transition "
                    f"{prev_status} → {cur} (allowed: {ALLOWED_TRANSITIONS[prev_status]})"
                )
            # No body-only edit may change status (D-22):
            # require Reason: trailer in body OR status_change_reason: in frontmatter delta.
            body_has_reason = bool(re.search(r"(?m)^Reason:\s", entry["body"]))
            # status_change_reason check is done by re-reading frontmatter at this commit;
            # we already have entry["status"] but would need full frontmatter dict for that.
            if not body_has_reason:
                errors.append(
                    f"{path} commit {entry['sha'][:8]}: status changed "
                    f"{prev_status} → {cur} but commit has no 'Reason:' trailer "
                    "and no 'status_change_reason:' frontmatter line"
                )
        prev_status = cur

    return errors


def main(directory: Path) -> int:
    all_errors: list[str] = []
    seen_numbers: set[int] = set()
    for path in sorted(directory.glob("*.md")):
        if path.name == "RFC-TEMPLATE.md":
            continue  # the golden fixture
        m = RFC_FILENAME_RE.match(path.name)
        if m:
            n = int(m.group(1))
            if n in seen_numbers:
                all_errors.append(f"{path}: duplicate RFC number {n:04d}")
            seen_numbers.add(n)
        all_errors.extend(validate_rfc_file(path))
    for e in all_errors:
        print(f"::error::{e}", file=sys.stderr)
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".planning/rfcs/")))
```

### Cascade-Preview SPARQL CONSTRUCT (D-18 Classification)

```sparql
# Source: SPARQL over the Phase 4 IRI scheme + Phase 5 supersession links +
# Phase 3 reconciliation_strategy + Phase 7 contest_votes. Produces dependent
# IRIs with the bucket-classification triples D-18 needs.
#
# Run against the corpus shard graph; the result is consumed by classify_dependent()
# in retract.py.
PREFIX fi: <https://folio-insights.example/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

CONSTRUCT {
  ?dep fi:dependsOnRetracted ?retracted ;
       fi:hasSupersessionAvailable ?succ ;
       fi:reconciliationStrategy ?strategy ;
       fi:epistemicStatus ?status ;
       fi:hasUnresolvedContestVotes ?contestCount .
}
WHERE {
  ?dep ( fi:depends_on_precedents
       | fi:depends_on_definitions
       | fi:depends_on_shards ) ?retracted .
  BIND(<RETRACTED_IRI> AS ?retracted)

  OPTIONAL {
    ?retracted fi:superseded_by ?succ .
    ?succ fi:valid_time_start ?vts .
    FILTER(?vts <= NOW())
  }
  OPTIONAL { ?dep fi:reconciliation_strategy ?strategy . }
  OPTIONAL { ?dep fi:epistemic_status ?status . }
  OPTIONAL {
    SELECT ?dep (COUNT(?vote) AS ?contestCount) WHERE {
      ?dep fi:contest_votes ?vote .
      FILTER NOT EXISTS { ?dep fi:contest_resolution ?_ }
    } GROUP BY ?dep
  }
}
```

Classifier logic (`classify_dependent`, locked by D-18):

```python
def _classify_dependent(dep_attrs: dict) -> Literal["auto_rederive", "aporetic", "review_needed"]:
    has_succ = dep_attrs.get("supersession_available", False)
    strategy = dep_attrs.get("reconciliation_strategy")  # one of 7 strategies
    status = dep_attrs.get("epistemic_status")
    unresolved_votes = dep_attrs.get("unresolved_contest_count", 0)

    # review_needed wins — any human-judgment marker forces review
    if status in {"contested", "aporetic"}: return "review_needed"
    if unresolved_votes > 0: return "review_needed"
    if strategy is not None and strategy != "prefer_latest": return "review_needed"

    # auto_rederive: prefer_latest + supersession available
    if strategy == "prefer_latest" and has_succ: return "auto_rederive"

    # aporetic: nothing else to go on
    return "aporetic"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single shared `disagreement()` helper with `kind: Literal["contest", "supersede", "retract"]` discriminator | Three modules with zero shared code (D-16) | Phase 7 — driven by PRD §21.8 "reviewers must pick the right mechanism" | Refactoring toward DRY is intentionally forbidden; PR review catches reviewer-judgment-skipping shortcuts |
| Eager Turtle write to `<corpus>/governance.ttl` on every event | On-demand `governance export` (D-08) + Phase 13 SQLite as hot path | Phase 7 D-08 | Avoids partial-write corruption + double-write races; export is auditable replay artifact |
| Last-admin self-revocation silently allowed | Hard refused with `WouldLockoutCorpusAdmin` (D-11) | Phase 7 — closes F6 from Phase 6 deferred | F6 closed without break-glass complexity; remedy is fork-the-corpus (D-12) |
| `RoleAssertion` with `is_revocation: bool` flag | Distinct `RoleRevocationEvent` class (D-13) | Phase 7 — adds 12th `SignedAction` value | Distinct concept → distinct event → distinct SHACL → clean PROV-O audit; mirrors GOV-04 three-way disambiguation philosophy |
| RFC linter via `pre-commit` hook only | Linter as `python -m folio_insights.rfc.lint` runnable in CI + locally (D-22) | Phase 7 | Pre-commit is a hint; CI is the gate. Phase 18 wires the pre-commit hook config |
| Majority-vote contest resolution | Three explicit paths: arbiter / distinguo / aporetic (GOV-05) | PRD §3.1.3 + decision #8 | Voting-on-truth conflates social with epistemic; the three paths each do their own work. Explicit-rejection test required |

**Deprecated/outdated:**
- **PRD §3.1's "decision #8 — contest_votes as the voting tally"** — the votes
  are recorded but NEVER resolve a contest; resolution always requires
  arbiter / distinguo / aporetic. Documented as a clarification, not a
  contradiction.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `pydantic.Annotated[Union[...], Field(discriminator="action")]` correctly dispatches to the right event class on `model_validate` for a 12-class union | Pattern 1 | Could need a manual `model_validator` fallback; doesn't change architecture. [ASSUMED] from Pydantic 2 training data; verified at planning time by spike. |
| A2 | `pyshacl 0.31.0`'s `sh:sparql` constraint correctly returns the bad case (Phase 5 polarity discipline carries over) | SHACL shape examples | Already proven by Phase 5 live spike — high confidence. [VERIFIED: Phase 5 `content_edit_shape.ttl` cited L19-20 "spiked live against pyshacl 0.31.0"]. Polarity for new shapes needs same spike. |
| A3 | The PROV-O `prov:Activity` / `prov:wasAttributedTo` / `prov:wasGeneratedBy` mapping fits cleanly onto our 12 events (each event is a `prov:Activity` attributed to the signer DID, generating a new shard-state entity) | SHACL `fi:GovernanceLogShape` + governance log structure | Could need a `prov:` namespace import in shapes. [CITED: W3C PROV-O Recommendation — `Activity` is the canonical class for a temporally-bounded action with an Agent]. |
| A4 | `subprocess.run(["git", "log", "--follow", "--reverse", "--format=...", path])` on a renamed RFC file returns commits across the rename boundary | `rfc.lint` | `--follow` is documented to track renames; verified `git --version 2.51.0` on dev box. [VERIFIED: `git log --follow` behavior is standard]. |
| A5 | Active-roles-at query can be expressed as `assertions \ revocations` windowed by `signature.signed_at <= asof` with no edge case left over | `query_active_roles_at` | Re-assertion of a revoked role currently returns "active" — correct semantic. Need test: assert → revoke → re-assert; query at each timestamp returns expected state. [ASSUMED] — needs explicit test. |
| A6 | The cascade-preview `underlying_state_hash` (D-17 PreviewStale) can be computed deterministically over the dependent set's relevant fields + governance-log latest position for the corpus | `commit_cascade()` | If the hash misses a relevant field, a race goes undetected. Recommend: hash the **set of (dep_iri, epistemic_status, reconciliation_strategy, valid_time_end, superseded_by, signing_log_position)** tuples. [ASSUMED] — needs spike. |
| A7 | The `RFC-TEMPLATE.md` filename is treated specially by the linter (not validated as a real RFC) | rfc.lint `main()` | If treated as a real RFC, linter fails immediately because `RFC-TEMPLATE.md` doesn't match `NNNN-kebab-title.md`. Code explicitly skips `RFC-TEMPLATE.md`. [VERIFIED: locked in skeleton above]. |
| A8 | The `SignedAction` Literal extension (12 → 13) doesn't break any caller because no exhaustive `match` statement covers all values today | Runtime State Inventory | Grep confirms: `identity/preview.py` hardcodes the DID-07 8-action subset; no `match SignedAction` exhaustive switch elsewhere. [VERIFIED: `grep -rn "SignedAction" src/`]. |

## Open Questions (RESOLVED)

1. **Should the genesis admin DID be the operator's currently-bound DID, or a freshly generated `did:key`?**
   - What we know: D-10 says `folio-insights corpus init --admin-did did:...`. The flag is required.
   - What's unclear: Whether the CLI should default to the operator's already-bound DID (from Phase 6 `did bind`) or refuse to default at all.
   - **RESOLVED — Refuse to default.** The genesis decision is too important; the operator must pass an explicit DID. CLI errors with a helpful message pointing at `folio-insights did bind`.

2. **Hash-chain over governance events: ship now, or defer to Phase 13?**
   - What we know: F5 mitigation lists "Cryptographic chain: each governance event hash-chains over the prior event's hash" as a strong defense.
   - What's unclear: Is the hash-chain part of the Phase 7 acceptance bar?
   - **RESOLVED — Ship now as part of the per-event `over_content_hash`.** Include `prior_event_hash` in the JCS payload before hashing. Cost is one line in `events.py`; gain is Phase 19 audit can re-walk from genesis to verify integrity even before Phase 13's SQLite trigger lands. No new test fixtures needed.

3. **`folio-insights corpus init` — new top-level `corpus` Click subgroup or extension of existing CLI?**
   - What we know: D-10 says "CLI: `folio-insights corpus init --admin-did did:...`" — implies a new `corpus` subgroup or a top-level command.
   - What's unclear: Phase 18.5 `corpus fork` will also live under this namespace; should the subgroup be opened here?
   - **RESOLVED — Open the `corpus` Click subgroup now** (`cli.add_command(corpus_group)` from `governance/cli/corpus.py`). Subcommand `init` ships in Phase 7; `fork` joins in Phase 18.5 with no CLI restructuring needed.

4. **Should `query_active_roles_at()` accept `corpus` only, or `(corpus, did)` for efficiency on hot paths?**
   - What we know: `authorize.py` calls it on every CLI command; the cost on a 10K-event log is O(N) without indexing.
   - What's unclear: Premature optimization for Phase 7?
   - **RESOLVED — Ship with corpus-only query and a per-DID convenience wrapper `query_active_roles_for_did(corpus, did, asof)`.** Phase 13 backs both with indexed SQLite queries.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `git` | rfc.lint git-history walk + grep-guard test fixtures | ✓ | 2.51.0 | — |
| Python 3.12 | All Phase 7 modules (matches existing tree) | ✓ | per pyproject | — |
| pyshacl + rdflib | SHACL validation (via `services/shacl_validator.py`) | ✓ (in pyproject) | 0.31.0+ / 7.6.0+ | — |
| `~/.folio-insights/` keystore | Genesis admin signing (D-10) | ✓ if operator ran `folio-insights did generate` | Phase 6 keystore | Refuse with helpful error pointing at Phase 6 setup |

**Missing dependencies with no fallback:** None. All Phase 7 mechanisms run on
Phase 5/6 primitives + stdlib.

**Missing dependencies with fallback:** None.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest` + `pytest-asyncio` (already in tree) + `hypothesis` (already in tree for property tests) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (existing) |
| Quick run command | `pytest tests/governance/ tests/rfc/ -x -q` |
| Full suite command | `pytest tests/governance/ tests/rfc/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GOV-01 | Role assertions round-trip; per-corpus role queries return correct set | unit | `pytest tests/governance/test_role_assertion_signed.py -x` | ❌ Wave 0 |
| GOV-01 | Active-roles query is `assertions \ revocations` windowed by signed_at | unit + property | `pytest tests/governance/test_active_roles_query.py -x` | ❌ Wave 0 |
| GOV-02 | Governance log refuses mutation on past rows (SHACL) | unit | `pytest tests/governance/test_governance_log_is_append_only.py -x` | ❌ Wave 0 |
| GOV-02 | InMemoryGovernanceLog has no public mutation API beyond append | contract | `pytest tests/governance/test_governance_log_protocol_contract.py -x` | ❌ Wave 0 |
| GOV-02 | Governance log exports valid PROV-O Turtle | integration | `pytest tests/governance/test_governance_log_exports_as_provo.py -x` | ❌ Wave 0 |
| GOV-03 | Promotion requires reviewer role + citation + signed event | unit + e2e CLI | `pytest tests/governance/test_promotion_requires_citation.py -x` | ❌ Wave 0 |
| GOV-03 | Unsigned promotion rejected end-to-end via CLI | integration | `pytest tests/governance/test_unsigned_promotion_rejected.py -x` | ❌ Wave 0 |
| GOV-03 | D-21 status-kind consistency: authority_only requires AuthorityShard cited | unit | `pytest tests/governance/test_promotion_status_kind.py -x` | ❌ Wave 0 |
| GOV-04 | grep-guard: contest/supersede/retract share no codepath | regression | `pytest tests/governance/test_grep_guard_three_way_disambiguation.py -x` | ❌ Wave 0 |
| GOV-04 | dep-leak guard: no aiosqlite/rdflib/pyoxigraph in governance/ | regression | `pytest tests/governance/test_dep_leak_guard.py -x` | ❌ Wave 0 |
| GOV-04 | Three distinct CLI subcommands present and disjoint | integration | `pytest tests/governance/test_cli_three_way_distinct.py -x` | ❌ Wave 0 |
| GOV-05 | All 3 contest-resolution paths (arbiter/distinguo/aporetic) tested | unit | `pytest tests/governance/test_arbiter_can_resolve_contest.py tests/governance/test_distinguo_resolution.py tests/governance/test_aporetic_acceptance.py -x` | ❌ Wave 0 |
| GOV-05 | Majority-vote resolution explicitly rejected | unit | `pytest tests/governance/test_no_majority_vote_resolution.py -x` | ❌ Wave 0 |
| GOV-05 | Contest votes append; contested status surfaces | unit | `pytest tests/governance/test_contested_state_records_votes.py -x` | ❌ Wave 0 |
| GOV-06 | Cascade preview classifies dependents by D-18 heuristic | unit | `pytest tests/governance/test_cascade_preview_classification.py -x` | ❌ Wave 0 |
| GOV-06 | `--apply` refuses with PreviewStale on state change | integration | `pytest tests/governance/test_preview_stale_refusal.py -x` | ❌ Wave 0 |
| GOV-06 | Interactive default + `--preview` + `--apply` all share preview-builder | unit | `pytest tests/governance/test_cascade_preview_shared_builder.py -x` | ❌ Wave 0 |
| GOV-07 | RFC linter frontmatter schema enforced | unit | `pytest tests/rfc/test_lint_frontmatter_schema.py -x` | ❌ Wave 0 |
| GOV-07 | Filename `NNNN-kebab-title.md` + monotonic numbering | unit | `pytest tests/rfc/test_lint_filename_monotonic.py -x` | ❌ Wave 0 |
| GOV-07 | Status transitions monotonic across git history | integration | `pytest tests/rfc/test_lint_status_monotonic_across_history.py -x` | ❌ Wave 0 |
| GOV-07 | Body-only edit forbidden from changing status (Reason: trailer required) | integration | `pytest tests/rfc/test_lint_body_only_edit_refused.py -x` | ❌ Wave 0 |
| CORPUS-05 | corpus init writes self-signed genesis row 0 | integration | `pytest tests/governance/test_genesis_self_signed_carveout.py -x` | ❌ Wave 0 |
| F6 (D-11) | Last-admin self-revocation refused with `WouldLockoutCorpusAdmin` | unit | `pytest tests/governance/test_last_admin_self_revocation_refused.py -x` | ❌ Wave 0 |
| D-13 | SignedAction Literal has 13 values | unit | `pytest tests/governance/test_signed_action_literal_13_values.py -x` | ❌ Wave 0 |
| D-19 | Every CLI command calls authorize() as first step | regression | `pytest tests/governance/test_authorize_called_first.py -x` | ❌ Wave 0 |
| F2 | Active-roles windowed by signed_at (rotation-survival) | property | `pytest tests/governance/test_active_roles_rotation_safe.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/governance/ tests/rfc/ -x -q` (full Phase 7 suite; estimated < 30s for the in-memory backend).
- **Per wave merge:** `pytest tests/governance/ tests/rfc/ tests/identity/ tests/revision/ tests/shards/ -v` (Phase 7 + upstream Phases 5/6/2 to catch any AttestedSignature regressions).
- **Phase gate:** Full suite green + `pytest -m governance --strict-markers` + lint passes (`ruff check src/folio_insights/governance/ src/folio_insights/rfc/`) before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/governance/__init__.py` and `tests/governance/conftest.py` — shared fixtures
  (a built `InMemoryGovernanceLog`, a pre-seeded corpus with one corpus_admin, a Phase 6
  test key fixture).
- [ ] `tests/rfc/__init__.py` and `tests/rfc/conftest.py` — shared fixtures (synthetic
  git repos via `git init` in `tmp_path`).
- [ ] `tests/rfc/fixtures/` — sample `.planning/rfcs/` trees including pass cases
  (linear lifecycle), fail cases (downgrade, body-only status edit, missing frontmatter,
  duplicate RFC number).
- [ ] `pytest.mark.governance` and `pytest.mark.rfc` registered in `pyproject.toml`
  `[tool.pytest.ini_options.markers]`.
- [ ] No framework install needed — `pytest` + `pytest-asyncio` + `hypothesis` already
  present.

## Security Domain

### Applicable ASVS Categories (OWASP ASVS 5.0)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | DID-based authentication via Phase 6 `verify_attestation`; no passwords introduced here. Phase 7 reuses, doesn't invent. |
| V3 Session Management | no | No session state in Phase 7 — CLI invocations sign per-action. |
| V4 Access Control | **yes** | Central `authorize(did, action, corpus)` (D-19) is THE access-control enforcement point. Action-permission table + active-roles query. Every CLI command + future web phase calls it. |
| V5 Input Validation | yes | Pydantic `extra="forbid"` on every event class + SHACL per-event shapes. **Belt-and-suspenders by design** (D-19). |
| V6 Cryptography | yes | ed25519 via Phase 6 PyNaCl (`identity/signer.py`). **Never hand-roll** — Phase 7 reuses Phase 6 signer/verifier verbatim. |
| V7 Error Handling and Logging | yes | All authorization denials raise typed `Deny(reason)`; the governance log IS the audit log. No PII in error messages. |
| V8 Data Protection at Rest | yes (Phase 13) | Phase 13 owns SQLite at-rest. Phase 7 invariant: no governance event is loggable to stderr/stdout at INFO level by default (D-19 / DID-06 spirit). |
| V11 Business Logic | **yes** | Three-way disambiguation IS a business-logic enforcement: refusing to make `disagreement()` easy is the V11 mitigation. Three modules + grep-guard. |
| V12 Files and Resources | yes | RFC linter validates filename pattern; refuses arbitrary paths in `--apply <file>` (must resolve under CWD or `--output` parent). |

### Known Threat Patterns for Governance Substrate

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Privilege escalation (extractor → reviewer via forged role assertion) | Elevation | D-19 `authorize()` queries active-roles-at-signed_at; SHACL `fi:RoleAssertionShape` requires signer to hold corpus_admin (except genesis carve-out) |
| Forged signatures on governance events | Spoofing | Phase 6 `verify_attestation` with `DidDocCache`-resolved signing-time key; SHACL `fi:GovernanceLogShape` refuses unsigned events |
| Append-only bypass via direct backend mutation | Tampering | `InMemoryGovernanceLog` has no public mutation API on past rows; SHACL refuses position re-use; Phase 13 SQLite trigger seals it |
| Replay of old role-revocation event | Tampering | Position-monotonic + signed_at-monotonic SHACL constraints; signatures bind to corpus + position |
| Last-admin self-revocation lockout | Denial of Service | D-11 `WouldLockoutCorpusAdmin` hard refusal at append() + SHACL `fi:RoleRevocationShape` |
| Self-signed assertion of arbitrary role | Elevation | Genesis carve-out (D-10) ONLY accepts position=0 + self-signed + role=corpus_admin; every other self-signed role_assertion is rejected |
| RFC status downgrade attempt (rewriting history) | Tampering | rfc.lint walks git history and rejects forbidden transitions; CI gate |
| Cascade-preview replay across state change | Tampering | D-17 `PreviewStale` refusal — preview hash binds underlying state |
| Body-only edit changes RFC status (review bypass) | Tampering | D-22 requires `Reason:` trailer or `status_change_reason:` frontmatter when status changes |
| Information disclosure via verbose error messages | Information Disclosure | Deny errors carry `reason: str` enumeration ("not_authorized", "no_active_role", "would_lockout_admin"), not raw SQL/IRI debug |
| Cross-corpus role bleed (reviewer on Corpus A acts on Corpus B) | Elevation | Roles are corpus-scoped (PRD §3.1.1); every event carries `corpus: str`; `query_active_roles_at(corpus, asof)` filters |

## Sources

### Primary (HIGH confidence)

- `.planning/phases/07-governance-model-3-1/07-CONTEXT.md` — D-01..D-22 locked decisions (read in full).
- `.planning/REQUIREMENTS.md` rows GOV-01..GOV-10 + CORPUS-05 — acceptance contracts.
- `PRD-v2.0-draft-2.md` §3.1 (governance model L92-154), §6.5 (DID attestations), §21.8 (demotion/contest L1949), §21.9 (supersession ≠ retraction L1963), §P3 (retraction cascade L994-1043). [VERIFIED: read locally].
- `src/folio_insights/shards/envelope.py:85` (SignedAction Literal, 11 values today). [VERIFIED: file read].
- `src/folio_insights/identity/cache.py` (DidDocCache Protocol — the template for GovernanceLog seam). [VERIFIED: file read].
- `src/folio_insights/revision/store.py` (ShardStore Protocol — the template for the in-memory-seam pattern). [VERIFIED: file read].
- `src/folio_insights/revision/content_edit_shape.ttl` (Phase 5 SHACL shape pattern). [VERIFIED: file read; pyshacl 0.31.0 polarity discipline noted in TTL header].
- `src/folio_insights/services/shacl_validator.py` (validate_*_shape() convention at L56,81). [VERIFIED: file read].
- `src/folio_insights/identity/cli.py` (Phase 6 `did` Click subgroup template). [VERIFIED: file read].
- `src/folio_insights/identity/signer.py` (Phase 6 `sign_attestation` real ed25519). [VERIFIED: file read].
- `src/folio_insights/identity/verifier.py` (Phase 6 `verify_attestation` with rotation-safe key resolution). [VERIFIED: file read].
- `tests/shards/test_dep_leak_guard.py` (the dep-leak grep-guard template). [VERIFIED: file read].
- `tests/polysemy/test_detector_rules.py` (the rule-based regression-test template). [VERIFIED: file read].
- `.planning/research/PITFALLS.md` F1 (cascade vs supersession L181), F2 (key rotation L212), F4 (JCS L277), F5 (append-only L312), F6 (admin lockout L343), U1 (badge L875). [VERIFIED: read in full].
- `pyproject.toml` (dep versions). [VERIFIED: file read].

### Secondary (MEDIUM confidence)

- W3C PROV-O Recommendation — `prov:Activity`, `prov:wasAttributedTo`, `prov:wasGeneratedBy`. [CITED: https://www.w3.org/TR/prov-o/]. Used to ground the governance log's PROV-O export contract (GOV-02).
- Pydantic 2 Discriminated Unions docs. [CITED: https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions]. Pattern reference for `GovernanceEvent` 12-class union.
- pyshacl 0.31.0 `sh:sparql` constraint semantics. [VERIFIED: live-spiked by Phase 5 RESEARCH, cited in `content_edit_shape.ttl:19-20`]. Used as the basis for new shapes' polarity discipline.

### Tertiary (LOW confidence)

- W3C PROV-O OWL ontology download. [CITED: https://www.w3.org/ns/prov-o.owl]. Should be re-confirmed when the per-event shapes are written (the actual `prov:` namespace usage in SHACL needs validation).

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — every library is already in `pyproject.toml` and proven through 6 prior phases; no new deps.
- Architecture: **HIGH** — Phase 5/6 seam template is exact; D-04..D-19 lock the surface; only the cascade-preview is genuinely new.
- SHACL shape skeletons: **MEDIUM** — bodies given here are sound but the polarity must be live-spiked against pyshacl 0.31.0 before merge (Phase 5 precedent: pyshacl SPARQL polarity is load-bearing and tested live).
- Cascade-preview SPARQL CONSTRUCT: **MEDIUM** — the query is structurally correct but the exact `fi:` namespace IRIs need to match Phase 4's IRI scheme (`urn:folio:shard/...` vs `fi:` prefix in shape file). Planner verifies.
- Grep-guard regression test: **HIGH** — direct port of `tests/shards/test_dep_leak_guard.py`.
- rfc.lint git-history walk: **MEDIUM** — `subprocess git log` is well-known; the `--follow --reverse` semantics on renames need a real-tree test fixture (synthetic `git init` in `tmp_path`).
- Pitfalls: **HIGH** — all derived from PITFALLS.md (already locked) + CONTEXT.md D-09..D-22.

**Research date:** 2026-05-30
**Valid until:** 2026-06-29 (30 days; stack is stable across Phases 5/6/7 — re-validate
if any of `pydantic`, `pyshacl`, `rdflib`, or `click` ship a major version before Phase 7
merges).
