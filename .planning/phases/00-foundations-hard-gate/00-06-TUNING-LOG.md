---
phase: 0
plan: 6
gate: 2
requirement: QUALITY-01
created: 2026-04-23
baseline_commit: 705f586dc7632a738cc551360a266d331c205a47
authoritative_artifact: bench-results.json
---

# Gate 2 Tuning Log — D-05 6-Pass Playbook

**Target:** P95 < 500ms (QUALITY-01 hard target)
**SLO Ceiling:** <= 800ms (accept-with-SLO per D-05)
**Pivot Trigger:** > 800ms (pivot=fuseki)

---

## Machine / Environment (T-00-27 mitigation)

| Field | Value |
|-------|-------|
| Node | `damienriehl-IdeaCentre-Mini-01IRH10R` |
| CPU | Intel(R) Core(TM) 7 240H @ 4.9906 GHz (16 logical cores) |
| OS | Linux 6.17.0-22-generic x86_64 |
| Python | CPython 3.12.12 |
| pyoxigraph | 0.5.7 |
| pytest-benchmark | 5.2.3 |
| Corpus | `fixtures/bench.nq` — 1,000,000 quads, SHA256 `ffb2c130...` (Plan 00-02) |
| Store mode | in-memory (`Store(path=None)`) — RocksDB tuning out-of-scope for Phase 0 |
| Benchmark cfg | pedantic, rounds=20, warmup_rounds=3, iterations=1 |

Hostname + CPU + RAM auto-detected and preserved inside `bench-results.json`
under `.machine_info` so Plan 00-08 can quote it verbatim in DECISION.md.

---

## Pass 0 — Baseline

Tuning state (tuning levers inherited from Plan 00-03 wrapper; per-query prune
table active via `GOLD_QUERY_NAMED_GRAPHS` resolved through `named_graphs="auto"`):

- bulk_load via `Store.bulk_load()`: YES (Plan 03)
- `Store.optimize()` after load: YES (Plan 03)
- `named_graphs=` prune: ACTIVE (`GOLD_QUERY_NAMED_GRAPHS` default)
- Warm cache: YES (pytest-benchmark `warmup_rounds=3`)
- SPARQL query-plan rewrites: YES as authored (Gate 1 rewrites; Q02 dropped
  UNION per 00-03 Rule-1 fix, Q11 subquery + outer FILTER per 00-03 Rule-1 fix)
- RocksDB tuning: N/A (in-memory store)

Because `GOLD_QUERY_NAMED_GRAPHS` is threaded by default via the harness
entrypoint (`named_graphs="auto"`), Pass 0 already reflects tuning steps 1-5
at once. A "true" no-tuning baseline that bypasses the prune table would
require callers to pass `named_graphs=None` explicitly; the harness does not
offer a CLI toggle because D-05 defines the authoritative measurement as
"whatever the production call-site uses," and Plan 08 consumes this call-site
directly.

### Measurement — authoritative bench-results.json

| Query                              | P50 (ms) | P95 (ms) | Max (ms) | Status |
|------------------------------------|---------:|---------:|---------:|:-------|
| q01_confidence_threshold           |     0.52 |     0.66 |     0.66 | PASS   |
| q02_advocacy_with_provenance       |     0.27 |     0.32 |     0.32 | PASS   |
| q03_polysemy_siblings              |     0.11 |     0.12 |     0.12 | PASS   |
| q04_supersession_chain             |     0.08 |     0.09 |     0.09 | PASS   |
| q05_framework_filter               |     3.92 |     4.86 |     4.86 | PASS   |
| q06_as_of_historical               |     0.11 |     0.86 |     0.86 | PASS   |
| q07_axiom_closure                  |    37.16 |    38.96 |    38.96 | PASS   |
| q08_seven_principles_conflict      |     0.18 |     0.22 |     0.22 | PASS   |
| q09_author_cluster_by_framework    |    18.15 |    19.02 |    19.02 | PASS   |
| q10_governance_attestation         |     0.30 |     0.38 |     0.38 | PASS   |
| q11_cross_corpus_traversal         |    23.66 |    25.76 |    25.76 | PASS   |
| q12_deprecated_with_successor     |     0.11 |     0.14 |     0.14 | PASS   |
| q13_confidence_histogram           |   103.27 |   116.95 |   116.95 | PASS   |

**Worst-case P95:** **116.95 ms** on `q13_confidence_histogram`
**Verdict:** **PASS** — every gold query is below the 500 ms hard target by
>4x (worst-case margin: 383 ms headroom). No further tuning required.

Totality of the parametrized warm-cache suite (13 queries x 20 rounds + 3
warmup + 1 module-scoped bulk_load): 7.64 s wall-clock.

---

## Pass 1 — `named_graphs=` prune (tuning step 3)

**Status:** NOT NEEDED. Pass 0 already meets the hard target by >4x; the prune
table is already active in the Pass 0 measurement via `named_graphs="auto"`
default resolution through `GOLD_QUERY_NAMED_GRAPHS`.

Skipped — no measurement required. If a future corpus-scale increase
(Phase 13 at 100M triples) degrades Pass 0 below target, re-enter the
playbook here and diff against the Pass 0 numbers in this document.

---

## Pass 2 — SPARQL query-plan rewrites (tuning step 5)

**Status:** NOT NEEDED. Every query under the 500 ms hard target on Pass 0.

Historical note: two query-plan rewrites were already applied at Plan 00-03
against a pre-benchmark iteration of the gold query set (not done in Plan
00-06; out-of-band deviations logged in 00-03-SUMMARY.md):

