# Bridge ingest: folio-enrich propositions as hypothesis shards

folio-enrich extracts propositions from a document.
folio-insights keeps a governed corpus of shards.
The bridge connects the two without merging them ("bridge, not merge").

- **Ingest** turns one enrich export, a `PropositionDocumentRecord`, into `HypothesisShard`s.
- **Status** answers what the corpus knows about a batch of shard IRIs.

Code: `src/folio_insights/bridge_ingest/`.
HTTP: `api/routes/bridge.py`.
Plan: folio-enrich `docs/plans/2026-10-09-0645-feat-insights-bridge-plan.md` (unit U4, R11 to R16).

## Identity contract

A shard IRI is a content address of `(source_uri, span)`:

```
input = rfc3986_nfc(source_uri) + "\n" + normalize_span(span)
hash  = sha256(input).hexdigest()
iri   = "urn:folio:shard/" + hash[:32]
```

- `folio_insights.shards.minting.mint_shard_iri` is the frozen recipe.
- `folio_propositions.content_iri` (v0.4.0) reproduces it byte for byte.
- `tests/bridge_ingest/test_identity_parity.py` checks the two agree on fixed vectors and on a property-based corpus.
  The corpus covers http, https and urn URIs; NFC and NFD paths; trailing slashes; queries and fragments; CRLF, CR and LF spans; Unicode; and surrounding whitespace.
- Identity is per span, not per proposition type.
  Two enrich propositions with different types over one span share one IRI and one shard.
- A stamped `content_iri` that differs from `mint_shard_iri(source_uri, text)` refuses the whole record (`ContentIriMismatch`, naming the proposition).
  Ingest never re-mints silently.
- A record without `source_uri` is refused (`MissingSourceUri`).
- Only the library refuses a span that normalizes to the empty string; bridge-ingest skips such propositions (`empty text`).

## Accepted input

- The JSON record from `GET /enrich/{job}/export?format=propositions` (schema v4).
- The NDJSON form (`format=propositions-ndjson`).
  The first line is a header with `record_type` `proposition_document` (also accepted: `document`, `record`, `header`) carrying the record fields.
  Each following line is one proposition with `record_type: "proposition"`.
- Older schema versions migrate through `folio_propositions.migrate_record` first.
  A v3 record has no `source_uri`, so enrich must re-export it before it can be ingested.

## Field mapping

One `HypothesisShard` per distinct IRI.
Within a group, propositions sort by `(proposition_type, id)`; the first one supplies the per-proposition fields.

| Shard field | Value |
|---|---|
| `shard_iri`, `provenance_hash` | `mint_shard_iri(record.source_uri, text)` |
| `source_uri` | `record.source_uri` |
| `source_span`, `sense`, `triple.object` | the proposition text |
| `extracted_at` | first ISO-8601 timestamp in `document_metadata` (`extracted_at`, `exported_at`, `completed_at`, `created_at`, `timestamp`), else now (UTC) |
| `first_extractor_did` | `--extractor-did` / `$FOLIO_INSIGHTS_BRIDGE_EXTRACTOR_DID`, default `did:web:folio-enrich.local` |
| `epistemic_status` | `hypothesis` |
| `generation_method` | `inductive` |
| `verification_method` | `extractor_assertion` |
| `predication_mode` | `per_accidens` |
| `fork` | `synthetic_a_posteriori` |
| `layer` | `L3_jurisdictional` |
| `bfo_category` | `continuant_dependent` |
| `speech_act` | asserter role: court → `holding`; secondary_source → `treatise_statement`; party, plaintiff, defendant, appellant, appellee, petitioner, respondent, both_parties → `pleading_argument`; system or none → `dictum` |
| `triple.subject` | asserter `individual_id`, else `role:<role>`, else `unknown` |
| `triple.predicate` | `proposition_type` |
| `reference` | the FOLIO IRI from `WORKING_TAXONOMY[type]`, else `urn:folio-propositions:type/<slug>` |
| `logical_form_imputed` | `PROPOSITION_TYPES(<sorted distinct types joined by " \| ">)` |
| `framework_id` | `--framework-id`, default `us.case-law.unspecified` |
| `extractor_version` | `record.generator.version`, else `unknown` |
| `extractor_model` | `record.generator.tool`, else `unknown` |
| `extraction_prompt_hash` | `sha256("<tool>\|<version>\|<proposition_lexicon_version>")` |
| `confidence` | `0.5` |
| `ttl_days` | model default (90) |
| `depends_on_precedents` | empty; enrich citation edges name enrich individuals, not insights IRIs |

