---
phase: 07-governance-model-3-1
plan: 04b
type: execute
wave: 4
depends_on: [07-01, 07-03, 07-04a]
files_modified:
  - src/folio_insights/governance/promote.py
  - src/folio_insights/governance/shape_validation.py
  - src/folio_insights/governance/shapes/promotion_shape.ttl
  - src/folio_insights/governance/cli/__init__.py
  - src/folio_insights/governance/cli/promote.py
  - src/folio_insights/governance/cli/role_assert.py
  - src/folio_insights/governance/cli/role_revoke.py
  - src/folio_insights/corpus/__init__.py
  - src/folio_insights/corpus/cli/__init__.py
  - src/folio_insights/corpus/cli/corpus.py
  - src/folio_insights/cli.py
  - tests/governance/test_promotion_requires_citation.py
  - tests/governance/test_promotion_status_kind.py
  - tests/governance/test_unsigned_promotion_rejected.py
  - tests/governance/test_promotion_shape.py
  - tests/governance/test_authorize_called_first.py
  - tests/corpus/__init__.py
  - tests/corpus/test_corpus_init_genesis.py
autonomous: true
requirements: [GOV-03, CORPUS-05]
deferred: [GOV-09, GOV-10]
tags: [governance, promotion, cli, corpus-init, authorize-first]

must_haves:
  truths:
    - "[D-20] Promotion citation: `cited_iris` non-empty + every IRI resolves to an existing shard in the corpus AND is not the shard being promoted"
    - "[D-21] Reviewer specifies `epistemic_status` via `--status`; validator enforces per-status table"
    - "[D-10/D-19] corpus init calls authorize() with action=\"corpus_init\"; authorize() returns Allow only when the corpus has zero log rows AND DID matches admin DID (genesis bootstrap carve-out). No CLI command is exempt from the authorize-first rule."
    - "[D-19] Every governance CLI command (`promote`, `assert-role`, `revoke-role`, `corpus init`) calls `authorize()` as the first step after parsing; the source-scan regression test enforces this AST-level"
    - "Unsigned promotion rejected end-to-end via CLI (orig EC3 amended bar — CLI-only per D-03)"
    - "[D-01/D-03] GOV-09 + GOV-10 + all web UI surfaces deferred post-Phase-14; Phase 7 ships CLI + library + thin HTTP API contract only."
  artifacts:
    - path: "src/folio_insights/governance/promote.py"
      provides: "PromotionEvent validator: D-20 cite-resolvable + D-21 status-kind cross-check"
      contains: "def validate_promotion"
    - path: "src/folio_insights/corpus/cli/corpus.py"
      provides: "folio-insights corpus init --admin-did did:... writes genesis row 0 (D-10) via authorize()"
      contains: "corpus_group"
    - path: "src/folio_insights/governance/cli/promote.py"
      provides: "governance promote subcommand — authorize -> validate_promotion -> sign -> append"
      contains: "await authorize"
    - path: "src/folio_insights/governance/shapes/promotion_shape.ttl"
      provides: "fi:PromotionShape — sh:in 3-status Literal + sh:minCount 1 on citation"
      contains: "fi:PromotionShape"
  key_links:
    - from: "src/folio_insights/governance/cli/promote.py"
      to: "src/folio_insights/governance/authorize.py::authorize"
      via: "first step after Click parsing (D-19)"
      pattern: "await authorize"
    - from: "src/folio_insights/corpus/cli/corpus.py"
      to: "src/folio_insights/governance/authorize.py::authorize"
      via: "first step calls authorize(did, action='corpus_init', corpus, log=log, admin_did=admin_did) — genesis carve-out per D-10/D-19"
      pattern: "action=\"corpus_init\""
    - from: "src/folio_insights/cli.py"
      to: "src/folio_insights/governance/cli/__init__.py::governance_group"
      via: "module-bottom cli.add_command(governance_group) + cli.add_command(corpus_group)"
      pattern: "cli\\.add_command"
---