1. Q02: dropped UNION branch of the `{| fi:confidence |}` pipe/reified
   alternatives — kept pipe form in `#` comments only. Enabled consistent
   sub-second runtime for Q02 (observed 0.32 ms P95 here).
2. Q11: rewrote `HAVING (?ngraphs >= 2)` into `SELECT ?concept ?ngraphs WHERE
   { { SELECT ... } FILTER (?ngraphs >= 2) }` because pyoxigraph 0.5.x HAVING
   drops all rows when the bound variable is `xsd:integer`-typed. Query now
   returns 50 rows at 25.76 ms P95.

No further rewrites applied in Plan 00-06 — baseline passes.

---

## Pass 3 — RocksDB tuning (tuning step 6)

**Status:** N/A for Phase 0 — in-memory store only.

Pyoxigraph 0.5.x Python API exposes minimal RocksDB config via `Store(path=)`
alone; block_cache_size / bloom_filter exposure requires upstream work.
Phase 13 persistence migration will re-open the RocksDB tuning lever for the
then-target corpus size; Plan 00-06 does not exercise it.

**Ceiling documented for Plan 08:** "Gate 2 final tuning is bounded by
pyoxigraph 0.5.x's RocksDB API surface. Further gains (if needed at larger
scale) require Phase 13 persistent-store migration and/or upstream feature
requests for `block_cache_size` and `bloom_filter` exposure."

---

## Cold-cache datapoint (informational, not D-05 authoritative)

A separate `test_gate2_p95_cold` parametrized over the first 3 gold queries
is committed alongside this plan. It measures the full `bulk_load_nquads +
optimize + query_rdf12` round (i.e. cost of the Phase 13 per-request restart
pattern). Not executed in Plan 00-06 because:

- Pass 0 warm-cache numbers are >4x below budget — no ambiguity to resolve
- Cold runs cost ~30 s per round x 5 rounds x 3 queries = ~7.5 min wall-clock
- Phase 13 persistence decision will re-measure this on disk-backed Store

Test is collected + skippable via its own nodeid; invoke manually when the
Phase 13 persistence plan needs the delta:

```bash
uv run pytest tests/bench/test_gate2_p95_cold --benchmark-only --timeout=3600
```

---

## Final Measurement Table (-> 00-DECISION.md Gate 2 row)

| Query                              | Baseline P95 | Post-Tune P95 | vs 500ms | vs 800ms | Verdict |
|------------------------------------|-------------:|--------------:|:--------:|:--------:|:-------:|
| q01_confidence_threshold           |      0.66 ms |          same |  PASS    |  PASS    |  PASS   |
| q02_advocacy_with_provenance       |      0.32 ms |          same |  PASS    |  PASS    |  PASS   |
| q03_polysemy_siblings              |      0.12 ms |          same |  PASS    |  PASS    |  PASS   |
| q04_supersession_chain             |      0.09 ms |          same |  PASS    |  PASS    |  PASS   |
| q05_framework_filter               |      4.86 ms |          same |  PASS    |  PASS    |  PASS   |
| q06_as_of_historical               |      0.86 ms |          same |  PASS    |  PASS    |  PASS   |
| q07_axiom_closure                  |     38.96 ms |          same |  PASS    |  PASS    |  PASS   |
| q08_seven_principles_conflict      |      0.22 ms |          same |  PASS    |  PASS    |  PASS   |
| q09_author_cluster_by_framework    |     19.02 ms |          same |  PASS    |  PASS    |  PASS   |
| q10_governance_attestation         |      0.38 ms |          same |  PASS    |  PASS    |  PASS   |
| q11_cross_corpus_traversal         |     25.76 ms |          same |  PASS    |  PASS    |  PASS   |
| q12_deprecated_with_successor     |      0.14 ms |          same |  PASS    |  PASS    |  PASS   |
| q13_confidence_histogram           |    116.95 ms |          same |  PASS    |  PASS    |  PASS   |

**Worst-case post-tune P95:** **116.95 ms** on `q13_confidence_histogram`
**D-05 Verdict:** **PASS** (every query comfortably below the 500 ms hard
target; no pivot to Fuseki)

---

## Techniques Applied (DECISION.md provenance)

- [x] Pass 0 — `Store.bulk_load` + `Store.optimize` (inherited from Plan 03 wrapper)
- [x] Pass 1 — `named_graphs=` prune via `GOLD_QUERY_NAMED_GRAPHS` (active by
      default through `named_graphs="auto"` resolution)
- [ ] Pass 2 — SPARQL query-plan rewrites (NOT NEEDED — baseline passes; two
      historical rewrites from Plan 00-03 already in the fixtures)
- [ ] Pass 3 — RocksDB tuning (N/A — in-memory store for Phase 0; deferred to
      Phase 13 if scale grows)

---

## Tuning-to-Test Guard (T-00-24)

This baseline was measured on `705f586dc7632a738cc551360a266d331c205a47` —
immediately after the GREEN commit that ships `gate2_harness.py`. No gold
query was modified in this plan; the only edits to queries occurred in Plan
00-03 (Q02 UNION drop + Q11 HAVING rewrite, both documented there as Rule-1
correctness fixes, not performance tuning). The pre-tuning baseline already
passes, so "tune to pass" is a non-issue here by construction.

Any future re-measurement must cite a commit hash and be run on this same
machine (or record a new machine profile block) — Plan 00-08 reconciles.
