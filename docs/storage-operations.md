# Storage operations (Phase 13)

How to back up, restore, dump and export a folio-insights storage root. The
design lives in the [Phase 13 storage plan](plans/2026-09-30-0913-feat-phase13-storage-plan.md);
this page is the operator's view.

## What a storage root holds

A storage root is one directory, chosen by `--corpus-root`, else
`$FOLIO_INSIGHTS_CORPUS_ROOT`, else `~/.folio-insights/corpora`.

| Path | Role |
|---|---|
| `journal.sqlite3` (+ `-wal`, `-shm`) | The authoritative journal: every shard revision and governance event of every corpus, append-only, with an `op_id` per operation. The same file holds the append-only `proposal_ledger` table (proposed-class governance; see below). |
| `projection.oxigraph/` | The RDF projection (pyoxigraph/RocksDB). It is derived state: one ABox graph and one governance graph per corpus, a shared TBox graph, and a per-corpus watermark. |
| `projection.lock` | The cross-process lock that guards the projection. |

The journal is the only thing that must survive. The projection can always
be rebuilt from it. On every open, the projection checks its watermark: the
journal position, the payload sha256 of the row at that position, and a
chain digest over every applied row's (position, op_id, payload sha256,
commit time). A journal that is shorter, or that differs in ANY applied row,
makes the projection rebuild itself rather than serve stale RDF. The chain
is checked incrementally, so it costs a full journal scan only on a
context's first read.

Named graphs:

- ABox: `https://folio-insights.aleainstitute.ai/corpus/<percent-encoded corpus>`.
- Governance: the ABox IRI followed by `/governance`.
- TBox (shared): `https://folio-insights.aleainstitute.ai/tbox`. It is loaded
  from the vocabulary TTL files in `folio_insights.vocab` and reloaded when
  they change.

`ctx.query(sparql, include_tbox=True)` sees all three graphs of one corpus.
It never sees another corpus.

## Commands

All commands are `folio-insights storage …`. They work on the local
filesystem and do not sign anything. Per-corpus access policy for exports
arrives with Phase 13.5 (private corpora).

| Command | What it does |
|---|---|
| `status CORPUS` | (Refuses a corpus with no committed rows; never creates one.) Journal head, projection watermark, installed validation hooks, `full_shacl` (always `deferred-to-phase-11`). |
| `export CORPUS --out DIR [--format F]… [--construct-query Q \| --construct-file F] [--allow-partial] [--require-named-graphs]` | The export formats (below). Writes to a new or empty directory. |
| `dump --repo DIR [--corpus C]… [--init]` | Writes a TTL dump of every corpus and records a local Git commit. This is the nightly job's entry point. |
| `snapshot --out DIR [--no-projection]` | Snapshots the whole storage root (all corpora). |
| `restore SNAPSHOT --to NEWDIR [--use-snapshot-projection]` | Restores a snapshot into a new storage root (the projection is rebuilt from the journal unless asked otherwise). |

## Backup: snapshots

```bash
folio-insights storage snapshot --corpus-root /srv/fi/corpora --out /backups/fi-2026-10-03
```

- **Projection:** the projection lock is held for the whole snapshot. The
  projection is copied first, with RocksDB `Store.backup`, which hard-links
  when it can.
- **Journal:** copied second, with SQLite's online backup API (aiosqlite
  `Connection.backup`). It is a consistent point-in-time copy of every row,
  byte for byte, `op_id` included. The journal only grows, so the copy's
  heads are at or above the projection's watermarks.
- **Self-contained:** the journal copy passes `PRAGMA integrity_check` and
  is switched to a single file (no WAL side files).
- **Manifest:** `snapshot.json` records, per corpus, the journal head, the
  head row's payload sha256 and the row counts. It also records the
  projection watermarks, the schema and adapter versions, the TBox digest,
  the journal file's sha256 and the code version.
- **Atomic:** the snapshot is assembled in a hidden sibling directory and
  renamed into place. An interrupted snapshot leaves no partial snapshot at
  the destination.
- **Journal only:** `--no-projection` snapshots the journal alone. Restoring
  it rebuilds the projection.

Writers may keep committing during a snapshot. Their rows land after the
copy point and are simply not in the snapshot.

