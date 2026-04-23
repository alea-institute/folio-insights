# Phase 0 Branch Guidance for Downstream Planners

**Source of truth:** `.planning/phases/00-foundations-hard-gate/00-DECISION.md` §Downstream Phase Branch Guidance.

This file duplicates that table at a stable, predictable path so downstream PLAN.md files can `@`-reference it without re-parsing DECISION.md.

## Verdict

**keep=pyoxigraph** (sourced from DECISION.md; if DECISION.md updates, update this file)

Driver: All ship-critical gates pass (Gate 1 13/13 gold + 5/5 adversarial; Gate 2 worst-case P95 116.95 ms; Gate 3 74.6 MB; Gate 5 Mode 1 bit-identical digest). Gate 4 and D-11 deferred with runnable harnesses; neither is a pivot trigger.

## Branch table

| Phase | Keep branch (pyoxigraph) | Pivot branch (fuseki) | Note |
|-------|--------------------------|-----------------------|------|
| 6 (DID + Auth) | Storage-agnostic; no changes on verdict. Executes DECISION.md signature backfill once DID substrate ships. | Storage-agnostic; no changes on verdict. Same signature backfill obligation. | DID middleware is HTTP-layer; indifferent to store. KEEP branch ACTIVE. |
| 10 (Arq Worker + Redis) | Worker embeds pyoxigraph in-process (read-only snapshot on shared volume); inherits HermitHarness + Xmx recommendation from Plan 00-07. | Worker issues HTTP SPARQL to Fuseki sidecar; Redis still for job queue. | On keep: resolve snapshot-staleness vs lock-contention. On pivot: add Fuseki-HTTP retry + circuit breaker. KEEP branch ACTIVE. |
| 11 (SHACL @ scale) | pyshacl over pyoxigraph.Store direct Graph API (rdflib bridge per 00-03-SUMMARY.md; inherits Pitfall 2 drop guard). Annotation-dependent shapes route through `query_rdf12` SPARQL ASK, not the bridge. | pyshacl over Fuseki HTTP SPARQL endpoint, OR switch to native Jena SHACL (Java-side, worker-tier). | Keep branch reuses bridge guard; pivot inherits Jena SHACL profile. KEEP branch ACTIVE. |
| 13 (Storage + RocksDB) | pyoxigraph path-backed `Store(path=...)` with RocksDB tuning (Pass 3 of Gate 2 TUNING-LOG). First real cold-page P95 measurement on disk. Rewrites gold queries to RDF-12-native pipe form when pyoxigraph emits RDF-12 N-Quads. | Drop RocksDB; Fuseki TDB2 native tuning (`tdb2:location` + `arq:queryTimeout`). | On pivot, Plan 13 scope shrinks significantly. KEEP branch ACTIVE. |
| 16 (Public SPARQL) | FastAPI wrapper over pyoxigraph.Store with SPARQL-injection hardening: parser-based per-endpoint SERVICE allowlist (replaces Plan 00-03 regex preflight), query timeout enforcement, prefix allow-list, per-user rate limiting. | Fuseki proxy with Fuseki-side ACLs + rate limits; FastAPI becomes auth shim only. | SEC-01 adjacency: keep branch must hand-roll what pivot branch inherits. `fuseki/config.ttl` config-as-code diff review is a Phase 16 mitigation requirement per T-00-40 regardless of verdict (scaffold stays committed). KEEP branch ACTIVE. |

## Escape hatches (NOT pivot — apply to keep verdict only)

| Trigger | Affects | Adjustment | Current status |
|---------|---------|------------|----------------|
| Gate 3 final size > 700 MB post-tune (D-06) | Phase 10 | Split HermiT reasoner into separate microservice | NOT TRIGGERED (74.6 MB << 500 MB) |
| Gate 4 worst surface P95 > 400 ms post-tune (D-07) | Phase 15 | Per-surface deferred-hydration fallback (SPA shell + client fetch) | PENDING verify-session measurement |
| D-11 HermiT 1M > 2 h OR OOM at 4 GB Xmx | Phase 9.P7 | Stream TBox inferences incrementally; not whole-World reasoning | PENDING verify-session full-1M run |
| Gate 5 Mode 2 (Railway) digest mismatch when RAILWAY_TOKEN available | Phase 10+ / Phase 20 | Investigate Railway build-context non-determinism | SKIPPED (no RAILWAY_TOKEN at Phase 0) |

## How to use this file

Downstream PLAN.md files add one line to `<context>`:

```
@.planning/phases/00-foundations-hard-gate/00-BRANCH-GUIDANCE.md
```

Then branch frontmatter/tasks on `Verdict`.

For the current keep=pyoxigraph verdict, every one of Phases 6/10/11/13/16 takes the LEFT column of the branch table. The right column stays committed as documentation for a hypothetical v2.1 re-evaluation (see `fuseki/README.md`).
