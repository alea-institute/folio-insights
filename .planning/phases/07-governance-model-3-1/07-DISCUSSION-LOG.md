# Phase 7: Governance Model (§3.1) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in 07-CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-30
**Phase:** 7-Governance Model (§3.1)
**Areas discussed:** Phase shape / scope split; Governance-log storage substrate; Bootstrap & break-glass (F6); Retract / contest / supersede CLI surface; Residuals (authorization, citation depth, RFC linter, promotion status)

---

## Phase shape / scope split

### Q1: GOV-09 (timeline viewer UI) + GOV-10 (warrant trace-back UI) — ship now, defer, or split?

| Option | Description | Selected |
|--------|-------------|----------|
| Defer both post-Phase-14 (Recommended) | Mirror Phase 6 D-02 — P2 + needs design system + adapter-node. Phase 7 ships the underlying queryable PROV-O log + `warrant:` metadata that those views render. Avoids throwaway pre-design UI. | ✓ |
| Defer GOV-09; ship GOV-10 minimal CLI breadcrumb | Warrant trace-back is mostly a SPARQL view over present `warrant:` metadata. Timeline viewer is heavier. | |
| Ship both as CLI-rendered surfaces | `folio-insights governance timeline` + `folio-insights warrant <shard>` CLI commands now. Risk: CLI UI work the web phase mostly replaces. | |

**User's choice:** Defer both post-Phase-14 (Recommended)
**Notes:** Locks Phase 6 D-02 pattern forward; Phase 7 guarantees the data is queryable, post-Phase-14 web phase renders.

---