Measured at 1,000,017 triples (43,479 shards; hardware as in the plan's U4
evidence):

| Operation | Time |
|---|---|
| Snapshot with projection | 0.22 s |
| Snapshot, journal only | 0.19 s |

## Restore

```bash
folio-insights storage restore /backups/fi-2026-10-03 --to /srv/fi/corpora-restored
```

- **New destination only.** A destination that exists (even an empty one)
  is refused, and so is one that overlaps the snapshot. A restore never
  writes over live data.
- **Checked before it appears.** The restore is assembled in
  `.<dest>.restoring-<id>` next to the destination. These checks run first:
  - the journal sha256 against the manifest;
  - the SQLite integrity check and the schema version;
  - per-corpus heads and head-row digests against the manifest;
  - a full open and catch-up of every corpus.

  Only then is the directory renamed into place, with a no-replace rename
  (`renameat2(RENAME_NOREPLACE)`): a destination that appears meanwhile is
  never replaced.
- **The projection is rebuilt by default.** The snapshot's projection is
  used only with `--use-snapshot-projection` (`rebuild_projection=False`),
  and then only after every file's sha256 matches the manifest; symlinks,
  special files, missing or unlisted files are refused.
- **The manifest is not authenticated.** These checks prove the snapshot is
  consistent with its own `snapshot.json`; that file is not signed, so
  anyone who can rewrite the snapshot directory can rewrite it to match.
  Keep snapshots where only the operator can write. Rebuilding the
  projection (the default) at least never serves RDF the journal does not
  produce.
- **Never in the served directory.** Snapshot and restore destinations
  inside the served `output/` directory are refused.
- **Interruption-safe.** A failure or kill before the rename never creates
  the destination. It never touches the snapshot or any live root. A killed
  process can leave a `.<dest>.restoring-*` directory, which is safe to
  delete.
- **Matching code:** restore with the code version recorded in the
  manifest. An unsupported journal schema is refused, never migrated
  silently.

Then point the service at the new root (`--corpus-root` or
`$FOLIO_INSIGHTS_CORPUS_ROOT`). Rollback means restoring into a new
destination and switching to it; never overwrite the only copy.

At 1,000,017 triples, a restore that copies the projection took 0.26 s, and
a restore with a rebuild (now the default) took 2.38 s.

## Dumps: the nightly TTL job

```bash
folio-insights storage dump --corpus-root /srv/fi/corpora --repo /srv/fi/dumps [--init]
```

The job writes this layout into a dedicated Git repository:

```text
tbox.ttl
corpora/<percent-encoded corpus>/abox.ttl
corpora/<percent-encoded corpus>/governance.ttl
corpora/<percent-encoded corpus>/manifest.json   # graph IRI, statements, sha256 per file
```

- **Verified:** every file is parsed back and compared with its graph
  before the commit.
- **Deterministic:** statements are sorted, TBox blank-node labels are
  stable, and the files carry no timestamps. An unchanged corpus produces
  no commit.
- **Committer:** commits are made by `folio-insights dump job
  <dump-job@folio-insights.invalid>` with the message
  `dump: N corpora at <UTC time>`, plus one line per corpus with its journal
  head.
- **Its own work tree:** the repository must be its own work tree. A
  subdirectory of another repository (this checkout, for instance) is
  refused, including a path that does not exist yet (the nearest existing
  ancestor is checked before anything is created), and so is any path that
  overlaps the storage root or sits inside the served `output/` directory.
- **Git runs pinned.** Every git call drops inherited `GIT_*` variables,
  ignores system and global config (`GIT_CONFIG_NOSYSTEM=1`,
  `GIT_CONFIG_GLOBAL=/dev/null`), and pins `core.hooksPath=/dev/null`,
  `core.fsmonitor=false` and `commit.gpgsign=false`; commits use
  `--no-verify`. Repository hooks, fsmonitor commands and signing never run.
