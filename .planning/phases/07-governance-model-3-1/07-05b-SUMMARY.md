---
phase: 07-governance-model-3-1
plan: 05b
subsystem: retraction-cascade-turtle-export-governance-show
tags: [governance, retract, cascade-preview, turtle-export, governance-show, D-17, D-18, D-08, GOV-06]
requires:
  - "governance/events.RetractionEvent (07-01)"
  - "governance/events._BaseEvent.signature_payload (07-04a)"
  - "governance/authorize.authorize + Allow/Deny + _REVIEWER_ACTIONS (07-04a — extended here for export/show)"
  - "governance/log.InMemoryGovernanceLog (07-03 / 07-04a)"
  - "governance/shape_validation.validate_retraction_shape stub (07-01 — body filled here)"
  - "governance/cli.governance_group (07-04b / 07-05a — extended here with retract + export + show)"
  - "governance/cli._state.GOVERNANCE_LOG (07-04b — singleton wired here for the 3 new commands)"
  - "revision/store.ShardStore + InMemoryShardStore (Phase 5)"
provides:
  - "governance/retract.CascadePreview — frozen Pydantic preview (D-17, RESEARCH 636-644)"
  - "governance/retract.PreviewStale — D-17 race-refusal exception"
  - "governance/retract.classify_dependent — D-18 heuristic (locked verbatim, RESEARCH 1338-1353)"
  - "governance/retract.build_cascade_preview — async cascade builder over InMemoryShardStore"
  - "governance/retract.commit_cascade — re-runs builder + raises PreviewStale on race"
  - "governance/retract.validate_retraction — defense-in-depth field validator"
  - "governance/shapes/retraction_shape.ttl — fi:RetractionShape (cascadePreviewHash + shardIri non-empty)"
  - "governance/shape_validation.validate_retraction_shape (body) + _build_retraction_graph"
  - "governance/shape_validation.serialize_log_as_turtle — D-08 Turtle helper inside the lone exempt module"
  - "governance/cli/retract.retract_cmd — interactive / --preview / --apply (D-17 three modes)"
  - "governance/cli/export.export_cmd — D-08 on-demand Turtle export"
  - "governance/cli/show.show_cmd — read-only paginated companion to export"
affects:
  - "governance/cli/__init__.py — 3 new add_command calls (alongside 07-04b's 3 + 07-05a's 3)"
  - "governance/authorize.py — _REVIEWER_ACTIONS extended with 'export' + 'show' (D-19 read paths)"
  - "governance/shape_validation.py — validate_retraction_shape body + serialize_log_as_turtle helper"
  - "tests/governance/test_authorize_called_first.py — parametrize list extended over the 3 new CLI files"
tech-stack:
  added: []
  patterns:
    - "Standalone module discipline (D-16): retract.py imports only from governance.events + revision.store + revision.content_edit + identity primitives + stdlib + jcs — NEVER from contest.py or supersede.py. Auto-flips the 07-05a grep-guard test from 5 pass + 3 skip to 8 pass (full triad enforcement)."
    - "Immutable, frozen CascadePreview Pydantic model so two preview JSON round-trips are structurally identical and any extra field at --apply time triggers ValidationError before the race-check runs."
    - "JCS-canonical SHA-256 (via jcs.canonicalize + hashlib) for the cascade_preview_hash AND the underlying_state_hash — same pre-normalization recipe Phase 5's canonical_content_hash uses (RFC 8785)."
    - "commit_cascade re-runs build_cascade_preview internally so PreviewStale is detected over the SAME logic that built the preview — there is no separate 'comparator function' to drift apart from the builder."
    - "D-19 read-path extension: 'export' + 'show' added to _REVIEWER_ACTIONS. Read CLI commands still pass through authorize() as their first awaited step — D-19 is uniform across read AND write surfaces (Rule 2 — uniform critical coverage)."
    - "D-04 boundary discipline at the CLI layer: cli/export.py delegates Turtle serialization to shape_validation.serialize_log_as_turtle (the lone module under governance/ allowed to import rdflib). The CLI itself contains zero rdflib references."
    - "Singleton-reset robustness in tests: test_governance_export_cli.py reassigns _cli_state.GOVERNANCE_LOG (mirrors tests/corpus/test_corpus_init_genesis.py) instead of mutating .by_corpus on a stale reference — required because the corpus test fixture replaces the singleton mid-suite."
    - "Sample retract preview JSON (anonymized) — see 'Sample Cascade Preview' section below."
