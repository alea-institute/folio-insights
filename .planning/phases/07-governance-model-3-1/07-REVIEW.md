---
phase: 07-governance-model-3-1
reviewed: 2026-05-30T00:00:00Z
depth: standard
files_reviewed: 93
files_reviewed_list:
  - src/folio_insights/cli.py
  - src/folio_insights/corpus/__init__.py
  - src/folio_insights/corpus/cli/__init__.py
  - src/folio_insights/corpus/cli/corpus.py
  - src/folio_insights/governance/__init__.py
  - src/folio_insights/governance/authorize.py
  - src/folio_insights/governance/cli/__init__.py
  - src/folio_insights/governance/cli/_state.py
  - src/folio_insights/governance/cli/contest.py
  - src/folio_insights/governance/cli/export.py
  - src/folio_insights/governance/cli/promote.py
  - src/folio_insights/governance/cli/resolve_contest.py
  - src/folio_insights/governance/cli/retract.py
  - src/folio_insights/governance/cli/role_assert.py
  - src/folio_insights/governance/cli/role_revoke.py
  - src/folio_insights/governance/cli/show.py
  - src/folio_insights/governance/cli/supersede.py
  - src/folio_insights/governance/contest.py
  - src/folio_insights/governance/events.py
  - src/folio_insights/governance/log.py
  - src/folio_insights/governance/promote.py
  - src/folio_insights/governance/resolve_contest.py
  - src/folio_insights/governance/retract.py
  - src/folio_insights/governance/roles.py
  - src/folio_insights/governance/shape_validation.py
  - src/folio_insights/governance/shapes/contest_resolution_shape.ttl
  - src/folio_insights/governance/shapes/contest_shape.ttl
  - src/folio_insights/governance/shapes/governance_log_shape.ttl
  - src/folio_insights/governance/shapes/promotion_shape.ttl
  - src/folio_insights/governance/shapes/retraction_shape.ttl
  - src/folio_insights/governance/shapes/role_assertion_shape.ttl
  - src/folio_insights/governance/shapes/role_revocation_shape.ttl
  - src/folio_insights/governance/shapes/supersession_shape.ttl
  - src/folio_insights/governance/supersede.py
  - src/folio_insights/rfc/__init__.py
  - src/folio_insights/rfc/__main__.py
  - src/folio_insights/rfc/frontmatter.py
  - src/folio_insights/rfc/git_history.py
  - src/folio_insights/rfc/lint.py
  - src/folio_insights/shards/envelope.py
  - tests/corpus/__init__.py
  - tests/corpus/test_corpus_init_genesis.py
  - tests/governance/__init__.py
  - tests/governance/conftest.py
  - tests/governance/fixtures/__init__.py
  - tests/governance/fixtures/cascade_corpora.py
  - tests/governance/property/__init__.py
  - tests/governance/property/test_active_roles_stability.py
  - tests/governance/property/test_log_append_monotonic.py
  - tests/governance/test_active_roles_query.py
  - tests/governance/test_active_roles_rotation_safe.py
  - tests/governance/test_authorize_called_first.py
  - tests/governance/test_authorize_central.py
  - tests/governance/test_authorize_genesis_carve_out.py
  - tests/governance/test_cascade_preview_classification.py
  - tests/governance/test_cascade_preview_shared_builder.py
  - tests/governance/test_contest_resolution_shape.py
  - tests/governance/test_contest_shape.py
  - tests/governance/test_contested_state_records_votes.py
  - tests/governance/test_dep_leak_guard.py
  - tests/governance/test_distinguo_resolution.py
  - tests/governance/test_aporetic_acceptance.py
  - tests/governance/test_arbiter_can_resolve_contest.py
  - tests/governance/test_cli_three_way_distinct.py
  - tests/governance/test_cli_three_way_help_distinct.py
  - tests/governance/test_genesis_self_signed_carveout.py
  - tests/governance/test_governance_export_cli.py
  - tests/governance/test_governance_log_exports_as_provo.py
  - tests/governance/test_governance_log_is_append_only.py
  - tests/governance/test_governance_log_protocol_contract.py
  - tests/governance/test_governance_log_shape.py
  - tests/governance/test_grep_guard_three_way_disambiguation.py
  - tests/governance/test_last_admin_self_revocation_refused.py
  - tests/governance/test_no_majority_vote_resolution.py
  - tests/governance/test_preview_stale_refusal.py
  - tests/governance/test_promotion_requires_citation.py
  - tests/governance/test_promotion_shape.py
  - tests/governance/test_promotion_status_kind.py
  - tests/governance/test_retraction_shape.py
  - tests/governance/test_role_assertion_shape.py
  - tests/governance/test_role_assertion_signed.py
  - tests/governance/test_role_revocation_distinct_event.py
  - tests/governance/test_role_revocation_shape.py
  - tests/governance/test_signed_action_literal_13_values.py
  - tests/governance/test_unsigned_promotion_rejected.py
  - .planning/rfcs/RFC-TEMPLATE.md
