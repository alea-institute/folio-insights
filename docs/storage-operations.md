# Storage operations (Phase 13)

How to back up, restore, dump and export a folio-insights storage root. The
design lives in the [Phase 13 storage plan](plans/2026-09-30-0913-feat-phase13-storage-plan.md);
this page is the operator's view.

## What a storage root holds

A storage root is one directory, chosen by `--corpus-root`, else
`$FOLIO_INSIGHTS_CORPUS_ROOT`, else `~/.folio-insights/corpora`.

| Path | Role |
|---|---|
| `journal.sqlite3` (+ `-wal`, `-shm`) | The authoritative journal: every shard revision and governance event of every corpus, append-only, with an `op_id` per operation. |
| `projection.oxigraph/` | The RDF projection (pyoxigraph/RocksDB). It is derived state: one ABox graph and one governance graph per corpus, a shared TBox graph, and a per-corpus watermark. |
| `projection.lock` | The cross-process lock that guards the projection. |

The journal is the only thing that must survive. The projection can always
be rebuilt from it. On every open, the projection checks its watermark: the
journal position plus the payload sha256 of the row at that position. A
journal that is shorter, or the same length with different content, makes
the projection rebuild itself rather than serve stale RDF.

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
| `status CORPUS` | Journal head, projection watermark, installed validation hooks, `full_shacl` (always `deferred-to-phase-11`). |
| `export CORPUS --out DIR [--format F]… [--construct-query Q \| --construct-file F] [--allow-partial] [--require-named-graphs]` | The export formats (below). Writes to a new or empty directory. |
| `dump --repo DIR [--corpus C]… [--init]` | Writes a TTL dump of every corpus and records a local Git commit. This is the nightly job's entry point. |
| `snapshot --out DIR [--no-projection]` | Snapshots the whole storage root (all corpora). |
| `restore SNAPSHOT --to NEWDIR [--rebuild-projection]` | Restores a snapshot into a new storage root. |

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
- **Verified before it appears.** The restore is assembled in
  `.<dest>.restoring-<id>` next to the destination. These checks run first:
  - the journal sha256 against the manifest;
  - the SQLite integrity check and the schema version;
  - per-corpus heads and head-row digests against the manifest;
  - a full open and catch-up of every corpus. Journal rows past a snapshot
    watermark are replayed; a watermark whose digest does not match is
    rebuilt.

  Only then is the directory renamed into place.
- **Interruption-safe.** A failure or kill before the rename never creates
  the destination. It never touches the snapshot or any live root. A killed
  process can leave a `.<dest>.restoring-*` directory, which is safe to
  delete.
- **Rebuild:** `--rebuild-projection` skips the copied projection and
  replays the journal into a fresh one.
- **Matching code:** restore with the code version recorded in the
  manifest. An unsupported journal schema is refused, never migrated
  silently.

Then point the service at the new root (`--corpus-root` or
`$FOLIO_INSIGHTS_CORPUS_ROOT`). Rollback means restoring into a new
destination and switching to it; never overwrite the only copy.

At 1,000,017 triples, a restore that copies the projection took 0.26 s, and
a restore with a rebuild took 2.38 s.

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
  refused, and so is any path that overlaps the storage root or sits inside
  the served `output/` directory.
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
  journal append. They therefore never reach the journal, the projection, a
  dump, a snapshot or an export.

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
- **Parallel checks.** The per-record checks and the N-Quads rendering run
  in a `forkserver` process pool for batches of 2,048 records or more. If
  the pool cannot start, they fall back to running in-process.
- **Throughput.** The recorded 1M-triple benchmark lives in the plan's U4
  evidence. It is reproduced by `pytest tests/bench/test_storage_bulk_load.py -m slow -s`.

## Validation hooks and Phase 11

`StorageConfig(shard_validator=..., event_validator=...)` are the Phase 11
hooks.

- **When they run.** They run after the built-in checks: the PII gate and
  model validation for shards, signature verification for events. They run
  before the journal transaction, whose identity and authorization checks
  still follow. A hook can add a refusal; it cannot remove one.
- **Full SHACL is still deferred.** `status().full_shacl` stays
  `deferred-to-phase-11` even with hooks installed. A hook is a seam, not
  the Phase 11 exit criterion.

## rdflib

rdflib is adapter-only. It builds in-memory graphs for pyshacl validation
and is never a store. Every projection, export, dump and restore write goes
through pyoxigraph. `tests/storage/test_rdflib_adapter_only.py` checks this
by scanning the source and by running the whole life cycle.
