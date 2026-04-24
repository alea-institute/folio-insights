---
phase: 01-polysemy-distinguo-spike
plan: 04
subsystem: polysemy

tags: [pydantic, pyoxigraph, turtle, sparql, vocab-02, analogia, distinguo, rdf, tdd]

# Dependency graph
requires:
  - phase: 01-polysemy-distinguo-spike
    provides: "Plan 01-02 ProposedFork model (B7 uses_analogousTo flag) + PyoxigraphStore wrapper (SEC-01) — both consumed by distinguo.emit_fork_ttl()"
provides:
  - "src/folio_insights/polysemy/distinguo.py — ForkProposal + emit_fork_ttl + validate_fork_proposal_shape + DistinctionKind + FI_VOCAB"
  - "ForkProposal.to_proposed_fork() projection — JSONL-embedded shape consumed by 01-05 CLI modify"
  - "Pitfall 5 atomic-triad invariant enforced at BOTH pydantic model construction AND pre-emit (defense-in-depth)"
  - "Canonical Pattern-2 Turtle emission matching 01-RESEARCH.md §Pattern 2 lines 334-373"
  - "pyoxigraph round-trip validated — TTL bulk_load → SPARQL SELECT returns same triples under urn:folio:proposal/<cluster_id>"
affects: [01-05-cli-review, 01-06-fp-audit, phase-15-polysemy-fork]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Frozen pydantic BaseModel (frozen=True, extra='forbid') for emission-layer contracts — schema drift raises at 01-05/01-06 rather than silently mutating"
    - "@model_validator(mode='after') for cross-field invariants (atomic-triad check) — runs after individual field validation"
    - "Standalone defense-in-depth validator (validate_fork_proposal_shape) catches model_construct() bypass — same invariant re-checked pre-emit"
    - "Turtle literal emission uses manual _escape_turtle_literal (\\, \", \\r, \\n) rather than triple-quoted literals — keeps emitted TTL short and grep-friendly"
    - "Named-graph target urn:folio:proposal/<cluster_id> set via pyoxigraph Store.bulk_load(..., to_graph=NamedNode(...)) — Phase 15 provenance contract (D-3)"
    - "pyoxigraph 0.5.7 RdfFormat.TURTLE constant preferred over 'text/turtle' media-type string (avoids DeprecationWarning)"

key-files:
  created:
    - src/folio_insights/polysemy/distinguo.py
  modified:
    - tests/polysemy/test_distinguo_emission.py

key-decisions:
  - "Single GREEN commit for Task 1 + Task 2 (not split) — test_distinguo_emission.py imports emit_fork_ttl at module-top so Task-1-only GREEN fails test collection; mirrors 01-02 Task 2 pattern (fixtures + loader landed together)"
  - "source_frameworks: tuple[str, ...] not list — keeps ForkProposal hashable/frozen; to_proposed_fork() projects to list(source_frameworks) for the 01-02 ProposedFork.frameworks: list[str] contract"
  - "Subject IRI synthesized as urn:folio:term/<term>#<first_framework_lowercased> — mirrors 01-RESEARCH.md §Pattern 2 example verbatim (e.g., urn:folio:term/consideration#commonlaw)"
  - "_escape_turtle_literal handles \\r in addition to \\ + \" + \\n — Windows-line-ending-safe because reviewer CLI (01-05) accepts pasted input"
  - "validate_fork_proposal_shape re-checks distinction_kind against the allowed set (not just the triad) — covers the case where model_construct bypasses the Literal type check, not just the @model_validator"
  - "RdfFormat.TURTLE (not 'text/turtle' string) in the round-trip test — pyoxigraph 0.5.7 deprecated string format argument; plan text used the string for readability but clean-code path uses the enum"

patterns-established:
  - "Wave-2 emission module: pydantic model → validator → escape helper → emit function → __all__ exports, with docstring referencing PHILOSOPHY.md line + 01-RESEARCH.md line for every invariant"
  - "TDD gate sequence in this plan: test(01-04) RED commit → feat(01-04) GREEN commit covering both tasks — no refactor commit needed (code is small and clean)"
  - "Round-trip test uses pyoxigraph.Literal.value / NamedNode.value for structural assertions rather than str()-coercion — str(NamedNode) returns '<iri>' not 'iri', so .value is the right surface"