key-files:
  created:
    - src/folio_insights/governance/retract.py
    - src/folio_insights/governance/shapes/retraction_shape.ttl
    - src/folio_insights/governance/cli/retract.py
    - src/folio_insights/governance/cli/export.py
    - src/folio_insights/governance/cli/show.py
    - tests/governance/fixtures/__init__.py
    - tests/governance/fixtures/cascade_corpora.py
    - tests/governance/test_cascade_preview_classification.py
    - tests/governance/test_preview_stale_refusal.py
    - tests/governance/test_retraction_shape.py
    - tests/governance/test_cascade_preview_shared_builder.py
    - tests/governance/test_governance_export_cli.py
  modified:
    - src/folio_insights/governance/cli/__init__.py
    - src/folio_insights/governance/authorize.py
    - src/folio_insights/governance/shape_validation.py
    - tests/governance/test_authorize_called_first.py
decisions:
  - "D-17 three-mode cascade preview SHIPPED: interactive default + --preview (JSON dry-run) + --apply (PreviewStale on race). The commit step re-runs build_cascade_preview internally, so the 'detector' and the 'builder' are the same code — no second-implementation drift risk."
  - "D-18 classifier LOCKED at three layers: (a) classify_dependent in retract.py (heuristic verbatim from RESEARCH 1338-1353); (b) 10-row parametrized truth table in test_cascade_preview_classification.py + a safe-default test (>=8 rows per acceptance); (c) cascade fixture corpora seed all three buckets so the interactive CLI flow exercises the same paths the unit tests cover."
  - "D-08 closure: governance export CLI ships with the actual Turtle writer (NOT just a stubbed CLI shape). The writer lives in shape_validation.serialize_log_as_turtle (D-04 boundary-respecting). tests/governance/test_governance_export_cli.py is the dedicated CLI-end-to-end verification owner per Issue #4 — positive round-trip + negative unauthorized + AST-first-step + D-04 boundary scan, all in one dedicated file."
  - "D-16 grep-guard FULL TRIAD: the 07-05a test_grep_guard_three_way_disambiguation.py auto-promoted from 5 pass + 3 skip to 8/8 PASS the moment retract.py + cli/retract.py landed. NO edit was needed in 07-05a; the pytest.importorskip + module-path lookups were idempotent. Smoke-tested by removing the file would cause the test to skip back; restoring restores."
  - "D-19 source-scan parametrize list EXTENDED over retract + export + show (Rule 2 — uniform critical coverage; mirrors the 07-05a precedent that extended the list over contest/supersede/resolve_contest)."
  - "Singleton fix in the new export CLI test: reassigning _cli_state.GOVERNANCE_LOG (instead of clearing the dict on a snapshot) is required because corpus tests REPLACE the singleton, and the CLI's late-binding `from ._state import GOVERNANCE_LOG` resolves to the CURRENT module-level reference each invocation. Documented as a test-only fix; no production code change needed."
metrics:
  duration_minutes: 60
  completed: 2026-05-30
---

# Phase 07 Plan 05b: Retraction Cascade + Turtle Export + governance log show Summary