Every other field keeps its model default.
The envelope also requires `schema_version`, `vocab_version` and `transaction_time`; their defaults are the current pins and the wall clock.

The envelope is `extra="forbid"`, so enrich provenance goes to a manifest instead.
`<corpus storage root>/bridge-ingest/manifest.jsonl` holds one JSON line per `(corpus, iri, document_id, proposition_id)`.
Each line carries `proposition_type`, `start_char`, `end_char`, `disposition`, `asserter_role` and `citation_edges`.
Citation edges keep only `edge_type` and `authority_individual_id`; the free-text `authority_text` is dropped.
Every candidate line passes the corpus PII gate (the same gate `ingest_shards` applies to shards) before it is written.
A refused line is dropped and listed in the report's `manifest_refused` by IRI, field path and pattern name, never by value.
Appends take a non-blocking `flock` on `manifest.lock`, retried for up to 5 seconds, then fail with `ManifestBusy` (HTTP 503).
Under the lock, keys already present are skipped (the seen-key set is cached by file size and mtime), and the append is `fsync`ed.
Reads take no lock, and all manifest I/O runs in a worker thread, so a held lock never stalls `/status` or `/health`.

## Ingest semantics

- Writes go through `CorpusStorageContext.ingest_shards`, so the PII gate, model validation and the SHACL suite apply unchanged.
- Idempotent per IRI: an IRI already in the corpus is never rewritten and counts as `existing`.
- New IRIs land in one batch with operation ID `bridge-ingest:<record sha256[:16]>:<new-IRI-set sha256[:16]>`.
- If the batch is refused (PII, SHACL, record validation), each new shard is retried alone.
  Refused shards are reported with a reason that never contains the matched value; the rest land.
- Another writer can land an IRI between the existence check and the write.
  The same record pushed twice shows up as an operation-ID conflict or a replay.
  A different record sharing a span shows up as `ShardIdentityViolation`, because its `extracted_at` differs.
  Either way ingest re-checks and retries (up to 3 attempts).
  After the write, any shard reported refused that is now in the corpus moves to `existing` and keeps its manifest provenance.
- Concurrent first pushes to a brand-new storage root race inside SQLite on the WAL pragma; ingest retries opening storage a few times.
- The manifest is appended after the shards commit. If that step fails (`ManifestBusy`), re-pushing the record appends the provenance.
- The report (`IngestReport`) lists `created`, `existing`, `skipped` and `refused` counts and the IRIs or proposition ids behind them.

## HTTP contract (`/api/bridge/v1`)

### `POST /status`

Request: `{"iris": ["urn:folio:shard/<32 hex>", ...], "corpus": null}`.

- At most 500 IRIs; each must match `^urn:folio:shard/[0-9a-f]{32}$` (422 otherwise).
- Duplicates are dropped; request order is kept.
- An unknown corpus answers 404.

Response: `{"corpus", "insights_version", "results": [...]}`, one result per IRI:

```json
{"iri": "urn:folio:shard/…", "present": true, "shard_type": "hypothesis", "epistemic_status": "hypothesis",
 "contested": false, "supersedes": null, "superseded_by": null,
 "related": [{"iri": "…", "relation": "elaborates|elaborated_by|depends_on|depended_on_by|glosses|glossed_by"}],
 "contesting": [{"iri": "…", "relation": "contests|conflicting_authority|superseded_by|objection"}],
 "enrich_sources": [{"document_id": "…", "proposition_id": "…", "proposition_type": "…"}]}
```

