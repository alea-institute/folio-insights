---
phase: 07-governance-model-3-1
plan: 05b
type: execute
wave: 6
depends_on: [07-01, 07-03, 07-04a, 07-04b, 07-05a]
files_modified:
  - src/folio_insights/governance/retract.py
  - src/folio_insights/governance/shape_validation.py
  - src/folio_insights/governance/shapes/retraction_shape.ttl
  - src/folio_insights/governance/authorize.py
  - src/folio_insights/governance/cli/__init__.py
  - src/folio_insights/governance/cli/retract.py
  - src/folio_insights/governance/cli/export.py
  - src/folio_insights/governance/cli/show.py
  - tests/governance/test_cascade_preview_classification.py
  - tests/governance/test_preview_stale_refusal.py
  - tests/governance/test_cascade_preview_shared_builder.py
  - tests/governance/test_retraction_shape.py
  - tests/governance/test_governance_export_cli.py
  - tests/governance/fixtures/__init__.py
  - tests/governance/fixtures/cascade_corpora.py
autonomous: false
requirements: [GOV-06]
deferred: [GOV-09, GOV-10]
tags: [governance, cascade-preview, retract, turtle-export, D-17, D-18, D-08]

must_haves:
  truths:
    - "[D-17] Retract CLI has 3 modes: interactive default (rich.prompt confirm + grouped table), `--preview` (write timestamped JSON, exit 0), `--apply <file>` (re-run preview, refuse with `PreviewStale` if `underlying_state_hash` differs)"
    - "[D-18] Dependents classification: `auto_rederive` (prefer_latest + supersession <= now), `aporetic` (no supersession + no reviewer marker), `review_needed` (any of contested/aporetic status, human-judgment reconciliation strategy, unresolved contest_votes[])"
    - "[D-08] Turtle export on-demand via `folio-insights governance export <corpus>` — reads InMemoryGovernanceLog (Phase 7) or SQLite ledger (Phase 13 wires backend) and emits Turtle. Phase 7 ships the CLI shape AND the actual Turtle writer for the in-memory backend. tests/governance/test_governance_export_cli.py is the dedicated CLI-end-to-end verification owner."
    - "[D-19] retract CLI calls authorize() as the first step; export CLI calls authorize() as the first step (read-only action but still passes through the central gate)"
  artifacts:
    - path: "src/folio_insights/governance/retract.py"
      provides: "RetractionEvent + build_cascade_preview + commit_cascade + classify_dependent (D-18) + PreviewStale + standalone module (D-16 third sibling)"
      contains: "build_cascade_preview"
    - path: "src/folio_insights/governance/shapes/retraction_shape.ttl"
      provides: "fi:RetractionShape — sh:property cascade_preview_hash"
      contains: "fi:RetractionShape"
    - path: "src/folio_insights/governance/cli/retract.py"
      provides: "governance retract subcommand with 3 modes (interactive / --preview / --apply); D-17 PreviewStale refusal on state change"
      contains: "PreviewStale"
    - path: "src/folio_insights/governance/cli/export.py"
      provides: "governance export — D-08 on-demand Turtle export"
      contains: "serialize_log_as_turtle"
    - path: "tests/governance/test_governance_export_cli.py"
      provides: "Dedicated CLI-end-to-end verification for D-08 (Issue #4 closure — owns its own file, no folding into 07-03)"
      contains: "governance export"
  key_links:
    - from: "src/folio_insights/governance/retract.py::build_cascade_preview"
      to: "src/folio_insights/governance/retract.py::commit_cascade"
      via: "shared preview-builder (D-17); only commit step differs across modes"
      pattern: "build_cascade_preview"
    - from: "src/folio_insights/governance/cli/retract.py"
      to: "src/folio_insights/governance/retract.py::commit_cascade"
      via: "--apply path re-runs build_cascade_preview and refuses with PreviewStale on state-change"
      pattern: "PreviewStale"
    - from: "src/folio_insights/governance/cli/export.py"
      to: "src/folio_insights/governance/shape_validation.py::serialize_log_as_turtle"
      via: "exempt rdflib seam — CLI itself does NOT import rdflib (D-04 boundary)"
      pattern: "serialize_log_as_turtle"
