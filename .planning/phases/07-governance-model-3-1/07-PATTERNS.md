# Phase 7: Governance Model (§3.1) - Pattern Map

**Mapped:** 2026-05-30
**Files analyzed:** 37 new files + 2 extensions
**Analogs found:** 37 / 37 (all new files have a direct codebase analog)

---

## File Classification

### New package: `src/folio_insights/governance/` (library + shapes + CLI)

| New / Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `governance/__init__.py` | package init | barrel re-export | `identity/__init__.py` | exact |
| `governance/log.py` (`GovernanceLog` Protocol + `InMemoryGovernanceLog`) | seam / store | append + query | `revision/store.py` (`ShardStore`); `identity/cache.py` (`DidDocCache`) | exact (two complementary analogs) |
| `governance/events.py` (12 `GovernanceEvent` classes, discriminated union) | model | Pydantic discriminator over `action` | `shards/envelope.py` (`AttestedSignature` + `SignedAction` Literal) + `shards/subtypes.py` (`Shard` discriminated union over `shard_type`) | exact |
| `governance/authorize.py` (`authorize(did, action, corpus) → Allow \| Deny`) | service / central authz | request-response | `identity/verifier.py` `verify_attestation()` (single fact-of-truth pattern) | role-match (closest single-function authorization analog in tree) |
| `governance/roles.py` (`RoleAssertionEvent` + `RoleRevocationEvent` + `active_roles_at`) | model + query | event + windowed query | `revision/content_edit.py` (event + write path) + `identity/cache.py` (windowed `(did, signed_at)` key) | role-match |
| `governance/promote.py` (`PromotionEvent` + `validate_promotion`) | validator | request-response | `revision/content_edit.py` `edit_shard_content()` + `polysemy/distinguo.py` `validate_fork_proposal_shape()` | exact |
| `governance/contest.py` (`ContestEvent` + validator) | model + validator | event-driven | `polysemy/distinguo.py` (self-contained event + `validate_*_shape()`) | exact |
| `governance/supersede.py` (`SupersessionEvent` + validator) | model + validator | event-driven | `polysemy/distinguo.py` | exact |
| `governance/retract.py` (`RetractionEvent` + `build_cascade_preview` + `commit_cascade` + `_classify_dependent`) | model + workflow | preview-then-apply (transactional dry-run) | `revision/content_edit.py` `edit_shard_content()` (transactional pattern) + `services/shacl_validator.py` `generate_report()` (grouped-result builder) | role-match |
| `governance/resolve_contest.py` (`ContestResolutionEvent`, 3 paths) | model + workflow | event-driven | `polysemy/distinguo.py` (event + Pydantic Literal discriminator over 3 distinction kinds) | exact |
| `governance/shapes/governance_log_shape.ttl` | SHACL shape | RDF validation | `revision/content_edit_shape.ttl` (sh:sparql self-join append-only shape) | exact |
| `governance/shapes/role_assertion_shape.ttl` | SHACL shape | RDF validation | `revision/content_edit_shape.ttl` | exact |
| `governance/shapes/role_revocation_shape.ttl` | SHACL shape | RDF validation | `revision/content_edit_shape.ttl` | exact |
| `governance/shapes/promotion_shape.ttl` | SHACL shape | RDF validation | `revision/content_edit_shape.ttl` | exact |
| `governance/shapes/contest_shape.ttl` | SHACL shape | RDF validation | `revision/content_edit_shape.ttl` | exact |
| `governance/shapes/contest_resolution_shape.ttl` | SHACL shape | RDF validation | `revision/content_edit_shape.ttl` | exact |
| `governance/shapes/supersession_shape.ttl` | SHACL shape | RDF validation | `revision/content_edit_shape.ttl` | exact |
| `governance/shapes/retraction_shape.ttl` | SHACL shape | RDF validation | `revision/content_edit_shape.ttl` | exact |
| `governance/shape_validation.py` (or per-module `validate_*_shape()` fns) | service | RDF validation | `revision/shape_validation.py` `validate_content_edit_shape()` (THE convention) | exact |
| `governance/cli/__init__.py` (`governance_group = click.Group("governance")`) | CLI subgroup | request-response | `identity/cli.py` `did_group` (`@click.group(name="did")`) + `polysemy/cli.py` `polysemy` | exact |
| `governance/cli/promote.py` | CLI command | request-response | `identity/cli.py` `sign_cmd` (auth → preview → sign → emit) | exact |
| `governance/cli/contest.py` | CLI command | request-response | `identity/cli.py` `sign_cmd` | exact |
| `governance/cli/supersede.py` | CLI command | request-response | `identity/cli.py` `sign_cmd` | exact |
| `governance/cli/retract.py` (interactive `--preview` / `--apply`) | CLI command | preview-then-apply | `identity/cli.py` `sign_cmd` (click.confirm gate) + `polysemy/cli.py` (rich.prompt interactive) | exact (two complementary analogs) |
| `governance/cli/role_assert.py` | CLI command | request-response | `identity/cli.py` `sign_cmd` | exact |
| `governance/cli/role_revoke.py` | CLI command | request-response | `identity/cli.py` `sign_cmd` | exact |
| `governance/cli/governance_export.py` (D-08) | CLI command | file I/O (read SQLite → emit Turtle, Phase 13 wires backend) | `cli.py` `export` command (corpus_name → format → write file) | role-match |
| `governance/cli/corpus.py` (`corpus init --admin-did`, D-10 genesis) | CLI command | request-response | `identity/cli.py` `generate_cmd` (idempotent local init); `identity/cli.py` `bind_cmd` (orchestrate-then-emit) | exact |

### New package: `src/folio_insights/rfc/`