An absent IRI has `present: false`, null scalars and empty lists.

Where each field comes from:

- **Projection, one batched query**: `fi:shardType`, `fi:epistemicStatus`, `fi:contested`, `fi:supersedes`, `fi:supersededBy`.
- **Projection, one batched query**: `fi:dependsOn{Axiom,Definition,Precedent,Shard}` in both directions (`depends_on`, `depended_on_by`), shards that `fi:supersedes` the IRI (`superseded_by`), and governance contest events (`fi:action "contest"` with `fi:shardIri`, relation `contests`, IRI = the event).
- **Shard records**: `elaborates`, `glosses`, conflicting-authority `sic`/`non` positions and disputed-proposition objections are not projected.
  They come from one pass over the corpus shards, cached per journal head.
  Projecting them is a follow-up for the axioms lane; it would remove that pass.
- **Manifest**: `enrich_sources`.

### `GET /health`

`{"status": "ok", "corpus": <name>, "shards": <count>}`; a corpus with no committed rows reports 0.
Optional query `corpus`.

### `POST /ingest`

- Enabled only while `FOLIO_INSIGHTS_BRIDGE_TOKEN` is non-empty, checked per request; otherwise 404.
- Needs `Authorization: Bearer <token>`, compared with `hmac.compare_digest`; otherwise 401.
- Body: the JSON record (`application/json`), or NDJSON (`application/x-ndjson`, `application/ndjson`, `application/jsonl`, `application/x-jsonlines`).
- Bodies over `FOLIO_INSIGHTS_BRIDGE_MAX_BODY_BYTES` (default 20 MiB) answer 413.
- Query: `corpus` (default below), `framework_id` (default `us.case-law.unspecified`).
- Answers 200 with the `IngestReport`, also on re-push (then `created` is 0 and `existing` counts every IRI).
  folio-enrich pushes records automatically after a job, so repeated pushes are expected.
- A refused record answers 422 with the refusal class.
  Storage failures and a held manifest lock answer 503; other storage input refusals (such as an operation-ID conflict) answer 409.
  An invalid `Content-Length` answers 400.
  Error details name only the error class, never a path.

Read endpoints are unauthenticated, like the rest of the insights API today; adding auth is a follow-up.
No response contains a filesystem path.

## Environment

| Variable | Use |
|---|---|
| `FOLIO_INSIGHTS_CORPUS_ROOT` | corpus storage root (default `~/.folio-insights/corpora`; the app's configured root wins) |
| `FOLIO_INSIGHTS_BRIDGE_CORPUS` | default bridge corpus (else the app default corpus) |
| `FOLIO_INSIGHTS_BRIDGE_TOKEN` | enables `POST /ingest` and is its bearer token |
| `FOLIO_INSIGHTS_BRIDGE_EXTRACTOR_DID` | `first_extractor_did` for ingested shards; default `did:web:folio-enrich.local` |
| `FOLIO_INSIGHTS_BRIDGE_MAX_BODY_BYTES` | ingest body cap (default 20971520) |

Operators should set `FOLIO_INSIGHTS_BRIDGE_EXTRACTOR_DID` to a real DID for the enrich deployment.
The default is a placeholder that only satisfies the `did:(key|web|plc):` pattern.

## Operator walkthrough

1. Run an enrich job with proposition extraction on, then export it:
   `curl -o record.json "$ENRICH/enrich/$JOB/export?format=propositions"`.
2. Ingest it:
   `folio-insights bridge-ingest record.json --corpus case-law --json`.
   Add `--corpus-root PATH` to use another storage root.
   Exit code 1 means the record was refused; 2 means some shards were refused (listed in the report).
3. Check a shard:
   `folio-insights bridge-status urn:folio:shard/<32 hex> --corpus case-law`.
4. Re-running step 2 is safe: it reports every IRI as `existing`.
5. To let enrich push records itself, set `FOLIO_INSIGHTS_BRIDGE_TOKEN` on the insights server and give enrich the same token.