findings:
  critical: 4
  warning: 5
  info: 3
  total: 12
status: issues_found
---

# Phase 07: Code Review Report

**Reviewed:** 2026-05-30T00:00:00Z
**Depth:** standard
**Files Reviewed:** 93
**Status:** issues_found

## Summary

Phase 7 delivers the governance substrate: a role-based authorization gate (`authorize()`), an append-only governance log, 8 SHACL shapes, 13 event classes, and CLI commands for the full governance surface. The architecture is sound and the D-04/D-16/D-19 discipline is structurally enforced. The following findings are defects, not style concerns.

---

## Critical Issues

### CR-01: `verify_attestation` is never called at the log layer for non-genesis role events — the "suspenders" half of the belt-and-suspenders signature verification is completely absent

**File:** `src/folio_insights/governance/log.py:254-263`

**Issue:** The docstring for `_handle_role_assertion_append` explicitly describes Phase 6 `verify_attestation` as the "suspenders" the CLI is supposed to wire before calling `log.append`. But searching the entire CLI surface (`role_assert.py`, `role_revoke.py`, `corpus/cli/corpus.py`) shows `verify_attestation` is **never called** before `log.append` for any role event. The log layer also explicitly documents that it skips signature verification:

```
# Non-genesis: Phase 6 verify_attestation (skipped here because
# the synchronous DidDocCache isn't wired through this method
# signature; the CLI in 07-04b passes it in. For 07-04a the
# belt-and-suspenders signer-must-be-admin check is the gate)
```

This means a corpus_admin can sign a role assertion with an **arbitrary private key** that does not correspond to their stated DID, and `log.append` will accept it as long as the signer DID holds corpus_admin in the active-roles query. The cryptographic binding between DID and signing key is never verified for role events in any CLI command. The integration test `test_role_assertion_signed.py` does call `verify_attestation` independently but that code path is not exercised by the CLI commands, and there is no gate in `log.append` that enforces it. The `InvalidSignature` exception type is defined but never raised.

**Fix:** Either (a) wire `verify_attestation` into `_handle_role_assertion_append` by passing the `DidDocCache` through the call chain (requires adding `cache` parameter to `append` or accepting it at `_handle_role_assertion_append`), or (b) require all CLI role commands to call `verify_attestation` before `log.append` and add an AST-level regression test parallel to `test_authorize_called_first.py` that enforces the ordering. Option (a) is preferable because it makes the check impossible to bypass at the library layer.

---

### CR-02: `InMemoryGovernanceLog.iter_events` is declared `async def` but used as an async generator — Protocol stub declares it as a regular non-async function returning `AsyncIterator`, creating a type contract mismatch

**File:** `src/folio_insights/governance/log.py:132` (Protocol) vs `423-426` (implementation)

**Issue:** The `GovernanceLog` Protocol declares:

```python
def iter_events(self, corpus: str) -> AsyncIterator[GovernanceEvent]: ...
```

But `InMemoryGovernanceLog.iter_events` is an **async generator**:

```python
async def iter_events(self, corpus: str) -> AsyncIterator[GovernanceEvent]:
    for event in self._by_corpus.get(corpus, []):
        yield event
```

An `async def` function with `yield` is an async generator function. Its calling convention is `async for ev in log.iter_events(corpus)` — which is what all callers use and what works at runtime. However, the Protocol stub `def iter_events(...) -> AsyncIterator` is a regular synchronous function that returns an `AsyncIterator` (a fundamentally different calling convention). The Protocol contract test `test_governance_log_protocol_contract.py` checks `inspect.isasyncgenfunction` OR `inspect.iscoroutinefunction` — so the test passes. But the Protocol stub is incorrect.