- **Local only:** the job only commits locally. **Scheduling and pushing are
  deliberately not done here.** A host can run the entry point nightly,
  for example with a systemd user timer:

  ```ini
  # ~/.config/systemd/user/fi-dump.service (example only; not installed)
  [Service]
  Type=oneshot
  Environment=FOLIO_INSIGHTS_CORPUS_ROOT=/srv/fi/corpora
  ExecStart=/path/to/venv/bin/folio-insights storage dump --repo /srv/fi/dumps
  ```

  Pushing the dump repository anywhere is a separate publication decision.

**Restoring a dump.** A dump restores the **RDF view**, not the journal.
`folio_insights.storage.dump.restore_ttl_dump(dump_dir, new_store_dir)`
loads every file into its manifest graph in a new pyoxigraph store. The
authoritative journal (positions, op_ids, original signed bytes) is restored
from a snapshot. The dump does carry the signed records (below), so shards
and events can be re-verified from it.

At 1,000,017 triples, a dump and commit took 20.1 s.

## Export formats and their loss notes

```bash
folio-insights storage export corpus-a --out /tmp/corpus-a-export \
  [--format nquads --format jsonld …] [--construct-file q.rq]
```

| Format | Files | Named graphs | Loss notes |
|---|---|---|---|
| `combined.ttl` | `combined.ttl` | **none**: ABox, governance and TBox merged into one graph | Graph membership is lost. Refused with `--require-named-graphs`. |
| `abox` | `abox/<corpus>.ttl` | packaged: one file per ABox graph, mapped in `manifest.json` | None. |
| `tbox.ttl` | `tbox.ttl` | packaged (one graph) | None. Blank nodes are compared canonically. |
| `governance.ttl` | `governance.ttl` | packaged (one graph) | None. |
| `jsonld` | `dataset.jsonld` | native (`@graph` per graph) | Expanded JSON-LD, not framed. Cannot carry RDF 1.2 triple terms, so a dataset with one is refused. |
| `construct` | `construct.ttl` | **none**: the query result is one graph | It is a query-defined subset. A result that names a shard or governance event without its identity and signature triples is refused unless `--allow-partial`, which the manifest records. |
| `nquads` | `dataset.nq` | native | None. |
| `neo4j` | `neo4j/nodes.csv`, `neo4j/relationships.csv` | packaged: a `graph` property on each relationship | IRIs, blank nodes and literals (with datatype and language) become nodes; each quad becomes a relationship with its predicate IRI. Triple terms are refused. |

These rules hold for every format:

- **Signed records.** Every whole-dataset export carries them. For each
  current shard it writes `fi:signedRecord` (the journal's original record
  bytes, as validated and signed), `fi:signedRecordSha256` and
  `fi:recordSourceSchemaVersion`. For each governance event it writes
  `fi:signedEvent` (the event JSON with its signature). The projection
  itself keeps only signer DIDs and counts. Without these triples an export
  would drop signature material silently; with them, a shard or event can be
  reloaded from any format and its signatures re-verified.
- **One watermark.** The projection graphs and the journal's signed records
  are read at the same watermark.
- **Round-trip check.** After writing, every file is parsed back (pyoxigraph
  or the CSV reader) and compared with its source. A mismatch raises
  `ExportLossDetected` and removes what the export wrote.
- **Destinations.** An export goes to a new or empty directory outside the
  storage root and outside the served `output/` directory.
- **Default exports contain no rejected PII.** Inputs that match the PII
  gate (SSN, ABA routing number, US phone by default) are refused before the
  journal append. String leaves and integer leaves (as decimal text) are
  scanned; an integer too large to render is refused. They therefore never reach the journal, the projection, a
  dump, a snapshot or an export. Signature objects are scanned too (`did`,
  `signing_key_id`, cosigners); only a `signature` value shaped exactly like
  an Ed25519 base64url signature and 64-hex `*_hash` digests are exempt.
- **CONSTRUCT partiality is checked on subjects.** The identity/signature
  refusal applies to shards and events that appear as SUBJECTS of the
  result. A result that only mentions a shard IRI as an object is not
  checked (known limitation).
- **Unknown corpora are refused.** `storage export` and `storage status`
  refuse a corpus with no committed rows instead of creating it.

At 1,000,017 triples, the seven default formats took 62 s, including the
round-trip verification.

## Bulk load

`await ctx.bulk_load_shards(records, op_id=...)` takes the same checks and
the same single journal transaction as `ingest_shards`. It returns positions
instead of every committed record.

