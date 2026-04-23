# fuseki/ — Apache Jena Fuseki pivot scaffold

**Status (Phase 0 DECISION):** keep=pyoxigraph (scaffold not required; retained for v2.1 re-evaluation)

*See `.planning/phases/00-foundations-hard-gate/00-DECISION.md` §Verdict for context.*

## Purpose

This directory contains the Apache Jena Fuseki 5.x TDB2 scaffold specified as the Phase 0 pre-committed pivot target. If Phase 0 Gate 1 failed (RDF-12 annotation pattern did not work on pyoxigraph 0.5.7), this scaffold becomes the production RDF substrate.

## Local Fuseki run (for developers exploring the pivot branch)

```bash
mkdir -p fuseki/databases
docker run --rm -p 3030:3030 \
  -v "$(pwd)/fuseki/config.ttl:/fuseki/config.ttl:ro" \
  -v "$(pwd)/fuseki/databases:/fuseki/databases" \
  -e FUSEKI_BASE=/fuseki \
  stain/jena-fuseki:5.1.0 \
  /jena-fuseki/fuseki-server --config=/fuseki/config.ttl
```

Fuseki UI + SPARQL endpoint: `http://localhost:3030/fi/sparql`.

## Config

`config.ttl` defines one service (`/fi`) backed by one TDB2 dataset at `/fuseki/databases/fi`. Query timeout is 30s (matches Phase 0 gate-2 test harness).

## What must change downstream on pivot

See `.planning/phases/00-foundations-hard-gate/00-BRANCH-GUIDANCE.md` for the full table. TL;DR:
- Phase 10 worker issues HTTP SPARQL to Fuseki sidecar (not in-process pyoxigraph)
- Phase 11 SHACL uses Jena native SHACL OR pyshacl over HTTP
- Phase 13 drops RocksDB entirely; tunes Fuseki TDB2 instead
- Phase 16 public endpoint is a thin auth proxy to Fuseki

## v2.1 re-evaluation (keep verdict only)

Phase 0 verdict is `keep=pyoxigraph`, so this scaffold is NOT removed. It is retained so that a v2.1 re-evaluation (e.g., triple count growing past 10M, or RDF-12 spec changes) can re-test Fuseki without re-researching the scaffold.

Per T-00-40 (STRIDE threat register), Phase 16 planner MUST include a config-as-code diff review against this file as a Phase 16 gate — `config.ttl` is committed, so any future edit that weakens security posture (e.g., removes `arq:queryTimeout` or widens `fuseki:serviceQuery`) is reviewable.