requirements-completed: [VOCAB-02]

# Metrics
duration: ~20min
completed: 2026-04-24
---

# Phase 01 Plan 04: VOCAB-02 distinguo Emission Summary

**`emit_fork_ttl()` renders VOCAB-02 `fi:analogousTo` forks as canonical Pattern-2 Turtle that round-trips losslessly through pyoxigraph under `urn:folio:proposal/<cluster_id>`, with the atomic-triad invariant (Pitfall 5 / PHILOSOPHY.md L126) enforced at BOTH pydantic model construction AND pre-emit — no analogia fork can ship without both `fi:primeAnalogate` AND `fi:proportionalRelation` in the same graph.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-04-24T17:55:00Z (approx, post-worktree-base-reset + uv venv recreation)
- **Completed:** 2026-04-24T18:15:00Z
- **Tasks:** 2 (combined GREEN commit per TDD-gate discussion below)
- **Files modified:** 2 (1 new src module + 1 test file rewritten from xfail placeholders)

## Accomplishments

- **VOCAB-02 atomic triad locked at the model layer.** `ForkProposal.@model_validator` raises `ValidationError` at construction when `uses_analogousTo=True` but `prime_analogate` or `proportional_relation` is missing. This is Pitfall 5 defense — analogia is atomic per PHILOSOPHY.md L126, and the model enforces that no sub-property may be omitted.
- **Defense-in-depth validator (`validate_fork_proposal_shape`)** re-checks the same invariant against forks built via `ForkProposal.model_construct(...)` which bypass pydantic validation. `emit_fork_ttl()` calls it as a preflight — bypass attempts are caught with `ValueError` before any TTL is serialized (T-01-04-01 mitigation).
- **4-enum `DistinctionKind` Literal** locks `distinction_kind` to `{'realis', 'rationis', 'rationis_cum_fundamento_in_re', 'analogica'}`. A 5th value raises `ValidationError` at construction.
- **Canonical Pattern-2 Turtle emission** matches 01-RESEARCH.md §Pattern 2 lines 334-373 verbatim: `@prefix fi:` declared to `<https://folio-insights.aleainstitute.ai/vocab/>` (PRD §7.1); subject IRI synthesized as `urn:folio:term/<term>#<framework>`; all three analogia predicates emitted together when `uses_analogousTo=True`; plus `fi:distinctionKind` as a string literal (not an IRI) and `fi:proposedBy` / `fi:proposedAt` provenance (T-01-04-03, T-01-04-06).
- **pyoxigraph round-trip proven** — `PyoxigraphStore(path=None).store.bulk_load(ttl.encode(), RdfFormat.TURTLE, to_graph=NamedNode('urn:folio:proposal/<cluster_id>'))` succeeds; SPARQL SELECT against `fi:primeAnalogate` returns exactly 1 row with the expected NamedNode; SELECT against `fi:distinctionKind` returns a Literal whose `.value == 'analogica'`; the atomic triad (`fi:analogousTo` + `fi:primeAnalogate` + `fi:proportionalRelation`) is present together as validated via a FILTER-IN SPARQL assertion.
- **3 Wave-0 xfails flipped to 10 green tests** in `tests/polysemy/test_distinguo_emission.py` — the 3 original xfails (analogousTo_requires_sub_properties, distinctionKind_enum, ttl_roundtrip_pyoxigraph) are now 10 real tests covering Task 1 (model + validator) and Task 2 (TTL emission + round-trip).

## Task Commits

Each task committed atomically (TDD gate sequence):

1. **RED: replace 3 xfail placeholders with 10 real tests** — `83e46ba` (test)
2. **GREEN: ForkProposal + emit_fork_ttl + pyoxigraph round-trip** — `b835dcd` (feat)

Single GREEN commit (not split Task-1-GREEN + Task-2-GREEN) because `test_distinguo_emission.py` imports `emit_fork_ttl` at module top-level — a Task-1-only GREEN commit would fail `pytest --collect-only` on the Task 2 tests. This mirrors 01-02 Task 2's same-atomic-unit rationale for `test_fixture_loader.py` + fixtures. No refactor commit was needed — code is small and linear.

_Metadata commit for this SUMMARY will be added separately after self-check._

## Files Created/Modified

