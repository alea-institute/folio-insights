# Phase 7: Governance Model (§3.1) - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship the **governed-by-design backbone** that turns Phase 6's signing primitives into
authorized, audited, contestable corpus actions: the **4-tier role model**, the
**append-only PROV-O governance log** per corpus, **promotion / contest / supersede /
retract** with three-way disambiguation (locked **distinct codepaths** + **distinct CLI
commands** — GOV-04 code-review gate), the **retraction-cascade preview**, and the
**RFC lifecycle linter** that makes the community process auditable.

This phase is **deliberately scoped down to the critical-path CLI + library + API
contracts** — mirroring Phase 6 D-01/D-02 — so that everything web-UI-bound and every
P2 stretch travels forward (see `<deferred>`). What Phase 7 delivers:

1. **4-tier role model** (`extractor` / `reviewer` / `arbiter` / `corpus_admin`),
   asserted per corpus via DID-signed `fi:RoleAssertion`, revoked via a distinct
   `fi:RoleRevocation` (D-04 / D-13). Genesis bootstrap via a self-signed
   `RoleAssertion` at log row 0 with a narrow SHACL carve-out (D-10). **Last-admin
   self-revocation hard-refused** with `WouldLockoutCorpusAdmin` (D-11), closing F6
   from Phase 6 deferred. **No break-glass** — fork-the-corpus (Phase 18.5) is the
   remedy (D-12).
2. **PROV-O governance log** per corpus, append-only by construction. **`GovernanceLog`
   Protocol + `InMemoryGovernanceLog`** ships now (mirrors Phase 5 `ShardStore` D-02
   and Phase 6 `DidDocCache` D-11). **`fi:GovernanceLogShape` SHACL is real now**
   (append-only invariant + per-event validity). **SQLite trigger travels to Phase 13**
   (D-05 acceptance-bar amendment — see "Amended exit bar"). On-disk layout when Phase
   13 lands: `<corpus_root>/governance.ttl` + `<corpus_root>/.governance.sqlite`
   (D-07). Turtle export is **on-demand** via `folio-insights governance export
   <corpus>` (D-08).