When Phase 13 wires a persistent backend, a backend author following the Protocol stub literally will implement a **synchronous** function that returns an async iterator (e.g., a class implementing `__aiter__`/`__anext__`) rather than an async generator. Callers using `async for ev in log.iter_events(corpus)` work with both, but the Protocol stub misleads implementors about the expected signature.

**Fix:** Change the Protocol stub to match the implementation:

```python
async def iter_events(self, corpus: str) -> AsyncIterator[GovernanceEvent]: ...
```

Or, if sync-returning-AsyncIterator is the intended Phase 13 pattern, make `InMemoryGovernanceLog.iter_events` a regular sync method returning an async iterator class. Choose one calling convention and make the Protocol stub match it.

---

### CR-03: The `_GENESIS_ACTION` constant is documented as imported by the corpus CLI (to enforce single-place action-name definition) but is not exported from `authorize.py` and is not imported by the corpus CLI — the corpus CLI hardcodes the string directly

**File:** `src/folio_insights/governance/authorize.py:87` and `src/folio_insights/corpus/cli/corpus.py:103`

**Issue:** The docstring for `authorize.py` at line 86-87 states:

> The CLI in 07-04b imports this constant so the corpus_init action name lives in ONE place across the codebase.

But `_GENESIS_ACTION = "corpus_init"` is `_`-prefixed (private), is not in `__all__`, and is not imported by `corpus/cli/corpus.py`. The corpus CLI passes the literal string `action="corpus_init"` directly at line 103. If the action name is ever changed in `authorize.py` (e.g., to `"genesis_init"` for disambiguation), `corpus.py` will silently pass the old name and the `authorize()` genesis carve-out will route to the standard role-based path, returning `Deny(reason="no_active_role")` for any corpus initialization attempt.

**Fix:** Export the constant and import it in the corpus CLI:

```python
# authorize.py
GENESIS_ACTION = "corpus_init"  # public, importable

__all__ = ["Allow", "AuthorizeResult", "Deny", "GENESIS_ACTION", "authorize"]
```

```python
# corpus/cli/corpus.py
from folio_insights.governance.authorize import GENESIS_ACTION
# ...
decision = await authorize(
    signer_did,
    action=GENESIS_ACTION,
    corpus=corpus_name,
    log=log,
    admin_did=admin_did,
)
```

---

### CR-04: `commit_cascade` in `retract.py` signs the `RetractionEvent` with a **placeholder** `over_content_hash` of `"0" * 64` and the signature is produced over a different hash — the committed signature does not cover the actual event content

**File:** `src/folio_insights/governance/retract.py:391-421`

**Issue:** In `commit_cascade`, a `placeholder_sig` is constructed with `over_content_hash="0" * 64` (line 399), then a `RetractionEvent` is built from it. `validate_retraction(event)` is called. Then `payload_hash = event.signature_payload().decode("utf-8")` is computed — this is the JCS-canonical hash of the event **excluding** the signature field. The real signature is produced with:

```python
sig = sign_attestation(
    content_hash=payload_hash,  # hash of event content (correct)
    ...
    now=now,
)
```

Then `signed_event = event.model_copy(update={"signature": sig})` replaces the placeholder. **So far so correct.**

However, `event.signature_payload()` includes the `position` field (per the docstring at `events.py:89`: "Note: `position` is INCLUDED in the payload because it is part of the event's identity"). At the time `event.signature_payload()` is called, `event.position == -1` (the default — `log.append` has not yet been called). After `log.append(signed_event)`, the persisted event has its position assigned (e.g., position=5). The `over_content_hash` in the committed signature therefore covers the content with `position=-1`, **not** the actual appended position. This means the signature cannot be independently verified against the event as it appears in the log (position=5).

This same pattern is used in **all** CLI commands (promote, contest, supersede, etc.) — they all sign before append, which means the signature always covers `position=-1`. This is a protocol-level integrity gap: the governance log's audit trail contains events where the stored signature does not cover the event's actual log position.

