---
phase: 0
plan: 8
plan_number: 8
plan_name: decision-md-synthesis-and-fuseki-pivot-scaffold
subsystem: foundations-hard-gate
tags: [phase-0, decision-artifact, keep-pyoxigraph, branch-guidance, fuseki-scaffold, signature-deferral, oq4-resolution, d-17]
dependency_graph:
  requires:
    - .planning/phases/00-foundations-hard-gate/00-CONTEXT.md
    - .planning/phases/00-foundations-hard-gate/00-RESEARCH.md
    - .planning/phases/00-foundations-hard-gate/00-03-SUMMARY.md
    - .planning/phases/00-foundations-hard-gate/00-05-SUMMARY.md
    - .planning/phases/00-foundations-hard-gate/00-06-SUMMARY.md
    - .planning/phases/00-foundations-hard-gate/00-06-TUNING-LOG.md
    - .planning/phases/00-foundations-hard-gate/00-07-SUMMARY.md
    - .planning/phases/00-foundations-hard-gate/00-07-MEASUREMENTS.md
  provides:
    - .planning/phases/00-foundations-hard-gate/00-DECISION.md
    - .planning/phases/00-foundations-hard-gate/00-BRANCH-GUIDANCE.md
    - fuseki/config.ttl
    - fuseki/README.md
    - fuseki/.gitkeep
  affects:
    - Phase 6 (DID substrate — inherits signature backfill procedure)
    - Phase 10 (Arq worker — keep-branch embeds pyoxigraph in-process)
    - Phase 11 (SHACL — keep-branch uses rdflib bridge; Pitfall 2 drop-guard load-bearing)
    - Phase 13 (Storage + RocksDB — keep-branch unlocks Gate 2 Pass 3 tuning)
    - Phase 16 (Public SPARQL — keep-branch SEC-01 hand-rolled hardening)
tech_stack:
  added: []
  patterns:
    - "D-17 DECISION.md schema (verdict + per-gate table + tuning passes + branch guidance + signature slot)"
    - "Pre-committed pivot scaffold retained across verdicts (dead config-as-code on keep; active on pivot)"
    - "Signature deferral with 4-step backfill procedure (DID substrate doesn't exist yet per D-17 chicken-and-egg)"
    - "Duplicated branch-guidance doc at stable @-reference path for downstream PLAN.md consumption"
    - "SUPERSEDED-BY addendum pattern (never edit DECISION.md in-place post-commit per T-00-39)"
key_files:
  created:
    - .planning/phases/00-foundations-hard-gate/00-DECISION.md
    - .planning/phases/00-foundations-hard-gate/00-BRANCH-GUIDANCE.md
    - .planning/phases/00-foundations-hard-gate/00-08-SUMMARY.md
    - fuseki/config.ttl
    - fuseki/README.md
    - fuseki/.gitkeep
  modified:
    - .planning/STATE.md
    - .planning/ROADMAP.md
    - .planning/REQUIREMENTS.md
decisions:
  - "00-08-D1: Verdict = keep=pyoxigraph — all ship-critical gates (1/2/3/5) PASS; Gates 4 and D-11 deferred but harness-ready and not pivot-triggers per OQ4 numeric policy"
  - "00-08-D2: OQ4 resolved — pivot requires ONE of (a) Gate 1 STRICT fail, (b) Gate 2 warm P95 > 800ms post-tune, (c) Gate 5 Mode 1 determinism fail; Gates 3/4/D-11 trigger escape-hatches, NOT pivot"
  - "00-08-D3: DID signature DEFERRED to Phase 6+ per D-17 chicken-and-egg; 4-step backfill procedure documented in DECISION.md §Signature Deferral with T-00-39 substitute-then-sign mitigation"
  - "00-08-D4: Fuseki scaffold materialized on keep verdict (config.ttl + README + .gitkeep) and retained for v2.1 re-evaluation per T-00-40 mitigation; README status banner reflects keep=pyoxigraph (scaffold not required)"
  - "00-08-D5: BRANCH-GUIDANCE.md lives at stable @-reference path (separate from DECISION.md) so downstream PLAN.md files can @file-import without re-parsing the DECISION body; drift between the two is explicitly a bug"
metrics:
  duration_minutes: 20
  tasks_completed: 3
  files_created: 6
  files_modified: 3
  completed_date: 2026-04-23
requirements_addressed:
  - SEC-01
  - SEC-02
---