- **Bulk path.** A catch-up of 2,048 rows or more that only adds new
  subjects is written with `Store.bulk_load`, followed by a transactional
  watermark update. A crash between the two is repaired by idempotent
  replay.
- **Parallel checks (explicit opt-in).** The per-record checks and the
  N-Quads rendering run in a `forkserver` process pool for batches of 2,048
  records or more, but only when the pool is requested: `bulk_load_shards`
  (default `parallel=True`) and the storage CLI (`StorageConfig(process_pool=True)`).
  `ingest_shards`, `put` and ordinary catch-ups always run in-process.
  Worker start-up re-imports the caller's `__main__`, so a script that calls
  `bulk_load_shards` must guard its entry point with
  `if __name__ == "__main__":` or pass `parallel=False`.
- **Pool failure is permanent per process.** If the pool cannot start, or a
  worker breaks (for example a record that cannot be pickled back), the
  batch is redone in-process and the pool stays disabled for the rest of
  that process.
- **Refusal order does not depend on batch size.** The refusal raised is the
  one with the earliest input index, whether from a built-in check or a
  Phase 11 hook, with or without the pool.
- **Throughput.** The recorded 1M-triple benchmark lives in the plan's U4
  evidence. It is reproduced by `pytest tests/bench/test_storage_bulk_load.py -m slow -s`.

## Validation hooks and Phase 11

`StorageConfig(shard_validator=..., event_validator=...)` are the Phase 11
hooks.

- **They see copies.** Each hook receives a deep copy, so a hook can refuse
  but can never change what the identity and append-only checks, the
  journal, the projection cache or the persisted governance event see.
- **When they run.** They run after the built-in checks: the PII gate and
  model validation for shards, signature verification for events. They run
  before the journal transaction, whose identity and authorization checks
  still follow. A hook can add a refusal; it cannot remove one.
- **Full SHACL is still deferred.** `status().full_shacl` stays
  `deferred-to-phase-11` even with hooks installed. A hook is a seam, not
  the Phase 11 exit criterion.

## Proposed-class ledger

`ctx.proposals` (`PersistentProposalLedger`) is the storage seam of the
proposed-class governance pipeline (`folio_insights.proposals`,
`scripts/judge_proposals.py`). It is a second append-only table,
`proposal_ledger`, in `journal.sqlite3`.

- **Same guards as the journal.** Positions are contiguous per corpus, each
  operation has an explicit `op_id` (a retry returns the committed row, and a
  reuse for a different request is refused), UPDATE, DELETE and replace are
  refused by triggers, and the PII gate runs before the write transaction.
  `expected_head` makes an append conditional on the ledger head.
- **Schema key.** `storage_meta` records `proposal_ledger_schema_version`
  (1). A journal written before the ledger existed gains the empty table on
  its next open. An unknown version is refused.
- **No source text.** Proposals keep labels (at most 200 characters), run
  names, unit IDs and spans, never unit text or excerpts. A payload with an
  `excerpt`, `source_text` or similar key anywhere is refused, and judgments
  are reduced to an exact schema with capped strings.
- **PII gate scope.** The gate scans the operation ID as well as the payload.
- **Not projected.** Ledger rows never enter the RDF projection, so they do
  not move its watermark. TTL dumps and the RDF export formats do not include
  them (see "Approved-only backlog" below for why).
- **Decisions.** `decision` operations record explicit human review
  decisions (`scripts/apply_approvals.py apply`, or the review API; see
  "One approval surface" below). The ledger is the only store of record for
  proposal decisions. A proposal stays `pending`
  until one names it; judgments never change it. The whole batch is
  validated first (unknown IDs, invalid statuses and extra keys refuse it
  all), `decided_by` must be a reviewer handle `human:<handle>` (letters,
  digits, `.`, `_`, `-`; no e-mail address), and a changed decision appends
  to `decision_history` instead of overwriting.
- **Replays.** Every batch is appended, even one that changes nothing, so
  retrying its op_id always replays. A replay returns the original result and
  decision time, plus each proposal's `current_status` and a
  `superseded_since` list; the CLI prints a warning when a replayed decision
  was changed later. The CLI's default op_id includes the ledger head, so
  applying the same file again after the ledger moved is a new operation.