The `test_role_assertion_signed.py` integration test works around this by pre-computing the position (hardcoding `position=1` before signing), which the CLI commands do not do.

**Fix:** Either (a) assign a **provisional** position before signing by calling `await log.latest_position(corpus) + 1`, build the event with that position set, sign, then append with the pre-assigned position (the log will keep the explicit position since `event.position != -1`); or (b) remove `position` from `signature_payload()` (change the docstring and the field exclusion). Option (a) preserves the integrity intent; option (b) weakens it but is at least consistent. The design requires a clear decision documented in one place.

---

## Warnings

### WR-01: `GOVERNANCE_LOG` process-level singleton leaks between CLI tests — only `test_corpus_init_genesis.py` and `test_governance_export_cli.py` reset it; all other CLI-invocation tests (e.g., `test_unsigned_promotion_rejected.py`) share whatever corpus state a prior test left

**File:** `src/folio_insights/governance/cli/_state.py:23`

**Issue:** `GOVERNANCE_LOG` is a module-level singleton. Any `CliRunner.invoke` call that exercises `governance promote`, `governance contest`, etc., appends events to this shared instance. The documentation comment says "CliRunner.invoke in tests can reset it via a fixture if cross-test isolation is needed" — but no fixture resets it for the majority of governance CLI tests. The tests that do reset it (`test_corpus_init_genesis.py` autouse fixture, `test_governance_export_cli.py` explicit `_reset_log()`) are the exception. Tests that exercise CLI commands through `CliRunner` in isolation without resetting the singleton may produce false positives (a corpus initialized by a previous test still has rows, causing `corpus_already_initialized` Deny for a new test's authorize call) or false negatives (a test passes because role state from a prior test satisfies authorization it shouldn't have).

**Fix:** Add an `autouse` session- or function-scoped fixture in `tests/governance/conftest.py` that resets `GOVERNANCE_LOG` between tests:

```python
@pytest.fixture(autouse=True)
def _reset_governance_singleton():
    from folio_insights.governance.cli import _state
    from folio_insights.governance.log import InMemoryGovernanceLog
    _state.GOVERNANCE_LOG = InMemoryGovernanceLog()
    yield
    _state.GOVERNANCE_LOG = InMemoryGovernanceLog()
```

---

### WR-02: The `promote_cmd` PromotionEvent is signed with a placeholder `over_content_hash` in the signature while D-20/D-21 validators run — `validate_promotion` is called on an event whose signature slot has `over_content_hash="0" * 64`, meaning the validator operates on an event that could not survive a verify pass

**File:** `src/folio_insights/governance/cli/promote.py:119-145`

**Issue:** The CLI builds `placeholder_sig` with `over_content_hash="0" * 64`, constructs the `PromotionEvent`, and then calls `validate_promotion(event, store=store)` before signing. This is architecturally correct for the D-20/D-21 cross-shard checks (those only read `cited_iris` and `new_status`, not the signature). However, the `validate_promotion` call also receives the full event; a future validator that reads `event.signature.over_content_hash` to verify anything about the signing intent would receive the bogus placeholder. The structural pattern of "validate before signing" is sound for this phase's validators, but the placeholder hash at `"0" * 64` is a silent integrity gap that could mislead a future auditor. The same pattern appears identically in `contest_cmd`, `supersede_cmd`, `resolve_contest_cmd`, `retract.py::commit_cascade`, `role_assert_cmd`, and `role_revoke_cmd`.

**Fix:** Document explicitly in `_BaseEvent.signature_payload()` and in the CLI pattern comment that `validate_*` functions MUST NOT read `over_content_hash` from the placeholder signature. Alternatively, compute the real payload hash first and pass it as part of the placeholder construction, deferring only the ed25519 signature bytes:

```python
# Compute the payload hash over a zero-signature placeholder
# (position=-1 at this point; see CR-04 for the position issue)
draft_event = PromotionEvent(corpus=corpus, signature=placeholder_sig, ...)
payload_hash = draft_event.signature_payload().decode("utf-8")
# Build the real signature
sig = sign_attestation(content_hash=payload_hash, ...)
signed_event = draft_event.model_copy(update={"signature": sig})
await validate_promotion(signed_event, store=store)
await log.append(signed_event)
```

This orders validation after signing rather than before, which eliminates the placeholder-during-validation window.