Shipped GOV-06 (the D-17 three-mode retraction cascade preview),
D-08 (on-demand `governance export` CLI with its dedicated
end-to-end test file per Issue #4), the `governance show` companion,
and the D-16 third sibling (`retract.py`) — which automatically promoted
the 07-05a grep-guard regression test from skip-mode to full-triad
enforcement. All 8 SHACL TTL shapes for Phase 7 now ship. The
D-04 boundary is intact across the full `governance/` package
(`shape_validation.py` remains the lone rdflib-import exempt module).

## What Shipped

### 1. `governance/retract.py` — the third D-16 sibling (PRD §3.1.4, GOV-06)

```
src/folio_insights/governance/
├── contest.py          — ContestEvent + validate_contest (07-05a)
├── supersede.py        — SupersessionEvent + validate_supersession (07-05a)
├── retract.py          — RetractionEvent + CascadePreview + PreviewStale +
│                         classify_dependent + build_cascade_preview +
│                         commit_cascade + validate_retraction      (07-05b)
└── resolve_contest.py  — ContestResolutionEvent + _GOV_05_PATHS (07-05a)
```

`retract.py` imports ONLY from `governance.events`, `revision.store`,
`identity.signer`, `shards.envelope`, stdlib, and `jcs`. NEVER from
`governance.contest` or `governance.supersede`. The D-16 grep-guard
regression test auto-promotes the moment this module ships.

Exports:
* `RetractionEvent` (re-exported from `events.py`).
* `CascadePreview` — frozen Pydantic model with 7 fields (RESEARCH 636-644).
* `PreviewStale(ValueError)` — race-refusal exception.
* `classify_dependent` — D-18 heuristic verbatim (RESEARCH 1338-1353).
* `build_cascade_preview` — async cascade builder.
* `commit_cascade` — re-runs the builder, raises PreviewStale on mismatch.
* `validate_retraction` — defense-in-depth field validator.

### 2. `fi:RetractionShape` — the 8th and final SHACL TTL shape

`src/folio_insights/governance/shapes/retraction_shape.ttl` (15 triples;
parses cleanly via rdflib):

| Constraint                | Form                                           |
|---------------------------|------------------------------------------------|
| `fi:shardIri`             | sh:minLength 1 (non-empty)                     |
| `fi:cascadePreviewHash`   | sh:minLength 1 + sh:datatype xsd:string        |

Defense-in-depth belt over `validate_retraction` in retract.py.

`shape_validation.validate_retraction_shape` body replaces the
`NotImplementedError` stub from 07-01; `_build_retraction_graph` helper
follows the 07-04a plain-Literal precedent (xsd:string datatype + minLength
constraints fire cleanly together).

### 3. The 8 SHACL TTL shapes — Phase 7 complete

```
governance/shapes/
├── governance_log_shape.ttl     (07-03)
├── role_assertion_shape.ttl     (07-04a)
├── role_revocation_shape.ttl    (07-04a)
├── promotion_shape.ttl          (07-04b)
├── contest_shape.ttl            (07-05a)
├── contest_resolution_shape.ttl (07-05a)
├── supersession_shape.ttl       (07-05a)
└── retraction_shape.ttl         (07-05b)
```

`ls src/folio_insights/governance/shapes/*.ttl | wc -l` → 8.

### 4. Three new CLI command modules (D-08, D-15, D-17, D-19 authorize-first)

```
src/folio_insights/governance/cli/
├── retract.py — `governance retract` (D-17 three modes; PRD §3.1.4)
├── export.py  — `governance export`  (D-08 on-demand Turtle)
└── show.py    — `governance show`    (read-only companion)
```

Total `folio-insights governance --help` subcommands: **9**
(`assert-role, contest, export, promote, resolve-contest, retract,
revoke-role, show, supersede` — alphabetized by Click).

### 5. D-17 three-mode `governance retract` flow

| Mode                | Behavior                                                                                                  |
|---------------------|-----------------------------------------------------------------------------------------------------------|
| default (interactive) | build_cascade_preview → rich.table.Table (3-column grouped render) → click.confirm "Confirm retraction of N shards (auto_rederive: A, aporetic: B, review_needed: C)?" [y/N] → commit_cascade on y. |
| `--preview`         | build_cascade_preview → write timestamped JSON to `retract-preview-<sanitized_iri>-<ts>.json` (or `--output`) → exit 0 WITHOUT committing.                                                                  |
| `--apply <file>`    | load CascadePreview JSON → commit_cascade (re-runs build_cascade_preview internally) → on hash mismatch raise PreviewStale referencing `--preview` (exit code 2); on success emit signed RetractionEvent JSON. |

`--preview` and `--apply` are mutually exclusive (CLI validates).

### 6. D-08 on-demand Turtle export

`governance export <corpus_name> -o <output_path>`:

1. D-19 first step: `await authorize(signer_did, "export", corpus_name, log=log)`.
2. Collect events via `log.iter_events(corpus_name)`.
3. Delegate to `shape_validation.serialize_log_as_turtle(events)` —
   the lone exempt module under `governance/`.
4. Write Turtle to `output_path`.

Each event becomes a `prov:Activity` carrying:
* `prov:wasAttributedTo <signer_did_uri>`,
* `fi:position N` (xsd:integer),
* `fi:action "<action>"` (xsd:string),
* `fi:signedAt "<iso_datetime>"^^xsd:dateTime` (when signed_at is non-None).

Activity URIs are stable: `urn:fi:event:<corpus>:<position>`.

`tests/governance/test_governance_export_cli.py` is the dedicated
end-to-end verification owner per Issue #4 — it covers positive
round-trip + negative unauthorized + AST-first-step + D-04 boundary
scan in ONE file.

### 7. `governance show` — read-only paginated companion

`governance show --corpus <c> --limit 50`:

1. D-19 first step (read path still gated): `await authorize(signer_did, "show", corpus, log=log)`.
2. Iterate up to `--limit` events.
3. Render via `rich.table.Table`:
   `position | action | signer_did | signed_at | shard_iri`.

### 8. D-19 read-path extension

`governance/authorize.py::_REVIEWER_ACTIONS` extended with `export` + `show`.
Reviewers, arbiters, and corpus_admins MAY `export` / `show`; extractors
MAY NOT (no PRD §3.1 read-of-governance-log mandate for them). Rule 2
uniform critical coverage discipline — same as 07-05a's extension for
contest/supersede/resolve_contest.

### 9. D-19 source-scan extended

`tests/governance/test_authorize_called_first.py::_COMMAND_FILES` extended
with retract / export / show. The AST walk runs on all 10 command files
(promote, role_assert, role_revoke, corpus_init, contest, supersede,
resolve_contest, retract, export, show) and asserts `await authorize(...)`
precedes any `log.append` or `log.iter_events` call.

## Sample Cascade Preview (anonymized fixture output)

Generated by the cascade fixture corpora factory + `build_cascade_preview`:

```json
{
  "retracted_shard_iri": "fi:shard:retracted",
  "corpus": "cascade-test-corpus",
  "taken_at": "2026-05-30T22:00:27.714947Z",
  "underlying_state_hash": "c894abd2f44d66f67f46b10635817e38a58e9763c998744c5f1bff5d97f1d617",
  "auto_rederive": [
    "fi:shard:auto-1",
    "fi:shard:auto-2"
  ],
  "aporetic": [
    "fi:shard:aporetic-1"
  ],
  "review_needed": [
    "fi:shard:review-1",
    "fi:shard:review-2"
  ]
}
```

The hash is JCS-canonical SHA-256 over the `(retracted_iri,
retracted.superseded_by, corpus, log_latest_position, sorted dependents
attrs)` tuple set. The bucket lists are sorted by IRI for deterministic
rendering AND deterministic hashing.

## D-18 Classifier Truth Table (locked verbatim)

| # | supersession_avail | strategy           | epistemic_status | unresolved_votes | bucket          |
|---|--------------------|--------------------|------------------|------------------|------------------|
| 1 | True               | prefer_latest      | authority_only   | 0                | auto_rederive    |
| 2 | False              | prefer_latest      | authority_only   | 0                | aporetic         |
| 3 | False              | None               | authority_only   | 0                | aporetic         |
| 4 | True               | prefer_latest      | contested        | 0                | review_needed    |
| 5 | False              | None               | aporetic         | 0                | review_needed    |
| 6 | True               | prefer_latest      | authority_only   | 1                | review_needed    |
| 7 | True               | sense_distinction  | authority_only   | 0                | review_needed    |
| 8 | False              | unreconciled       | authority_only   | 0                | review_needed    |
| 9 | False              | None               | hypothesis       | 0                | aporetic         |
| 10| True               | None               | demonstrable     | 0                | aporetic         |

Plus `classify_dependent({})` → `aporetic` (safe-default test).
Total: 10 parametrized rows + 1 safe-default = >=8 per acceptance.

## Test Counts

| Suite                                                          | Tests Added | Status                                  |
|----------------------------------------------------------------|-------------|------------------------------------------|
| tests/governance/test_cascade_preview_classification.py        | 11          | 11/11 pass                               |
| tests/governance/test_preview_stale_refusal.py                 | 5           | 5/5 pass (3 async race + 2 sentinels)    |
| tests/governance/test_retraction_shape.py                      | 3           | 3/3 pass (1 positive + 2 negative)       |
| tests/governance/test_cascade_preview_shared_builder.py        | 4           | 4/4 pass                                 |
| tests/governance/test_governance_export_cli.py                 | 4           | 4/4 pass                                 |
| tests/governance/test_grep_guard_three_way_disambiguation.py   | 0 (07-05a)  | **8/8 pass** (was 5 pass + 3 skip)       |
| tests/governance/test_authorize_called_first.py                | 0 (07-04b)  | 10/10 pass (parametrize extended)        |
| tests/governance (this plan total)                             | 27          | 27/27 pass                               |
| tests/governance (cumulative 07-01 + 07-03 + 07-04a + 07-04b + 07-05a + 07-05b) | n/a | 166 pass + 0 skip                |
| tests/corpus (regression)                                      | 0 added     | 4/4 pass                                 |
| tests/ full (excluding pre-existing fastapi/folio-enrich)      | 0 added net | 795/795 pass                             |

## Sample CLI invocations

```bash
$ folio-insights governance --help
Commands:
  assert-role      Issue a role assertion (corpus_admin signs).
  contest          Record a contest on a shard (PRD §21.8 — distinct from...
  export           Export the governance log for <corpus_name> as Turtle...
  promote          Promote a HypothesisShard to an attested status (D-20...
  resolve-contest  Resolve a contested shard (GOV-05 — 3 paths: arbiter,...
  retract          Retract a shard with cascade preview (PRD §3.1.4 /...
  revoke-role      Revoke a previously-asserted role (corpus_admin signs;...
  show             Show recent governance events for a corpus (read-only,...
  supersede        Supersede an old shard with a new shard (PRD §21.9 —...

$ folio-insights governance retract --help
Usage: folio-insights governance retract [OPTIONS] SHARD_IRI

  Retract a shard with cascade preview (PRD §3.1.4 / GOV-06).

  Three modes (D-17):
    - default: build_cascade_preview, render grouped table, prompt
      'Confirm? [y/N]', commit on y.
    - --preview: write timestamped JSON, exit 0 without committing.
    - --apply <file>: re-run preview, compare underlying_state_hash;
      raise PreviewStale if changed.

Options:
  --preview        Build the cascade preview and write it to JSON; exit 0
                   without committing.
  --apply FILE     Re-run the preview, refuse with PreviewStale if the
                   underlying state changed, and commit.
  --output FILE    Output path for the --preview JSON.
  --corpus TEXT    Per-corpus governance log to retract within.  [required]
  --key-path PATH  Local ed25519 keystore JWK (DID-06).
  --yes            Skip the interactive confirmation (scripted use).
  --help           Show this message and exit.

$ folio-insights governance export --help
Usage: folio-insights governance export [OPTIONS] CORPUS_NAME

  Export the governance log for <corpus_name> as Turtle (D-08, on-demand).
```

## Acceptance Criteria

- [x] `python -c "from folio_insights.governance.retract import build_cascade_preview, commit_cascade, classify_dependent, CascadePreview, PreviewStale, RetractionEvent; print('ok')"` → `ok`
- [x] `rdflib.Graph().parse("retraction_shape.ttl")` succeeds (15 triples)
- [x] `pytest tests/governance/test_cascade_preview_classification.py` → 11/11 pass (>=8 parametrized rows)
- [x] `pytest tests/governance/test_preview_stale_refusal.py` → 5/5 pass (race detection asserts `--preview` in error message)
- [x] `grep -c "PreviewStale" src/folio_insights/governance/retract.py` → 5 (1 class def + 4 references)
- [x] `grep -c "from folio_insights.governance.contest\|from folio_insights.governance.supersede" src/folio_insights/governance/retract.py` → 0 (D-16 third sibling discipline)
- [x] `grep -rn "import rdflib|aiosqlite|pyoxigraph" src/folio_insights/governance/retract.py` → empty (D-04)
- [x] D-16 grep-guard test from 07-05a flips from skip-retract to full-triad enforcement → 8/8 PASS (was 5 pass + 3 skip)
- [x] `folio-insights governance retract --help` exits 0; mentions `--preview` + `--apply` + 3 modes
- [x] `folio-insights governance export --help` exits 0; mentions on-demand Turtle export per D-08
- [x] `folio-insights governance show --help` exits 0
- [x] `pytest tests/governance/test_cascade_preview_shared_builder.py` → 4/4 pass; AST walk proves all 3 retract CLI branches invoke build_cascade_preview (either directly or via commit_cascade which re-runs it)
- [x] `pytest tests/governance/test_governance_export_cli.py` → 4/4 pass (positive round-trip + negative unauthorized + AST-first-step + D-04 boundary)
- [x] `grep -rn "import rdflib|aiosqlite|pyoxigraph" src/folio_insights/governance/cli/` → empty
- [x] `grep -c "def serialize_log_as_turtle" src/folio_insights/governance/shape_validation.py` → 1
- [x] `pytest tests/governance -q` → 166 pass + 0 skip cumulatively across 07-01 / 07-03 / 07-04a / 07-04b / 07-05a / 07-05b
- [x] Behavior: 3-event InMemoryGovernanceLog emits valid Turtle via `governance export <corpus> -o <path>` that parses back to ≥3 prov:Activity triples
- [x] `ls src/folio_insights/governance/shapes/*.ttl | wc -l` → 8
- [x] `ruff check src/folio_insights/governance/` → clean (pre-existing F401 in tests/governance/test_promotion_status_kind.py is out of scope; documented in 07-05a SUMMARY)
- [x] `uv run python -m folio_insights.rfc.lint .planning/rfcs/` → exit 0 (no regression from 07-02)
- [x] `pytest tests/ -q` (excluding pre-existing fastapi/folio-enrich failures) → 795/795 pass
- [ ] Human-verify checkpoint (Task 3) → **AWAITING USER VERIFICATION**

## TDD Gate Compliance

Both tasks shipped under `tdd="true"` with strict RED → GREEN sequencing.
A REFACTOR step was not needed — the GREEN implementations match the plan's
PATTERNS structure on first pass.

| Phase  | Commit  | Description |
|--------|---------|-------------|
| RED    | 86131f6 | `test(07-05b): add failing tests for cascade preview + classifier + retraction shape (D-17/D-18)` (all fail at import — `governance.retract` does not exist) |
| GREEN  | 75482ce | `feat(07-05b): ship retract.py + RetractionShape + D-18 classifier (D-16/D-17)` (19/19 Task 1 tests pass; grep-guard flips 5+3 → 7+1) |
| RED 2  | 7c5f8cc | `test(07-05b): add failing tests for retract+export CLI (Task 2 RED)` (file-existence assertions fail) |
| GREEN 2| 7035446 | `feat(07-05b): ship retract/export/show CLI + serialize_log_as_turtle (D-08/D-17/D-19)` (8/8 Task 2 tests pass; grep-guard now 8/8 PASS; full repo 795/795 PASS) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical coverage] D-19 source-scan parametrize list extended**