**Created — source (1):**
- `src/folio_insights/polysemy/distinguo.py` — 8-field `ForkProposal` pydantic model (frozen, extra='forbid') + `@model_validator` atomic-triad guard + `validate_fork_proposal_shape()` standalone re-check + `_escape_turtle_literal()` + `emit_fork_ttl()` + `DistinctionKind` Literal + `FI_VOCAB` constant + `__all__` explicit exports.

**Modified — tests (1) [xfail → 10 real tests]:**
- `tests/polysemy/test_distinguo_emission.py` — 3 Wave-0 xfails replaced by 10 real tests:
  - Task 1 (6): `test_analogousTo_requires_sub_properties`, `test_analogousTo_requires_sub_properties_relation`, `test_distinctionKind_enum`, `test_validate_fork_proposal_shape_happy_path`, `test_fork_without_analogousTo_allows_missing_subproperties`, `test_to_proposed_fork_projects_down`
  - Task 2 (4): `test_emit_fork_ttl_shape`, `test_ttl_roundtrip_pyoxigraph`, `test_ttl_roundtrip_preserves_distinctionKind`, `test_emit_refuses_invalid_shape_defense_in_depth`

## Public Exports

```python
from folio_insights.polysemy.distinguo import (
    FI_VOCAB,                        # 'https://folio-insights.aleainstitute.ai/vocab/'
    DistinctionKind,                 # Literal['realis','rationis','rationis_cum_fundamento_in_re','analogica']
    ForkProposal,                    # pydantic BaseModel (frozen, extra='forbid')
    emit_fork_ttl,                   # (fork: ForkProposal) -> str
    validate_fork_proposal_shape,    # (fork: ForkProposal) -> None; raises ValueError on violation
)
```

## Example Round-Tripped TTL

Live output from `emit_fork_ttl(fork)` for the canonical analogia fork used in the test suite (copy-paste of actual Python-printed output, not a hand-written example):

```turtle
@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:folio:term/consideration#commonlaw>
    fi:analogousTo             <urn:folio:term/consideration#restatement> ;
    fi:primeAnalogate          <urn:folio:term/consideration#restatement> ;
    fi:proportionalRelation    "bargained-for exchange (CL) ↔ bargain + mutual inducement (R2d)" ;
    fi:distinctionKind         "analogica" ;
    fi:proposedBy              <did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK> ;
    fi:proposedAt              "2026-04-24T17:30:00+00:00"^^xsd:dateTime .
```

This block matches 01-RESEARCH.md §Pattern 2 lines 334-373 exactly (subject IRI shape, triad, distinctionKind as literal, proposedBy/proposedAt provenance).

## Decisions Made

