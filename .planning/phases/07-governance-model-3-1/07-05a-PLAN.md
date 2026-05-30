---
phase: 07-governance-model-3-1
plan: 05a
type: execute
wave: 5
depends_on: [07-01, 07-03, 07-04a, 07-04b]
files_modified:
  - src/folio_insights/governance/contest.py
  - src/folio_insights/governance/supersede.py
  - src/folio_insights/governance/resolve_contest.py
  - src/folio_insights/governance/shape_validation.py
  - src/folio_insights/governance/shapes/contest_shape.ttl
  - src/folio_insights/governance/shapes/contest_resolution_shape.ttl
  - src/folio_insights/governance/shapes/supersession_shape.ttl
  - src/folio_insights/governance/cli/__init__.py
  - src/folio_insights/governance/cli/contest.py
  - src/folio_insights/governance/cli/supersede.py
  - src/folio_insights/governance/cli/resolve_contest.py
  - tests/governance/test_grep_guard_three_way_disambiguation.py
  - tests/governance/test_contested_state_records_votes.py
  - tests/governance/test_arbiter_can_resolve_contest.py
  - tests/governance/test_distinguo_resolution.py
  - tests/governance/test_aporetic_acceptance.py
  - tests/governance/test_no_majority_vote_resolution.py
  - tests/governance/test_contest_shape.py
  - tests/governance/test_contest_resolution_shape.py
  - tests/governance/test_supersession_shape.py
  - tests/governance/test_cli_three_way_distinct.py
  - tests/governance/test_cli_three_way_help_distinct.py
  - tests/governance/property/test_active_roles_stability.py
autonomous: true
requirements: [GOV-04, GOV-05]
deferred: [GOV-09, GOV-10]
tags: [governance, three-way-disambiguation, grep-guard, GOV-04, GOV-05]

must_haves:
  truths:
    - "[D-14/D-15] CLI shape `folio-insights governance {contest|supersede|resolve-contest}` — sibling subcommands; each in its own Click command module under `governance/cli/`"
    - "[D-16] Three modules `src/folio_insights/governance/{contest,supersede,retract}.py` are structurally distinct: (a) own Pydantic event class, (b) own SHACL shape, (c) own validator function — `AttestedSignature` is the ONLY shared primitive. (This plan ships contest + supersede; retract ships in 07-05b but the grep-guard test is owned here as the quality_gate requires per the revision instructions.)"
    - "[D-16] Grep-guard regression test fails CI if (a) any of the three modules imports from another, (b) any base class beyond the GovernanceEvent / _BaseEvent umbrella is shared, (c) the three Click commands share an implementation function. Test is its OWN task per the quality_gate convention."
    - "[GOV-05] Contest resolution paths: arbiter / distinguo / aporetic — 3 explicit paths; NO majority-vote resolution path exists; the `ContestResolutionEvent.resolution_path` Literal has exactly 3 values"
  artifacts:
    - path: "src/folio_insights/governance/contest.py"
      provides: "ContestEvent + validate_contest_shape + standalone module (no cross-imports per D-16)"
      contains: "class ContestEvent"
    - path: "src/folio_insights/governance/supersede.py"
      provides: "SupersessionEvent + validate_supersession_shape + standalone module"
      contains: "class SupersessionEvent"
    - path: "src/folio_insights/governance/resolve_contest.py"
      provides: "ContestResolutionEvent — 3 paths {arbiter, distinguo, aporetic}; no majority-vote"
      contains: "resolution_path"
    - path: "tests/governance/test_grep_guard_three_way_disambiguation.py"
      provides: "AST + source-scan regression test enforcing D-16 (no cross-imports, no shared base class, no shared Click impl function). OWN task per quality_gate."
      contains: "THREE_WAY"
    - path: "tests/governance/test_no_majority_vote_resolution.py"
      provides: "Explicit-rejection test for any 4th resolution path beyond {arbiter,distinguo,aporetic}"
      contains: "majority"
  key_links:
    - from: "src/folio_insights/governance/cli/{contest,supersede,resolve_contest}.py"
      to: "src/folio_insights/governance/{contest,supersede,resolve_contest}.py"
      via: "Each Click command imports ONLY its own module's event class + validator"
      pattern: "from folio_insights\\.governance\\.(contest|supersede|resolve_contest) import"
    - from: "src/folio_insights/governance/cli/{contest,supersede,resolve_contest}.py"
      to: "src/folio_insights/governance/authorize.py::authorize"
      via: "D-19 first step"
      pattern: "await authorize"