- **Found during:** Task 2 GREEN.
- **Issue:** `tests/governance/test_authorize_called_first.py::_COMMAND_FILES`
  hardcodes 7 command files (promote, role_assert, role_revoke, corpus_init,
  contest, supersede, resolve_contest from 07-04b + 07-05a). Without
  extending the list to cover retract / export / show, a future regression
  removing `await authorize(...)` from any of the new commands would NOT
  be caught.
- **Fix:** Extended `_COMMAND_FILES` to include the 3 new CLI files with an
  explanatory comment naming 07-05b as the contributor (mirrors the
  07-05a precedent that did the same for the three-way disambiguation
  commands).
- **Files modified:** `tests/governance/test_authorize_called_first.py`
- **Commit:** 7035446 (Task 2 GREEN)

**2. [Rule 3 - Blocking issue] Dep-leak guard string-matches `import rdflib` in docstrings**

- **Found during:** Task 2 GREEN — first run of `pytest tests/governance` failed
  on `test_no_storage_import_in_governance[rdflib]`.
- **Issue:** My initial `cli/export.py` docstring + inline comment contained
  the literal substring `import rdflib` (intended as prose explanation of
  the D-04 boundary). The dep-leak guard does a plain `assert "import rdflib"
  not in source` over every governance/ module — false positive on docstrings.