- **The fold re-validates.** Each stored decision item is checked again when
  the ledger is folded. An item with an unknown status, a non-human
  `decided_by`, an unknown proposal or a bad merge target decides nothing; it
  is listed in the registry's `invalid_decisions` and counted in the backlog
  (`invalid_decision_items`). It is not a load failure, because an
  append-only row can never be removed.
- **Limit: `decided_by` is self-asserted.** Nothing proves that a human made a
  decision: whoever can write the storage root can record any handle. The
  `human:` prefix and the fold check keep honest tooling from promoting
  judgments; they are not authentication. Signed decisions are a planned
  follow-up.
- **Reviewer notes are reviewer-authored.** `reviewer_note` is free text in
  the reviewer's own words, capped at 500 characters and passed through the
  PII gate. It must never hold pasted source text.
- **Snapshots verify it.** The manifest's per-corpus entry (covering the union
  of journal and ledger corpora) records `proposal_head`,
  `proposal_head_payload_sha256` and `proposal_rows`. A snapshot or restore
  refuses an unknown `proposal_ledger_schema_version`, and a restore checks
  each corpus's ledger head. A manifest written before the ledger existed
  restores only if the journal file holds no ledger rows.

### Approved-only backlog

`scripts/apply_approvals.py export --corpus C --out FILE` writes the
ontology-extension backlog: only proposals whose current decision is
`approved`, rows sorted by proposal ID, every value from the ledger. The same
ledger gives the same bytes, before or after a restart. The output passes the
corpus PII gate and the forbidden-key check, carries no source text or FOLIO
definition, and must be written outside every git work tree and outside the
storage root (the worklist and approval-queue writers follow the same rule).

It is deliberately separate from `storage export` and `storage dump`:

- the export formats are verified RDF views of the projection, and ledger
  rows are not in the projection;
- the dump commits into a git repository, and generated proposal material,
  whose labels come from pipeline output, must never be committed (R5);
- snapshots already copy the ledger and verify its per-corpus head, so a
  restore recovers every decision, and the backlog is regenerated from it.

### One approval surface: the review API

The review API records and reads proposed-class decisions in the same ledger
(`api/services/proposals.py`), so a decision made in the viewer reaches the
approved-only backlog.

- **Write.** `POST /api/v1/proposed-classes/{label}/review?corpus=C` with
  `{"status": "approved", "note": "..."}`. It also accepts every status the
  ledger accepts: `approve`/`approved`, `reject`/`rejected`, `needs_work`, and
  `merge`/`merged` with `merge_into` naming the surviving proposal ID. The
  label resolves to the corpus's proposal ID through the registry, so case and
  punctuation variants find the same proposal. The decision is recorded
  through `ProposalStore.record_decisions`, with the same validation, the PII
  gate and the decision history. Every refusal writes nothing:

  | Refusal | Status |
  |---|---|
  | Invalid status, malformed corpus ID or `op_id`, or a merge without a valid target | 400 |
  | No reviewer configured, or an invalid one | 403 |
  | Unknown label (or no ledger yet) | 404 |
  | `op_id` reused for a different decision, or the ledger moved mid-request | 409 |
  | A body field outside the model (`decided_by`, for instance) | 422 |
  | The PII gate matched the note | 422 |
  | The storage root sits inside the served output directory, or storage cannot open | 503 |
- **Reviewer.** `decided_by` is `human:<handle>` from server configuration:
  `api.main.configure(reviewer=...)`, else `$FOLIO_INSIGHTS_REVIEWER`. A bare
  handle gets the `human:` prefix. The API has no authentication, so the
  reviewer is never taken from the request. When authentication lands, it
  must come from the authenticated principal. As with the CLI, the handle is
  self-asserted.
- **Operation IDs.** The body may carry `op_id`, a client idempotency key
  (1-100 of letters, digits, `.`, `_`, `:`, `-`), stored as
  `api:review:key:<op_id>`. A retry with it replays the original result and
  appends nothing. Without one, the server derives
  `api:review:auto:<digest>` over the corpus, reviewer, decision and ledger
  head. A repeat of a current decision is then a no-op batch that keeps the
  original `decided_at`.