---

<objective>
Ship the GOV-04 three-way disambiguation (contest / supersede as two of the three structurally-distinct modules; retract ships in 07-05b) + the GOV-05 contest workflow (3 resolution paths, no majority-vote). The D-16 grep-guard regression test is the code-review gate that fails CI if anyone refactors toward DRY across the three modules — it lives in its OWN task per the quality_gate convention (revision Issue #6 split instruction).

Purpose: Closes the philosophical-discipline heart of Phase 7 — the PRD §21.8 / §21.9 / GOV-04 commitment that reviewers pick the right mechanism (contest vs supersede vs retract), made software-enforceable by refusing to ship a unified `disagreement()` helper. The grep-guard test references all three modules including `retract.py` (07-05b ships it; the test gates execute-time once 07-05b lands).

Output: 3 governance modules (contest, supersede, resolve_contest), 3 SHACL TTL shapes, 3 CLI command modules, the D-16 grep-guard regression test in its own task, the GOV-05 no-majority-vote test, per-shape polarity tests, CLI distinctness tests, and the Hypothesis active-roles stability property test.
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
@.planning/phases/07-governance-model-3-1/07-04b-SUMMARY.md
@src/folio_insights/governance/events.py
@src/folio_insights/governance/authorize.py
@src/folio_insights/governance/cli/__init__.py

<interfaces>
From src/folio_insights/governance/events.py (07-01 — the 3 event classes this plan validates):
```python
class ContestEvent(_BaseEvent):
    action: Literal["contest"] = "contest"
    shard_iri: str
    voter_did: str
    position_text: str

class SupersessionEvent(_BaseEvent):
    action: Literal["supersede"] = "supersede"
    old_shard_iri: str
    new_shard_iri: str

class ContestResolutionEvent(_BaseEvent):
    action: Literal["resolve_contest"] = "resolve_contest"
    shard_iri: str
    resolution_path: Literal["arbiter", "distinguo", "aporetic"]  # GOV-05 — no majority-vote
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Ship `contest.py` + `supersede.py` + `resolve_contest.py` + 3 SHACL shapes + 3 CLI commands + per-module workflow tests + per-shape polarity tests + CLI distinctness tests + GOV-05 no-majority-vote test + Hypothesis active-roles stability</name>
  <files>src/folio_insights/governance/contest.py, src/folio_insights/governance/supersede.py, src/folio_insights/governance/resolve_contest.py, src/folio_insights/governance/shape_validation.py, src/folio_insights/governance/shapes/contest_shape.ttl, src/folio_insights/governance/shapes/contest_resolution_shape.ttl, src/folio_insights/governance/shapes/supersession_shape.ttl, src/folio_insights/governance/cli/__init__.py, src/folio_insights/governance/cli/contest.py, src/folio_insights/governance/cli/supersede.py, src/folio_insights/governance/cli/resolve_contest.py, tests/governance/test_contested_state_records_votes.py, tests/governance/test_arbiter_can_resolve_contest.py, tests/governance/test_distinguo_resolution.py, tests/governance/test_aporetic_acceptance.py, tests/governance/test_no_majority_vote_resolution.py, tests/governance/test_contest_shape.py, tests/governance/test_contest_resolution_shape.py, tests/governance/test_supersession_shape.py, tests/governance/test_cli_three_way_distinct.py, tests/governance/test_cli_three_way_help_distinct.py, tests/governance/property/test_active_roles_stability.py</files>
  <read_first>
    - src/folio_insights/governance/events.py (from 07-01 — ContestEvent, SupersessionEvent, ContestResolutionEvent)
    - src/folio_insights/polysemy/distinguo.py (FULL — THE primary analog for self-contained event + validate_*_shape() module; line 99 is the canonical validator surface)
    - src/folio_insights/governance/cli/promote.py (from 07-04b — the canonical authorize -> validate -> sign -> append CLI command structure to MIRROR but NOT share)
    - src/folio_insights/revision/content_edit_shape.ttl (Phase 5 SHACL polarity precedent)
    - .planning/phases/07-governance-model-3-1/07-RESEARCH.md lines 280-318 (three-way modules pattern); lines 996-1013 (PromotionShape — model for per-event shapes)
    - .planning/phases/07-governance-model-3-1/07-PATTERNS.md lines 282-318 (three-way modules pattern assignments); lines 596-680 (test patterns)
    - .planning/phases/07-governance-model-3-1/07-CONTEXT.md `<decisions>` D-14, D-15, D-16; GOV-05 explicit-rejection (no majority-vote)
  </read_first>
  <behavior>
    - Test (contest workflow — contest_votes records): append a ContestEvent for shard `fi:shard:abc` with voter_did `did:fi:bob` and position_text `"I disagree because..."`; query the governance log; assert the contest is recorded with all fields preserved.
    - Test (arbiter resolution): a ContestResolutionEvent with `resolution_path="arbiter"` is signed by a DID holding `arbiter` role; `governance_log.append()` succeeds.
    - Test (distinguo resolution): a ContestResolutionEvent with `resolution_path="distinguo"` is appended; resolver path valid.
    - Test (aporetic resolution): a ContestResolutionEvent with `resolution_path="aporetic"` is appended; shard remains contested-but-resolved-as-aporetic in the log audit.
    - Test (NO majority-vote — explicit rejection per GOV-05): `ContestResolutionEvent(resolution_path="majority")` raises Pydantic ValidationError (Literal has exactly 3 values); also assert via `get_args(...)` that the resolution_path Literal contains EXACTLY `{"arbiter", "distinguo", "aporetic"}`.
    - Test (Three-way CLI help — distinct): `runner.invoke(cli, ["governance", "contest", "--help"]).output` ≠ supersede help ≠ resolve-contest help; each `--help` text references its distinct PRD section.
    - Test (Three-way CLI surface — distinct commands): `runner.invoke(cli, ["governance", "--help"]).output` lists `contest`, `supersede`, `resolve-contest` as separate subcommands.
    - Test (per-shape positive + negative polarity for each of contest_shape, contest_resolution_shape, supersession_shape).
    - Test (Hypothesis property — active_roles stability): with N random interleavings of role assertions + revocations at random timestamps, `active_roles_at(corpus, asof)` returns the same dict regardless of insertion order within the same `asof` window (set semantics + chronological scan stable). max_examples=500.
  </behavior>
  <action>
    Create `src/folio_insights/governance/contest.py`:
    - Module docstring citing D-14/D-16/PRD §21.8; state "imports ONLY from governance.events, governance.shape_validation, and shared identity primitives — NEVER from supersede.py or retract.py".
    - Re-export `ContestEvent` from events.py.
    - `def validate_contest(event: ContestEvent) -> None:` defense-in-depth check: `event.shard_iri` non-empty, `event.voter_did` starts with `"did:"`, `event.position_text` non-empty. Raises ValueError.

    Create `src/folio_insights/governance/supersede.py`:
    - Standalone discipline; cites PRD §21.9 (supersession ≠ retraction).
    - Re-export `SupersessionEvent`.
    - `def validate_supersession(event: SupersessionEvent, *, store: ShardStore) -> None:` body: assert both `old_shard_iri` and `new_shard_iri` resolve in store; assert they differ; raise ValueError.

    Create `src/folio_insights/governance/resolve_contest.py`:
    - Standalone discipline; cites PRD §3.1.3 + GOV-05 no-majority-vote explicitly.
    - Re-export `ContestResolutionEvent`.
    - `def validate_contest_resolution(event: ContestResolutionEvent, *, log: GovernanceLog) -> None:` body: assert `event.shard_iri` has been contested (an earlier ContestEvent with the same shard_iri exists in the log); assert `event.resolution_path` is one of the 3 Literal values (Pydantic enforces but defense-in-depth check raises if somehow bypassed).

    Create 3 SHACL TTL shapes mirroring `revision/content_edit_shape.ttl` header pattern:
    - `governance/shapes/contest_shape.ttl` — `fi:ContestShape` with `sh:property` blocks on `fi:shardIri` (non-empty), `fi:voterDid` (datatype xsd:string, starts with "did:"), `fi:positionText` (non-empty).
    - `governance/shapes/contest_resolution_shape.ttl` — `fi:ContestResolutionShape` with `sh:property [ sh:path fi:resolutionPath ; sh:in ("arbiter" "distinguo" "aporetic") ; sh:minCount 1 ; sh:maxCount 1 ]`. Header comment block: `# GOV-05: NO majority-vote — locked by 3-value sh:in constraint. Adding a 4th value requires an ADR.`
    - `governance/shapes/supersession_shape.ttl` — `fi:SupersessionShape` with `sh:property` blocks on `fi:oldShardIri` + `fi:newShardIri` (both non-empty, different).

    Edit `src/folio_insights/governance/shape_validation.py` to replace the NotImplementedError stubs for `validate_contest_shape`, `validate_contest_resolution_shape`, `validate_supersession_shape` with real bodies (mirror `validate_governance_log_shape` body pattern from 07-03).

    Extend `src/folio_insights/governance/cli/__init__.py` (from 07-04b) to register the 3 new subcommands defined below.

    Create 3 CLI command modules under `governance/cli/` — EACH must be standalone (D-16 grep-guard — Task 2 enforces):
    - `governance/cli/contest.py` — `@governance_group.command("contest")` with `shard_iri`, `--position-text`, `--corpus`, `--key-path`, `--yes`. Body: `await authorize(signer_did, "contest", corpus, log=log)` first; build ContestEvent; sign; append; emit. Help text: `"Record a contest on a shard (PRD §21.8 — distinct from supersession and retraction)."`
    - `governance/cli/supersede.py` — `@governance_group.command("supersede")` with `old_shard_iri`, `new_shard_iri`, `--corpus`, `--key-path`, `--yes`. Body: `await authorize(signer_did, "supersede", corpus, log=log)`; `validate_supersession(event, store=store)`; sign; append; emit. Help text: `"Supersede an old shard with a new shard (PRD §21.9 — distinct from retraction; valid-time semantics)."`
    - `governance/cli/resolve_contest.py` — `@governance_group.command("resolve-contest")` with `shard_iri`, `--path` (Click Choice over 3-Literal), `--corpus`, `--key-path`, `--yes`. Body: `await authorize(signer_did, "resolve_contest", corpus, log=log)` (requires arbiter role per D-19 action-permission table); validate; sign; append; emit. Help text: `"Resolve a contested shard (GOV-05 — 3 paths: arbiter, distinguo, aporetic; NO majority-vote)."`

    Create `tests/governance/test_no_majority_vote_resolution.py`:
    - Test 1: `from folio_insights.governance.resolve_contest import ContestResolutionEvent; from typing import get_args; rp_literal = ContestResolutionEvent.model_fields["resolution_path"].annotation; assert set(get_args(rp_literal)) == {"arbiter", "distinguo", "aporetic"}`.
    - Test 2: Pydantic ValidationError when constructing `ContestResolutionEvent(action="resolve_contest", corpus="c1", signature=<sig>, shard_iri="fi:shard:abc", resolution_path="majority")`.
    - Test 3: `validate_contest_resolution_shape(<event_with_bogus_path>)` returns `conforms=False` (SHACL belt also refuses).

    Create the other 8 test files per behavior list:
    - `test_contested_state_records_votes.py`, `test_arbiter_can_resolve_contest.py`, `test_distinguo_resolution.py`, `test_aporetic_acceptance.py` — contest + 3 resolution paths
    - `test_contest_shape.py`, `test_contest_resolution_shape.py`, `test_supersession_shape.py` — positive + negative SHACL polarity pairs
    - `test_cli_three_way_distinct.py` — `runner.invoke(cli, ["governance", "--help"])` lists 3 subcommands
    - `test_cli_three_way_help_distinct.py` per PATTERNS.md lines 663-680 — each subcommand's --help text references its distinct PRD section
    - `tests/governance/property/test_active_roles_stability.py` — Hypothesis property test (max_examples=500)
  </action>
  <verify>
    <automated>uv run pytest tests/governance/test_no_majority_vote_resolution.py tests/governance/test_contest_shape.py tests/governance/test_contest_resolution_shape.py tests/governance/test_supersession_shape.py tests/governance/test_cli_three_way_distinct.py tests/governance/test_cli_three_way_help_distinct.py tests/governance/test_contested_state_records_votes.py tests/governance/test_arbiter_can_resolve_contest.py tests/governance/test_distinguo_resolution.py tests/governance/test_aporetic_acceptance.py tests/governance/property/test_active_roles_stability.py -x -q</automated>
  </verify>
  <acceptance_criteria>
    - `python -c "from folio_insights.governance.contest import validate_contest; from folio_insights.governance.supersede import validate_supersession; from folio_insights.governance.resolve_contest import validate_contest_resolution; print('ok')"` prints `ok`.
    - `uv run folio-insights governance --help` lists `contest`, `supersede`, `resolve-contest` as subcommands (plus `promote`, `assert-role`, `revoke-role` from 07-04b).
    - `uv run folio-insights governance contest --help`, `governance supersede --help`, `governance resolve-contest --help` all exit 0 and each --help text mentions a distinct PRD section.
    - `uv run pytest tests/governance/test_no_majority_vote_resolution.py -x` exits 0 — confirms the Literal has exactly 3 values.
    - `uv run pytest tests/governance/test_contest_shape.py tests/governance/test_contest_resolution_shape.py tests/governance/test_supersession_shape.py -x` exits 0.
    - `uv run pytest tests/governance/property/test_active_roles_stability.py -x` exits 0 with Hypothesis max_examples=500.
    - `grep -c "from folio_insights.governance.supersede\|import folio_insights.governance.supersede" src/folio_insights/governance/contest.py` returns 0 (no cross-import).
    - `grep -c "from folio_insights.governance.contest\|import folio_insights.governance.contest" src/folio_insights/governance/supersede.py` returns 0.
    - `grep -c "majority" src/folio_insights/governance/shapes/contest_resolution_shape.ttl` returns 0 — locked sh:in constraint has only the 3 values.
    - Behavior: a `ContestResolutionEvent(resolution_path="majority", ...)` raises Pydantic ValidationError; the SHACL shape refuses any non-3-Literal value.
  </acceptance_criteria>
  <done>Three structurally-distinct governance modules (contest, supersede, resolve_contest) ship — each with its own event class, validator, SHACL shape, and CLI command. GOV-05 no-majority-vote locked by 3-value Literal + 3-value sh:in + explicit-rejection test. Active-roles stability Hypothesis property test gives 500-example coverage. The grep-guard regression test is in its OWN Task 2 (quality_gate convention).</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Ship the D-16 grep-guard regression test (its own task per the quality_gate convention)</name>
  <files>tests/governance/test_grep_guard_three_way_disambiguation.py</files>
  <read_first>
    - tests/shards/test_dep_leak_guard.py (FULL — THE per-file source-scan template)
    - tests/identity/test_no_server_keys_contract.py (FULL — THE AST-walk pattern at lines 36-58 for the Click-impl-function check)
    - src/folio_insights/governance/{contest,supersede}.py (from Task 1 of this plan)
    - .planning/phases/07-governance-model-3-1/07-RESEARCH.md lines 1015-1095 (grep-guard regression test code skeleton)
  </read_first>
  <behavior>
    - Test (grep-guard 1 — no cross-imports): for each module in `{contest, supersede, retract}`, source-scan refuses `from folio_insights.governance.<other>` AND `import folio_insights.governance.<other>` (where `<other>` is one of the other two).
    - Test (grep-guard 2 — no shared base class beyond GovernanceEvent / _BaseEvent): AST-walk each module; find each `ClassDef` whose name contains `Event`; collect its base names; assert no base name is in the forbidden-shared set `{ContestSupersedeBase, DisagreementEvent, DisputeEvent}`.
    - Test (grep-guard 3 — no shared Click implementation function): source-scan each `governance/cli/{contest,supersede,retract}.py`; refuse references to forbidden helpers `{execute_disagreement, _dispatch_disagreement, handle_disputed_action}`.
  </behavior>
  <action>
    Create `tests/governance/test_grep_guard_three_way_disambiguation.py` per RESEARCH lines 1015-1095 verbatim with substitutions:
    - `THREE_WAY = ("contest", "supersede", "retract")` (NOTE: `retract.py` ships in 07-05b; this test uses `pytest.importorskip("folio_insights.governance.retract")` at module top so the test runs as a no-op until 07-05b lands, then enforces the full triad).
    - 3 parametrized tests per the behavior list.
    - Use `pytestmark = pytest.mark.governance`.

    Document in the module docstring: this test is the QUALITY GATE for D-16; it has its own task to keep the regression check decoupled from any module's implementation. Once 07-05b lands `retract.py`, this test enforces the full three-way separation.
  </action>
  <verify>
    <automated>uv run pytest tests/governance/test_grep_guard_three_way_disambiguation.py -x -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/governance/test_grep_guard_three_way_disambiguation.py -x` exits 0 — D-16 enforced for the modules that exist now (contest, supersede). With `pytest.importorskip("folio_insights.governance.retract")`, the test currently SKIPS the retract branch and PASSES the contest/supersede branches.
    - The module top contains `pytest.importorskip("folio_insights.governance.retract")` so 07-05b's landing flips the test from partial to full coverage automatically (no edit needed in 07-05b).
    - `grep -c "THREE_WAY" tests/governance/test_grep_guard_three_way_disambiguation.py` >= 1.
  </acceptance_criteria>
  <done>D-16 grep-guard regression test ships as its own task (quality_gate convention); skips retract checks until 07-05b lands; auto-enforces the full triad on 07-05b's completion.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Three-way disambiguation (PRD §21.8 / §21.9 / GOV-04 reviewer-judgment moment) -> 3 distinct modules + 3 distinct Click commands | D-16 software discipline. Refactoring toward DRY is intentionally forbidden; grep-guard test fails CI. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-7-11 | Tampering | Code review tries to DRY contest/supersede/retract into a shared `disagree()` helper | mitigate | D-16 grep-guard regression test (test_grep_guard_three_way_disambiguation.py) — 3 parametrized tests refusing cross-imports / shared base class / shared Click impl function. OWN task per the revision quality_gate convention. **HIGH severity**. |
| GOV-05 explicit-rejection | Logic | majority-vote contest resolution sneaks back in | mitigate | Pydantic `Literal["arbiter","distinguo","aporetic"]` (3 values exactly) + `sh:in` SHACL constraint + test_no_majority_vote_resolution.py asserts `get_args()` returns the 3-value set. Future expansion requires ADR. |
| T-7-01 | Elevation | CLI command bypasses role check | mitigate | D-19 `await authorize(...)` as first step in every new CLI; test_authorize_called_first.py (07-04b) source-scan extends to cover contest/supersede/resolve-contest. |
| T-7-12 | Tampering | direct rdflib import in contest.py / supersede.py / resolve_contest.py | mitigate | dep-leak guard (07-01) covers all new files. |
| T-7-SC | Tampering | new pip dep | accept | Zero new packages this plan. |
</threat_model>

<verification>
- `uv run pytest tests/governance -x -q` exits 0 cumulatively (07-01 + 07-03 + 07-04a + 07-04b + 07-05a).
- `uv run pytest tests/ -q` exits 0 (no regression).
- `uv run folio-insights governance --help` lists at least 6 subcommands: `promote`, `assert-role`, `revoke-role`, `contest`, `supersede`, `resolve-contest` (and `retract`, `export` after 07-05b).
- `grep -rn "import aiosqlite\|import rdflib\|import pyoxigraph" src/folio_insights/governance/ | grep -v shape_validation.py | grep -v "^#"` returns empty.
- `ls src/folio_insights/governance/shapes/*.ttl | wc -l` returns 6 (governance_log + role_assertion + role_revocation + promotion + contest + contest_resolution + supersession = 7 actually; recount: 07-03 ships 1, 07-04a ships 2, 07-04b ships 1, this plan ships 3 → 7 total at this point; 07-05b ships the 8th retraction shape).
- `ruff check src/folio_insights/governance/` exits 0.

Correction: this plan ships 3 TTL files (contest, contest_resolution, supersession), bringing the cumulative shape count to 7 (log + role_assertion + role_revocation + promotion + 3 here). 07-05b ships the 8th (retraction).
</verification>

<success_criteria>
- GOV-04 partially satisfied: 2 of 3 standalone modules ship (contest, supersede); resolve_contest + 3 CLI subcommands; retract module ships in 07-05b.
- GOV-05 satisfied: 3 contest-resolution paths; explicit-rejection test refuses any 4th.
- D-16 grep-guard ships as its own task (Task 2); auto-enforces the full triad once 07-05b lands.
- Active-roles stability Hypothesis property test (max_examples=500) covers D-13.
- D-04 boundary intact.
</success_criteria>

<output>
Create `.planning/phases/07-governance-model-3-1/07-05a-SUMMARY.md` when done with: files created (3 modules + 3 TTL + 3 CLI + 11 test files), test counts, the D-16 quality_gate test status (skips retract branch pending 07-05b), and a sample resolve-contest CLI invocation showing one of the 3 paths.
</output>
</content>
</invoke>