- **Fix:** Rephrased the prose to avoid the literal substring. The docstring
  still explains the D-04 boundary ("does NOT pull in the RDF stack
  directly"); the inline comment now says "lone module under governance/
  that owns the RDF substrate dependency". Functionally identical
  explanation; lexically distinct.
- **Files affected:** `src/folio_insights/governance/cli/export.py`
- **Commit:** 7035446 (Task 2 GREEN; rephrasing folded into the GREEN commit)

**3. [Rule 1 - Bug] Singleton-reset test pattern**

- **Found during:** Task 2 GREEN, full-repo test run.
- **Issue:** `test_governance_export_cli.py::test_export_turtle_round_trip`
  passed in isolation but failed in the broader run with
  `unauthorized (denied: no_active_role)`. Root cause:
  `tests/corpus/test_corpus_init_genesis.py` has an autouse fixture that
  REPLACES `_cli_state.GOVERNANCE_LOG` between tests. After it runs, our
  test's initial `GOVERNANCE_LOG._by_corpus.clear()` cleared the old
  reference; the CLI's late-binding `from ._state import GOVERNANCE_LOG`
  resolved to the NEW (empty) singleton; the seeded events were on the
  OLD instance; export saw an empty log + no role → `no_active_role`.
- **Fix:** Switched to the same pattern the corpus test uses — reassign
  `_cli_state.GOVERNANCE_LOG = InMemoryGovernanceLog()` and reference
  `_cli_state.GOVERNANCE_LOG` directly for the seeding step. Both the
  seed AND the CLI now resolve the SAME singleton.
- **Files modified:** `tests/governance/test_governance_export_cli.py`
- **Commit:** 7035446 (Task 2 GREEN; fix folded into the GREEN commit)

### Process Notes

- No `git stash` was used. All worktree-safety guards
  (`worktree_branch_check`, `pre_commit_head_assertion`) passed at every commit.
- The D-16 grep-guard was NOT smoke-tested with a forbidden-import
  injection this plan (the 07-05a SUMMARY records that smoke for
  contest.py); the test went from skip to PASS cleanly the moment the
  retract files landed, which IS the contract the plan-acceptance
  criterion specifies ("the test auto-expands without an edit").

## Threat Surface Scan

The plan's `<threat_model>` enumerates T-7-10, T-7-11, T-7-12, T-7-01,
T-7-SC. Each disposition is realized:

| Threat ID                                            | Mitigation Realized                                                                              |
|------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| T-7-10 (cascade preview replay across state change)  | D-17 PreviewStale via underlying_state_hash; `test_preview_stale_refusal.py` covers the mutated + identical state cases. |
| T-7-11 (code review DRYs contest/supersede/retract)  | D-16 grep-guard test from 07-05a auto-flipped to FULL TRIAD (8/8 PASS). HIGH severity threat closed. |
| T-7-12 (direct rdflib import under governance/)      | Dep-leak guard passes 4/4 across the FULL governance/ tree minus shape_validation.py. `cli/export.py` routes via `serialize_log_as_turtle` in the exempt module. |
| T-7-01 (CLI bypasses role check)                     | D-19 `await authorize(...)` as first awaited step in all 3 new CLI files. `test_authorize_called_first.py` parametrize list extended to cover them (Rule 2). |
| T-7-SC (new pip dep)                                 | Accepted: zero new packages. |

No NEW security-relevant surface introduced beyond the plan's enumeration.

## Threat Flags

(None — every new surface introduced by 07-05b is enumerated in the plan's
`<threat_model>`.)

## Known Stubs

(None — `validate_retraction_shape` was the last `NotImplementedError`
stub in `governance/shape_validation.py`; its body shipped in this plan.
All 8 SHACL shapes are real-bodied.)

## Deferred Issues (out of scope; pre-existing)

The 5 pre-Phase-7 failures noted in 07-01 / 07-03 / 07-04a / 07-04b /
07-05a SUMMARYs persist (and were NOT touched by this plan):

- `tests/bench/test_gate5_digest.py` (Dagger digest reproducibility).
- `tests/test_bridge.py` (FileNotFoundError on `folio-enrich/backend`).
- `tests/test_ingestion.py` (5 cases — same folio-enrich missing path).
- 7 `test_*_api.py` files cannot collect due to missing `fastapi` dep.
- 1 pre-existing F401 lint warning in
  `tests/governance/test_promotion_status_kind.py` (07-04b — unused
  `AuthorityPosition` import; out of scope for 07-05b).

GOV-09 + GOV-10 + all web UI surfaces remain deferred post-Phase-14 per
D-01 / D-03 (Phase 7 ships CLI + library + thin HTTP API contract only).

## Checkpoint Status — Task 3 (human-verify)

Task 3 is a `checkpoint:human-verify` gate (the plan is marked
`autonomous: false`). The operator must manually invoke the
interactive `governance retract` flow + the `corpus init` interactive
flow per the plan's `<how-to-verify>` block and type `approved` (or
describe a UX issue).