- **Read.** `GET /api/v1/proposed-classes?corpus=C` lists every proposal with
  its current decision, and `GET /api/v1/proposed-classes/{label}?corpus=C`
  returns one. Both read the folded ledger, never `review.db`.
- **Corpus mapping (conservative).** The ledger corpus is the API corpus ID
  verbatim. That is the `output/<corpus>/` directory name, and
  `judge_proposals.py collect --corpus` must use the same name. IDs that are
  not 1-128 characters of letters, digits, `.`, `_` or `-` are refused.
  Proposal IDs hash the corpus, so collecting under a different name leaves
  the API with no proposals (404). It can never decide another corpus's
  proposal.
- **Storage root.** `api.main.configure(corpus_root=...)`, else
  `$FOLIO_INSIGHTS_CORPUS_ROOT`, else `~/.folio-insights/corpora`, the same
  resolution as the CLI. The API never creates a storage root: with no
  `journal.sqlite3`, reads return an empty list and writes find no label.
- **Reset.** `POST /api/v1/review/reset` resets unit review only. Ledger
  decisions are append-only, and the legacy table is read-only.

### Legacy review.db decisions

Before the ledger, the API upserted proposed-class decisions into the
`proposed_class_decisions` table of `output/<corpus>/review.db`, keyed by
label, with no reviewer. That table is now **read-only legacy**:

- the review.db schema (`folio_insights.persistence.review_db.SCHEMA_SQL`,
  run on every open) adds triggers that refuse INSERT, UPDATE and DELETE on
  it;
- nothing drops it, and nothing migrates it on startup.

Its rows reach the ledger only through an explicit, idempotent import:

```bash
python scripts/apply_approvals.py import-legacy --corpus C \
    --review-db output/C/review.db [--legacy-corpus NAME] [--dry-run]
```

- **What it records.** It opens the database read-only and imports the
  `approved` and `rejected` rows of the corpus. Rows are matched by
  `corpus_name`, which defaults to `--corpus`. They go in as one decision
  batch by `human:legacy-review-db`, with op_id `legacy-review-db:<digest>`.
- **Provenance.** Each decision carries `source`, `legacy_row_id`,
  `legacy_row_digest` and the original `legacy_reviewed_at`. The ledger's
  `decided_at` is the import's commit time. The approved-only backlog shows
  the provenance.
- **Never overrides.** A proposal that already has a ledger decision is left
  alone (`already_decided`), because the ledger is newer than the legacy
  table.
- **Idempotent.** A row already imported is found by its digest
  (`already_imported`), so a second run appends nothing.
- **Skipped rows.** These are reported by legacy row ID, never by label or
  note:
  - `pending` rows;
  - rows with another status or an invalid note (`invalid_rows`);
  - labels that resolve to no proposal of the corpus (`unresolved_rows`);
  - all but the latest of several rows for one proposal (`superseded_rows`);
  - rows the PII gate refuses (`pii_refused_rows`).
- **Dry run.** `--dry-run` reports `would_import` and writes nothing.

## Deploying extraction: the deterministic IRI path

The extraction pipeline's FOLIO tagger needs its deterministic entity-ruler
path. By default (`require_deterministic_iri`) a run aborts when that path
cannot load, rather than emitting LLM/semantic IRIs silently. A host that runs
extraction therefore needs:

- a folio-enrich checkout (`FOLIO_INSIGHTS_FOLIO_ENRICH_PATH`), which provides
  the FolioService and its FOLIO labels; and
- the FOLIO ontology, either cached locally by folio-enrich or reachable over
  the network on first load.

Without them, set `FOLIO_INSIGHTS_REQUIRE_DETERMINISTIC_IRI=false` to run in
degraded mode. The state is then recorded as `deterministic_iri_path:
degraded` in the output summary's `folio_tagger` block, so a degraded run is
never mistaken for a clean one.

## rdflib

rdflib is adapter-only. It builds in-memory graphs for pyshacl validation
and is never a store. Every projection, export, dump and restore write goes
through pyoxigraph. `tests/storage/test_rdflib_adapter_only.py` checks this
by scanning the source and by running the whole life cycle.
