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
- 2026-10-09 axioms lane: plan `docs/plans/2026-10-09-0650-feat-shards-axioms-drain-plan.md` (branch `feat/drain-shards-axioms`). No change to `mint_shard_iri`, the envelope's public fields, `VOCAB_VERSION` or the projection predicates above. Changes the bridge lane will meet:
  - **Cycle guard (U4):** `ingest_shards` and `shards.put` refuse a write whose `depends_on_*` or `elaborates` edges close a cycle (`DependencyCycle`), behind `StorageConfig.refuse_dependency_cycles` (default on). Bridge-ingested `dependsOnShard` edges are checked too.
  - **API auth (U5):** every state-changing route needs `Depends(require_operator)` from `api/auth.py`. A test enumerates the route table, so a new mutating route in `api/routes/bridge.py` without it fails that test; add the dependency when both land.
  - **CLI:** the axioms lane adds `mint`, `rubric`, `kernel`, `graph`, `validate` (clusters) and `query` groups, each as one `cli.add_command` line at the end of `cli.py`.
  - **`axiom_status`:** not defined here; kernel shards use `epistemic_status="authority_only"` (Chief, `folio-insights-2026-10-09-1148-kernel-epistemic-status`) and will consume the bridge lane's lifecycle when it lands.
- 2026-10-09 bridge lane (I1): bridge read API (`api/routes/bridge.py`, `bridge_ingest/status.py`) relies on projected `fi:shardType`, `fi:epistemicStatus`, `fi:contested`, `fi:supersedes`, `fi:supersededBy`, `fi:dependsOn{Axiom,Definition,Precedent,Shard}`, and governance `fi:action`/`fi:shardIri`; `elaborates`, `glosses`, `sic`/`non` and `objections` are read from shard records because they are not projected. Enrich provenance lives in `<corpus root>/bridge-ingest/manifest.jsonl`.
- 2026-10-09 bridge lane → storage owners: concurrent first opens of a brand-new corpus journal fail with `sqlite3.OperationalError: database is locked` because `PRAGMA journal_mode = WAL` in `storage/journal.py:Journal.open` does not wait on the busy timeout. bridge-ingest works around it by retrying the storage open (5 attempts, short backoff); the proper fix is a retry around that pragma inside `storage/journal.py`.