Per the orchestrator's `<parallel_execution>` instructions, this SUMMARY
is committed BEFORE the human-verify checkpoint is reached. If the
operator approves, the plan is fully complete; if the operator finds a
UX issue, this SUMMARY will be amended in a follow-up commit.

**Tasks 1 + 2 are AUTOMATION-COMPLETE.** All 27 new tests pass + the
07-05a D-16 grep-guard auto-promoted to 8/8 PASS + the full repo runs
795/795 PASS (excluding pre-existing fastapi/folio-enrich failures).
The interactive flow has been smoke-tested in isolation via the
fixture corpora (the rich.table.Table renders correctly; the
click.confirm prompt text matches the spec verbatim).

## Self-Check

**Files created (existence verified via `[ -f X ] && echo FOUND`):**
- src/folio_insights/governance/retract.py — FOUND
- src/folio_insights/governance/shapes/retraction_shape.ttl — FOUND
- src/folio_insights/governance/cli/retract.py — FOUND
- src/folio_insights/governance/cli/export.py — FOUND
- src/folio_insights/governance/cli/show.py — FOUND
- tests/governance/fixtures/__init__.py — FOUND
- tests/governance/fixtures/cascade_corpora.py — FOUND
- tests/governance/test_cascade_preview_classification.py — FOUND
- tests/governance/test_preview_stale_refusal.py — FOUND
- tests/governance/test_retraction_shape.py — FOUND
- tests/governance/test_cascade_preview_shared_builder.py — FOUND
- tests/governance/test_governance_export_cli.py — FOUND

**Files modified (existence verified):**
- src/folio_insights/governance/cli/__init__.py — FOUND (3 new add_command + comments)
- src/folio_insights/governance/authorize.py — FOUND (_REVIEWER_ACTIONS extended)
- src/folio_insights/governance/shape_validation.py — FOUND (validate_retraction_shape body + serialize_log_as_turtle helper)
- tests/governance/test_authorize_called_first.py — FOUND (_COMMAND_FILES list extended)

**Commits (verified via `git log`):**
- 86131f6 — FOUND (RED Task 1: 3 test files + fixtures)
- 75482ce — FOUND (GREEN Task 1: retract.py + retraction_shape.ttl + shape_validation body)
- 7c5f8cc — FOUND (RED Task 2: AST + E2E test files)
- 7035446 — FOUND (GREEN Task 2: 3 CLI files + serialize helper + table extension + test fixes)

## Self-Check: PASSED (Tasks 1 + 2 automation; Task 3 awaiting human verify)
