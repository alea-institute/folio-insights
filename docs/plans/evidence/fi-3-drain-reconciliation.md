# fi-3 drain reconciliation evidence

## Result and limits

**Partial historical reconciliation; no branch is recommended for closure.**
Four recorded merge parents and eight supplemental landing/replacement commits
are ancestors of both the build entry and local `master`. No missing,
still-required production change was demonstrated from the accessible history.
No production code, tests, viewer files, dependencies or schemas were changed.

The complete current `feat/drain-*` inventory, its source objects, authoritative
target and chief campaign authority excerpt were not supplied. Historical
inclusion does not establish that a branch has no later tail. This receipt does
not satisfy the implementation Definition of Done in the
[fi-3 plan](../2026-10-27-2141-refactor-fi3-drain-reconciliation-plan.md).

## Pinned comparison

Local inventory captured **2026-10-28T02:54:05Z** (October 27 in America/Chicago).
This is the lane's observation time, not a controller source-snapshot time.

| Role | Commit or observation |
|---|---|
| Build entry, `drawdown/fi-3` | `ee97bfdffe0de158b7746e70be58727c2d5d3bcf` |
| Shared production baseline | `99c3f6db65385f85fa41ed975a0c12924d155397` |
| Local comparison target, `master` | `269171e47bdfc20fa574fa9eeeff730b91919b91` |
| Authoritative controller target | Not supplied; local `master` is not asserted to be current upstream |
| Current drain refs and remote-tracking refs | None in this clone |
| Other refs | `refs/tags/v1.0` at `5ed2789e38f90b65e66834b5d246d0a9acc819c6`; `refs/tags/v1.1` at `96de497a26f15576ec7049b4a4f852061c6de2bc` |
| Git history | Not shallow; no remotes; clean worktree at entry |

The entry adds only the fi-3 plan to the shared baseline. Local `master` adds one
session/planning metadata commit to that baseline. A direct comparison of
`src/`, `api/`, `tests/`, `viewer/`, `ci/`, `pyproject.toml`, `uv.lock`,
`requirements.lock` and `requirements.dev.lock` between entry and local target
returned no changed paths. The metadata commit was neither imported nor altered.
The fi-3 contribution is measured from the shared baseline, not by treating the
target's unrelated metadata as fi-3 deletions.

No on-disk `AGENTS.md` or `CLAUDE.md` was found. The supplied mandate and plan
govern this work. The chief file
`docs/plans/2026-10-26-0705-feat-codex-drawdown-campaign-plan.md` and chief
`ops/drawdown/mandates/_common.md` are unavailable here. Their contents have not
been inferred from similarly numbered repository requirements. The repository's
Phase 9 R9 polysemy gate and measured-propositions R9 atomicity requirement are
distinct; neither supplies the missing campaign authority.

## Historical branches

These seven names come from local merge messages, the auth squash message and
the U9/U10 review plans. **They are not a complete current branch inventory.**
For every row, the current source tip and current external PR state are unknown.
An evidenced historical PR number is not a claim about its present state.

