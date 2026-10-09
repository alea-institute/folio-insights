# 2026-10-09 drain — cross-lane coordination

Two lanes touch folio-insights on 2026-10-09. Append notes below; never rewrite another lane's entry.

## Lanes and file ownership

- **Axioms lane** (shards, minting, governance build-out). Owns `src/folio_insights/shards/**`, `src/folio_insights/governance/**`, SHACL shapes, the envelope, and `minting.py`.
- **Bridge lane** (folio-enrich ↔ folio-insights bridge, "Bridge, not merge"). Owns only:
  - `src/folio_insights/bridge_ingest/**` (new)
  - `api/routes/bridge.py` (new) plus one `include_router` line in `api/main.py`
  - one `bridge-ingest` command registration in `src/folio_insights/cli.py`
  - `src/folio_insights/services/bridge/**` (sys.path bridge retirement)
  - `tests/bridge_ingest/**`, `tests/services/bridge_retire/**`
  - the `folio-propositions` pin in `pyproject.toml` and the lock files (bump v0.3.0 → v0.4.0)

## Contracts the bridge lane relies on

- `mint_shard_iri(source_uri, source_span)` and its recipe are frozen. folio-propositions v0.4.0 reproduces the recipe as `content_iri()`; the bridge lane adds a parity test, it does not edit `minting.py`. If the axioms lane must change the recipe, note it here first: enrich-minted IRIs depend on it.
- Bridge ingest builds `HypothesisShard` (`epistemic_status="hypothesis"`) through public constructors and writes through `open_corpus_storage(...).ingest_shards(...)`, so the PII and SHACL gates apply unchanged.
- The status read API reads the projection (`fi:shardType`, `fi:epistemicStatus`, `fi:contested`, `fi:supersedes`, `fi:supersededBy`, `fi:dependsOnShard`). Renaming those predicates breaks enrich's corpus panel; note it here.

## Log

- 2026-10-09 bridge lane: created this file. Plan: folio-enrich `docs/plans/2026-10-09-0645-feat-insights-bridge-plan.md`.