---

<objective>
Ship the GOV-06 retraction cascade preview (D-17 interactive + `--preview` + `--apply` with `PreviewStale` refusal), the D-18 dependents classifier, the D-08 Turtle export CLI (with dedicated end-to-end test file per Issue #4 closure), and the `governance log show` companion. Land the 3rd sibling (`retract.py`) of the D-16 three-way disambiguation — which auto-promotes the 07-05a grep-guard test from skip-mode to full enforcement.

Purpose: Closes GOV-06 + D-08. The D-16 grep-guard from 07-05a flips to full coverage the moment `retract.py` lands here. The export CLI plus dedicated test file closes Issue #4 by giving D-08 its own CLI-end-to-end verification owner — no handwaving about "fold into 07-03".

Output: `retract.py` (full cascade preview + commit + classifier + PreviewStale), `retraction_shape.ttl`, 3 CLI modules (retract, export, show), shared cascade fixture corpora, 5 governance tests + the dedicated `test_governance_export_cli.py`, and one human-verify checkpoint for the interactive flow.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/07-governance-model-3-1/07-CONTEXT.md
@.planning/phases/07-governance-model-3-1/07-RESEARCH.md
@.planning/phases/07-governance-model-3-1/07-PATTERNS.md
@.planning/phases/07-governance-model-3-1/07-04a-SUMMARY.md
@.planning/phases/07-governance-model-3-1/07-05a-SUMMARY.md
@src/folio_insights/governance/events.py
@src/folio_insights/governance/log.py
@src/folio_insights/governance/authorize.py

<interfaces>
From src/folio_insights/governance/events.py (07-01):
```python
class RetractionEvent(_BaseEvent):
    action: Literal["retract"] = "retract"
    shard_iri: str
    cascade_preview_hash: str  # commits the preview the operator confirmed (D-17)
```

CascadePreview Pydantic model (from RESEARCH lines 636-644 — immutable, hashable for PreviewStale):
```python
class CascadePreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    retracted_shard_iri: str
    corpus: str
    taken_at: datetime
    underlying_state_hash: str
    auto_rederive: list[str]
    aporetic: list[str]
    review_needed: list[str]
```

D-18 classification heuristic (locked verbatim; RESEARCH lines 1338-1353):
```python
def _classify_dependent(dep_attrs: dict) -> Literal["auto_rederive", "aporetic", "review_needed"]:
    has_succ = dep_attrs.get("supersession_available", False)
    strategy = dep_attrs.get("reconciliation_strategy")
    status = dep_attrs.get("epistemic_status")
    unresolved_votes = dep_attrs.get("unresolved_contest_count", 0)
    if status in {"contested", "aporetic"}: return "review_needed"
    if unresolved_votes > 0: return "review_needed"
    if strategy is not None and strategy != "prefer_latest": return "review_needed"
    if strategy == "prefer_latest" and has_succ: return "auto_rederive"
    return "aporetic"
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Ship `retract.py` (cascade preview builder + commit + classify_dependent + PreviewStale) + `retraction_shape.ttl` + retraction polarity test + D-18 classifier test + D-17 PreviewStale race test + cascade fixture corpora</name>
  <files>src/folio_insights/governance/retract.py, src/folio_insights/governance/shape_validation.py, src/folio_insights/governance/shapes/retraction_shape.ttl, tests/governance/test_cascade_preview_classification.py, tests/governance/test_preview_stale_refusal.py, tests/governance/test_retraction_shape.py, tests/governance/fixtures/__init__.py, tests/governance/fixtures/cascade_corpora.py</files>
  <read_first>
    - src/folio_insights/polysemy/distinguo.py (FULL — module structure analog for the 3rd D-16 sibling)
    - src/folio_insights/revision/content_edit.py:410-521 — `edit_shard_content()` transactional working-copy pattern (analog for `build_cascade_preview` → `commit_cascade`)
    - src/folio_insights/services/shacl_validator.py:81 — `generate_report()` grouped-result builder analog (OUTPUT-FORMATTING ONLY — do NOT add SHACL validation code to services/shacl_validator.py; use governance/shape_validation.py for per-event shape validators)
    - src/folio_insights/revision/store.py (ShardStore Protocol — consumed by build_cascade_preview to query dependents)
    - .planning/phases/07-governance-model-3-1/07-RESEARCH.md lines 624-680 (Pattern 4 — cascade preview builder); lines 1294-1353 (SPARQL CONSTRUCT + classifier); lines 846-865 (Pitfall 5 — PreviewStale race)
    - .planning/phases/07-governance-model-3-1/07-PATTERNS.md lines 452-528 (retract pattern)
    - .planning/phases/07-governance-model-3-1/07-CONTEXT.md `<decisions>` D-17, D-18
  </read_first>
  <behavior>
    - Test (cascade preview classification — D-18): table-driven; for each combination of `(supersession_available, reconciliation_strategy, epistemic_status, unresolved_contest_count)` -> expected bucket `{auto_rederive, aporetic, review_needed}`, assert `classify_dependent(...)` returns the expected bucket. >=8 rows.
    - Test (PreviewStale refusal — D-17): build a CascadePreview snapshot at t0 using the cascade fixture corpus; mutate the dependents set (add a new shard depending on the retracted one); call `commit_cascade(preview)` -> raises `PreviewStale("underlying state changed since preview taken at ...; re-run --preview")`.
    - Test (PreviewStale not raised on identical state): build preview; immediately call commit_cascade without mutation; succeeds (the `underlying_state_hash` matches).
    - Test (RetractionShape positive + negative): valid RetractionEvent conforms=True; missing `cascade_preview_hash` conforms=False.
  </behavior>
  <action>
    Create `src/folio_insights/governance/retract.py`:
    - Module docstring citing D-14/D-16/D-17/D-18 + PRD §3.1.4 + the standalone discipline ("does NOT import from contest.py or supersede.py — the D-16 grep-guard test from 07-05a auto-flips to full coverage once this module lands").
    - Re-export `RetractionEvent` from events.py.
    - `class CascadePreview(BaseModel)` per RESEARCH lines 636-644 — frozen, extra="forbid", fields: `retracted_shard_iri`, `corpus`, `taken_at`, `underlying_state_hash`, `auto_rederive: list[str]`, `aporetic: list[str]`, `review_needed: list[str]`.
    - `class PreviewStale(ValueError)`.
    - `def classify_dependent(dep_attrs: dict) -> Literal["auto_rederive", "aporetic", "review_needed"]:` per D-18 heuristic verbatim (RESEARCH lines 1338-1353).
    - `async def build_cascade_preview(retracted_iri: str, corpus: str, *, store: ShardStore, log: GovernanceLog) -> CascadePreview:` body:
      1. SPARQL CONSTRUCT (RESEARCH lines 1294-1333) is the Phase 13 implementation. Phase 7 simulates with a Python-level dependent walk over the in-memory ShardStore: iterate shards whose `depends_on_precedents` / `depends_on_definitions` / `depends_on_shards` include `retracted_iri`.
      2. For each dependent, extract `(supersession_available, reconciliation_strategy, epistemic_status, unresolved_contest_count)` from the shard envelope; call `classify_dependent(attrs)`.
      3. Compute `underlying_state_hash` over the set of `(dep_iri, epistemic_status, reconciliation_strategy, valid_time_end, superseded_by, log_position_at_signing)` tuples (RESEARCH Q6 recommendation; use JCS-canonical hash via `revision.content_edit.canonical_content_hash`).
      4. Return `CascadePreview(...)`.
    - `async def commit_cascade(preview: CascadePreview, *, store: ShardStore, log: GovernanceLog, signing_key, did: str) -> RetractionEvent:` body:
      1. Re-run `build_cascade_preview(preview.retracted_shard_iri, preview.corpus, store=store, log=log)`.
      2. Compare `current.underlying_state_hash` to `preview.underlying_state_hash`; if different, raise `PreviewStale(f"underlying state changed since preview taken at {preview.taken_at}; re-run --preview")`.
      3. Build `RetractionEvent(...)` + sign + `await log.append(event)`; return event.
    - `def validate_retraction(event: RetractionEvent) -> None:` defense-in-depth: shard_iri non-empty, cascade_preview_hash non-empty.

    Create `src/folio_insights/governance/shapes/retraction_shape.ttl`:
    - `fi:RetractionShape` with sh:property blocks on `fi:shardIri` (non-empty) and `fi:cascadePreviewHash` (non-empty, sh:datatype xsd:string).

    Edit `src/folio_insights/governance/shape_validation.py` `validate_retraction_shape` NotImplementedError stub -> real body.

    Create `tests/governance/fixtures/__init__.py` (empty marker) and `tests/governance/fixtures/cascade_corpora.py`:
    - Helper factories to seed an InMemoryShardStore + InMemoryGovernanceLog with a retraction-target shard and N dependents per classifier bucket (auto_rederive, aporetic, review_needed).
    - Reused by Task 2's interactive CLI test + the PreviewStale race test in this task.

    Create 3 test files per behavior list:
    - `tests/governance/test_cascade_preview_classification.py` — D-18 table-driven (≥8 rows)
    - `tests/governance/test_preview_stale_refusal.py` — D-17 race test (uses cascade_corpora fixture)
    - `tests/governance/test_retraction_shape.py` — positive + negative polarity pair
  </action>
  <verify>
    <automated>uv run pytest tests/governance/test_cascade_preview_classification.py tests/governance/test_preview_stale_refusal.py tests/governance/test_retraction_shape.py -x -q</automated>
  </verify>
  <acceptance_criteria>
    - `python -c "from folio_insights.governance.retract import build_cascade_preview, commit_cascade, classify_dependent, CascadePreview, PreviewStale, RetractionEvent; print('ok')"` prints `ok`.
    - `rdflib.Graph().parse("src/folio_insights/governance/shapes/retraction_shape.ttl", format="turtle")` succeeds.
    - `uv run pytest tests/governance/test_cascade_preview_classification.py -x` exits 0 with >=8 parametrized rows.
    - `uv run pytest tests/governance/test_preview_stale_refusal.py -x` exits 0; the test mutates the dependent set between preview and apply and asserts `PreviewStale` is raised with a message referencing `--preview`.
    - `grep -c "PreviewStale" src/folio_insights/governance/retract.py` >= 1.
    - `grep -c "from folio_insights.governance.contest\|from folio_insights.governance.supersede" src/folio_insights/governance/retract.py` returns 0 (D-16 third sibling discipline).
    - `grep -rn "import rdflib\|import aiosqlite\|import pyoxigraph" src/folio_insights/governance/retract.py | grep -v "^#"` returns empty (D-04 boundary).
    - After this task, the D-16 grep-guard test from 07-05a (`test_grep_guard_three_way_disambiguation.py`) flips from skip-retract to full-triad enforcement — running it locally MUST exit 0.
  </acceptance_criteria>
  <done>Retract library ships with CascadePreview + PreviewStale + classify_dependent (D-18 heuristic verbatim); the D-16 third sibling lands and auto-promotes the 07-05a grep-guard to full coverage. RetractionShape ships. Cascade fixture corpora are shared with Task 2.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Ship `cli/retract.py` (3 modes) + `cli/export.py` (D-08 Turtle export with `serialize_log_as_turtle` helper) + `cli/show.py` (governance log show) + shared-builder AST test + dedicated test_governance_export_cli.py (Issue #4 owner)</name>
  <files>src/folio_insights/governance/cli/__init__.py, src/folio_insights/governance/cli/retract.py, src/folio_insights/governance/cli/export.py, src/folio_insights/governance/cli/show.py, src/folio_insights/governance/shape_validation.py, tests/governance/test_cascade_preview_shared_builder.py, tests/governance/test_governance_export_cli.py</files>
  <read_first>
    - src/folio_insights/governance/retract.py (from Task 1 — CascadePreview, commit_cascade, PreviewStale)
    - src/folio_insights/governance/cli/promote.py (from 07-04b — the canonical authorize -> validate -> sign -> append CLI pattern)
    - src/folio_insights/polysemy/cli.py — rich.prompt + rich.table interactive analog for the retract CLI default mode
    - src/folio_insights/identity/cli.py:271-279 — `click.confirm` gate pattern for the post-preview confirmation
    - src/folio_insights/cli.py:280-495 — `export` command analog for the Turtle export
    - src/folio_insights/services/shacl_validator.py:81 — `generate_report()` grouped-result builder analog (OUTPUT-FORMATTING ONLY — do NOT add SHACL validation code to services/shacl_validator.py; use governance/shape_validation.py for per-event shape validators)
    - .planning/phases/07-governance-model-3-1/07-PATTERNS.md lines 459-528 (retract CLI pattern + governance_export pattern)
    - .planning/phases/07-governance-model-3-1/07-CONTEXT.md `<decisions>` D-08, D-17, D-18, D-19
  </read_first>
  <behavior>
    - Test (cascade preview shared builder — D-17): AST-walk of `cli/retract.py` asserts all three branches (interactive, `--preview`, `--apply`) invoke `build_cascade_preview(...)`. Mirror test_authorize_called_first.py from 07-04b.
    - Test (governance export Turtle round-trip): seed an InMemoryGovernanceLog with 3 events (via cascade_corpora fixture or a minimal inline seed); `runner.invoke(cli, ["governance", "export", "test-corpus", "-o", str(tmp_path / "g.ttl")])` exits 0; `tmp_path / "g.ttl"` exists and parses via `rdflib.Graph().parse(format="turtle")` to >=3 `prov:Activity` instances with `prov:wasAttributedTo` predicates.
    - Test (export CLI calls authorize first): AST-walk asserts `await authorize(signer_did, "export", corpus, log=log)` precedes any `await log.iter_events(...)` call (read-only but still gated per D-19).
  </behavior>
  <action>
    Extend `src/folio_insights/governance/cli/__init__.py` (from 07-05a) to register the 3 new subcommands defined below.

    Create `src/folio_insights/governance/cli/retract.py` per PATTERNS.md lines 459-477 + D-17:
    - `@governance_group.command("retract")` with `shard_iri` argument; `--preview` (preview_only flag); `--apply` (apply_path with `click.Path(exists=True, ...)`); `--output` (preview output path); `--corpus`; `--key-path`; `--yes`.
    - Mutually-exclusive: `--preview` and `--apply` cannot both be set.
    - Body:
      - **First step (D-19)**: `await authorize(signer_did, "retract", corpus, log=log)`.
      - **--apply path**: load `CascadePreview.model_validate_json(Path(apply_path).read_text())`; call `commit_cascade(preview, ...)`; on PreviewStale, print verbatim error to stderr + exit non-zero; on success, emit the RetractionEvent JSON.
      - **--preview path**: call `build_cascade_preview(...)`; default output path `retract-preview-<sanitized_iri>-<ts>.json`; write `preview.model_dump_json(indent=2)`; exit 0 WITHOUT committing.
      - **Default (interactive) path**: call `build_cascade_preview(...)`; render the grouped table via `rich.table.Table` (3 columns: `auto_rederive`, `aporetic`, `review_needed`); `click.confirm(f"Confirm retraction of N shards (auto_rederive: {len(p.auto_rederive)}, aporetic: {len(p.aporetic)}, review_needed: {len(p.review_needed)})?", default=False)`; on yes, call `commit_cascade(preview, ...)`; on no, exit 0 without committing.

    Create `src/folio_insights/governance/cli/export.py` per PATTERNS.md lines 514-528 + D-08:
    - `@governance_group.command("export")` with `corpus_name` argument, `--output / -o` (default `./governance.ttl`), `--key-path`.
    - **D-19 first step**: `await authorize(signer_did, "export", corpus_name, log=log)`. Add `"export"` to the action-permission table in `authorize.py` (extends 07-04a's table) — reviewers + arbiters + corpus_admins may export; extractors may not. This is a small retroactive edit acceptable here.
    - Body: iterate `log.iter_events(corpus_name)`; pass the event list to `serialize_log_as_turtle(events)` (the boundary-respecting wrapper inside `shape_validation.py`); write result to output path; emit confirmation.
    - **D-04 boundary**: the CLI does NOT import rdflib. Instead, add a tiny serializer inside `src/folio_insights/governance/shape_validation.py` (the lone exempt module) called `def serialize_log_as_turtle(events: list[GovernanceEvent]) -> str:` that does the rdflib graph construction + serialization (`<event_uri> a prov:Activity ; prov:wasAttributedTo <signer_did> ; fi:position N ; fi:action "<action_string>" ; fi:signedAt "<iso_datetime>"^^xsd:dateTime`). The CLI calls this function — keeps the boundary intact.

    Create `src/folio_insights/governance/cli/show.py`:
    - `@governance_group.command("show")` companion that prints a paginated view of events for a corpus (mirror `cli.py` show-style command). `--corpus`, `--limit` (default 50), `--key-path`.
    - **D-19 first step**: `await authorize(signer_did, "show", corpus, log=log)` (extend action-permission table similarly to export).
    - Body: iterate `log.iter_events(corpus)`; for each event, render `position | action | signer_did | signed_at | shard_iri` via `rich.table.Table`.

    Create `tests/governance/test_cascade_preview_shared_builder.py` — AST-walk `cli/retract.py` asserting all 3 branches call `build_cascade_preview`. Mirror test_authorize_called_first.py from 07-04b.

    Create `tests/governance/test_governance_export_cli.py` (Issue #4 dedicated owner):
    - Seed an InMemoryGovernanceLog with 3 events via `tests/governance/fixtures/cascade_corpora.py` (Task 1) or minimal inline seed.
    - `runner.invoke(cli, ["governance", "export", "test-corpus", "-o", str(tmp_path / "g.ttl"), "--key-path", str(test_key)])` exits 0.
    - Assert the file exists; `rdflib.Graph().parse(str(tmp_path / "g.ttl"), format="turtle")` succeeds; query for `prov:Activity` triples and assert count >= 3; query for `prov:wasAttributedTo` and assert each Activity has a signer DID.
    - Negative case: unauthorized DID (no role) → `runner.invoke` exits non-zero with stderr message about authorize Deny.
    - AST-test: source-scan `governance/cli/export.py` to assert `await authorize(...)` precedes any `log.iter_events(...)` call.
  </action>
  <verify>
    <automated>uv run pytest tests/governance/test_cascade_preview_shared_builder.py tests/governance/test_governance_export_cli.py -x -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run folio-insights governance retract --help` exits 0; output mentions `--preview`, `--apply`, and the 3 modes (interactive default + preview dry-run + apply re-run).
    - `uv run folio-insights governance export --help` exits 0; mentions on-demand Turtle export per D-08.
    - `uv run folio-insights governance show --help` exits 0.
    - `uv run pytest tests/governance/test_cascade_preview_shared_builder.py -x` exits 0; AST-walk proves all 3 retract CLI branches invoke `build_cascade_preview`.
    - `uv run pytest tests/governance/test_governance_export_cli.py -x` exits 0 with at least the positive round-trip + negative unauthorized + AST-first-step tests.
    - `grep -rn "import rdflib\|import aiosqlite\|import pyoxigraph" src/folio_insights/governance/cli/ | grep -v "^#"` returns empty (rdflib used ONLY via `shape_validation.py::serialize_log_as_turtle`).
    - `grep -c "def serialize_log_as_turtle" src/folio_insights/governance/shape_validation.py` >= 1.
    - `uv run pytest tests/governance -x -q` exits 0 cumulatively across all of 07-01/07-03/07-04a/07-04b/07-05a/07-05b.
    - Behavior: a 3-event InMemoryGovernanceLog emits a valid Turtle file via `folio-insights governance export <corpus> -o <path>` that parses back to >=3 prov:Activity triples.
  </acceptance_criteria>
  <done>Retract CLI ships with 3 modes (D-17); Turtle export CLI ships with the boundary-respecting `serialize_log_as_turtle` helper inside `shape_validation.py`; `governance show` companion ships. `test_governance_export_cli.py` owns the D-08 CLI-end-to-end verification per Issue #4. All Phase 7 governance + corpus CLI surfaces complete.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 3: Human-verify the interactive `governance retract` flow + the `corpus init` interactive flow</name>
  <files>n/a — human-verify checkpoint (no file edits)</files>
  <action>Pause execution. The operator manually invokes the interactive CLI flows below and visually confirms the rich.table.Table grouped table renders with 3 buckets, the click.confirm prompt text matches spec verbatim, and both branches (y/n) behave correctly. Do NOT proceed to plan completion until the operator types `approved` or describes the issue.</action>
  <what-built>
    - `folio-insights governance retract <shard_iri>` interactive default mode renders a grouped table (3 columns: auto_rederive, aporetic, review_needed) via rich.table.Table and prompts `Confirm retraction of N shards (auto_rederive: A, aporetic: B, review_needed: C)? [y/N]` via click.confirm.
    - `folio-insights corpus init <corpus> --admin-did did:fi:test --key-path <test-key>` writes a self-signed genesis RoleAssertion at row 0 and emits the JSON (07-04b ships this; verify here for visual confidence).
  </what-built>
  <how-to-verify>
    1. **Set up a test key** (one-time): `uv run folio-insights did generate --key-path /tmp/test-fi-key.pem`. Note the DID it derives.
    2. **Corpus init**: run `uv run folio-insights corpus init test-corpus --admin-did <derived-did> --key-path /tmp/test-fi-key.pem`. Expected: JSON output with `"position": 0`, `"role": "corpus_admin"`, `"action": "role_assertion"`, and `"signature"."did" == subject_did` (self-signed). Exit code 0.
    3. **Cascade preview interactive flow**: seed via REPL using `tests/governance/fixtures/cascade_corpora.py`:
       ```bash
       uv run python -c "<seed code referencing cascade_corpora factories>"
       ```
       Then run `uv run folio-insights governance retract fi:shard:<test-iri> --corpus test-corpus --key-path /tmp/test-fi-key.pem`.
    4. **Verify the table renders**: visually confirm the 3 columns appear, with dependent IRIs listed under each bucket per the D-18 classifier.
    5. **Verify the prompt**: confirm the prompt text matches `Confirm retraction of N shards (auto_rederive: A, aporetic: B, review_needed: C)?`. Press `n` first — expected: command exits 0 with no commit; verify by re-querying `await log.iter_events("test-corpus")` (in REPL) — no RetractionEvent appended.
    6. **Re-run the retract command** and press `y`. Expected: a RetractionEvent is appended; the output JSON shows the event with monotonic position; cascade_preview_hash matches the hash of the preview.
    7. **Cleanup**: `rm /tmp/test-fi-key.pem`.
  </how-to-verify>
  <verify>
    <human-check>Operator visually confirmed the interactive table renders with 3 buckets, the prompt text matches verbatim, and both `y` and `n` branches behave correctly. `corpus init` JSON output matches D-10 genesis carve-out schema.</human-check>
  </verify>
  <done>Operator typed `approved` after running both interactive flows; OR documented a UX issue for revision before this plan's SUMMARY.md is written.</done>
  <resume-signal>Type `approved` if the corpus init JSON matches and the retract interactive flow renders the table + prompts + commits/aborts correctly. Describe any UX issues otherwise.</resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| `commit_cascade(preview)` (frozen preview JSON across CLI invocations) -> `build_cascade_preview()` re-run | D-17 `PreviewStale` refusal binds the commit to the same underlying state the operator confirmed. |
| `governance export` CLI -> `rdflib.Graph` via `governance/shape_validation.py::serialize_log_as_turtle` (the lone exempt module) | D-04 boundary preserved: the CLI itself does NOT import rdflib; the serializer wrapper inside the exempt module handles RDF construction. |
| Operator → `governance export` / `governance show` (read paths) | D-19 first-step authorize() applies even to read paths; extends 07-04a's action-permission table with `export` + `show`. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-7-10 | Tampering | Cascade preview replay across state change | mitigate | D-17 `commit_cascade` re-runs `build_cascade_preview` and compares `underlying_state_hash`; raises `PreviewStale`. test_preview_stale_refusal.py simulates two racing operators. |
| T-7-11 | Tampering | Code review tries to DRY contest/supersede/retract into a shared `disagree()` helper (now that retract.py ships) | mitigate | The 07-05a grep-guard test auto-promotes to full coverage when this plan's `retract.py` lands. **HIGH severity**. |
| T-7-12 | Tampering | direct rdflib import in retract.py / cli/retract.py / cli/export.py | mitigate | dep-leak guard (07-01) covers all new files; `governance export` calls `shape_validation.serialize_log_as_turtle` (the exempt module) instead of importing rdflib directly. |
| T-7-01 | Elevation | retract / export / show CLIs bypass role check | mitigate | D-19 `await authorize(...)` as first step (test_authorize_called_first.py covers all governance CLI commands including the new retract/export/show in this plan; extend the source-scan list). |
| T-7-SC | Tampering | new pip dep | accept | Zero new packages this plan. |
</threat_model>

<verification>
- `uv run pytest tests/governance -x -q` exits 0 cumulatively across all Phase 7 plans (07-01 + 07-03 + 07-04a + 07-04b + 07-05a + 07-05b).
- `uv run pytest tests/ -q` exits 0 (no regression).
- `uv run folio-insights governance --help` lists 8 subcommands: `promote`, `assert-role`, `revoke-role`, `contest`, `supersede`, `resolve-contest`, `retract`, `export`, `show` (9 actually).
- `uv run folio-insights corpus --help` lists `init`.
- `uv run python -m folio_insights.rfc.lint .planning/rfcs/` exits 0 (no regression from 07-02).
- `grep -rn "import aiosqlite\|import rdflib\|import pyoxigraph\|import oxrdflib" src/folio_insights/governance/ | grep -v shape_validation.py | grep -v "^#"` returns empty (D-04 boundary intact across all 8 SHACL shapes + CLI surface).
- `ls src/folio_insights/governance/shapes/*.ttl | wc -l` returns 8 (governance_log + role_assertion + role_revocation + promotion + contest + contest_resolution + supersession + retraction).
- `ruff check src/folio_insights/governance/ src/folio_insights/rfc/` exits 0.
- D-16 grep-guard test (`tests/governance/test_grep_guard_three_way_disambiguation.py` from 07-05a) flips from skip-retract to full-triad and exits 0.
- Human-verify checkpoint (Task 3) approved.
</verification>

<success_criteria>
- GOV-06 satisfied: cascade preview builder + 3 CLI modes (interactive / `--preview` / `--apply`); D-17 PreviewStale refusal; D-18 classifier locked.
- D-08 satisfied: `governance export` CLI emits Turtle on-demand from in-memory backend with dedicated `test_governance_export_cli.py` owner (Issue #4 closure).
- D-16 closure: third sibling (`retract.py`) lands and 07-05a's grep-guard auto-flips to full triad enforcement.
- All 8 SHACL TTL shapes ship total across Phase 7.
- All 6 STAYS criteria from CONTEXT.md amended exit bar are now met across the 7 plans.
- D-04 boundary intact across the full `governance/` package.
- Human-verify checkpoint confirms interactive flows render and prompt correctly.
</success_criteria>

<output>
Create `.planning/phases/07-governance-model-3-1/07-05b-SUMMARY.md` when done with: files created (1 module + 1 TTL + 3 CLI + 1 fixture + 5 test files), test counts (cumulative across all 7 Phase 7 plans), enumeration of the 8 SHACL TTL files, enumeration of the 9 governance CLI subcommands + 1 corpus subcommand, the D-18 classifier truth table, and a sample retract-preview JSON (anonymized).
</output>
</content>
</invoke>