| Historical branch | Pinned evidence | Disposition of accessible history | Closure recommendation |
|---|---|---|---|
| `feat/drain-shards-axioms` | PR #32, merge `103d9ca74341f21aae6b1be6645cb2c51d73b9be`, parent 2 `183bcf8c44d2164bf9fc1c4c55dbb664d4c834b5` | Included: original plan and coordination note. This tip alone does not contain the later implementation. | Unresolved current tail; do not close from this receipt |
| `feat/drain-retire-syspath-bridges` | PR #33, merge `09b54b73be0466a821ec5d802ee8570536725eaf`, parent 2 `b1282f5ad959fd2eda259ffb36361b042d16d715` | Included: four retired bridge seams, parity fixtures, lazy ingestion, citation probe and load cooldown. Retained ingestion/mapper seams are intentional. | Unresolved current tail; do not close from this receipt |
| `feat/drain-wave1` | PR #34, merge `3dd361e7d78fbf3cdba4b3d0c5cf255ee3d17583`, parent 2 `22f921a9aedaca7c9ced1b1eae8e479b65e7c637` | Included historical wave and review corrections; active hierarchy later superseded, as detailed below. | Unresolved current tail; no blanket closure |
| `feat/drain-bridge-ingest` | PR #35, merge `8c9817015fc337d1eeb966a3d809ac34e7169fb9`, parent 2 `bf683c2a0512fc04f1bfeae4e01509be673c995b` | Included: ingestion/status, v0.4.0 dependency lock, manifest PII/I/O/shared-span fixes. Later guard and journal repairs are also included. | Unresolved current tail; do not close from this receipt |
| `feat/drain-u5-auth` | Squash-source name in `6d1b2970dc7b38495060473c70b63939ae715f83`, included through PR #34 | Auth landing included. No source tip/object was supplied for independent squash equivalence. | Unresolved source comparison and current tail |
| `feat/drain-fix-u9` | [Review plan](../2026-10-09-fix-u9-decision-review-plan.md); landing `d2b1f7ca1d92e60b28e676700e7bf8780701948f` (#36) includes that plan and signed-decision code/tests | Landing included; source-tip patch equivalence is unverified. Historical review-UI changes are outside this lane. | Unresolved source comparison and current tail |
| `feat/drain-fix-u10` | [Review plan](../2026-10-09-fix-u10-review-plan.md); landing `2f742eb93c49c5e8a7f32b2a080ce903a426c62e` (#38) includes that plan and graph code/tests | Landing included; backend flat-reference replacement retained. Viewer behavior was not re-reviewed in this lane. | Unresolved source comparison and current tail |

### Merge integration checks

For each of the four merge records, `git merge-base --is-ancestor` returned 0
for its second parent against both pinned entry and target. The source-side
ranges contain respectively 1, 2, 40 and 3 reachable commits (including merges
where present). Comparing each second-parent tree to its merge tree, restricted
to the union of source-side changed paths, found:

- PR #32 and #33: no differences on source-side changed paths.
- PR #34: only `src/folio_insights/config.py` and
  `src/folio_insights/pipeline/stages/knowledge_classifier.py` differ. Inspection
  shows the already-landed bridge documentation/settings and one-time citation
  availability probe added at integration; the compared patch removes no wave
  implementation.
- PR #35: only `api/main.py` and `src/folio_insights/cli.py` differ. The integration
  retains the wave's authentication, corpus validation, read-only database
  behavior, paused-job commands and CLI registrations; the compared patch
  removes no ingest implementation.

This checks the historical integration boundary. It does not prove behavior at
an unavailable current tip. No patch-id or `git cherry` equivalence is claimed
for the three branches whose source objects are missing.

### Behavior groups and current-contract evidence

The files below exist at the entry revision. Test names describe coverage to
run, **not passing results**; execution was blocked before collection.

| Historical group | Current disposition and evidence | Existing verification surface |
|---|---|---|
| U1 lineage | Included in wave: per-unit template identity in `models/knowledge_unit.py`, `pipeline/stages/base.py` and `llm/templates.py` under `src/folio_insights/` | `tests/pipeline/test_unit_template_lineage.py` |
| U2 rubric | Included in wave, including judged-gate, integer-grade and chapter-floor corrections; `src/folio_insights/rubric/` | `tests/rubric/test_harness.py`, `tests/rubric/test_criteria.py`, `tests/rubric/test_gold.py` |
| U3 kernel | Included in wave, including seed digest/idempotency and traversal truncation fixes; `src/folio_insights/kernel/` | `tests/kernel/test_catalog.py`, `tests/kernel/test_seed.py`, `tests/kernel/test_traversal.py` |
| U4 references | Historical Tractarian hierarchy/ordinals superseded by flat IRI references in `src/folio_insights/revision/tractarian.py`; logical cycles still refused by `revision/acyclicity.py` | `tests/revision/test_flat_propositions.py`, `tests/revision/test_cycle_guard.py`, `tests/revision/test_tractarian.py` |
| U5 authentication/read safety | Auth squash and wave corrections included; corpus validation, loopback CSRF and read-only access retained in `api/`. Bridge status is a read and ingest has its service-token dependency. | `tests/api/test_auth.py`, `tests/api/test_read_side_effects.py`, `tests/bridge_ingest/test_bridge_api.py` |
| U6 server time | Included in wave, including log-shape ordering and declared `fi:asof`; `src/folio_insights/governance/clock.py`, `storage/governance.py` | `tests/governance/test_server_time.py`, `tests/governance/test_governance_export_cli.py` |
| U7 paused-job expiry | Included in wave, with standalone-worker TTL parsing; `src/folio_insights/jobs/queue.py`, `jobs/worker.py` | `tests/jobs/test_paused_expiry.py` |
| U8 minting | Landing #37 included; later atomic mapping preserves the legacy identity recipe rather than replaying the historical mapper | `tests/minting/test_minter.py`, `tests/minting/test_atomic_mapper.py`, `tests/minting/test_support.py`, `tests/shards/test_verify_iris_cli.py` |
| U9 signed decisions | Landing #36 included; signer attribution, freshness at commit time and nonce replay checks remain in `src/folio_insights/proposals/signed_decisions.py` and `proposals/store.py`; API read-back coverage exists | `tests/proposals/test_signed_decisions.py`, `tests/test_signed_decisions_api.py` |
| U10 bounded graphs | Landing #38 included; `api/routes/shard.py` retains bounded graph/derivation behavior with flat references | `tests/test_shard_graph_api.py`, especially `test_graph_references_are_flat_iris` and edge-budget cases |
| U11 validator | Included in wave with unscreened/unverdicted clusters reported unchecked; `src/folio_insights/validation/validator.py` | `tests/validation/test_clusters.py`, `tests/validation/test_hermit_cluster.py`, `tests/validation/test_dep_leak_guard.py` |
| U12 closed-world query | Included in wave with full-match IRI validation; `src/folio_insights/query/closed_world.py` | `tests/query/test_closed_world.py` |
| Bridge retirement | Included; retained seams and parity conditions documented in [bridge retirement](../../bridge-retirement-2026-10-09.md) | `tests/test_bridge_retirement_parity.py` |
| Bridge ingestion | Included, including manifest PII refusal and same-span race fixes; `src/folio_insights/bridge_ingest/` | `tests/bridge_ingest/test_ingest.py`, `tests/bridge_ingest/test_identity_parity.py`, `tests/bridge_ingest/test_bridge_api.py` |
| Integration repairs | PR #39 classifies bridge guards; PR #40 retries the WAL switch. The redundant bridge-level open retry remains unchanged. | `tests/api/test_auth.py`, `tests/storage/test_journal_wal_open.py` |
| Other wave corrections | Framework registration authorization remains a ledger-transaction operation; superseded shards end at server commit time | `tests/frameworks/test_framework_storage.py`, `tests/revision/test_revision_effects.py` |

Full supplemental commit identities, all verified ancestors of entry and target:

| Evidence | Commit |
|---|---|
| U5 auth squash | `6d1b2970dc7b38495060473c70b63939ae715f83` |
| U9 landing, #36 | `d2b1f7ca1d92e60b28e676700e7bf8780701948f` |
| U8 landing, #37 | `fe430a448fbbe66af90017ec98e1c7131bc57392` |
| U10 landing, #38 | `2f742eb93c49c5e8a7f32b2a080ce903a426c62e` |
| Bridge guard merge, #39 | `1738558fc5a18e99279de663408c63713dc17e16` |
| WAL retry merge, #40 | `1c6d4b4ab8d998f620403b97cf84db46be9d1c9f` |
| Hierarchy retirement, landed through #56 | `b08525b82bee116f6dda80e9549cd0de7e9a8c15` |
| Archived hierarchy protection, landed through #67 | `2bdc1d039c793089241e81819e0f7eb37a80f74d` |

The [measured-propositions plan](../2026-10-26-0716-feat-measured-propositions-and-workbench-plan.md),
KD3, R9–R10, KTD9–KTD11 and U36, explicitly supersedes active hierarchy. Current
`revision/tractarian.py` returns frozen IRIs and empty parent fields;
`revision/acyclicity.py` uses only logical dependencies. `shards/records.py`
archives legacy hierarchy and retains original bytes. Paths in this paragraph
are under `src/folio_insights/`. Existing flat-proposition, identity and kernel
tests cover these distinctions. Their presence plus replacement ancestry is
supersession evidence, not a new runtime acceptance claim.

## Fresh verification

All attempted runtime commands used the unchanged production tree at build entry
`ee97bfdffe0de158b7746e70be58727c2d5d3bcf`. Later fi-3 edits are documentation
only, so no different runtime candidate was tested. No tests were added or
modified: U2 has no demonstrated behavior to recover, and U1/U3 are documentary.

| Check | Observed outcome |
|---|---|
| Ref inventory, ancestry and merge integration | PASS for the bounded historical comparisons above; current inventory remains unresolved |
| Runtime/manifest entry-to-target comparison | PASS: no changed paths in the listed runtime/manifest scope |
| `uv sync --frozen --extra dev --offline --python 3.12` | BLOCKED, exit 1: selected CPython 3.12.12 and created ignored `.venv/`, then failed because locked `torch==2.11.0` was absent from cache. Offline mode prevented download; this is not evidence that online connectivity was tested. |
| Quick suite command below | BLOCKED, exit 1 before collection: `No module named pytest`; zero tests executed, no pass/fail/skip totals available |
| `PYTHONPATH=src:. .venv/bin/python scripts/check_exclusions.py --history 269171e47bdfc20fa574fa9eeeff730b91919b91` | BLOCKED, exit 1 at import: `No module named 'jcs'`; scanner did not run |
| Focused suites and bridge integration parity | NOT RUN after dependency failure; require the existing test environment. Parity additionally requires a supplied folio-enrich backend. |
| Ruff, shapes, Vitest, build and Playwright | NOT APPLICABLE to this documentation-only diff; no Python, shape, backend graph or front-end change |

Quick suite attempted, matching the selection in `ci/build.py`:

```sh
PYTHONPATH=src:. FOLIO_INSIGHTS_LIVE_LLM=0 HF_HUB_OFFLINE=1 \
  .venv/bin/python -m pytest -x --ff -q --benchmark-skip \
  -m 'not gate5 and not slow and not integration'
```

The system interpreter is Python 3.14.4, outside the project's `>=3.11,<3.13`
range. `XDG_CACHE_HOME` and `UV_CACHE_DIR` were unset; the adjacent sandbox cache
directory was empty. No manifest/lockfile was changed to obtain an install.
No online install, provider call or credential discovery was attempted. Missing
dependency/model/JRE inputs and the announced socket restriction must be handled
by the controller's prepared environment; socket-dependent tests were not
reached, so no socket failure is asserted for this run.

Document-only validation passed: all Markdown links in the three changed
documents resolve inside the repository; all cited full commit hashes resolve;
all 59 explicit implementation/test file references in the fi-3 plan exist; the
coordination update preserves its original bytes as a prefix; original refs
remain present with `master` and both tags unchanged; and the working diff is
limited to the three intended documents. The targeted public-path/private-key
marker screen and `git diff --check` also passed. These limited checks do not
replace the blocked exclusion scanner or repository tests.

## Controller recovery and closure protocol

1. Supply the chief campaign Goal Capsule and cited R11/R15/R16/R17/R19/R20
   excerpts and clarify the campaign R9 reference. This is preparation, not a
   new product decision.
2. Supply a complete, timestamped `feat/drain-*` inventory, exact current tips,
   corresponding local Git objects and authoritative target hash. Account for
   all seven historical names even if absent from the current source inventory.
   Supply external PR identity/state separately; absence of a local ref proves
   neither deletion nor closure. The lane must not add a remote or seek access.
3. Compare each supplied tip to that target. For non-ancestors, use patch
   comparison and current-contract review. Split mixed groups; recover only a
   demonstrated, still-required backend omission with a failing regression
   test. Excluded viewer changes go to their owner, not into this lane.
4. Supply a compatible locked environment and execute the quick suite,
   supersession-sensitive tests above and exclusion scanner. Run required
   parity with the supplied backend using `FOLIO_INSIGHTS_FOLIO_ENRICH_PATH` and
   isolated corpus storage; record required skips and host-only checks honestly.
5. Recheck source/target tips before publication or closure. An advanced tip
   reopens its affected comparison. The controller owns scanning, pushing and
   opening the PR; the campaign gate owns Astra/Fable review and merging. No
   external branch/PR action has been taken by this lane.

Plan coverage: U1 is partial (historical evidence complete for these records,
current inventory absent); U2 is blocked on an identified missing delta, with
no recovery change justified; U3 provides this receipt and the
[controller handoff](../../handoffs/2026-10-27-fi-3-drain-reconciliation.md), but
full closeout remains blocked. AE1 and AE4 are represented by explicit unknown
tips and unavailable verification; AE2's retired hierarchy is accounted for;
AE3 squash equivalence remains unverified; AE5 governs the controller recheck.