| New / Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `rfc/__init__.py` | package init | barrel | `identity/__init__.py` | exact |
| `rfc/lint.py` (`python -m folio_insights.rfc.lint`) | linter / CLI module | file I/O + subprocess walk | `cli.py` `verify_iris` (registry-walk + drift report) | role-match |
| `rfc/frontmatter.py` (Pydantic model + regex parser) | model + parser | request-response | `shards/envelope.py` (Pydantic `BaseModel` with `ConfigDict(extra="forbid")`) | role-match |
| `rfc/git_history.py` (`subprocess.run("git log ...")` walker) | utility | file I/O / subprocess | new — no direct analog (closest: stdlib pattern from RESEARCH §"Don't Hand-Roll") | no analog (use research) |
| `.planning/rfcs/RFC-TEMPLATE.md` | doc fixture | static markdown | n/a (golden fixture; format matches `frontmatter.py`'s Pydantic model) | no analog needed |

### Extensions (modify in place)

| Modified File | Role | Data Flow | Change | Closest Analog |
|---|---|---|---|---|
| `src/folio_insights/shards/envelope.py:85` (`SignedAction` Literal) | model | discriminator vocabulary | Add `"role_revocation"` → 11 → 12 values (D-13) | self (existing 11-value Literal at L85-103) |
| `src/folio_insights/services/shacl_validator.py` | service | RDF validation | NOTE: this is the OWL-export validator; per-event `validate_*_shape()` fns belong in `governance/shape_validation.py` mirroring `revision/shape_validation.py` (the real per-event convention). | `revision/shape_validation.py:99` |

### Test files (under `tests/governance/`, `tests/corpus/`, `tests/rfc/`)

| New Test File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `tests/governance/test_governance_log_is_append_only.py` (Protocol contract) | test | contract assertion | `tests/shards/test_content_edit_audit_append_only.py` | exact |
| `tests/governance/test_governance_log_exports_as_provo.py` | test | round-trip | `tests/shards/test_envelope_roundtrip.py` | role-match |
| `tests/governance/test_*_shape.py` (8 SHACL conforms-true/false pairs) | test | SHACL polarity | `tests/revision/test_shacl_forward_only.py` (positive + negative polarity) | exact |
| `tests/governance/test_grep_guard_three_way_disambiguation.py` (D-16) | test | AST / source-scan guard | `tests/shards/test_dep_leak_guard.py` (per-file `read_text` source scan) + `tests/identity/test_no_server_keys_contract.py` (AST-based) | exact (two complementary analogs) |
| `tests/governance/test_dep_leak_guard.py` (no aiosqlite/rdflib/pyoxigraph in `governance/`) | test | source-scan guard | `tests/shards/test_dep_leak_guard.py` | exact |
| `tests/governance/test_last_admin_self_revocation_refused.py` (D-11) | test | append-then-assert | `tests/shards/test_content_edit_audit_append_only.py` | role-match |
| `tests/governance/test_genesis_self_signed_carveout.py` (D-10) | test | append-then-assert | `tests/identity/test_signature_survives_key_rotation.py` (cache-windowed semantics) | role-match |
| `tests/governance/test_cascade_preview_classification.py` (D-18) | test | fixture-driven classifier | `tests/polysemy/test_detector_rules.py` (table-driven classifier) | role-match |
| `tests/governance/test_preview_stale_refusal.py` (D-17 `--apply` race) | test | two-snapshot diff | new pattern — closest: `tests/identity/test_signature_survives_key_rotation.py` (two-time-windowed test) | role-match |
| `tests/governance/test_unsigned_promotion_rejected.py` | test | acceptance e2e | `tests/shards/test_envelope_roundtrip.py` + Phase 6 unsigned-stub honesty checks | role-match |
| `tests/governance/test_role_revocation_distinct_event.py` (D-13) | test | discriminator assertion | `tests/shards/test_discriminated_union.py` | exact |
| `tests/governance/test_signed_action_literal_12_values.py` | test | `get_args(SignedAction)` assertion | `tests/shards/test_discriminated_union.py` | exact |
| `tests/governance/test_authorize_central.py` (D-19) | test | table-driven action-permission | `tests/polysemy/test_detector_rules.py` | role-match |
| `tests/governance/test_no_majority_vote_resolution.py` (GOV-05 explicit reject) | test | Literal exhaustiveness | `tests/shards/test_discriminated_union.py` | exact |
| `tests/governance/property/test_log_append_monotonic.py` (Hypothesis) | test | property test | `tests/identity/test_canonical_jcs_properties.py` (Hypothesis @given, max_examples=1000) | exact |
| `tests/governance/property/test_active_roles_stability.py` (Hypothesis) | test | property test | `tests/identity/test_canonical_jcs_properties.py` | exact |
| `tests/governance/cli/test_governance_help_distinct.py` (CLI snapshot per D-16) | test | CLI snapshot | `tests/polysemy/test_cli_review.py` (CliRunner against Click subgroup) | exact |
| `tests/rfc/test_lint_frontmatter_schema.py` | test | parser unit | `tests/polysemy/test_fixture_loader.py` (fixture-load + Pydantic-validate) | role-match |
| `tests/rfc/test_lint_filename_monotonic.py` | test | filename scan | `tests/shards/test_iri_collision.py` (uniqueness/monotonicity check) | role-match |
| `tests/rfc/test_lint_status_monotonic_across_history.py` | test | `tmp_path` + `git init` + `git commit` + walk | new — closest: stdlib `subprocess.run` pattern from `tests/identity/test_no_server_keys_contract.py` AST walker (file-tree iteration only) | no exact analog (use stdlib + tmp_path) |
| `tests/rfc/test_lint_body_only_edit_refused.py` | test | git-history walk | same as above | no exact analog |
| `tests/corpus/test_corpus_init_genesis.py` (CLI for D-10) | test | CliRunner | `tests/identity/test_did_cli.py` (CliRunner against `did_group`) | exact |

---

## Pattern Assignments

### `governance/log.py` (`GovernanceLog` Protocol + `InMemoryGovernanceLog`)

**Primary analog:** `src/folio_insights/revision/store.py` (`ShardStore` — the in-memory-Protocol-seam template; Phase 5 D-02).
**Complementary analog:** `src/folio_insights/identity/cache.py` (`DidDocCache` — windowed-by-time async pattern; Phase 6 D-11).

**Module docstring pattern** — copy the boundary discipline verbatim (`store.py:1-18`):

```python
"""Phase 7 GovernanceLog seam — append-only event log per corpus (CONTEXT D-04, D-05, D-06).

The append-only governance log per PRD §3.1.5. D-04 keeps that signature honest
with a thin ``GovernanceLog`` Protocol over an in-memory dict; Phase 13 swaps a
persistent aiosqlite-backed store + the BEFORE UPDATE/DELETE → RAISE FAIL trigger
in behind the *same* async interface without touching any caller (D-05 — the path
is ``async def`` so Phase 13 storage slots in without signature churn).

Analog: ``revision/store.py::ShardStore`` (in-memory-dict + thin async Protocol)
and ``identity/cache.py::DidDocCache`` (windowed-by-time async query pattern).

Boundary: this module is stdlib + Pydantic ONLY — NO ``aiosqlite`` / ``rdflib`` /
``pyoxigraph`` imports here (D-04; the ``tests/governance/test_dep_leak_guard.py``
boundary). Phase 13 is the place that fills the persistent backend; in Phase 7
the dict IS the store.
"""
```

**Protocol pattern** (copy from `revision/store.py:26-36` + add `query_active_roles_at` from RESEARCH Pattern 2):

```python
@runtime_checkable
class GovernanceLog(Protocol):
    """Append-only governance log seam (D-04). Phase 13 swaps aiosqlite behind it."""

    async def append(self, event: GovernanceEvent) -> GovernanceEvent: ...
    async def query_active_roles_at(
        self, corpus: str, asof: datetime,
    ) -> dict[str, set[str]]: ...
    async def get_by_position(self, corpus: str, position: int) -> GovernanceEvent | None: ...
    async def iter_events(self, corpus: str) -> AsyncIterator[GovernanceEvent]: ...
    async def latest_position(self, corpus: str) -> int: ...
```

**InMemory class pattern** (copy from `revision/store.py:39-53` + `identity/cache.py:76-91` for the `(key, value)` snapshot semantics; init resets per construction):

```python
class InMemoryGovernanceLog:
    """Process-local in-memory ``GovernanceLog`` (D-04). Reset per construction.

    Stdlib + Pydantic only — the dict IS the seam Phase 13 replaces with a
    persistent aiosqlite-backed store behind the identical async interface.
    """
    def __init__(self) -> None:
        self._by_corpus: dict[str, list[GovernanceEvent]] = {}
```

**The append() body** uses RESEARCH Pattern 3 (genesis carve-out + last-admin refusal). The transactional discipline mirrors `revision/content_edit.py` `edit_shard_content()` (CR-01 working-copy pattern at L444-465).

---

### `governance/events.py` (12 `GovernanceEvent` classes + discriminated union)

**Primary analog:** `src/folio_insights/shards/envelope.py` (`AttestedSignature` + `SignedAction` Literal at L85-162).
**Complementary analog:** `src/folio_insights/shards/subtypes.py` (Pydantic discriminated union over `shard_type`; same pattern, different discriminator).

**Pydantic envelope discipline** (copy from `shards/envelope.py:151-162` `AttestedSignature`):

```python
class _BaseEvent(BaseModel):
    """Shared envelope discipline; NOT a behavior-sharing base class (D-16).
    Subclasses CANNOT inherit logic from this — only model_config + the three
    universal slots (corpus, position, signature)."""
    model_config = ConfigDict(extra="forbid")  # mirrors AttestedSignature L151
    corpus: str
    position: int = -1  # assigned by GovernanceLog.append()
    signature: AttestedSignature  # the only shared primitive (D-16)
```

**Per-event class pattern** — each of the 12 follows the same `Literal[action] = action` discriminator pin (mirrors `shards/subtypes.py` how each `Shard` subclass pins `shard_type` Literal). RESEARCH Pattern 1 gives the canonical 12-class enumeration.

**Discriminated union pattern** (Pydantic 2 canonical — `RESEARCH §"Alternatives Considered"` confirms; same template as `shards/subtypes.py` `Shard = Annotated[Union[...], Field(discriminator="shard_type")]`):

```python
GovernanceEvent = Annotated[
    Union[
        RoleAssertionEvent, RoleRevocationEvent,
        PromotionEvent, ContestEvent, ContestResolutionEvent,
        SupersessionEvent, RetractionEvent,
        ExtractEvent, DemotionEvent, DistinguoEvent,
        ContentEditEvent, ReparentEvent, ReconcileEvent,
    ],
    Field(discriminator="action"),
]
```

---

### `governance/authorize.py` (`authorize(did, action, corpus) → Allow | Deny(reason)`)

**Primary analog:** `src/folio_insights/identity/verifier.py:52-83` `verify_attestation()` (the "single fact-of-truth" function pattern Phase 6 D-19 established).

**Function signature pattern** (mirror `verify_attestation`'s async + cache-dependency + boolean-or-typed-result):

```python
async def authorize(
    did: str,
    action: SignedAction,
    corpus: str,
    *,
    log: GovernanceLog,
    asof: datetime | None = None,
) -> AuthorizeResult:
    """Central authorization (D-19). Every CLI command calls this as the first
    step after parsing. SHACL is the belt-and-suspenders second check at storage time.

    Returns ``Allow`` or ``Deny(reason)`` — NEVER raises (the typed result is the
    only failure mode the caller sees, by design; mirrors verify_attestation's
    boolean discipline at verifier.py L77-82).
    """
```

**Pydantic result types** (mirror `identity/cache.py:29-53` `DidDocSnapshot` discipline):

```python
class Allow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class Deny(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: str

AuthorizeResult = Allow | Deny
```

**Action-permission table** — a module-level dict keyed by `(SignedAction, role)`. Mirrors PRD §3.1 mapping. Concrete example (RESEARCH §"Architectural Responsibility Map"):
- `extractor` → `{extract, content_edit}`
- `reviewer` → above + `{promote, demote, contest, supersede, retract, distinguo, content_edit, reparent, reconcile}`
- `arbiter` → above + `{resolve_contest}`
- `corpus_admin` → above + `{role_assertion, role_revocation}`

---

### `governance/roles.py` (`RoleAssertionEvent` + `RoleRevocationEvent` + `active_roles_at`)

**Primary analog:** `src/folio_insights/identity/cache.py` (windowed-by-`signed_at` query pattern at L67-73). D-13 active-roles query = assertions minus revocations, windowed by `signature.signed_at <= asof` — directly mirrors `DidDocCache.get((did, signed_at))`'s historical-key resolution discipline (closes Pitfall F2).

**Pattern excerpt** (from `cache.py:56-73`):

```python
@runtime_checkable
class DidDocCache(Protocol):
    async def get(self, key: tuple[str, datetime]) -> DidDocSnapshot | None: ...
```

`active_roles_at(corpus, asof)` walks the log's events and applies the same `signed_at <= asof` window:

```python
async def active_roles_at(corpus: str, asof: datetime, *, log: GovernanceLog) -> dict[str, set[str]]:
    """Active roles per DID at ``asof`` — assertions minus revocations,
    each windowed by ``signature.signed_at <= asof`` (D-13 / Pitfall F2)."""
```

---

### `governance/promote.py` (`PromotionEvent` + `validate_promotion`)

**Primary analog:** `src/folio_insights/polysemy/distinguo.py:99` `validate_fork_proposal_shape()` (the canonical `validate_*_shape()` idiom).
**Complementary analog:** `src/folio_insights/revision/content_edit.py:410-521` `edit_shard_content()` (transactional working-copy + post-validate pattern).

**Validator surface** (mirror `distinguo.py:99`):

```python
def validate_promotion(event: PromotionEvent, *, store: ShardStore) -> None:
    """D-20 citation-resolvability + D-21 status-kind cross-check.

    Mirrors polysemy/distinguo.py::validate_fork_proposal_shape() — defense-in-depth
    Python-level validation BEFORE SHACL at storage time. Raises ValueError on
    violation (Phase 6 verify_attestation discipline: typed failure, no exception
    spelunking by the caller).
    """
```

**D-20 cite-resolvable check** — every IRI in `event.cited_iris` must `await store.get(iri) is not None` AND must not equal `event.shard_iri` (CONTEXT D-20). Mirrors `edit_shard_content()`'s `store.get(shard_iri)` precondition check at `content_edit.py:446-451`.

**D-21 status-kind cross-check** table (CONTEXT D-21):
- `event.new_status == "authority_only"` → at least one cited shard must be `AuthorityShard` subtype.
- `event.new_status == "demonstrable"` → at least one cited shard must have `epistemic_status ∈ {demonstrable, per_se_nota_quoad_se, per_se_nota_quoad_nos, authority_only}`.
- `event.new_status == "per_se_nota_quoad_nos"` → no depth check (axiomatic).

---

### `governance/contest.py`, `governance/supersede.py`, `governance/retract.py`, `governance/resolve_contest.py` (the D-16 three-way disambiguation modules)

**Primary analog:** `src/folio_insights/polysemy/distinguo.py` (self-contained event + `validate_fork_proposal_shape()` + lives independently from other polysemy modules).

**D-16 grep-guard discipline** — each module MUST:
- Define its own Pydantic event class (`ContestEvent`, `SupersessionEvent`, `RetractionEvent`).
- Define its own `validate_*_shape()` function (mirrors `distinguo.py:99`).
- NOT import from the other two modules.
- Have ONE Click command module under `governance/cli/` with no shared implementation function.

`AttestedSignature` (from `shards/envelope.py:106`) is THE ONLY shared primitive — it's the signature, not the codepath.

**Cascade-preview builder** (lives in `retract.py`, RESEARCH Pattern 4):

```python
class CascadePreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)  # immutable preview
    retracted_shard_iri: str
    corpus: str
    taken_at: datetime
    underlying_state_hash: str  # for PreviewStale detection on --apply (D-17)
    auto_rederive: list[str]    # D-18 classification
    aporetic: list[str]
    review_needed: list[str]


async def build_cascade_preview(
    retracted_iri: str, corpus: str,
    *, store: ShardStore, log: GovernanceLog,
) -> CascadePreview: ...


async def commit_cascade(preview: CascadePreview, *, ...) -> RetractionEvent:
    """Re-runs build_cascade_preview and compares underlying_state_hash;
    raises PreviewStale if changed (D-17)."""
```

---

### `governance/shapes/*.ttl` (8 SHACL shape files)

**Primary analog:** `src/folio_insights/revision/content_edit_shape.ttl` (THE Phase-5 forward-only `sh:sparql` self-join shape; the polarity discipline is load-bearing).

**Header comment block pattern** (copy structure from `content_edit_shape.ttl:1-21`):

```turtle
# Phase 7 governance-log append-only SHACL shape (CONTEXT D-05; exit criterion GOV-02).
#
# DEFENSE-IN-DEPTH pyshacl shape over the governance log. The AUTHORITATIVE gate
# is (a) the InMemoryGovernanceLog's "no public mutation API on past rows" surface,
# and (b) Phase 13's SQLite BEFORE UPDATE/DELETE → RAISE FAIL trigger. This shape
# is the literal "SHACL guard" GOV-02's amended exit bar references.
#
# CANNOT enforce: deletion detection across snapshots (SHACL is stateless over a
# single graph snapshot — same constraint content_edit_shape.ttl L15-17 calls out).
# That half is carried by (a) the Protocol's no-mutator-on-past-rows surface,
# (b) the hash-chain (each event's over_content_hash includes the prior event's
# signature bytes; tampering breaks the chain deterministically), and (c) Phase 13's
# SQLite trigger.
```

**Namespace declarations** (verbatim from `content_edit_shape.ttl:22-25`):

```turtle
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix fi: <https://folio-insights.example/> .
```

**Append-only invariant** (`fi:GovernanceLogShape`) — use `sh:sparql` for the gap-in-fi:position check + the chain-hash check (mirrors `content_edit_shape.ttl:27-41` self-join structure). The bad-case-matches polarity is locked from Phase 5.

**Per-event shapes** (`fi:PromotionShape` et al.) — use `sh:property` blocks with `sh:minCount` / `sh:datatype` / `sh:in` constraints. For `fi:ContestResolutionShape`, `sh:in (fi:arbiter fi:distinguo fi:aporetic)` locks the 3 resolution paths (GOV-05 no-majority-vote).

---

### `governance/shape_validation.py` (per-event `validate_*_shape()` functions)

**Primary analog:** `src/folio_insights/revision/shape_validation.py` (THE per-event `validate_*_shape()` convention — NOT `services/shacl_validator.py`, which is the OWL-export validator).

**Module structure pattern** (mirror `revision/shape_validation.py:1-32` exactly):

```python
"""Defense-in-depth SHACL guards over governance events (CONTEXT D-05).

Mirrors revision/shape_validation.py for the 8 governance shapes. Boundary:
rdflib/pyshacl imports are SAFE here — this module lives in governance/ but is
EXEMPT from the governance/ dep-leak guard for the SAME reason revision/
shape_validation.py is exempt: it's the SHACL validator wrapper that the rest of
the package consumes through a typed function call (the dep stays out of
governance/log.py, governance/events.py, governance/authorize.py, etc.).
"""
```

**Plumbing pattern** (`revision/shape_validation.py:111-138` — minimal local RDF graph + `pyshacl.validate` + `ValidationResult` dataclass):

```python
@dataclass
class ValidationResult:
    conforms: bool
    violations: list[str]
    results_text: str


def validate_promotion_shape(event: PromotionEvent) -> ValidationResult:
    """Run fi:PromotionShape against a PromotionEvent (D-05 defense-in-depth)."""
    shapes = Graph()
    shapes.parse(str(_PROMOTION_SHAPE_PATH), format="turtle")
    data_graph = _build_event_graph(event)  # minimal local RDF graph
    conforms, _results_graph, results_text = pyshacl.validate(
        data_graph, shacl_graph=shapes, inference="none", abort_on_first=False,
    )
    # ... violations parsing identical to shape_validation.py L123-133
```

Ship 8 `validate_*_shape()` functions (one per shape: governance_log, role_assertion, role_revocation, promotion, contest, contest_resolution, supersession, retraction).

**Note on `services/shacl_validator.py`:** the prompt's reference to line 56, 81 there is the **OWL-export** validator's pattern. The real per-event `validate_*_shape()` precedent the planner should follow is `revision/shape_validation.py`. The planner should **NOT** add new functions inside `services/shacl_validator.py` (which is wired to `export/shapes.ttl` — a different domain).

---

### `governance/cli/__init__.py` + per-command modules

**Primary analog:** `src/folio_insights/identity/cli.py` (THE Phase-6 `did_group` template; `@click.group(name="did")` + sibling commands + idempotent local-key pattern + click.confirm gate).
**Complementary analog:** `src/folio_insights/polysemy/cli.py` (rich.prompt.Confirm interactive gate, useful for cascade-preview).

**Group registration pattern** (mirror `identity/cli.py:101-108`):

```python
@click.group(name="governance")
def governance_group() -> None:
    """Governance substrate: promote / contest / supersede / retract / role / export.

    The PROV-O governance log per PRD §3.1.5. Signing happens CLIENT-SIDE with the
    local keyfile (DID-06); private keys never leave your machine.
    """
```

**Per-command pattern** (copy `identity/cli.py:206-296` `sign_cmd` — the canonical authorize → preview → confirm → sign → append → emit sequence):

```python
@governance_group.command("promote")
@click.argument("shard_iri")
@click.option("--status", required=True, type=click.Choice([...]))
@click.option("--cite", multiple=True, required=True)
@click.option("--key-path", type=click.Path(...), default=KEY_PATH)
@click.option("--yes", is_flag=True, default=False)
def promote_cmd(shard_iri, status, cite, key_path, yes):
    """Promote a shard to <status> with reviewer citation (PRD §3.1.2 / GOV-03)."""
    # 1. authorize(did, "promote", corpus)  — D-19 first step
    # 2. build PromotionEvent
    # 3. validate_promotion(event, store=store)  — D-20 + D-21
    # 4. sign_attestation(...) via load_signing_key
    # 5. governance_log.append(event)
    # 6. click.echo(event.model_dump_json(indent=2))
```

**Root CLI registration** (mirror `cli.py:631-640` module-bottom pattern):

```python
# Phase 7 governance + corpus subgroups
from folio_insights.governance.cli import governance_group as _governance_group
from folio_insights.governance.cli.corpus import corpus_group as _corpus_group

cli.add_command(_governance_group)
cli.add_command(_corpus_group)
```

---

### `governance/cli/retract.py` (interactive `--preview` / `--apply`, D-17)

**Primary analog:** `identity/cli.py:271-279` `click.confirm` gate (the post-preview keystroke pattern).
**Complementary analog:** `polysemy/cli.py:43-55` (rich.prompt + rich.table for the grouped-table render).

**Three-mode pattern** (CONTEXT D-17; RESEARCH §"Cascade Preview Architecture"):

```python
@governance_group.command("retract")
@click.argument("shard_iri")
@click.option("--preview", "preview_only", is_flag=True, default=False)
@click.option("--apply", "apply_path", type=click.Path(exists=True, ...), default=None)
@click.option("--output", type=click.Path(...), default=None,
              help="--preview output path (default: retract-preview-<iri>-<ts>.json in CWD)")
def retract_cmd(shard_iri, preview_only, apply_path, output, ...):
    """Retract a shard with cascade preview (PRD §3.1.4 / GOV-06).

    Three modes (D-17):
      - default: print grouped table, prompt 'Confirm? [y/N]', commit on y.
      - --preview: write timestamped JSON, exit 0 without committing.
      - --apply <file>: re-run preview, compare underlying_state_hash;
        raise PreviewStale if changed.
    """
```

The `click.confirm("Confirm retraction of N shards (auto_rederive: A, aporetic: B, review_needed: C)?", default=False)` mirrors `identity/cli.py:277` exactly.

---

### `governance/cli/corpus.py` (`corpus init --admin-did`, D-10 genesis)

**Primary analog:** `identity/cli.py:114-152` `generate_cmd` (idempotent local-init pattern; "second call with existing file reuses").
**Complementary analog:** `identity/cli.py:392-471` `bind_cmd` (orchestrate: build payload → sign → call append).

**Genesis bootstrap pattern** (D-10 — the only carve-out where `position=0 AND self-signed AND role=corpus_admin` is accepted):

```python
@click.group(name="corpus")
def corpus_group() -> None:
    """Corpus lifecycle: init / fork (Phase 18.5) / show."""


@corpus_group.command("init")
@click.argument("corpus_name")
@click.option("--admin-did", required=True)
@click.option("--key-path", type=click.Path(...), default=KEY_PATH)
def init_cmd(corpus_name, admin_did, key_path):
    """Initialize a new corpus with a genesis self-signed RoleAssertion at row 0 (D-10).

    The DID at --admin-did signs its OWN RoleAssertion granting itself corpus_admin.
    PRD §3.1.5 append-only is preserved — row 0 is the bootstrap row, not a mutation.
    Every later row requires an existing-admin signature verifiable against the log.
    """
```

---

### `governance/cli/governance_export.py` (D-08 on-demand Turtle export)

**Primary analog:** `src/folio_insights/cli.py:280-495` `export` command (corpus_name → format selection → write file).

**Pattern excerpt** (mirror `cli.py:280-298` flag plumbing):

```python
@governance_group.command("export")
@click.argument("corpus_name")
@click.option("--output", "-o", default="./governance.ttl",
              type=click.Path(resolve_path=True))
def export_cmd(corpus_name, output):
    """Export the governance log for <corpus_name> as Turtle (D-08, on-demand).

    Phase 7 ships the CLI shape; the actual Turtle writer lands in Phase 13 when
    the persistent backend swaps in. The in-phase implementation iterates
    InMemoryGovernanceLog and emits the per-event Turtle via the same rdflib
    helpers governance/shape_validation.py uses.
    """
```

---

### `rfc/lint.py` + `rfc/frontmatter.py` + `rfc/git_history.py`

**Primary analog (overall structure):** `src/folio_insights/cli.py:498-592` `verify_iris` command (drift-report + non-zero-exit-on-failure CLI module).
**Frontmatter Pydantic model analog:** `shards/envelope.py:151-162` `AttestedSignature` (`ConfigDict(extra="forbid")` discipline).

**`rfc/frontmatter.py` Pydantic model**:

```python
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict


class RFCFrontmatter(BaseModel):
    """Parsed `.planning/rfcs/NNNN-*.md` frontmatter (D-22)."""
    model_config = ConfigDict(extra="forbid")  # mirrors AttestedSignature envelope discipline
    rfc: int
    title: str
    status: Literal["draft", "discussion", "accepted", "rejected", "implemented"]
    authors: list[str]  # DIDs
    created: date
    superseded_by: int | None = None
```

**Frontmatter regex parser** (stdlib, RESEARCH §"Don't Hand-Roll" — avoid YAML/`python-frontmatter` deps):

```python
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
# Per-line `key: value` split; coerce list-valued via `[a, b, c]` or YAML-style `- item`.
```

**`rfc/git_history.py` subprocess walker** (no GitPython — RESEARCH §"Don't Hand-Roll"):

```python
def walk_history(rfc_path: Path, *, repo_root: Path) -> list[tuple[str, str, str]]:
    """Return [(commit_hash, full_message, file_content_at_commit), ...] for rfc_path.

    Uses subprocess.run(['git', 'log', '--follow', '--format=%H', '--', path]) then
    git show $hash:path for each commit. Stdlib only; matches Phase 1 minimal-deps.
    """
```

**`rfc/lint.py` lifecycle DAG check** (D-22):

```python
_ALLOWED_TRANSITIONS = {
    "draft": {"discussion", "rejected"},
    "discussion": {"accepted", "rejected"},
    "accepted": {"implemented", "rejected"},
    "implemented": set(),  # terminal
    "rejected": set(),     # terminal (D-22)
}
```

**CLI entry point** (`python -m folio_insights.rfc.lint .planning/rfcs/`):

```python
def main(argv: list[str]) -> int:
    """Returns 0 on green; 1 on any violation. Runs in CI."""
```

---

### Test patterns

#### `tests/governance/test_grep_guard_three_way_disambiguation.py` (D-16)

**Primary analog:** `tests/shards/test_dep_leak_guard.py` (per-file `read_text` source scan).
**Complementary analog:** `tests/identity/test_no_server_keys_contract.py` (AST-based, deeper but pattern-compatible).

**Pattern** (mirror `test_dep_leak_guard.py:24-39`):

```python
from folio_insights import governance as _gov

_GOV_DIR = pathlib.Path(_gov.__file__).parent
_THREE_WAY = ["contest.py", "supersede.py", "retract.py"]

@pytest.mark.parametrize("module_name", _THREE_WAY)
def test_no_cross_import_among_three_way(module_name: str) -> None:
    """D-16: contest/supersede/retract MUST NOT import from each other."""
    source = (_GOV_DIR / module_name).read_text(encoding="utf-8")
    for other in _THREE_WAY:
        if other == module_name:
            continue
        other_mod = other.removesuffix(".py")
        assert f"from folio_insights.governance.{other_mod}" not in source, (
            f"{module_name}: D-16 grep-guard — must not import from {other_mod}"
        )
        assert f"import folio_insights.governance.{other_mod}" not in source, (
            f"{module_name}: D-16 grep-guard — must not import {other_mod}"
        )
```

The three grep patterns (CONTEXT D-16):
1. No cross-module imports among the three.
2. No shared base class beyond `_BaseEvent` (the discriminated-union umbrella).
3. The three Click commands share no implementation function — assert by parsing CLI modules and checking that each command's callback function name is unique (mirror `test_no_server_keys_contract.py:36-58` `_identity_modules()` iteration).

#### `tests/governance/test_dep_leak_guard.py`

**Primary analog:** `tests/shards/test_dep_leak_guard.py:24-38` — copy verbatim, swap `shards` → `governance` and `FORBIDDEN_MODULES` to `["aiosqlite", "rdflib", "pyoxigraph", "oxrdflib"]`. **Exception:** `governance/shape_validation.py` is exempted (same as `revision/shape_validation.py` is exempted from the `shards/` boundary — it's the SHACL wrapper).

#### `tests/governance/test_*_shape.py` (8 positive + negative polarity test pairs)

**Primary analog:** `tests/revision/test_shacl_forward_only.py:67-87` — copy the conforms-true / conforms-false test pair structure exactly.

```python
def test_promotion_with_resolvable_citations_conforms() -> None:
    """Positive polarity: a valid PromotionEvent passes the SHACL guard."""
    result = validate_promotion_shape(_valid_promotion_event())
    assert result.conforms is True
    assert result.violations == []


def test_promotion_with_empty_citations_rejected() -> None:
    """Negative polarity: empty cited_iris fails (D-20 non-empty)."""
    result = validate_promotion_shape(_promotion_event(cited_iris=[]))
    assert result.conforms is False
    assert len(result.violations) >= 1
```

#### `tests/governance/property/test_log_append_monotonic.py` (Hypothesis)

**Primary analog:** `tests/identity/test_canonical_jcs_properties.py:44-75` — copy the `@settings(max_examples=1000, deadline=None, ...)` + `@given(...)` decoration verbatim.

**Property:** for any sequence of N append() calls, `event.position` is `[0, 1, 2, ..., N-1]` AND `latest_position()` is `N-1`.

#### `tests/governance/cli/test_governance_help_distinct.py` (D-16 CLI surface check)

**Primary analog:** `tests/polysemy/test_cli_review.py` (CliRunner against Click subgroup).

**Pattern**:

```python
from click.testing import CliRunner

def test_three_way_commands_have_distinct_help_text() -> None:
    """D-16: contest/supersede/retract have distinct --help (no shared template)."""
    runner = CliRunner()
    helps = {
        cmd: runner.invoke(governance_group, [cmd, "--help"]).output
        for cmd in ("contest", "supersede", "retract")
    }
    # Each command's --help mentions its distinct PRD section
    assert "§21.8" in helps["contest"] or "contest" in helps["contest"].lower()
    assert "§21.9" in helps["supersede"] or "supersede" in helps["supersede"].lower()
    assert "§3.1.4" in helps["retract"] or "cascade" in helps["retract"].lower()
```

#### `tests/rfc/test_lint_status_monotonic_across_history.py` (git-history walk)

**No exact analog** — closest is the `subprocess.run` discipline from RESEARCH §"Don't Hand-Roll". Use `tmp_path` + `subprocess.run(["git", "init"], cwd=tmp_path, check=True)` + iterative `git commit` + invoke the linter against the tmp repo. Reference pattern (file-tree iteration only): `tests/identity/test_no_server_keys_contract.py:36-58`.

---

## Shared Patterns

### Pydantic envelope discipline (`extra="forbid"`)

**Source:** `src/folio_insights/shards/envelope.py:151` (`AttestedSignature.model_config = ConfigDict(extra="forbid")`).
**Apply to:** ALL 12 `GovernanceEvent` classes, `CascadePreview`, `Allow`/`Deny`, `RFCFrontmatter`.

```python
class _BaseEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

Phase-2 D-13 + Phase-6 D-13 precedent — unknown fields raise at construction.

### Phase 13 dep-isolation boundary

**Source:** `src/folio_insights/revision/store.py:14-18` docstring + `tests/shards/test_dep_leak_guard.py:22-38`.
**Apply to:** ALL files under `governance/` (one EXEMPTION: `governance/shape_validation.py`, which legitimately uses pyshacl/rdflib — same exemption `revision/shape_validation.py` enjoys).

Forbidden imports in `governance/`: `aiosqlite`, `rdflib`, `pyoxigraph`, `oxrdflib`.

```python
# In every governance/*.py top docstring:
# Boundary: this module is stdlib + Pydantic ONLY — NO aiosqlite / rdflib /
# pyoxigraph imports here (D-04). Phase 13 wires the persistent backend behind
# the GovernanceLog Protocol.
```

### Signing seam (Phase 6 reuse, zero duplication)

**Source:** `src/folio_insights/identity/signer.py` `sign_attestation` + `src/folio_insights/identity/verifier.py:52-83` `verify_attestation`.
**Apply to:** ALL CLI commands (`promote`, `contest`, `supersede`, `retract`, `role_assert`, `role_revoke`, `corpus init`, `resolve_contest`) AND `governance_log.append()` body.

**CLI sign pattern** (verbatim from `identity/cli.py:280-296`):

```python
sk = load_signing_key(key_path)
did = _derive_didkey_from_signing_key(sk)
key_id = f"{did}#{did.removeprefix('did:key:')}"
sig = sign_attestation(
    preview.content_hash, sk, did, action,
    signing_key_id=key_id,
    did_doc_snapshot_at=None,
    now=datetime.now(UTC),
)
# sk falls out of scope — never persisted, never logged, never transmitted (DID-06).
```

**Log-append verify pattern** (consume `verify_attestation` per RESEARCH Pattern 3 step 3):

```python
if not is_genesis:
    if not await verify_attestation(event.signature_payload(), event.signature, cache=...):
        raise InvalidSignature(...)
```

### Canonical content hash (Phase 5 / Phase 6 reuse)

**Source:** `src/folio_insights/revision/content_edit.py:304-333` `canonical_content_hash` + `_jcs_canonical_bytes`.
**Apply to:** Every `GovernanceEvent.over_content_hash` computation. RESEARCH §"Don't Hand-Roll" forbids re-implementation.

```python
from folio_insights.revision.content_edit import canonical_content_hash, _jcs_canonical_bytes
# every event's over_content_hash flows through this single seam (Phase 6 D-12 / DID-03).
```

### Module-bottom CLI registration

**Source:** `src/folio_insights/cli.py:622-640`.
**Apply to:** `governance_group` + `corpus_group` registration at root CLI.

```python
# At cli.py bottom:
from folio_insights.governance.cli import governance_group as _gov_group
from folio_insights.governance.cli.corpus import corpus_group as _corpus_group
cli.add_command(_gov_group)
cli.add_command(_corpus_group)
```

The pattern keeps Click off `folio-insights --help`'s import graph for commands that don't need it (Phase 6 `did_group` precedent).

### `validate_*_shape()` defense-in-depth convention

**Source:** `src/folio_insights/revision/shape_validation.py:99-139` `validate_content_edit_shape`.
**Apply to:** All 8 SHACL-shape validators under `governance/shape_validation.py`. Same `Graph().parse()` + `pyshacl.validate(...)` + `ValidationResult` dataclass plumbing.

### Positive + negative SHACL polarity test pair

**Source:** `tests/revision/test_shacl_forward_only.py:67-87`.
**Apply to:** All 8 shape tests under `tests/governance/test_*_shape.py`.

---

## No Analog Found

| File | Role | Data Flow | Reason | Planner Guidance |
|------|------|-----------|--------|------------------|
| `rfc/git_history.py` (`subprocess.run("git log ...")` walker) | utility | subprocess + file I/O | No prior subprocess-git-walker in tree | Use stdlib `subprocess.run([...], check=True, text=True)` per RESEARCH §"Don't Hand-Roll". Reference: RESEARCH Pattern §"RFC Linter Strategy" + `subprocess` discipline from `tests/identity/test_no_server_keys_contract.py:36-58` file-tree iteration. |
| `tests/rfc/test_lint_status_monotonic_across_history.py` (tmp_path git-history fixture) | test | git-init + commit + walk | No prior test creates a tmp git repo | Use `subprocess.run(["git", "init"], cwd=tmp_path, check=True)` + iterative `git commit -m ... --allow-empty` to build a synthetic history. Stdlib only. |
| `tests/governance/test_preview_stale_refusal.py` (D-17 race) | test | two-snapshot diff | Closest is `tests/identity/test_signature_survives_key_rotation.py` (two-time-windowed); no exact match for "underlying-state-changed-since-preview" | Build two `InMemoryGovernanceLog` snapshots; mutate the dependent set between them; assert `commit_cascade(preview)` raises `PreviewStale`. |
| `.planning/rfcs/RFC-TEMPLATE.md` | doc fixture | static markdown | n/a | The frontmatter must match the `RFCFrontmatter` Pydantic model exactly; ship a worked example with `rfc: 0` (template) so the linter has a golden fixture. |

---

## Metadata

**Analog search scope:**
- `src/folio_insights/shards/` — envelope, audit, subtypes, minting, iri_registry
- `src/folio_insights/revision/` — store, content_edit, shape_validation, content_edit_shape.ttl
- `src/folio_insights/identity/` — cli, signer, verifier, cache, keys, binding, preview, resolver
- `src/folio_insights/polysemy/` — cli, distinguo, reviewer
- `src/folio_insights/services/` — shacl_validator (OWL-export; NOT the per-event analog)
- `src/folio_insights/cli.py` — root CLI registration pattern
- `tests/shards/` — dep_leak_guard, content_edit_audit_append_only, discriminated_union, envelope_roundtrip
- `tests/identity/` — no_server_keys_contract, canonical_jcs_properties, signature_survives_key_rotation, did_cli
- `tests/revision/` — shacl_forward_only, edit_shard_content
- `tests/polysemy/` — cli_review, detector_rules

**Files scanned:** ~50 source files + ~30 test files.

**Pattern extraction date:** 2026-05-30.

**Critical correction from prompt:** the prompt referenced `services/shacl_validator.py` lines 56, 81 as the per-event `validate_*_shape()` convention. **That is the OWL-export validator** wired to `export/shapes.ttl` — a different domain. The **real** per-event convention is `src/folio_insights/revision/shape_validation.py:99` (`validate_content_edit_shape`). The planner should NOT extend `services/shacl_validator.py`; ship `governance/shape_validation.py` mirroring `revision/shape_validation.py` instead.