# Phase 0 Plan 8: decision-md-synthesis-and-fuseki-pivot-scaffold Summary

Phase 0 HARD GATE closed with verdict **keep=pyoxigraph** — the locked v2.0 stack (pyoxigraph 0.5.7 + rdflib 7.6 bridge + owlready2/HermiT + SvelteKit 5 adapter-node + Dagger CI) validates against reality across all ship-critical gates, with DECISION.md as the binding artifact for Phases 1-20 and the Fuseki scaffold retained as pre-committed v2.1 re-evaluation capacity.

## Final Verdict

**keep=pyoxigraph**

*Driver:* All ship-critical gates pass — Gate 1 (13/13 RDF-12 gold + 5/5 adversarial + 32/32 tests), Gate 2 (worst-case P95 = 116.95 ms vs 500 ms hard target, >4x headroom), Gate 3 (74.6 MB worker image vs 500 MB hard target, 15% utilization), Gate 5 Mode 1 (bit-identical digest across back-to-back local Dagger runs — web sha256 `b36de1fe...6edd`, worker sha256 `b2abdffc...b309f`). Gate 4 (SSR cold-page P95) and D-11 (full-1M HermiT reasoning) deferred to verify session with runnable harnesses; neither is a pivot-trigger gate by the D-17 decision schema.

### Per-Gate Verdict Counts

| Bucket | Count | Gates |
|--------|-------|-------|
| PASS | 4 | Gate 1, Gate 2, Gate 3, Gate 5 (Mode 1) |
| ACCEPT-WITH-SLO | 0 | — |
| DEFERRED (harness-ready; NOT pivot trigger) | 1 | Gate 4 |
| ESCAPE-HATCH (NOT pivot) | 0 | — |
| FAIL (pivot) | 0 | — |

Plus cross-cut (not gate): D-11 full-1M = DEFERRED pending verify session + `.owl` fixture.

## What Was Built

- **`.planning/phases/00-foundations-hard-gate/00-DECISION.md`** (138 lines): the binding Phase 0 verdict per D-17, synthesized from all 5 gate SUMMARYs + tuning logs + measurements. Includes verdict + per-gate measurement table (all 5 rows populated with real values + source citations) + tuning-passes section (Gates 2/3/4 with Pass 0 baselines and documented deferrals) + downstream phase branch-guidance table (Phases 6/10/11/13/16) + escape-hatch triggers (Gates 3/4, D-11, Gate 5 Mode 2 — each NOT a pivot trigger) + OQ 1-5 resolutions + Signature Deferral procedure + Provenance table. Commit: **3f9e7a3**.

- **`.planning/phases/00-foundations-hard-gate/00-BRANCH-GUIDANCE.md`** (42 lines): standalone branch-guidance doc that duplicates the DECISION.md branch table at a stable `@`-reference path. Downstream PLAN.md files add one `@`-import line and branch frontmatter/tasks on `Verdict`. Commit: **7dd654d**.

- **Fuseki scaffold** (`fuseki/config.ttl` 15 lines, `fuseki/README.md` 41 lines, `fuseki/.gitkeep`): Fuseki 5.x TDB2 assembler config (valid Turtle) + docker-run invocation + v2.1 re-evaluation note. Materialized on both verdicts per T-00-40 (Phase 16 config-as-code diff review is a keep-branch mitigation requirement). README status banner: `keep=pyoxigraph (scaffold not required; retained for v2.1 re-evaluation)`. Commit: **7dd654d**.

## Key Decisions

### 00-08-D1: Verdict = keep=pyoxigraph

All four ship-critical gates (1, 2, 3, 5 Mode 1) pass with margin. Gate 4 and D-11 carry runnable harnesses but their measurements are deferred to the verify session — per OQ4 resolution (00-08-D2), these are NOT pivot triggers. Decision tree from DECISION.md Step 2:

```
Gate 1 STRICT: PASS (13/13 gold, 5/5 adversarial)    → no pivot
Gate 2 warm P95: 116.95 ms << 800 ms hard ceiling    → no pivot
Gate 5 Mode 1: bit-identical digest                   → no pivot
⇒ verdict = keep=pyoxigraph
```

### 00-08-D2: OQ4 numeric policy resolution

CONTEXT.md Open Question 4 (Fuseki pivot trigger numeric threshold) was qualitative in D-06/D-07. DECISION.md §Open Question Resolutions item 4 codifies the binding policy:

> Pivot requires ONE of: (a) Gate 1 failure (D-04 STRICT), (b) Gate 2 warm P95 > 800 ms post-tune, (c) Gate 5 Mode 1 local-determinism failure. This is the canonical numeric policy. Gate 4 cold-page > 400 ms triggers per-surface deferred-hydration (not full adapter swap, not pivot). Gate 3 > 700 MB triggers reasoner-microservice split (not pivot). D-11 > 2 h OR OOM triggers incremental TBox streaming in Phase 9.P7 (not pivot).

### 00-08-D3: Signature deferral

Per D-17 chicken-and-egg, Phase 0 cannot DID-sign DECISION.md because the DID substrate ships in Phase 6. Authenticity until Phase 6 = git commit sha + optional GPG signature. 4-step backfill procedure (Phase 6 DID method → post-ship signing task → addendum commit → SUPERSEDED-BY on any gate invalidation) addresses T-00-35 repudiation + T-00-39 substitute-then-sign via "verify body matches git-sha'd commit before signing" requirement.

### 00-08-D4: Fuseki scaffold retained on keep verdict

Per plan success criteria ("if verdict = keep, fuseki/ directory still exists with README stating 'scaffold not required; kept for v2.1 re-evaluation'") and T-00-40 (Phase 16 config-as-code diff review). The config.ttl is dead config-as-code on keep; if v2.1 re-evaluation triggers (corpus growing past 10M triples, or RDF-12 spec changes), the scaffold is ready without a second research pass. Zero cost to keep; non-zero cost to delete + re-research.

### 00-08-D5: BRANCH-GUIDANCE.md as separate @-ref doc

DECISION.md is the source of truth; BRANCH-GUIDANCE.md duplicates its branch table at a predictable path so downstream PLAN.md files can write one `@.planning/phases/00-foundations-hard-gate/00-BRANCH-GUIDANCE.md` import line instead of parsing DECISION.md sections. Drift between the two is explicitly a bug (DECISION.md updates must replicate to BRANCH-GUIDANCE.md).

## Fuseki Scaffold Status

- `fuseki/config.ttl` — materialized (15 lines, valid Fuseki 5.x TDB2 assembler — `fuseki:Service` + `tdb2:DatasetTDB2` + `arq:queryTimeout=30000`)
- `fuseki/README.md` — materialized with **keep** banner: `**Status (Phase 0 DECISION):** keep=pyoxigraph (scaffold not required; retained for v2.1 re-evaluation)`
- `fuseki/.gitkeep` — present to anchor the directory even though config + README are also committed

## DID-Signing Procedure

**NOT invoked in Phase 0.** Deferred to Phase 6+ per D-17 chicken-and-egg. The signature slot in DECISION.md is empty (comment-only block). Authenticity chain until Phase 6:

- Git commit sha of DECISION.md introducing commit: **3f9e7a3**
- Git author: Damien Riehl <damienriehl@gmail.com>
- Git signature: none (no GPG configured on this project)

Phase 6 DID-signing task will append the signature as an addendum below §Signature Deferral, NOT re-write the DECISION body, and MUST verify the body matches the git-sha'd commit before signing (T-00-39 mitigation).

## Resolution of CONTEXT.md OQ 4 (verbatim)

From DECISION.md §Open Question Resolutions (quoted verbatim per output spec):

> **OQ 4 (Fuseki pivot trigger numeric threshold):** **Resolved here.** The D-05 hard ceiling of 800 ms stands; Gates 3/4 do NOT trigger pivot (they trigger escape-hatches per D-06/D-07). Therefore pivot requires ONE of: (a) Gate 1 failure (D-04 STRICT), (b) Gate 2 warm P95 > 800 ms post-tune, (c) Gate 5 Mode 1 local-determinism failure. This is the canonical numeric policy. Gate 4 cold-page > 400 ms triggers per-surface deferred-hydration (not full adapter swap, not pivot). Gate 3 > 700 MB triggers reasoner-microservice split (not pivot). D-11 > 2 h OR OOM triggers incremental TBox streaming in Phase 9.P7 (not pivot).

## Downstream Phases That MUST Read DECISION.md + BRANCH-GUIDANCE.md

Before writing their first PLAN.md, the following phase planners MUST `@`-reference both `.planning/phases/00-foundations-hard-gate/00-DECISION.md` and `.planning/phases/00-foundations-hard-gate/00-BRANCH-GUIDANCE.md`:

- **Phase 6** — DID substrate + signature backfill owner; picks up the 4-step backfill procedure
- **Phase 10** — Arq worker; keep-branch embeds pyoxigraph in-process with Plan 00-07 HermitHarness
- **Phase 11** — SHACL @ scale; keep-branch uses rdflib bridge with Pitfall 2 drop-guard, annotation shapes via `query_rdf12` SPARQL ASK
- **Phase 13** — Storage + RocksDB; keep-branch unlocks Gate 2 Pass 3 RocksDB tuning (first disk-backed store measurement)
- **Phase 16** — Public SPARQL endpoint; keep-branch hand-rolls SPARQL-injection hardening (parser-based SERVICE allowlist replaces Plan 00-03 regex preflight)

## Deviations from Plan

None — plan executed exactly as written across all three tasks.

- Task 1 (Synthesize DECISION.md): executed per action steps 1-4, all self-audit checklist items satisfied, all 10 acceptance-criteria `grep` invariants green. Commit 3f9e7a3.
- Task 2 (Materialize fuseki/ + BRANCH-GUIDANCE.md): executed per action steps 1-4, banner substitution confirmed (`keep=pyoxigraph (scaffold not required; retained for v2.1 re-evaluation)`), all 11 acceptance-criteria invariants green. Commit 7dd654d.
- Task 3 (Checkpoint: user approves verdict): user replied "approved" — no changes requested.

## Phase 0 DONE

**Phase 00-foundations-hard-gate is DECLARED DONE.**

All 8 plans complete (00-01 through 00-08), all 5 gates measured or harness-ready, decision artifact committed, downstream-phase branch guidance published, Fuseki pivot scaffold materialized as pre-committed v2.1 re-evaluation capacity. Phases 1-20 can now plan against a binding substrate verdict.

ROADMAP.md Phase 0 checkbox: **flip to checked**.

## Downstream Impact

- **Phase 1 (Polysemy spike)** — can now open; storage substrate is known; spike does not touch RDF storage so no branch decision needed beyond "use pyoxigraph" default
- **Phase 2 (Shard envelope)** — can now open; no RDF storage touchpoint, Pydantic-only work
- **Phases 6/10/11/13/16** — MUST read DECISION.md + BRANCH-GUIDANCE.md before writing their first plan (see list above)
- **Phase 14 (UI design contract)** — SSR prototype from Plan 00-07 is the starting point; Gate 4 measurement feeds Phase 14 UI performance budget when verify session lands
- **Phase 19 (security audit)** — T-00-39 substitute-then-sign mitigation, T-00-40 config-as-code diff review, and SEC-01 hardening all pre-noted for audit scope

## Threat Flags

None — no new security surface introduced. DECISION.md + BRANCH-GUIDANCE.md are documentation artifacts; fuseki/config.ttl is dead config on keep verdict (activation requires explicit docker-run per README).

## Commits

| # | Task | Commit | Description |
|---|------|--------|-------------|
| 1 | Synthesize DECISION.md | 3f9e7a3 | docs(00-08): synthesize Phase 0 DECISION.md — verdict=keep=pyoxigraph |
| 2 | Materialize fuseki/ + BRANCH-GUIDANCE.md | 7dd654d | docs(00-08): materialize fuseki/ scaffold + BRANCH-GUIDANCE.md (keep verdict) |
| 3 | Checkpoint approved — no commit (documentation step) | — | (user approved; no code change) |

## Self-Check: PASSED

All files claimed above exist on disk:

- `.planning/phases/00-foundations-hard-gate/00-DECISION.md` — FOUND (138 lines)
- `.planning/phases/00-foundations-hard-gate/00-BRANCH-GUIDANCE.md` — FOUND (42 lines)
- `.planning/phases/00-foundations-hard-gate/00-08-SUMMARY.md` — FOUND (this file)
- `fuseki/config.ttl` — FOUND (15 lines, valid Turtle)
- `fuseki/README.md` — FOUND (41 lines, keep banner)
- `fuseki/.gitkeep` — FOUND (0 bytes)

All commits claimed above exist in git log:

- 3f9e7a3 — FOUND (docs(00-08): synthesize Phase 0 DECISION.md — verdict=keep=pyoxigraph)
- 7dd654d — FOUND (docs(00-08): materialize fuseki/ scaffold + BRANCH-GUIDANCE.md (keep verdict))

---

*Plan 00-08 completed 2026-04-23. Phase 0 HARD GATE is CLOSED with keep=pyoxigraph verdict. Ready for Phase 1+.*