### Q2: GOV-08 community artifact FILES (CONTRIBUTING / CoC / GOVERNANCE / RFC-TEMPLATE) — who owns?

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 18 owns the files; Phase 7 owns only the RFC linter (Recommended) | Roadmap encodes the dependency. Phase 7 ships RFC frontmatter schema + lifecycle linter + `RFC-TEMPLATE.md` (linter's golden fixture); Phase 18 writes CONTRIBUTING/CoC/GOVERNANCE prose. | ✓ |
| Phase 7 writes stub versions of all four; Phase 18 enriches | Ship one-pagers now. Risk: double-authoring + drift. | |
| Phase 7 writes RFC-TEMPLATE.md + GOVERNANCE.md only | Hybrid: GOVERNANCE.md is close to phase domain. CONTRIBUTING + CoC clearly Phase 18. | |

**User's choice:** Phase 18 owns the files; Phase 7 owns only the RFC linter (Recommended)
**Notes:** Cleanest split. Phase 7 ships `RFC-TEMPLATE.md` (the linter's golden fixture) + the linter mechanism. Phase 18 writes the prose later.

---

### Q3: Web surfaces for governance flows — defer like Phase 6 did?

| Option | Description | Selected |
|--------|-------------|----------|
| Defer all web surfaces post-Phase-14 (Recommended) | Match Phase 6 D-02. Ship CLI + API contract here; web phase calls the same functions. Locks GOV-04 prompt copy + GOV-06 preview shape in the API. | ✓ |
| Ship CLI only; web phase invents API later | Risk: drift, double-authoring. | |

**User's choice:** Defer all web surfaces post-Phase-14 (Recommended)
**Notes:** Phase 7's `authorize()` + `governance_log.append()` is the contract. Web phase calls the same functions.

---

## Governance-log storage substrate

### Q1: Persistence depth (GOV-02 names BOTH SHACL AND a SQLite trigger)

| Option | Description | Selected |
|--------|-------------|----------|
| In-memory seam + real SHACL, defer trigger to Phase 13 (Recommended) | `GovernanceLog` Protocol + `InMemoryGovernanceLog`. `fi:GovernanceLogShape` SHACL is real now. SQLite trigger ships with Phase 13. Mirrors Phase 5 D-02 + Phase 6 D-11. Amend GOV-02 exit-bar like Phase 6 D-12. | ✓ |
| Real append-only Turtle writer + tiny aiosqlite ledger now | Literal exit-criterion match. Risk: Phase 13 reshapes and forces rewrite. | |
| Hybrid: SHACL real + aiosqlite ledger now; Turtle export deferred | Ship trigger now; Turtle export via CLI later. | |

**User's choice:** In-memory seam + real SHACL, defer trigger to Phase 13 (Recommended)
**Notes:** Keeps storage libs out of `governance/` package (same dep-discipline as `revision/` and `identity/`).

---

### Q2: Write API (how callers append events)

| Option | Description | Selected |
|--------|-------------|----------|
| Single `governance_log.append(event)` (Recommended) | One entry point. `GovernanceEvent` discriminated union over 12 action types. Mirrors Phase 5 `edit_shard_content()` frozen call site. | ✓ |
| Per-action methods on the log | `append_promotion()` etc. Bleeds GOV-04's "distinct codepaths" into storage. | |
| Free-form RDF triples in | Lowest discipline. | |

**User's choice:** Single `governance_log.append(event)` (Recommended)
**Notes:** All callers (CLI, future API, future web phase) go through this seam.

---

### Q3: Log location on disk (when Phase 13 persists)

| Option | Description | Selected |
|--------|-------------|----------|
| `<corpus_root>/governance.ttl` + `<corpus_root>/.governance.sqlite` (Recommended) | Matches PRD §3.1.5 verbatim. Self-contained per corpus. `corpus fork` copies governance with corpus. | ✓ |
| Central `.folio-insights/governance/<corpus_id>.{ttl,sqlite}` | Cleaner separation but breaks "corpus is self-contained" + complicates fork. | |
| Named graph inside central Oxigraph store | Maximally federated but Phase 13 owns Oxigraph. | |

**User's choice:** `<corpus_root>/governance.ttl` + `<corpus_root>/.governance.sqlite` (Recommended)
**Notes:** Self-containment matches Phase 18.5 corpus-fork semantics.

---

### Q4: Export mode (when Phase 13 lands)

| Option | Description | Selected |
|--------|-------------|----------|
| On-demand only — `folio-insights governance export <corpus>` (Recommended) | SQLite ledger = source of truth; Turtle = derived view. Avoids partial-write corruption. | ✓ |
| Eager — write Turtle on every event | Live `governance.ttl` always current. Doubles write cost. | |
| Both — default on-demand, `--watch` opt-in | Most flexible; little marginal value pre-Phase-13. | |

**User's choice:** On-demand only — `folio-insights governance export <corpus>` (Recommended)
**Notes:** Phase 13 may add `--watch` if needed.

---

## Bootstrap & break-glass (F6)

### Q1: Genesis admin (first corpus_admin appointment)

| Option | Description | Selected |
|--------|-------------|----------|
| Self-signed genesis `RoleAssertion` at row 0 (Recommended) | DID signs its OWN `RoleAssertion`. Narrow SHACL carve-out: position=0 AND self-signed AND role=corpus_admin only. CLI: `folio-insights corpus init --admin-did did:...`. | ✓ |
| M-of-N genesis signers manifest | More federated; heavier ceremony for single-maintainer corpora. | |
| Constitutional project-admin DID issues first assertion | Centralized; violates per-corpus autonomy. | |

**User's choice:** Self-signed genesis `RoleAssertion` at row 0 (Recommended)
**Notes:** Documented bootstrap exception; preserves append-only invariant.

---

### Q2: Self-revocation (last admin)

| Option | Description | Selected |
|--------|-------------|----------|
| Hard refuse when revocation would leave 0 active admins (Recommended) | `WouldLockoutCorpusAdmin` error. Forces appoint-successor-first ordering. Closes F6. | ✓ |
| Allow self-revoke + emit warning | Risk: silent corpus lockout. | |
| Allow self-revoke only with co-signed break-glass event | Adds break-glass concept (see Q3). | |

**User's choice:** Hard refuse when revocation would leave 0 active admins (Recommended)
**Notes:** SHACL + code both enforce; structurally safe ordering.

---

### Q3: Break-glass mechanism for catastrophic key loss

| Option | Description | Selected |
|--------|-------------|----------|
| No — fork the corpus is the remedy (Recommended for v2.0) | Phase 18.5 owns corpus-fork. Old corpus becomes read-only history. Matches PRD §3.1 per-corpus autonomy framing. | ✓ |
| Yes — single `break_glass_did` configured at corpus genesis | Burns on use; recorded in log. | |
| Yes — M-of-N break-glass ceremony | Heavier; defers to a later phase. | |

**User's choice:** No — fork the corpus is the remedy (Recommended for v2.0)
**Notes:** Capture community break-glass requests as deferred idea post-GA.

---

### Q4: Revocation event shape (append-only log)

| Option | Description | Selected |
|--------|-------------|----------|
| Append a distinct `fi:RoleRevocation` event referencing prior assertion IRI (Recommended) | Extend `SignedAction` Literal with `role_revocation`. Distinct codepath. Clean PROV-O semantics. | ✓ |
| Append `RoleAssertion` with `revoked=true` flag | Less PROV-O-pure; harder to validate. | |
| Append `RoleAssertion` with empty `roles[]` | Conflates revocation with downgrade. | |

**User's choice:** Append a distinct `fi:RoleRevocation` event (Recommended)
**Notes:** Mirrors GOV-04 three-way disambiguation philosophy at the schema level.

---

## Retract / contest / supersede CLI surface

### Q1: CLI command shape (GOV-04 locks "distinct CLI commands")

| Option | Description | Selected |
|--------|-------------|----------|
| Subgroup: `folio-insights governance {contest\|supersede\|retract}` (Recommended) | Three subcommands, three modules. Discoverable via `--help`. Parity with Phase 6 `did` subgroup. | ✓ |
| Three top-level commands | Pollutes root namespace. | |
| Single command with `--mode` | Violates GOV-04 + PRD §21.8. | |

**User's choice:** Subgroup: `folio-insights governance {contest|supersede|retract}` (Recommended)
**Notes:** Locks namespace parity with `did` and `polysemy`.

---

### Q2: "No shared codepath" enforcement (the code-review gate)

| Option | Description | Selected |
|--------|-------------|----------|
| Separate modules + grep-guard regression test (Recommended) | Three modules under `governance/{contest,supersede,retract}.py`. Grep-guard fails CI on cross-imports / shared base classes / shared command implementations. `AttestedSignature` is the only shared primitive. | ✓ |
| Three completely separate top-level packages | Heaviest discipline but breaks codebase navigation. | |
| Code-review only (no automated gate) | GOV-04 explicitly calls it a gate; should automate. | |

**User's choice:** Separate modules + grep-guard regression test (Recommended)
**Notes:** Mirrors Phase 1 `detector_confidence` grep-guard pattern.

---

### Q3: Retraction-cascade preview UX

| Option | Description | Selected |
|--------|-------------|----------|
| Interactive default + `--preview` dry-run + `--apply <report.json>` (Recommended) | Three modes, shared preview-builder. `--apply` verifies state hasn't changed since preview. | ✓ |
| Interactive only (no `--apply`) | Loses audit-path use case. | |
| Preview-then-apply only (no interactive) | Friction tax on every retraction. | |

**User's choice:** Interactive default + `--preview` dry-run + `--apply <report.json>` (Recommended)
**Notes:** Fast-path + audit-path both supported; same preview-builder backs both.

---

### Q4: Dependents classification heuristic — lock or defer?

| Option | Description | Selected |
|--------|-------------|----------|
| Lock here (Recommended) | `auto_rederive`: prefer_latest + supersession available. `aporetic`: no supersession + no reviewer marker. `review_needed`: any reviewer-disagreement marker OR contested/aporetic OR human-judgment reconciliation_strategy. | ✓ |
| Defer to researcher | Let RESEARCH.md propose. | |
| Lock 3 buckets + escape hatch | Lock + hidden 4th `unknown` bucket. | |

**User's choice:** Lock here (Recommended)
**Notes:** Researcher / planner own the exact SPARQL CONSTRUCT; the rule is locked.

---

## Residuals

### Q1: Authorization enforcement surface

| Option | Description | Selected |
|--------|-------------|----------|
| Central `authorize(did, action, corpus)` called by every command (Recommended) | One function. CLI + API + web phase all call it. SHACL is belt-and-suspenders at storage. Mirrors Phase 6 `verify_attestation`. | ✓ |
| Click decorator `@requires_role(...)` | Couples auth to Click layer; bleeds into testing. | |
| Pure SHACL | Opaque error messages; commands construct-then-fail. | |

**User's choice:** Central `authorize(did, action, corpus)` (Recommended)
**Notes:** Single fact-of-truth for authorization across CLI / future API / future web.

---

### Q2: Promotion citation depth (GOV-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Non-empty + resolvable to local-store shard (Recommended) | ≥1 `depends_on_precedents` or `depends_on_definitions` IRI; cited IRI resolves; cited IRI ≠ promoted shard. | ✓ |
| Non-empty only | Lets typos through. | |
| Non-empty + resolvable + epistemic_status check | Encodes a debatable rule into software. | |

**User's choice:** Non-empty + resolvable (Recommended)
**Notes:** "Is good law" is reviewer judgment, not software.

---

### Q3: RFC linter scope + execution

| Option | Description | Selected |
|--------|-------------|----------|
| Frontmatter schema + monotonic status transitions + CI + pre-commit (Recommended) | Pydantic-validated frontmatter; `NNNN-kebab-title.md` filename; monotonic status across git history; `rejected` terminal; no body-only status flip. CI: `python -m folio_insights.rfc.lint`. RFC-TEMPLATE.md is the golden fixture. | ✓ |
| Frontmatter + filename only, no transition check | Loses "no auto-merge" protection GOV-07 names. | |
| Full lifecycle linter + auto-PR-comment bot | Out of scope for Phase 7; defer. | |

**User's choice:** Frontmatter schema + monotonic status transitions + CI + pre-commit (Recommended)
**Notes:** RFC-TEMPLATE.md ships in Phase 7 as the linter's golden fixture.

---

### Q4: Promotion `epistemic_status` selection

| Option | Description | Selected |
|--------|-------------|----------|
| Reviewer specifies via `--status` flag; validator checks consistency with citation kind (Recommended) | `authority_only` requires AuthorityShard citation; `demonstrable` requires citation to be `demonstrable`+; `per_se_nota_quoad_nos` is axiomatic (no citation depth check). | ✓ |
| Inferred from citation kind — no reviewer choice | Removes reviewer agency PRD §3.1.2 expects. | |
| Reviewer specifies; no validator check | Loses obvious-mismatch shape check. | |

**User's choice:** Reviewer specifies via `--status`; validator checks consistency (Recommended)
**Notes:** Reviewer judgment is the source; software validates shape.

---

## Claude's Discretion

- Package layout under `src/folio_insights/governance/` (modules: `log.py`, `events.py`, `authorize.py`, `roles.py`, `promote.py`, `contest.py`, `supersede.py`, `retract.py`, `cli/`, `shapes/`). Must respect D-16 grep-guard constraints.
- Exact SHACL TTL for `fi:GovernanceLogShape` + per-event shapes. Mirror Phase 5 `revision/content_edit_shape.ttl` pattern.
- `rfc.lint` git-history walk strategy (subprocess git log vs GitPython vs pure shell). Minimal-deps preference.
- Exact SPARQL CONSTRUCT for the cascade-preview dependents query implementing D-18.
- Whether to ship a focused `fi:SignedActionShape` shape now (Phase 5 pattern) or to verify per-event shapes only and let Phase 11 build the suite.
- Exact Click surface for `folio-insights corpus init` (the genesis row-0 CLI for D-10).

## Deferred Ideas

- GOV-09 timeline viewer UI (P2) — post-Phase-14 web phase.
- GOV-10 warrant trace-back UI (P2) — post-Phase-14 web phase.
- Web flows for governance actions — post-Phase-14 (D-03).
- Community-artifact prose (CONTRIBUTING, CoC, GOVERNANCE) — Phase 18 (D-02).
- Persistent governance log (real Turtle writer + aiosqlite + SQLite trigger) — Phase 13 (D-04/D-05).
- Full `fi:SignedActionShape` SHACL suite — Phase 11.
- Multi-sig role grants — uses Phase 6.3 multi-sig (deferred).
- Corpus-level break-glass mechanism — NOT shipped (D-12). Capture for post-GA.
- Multi-cascade transactional rollback — REQUIREMENTS.md row 270 deferral.
- Eager Turtle export `--watch` mode — Phase 13.
- `rfc lint` GitHub PR comment bot — Phase 18 or later.