3. **Single write entry: `governance_log.append(event)`** (D-06) over a
   `GovernanceEvent` Pydantic discriminated union (12 event types reconciled with
   Phase 6's `SignedAction` Literal + the new `role_revocation`). Every caller — CLI,
   future API, future web phase — goes through this seam.
4. **Promotion** (GOV-03): `folio-insights governance promote <iri> --status=<S> --cite
   <iri>+` (D-21). Requires reviewer role + ≥1 `depends_on_precedents` or
   `depends_on_definitions` IRI **resolvable to an existing shard in the local store**
   (D-20). Reviewer specifies the resulting `epistemic_status` from
   `{per_se_nota_quoad_nos, demonstrable, authority_only}`; validator checks
   consistency with citation kind (D-21).
5. **Three-way disambiguation** (GOV-04, the code-review gate): three subcommands
   under `folio-insights governance {contest|supersede|retract}` (D-15), implemented
   as three modules under `src/folio_insights/governance/{contest,supersede,retract}.py`
   with **distinct Pydantic event classes**, **distinct SHACL shapes**, **distinct
   validators**, and **distinct CLI command modules**. **Grep-guard regression test**
   (D-16) fails CI if (a) any of the three modules imports from another, (b) any base
   class beyond `GovernanceEvent` is shared, or (c) the Click commands share an
   implementation function. `AttestedSignature` is the **only** shared primitive
   (it's the signature, not the codepath).
6. **Contest workflow** (GOV-05): position + citation → `contest_votes[]` populated →
   resolution via **arbiter / distinguo / aporetic** (3 paths, **no majority-vote** —
   PRD §3.1.3 + §21.8). All 3 resolution paths get tests; majority-vote resolution
   gets an explicit-rejection test.
7. **Retraction-cascade preview** (GOV-06): **interactive default + `--preview`
   dry-run + `--apply <report.json>`** (D-17). Default prints the grouped table to
   stdout and prompts `Confirm? [y/N]`; `--preview` writes a timestamped JSON report
   and exits without committing; `--apply <file>` re-applies a previously-generated
   preview (refusing if underlying state changed since preview was taken — fresh
   preview required). Dependents are classified by the heuristic locked in **D-18**:
   `auto_rederive` (prefer_latest + supersession available), `aporetic` (no
   supersession + no reviewer marker), `review_needed` (any reviewer-disagreement
   marker OR `epistemic_status ∈ {contested, aporetic}` OR `reconciliation_strategy`
   requiring human judgment).
8. **Central authorization** (D-19): `src/folio_insights/governance/authorize.py`
   exports `authorize(did, action, corpus) → Allow | Deny(reason)`. Every CLI command
   calls it as the first step after parsing; SHACL shapes are the belt-and-suspenders
   second check at storage time. The post-Phase-14 web/API phase calls the same
   function — no second authorization layer to keep in sync.
9. **RFC lifecycle linter** (GOV-07): `python -m folio_insights.rfc.lint` validates
   frontmatter schema, `NNNN-kebab-title.md` filename + monotonic numbering, monotonic
   status transitions (`draft → discussion → accepted|rejected → implemented`) across
   git history, terminal `rejected`, and no body-only edit may change status (D-22).
   Runs in CI; pre-commit hook hint is shipped in `RFC-TEMPLATE.md`'s sibling docs
   (Phase 18 wires the actual hook). **`RFC-TEMPLATE.md` ships here as the linter's
   golden fixture** (D-02).

**Amended acceptance bar for THIS phase** (amended from ROADMAP's 6 exit criteria,
following Phase 6's D-12 precedent — see "TRAVELS FORWARD" below):

- **STAYS:**
  - Role assertions round-trip; per-corpus role queries return correct set (orig EC1).
  - **Append-only governance log via SHACL + Protocol-contract test** (orig EC2,
    AMENDED — SQLite trigger travels to Phase 13 per D-05; in-phase gate is the
    `GovernanceLog` Protocol contract test + `fi:GovernanceLogShape` SHACL refusal of
    `DELETE` / `UPDATE` on past rows).
  - Promotion `hypothesis → attested` requires reviewer role + citation +
    DID-signed `fi:Promotion` — unsigned promotion rejected **end-to-end (CLI** only;
    API is contract-defined here, the web/API surface defers per D-03) (orig EC3,
    AMENDED — CLI-only end-to-end).
  - Three-way disambiguation: **distinct codepaths verified by grep-guard** +
    distinct CLI subcommands (orig EC4, unchanged in spirit).
  - Retraction cascade preview groups dependents `{auto_rederive, aporetic,
    review_needed}` with **interactive + `--preview` + `--apply`** rollback-before-
    commit affordance (orig EC5, refined per D-17).
  - RFC process: `.planning/rfcs/NNNN-title.md` lifecycle linter green in CI; no
    auto-merge (orig EC6, unchanged — D-22 specifies what "lifecycle linter" means).
- **TRAVELS FORWARD (explicitly NOT Phase 7):**
  - **Real `<corpus>/governance.ttl` writer + `.governance.sqlite` with `BEFORE
    UPDATE/DELETE → RAISE FAIL` trigger** → Phase 13 (storage layer fills the
    `GovernanceLog` seam D-05/D-06 ships).
  - **Web flows** (role-assertion signing UI, promotion preview component,
    retract/contest/supersede modals) → **post-Phase-14** (after design contract +
    adapter-node), invoking the same `authorize()` + `governance_log.append()` API the
    CLI uses (D-03).
  - **GOV-09 governance-log timeline viewer UI** + **GOV-10 warrant trace-back UI**
    (both P2) → post-Phase-14 web phase (D-01).
  - **Community artifact FILES** (CONTRIBUTING / CODE_OF_CONDUCT / GOVERNANCE.md
    prose) → **Phase 18** (which already declares dependency on Phase 7). Phase 7
    ships only **`RFC-TEMPLATE.md`** (the linter's golden fixture) (D-02).

**NOT in scope (carried to other phases):**
- Governance-log persistent storage (real Turtle + SQLite trigger) — **Phase 13**.
- Full `fi:SignedActionShape` SHACL suite (verification-at-ingest across every event
  type) — **Phase 11**. Phase 7 ships only the focused shapes it needs: the role
  shapes, the governance-log append-only shape, and one per event class (mirrors
  Phase 5's "ship the focused shape, defer the suite" pattern).
- GOV-09 timeline viewer UI + GOV-10 warrant trace-back UI — post-Phase-14 web phase.
- CONTRIBUTING.md / CODE_OF_CONDUCT.md / GOVERNANCE.md prose — **Phase 18**.
- Multi-sig role assertions (e.g., M-of-N corpus_admin grants) — uses Phase 6.3
  multi-sig (already deferred to a 6.x / v2.1 phase); the `cosigners[]` slot is
  reserved in Phase 6 D-13 so the schema doesn't re-break.
- Corpus-level break-glass mechanism (single break-glass DID, M-of-N reseed
  ceremony, etc.) — **not shipped** (D-12 — fork-the-corpus is the remedy). Capture
  as a deferred idea in case the community asks for it post-GA.
- Cascade simulation / full transactional dry-run with rollback across multiple
  cascades (REQUIREMENTS.md row 270 already defers this as "analyst power tool" beyond
  GOV-06 cascade preview).
</domain>

<decisions>
## Implementation Decisions

### Scope & Phase Shape

- **D-01:** **Defer GOV-09 (timeline viewer UI) + GOV-10 (warrant trace-back UI)
  post-Phase-14.** Both are P2 in REQUIREMENTS; both need the design system + adapter-
  node. Phase 7 ships the queryable PROV-O log + `warrant:` metadata that those views
  render. Mirrors Phase 6 D-02. Web phase post-Phase-14 owns both screens; Phase 7
  guarantees the data is there and queryable by SPARQL.
- **D-02:** **Phase 18 owns the community-artifact files** (CONTRIBUTING.md,
  CODE_OF_CONDUCT.md, GOVERNANCE.md prose). Phase 7 ships **only** the **RFC linter
  mechanism** + **`RFC-TEMPLATE.md`** (the linter's golden fixture — the linter is
  meaningless without a template to validate against). Roadmap already encodes this
  dependency: Phase 18 "Depends on Phase 7 (governance model + RFC process must exist
  before we document them)." This decision lifts the ambiguity.
- **D-03:** **Defer all web surfaces post-Phase-14** (role-assertion signing UI,
  promotion preview component, retract/contest/supersede modals, timeline viewer,
  warrant trace-back). Phase 7 ships the **CLI + Python API + thin HTTP API contract**
  the web phase will render. Concretely: `authorize()` + `governance_log.append()` +
  the 12 `GovernanceEvent` Pydantic classes + the 4 CLI subgroups are the contract.
  The post-Phase-14 web phase calls the **same functions** the CLI calls — no second
  authorization or validation layer to keep in sync.

### Governance-Log Storage Substrate

- **D-04:** **`GovernanceLog` Protocol now; persistent backend in Phase 13.** Mirrors
  Phase 5 D-02 (`ShardStore`) and Phase 6 D-11 (`DidDocCache`). Lives in
  `src/folio_insights/governance/log.py` with `InMemoryGovernanceLog` as the in-phase
  implementation. The seam keeps `aiosqlite` / `rdflib` / `pyoxigraph` **out of the
  `governance/` package** (same dep-discipline that forced Phase 5's `revision/`
  boundary and Phase 6's `identity/` boundary).
- **D-05 (acceptance-bar amendment — see `<domain>` "STAYS"):** **`fi:GovernanceLogShape`
  SHACL is REAL now**; **SQLite trigger travels to Phase 13.** GOV-02's in-phase gate
  is (a) the SHACL shape refusing `DELETE`/`UPDATE` on past rows, and (b) the
  `GovernanceLog` Protocol contract test (`InMemoryGovernanceLog` enforces append-
  only by construction — no public mutation API on past rows). Phase 13 wires the
  `BEFORE UPDATE/DELETE → RAISE FAIL` trigger when it ships the aiosqlite backend.
  Same shape Phase 6 used (D-12 acceptance-bar amendment).
- **D-06:** **Single write entry: `governance_log.append(event: GovernanceEvent)`.**
  All callers — CLI commands, the post-Phase-14 API, future tooling — go through this
  function. `GovernanceEvent` is a Pydantic discriminated union over 12 event types
  (12 `SignedAction` Literal values: `extract, promote, demote, contest,
  resolve_contest, distinguo, supersede, retract, role_assertion, role_revocation,
  content_edit, reparent, reconcile` — extending Phase 6's 11-value Literal by adding
  `role_revocation` per D-13). `append()` (i) validates the event's SHACL shape, (ii)
  validates the embedded `AttestedSignature` via Phase 6's `verify_attestation`, (iii)
  assigns the next monotonic `position`, (iv) returns the persisted event.
- **D-07:** **On-disk layout when Phase 13 lands:** `<corpus_root>/governance.ttl` +
  `<corpus_root>/.governance.sqlite`. Matches PRD §3.1.5 verbatim. Self-contained per
  corpus — `corpus fork` (Phase 18.5) copies governance with the corpus. SQLite is
  the queryable hot path; Turtle is the export/audit format. Phase 7 ships only the
  on-disk *layout decision*; the actual files do not exist until Phase 13.
- **D-08:** **Turtle export is on-demand**, never eager. `folio-insights governance
  export <corpus>` reads the SQLite ledger and emits Turtle. Avoids partial-write
  corruption + double-write races. Phase 13 may later add an opt-in `--watch` mode.

### Three-Way Disambiguation (GOV-04 — code-review gate)

- **D-14:** **PRD §21.8 / §21.9 / GOV-04 lock that contest / supersede / retract are
  conceptually distinct mechanisms.** "Reviewers must pick the right mechanism; UI
  prompts clarify the choice at action time" (§21.8 tradeoff accepted). Software
  enforces this by refusing to provide a unified path.
- **D-15:** **CLI shape: `folio-insights governance {contest|supersede|retract}`
  subgroup.** Each subcommand lives in its own Click command module under
  `src/folio_insights/governance/cli/`. Discoverable via `--help`; same namespace
  parity as Phase 6's `did` subgroup, Phase 1's `polysemy` subgroup.
- **D-16:** **"No shared codepath" enforced by grep-guard regression test.** Three
  modules `src/folio_insights/governance/{contest,supersede,retract}.py`. Each
  defines its own (a) Pydantic event class (`ContestEvent`, `SupersessionEvent`,
  `RetractionEvent`), (b) SHACL shape, (c) validator function. A grep-guard test
  (mirrors Phase 1's `detector_confidence` grep-guard) fails CI if:
    - any of the three modules `import` from another,
    - any base class beyond the shared `GovernanceEvent` discriminated-union umbrella
      is shared,
    - the three Click commands share an implementation function.
  `AttestedSignature` is the **only** shared primitive — it's the signature on the
  action, not the action's codepath.

### Retraction-Cascade Preview UX (GOV-06)

- **D-17:** **Interactive default + `--preview` dry-run + `--apply <report.json>`.**
  - **Default**: print grouped table to stdout, prompt `Confirm retraction of N
    shards (auto_rederive: A, aporetic: B, review_needed: C)? [y/N]`, commit on `y`
    / abort otherwise.
  - **`--preview`**: write the report to a timestamped JSON file
    (`retract-preview-<iri>-<ts>.json` in CWD by default; `--output <path>` overrides),
    exit `0` without committing.
  - **`--apply <file>`**: re-apply a previously-generated preview. Verifies the
    underlying state hasn't changed since preview (re-runs the dependents query;
    fails with `PreviewStale` if the dependent set or any classification differs).
    A fresh `--preview` is required if state has changed.
  - All three modes share the **same preview-builder** (`build_cascade_preview(...)`);
    only the commit step differs (`commit_cascade(preview)`).
- **D-18:** **Dependents classification heuristic — locked here:**
  - `auto_rederive`: dependent has `reconciliation_strategy = "prefer_latest"` AND a
    superseding shard exists with `valid_time <= now`.
  - `aporetic`: no supersession available AND no reviewer-disagreement marker on the
    dependent.
  - `review_needed`: ANY of — (a) `epistemic_status ∈ {contested, aporetic}`, (b)
    `reconciliation_strategy` is one of the 7 human-judgment strategies (i.e., not
    `prefer_latest`), (c) the shard has an unresolved `contest_votes[]`.
  Researcher / planner own the exact SPARQL CONSTRUCT. This is the rule.

### Authorization & Promotion (GOV-01 / GOV-03 / GOV-05)

- **D-19:** **Central `authorize(did, action, corpus) → Allow | Deny(reason)`** in
  `src/folio_insights/governance/authorize.py`. Queries active-roles-at-time(now)
  from the `GovernanceLog` Protocol; returns a result. **Every CLI command calls it
  as the first step after parsing.** SHACL shapes are the belt-and-suspenders
  second check at storage time (defense in depth). The post-Phase-14 API/web phase
  calls the same function — no parallel authorization layer to keep in sync. Mirrors
  Phase 6's central `verify_attestation`.
- **D-20:** **Promotion citation depth: non-empty + resolvable.** Promotion requires
  ≥1 `depends_on_precedents` or `depends_on_definitions` IRI; each cited IRI must
  resolve to an existing shard in the corpus (and the cited IRI must not be the
  shard being promoted). No deeper rule (e.g., "is good law" is reviewer judgment,
  not software).
- **D-21:** **Reviewer specifies the promoted `epistemic_status` via `--status`
  flag; validator checks consistency with citation kind.**
  - CLI: `folio-insights governance promote <iri> --status=demonstrable --cite
    <iri>+`.
  - Validator rule: `authority_only` requires the cited shard's authority kind to be
    a precedent/statute (`AuthorityShard` subtypes); `demonstrable` requires the
    cited shard to itself be `demonstrable` or stronger; `per_se_nota_quoad_nos`
    requires no citation depth check (axiomatic, self-evident-to-us). Reviewer's
    judgment is the source; software checks the shape match.
  - Resulting `AttestedSignature` records `action="promote"` (PRD §3.1.2 L117 — Phase
    6 already defines this Literal).

### Bootstrap & Lockout Defense (closes F6)

- **D-09:** **F6 (corpus-admin role-lockout defense) lives in Phase 7** — Phase 6
  surfaced it in research and deferred to Phase 7 (Phase 6 `<deferred>` row). This
  phase ships the closing decisions D-10 / D-11 / D-12 / D-13.
- **D-10:** **Genesis admin via self-signed `RoleAssertion` at log row 0** with a
  narrow SHACL carve-out. The DID issuing a corpus genesis signs its OWN
  `RoleAssertion` granting itself `corpus_admin`. PRD §3.1.5 append-only is preserved
  — it's row 0 ("the bootstrap row"), not a mutation. The carve-out: position=0 AND
  self-signed AND role=corpus_admin is the **only** self-signed assertion accepted;
  every later row requires an existing-admin signature verifiable against the log.
  CLI: `folio-insights corpus init --admin-did did:...`.
- **D-11:** **Last-admin self-revocation hard-refused.** SHACL + code both check
  active-admin count before accepting a `RoleRevocation` event. The user-facing
  error is `WouldLockoutCorpusAdmin: revocation would leave the corpus with 0
  active corpus_admins; appoint a successor first`. Forces a structurally-safe
  ordering: appoint successor → successor signs their `RoleAssertion` → outgoing
  admin revokes themselves.
- **D-12:** **No corpus-level break-glass mechanism.** If all corpus_admin keys are
  lost, the remedy is **fork the corpus** (Phase 18.5 corpus-fork) and create a new
  genesis admin. The old corpus becomes read-only history. Matches PRD §3.1's
  fully-autonomous-per-corpus framing; "lockout is a community problem, not a
  software problem." Capture an explicit deferred idea so post-GA community
  requests for M-of-N break-glass aren't lost.
- **D-13:** **Revocation is a distinct `fi:RoleRevocation` event** (NOT a flag on a
  `RoleAssertion`). Adds `role_revocation` to Phase 6's `SignedAction` Literal
  (extending from 11 → 12 values). Mirrors GOV-04's three-way-disambiguation
  philosophy: distinct concept → distinct event class → distinct SHACL shape →
  clean PROV-O audit. Active-roles query = role-assertions minus role-revocations,
  windowed by `signed_at <= asof`.

### RFC Lifecycle Linter (GOV-07)

- **D-22:** **`python -m folio_insights.rfc.lint` validates the full lifecycle.**
  - **Frontmatter schema** (Pydantic-validated): `rfc: int`, `title: str`, `status ∈
    {draft, discussion, accepted, rejected, implemented}`, `authors: list[did]`,
    `created: date`, optional `superseded_by: int`.
  - **Filename**: `NNNN-kebab-title.md`; `NNNN` is monotonic across the directory
    (gaps allowed; duplicates fail).
  - **Status transitions are monotonic across git history**: re-running the linter
    against the full history of each RFC file must yield a strictly-monotonic
    sequence per the allowed DAG `draft → discussion → {accepted, rejected} →
    implemented`. `rejected` is terminal. A commit changing `accepted → draft` fails.
  - **No body-only edit may change status**: a commit whose unified-diff touches the
    `status:` frontmatter line MUST also have a corresponding rationale line
    (`status_change_reason:` in the same commit's frontmatter delta, or a `Reason:
    ...` trailer in the commit message). Cheap heuristic; catches accidents.
  - **Runs in CI** as `python -m folio_insights.rfc.lint .planning/rfcs/`. A
    pre-commit hook hint is shipped in `RFC-TEMPLATE.md`'s sibling docs (Phase 18
    wires the actual `pre-commit` hook config).
  - **`RFC-TEMPLATE.md` ships in Phase 7** as the linter's golden fixture +
    contributor reference. Its frontmatter is the canonical schema example.

### Claude's Discretion (researcher / planner own these)

- The exact package layout for `src/folio_insights/governance/` — likely:
  `log.py` (`GovernanceLog` Protocol + `InMemoryGovernanceLog`), `events.py`
  (`GovernanceEvent` discriminated union), `authorize.py`, `roles.py` (RoleAssertion
  / RoleRevocation + active-roles query), `promote.py`, `contest.py` (D-15),
  `supersede.py` (D-15), `retract.py` (D-15) including the cascade-preview builder,
  `cli/` (Click subgroups), `shapes/` (per-event SHACL TTL files). Planner decides
  exact module split — must respect D-16 grep-guard constraints (no cross-imports
  among contest/supersede/retract).
- The exact SHACL turtle for `fi:GovernanceLogShape` + the per-event shapes
  (`fi:RoleAssertionShape`, `fi:RoleRevocationShape`, `fi:PromotionShape`,
  `fi:ContestShape`, `fi:SupersessionShape`, `fi:RetractionShape`,
  `fi:ContestResolutionShape`). Mirror Phase 5 `revision/content_edit_shape.ttl`
  pattern + Phase 5 `validate_content_edit_shape()` validator surface.
- The `rfc.lint` linter's git-history walk strategy (`subprocess git log` vs
  GitPython vs pure shell). Pick whatever has the fewest deps; matching the
  Phase 1 `pyproject.toml` minimal-deps discipline.
- The exact SPARQL CONSTRUCT for the cascade-preview dependents query and the
  classification heuristic D-18. Researcher should validate the query against the
  Phase 4 `depends_on_*` relations and Phase 5 supersession links.
- Whether to ship a focused `fi:SignedActionShape` shape now (mirroring Phase 5's
  "ship the one focused shape" pattern) or to verify via per-event shapes only and
  let Phase 11 build the full suite. Keep it honest — don't fake verification that
  isn't happening.
- The exact Click command surface for `folio-insights corpus init` (the genesis-row-0
  CLI for D-10) — likely a new `corpus` subgroup or an extension of an existing one.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Governance spec (GOV-01..GOV-10, CORPUS-05)
- `.planning/REQUIREMENTS.md` rows **GOV-01..GOV-10** + **CORPUS-05** (acceptance
  contracts).
- `PRD-v2.0-draft-2.md` **§3.1** (governance model: 4 roles, promotion §3.1.2,
  demotion + contest §3.1.3, retraction cascade §3.1.4, governance log §3.1.5,
  acceptance tests at end of §3.1) — **read before planning**.
- `PRD-v2.0-draft-2.md` **§21.8** (demotion/contest mechanics resolution: retraction
  cascade + contested state are distinct).
- `PRD-v2.0-draft-2.md` **§21.9** (supersession ≠ retraction: distinct mechanisms;
  valid-time semantics).
- `PRD-v2.0-draft-2.md` **§21.10** (DID-signed, downstream-weighted trust model —
  this is what Phase 7 consumes, Phase 6 produced).
- `PRD-v2.0-draft-2.md` **§P3** (retraction cascade design — Phase 7 GOV-06 owns
  the preview; cascade semantics are §P3).
- `PRD-v2.0-draft-2.md` **§6.4** + **§21.9** (supersession schema — Phase 5 fields
  `superseded_by` / `supersedes` / `valid_time_*` are what `supersede.py` writes).
- `PRD-v2.0-draft-2.md` **§3.1 acceptance tests** (7 listed `tests/governance/...`
  paths — direct test file mapping).

### Research (PITFALLS — risks Phase 7 must defuse)
- `.planning/research/PITFALLS.md` **F6** (corpus-admin role-lockout defense — Phase
  6 deferred to here; D-09 / D-10 / D-11 / D-12 / D-13 close it).
- `.planning/research/PITFALLS.md` **F2** (key rotation breaks historical sigs —
  Phase 6 mitigation flows in; active-roles query must use `signed_at`-window
  resolution against the historical-key cache).
- `.planning/research/SUMMARY.md` §Governance / §RFC process (any cited patterns).

### Existing code to extend / reuse
- `src/folio_insights/shards/envelope.py` (line 85) — `SignedAction` Literal (11
  values today: `extract, promote, demote, contest, resolve_contest, distinguo,
  supersede, retract, role_assertion, content_edit, reparent, reconcile`). Phase 7
  **extends to 12** by adding `role_revocation` (D-13). Same file's
  `AttestedSignature` (already Phase 6 D-13 reshape) is the shared primitive every
  governance event signs over.
- `src/folio_insights/identity/signer.py` + `verifier.py` + `binding.py` — Phase 6's
  signing / verifying primitives. Phase 7 consumes `verify_attestation`. **No
  duplicate verification logic** in `governance/`.
- `src/folio_insights/revision/content_edit.py` (`canonical_content_hash`,
  `sign_attestation`) — Phase 5 + Phase 6 D-12 JCS-canonical hashing seam. Every
  governance event hashes its content via this function.
- `src/folio_insights/services/shacl_validator.py` (line 56, 81 — `pyshacl.validate`
  + `validate_*_shape()` pattern) — mirror this for every per-event governance
  shape. **No new SHACL plumbing** — extend the validator with new shape files.
- `src/folio_insights/revision/content_edit_shape.ttl` — the TTL-file convention
  governance shapes follow (`fi:RoleAssertionShape`, `fi:GovernanceLogShape`, etc.,
  under `src/folio_insights/governance/shapes/`).
- `src/folio_insights/cli.py` + Phase 1's `polysemy` Click subgroup + Phase 6's `did`
  Click subgroup — template for the new `governance` + `corpus` Click subgroups
  (D-15, D-10).

### Prior decisions (carried forward — do NOT re-ask)
- `.planning/phases/06-did-substrate-6-5/06-CONTEXT.md`:
  - **D-01 / D-02** — defer P2 + defer web-UI surfaces post-Phase-14. **Phase 7
    follows the same pattern** (D-01, D-03 here).
  - **D-11** — in-memory seam → Phase 13 swap. **Phase 7 follows this pattern for
    `GovernanceLog`** (D-04, D-05 here).
  - **D-13** — `AttestedSignature` schema is locked. **Phase 7 does NOT reshape it.**
  - **D-10** — OAuth→DID binding rules locked (every reviewer action carries a DID
    bound to an immutable OAuth `sub`).
  - **`SignedAction` Literal** at envelope.py:85 — Phase 7 extends by exactly one
    value (`role_revocation`) per D-13.
- `.planning/phases/05-content-versioning-6-4/05-CONTEXT.md`:
  - **D-02** — `ShardStore` Protocol seam pattern (template for `GovernanceLog`
    D-04).
  - **D-05** — `canonical_content_hash` (JCS via Phase 6). Governance events hash
    their content via the same function.
- `.planning/phases/04-iri-scheme-6-3/04-CONTEXT.md`:
  - Immutable shard IRIs — governance events reference shards by IRI; signatures
    cover content, never change the IRI.
- `.planning/phases/02-shard-envelope/02-CONTEXT.md`:
  - `AttestedSignature` envelope discipline (`extra="forbid"`) — every new
    governance event class follows the same envelope discipline.
- `.planning/phases/01-polysemy-distinguo-spike/01-CONTEXT.md` (referenced via
  PROJECT.md):
  - Click subgroup CLI idiom + rich.prompt human-gate pattern — template for the
    governance interactive prompts (D-17).
  - grep-guard regression-test pattern (Phase 1's `detector_confidence` guard) —
    template for D-16's "no shared codepath" grep-guard.

### Project context
- `.planning/PROJECT.md` — Key Decisions; v2.0 stack constraints.
- `.planning/ROADMAP.md` Phase 7 entry — original 6 exit criteria; amended bar here.
- `.planning/STATE.md` — Phase 7 starts from "ready to plan".

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`SignedAction` Literal** (`shards/envelope.py:85`) — 11 values today; Phase 7
  extends by one (`role_revocation`) per D-13. All other governance event types
  already named (extract, promote, demote, contest, resolve_contest, distinguo,
  supersede, retract, role_assertion, content_edit, reparent, reconcile).
- **`AttestedSignature`** (`shards/envelope.py`) — Phase 6 D-13 reshape is final;
  Phase 7 does NOT touch it. Every governance event embeds one.
- **`verify_attestation` + `sign_attestation`** (`identity/verifier.py`, `revision/
  content_edit.py`) — Phase 7 consumes; no duplicate verification logic in
  `governance/`.
- **`canonical_content_hash` (JCS-canonical)** (`revision/content_edit.py`) — every
  governance event computes its `over_content_hash` via this seam (Phase 6 D-12).
- **pyshacl `validate_*_shape()` plumbing** (`services/shacl_validator.py:56,81` +
  `revision/content_edit_shape.ttl`) — copy the pattern for every per-event
  governance shape. New shapes live under `src/folio_insights/governance/shapes/`.
- **Phase 1 `polysemy` + Phase 6 `did` Click subgroups** — template for the new
  `governance` and `corpus` Click subgroups (D-15, D-10).
- **Phase 1 reviewer-DID local keyfile** (`~/.folio-insights/`, 0600/0700) —
  reviewers / arbiters / corpus_admins all sign via the same local-keyfile pattern.
  Phase 7 does NOT introduce new key custody.

### Established Patterns
- **New-package dep-isolation** — Phase 5 forced `revision/`, Phase 6 forced
  `identity/`, **Phase 7 forces `governance/`**. SQLite + Turtle + rdflib stay OUT
  of `governance/` (held behind the `GovernanceLog` Protocol; Phase 13 wires them
  in). Same dep-leak grep-guard pattern the prior packages used.
- **In-memory seam → Phase 13 swap** — Phase 5's `ShardStore`, Phase 6's
  `DidDocCache`, and **Phase 7's `GovernanceLog`** all follow the same template.
- **"Ship the focused SHACL shape; defer the suite to Phase 11"** — Phase 5
  pattern; Phase 7 ships only the shapes it needs for in-phase tests.
- **Click subgroup with rich.prompt interactive gate** — Phase 1's polysemy gate.
  Template for the cascade-preview interactive prompt (D-17).
- **grep-guard regression test** — Phase 1's `detector_confidence` guard.
  Template for D-16's three-module no-shared-codepath enforcement.
- **Hypothesis property tests** — Phase 2/4/6 determinism style. Template for the
  log-append-monotonic property test + active-roles-query stability test.

### Integration Points
- `GovernanceLog` Protocol (D-04) is the seam **Phase 13** (persistent storage)
  replaces — wires real `aiosqlite` + `<corpus_root>/.governance.sqlite` + the
  `BEFORE UPDATE/DELETE → RAISE FAIL` SQLite trigger (D-05 amendment) + the on-
  demand Turtle export (D-08).
- The CLI command modules (`governance/cli/{promote,contest,supersede,retract,
  role_assert,role_revoke}.py`) are the seams the **post-Phase-14 web phase**
  renders against. Web phase calls `authorize()` + `governance_log.append(event)`
  with the same `GovernanceEvent` instances — no API to invent (D-03).
- The `authorize()` function is the seam **Phase 11** (full SHACL suite) hardens
  with shape-level checks; today it's code-level + per-event SHACL belt-and-
  suspenders (D-19).
- The cascade-preview classification heuristic (D-18) consumes Phase 5 supersession
  links + Phase 3 `reconciliation_strategy` + Phase 7 contest/aporetic markers — a
  cross-cutting query the researcher must validate.
- The `corpus init` CLI (D-10 genesis) is the entry-point Phase 18.5 corpus-fork
  consumes (a fork creates a NEW genesis with a NEW corpus_admin via the same
  CLI).
- `RFC-TEMPLATE.md` (D-02) is consumed by the linter (D-22) AND by Phase 18
  (community artifacts which point contributors at the template).

</code_context>

<specifics>
## Specific Ideas

- Operator deliberately **scoped Phase 7 down to the critical-path CLI + library +
  API contracts** (mirrors Phase 6 D-01/D-02). All web-UI-bound surfaces, both P2
  UI items (GOV-09 / GOV-10), and CONTRIBUTING/CoC/GOVERNANCE prose travel forward.
  Phase 7 ships the **substrate every later phase renders or extends.**
- **Three-way disambiguation (GOV-04) is THE code-review gate of this phase.** Not
  one shared `disagree()` helper, not one base class beyond the discriminated-union
  umbrella. Three modules, three event classes, three SHACL shapes, three Click
  command modules. Grep-guard regression test fails CI if anyone tries to refactor
  toward DRY. The PRD calls disambiguation a reviewer-judgment moment; software's
  job is to refuse to make it easy to skip.
- **F6 (corpus-admin lockout) is closed by FOUR coordinated decisions**: genesis
  self-signed row 0 (D-10) + last-admin self-revocation hard-refuse (D-11) + no
  break-glass — fork-the-corpus is the remedy (D-12) + distinct `RoleRevocation`
  event (D-13). The fork-the-corpus remedy is intentionally low-tech and federated
  — matches PRD §3.1's "every corpus is autonomous" framing. Capture community
  break-glass requests post-GA as a future deferred phase if pressure builds.
- **Central `authorize()` (D-19) is the single fact-of-truth** the CLI today and
  the post-Phase-14 web phase tomorrow both call. Refusing to scatter authorization
  logic is the discipline that lets the web phase happen with zero parallel
  authorization layer to keep in sync.
- **Amended exit bar (D-05) is explicit** about SHACL + Protocol contract being the
  in-phase gate; SQLite trigger travels to Phase 13. Verifier must use the amended
  bar, not the original ROADMAP wording (Phase 6 D-12 set the precedent).
- **The 12-value `SignedAction` Literal** is the single canonical list of
  reviewer actions. Phase 7 extends Phase 6's 11 by exactly one (`role_revocation`).
  Future phases (Phase 9 distinguo deepening, Phase 11 SHACL suite) **must not**
  add new values without an ADR.

</specifics>

<deferred>
## Deferred Ideas

- **GOV-09 governance-log timeline viewer UI** (P2) — post-Phase-14 web phase.
  PROV-O log is already queryable; the styled view defers.
- **GOV-10 warrant trace-back UI** (P2) — post-Phase-14 web phase. `warrant:`
  metadata is already on every shard; the styled breadcrumb defers.
- **All web flows** (role-assertion signing UI, promotion preview, retract /
  contest / supersede modals) — post-Phase-14 web phase (D-03). Phase 7 locks
  the API contract (`authorize()` + `governance_log.append()` + 12 event classes).
- **Community-artifact files** (CONTRIBUTING.md, CODE_OF_CONDUCT.md, GOVERNANCE.md
  prose) — Phase 18 (already declares dependency on Phase 7). Phase 7 ships only
  the RFC linter mechanism + `RFC-TEMPLATE.md` (linter's golden fixture).
- **Persistent governance-log storage** (real `<corpus>/governance.ttl` writer +
  `.governance.sqlite` + `BEFORE UPDATE/DELETE → RAISE FAIL` trigger) — Phase 13
  fills the `GovernanceLog` Protocol seam D-04/D-05/D-06 ship.
- **Full `fi:SignedActionShape` SHACL verification-at-ingest suite across every
  event type** — Phase 11. Phase 7 ships per-event focused shapes only.
- **Multi-signature role grants** (e.g., M-of-N corpus_admin appointments) — uses
  Phase 6.3 multi-sig (deferred to 6.x / v2.1 phase); `cosigners[]` slot already
  reserved in Phase 6 D-13.
- **Corpus-level break-glass mechanism** (single break-glass DID, M-of-N reseed
  ceremony) — NOT shipped (D-12 — fork-the-corpus is the remedy). Capture for
  post-GA in case community asks. If pressure builds, ship a deferred sub-phase
  (e.g., "7.1 break-glass") layered on Phase 6.3 multi-sig.
- **Cascade simulation across multiple cascades with full transactional rollback**
  — REQUIREMENTS.md row 270 already defers this as "analyst power tool" beyond
  GOV-06 cascade preview. Capture explicitly here so it isn't lost.
- **Eager Turtle export `--watch` mode** for `governance export` — Phase 13 may
  add it; not needed in Phase 7.
- **`rfc lint` GitHub PR comment bot** (auto-comments on PRs touching `.planning/
  rfcs/`) — out of scope for Phase 7's CLI-only linter; Phase 18 may add it.

### Reviewed Todos (not folded)
None — STATE pending-todos = none.

</deferred>

---

*Phase: 7-Governance Model (§3.1)*
*Context gathered: 2026-05-30*