---

### WR-03: The `--apply` mode of `retract_cmd` hardcodes a fresh `InMemoryShardStore()` — the store used for the `PreviewStale` hash check is always empty, making the hash comparison semantically vacuous

**File:** `src/folio_insights/governance/cli/retract.py:133`

**Issue:** In `retract_cmd`, `store = InMemoryShardStore()` creates an empty store. In `--apply` mode (lines 165-188), `commit_cascade(preview, store=store, log=log, ...)` is called. Inside `commit_cascade`, `build_cascade_preview` re-runs with the empty store. Since `_iter_store_items(store)` returns `[]` for an empty store (no `_d` attribute entries), the re-run produces a preview with zero dependents and a hash computed over that empty state.

The original preview (loaded from the JSON file) was built in the `--preview` run, which used a **different** empty store too. So both previews always hash to the same value (no dependents, same `log_latest_position`), meaning `PreviewStale` will **never fire** in the `--apply` flow via the CLI — even if the corpus state changed between preview and apply. The D-17 race detection is effectively disabled at the CLI layer.

The `test_preview_stale_refusal.py` tests work because they call `build_cascade_preview` and `commit_cascade` directly with the **same seeded store**, bypassing the CLI. The CLI tests for D-17 are absent.

**Fix:** The CLI must provide a way to pass a pre-populated ShardStore. For Phase 7, the simplest fix is to at minimum document this limitation prominently and add a test that exercises the CLI `--apply` flow against the shared `InMemoryShardStore` singleton (which should be seeded the same way as `tests/governance/fixtures/cascade_corpora.py::seed_cascade_corpus`). For Phase 13, the persistent ShardStore backend removes this issue structurally.

---

### WR-04: `supersede.py::validate_supersession` only enforces IRI resolvability when BOTH sides are present or when asymmetrically present — if BOTH IRIs are absent from the store, the check is silently skipped

**File:** `src/folio_insights/governance/supersede.py:70-83`

**Issue:** The resolvability check reads:

```python
old_present = await store.get(event.old_shard_iri)
new_present = await store.get(event.new_shard_iri)
if (old_present is not None) and (new_present is None):
    raise ValueError(...)
if (new_present is not None) and (old_present is None):
    raise ValueError(...)
```

If both `old_shard_iri` and `new_shard_iri` are absent from the store, neither condition fires and the function returns without error. This is the documented intent ("skip-when-empty matches the 07-04b promote validator's behavior on empty in-memory stores") but it means a `SupersessionEvent` can be appended for two completely fabricated IRIs with no validation error. The comment says "the SHACL belt is the authoritative gate" — but `validate_supersession_shape` does not check IRI resolvability either (it only checks non-empty and old != new). No layer validates that the referenced shards exist when both are absent.

**Fix:** The skip-when-empty discipline is defensible for Phase 7, but the code should log a warning (or raise an explicit `ValueError`) when the store is non-empty AND both IRIs are absent simultaneously:

```python
if old_present is None and new_present is None:
    # Check if the store is non-empty to distinguish "empty store" from
    # "both IRIs fabricated in a populated store"
    any_entry = next(iter(_iter_store_items(store)), None)
    if any_entry is not None:
        raise ValueError(
            f"Both old_shard_iri ({event.old_shard_iri!r}) and "
            f"new_shard_iri ({event.new_shard_iri!r}) are absent from a "
            f"non-empty ShardStore — possible fabricated supersession."
        )
```

---

### WR-05: The `governance_log_shape.ttl` SPARQL gap-detection query uses `HAVING (MAX(?p) != COUNT(?e) - 1)` which mixes aggregate types — SPARQL integer arithmetic on `COUNT` aggregate may produce type-coercion behavior that differs from raw integer subtraction in some triple store implementations

**File:** `src/folio_insights/governance/shapes/governance_log_shape.ttl:82-93`

**Issue:** The gap-detection SPARQL constraint:

```sparql
HAVING (MAX(?p) != COUNT(?e) - 1)
```