- **Single Task-1 + Task-2 GREEN commit:** Task 1's model and Task 2's emit function land in the same module, and the test file imports `emit_fork_ttl` at module top. Splitting the GREEN commit would produce a commit where `pytest --collect-only` on the test file fails (`ImportError: cannot import name 'emit_fork_ttl'`). The 01-02 SUMMARY established the precedent that atomic units of implementation + tests commit together when the import graph demands it (see 01-02's Task 2 commit `863ad43`).
- **`source_frameworks: tuple[str, ...]`:** ForkProposal is `frozen=True` so it can be used as a dict key in 01-05 review state. Tuples hash; lists don't. `to_proposed_fork()` explicitly converts to `list(source_frameworks)` for the 01-02 ProposedFork JSONL-embedded `frameworks: list[str]` contract.
- **Subject IRI = `urn:folio:term/<term>#<first_framework>.lower()`:** 01-RESEARCH.md §Pattern 2 shows the subject as `<urn:folio:term/consideration#commonlaw>` — a per-framework term-sense node. The first-framework choice is arbitrary but deterministic (tuple order preserved); the 01-05 CLI can re-order `source_frameworks` before emit if a different subject is wanted.
- **`_escape_turtle_literal` handles `\r` in addition to `\n`:** Reviewers paste strings into the 01-05 CLI prompt which on Windows can carry `\r\n`. Pyoxigraph's Turtle parser rejects bare `\r` in single-quoted literals (only `\n` and `\t` are allowed unescaped per Turtle 1.1 §2.5.2 ECHAR). Escaping both keeps the CLI copy-paste path robust.
- **`RdfFormat.TURTLE` enum over `'text/turtle'` string:** pyoxigraph 0.5.7 emits `DeprecationWarning: Using string to specify a RDF format is deprecated, please use a RdfFormat object instead.` when the media-type string is passed. The plan text used `'text/turtle'` for readability; the implementation and tests use the enum to keep the suite warning-free.
- **`validate_fork_proposal_shape` also re-validates `distinction_kind` against the allowed set** (not just the atomic triad). Reason: `model_construct` bypasses the Literal type check entirely — without the extra check, a caller could build a `ForkProposal(distinction_kind="analogy", ...)` via `model_construct` and have it serialized to TTL. The validator covers both the triad and the 4-enum in one pass.
- **Test 6 bonus (`test_to_proposed_fork_projects_down`):** Not in the plan's behavior block, but added to explicitly verify the projection contract that 01-05 CLI will depend on. Catches drift if anyone ever changes `to_proposed_fork()` without updating the 01-02 ProposedFork shape.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug-avoidance] Plan example used `'text/turtle'` media-type string; used `RdfFormat.TURTLE` enum instead**
- **Found during:** Task 2 — while preparing the round-trip test, `./.venv/bin/python -c "..."` smoke confirmed `bulk_load(b'...', 'text/turtle', to_graph=...)` works but emits `DeprecationWarning`. pyoxigraph 0.5.7 has deprecated string format arguments.
- **Issue:** Using the deprecated form would add a DeprecationWarning to the test run; the suite's `--timeout=30` doesn't fail on warnings, but a clean warning-free baseline is the right default.
- **Fix:** Use `pyoxigraph.RdfFormat.TURTLE` in the test and in any future emit-side loader. The plan's example string form stays in the plan text for readability; the implementation diverges.
- **Files modified:** `tests/polysemy/test_distinguo_emission.py` (tests 7, 8 use `RdfFormat.TURTLE`)
- **Verification:** `pytest tests/polysemy/test_distinguo_emission.py -W error::DeprecationWarning` (implicit — clean run shows zero deprecation warnings from pyoxigraph)
- **Committed in:** `83e46ba` (test) — RED commit used the enum from the start; no re-fix needed.

**2. [Rule 2 — Auto-add missing critical functionality] Added `test_to_proposed_fork_projects_down`**
- **Found during:** Task 1 test authoring — the plan's behavior block lists 5 tests for Task 1 but the `acceptance_criteria` requires that `ForkProposal.to_proposed_fork()` "projects down to the canonical ProposedFork shape (with `frameworks=list(source_frameworks)`, `uses_analogousTo` preserved)". Without an explicit test, this contract is unenforced and 01-05 CLI's consumer-side assumption can silently drift.
- **Issue:** Projection correctness is a consumer-visible contract (01-05 CLI builds `DispositionRecord(proposed_fork=fork.to_proposed_fork(), ...)` then writes JSONL via 01-02's `append_disposition`). Any regression here breaks the 01-05 + 01-06 pipeline. Rule 2 applies (correctness requirement).
- **Fix:** Added `test_to_proposed_fork_projects_down` as test 6 in Task 1. Asserts cluster_id, term, uses_analogousTo, prime_analogate, proportional_relation, distinction_kind, and `frameworks == list(FRAMEWORKS)` all project correctly.
- **Files modified:** `tests/polysemy/test_distinguo_emission.py`
- **Verification:** `pytest tests/polysemy/test_distinguo_emission.py::test_to_proposed_fork_projects_down` — PASSED.
- **Committed in:** `83e46ba` (RED) + `b835dcd` (GREEN).

**3. [Rule 2 — Auto-add missing critical functionality] Added atomic-triad SPARQL assertion in `test_ttl_roundtrip_preserves_distinctionKind`**
- **Found during:** Task 2 — the plan's behavior block for test 8 says "same round-trip, SELECT `?k WHERE { ?s fi:distinctionKind ?k }`, assert `?k == 'analogica'`". This covers distinctionKind but does not re-verify that the atomic triad survived the round-trip under the same named graph.
- **Issue:** The core invariant of VOCAB-02 is that `fi:analogousTo` + `fi:primeAnalogate` + `fi:proportionalRelation` live together in the same graph. A future TTL-generation regression that emits the predicates to different graphs (or drops one) would pass the current `primeAnalogate` and `distinctionKind` round-trip tests individually but violate Pitfall 5 in practice.
- **Fix:** Extended test 8 with a FILTER-IN SPARQL against `{fi:analogousTo, fi:primeAnalogate, fi:proportionalRelation}` under the same named graph; asserts the returned set equals exactly those three predicate IRIs.
- **Files modified:** `tests/polysemy/test_distinguo_emission.py` (test 8 extended, not replaced)
- **Verification:** `pytest tests/polysemy/test_distinguo_emission.py::test_ttl_roundtrip_preserves_distinctionKind` — PASSED.
- **Committed in:** `83e46ba` (RED) + `b835dcd` (GREEN).

---

**Total deviations:** 3 — all Rule 1 (warning cleanup) or Rule 2 (critical-functionality additions that strengthen existing tests). No architectural changes (Rule 4) triggered. No scope creep.

## Issues Encountered

- **Worktree had no `.venv`:** Same as 01-01 and 01-02. Ran `uv venv .venv` + `uv pip install -e '.[dev]'` to reconstruct the environment; downloaded ~107 packages (cryptography 46.0.7, base58 2.1.1 from 01-01; pyoxigraph 0.5.7 from 00-foundations). Not a blocker — standard worktree behavior documented in the 01-02 SUMMARY.
- **Task-1-only GREEN commit not viable:** Attempted to write a Task-1-only `distinguo.py` (without `emit_fork_ttl`) and run the Task 1 test subset. `pytest --collect-only` failed with `ImportError: cannot import name 'emit_fork_ttl' from 'folio_insights.polysemy.distinguo'` because the test file imports both names at module top. Rolled back to single GREEN commit (per decision above).

## Threat-Model Compliance (THIS plan's `<threat_model>`)

| Threat ID | Mitigation Status | Evidence |
|-----------|-------------------|----------|
| T-01-04-01 (ForkProposal model_construct bypass → invalid TTL) | ✅ mitigated | `emit_fork_ttl()` calls `validate_fork_proposal_shape()` as first action; `test_emit_refuses_invalid_shape_defense_in_depth` asserts ValueError on `model_construct(uses_analogousTo=True, prime_analogate=None)` |
| T-01-04-02 (Turtle literal injection via proportional_relation) | ✅ mitigated | `_escape_turtle_literal(s)` escapes `\\`, `"`, `\\r`, `\\n`; pyoxigraph round-trip test 7 would fail parse on any un-escaped control char |
| T-01-04-03 (fi:proposedBy leaks reviewer identity) | ✅ accepted | Intentional per D-3 Phase 15 provenance contract; DID is pseudonymous per Phase 6 OQ-4 |
| T-01-04-04 (Large proportional_relation strings) | ✅ accepted | Single-maintainer CLI scope; no adversarial input path in Phase 1 |
| T-01-04-05 (SERVICE clauses in reasoner queries over fork graph) | ✅ mitigated | All reads route through `PyoxigraphStore.query_rdf12()` which enforces the SEC-01 SERVICE preflight |
| T-01-04-06 (Reviewer denies proposing a fork) | ✅ mitigated | Every fork emits `fi:proposedBy <did:key:...>` + `fi:proposedAt xsd:dateTime` provenance |
| T-01-04-07 (Attacker forges fork under another DID) | ✅ accepted | Phase 1 scope excludes signing verification; Phase 15 adds JCS-canonical signatures |

No threat_flags emerged beyond the register.

## Success Criteria Verification

- [x] `src/folio_insights/polysemy/distinguo.py` exports `ForkProposal`, `emit_fork_ttl`, `validate_fork_proposal_shape`, `DistinctionKind`, `FI_VOCAB` — verified via `python -c "from folio_insights.polysemy.distinguo import ..."` smoke print
- [x] All 10 tests in `tests/polysemy/test_distinguo_emission.py` pass — `pytest tests/polysemy/test_distinguo_emission.py -v` → 10 passed
- [x] Emitted TTL round-trips losslessly through pyoxigraph under the expected named graph — tests 7 + 8 assert NamedNode/Literal values from SPARQL match the source fork fields
- [x] Pitfall 5 (analogia atomicity) enforced at BOTH model construction AND pre-emit — tests 1, 2 (construction) + test 9 (pre-emit) cover both layers
- [x] No 5th `distinction_kind` value can ever be serialized — test 3 asserts pydantic ValidationError; `validate_fork_proposal_shape` enforces same check post-`model_construct`
- [x] Plan 01-05 (CLI `modify`) can import ForkProposal without circular-import issues — `distinguo.py` imports from `dispositions.py` (downstream direction), not the reverse; `python -c "from folio_insights.polysemy.distinguo import ForkProposal"` completes without error
- [x] `ForkProposal.to_proposed_fork()` produces canonical ProposedFork (uses_analogousTo preserved, `frameworks=list(source_frameworks)`) for 01-05 CLI — test 6 asserts all 7 fields project correctly

## Next Phase Readiness

- **Plan 01-05 (CLI review, Wave 3) can now:**
  - Construct a `ForkProposal` from reviewer CLI input — pydantic raises `ValidationError` inline if the atomic triad is violated, letting the CLI loop re-prompt
  - Call `fork.to_proposed_fork()` to get the canonical `ProposedFork` shape that `DispositionRecord.proposed_fork` expects (01-02 contract)
  - Optionally call `emit_fork_ttl(fork)` to produce a Turtle blob that can be bulk-loaded into a live `PyoxigraphStore` for reviewer preview — no modification to the CLI control flow required
  - Use `FI_VOCAB` as a single source of truth for the `fi:` namespace (avoids hardcoded strings in the CLI)
- **Plan 01-06 (FP audit, Wave 4) can now:**
  - Read back `DispositionRecord.proposed_fork` entries from JSONL via 01-02's `read_dispositions()` iterator and construct `ForkProposal` / re-emit TTL for audit-side comparison
  - Use `validate_fork_proposal_shape` as the post-JSON rehydration check
- **Phase 15 (polysemy-fork UI, downstream) can now:**
  - Consume the `urn:folio:proposal/<cluster_id>` named-graph layout directly — the emission layer locks the graph-IRI scheme
  - Bind to the 6-predicate vocabulary (`fi:analogousTo`, `fi:primeAnalogate`, `fi:proportionalRelation`, `fi:distinctionKind`, `fi:proposedBy`, `fi:proposedAt`) with confidence that emission-side always produces the atomic triad together

**Blockers for downstream:** None.

## Self-Check

- [x] `src/folio_insights/polysemy/distinguo.py` exists
- [x] All 5 expected exports importable: `FI_VOCAB`, `DistinctionKind`, `ForkProposal`, `emit_fork_ttl`, `validate_fork_proposal_shape`
- [x] `FI_VOCAB == "https://folio-insights.aleainstitute.ai/vocab/"` (verified via `print(FI_VOCAB)`)
- [x] `ForkProposal` has 9 declared fields: term, cluster_id, uses_analogousTo, prime_analogate, proportional_relation, distinction_kind, source_frameworks, reviewer_did, created_at_iso — verified via `len(ForkProposal.model_fields) == 9` (plan text L256 said "8 fields" but listed 9; implementation matches the canonical list)
- [x] `DistinctionKind` Literal resolves to the 4-enum set verified in REPL
- [x] `pytest tests/polysemy/test_distinguo_emission.py -v --timeout=30` → 10 passed
- [x] `pytest tests/polysemy/ --timeout=30` → 17 passed, 11 xfailed (downstream waves 2/3/4)
- [x] Commit `83e46ba` (RED) on worktree-agent-a0274228 branch
- [x] Commit `b835dcd` (GREEN) on worktree-agent-a0274228 branch
- [x] No modifications to `src/folio_insights/polysemy/{prototype_cluster,similarity_query,detector}.py` (owned by parallel 01-03 executor)
- [x] No modifications to STATE.md or ROADMAP.md (orchestrator owns those)
- [x] No commits bypassed pre-commit hooks with `--no-verify` flag other than the explicitly-instructed parallel-executor rule (see `<parallel_execution>` directive)

## Self-Check: PASSED

All exports verified, all 10 tests green, both task commits present in git log, no out-of-scope file writes, no STATE/ROADMAP touches.

---
*Phase: 01-polysemy-distinguo-spike*
*Completed: 2026-04-24*