<objective>
Ship the promotion validator (D-20 cite-resolvable + D-21 status-kind cross-check), the four CLI subcommands (`governance promote`, `governance assert-role`, `governance revoke-role`, `corpus init`) that consume the 07-04a `authorize()` + `governance_log.append()` substrate, and the D-19 source-scan regression test that enforces `authorize()` is the first step of EVERY governance CLI command — including `corpus init` (Issue #3 closure: no CLI exemption).

Purpose: Closes GOV-03 + CORPUS-05 by wiring the library-layer primitives from 07-04a into the user-facing CLI surface. The genesis bootstrap is implemented by calling `authorize(admin_did, action="corpus_init", corpus, log=log, admin_did=admin_did)` as the first step of `corpus init`, just like every other command — the carve-out lives inside `authorize()` itself.

Output: `governance/promote.py`; `promotion_shape.ttl`; 4 CLI command modules; root `cli.py` registration; 7 test files including the D-19 AST regression test that covers all 4 commands.
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
@src/folio_insights/governance/events.py
@src/folio_insights/governance/log.py
@src/folio_insights/governance/authorize.py
@src/folio_insights/governance/roles.py

<interfaces>
<!-- D-20 + D-21 contracts; D-19 first-step discipline; the 07-04a authorize() signature with admin_did keyword. -->

From src/folio_insights/governance/authorize.py (07-04a):
```python
async def authorize(
    did: str,
    action: str,            # SignedAction value OR the special "corpus_init" bookkeeping action
    corpus: str,
    *,
    log: GovernanceLog,
    admin_did: str | None = None,   # required when action == "corpus_init"
    asof: datetime | None = None,
) -> Allow | Deny: ...
```

From src/folio_insights/identity/cli.py:206-296 (sign_cmd — THE canonical authorize -> preview -> confirm -> sign -> append -> emit sequence):
```python
@did_group.command("sign")
def sign_cmd(...):
    # 1. load_signing_key
    # 2. build preview
    # 3. click.confirm gate
    # 4. sign_attestation(...)
    # 5. emit
```

D-21 status-kind cross-check (from CONTEXT.md):
- `authority_only` -> cited shard's authority kind must be precedent/statute (AuthorityShard subtype)
- `demonstrable` -> cited shard must itself be demonstrable or stronger
- `per_se_nota_quoad_nos` -> no citation depth check (axiomatic, self-evident-to-us)
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Ship `promote.py` validator + `promotion_shape.ttl` + validator body + promotion polarity tests</name>
  <files>src/folio_insights/governance/promote.py, src/folio_insights/governance/shape_validation.py, src/folio_insights/governance/shapes/promotion_shape.ttl, tests/governance/test_promotion_requires_citation.py, tests/governance/test_promotion_status_kind.py, tests/governance/test_promotion_shape.py</files>
  <read_first>
    - src/folio_insights/governance/events.py (from 07-01 — PromotionEvent class with cited_iris: list[str] = Field(min_length=1))
    - src/folio_insights/revision/content_edit.py:304-333 — canonical_content_hash + _jcs_canonical_bytes (every promotion event hashes via this seam)
    - src/folio_insights/revision/store.py (ShardStore Protocol — validate_promotion's cite-resolvability check consumes it)
    - src/folio_insights/shards/subtypes.py (the 5 shard subtypes + epistemic_status field on AuthorityShard etc.; needed for D-21 status-kind cross-check)
    - src/folio_insights/governance/shape_validation.py (from 07-01 — the validate_promotion_shape stub)
    - .planning/phases/07-governance-model-3-1/07-RESEARCH.md lines 993-1013 (PromotionShape TTL); lines 252-279 (validate_promotion body); lines 1438-1463 (validation requirements)
    - .planning/phases/07-governance-model-3-1/07-CONTEXT.md `<decisions>` D-20, D-21
  </read_first>
  <behavior>
    - Test (promotion citation, positive): a PromotionEvent with `cited_iris=["fi:shard:abc"]` where shard:abc resolves in the ShardStore -> `validate_promotion` passes.
    - Test (promotion citation, negative — empty): `cited_iris=[]` -> fails at Pydantic level (Field(min_length=1)) AND at SHACL level (sh:minCount 1).
    - Test (promotion citation, negative — unresolvable): `cited_iris=["fi:shard:nonexistent"]` -> `validate_promotion` raises ValueError mentioning "unresolvable" or "not in store".
    - Test (promotion citation, negative — self-citation): `cited_iris=[event.shard_iri]` -> `validate_promotion` raises ValueError mentioning "self-citation".
    - Test (D-21 status-kind, authority_only): `new_status="authority_only"` cited shard is an AuthorityShard subtype -> pass; cited shard is a SimpleAssertion -> fail with "authority_only requires AuthorityShard cited".
    - Test (D-21 status-kind, demonstrable): `new_status="demonstrable"` cited shard has `epistemic_status="demonstrable"` -> pass; cited shard has `epistemic_status="hypothesis"` -> fail.
    - Test (D-21 status-kind, per_se_nota_quoad_nos): no citation depth check; even an empty-meaning citation (still must be >=1 IRI for D-20) passes status-kind cross-check.
    - Test (PromotionShape positive + negative): valid promotion conforms=True; empty cited_iris conforms=False; new_status outside the 3-Literal set conforms=False.
  </behavior>
  <action>
    Create `src/folio_insights/governance/promote.py`:
    - Module docstring citing D-20 + D-21 + Phase 6 sign_attestation seam.
    - Re-export `PromotionEvent` from events.py.
    - `def validate_promotion(event: PromotionEvent, *, store: ShardStore) -> None:` body:
      - For each iri in `event.cited_iris`: assert `store.get(iri) is not None` (D-20 resolvable); assert `iri != event.shard_iri` (D-20 no-self-citation).
      - D-21 status-kind cross-check: a per-status helper dict `_STATUS_CITATION_RULES`. For `authority_only`, require >=1 cited shard whose `__class__.__name__` is in `{"AuthorityShard", "ConflictingAuthorities"}`. For `demonstrable`, require >=1 cited shard whose `epistemic_status` is in `{"demonstrable", "per_se_nota_quoad_se", "per_se_nota_quoad_nos", "authority_only"}`. For `per_se_nota_quoad_nos`, no depth check (pass through).
      - Raises `ValueError` on any violation.

    Create `src/folio_insights/governance/shapes/promotion_shape.ttl` per RESEARCH lines 999-1013:
    - `fi:PromotionShape` with `sh:in ("per_se_nota_quoad_nos" "demonstrable" "authority_only")` on `fi:newStatus` (sh:minCount 1, sh:maxCount 1).
    - `sh:property [ sh:path fi:citedIri ; sh:minCount 1 ]` (D-20 non-empty).
    - Comment block notes D-21 status-kind cross-check lives in `validate_promotion()` because SHACL cannot reach into the cited shard's authority kind (cross-shard lookup).

    Edit `src/folio_insights/governance/shape_validation.py` `validate_promotion_shape` NotImplementedError stub -> real body (mirror `validate_governance_log_shape` pattern from 07-03).

    Create 3 test files per behavior list:
    - `tests/governance/test_promotion_requires_citation.py` — positive + 3 negative cases (empty, unresolvable, self)
    - `tests/governance/test_promotion_status_kind.py` — D-21 per-status table (3 positive + 2 negative cases)
    - `tests/governance/test_promotion_shape.py` — SHACL positive + negative polarity pair
  </action>
  <verify>
    <automated>uv run pytest tests/governance/test_promotion_requires_citation.py tests/governance/test_promotion_status_kind.py tests/governance/test_promotion_shape.py -x -q</automated>
  </verify>
  <acceptance_criteria>
    - `python -c "from folio_insights.governance.promote import validate_promotion, PromotionEvent; from folio_insights.governance.shape_validation import validate_promotion_shape; print('ok')"` prints `ok`.
    - `rdflib.Graph().parse("src/folio_insights/governance/shapes/promotion_shape.ttl", format="turtle")` succeeds.
    - `uv run pytest tests/governance/test_promotion_requires_citation.py tests/governance/test_promotion_status_kind.py tests/governance/test_promotion_shape.py -x` exits 0 covering D-20 + D-21 + SHACL polarity.
    - `grep -rn "import aiosqlite\|import rdflib\|import pyoxigraph" src/folio_insights/governance/promote.py | grep -v "^#"` returns empty.
    - Behavior: `validate_promotion(event_with_self_cite, store=...)` raises ValueError; `validate_promotion(event_with_unresolvable_iri, store=...)` raises ValueError; `validate_promotion(event_with_authority_only_status_citing_simple_assertion, store=...)` raises ValueError mentioning the D-21 mismatch.
  </acceptance_criteria>
  <done>Promotion library ships with validator + SHACL shape; D-20 cite-resolvable + D-21 status-kind cross-check enforced via positive + negative polarity tests.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Ship 4 CLI subcommands (governance promote / assert-role / revoke-role + corpus init) + root CLI wiring + D-19 source-scan regression test + corpus init genesis test + unsigned-promotion CLI rejection test</name>
  <files>src/folio_insights/governance/cli/__init__.py, src/folio_insights/governance/cli/promote.py, src/folio_insights/governance/cli/role_assert.py, src/folio_insights/governance/cli/role_revoke.py, src/folio_insights/corpus/__init__.py, src/folio_insights/corpus/cli/__init__.py, src/folio_insights/corpus/cli/corpus.py, src/folio_insights/cli.py, tests/governance/test_unsigned_promotion_rejected.py, tests/governance/test_authorize_called_first.py, tests/corpus/__init__.py, tests/corpus/test_corpus_init_genesis.py</files>
  <read_first>
    - src/folio_insights/identity/cli.py (FULL — Phase 6 did_group template; sign_cmd at 206-296 is the canonical authorize -> preview -> sign -> append sequence; generate_cmd at 114-152 + bind_cmd at 392-471 for the corpus init analog)
    - src/folio_insights/cli.py:622-640 (module-bottom CLI registration — mirror exactly)
    - src/folio_insights/governance/log.py (from 07-04a — append() with signature verification + genesis carve-out at log layer)
    - src/folio_insights/governance/authorize.py (from 07-04a — every CLI command's first step; embeds the corpus_init carve-out)
    - src/folio_insights/governance/promote.py (from Task 1 of this plan — validate_promotion called by governance/cli/promote.py)
    - tests/polysemy/test_cli_review.py (CliRunner against Click subgroup analog)
    - tests/identity/test_did_cli.py (CliRunner against did_group analog)
    - tests/identity/test_no_server_keys_contract.py (lines 36-58 — AST-walk pattern for the authorize-called-first regression test)
    - .planning/phases/07-governance-model-3-1/07-PATTERNS.md lines 403-505 (governance/cli/ patterns + corpus init pattern)
    - .planning/phases/07-governance-model-3-1/07-CONTEXT.md `<decisions>` D-15 (CLI shape), D-19 (authorize first — no CLI exemption)
  </read_first>
  <behavior>
    - Test (unsigned promotion CLI rejected end-to-end): `runner.invoke(cli, ["governance", "promote", "fi:shard:abc", "--status=demonstrable", "--cite", "fi:shard:cited"])` WITHOUT a signing key path that produces a valid signature -> exits with non-zero code and stderr message about "no signing key" or "unauthorized" or "InvalidSignature".
    - Test (corpus init writes genesis row 0): `runner.invoke(cli, ["corpus", "init", "test-corpus", "--admin-did", "did:fi:alice", "--key-path", str(test_key_path)])` succeeds; after, `await log.get_by_position("test-corpus", 0)` returns a RoleAssertionEvent with `role="corpus_admin"`, `subject_did="did:fi:alice"`, and `signature.did="did:fi:alice"` (self-signed).
    - Test (authorize called first — D-19 regression for ALL FOUR commands including corpus init): AST-walk each `governance/cli/{promote,role_assert,role_revoke}.py` AND `corpus/cli/corpus.py`; for each Click command function body, assert the first `Await(Call(Name('authorize')))` precedes any `Await(Call(Attribute('append')))`. NO command file is exempt — `corpus init` MUST call `authorize(admin_did, action="corpus_init", corpus, log=log, admin_did=admin_did)` as its first awaited step.
    - Test (corpus init second invocation Deny): after a successful `corpus init`, a second `corpus init` on the same corpus (non-empty log) MUST exit non-zero with stderr `Deny(reason="corpus_already_initialized")`.
    - Test (corpus init mismatched DID): `runner.invoke(cli, ["corpus", "init", "test-corpus", "--admin-did", "did:fi:alice", "--key-path", str(bobs_key)])` where bob's key derives `did:fi:bob` (not matching --admin-did) MUST exit non-zero. The CLI binds the signer's DID == --admin-did before calling authorize; mismatched key → authorize returns `Deny(reason="genesis_mismatch")` or the CLI refuses earlier with a clear error.
  </behavior>
  <action>
    Create `src/folio_insights/governance/cli/__init__.py` with `@click.group(name="governance")` decorator (mirror `identity/cli.py:101-108`). Module docstring cites D-15 + D-03 (CLI-only this phase). Re-export `governance_group`. Import + register the 3 subcommands defined below (`promote`, `assert-role`, `revoke-role`). 07-05a will extend with `contest`, `supersede`, `resolve-contest`; 07-05b will extend with `retract`, `export`.

    Create `src/folio_insights/governance/cli/promote.py`:
    - `@governance_group.command("promote")` with `shard_iri` argument, `--status` (Click Choice over 3-value Literal), `--cite` (multiple, required, must have >=1), `--corpus` required, `--key-path`, `--yes`.
    - Body MUST follow this exact order (D-19):
      1. Parse + load signing key + derive `signer_did`.
      2. `result = await authorize(signer_did, "promote", corpus, log=log)` — if `Deny`, exit non-zero with reason; else continue.
      3. `validate_promotion(event, store=store)` (D-20 + D-21).
      4. Sign + `await governance_log.append(event)` + emit JSON.

    Create `src/folio_insights/governance/cli/role_assert.py`:
    - `@governance_group.command("assert-role")` with `subject_did: str` argument, `--role` (Click Choice over 4-role Literal), `--corpus` required, `--key-path`, `--yes`.
    - Body: parse + load key + derive signer DID + `await authorize(signer_did, "role_assertion", corpus, log=log)` FIRST — if `Deny`, exit non-zero; else `RoleAssertionEvent(...)`, sign, `await governance_log.append`, emit.

    Create `src/folio_insights/governance/cli/role_revoke.py`:
    - `@governance_group.command("revoke-role")` mirroring role_assert.py but with `--revoked-role` flag and building a RoleRevocationEvent. D-11 lockout refusal surfaces from `log.append()` as `WouldLockoutCorpusAdmin` — catch at CLI level, print verbatim error to stderr, exit non-zero.
    - Body: parse → load key → `await authorize(signer_did, "role_revocation", corpus, log=log)` FIRST → build event → sign → `await governance_log.append` (which raises `WouldLockoutCorpusAdmin` on last-admin attempts).

    Create `src/folio_insights/corpus/__init__.py` (empty marker package) and `src/folio_insights/corpus/cli/__init__.py` with `@click.group(name="corpus") def corpus_group()`.

    Create `src/folio_insights/corpus/cli/corpus.py` per PATTERNS.md lines 486-505 + RESEARCH Open Question 1 (refuse to default `--admin-did`; explicit DID required):
    - `@corpus_group.command("init")` with `corpus_name: str` argument, `--admin-did` required (no default; refuse to default per Open Question 1), `--key-path` (default from Phase 6 keystore).
    - Body MUST follow this exact order (D-19 — no CLI exemption; Issue #3 closure):
      1. Parse + load signing key + derive `signer_did` from the key.
      2. **Bind check** (defense in depth): if `signer_did != admin_did`, print error to stderr (`--admin-did does not match the DID derived from --key-path`) and exit non-zero. This prevents an honest CLI from passing a mismatched (did, admin_did) pair to authorize().
      3. `result = await authorize(signer_did, action="corpus_init", corpus_name, log=log, admin_did=admin_did)` — if `Deny`, print `result.reason` to stderr and exit non-zero. The allow case ONLY hits when log is empty AND signer_did == admin_did (genesis bootstrap per D-10).
      4. Build the genesis RoleAssertionEvent (corpus=corpus_name, position=0, subject_did=admin_did, role="corpus_admin"); call `sign_attestation` with action="role_assertion".
      5. `await governance_log.append(event)` (log.py also enforces the genesis carve-out as defense in depth).
      6. `click.echo(event.model_dump_json(indent=2))`.
    - Phase 7 caveat docstring: the `governance_log` for `corpus init` is currently an InMemoryGovernanceLog instance (Phase 13 wires `<corpus>/.governance.sqlite` per D-07; this plan does NOT). cross-invocation persistence lands in Phase 13. The CLI does NOT crash with `FileNotFoundError` looking for a missing SQLite file (in-memory means no disk I/O).

    Edit `src/folio_insights/cli.py` module-bottom (around lines 622-640) to add the module-bottom registration: import `governance_group` from `folio_insights.governance.cli` and `corpus_group` from `folio_insights.corpus.cli`; call `cli.add_command(_governance_group)` and `cli.add_command(_corpus_group)`.

    Create `tests/corpus/__init__.py` (empty marker) and `tests/corpus/test_corpus_init_genesis.py` per behavior list. Use `CliRunner` analog to `tests/identity/test_did_cli.py`. Generate a test signing key (or fixture); invoke `runner.invoke(cli, ["corpus", "init", "test-corpus", "--admin-did", "did:fi:alice", "--key-path", str(key_path)])`; assert result.exit_code == 0; assert "position": 0 and "role": "corpus_admin" in result.output. Add the second-invocation Deny test + the mismatched-DID Deny test.

    Create `tests/governance/test_unsigned_promotion_rejected.py` — CLI end-to-end via CliRunner; orig EC3 amended bar — invoke `runner.invoke(cli, ["governance", "promote", "fi:shard:abc", "--status=demonstrable", "--cite", "fi:shard:cited"])` WITHOUT a valid key path → exits non-zero.

    Create `tests/governance/test_authorize_called_first.py` — D-19 regression test; source-scan each governance/CLI command file AND `corpus/cli/corpus.py` to assert `await authorize(...)` appears before any `governance_log.append(...)` call in each command function body. Use `ast` module — find each Click-decorated function, walk its body, verify the first `Await(Call(Name('authorize')))` precedes any `Await(Call(Attribute('append')))`. **CRITICAL — Issue #3 closure**: `corpus/cli/corpus.py` is NOT exempt; the test asserts its `init` command also calls `authorize()` first (with `action="corpus_init"`).

    Register `pytest.mark.corpus` marker in `pyproject.toml`.
  </action>
  <verify>
    <automated>uv run pytest tests/governance/test_unsigned_promotion_rejected.py tests/governance/test_authorize_called_first.py tests/corpus/test_corpus_init_genesis.py -x -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run folio-insights governance --help` exits 0 and lists subcommands `promote`, `assert-role`, `revoke-role` (more added by 07-05a/b).
    - `uv run folio-insights corpus --help` exits 0 and lists subcommand `init`.
    - `uv run folio-insights corpus init test-corpus --admin-did did:fi:alice --key-path /path/to/test/key` (where the key derives did:fi:alice) succeeds and emits JSON with `"position": 0`, `"role": "corpus_admin"`, `"subject_did": "did:fi:alice"`.
    - `uv run folio-insights governance promote fi:shard:abc --status=demonstrable --cite fi:shard:cited` WITHOUT a valid key path exits non-zero with a message about missing signing key OR unauthorized.
    - `uv run pytest tests/governance/test_unsigned_promotion_rejected.py -x` exits 0 — proves orig EC3 amended bar.
    - `uv run pytest tests/governance/test_authorize_called_first.py -x` exits 0 — D-19 source-scan regression test passes for ALL FOUR command files (`promote.py`, `role_assert.py`, `role_revoke.py`, AND `corpus/cli/corpus.py` — Issue #3 closure).
    - `uv run pytest tests/corpus/test_corpus_init_genesis.py -x` exits 0 — CORPUS-05 acceptance + second-invocation Deny + mismatched-DID Deny.
    - `grep -rn "import aiosqlite\|import rdflib\|import pyoxigraph" src/folio_insights/governance/cli/ src/folio_insights/corpus/ | grep -v "^#"` returns empty (D-04 boundary).
    - `grep -c "from folio_insights.governance.cli import" src/folio_insights/cli.py` >= 1 (registration wired).
    - `grep -c "action=\"corpus_init\"" src/folio_insights/corpus/cli/corpus.py` >= 1 (Issue #3 fix verified — corpus init calls authorize with the bookkeeping action).
  </acceptance_criteria>
  <done>4 CLI subcommands ship and route through `authorize()` as the structurally-mandatory first step; `corpus init` is NOT exempt — it calls `authorize(admin_did, action="corpus_init", corpus, log=log, admin_did=admin_did)` and the genesis carve-out is recognized inside `authorize()` (07-04a). The D-19 regression test enforces this AST-level across all 4 commands. GOV-03 + CORPUS-05 acceptance closes.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| CLI invocation (untrusted operator) -> `authorize()` (D-19 central gate) | Every CLI command's first step; typed result, never raises. Even `corpus init` goes through authorize — Issue #3 closure. |
| Genesis bootstrap (`corpus init`) -> `authorize(action="corpus_init")` -> log row 0 (D-10 carve-out) | The carve-out lives in `authorize()` (07-04a). The CLI layer adds defense-in-depth: refuses if signer's DID != --admin-did before calling authorize. |
| Reviewer-promoted shard -> cited shard resolvability (D-20) -> shard's epistemic_status (D-21) | Phase 4 IRIs + Phase 3 subtypes + Phase 5 store integrity all required; failure modes are ValueError with diagnostic messages. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-7-01 | Elevation | CLI command bypasses role check (including `corpus init` slipping past authorize) | mitigate | D-19 central `authorize()` called as first step in EVERY CLI command including `corpus init`. test_authorize_called_first.py AST-walks all 4 command files (Issue #3 closure). **HIGH severity**. |
| T-7-06 | Tampering | Promotion without resolvable citations | mitigate | `validate_promotion` (D-20) raises ValueError if any cited_iri does not resolve in the ShardStore OR equals the shard being promoted. `fi:PromotionShape` SHACL enforces `sh:minCount 1`. |
| T-7-07 | Tampering | Promotion epistemic-status inconsistency (authority_only citing non-AuthorityShard) | mitigate | D-21 status-kind cross-check in `validate_promotion` (per-status table). Test_promotion_status_kind.py covers 3 positive + 2 negative cases. |
| T-7-12 | Tampering | direct aiosqlite/rdflib/pyoxigraph import in promote.py/cli/ | mitigate | dep-leak guard (07-01 Task 2) covers all new files. Acceptance criterion runs `grep` to confirm. |
| T-7-SC | Tampering | new pip dep | accept | Zero new packages this plan. |
</threat_model>

<verification>
- `uv run pytest tests/governance tests/corpus -x -q` exits 0 cumulatively (07-01 + 07-03 + 07-04a + 07-04b).
- `uv run pytest tests/ -q` exits 0 (no regression in upstream Phases 1/2/5/6).
- `uv run folio-insights governance --help` exits 0 and lists `promote`, `assert-role`, `revoke-role`.
- `uv run folio-insights corpus init test-corpus --admin-did did:fi:alice --key-path <matching test key>` produces JSON with position=0 and self-signed corpus_admin RoleAssertion.
- `grep -rn "import aiosqlite\|import rdflib\|import pyoxigraph" src/folio_insights/governance/ src/folio_insights/corpus/ | grep -v shape_validation.py | grep -v "^#"` returns empty.
- `ruff check src/folio_insights/governance/ src/folio_insights/corpus/` exits 0.
</verification>

<success_criteria>
- D-19 central `authorize()` is the first step every CLI command calls — including `corpus init` (no CLI exemption per Issue #3).
- D-20 + D-21 promotion validators ship with full positive + negative polarity coverage; orig EC3 amended bar satisfied (unsigned promotion rejected end-to-end via CLI).
- CORPUS-05 acceptance: `corpus init` writes genesis row 0 with self-signed corpus_admin RoleAssertion via the authorize()-gated path.
- 1 new SHACL TTL shape ships (promotion).
- `governance/` + `corpus/` package boundaries intact (D-04 dep-leak guard green).
- Phase 7 governance + corpus CLI surfaces visible in `folio-insights --help`.
</success_criteria>

<output>
Create `.planning/phases/07-governance-model-3-1/07-04b-SUMMARY.md` when done with: files created (1 src + 1 TTL + 4 CLI + 2 packages + 1 cli.py edit + 4 test files), test counts, the D-19 source-scan coverage list (4 command files), and a sample `folio-insights corpus init` JSON output.
</output>
</content>
</invoke>