In SPARQL 1.1, `COUNT(?e)` returns an `xsd:integer` and `MAX(?p)` returns the same type as the values (also `xsd:integer` since positions are typed). The subtraction `COUNT(?e) - 1` should work under pyshacl/rdflib, and testing confirms it does. However, this relies on SPARQL arithmetic over aggregate values in a `HAVING` clause, which is evaluated after grouping. If the grouped result for an empty log (zero events) were reached, `MAX(?p)` would be unbound and `COUNT(?e)` would be 0, making `HAVING (UNDEF != -1)` — which pyshacl handles as "no violation" because the `HAVING` clause filters groups, and an unbound MAX over an empty set does not produce a group to filter. This is correct behavior but is fragile; a log with zero events never reaches the `HAVING` clause because there are no `?e` bindings, making the query vacuously safe. The risk is real only if pyshacl changes how it handles unbound aggregates. The shape does not document this edge case.

**Fix:** Add a comment to the SPARQL explaining the empty-log vacuous safety and confirm it with a test that explicitly verifies `validate_governance_log_shape([], genesis_event)` conformance (the empty-history genesis test already exists in `test_governance_log_shape.py::test_empty_history_with_genesis_conforms`, so this is already covered — add a comment in the TTL referencing the test).

---

## Info

### IN-01: `_GENESIS_ACTION` is `_`-prefixed (private) but is referenced in the public API docstring as importable by the CLI — a public-private naming inconsistency

**File:** `src/folio_insights/governance/authorize.py:87`

**Issue:** The docstring at lines 86-87 says "The CLI in 07-04b imports this constant so the corpus_init action name lives in ONE place." The constant is named `_GENESIS_ACTION` (private). This is documented intent that was never implemented (see CR-03). If the export is added (as recommended in CR-03), the name should be `GENESIS_ACTION` (public) and documented consistently.

**Fix:** Rename to `GENESIS_ACTION`, add to `__all__`, and remove the private `_` prefix.

---

### IN-02: The `promote_cmd` uses `type: ignore[arg-type]` on `new_status` when constructing `PromotionEvent` — the Click Choice type does not narrow to the Pydantic Literal, requiring a cast that could be removed

**File:** `src/folio_insights/governance/cli/promote.py:138`

**Issue:**
```python
event = PromotionEvent(
    ...
    new_status=status,  # type: ignore[arg-type]
    ...
)
```

Click returns `str` from `click.Choice(...)`, which is too wide for `PromotionStatus = Literal["per_se_nota_quoad_nos", "demonstrable", "authority_only"]`. This is a legitimate type system gap. The same pattern appears in `resolve_contest_cmd` (line 118), `role_assert_cmd` (line 114), and `role_revoke_cmd` (line 118 and 125). These are not bugs but could be replaced with explicit `cast()` calls or typed narrowing.

**Fix:** Use `cast(PromotionStatus, status)` where the `type: ignore` is used, which is more semantically explicit and permits future static analysis tools to verify the narrowing without suppressing the check entirely.

---

### IN-03: The `retract.py::_iter_store_items` accesses the `_d` private attribute of `InMemoryShardStore` directly — this is a D-04 boundary duck-type bypass that will break silently if the store's internal attribute is renamed

**File:** `src/folio_insights/governance/retract.py:191-203`

**Issue:**
```python
def _iter_store_items(store: Any) -> list[tuple[str, Any]]:
    d = getattr(store, "_d", None)
    if d is None:
        return []
    return list(d.items())
```

This reaches into the `InMemoryShardStore` private implementation detail `_d`. The comment documents this as "Phase 7 in-memory" and notes Phase 13 will replace it with SPARQL. However, if `InMemoryShardStore` renames `_d` to `_store` or `_data` (a private name, so no stability guarantee), `_iter_store_items` silently returns empty and the cascade preview always shows zero dependents — the same vacuous behavior as WR-03.

**Fix:** Add an `iter_all` or `all_items` method to the `ShardStore` Protocol and `InMemoryShardStore`, gated by the D-04 boundary (it's a read-only query). This is a one-line Phase 7 addition:

```python
# In ShardStore Protocol
async def all_items(self) -> list[tuple[str, Any]]: ...

# In InMemoryShardStore
async def all_items(self) -> list[tuple[str, Any]]:
    return list(self._d.items())
```

Then `_iter_store_items` becomes `await store.all_items()` with no private-attribute access.

---

_Reviewed: 2026-05-30T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
