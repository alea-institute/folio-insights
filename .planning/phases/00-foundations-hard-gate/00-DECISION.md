# Phase 0 DECISION — Foundations HARD GATE

**Phase:** 00-foundations-hard-gate
**Authored:** 2026-04-23
**Status:** BINDING (per D-17) — all downstream phases MUST branch on the Verdict below
**Signature:** *Deferred to Phase 6+ (D-17 chicken-and-egg: DID substrate doesn't exist yet). Backfill procedure in §Signature Deferral.*

---

## Verdict

**keep=pyoxigraph**

*Driver:* All ship-critical gates pass — Gate 1 (13/13 RDF-12 gold + 5/5 adversarial), Gate 2 (worst-case P95 = 116.95 ms vs 500 ms hard target), Gate 3 (74.6 MB vs 500 MB hard target), Gate 5 Mode 1 (bit-identical digest across back-to-back local Dagger runs). Gate 4 (SSR cold-page P95) and D-11 (full-1M HermiT reasoning) are DEFERRED to the verify session per D-12 open-ended timebox with runnable harnesses in place; neither is a pivot-trigger gate by the D-17 decision schema.

The locked v2.0 stack validates against reality. pyoxigraph 0.5.7 + rdflib 7.6 bridge + owlready2/HermiT + SvelteKit 5 adapter-node + Dagger CI is the substrate for Phases 1-20.

---

## Per-Gate Measurement Table

| Gate | REQ | Target | Measured | Verdict |
|------|-----|--------|----------|---------|
| 1. RDF-12 annotation pattern | STORAGE-04 | 100% of 13 gold queries return expected rows (D-04 STRICT) | 13/13 gold queries non-empty on 1M corpus; 5/5 adversarial safe (SERVICE preflight blocks, deep traversal + large CONSTRUCT + supersession-as-of return expected cardinalities); 32/32 Gate 1 tests PASS. Source: 00-03-SUMMARY.md §Accomplishments + tests/bench/test_gate1_rdf12.py | PASS |
| 2. P95 SPARQL latency @ 1M triples (warm) | QUALITY-01 | <500 ms hard / 500-800 ms accept-with-SLO / >800 ms pivot (D-05) | Worst-case P95 = 116.95 ms on q13_confidence_histogram (13/13 queries < 500 ms; median 0.27 ms). Source: 00-06-TUNING-LOG.md §Final Measurement Table + bench-results.json (machine info: Intel Core 7 240H @ 4.99 GHz, Python 3.12.12, pyoxigraph 0.5.7) | PASS |
| 3. Worker Docker image size | QUALITY-03 | <500 MB hard / 500-700 MB accept / >700 MB split-reasoner (D-06) | fi-worker:smoke = 74.6 MB (15% of hard target; 425 MB headroom over 500 MB; 625 MB headroom over 700 MB ceiling). Source: 00-07-MEASUREMENTS.md §Gate 3 + `docker image inspect --format '{{.Size}}'` | PASS |
| 4. SSR cold page latency (P95, 3 surfaces × 3 IDs) | QUALITY-04 | <200 ms hard / 200-400 ms accept / >400 ms deferred-hydration-per-surface (D-07) | DEFERRED to verify session — harness (`tests/bench/test_gate4_ssr.py`, 9 parametrized cases over 3 surfaces × 3 IDs) ships and skips cleanly when hyperfine is absent. Tuning steps 1-3+5-7 already active (critical-path minimisation, cache-control via hooks.server.ts + setHeaders, prod-mode adapter-node, Node-22-slim base, no heavy `+page.server.ts` deps, relative-URL proxy). Source: 00-07-MEASUREMENTS.md §Gate 4 + viewer/src/hooks.server.ts. Per D-07 the escape-hatch is per-surface deferred hydration, NOT pivot. | DEFERRED (harness-ready; NOT a pivot trigger) |
| 5. Dagger reproducibility (bit-identical digest) | OBS-04 | Mode 1 local = PASS required; Mode 2 Railway = PASS when RAILWAY_TOKEN available (D-08) | Mode 1: PASS — two back-to-back `python -m ci.build` runs produce identical sha256 digests for BOTH images (web: `sha256:b36de1fe0c2e4c70c0132693c3366254ec8f1236dab01e4eb4f3f5688dad6edd`; worker: `sha256:b2abdffcc7a27e022ce2dabdddb0a7a91196c1d780f0895e1058d88f213b309f`). Mode 2: SKIPPED (no RAILWAY_TOKEN at Phase 0 execution host; test parametrized and ready). Source: 00-05-SUMMARY.md §Gate 5 Verdict + tests/bench/test_gate5_digest.py | PASS (Mode 1); Mode 2 deferred (no pivot trigger — D-08 Mode 1 is the determinism requirement; Mode 2 is a confirmation) |

### Cross-cut measurements (not gates, recorded for posterity)

- **D-11 HermiT full 1M reasoning:** DEFERRED to verify session. Smoke timings: tiny-case cold ~0.186 s, warm ~0.161 s, disjoint-violation ~0.18 s (consistent=False, sentinel class `<ontology-inconsistent>`). Xmx tuning knob wired via `owlready2.JAVA_MEMORY` at HermitHarness init. Full-1M run requires a `.owl`-format ABox fixture + 1-2 day wall-clock window per D-11 expected cost (generator currently emits N-Quads; `--format owl` option exists per 00-02-SUMMARY). Source: 00-07-MEASUREMENTS.md §D-11.
- **Gate 2 cold P95 (informational):** Not executed in Plan 00-06 — Pass 0 warm numbers land >4x below budget. `test_gate2_p95_cold` is parametrized over the first 3 queries (T-00-25 DoS mitigation) and is opt-in; Phase 13 persistence migration will re-run against a disk-backed `Store(path=)`. Source: 00-06-TUNING-LOG.md §Cold-cache datapoint.

---

## Tuning Passes Performed

*Chronological. Each row = one pass.*

### Gate 2 (SPARQL P95)

| Pass | Change | Before (P95 ms) | After (P95 ms) | Source |
|------|--------|-----------------|----------------|--------|
| 0 | Baseline (bulk_load + optimize + named_graphs="auto" prune active + warmup_rounds=3 + SPARQL rewrites inherited from Plan 00-03) | — | 116.95 (worst-case on q13) | 00-06-TUNING-LOG.md §Pass 0 |
| 1 | Named-graph pruning via `GOLD_QUERY_NAMED_GRAPHS` (per-query IRIs in corpus/{advocacy,fre,restatement}) | N/A — active by default in Pass 0 via `named_graphs="auto"` resolution (not measured independently; Pass 0 passes by >4x, no separate pass justified) | same (116.95) | 00-06-TUNING-LOG.md §Pass 1 |
| 2 | SPARQL rewrites (FILTER-push, LIMIT-push, predicate-reorder) | NOT NEEDED — baseline passes; two historical rewrites from Plan 00-03 already in fixtures (Q02 UNION drop, Q11 HAVING→subquery+FILTER) | same (116.95) | 00-06-TUNING-LOG.md §Pass 2 |
| 3 | RocksDB tuning (block_cache_size, bloom_filter) | N/A — in-memory store for Phase 0; pyoxigraph 0.5.x Python API exposes minimal RocksDB config via `Store(path=)` alone. Deferred to Phase 13 persistence migration. | N/A | 00-06-TUNING-LOG.md §Pass 3 |

### Gate 3 (Worker image size)

| Pass | Change | Before (MB) | After (MB) | Source |
|------|--------|-------------|------------|--------|
| 0 | Baseline — jlink custom JRE + Alpine base + 3-stage Dockerfile.worker + cache purges + scoped reasoning subset (pyoxigraph/owlready2/rdflib/oxrdflib only; no torch/sentence-transformers) | — | 74.6 | 00-07-MEASUREMENTS.md §Gate 3 Baseline |
| 1 | jlink custom JRE (`--add-modules java.base,java.logging,java.xml,java.naming,java.sql,jdk.crypto.ec --strip-debug --no-man-pages --no-header-files --compress=2`) | Pre-jlink Temurin-17-jdk-alpine: ~400 MB (RESEARCH.md estimate) | 60-80 MB JRE contribution → 74.6 MB total image | 00-07-MEASUREMENTS.md §Gate 3 Tuning 1 + Dockerfile.worker stage 1 |
| 2 | A1 musllinux spike (Alpine vs slim fallback) | slim fallback NOT built (A1 confirmed Alpine viable — pyoxigraph 0.5.7 ships musllinux_1_2_x86_64 wheel) | 74.6 (Alpine base retained; saves ~75 MB over slim) | 00-07-MEASUREMENTS.md §Gate 3 Tuning 2 + 00-04-D1 |

### Gate 4 (SSR P95)

| Pass | Change | Before (ms, worst surface) | After (ms, worst surface) | Source |
|------|--------|----------------------------|----------------------------|--------|
| 0 | Baseline — adapter-node prod-mode, streaming `{#await}` (one awaited `/core` fetch + two unawaited promises), relative-URL proxy, no heavy `+page.server.ts` deps | DEFERRED — hyperfine not on Plan 07 execution host | DEFERRED to verify session | 00-07-MEASUREMENTS.md §Gate 4 Baseline |
| 1 | `setHeaders` cache-control (`public, max-age=60, s-maxage=60`) + streaming unawaited fetches via hooks.server.ts regex matcher on `/{shards,polysemy,timeline}/*` | DEFERRED | DEFERRED | 00-07-MEASUREMENTS.md §Gate 4 Tuning 2 + viewer/src/hooks.server.ts |
| 2 | @polka/compression custom server (only if Pass 1 >400 ms) | NOT ACTIVATED — dependency installed in viewer/package.json; activation requires custom adapter-node server.js wrapper; defer until Pass 1 measurement shows need | N/A | 00-07-D4 |

---

## Downstream Phase Branch Guidance

*Every downstream phase listed here MUST read this table before writing its PLAN.*

| Phase | Keep branch (pyoxigraph) | Pivot branch (fuseki) | Note |
|-------|--------------------------|-----------------------|------|
| 6 (DID + Auth) | Storage-agnostic; no changes on verdict. DID middleware is HTTP-layer; indifferent to store. Also executes the DECISION.md signature-backfill procedure once the DID substrate ships (see §Signature Deferral). | Storage-agnostic; no changes on verdict. Same signature-backfill obligation; also: worker-tier reasoning reads from Fuseki HTTP endpoint instead of direct Store (but that's a Phase 10 concern, not Phase 6). | Keep branch ACTIVE for this project per Verdict above. |
| 10 (Arq Worker + Redis) | Worker tier embeds pyoxigraph in-process (read-only snapshot on a shared volume). Must resolve snapshot-staleness vs lock-contention tradeoff. Inherits HermitHarness from Plan 00-07 + Xmx recommendation (pending D-11 full-1M verify). | Worker issues HTTP SPARQL to Fuseki sidecar (see `fuseki/` scaffold). Redis still for job queue. Must add Fuseki-HTTP retry policy + circuit breaker. | Keep branch ACTIVE. |
| 11 (SHACL @ scale) | pyshacl over `pyoxigraph.Store` via the one-way rdflib bridge (Plan 00-03 `validate_shard_via_rdflib_bridge`). Inherits Pitfall 2 bridge-drop guard + SERVICE preflight from PyoxigraphStore wrapper. Annotation-dependent shapes MUST route through `query_rdf12` with SPARQL ASK instead of the bridge. | pyshacl over Fuseki HTTP SPARQL endpoint OR switch to native Jena SHACL (Java-side, worker-tier). Pivot inherits the Jena SHACL profile + Fuseki-side per-endpoint ACL. | Keep branch ACTIVE. Pitfall 2 drop-guard is load-bearing here. |
| 13 (Storage + RocksDB) | pyoxigraph path-backed `Store(path=...)` with RocksDB tuning (Pass 3 of Gate 2 TUNING-LOG — currently N/A in Phase 0 in-memory store). First measurement of cold P95 on disk (`test_gate2_p95_cold` runs against the disk-backed store). Also rewrites gold queries from `#`-comment annotation-pipe to RDF-12-native pipe form when pyoxigraph emits RDF-12-native N-Quads. | Drop entire RocksDB branch; use Fuseki TDB2 native tuning (`tdb2:location` + `arq:queryTimeout` via `fuseki/config.ttl`). Scope shrinks significantly — Fuseki TDB2 is preconfigured for most workloads. | Keep branch ACTIVE. Plan 13 is where Gate 2 Pass 3 finally becomes a real tuning lever. |
| 16 (Public SPARQL endpoint) | FastAPI wrapper over `pyoxigraph.Store` with SPARQL-injection hardening: parser-based per-endpoint SERVICE allowlist (replaces the Plan 00-03 regex preflight), query-timeout enforcement at handler layer, prefix allow-list, per-user rate limiting. SEC-01 final disposition. | Direct Fuseki proxy with Fuseki-side ACLs + rate limiting; FastAPI becomes auth shim only. Pivot inherits Jena's SPARQL sandbox — less custom code to write + maintain. | Keep branch ACTIVE. SEC-01 adjacency: keep branch must hand-roll what the pivot branch inherits. Config-as-code review of `fuseki/config.ttl` is a Phase 16 mitigation requirement per T-00-40 regardless of verdict (scaffold stays committed per §Verdict keep case). |

### Escape-hatch triggers (NOT pivot; DO adjust downstream plans)

| Trigger | Affects | Adjustment |
|---------|---------|------------|
| Gate 3 final size > 700 MB post-tune (D-06) | Phase 10 | Split HermiT reasoner into a separate microservice (not a container layer in the main worker); Plan 10 must budget for this. **Current status: NOT TRIGGERED** (74.6 MB << 500 MB hard target). |
| Gate 4 worst surface P95 > 400 ms post-tune (D-07) | Phase 15 | Per-surface deferred-hydration fallback (SPA shell + client fetch); NOT a full `adapter-node → adapter-static` swap. **Current status: PENDING** verify-session hyperfine measurement. |
| D-11 HermiT 1M reasoning > 2 h OR OOM at 4 GB Xmx | Phase 9.P7 | Stream TBox inferences incrementally (not whole-World reasoning); Plan 9.P7 must scope this. **Current status: PENDING** verify-session full-1M run. |
| Gate 5 Mode 2 (Railway) digest mismatch when RAILWAY_TOKEN available | Phase 10+ GHA / Phase 20 deploy | Investigate Dockerfile non-determinism introduced by Railway build context (e.g., Railway-injected env vars, build-time secrets). **Current status: SKIPPED** (no RAILWAY_TOKEN at Phase 0); first Railway deploy in a later plan lights up Mode 2 assertion. Not a pivot trigger; Mode 1 satisfies D-08. |

---

## Open Question Resolutions

- **OQ 1 (philosophy file path):** Resolved in 00-01-SUMMARY.md — file was at repo root (not `docs/`); `git mv` to `PHILOSOPHY.md` preserved blame.
- **OQ 2 (1M P95 baseline):** Measured — see §Per-Gate Measurement Table row 2 (116.95 ms worst-case, 0.27 ms median across 13 gold queries).
- **OQ 3 (Railway Node 22 cold-page baseline):** Harness in place but measurement deferred to verify session — see §Per-Gate Measurement Table row 4.
- **OQ 4 (Fuseki pivot trigger numeric threshold):** **Resolved here.** The D-05 hard ceiling of 800 ms stands; Gates 3/4 do NOT trigger pivot (they trigger escape-hatches per D-06/D-07). Therefore pivot requires ONE of: (a) Gate 1 failure (D-04 STRICT), (b) Gate 2 warm P95 > 800 ms post-tune, (c) Gate 5 Mode 1 local-determinism failure. This is the canonical numeric policy. Gate 4 cold-page > 400 ms triggers per-surface deferred-hydration (not full adapter swap, not pivot). Gate 3 > 700 MB triggers reasoner-microservice split (not pivot). D-11 > 2 h OR OOM triggers incremental TBox streaming in Phase 9.P7 (not pivot).
- **OQ 5 (adversarial SPARQL set composition):** Resolved in 00-03-SUMMARY.md — 5 queries per PRD §16/§21 (deep_graph_traversal, large_construct, service_blocked `evil.example`, service_ssrf `169.254.169.254`, supersession_as_of).

---

## Signature Deferral (per D-17)

The DID substrate this artifact would be signed against is delivered in Phase 6. Until Phase 6 ships, this DECISION.md is authenticated only by:
- Git commit sha of the commit that introduces this file
- Git signature (if the author has a configured GPG key)

**Backfill procedure (to be executed in Phase 6+):**
1. Phase 6 ships the `did:folio:...` DID method and signing tooling.
2. Phase 6 planner adds a post-ship task: "Sign Phase 0 DECISION.md with the project's minted DID."
3. The signature (detached JWS or W3C VC proof) is appended below this section and committed as an addendum; the DECISION.md body is NOT re-written.
4. If any gate measurement is later invalidated (e.g., corpus grows past 10M triples, or RDF-12 spec changes), a new DECISION.md is authored (never edited in-place); this one is marked SUPERSEDED-BY. T-00-39 mitigation: Phase 6 DID-signing task MUST verify the DECISION.md body matches the git-sha'd commit before signing to prevent substitute-then-sign attack.

```
# Signature slot (empty until Phase 6 backfill)
# DID: <did:folio:...>
# Proof: <JWS or VC proof appended here>
# Signed-at: <ISO-8601 UTC>
```

---

## Provenance

| Source | File | Section |
|--------|------|---------|
| Gate 1 | 00-03-SUMMARY.md | All (13/13 gold + 5/5 adversarial + 32/32 test suite) |
| Gate 2 | 00-06-SUMMARY.md + 00-06-TUNING-LOG.md | All passes + Final Measurement Table |
| Gate 2 machine-info | bench-results.json | `.machine_info` block (T-00-27 dispute mitigation) |
| Gate 3 | 00-07-SUMMARY.md + 00-07-MEASUREMENTS.md §Gate 3 | Image-size table (74.6 MB final) |
| Gate 4 | 00-07-SUMMARY.md + 00-07-MEASUREMENTS.md §Gate 4 | Per-surface P95 (DEFERRED; harness in place) |
| Gate 5 | 00-05-SUMMARY.md | Mode 1 digest match table + Mode 2 SKIPPED rationale |
| D-11 | 00-07-MEASUREMENTS.md §D-11 | HermiT smoke timings + full-1M deferral rationale |
| Decision rules | 00-CONTEXT.md §Decisions D-04 through D-08, D-17 | Verbatim |
| Fuseki pivot scaffold | 00-RESEARCH.md §Fuseki Pivot Scaffold (lines 609-633) | config.ttl skeleton + docker run invocation |

---

*DECISION.md authored 2026-04-23 per D-17; signature deferred to Phase 6+; see §Signature Deferral for backfill procedure.*
