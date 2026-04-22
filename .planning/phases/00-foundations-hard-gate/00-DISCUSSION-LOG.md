# Phase 0: Foundations / HARD GATE - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in 00-CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-22
**Phase:** 00-foundations-hard-gate
**Areas discussed:** Benchmark corpus + gold queries, Gate-failure rules, Spike scope + timeboxing, Load generator design

---

## Benchmark corpus + gold query set

### Q1: Corpus composition

| Option | Description | Selected |
|--------|-------------|----------|
| Scaled real (v1 + FRE + Restatement × N) | Re-extract v1, add FRE + Restatement, replay bitemporal edits to 1M | ✓ |
| Mixed: 3-corpus real + faker fill | Natural count + faker to 1M | |
| Pure synthetic (faker w/ ratios) | 100% generated; deterministic; fast | |
| Three-corpus real + adjust gate | Amend QUALITY-01 to actual count | |

**User's choice:** Scaled real — realistic shape preserved; reusable downstream.

### Q2: Gold query set

| Option | Description | Selected |
|--------|-------------|----------|
| §20 + adversarial edge cases | §20 + 3-5 GRAPH/CONSTRUCT/SERVICE stress queries | ✓ |
| §20 only | Pure spec compliance | |
| §20 + roadmap-phase queries | Phase 15 UI surface queries | |
| Claude derives from all sources | Widest coverage | |

**User's choice:** §20 + adversarial — feeds Phase 16 security testing for free.

### Q3: Subtype distribution

| Option | Description | Selected |
|--------|-------------|----------|
| Match real corpus ratios | Derive from v1 re-extraction | ✓ |
| Balanced (20% each) | Worst-case stress | |
| Stress-weighted | 30% Disputed + 30% Conflicting | |
| Claude picks from §20 shapes | Delegate to planning | |

**User's choice:** Real ratios — measures what production sees.

### Q4: Gate 1 pass criterion

| Option | Description | Selected |
|--------|-------------|----------|
| ALL §20 must rewrite + execute (strict) | Binary 100% or pivot | ✓ |
| Quorum pass (≥80%) + documented gaps | Pragmatic, subjective | |
| Semantic-equivalence subset counts | Filter known SPARQL 1.1 gaps | |

**User's choice:** Strict — matches SEC-01/STORAGE-04 intent.

---

## Gate-failure decision rules

### Q1: Gate 2 (P95 SPARQL)

| Option | Description | Selected |
|--------|-------------|----------|
| Tune first, ≤800ms budget | 3-day tune; >800ms triggers pivot | ✓ |
| Binary: >500ms → pivot | Strict literal match | |
| Accept with SLO adjustment | Amend QUALITY-01 | |

### Q2: Gate 3 (image size)

| Option | Description | Selected |
|--------|-------------|----------|
| Tune first, ≤700MB budget | JLink + slim deps; overflow → split reasoner | ✓ |
| Binary: >500MB → split reasoner | Any breach triggers split | |
| Accept with size adjustment | Amend QUALITY-03 | |

### Q3: Gate 4 (SSR latency)

| Option | Description | Selected |
|--------|-------------|----------|
| Tune + warm cache, ≤400ms | Stream tuning; overflow → deferred-hydration | ✓ |
| Binary: >200ms → adapter-static | Revert to SPA mode | |
| Accept with SLO adjustment | Amend QUALITY-04 | |

### Q4: Gate 5 definition

| Option | Description | Selected |
|--------|-------------|----------|
| Bit-identical image digest | Strongest; requires deterministic Dockerfile | ✓ |
| Same tests + size ±5% | Weaker | |
| Behavioral equivalence only | Runtime smoke test | |

---

## Spike scope + timeboxing (user went max-fidelity)

### Q1: SSR prototype depth

| Option | Description | Selected |
|--------|-------------|----------|
| Single shard page + one SSE demo | Minimum spike, ~2-3 days | |
| Full nav tree (shard + polysemy + timeline) | 3 Phase 15 surfaces, ~5-7 days | ✓ |
| Dummy-data SSR only | No pyoxigraph, ~1 day | |

### Q2: Dagger CI scope

| Option | Description | Selected |
|--------|-------------|----------|
| Build + test + image-digest reproducibility | Minimum Gate 5 proof, ~3-4 days | |
| Full CI (build + test + lint + deploy + Railway) | Replaces GitHub Actions, ~7-10 days | ✓ |
| Bare reproducibility check only | ~1 day | |

### Q3: HermiT benchmark realism

| Option | Description | Selected |
|--------|-------------|----------|
| Real TBox + synthetic 1K-class ABox | Measures realistic cold-start | |
| Full benchmark corpus reasoning (1M ABox) | Maximum realism; 1-2 days per run | ✓ |
| JVM cold-start + tiny fixture | Quickest; validates size only | |

### Q4: Time budget

| Option | Description | Selected |
|--------|-------------|----------|
| 3 days/gate; overrun triggers pivot | ~15 days total, forces decisiveness | |
| 5 days/gate; overrun → research refresh | ~25 days total | |
| No fixed budget; run until resolve | Open-ended | ✓ |

---

## 1M-triple load generator design

### Q1: Generation strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Scaled real corpus | v1 + FRE + Restatement × N, bitemporal replay | ✓ |
| Synthetic scaled from seed pipeline | Real seed, synthetic variations | |
| Pure faker with realistic ratios | Template-based, deterministic | |

### Q2: API surface

| Option | Description | Selected |
|--------|-------------|----------|
| CLI + pytest fixture | Both entry points | ✓ |
| CLI only | Subprocess from tests | |
| Library function only | Python import only | |

### Q3: Determinism

| Option | Description | Selected |
|--------|-------------|----------|
| Seeded deterministic | `--seed N`, stable across runs | ✓ |
| Random (fresh each run) | Fuzz-style | |
| Both (default seeded, --random flag) | Flexible | |

### Q4: Phase reusability

| Option | Description | Selected |
|--------|-------------|----------|
| Single generator w/ phase-profile flags | One tool, profiles | ✓ |
| Base + per-phase extension modules | Subclasses | |
| Separate fixture files checked in | Static files in repo | |

---

## Claude's Discretion

- Exact adversarial query patterns (derived from PRD §21 risk matrix by researcher)
- JVM heap sizing (`-Xmx`) once HermiT @ 1M measurements land
- Dagger pipeline stage ordering (standard build→test→lint→deploy)
- Subtype-ratio derivation methodology (analyze latest v1 corpus vs sample)

## Deferred Ideas

- DID-signing the DECISION.md — Phase 6+ (chicken-and-egg with DID substrate)
- PHILOSOPHY.md content restructure — Phase 18
- Query-log gold set from live Railway — v2.1 (no scale-worthy traffic yet)
- Per-gate time budget — explicitly rejected by user (D-12)
- Phase 0 sub-phases per gate — NOT needed; single phase with gate-labeled plans
