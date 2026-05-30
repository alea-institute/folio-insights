---
phase: 7
slug: governance-model-3-1
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-30
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Sourced
> from RESEARCH.md `## Validation Architecture` + CONTEXT.md `<decisions>` D-04
> through D-22. Populated by the planner during plan creation (task-row table).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio + Hypothesis (per Phase 2/5/6 precedent) |
| **Config file** | `pyproject.toml` (existing `[tool.pytest.ini_options]`) |
| **Quick run command** | `uv run pytest tests/governance -x -q` |
| **Full suite command** | `uv run pytest tests/ -q` |
| **Estimated runtime** | ~15 s quick / ~90 s full |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/governance -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green; grep-guards + dep-leak guards green; SHACL shape contract tests green; rfc.lint exit-0 on `.planning/rfcs/`.
- **Max feedback latency:** 15 seconds (quick) / 90 seconds (full)

---

## Per-Task Verification Map

*Populated by gsd-planner during plan creation. Each plan's `<task>` blocks emit
a row here. Required columns:*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| _populated by planner_ | | | | | | | | | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 (pre-Wave-1 test scaffolding) — minimal, since pytest infrastructure
already exists from Phases 2/5/6. Planner adds rows here if any are MISSING:

- [ ] `tests/governance/__init__.py` — package marker
- [ ] `tests/governance/conftest.py` — shared fixtures (InMemoryGovernanceLog factory, genesis-DID fixture, sample RoleAssertion events, sample shards-with-deps for cascade tests)
- [ ] `tests/governance/fixtures/` — sample SHACL graphs + sample PROV-O log states

*Existing infrastructure covers all other phase requirements (pytest config,
pyshacl validator harness, identity signer fixtures, shard-store fixtures).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `corpus init` interactive flow w/ rich.prompt | CORPUS-05 | TTY-bound prompt | `folio-insights corpus init --admin-did did:fi:test...` — verify confirmation prompt, accept, observe row 0 in `governance log show` |
| `governance retract` interactive default flow | GOV-06 | `Confirm? [y/N]` prompt | `folio-insights governance retract fi:shard:...` — verify grouped table renders, accept, observe cascade applied |
| `governance retract --preview` then `--apply` flow | GOV-06 D-17 | File round-trip across CLI invocations | Run `--preview` → inspect JSON → run `--apply <file>` → verify `PreviewStale` refuses stale state |

*All other phase behaviors have automated verification — see Per-Task Map.*

---

## Validation Dimensions (Nyquist)

Drawn from RESEARCH.md `## Validation Architecture`. Each dimension must have
≥1 automated test before phase verification can pass:

1. **SHACL shape coverage** — 8 shape TTL files (`GovernanceLogShape`,
   `RoleAssertionShape`, `RoleRevocationShape`, `PromotionShape`, `ContestShape`,
   `SupersessionShape`, `RetractionShape`, `ContestResolutionShape`) each get a
   conforms-true + conforms-false test (positive + negative polarity, mirroring
   Phase 5 `validate_content_edit_shape()` pattern).
2. **Grep-guard codepath isolation (D-16)** — three regression tests:
   (a) no cross-imports among `contest.py` / `supersede.py` / `retract.py`,
   (b) no shared base class beyond the `GovernanceEvent` discriminated union,
   (c) no shared Click command implementation function.
3. **Dep-leak guard (Phase 5 precedent)** — `tests/governance/test_dep_leak_guard.py`
   refuses any import of `aiosqlite`, `rdflib`, `pyoxigraph` from
   `src/folio_insights/governance/` (held behind `GovernanceLog` Protocol).
4. **`authorize()` defense-in-depth** — table-driven test for `(did, action, corpus)
   → Allow | Deny(reason)`. Every action-role pair tested; defense-in-depth verified
   by also confirming the per-event SHACL shape refuses when `authorize` would.
5. **Append-only invariants** — `InMemoryGovernanceLog` contract test:
   `position` monotonic, no public mutation API on past rows, SHACL refusal of
   `DELETE`/`UPDATE` on past rows. Hash-chain coverage if A-shipped (research Q2).
6. **Citation-resolvability (D-20)** — promotion validator refuses unresolvable
   IRIs, refuses self-citation, accepts ≥1 resolvable cited shard.
7. **Promotion epistemic-status consistency (D-21)** — per-status validator
   tests: `authority_only` requires AuthorityShard cited, `demonstrable` requires
   demonstrable-or-stronger cited, `per_se_nota_quoad_nos` requires no citation
   depth check.
8. **Last-admin self-revocation hard-refuse (D-11)** — SHACL + code both refuse;
   error `WouldLockoutCorpusAdmin: ...` returned.
9. **Genesis bootstrap carve-out (D-10)** — position=0 + self-signed +
   role=corpus_admin accepted; every other self-signed assertion refused.
10. **Cascade-preview classification heuristic (D-18)** — fixture corpora with
    each of `auto_rederive` / `aporetic` / `review_needed` paths; classifier
    returns expected partition.
11. **`--preview` / `--apply` round-trip (D-17)** — preview JSON written,
    re-apply succeeds; if dependents set or any classification differs,
    `PreviewStale` raised; cross-invocation file round-trip via `tmp_path`.
12. **Monotonic status transitions in rfc.lint (D-22)** — `tmp_path` `git init`
    fixture, write RFC frontmatter mutations across commits, lint must pass for
    legal DAG and fail for `accepted → draft` / body-only edits without
    `Reason:` trailer.
13. **Three-way distinct CLI surfaces** — `--help` snapshot tests for
    `folio-insights governance {contest,supersede,retract}` confirm three
    distinct subcommand modules / docstrings / signatures.
14. **Hypothesis property tests** — log-append monotonic; active-roles query
    stability across role assertion / revocation interleavings.
15. **End-to-end CLI gate (orig EC3)** — unsigned `promote` rejected end-to-end
    via `folio-insights governance promote` (CLI-only per D-03 amended bar).

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s (full)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
