---
phase: 08-folio-v2-vocab-mini-bfo-spine-7
fixed_at: 2026-05-31T23:55:00Z
review_path: .planning/phases/08-folio-v2-vocab-mini-bfo-spine-7/08-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 8: Code Review Fix Report

**Fixed at:** 2026-05-31T23:55:00Z
**Source review:** `.planning/phases/08-folio-v2-vocab-mini-bfo-spine-7/08-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 7 (2 Critical + 5 Warning; Info findings deferred per `critical_warning` scope)
- Fixed: 7
- Skipped: 0

All 7 in-scope findings were applied as atomic commits. Phase 8 test suite
re-run after every fix: **251 passed, 46 skipped**. (Two pre-existing
failures in `tests/bench/test_gate5_digest.py` are unrelated environment
issues — subprocess can't find `'python'` binary on PATH; they failed
identically on the pre-fix state.)

## Fixed Issues

### CR-01: `fi:SupersessionAlignmentShape` STR() Comparison Produces False Positives for Semantically-Equal Datetimes

**Files modified:** `src/folio_insights/vocab/shapes.ttl`
**Commit:** `e3a1793`
**Applied fix:** Replaced `FILTER(STR(?aStart) != STR(?bEnd))` with
`FILTER(?aStart != ?bEnd)` on the supersession-alignment SPARQL constraint.
Direct XSD comparison is timezone-aware per SPARQL 1.1, so two datetime
literals representing the same UTC instant (e.g. `"2026-05-01T00:00:00Z"`
and `"2026-04-30T22:00:00-02:00"`) now compare equal and the shape no
longer false-positives on chains written with mixed timezone notations.

### CR-02: `fi:SupersessionAlignmentShape` Fails Silently When Superseded Shard Lacks `fi:validTimeEnd`

**Files modified:** `src/folio_insights/vocab/shapes.ttl`,
`tests/temporal/test_supersession_alignment_shape.py`
**Commit:** `2d6749b`
**Applied fix:** Split `fi:SupersessionAlignmentShape` from one `sh:sparql`
into two co-located `sh:sparql` constraints under the same NodeShape. The
first preserves the existing mismatched-`validTimeEnd` check (CR-01's
behaviour). The second is new: `SELECT $this ?b WHERE { $this fi:supersedes ?b . FILTER NOT EXISTS { ?b fi:validTimeEnd ?bEnd . } }`
catches the case where A supersedes a still-current (open-ended) shard B.
Pyshacl required two separate `sh:sparql` constraints rather than a single
SELECT with a UNION branch — the UNION variant returned the violation row
when run via rdflib directly but pyshacl reported `conforms=True` (likely
because pyshacl substitutes `$this` per focus node and the UNION's second
branch didn't bind `?b` correctly under that substitution model).

Added regression test
`test_missing_validTimeEnd_on_superseded_shard_conforms_false` that
constructs A `fi:supersedes` B with B missing `fi:validTimeEnd` and
asserts `conforms=False`.

**Note:** The shape is a correctness gate; logic correctness here matters
beyond syntax. The test fixture verifies both polarities (aligned ⇒
conforms, missing-end ⇒ violation) so the gate is exercised end-to-end.

### WR-01: `vocab/__init__.py` Eagerly Imports pyoxigraph at Module Level, Coupling VOCAB_VERSION to a Storage-Layer Dependency

**Files modified:** `src/folio_insights/vocab/_constants.py` (new),
`src/folio_insights/vocab/__init__.py`,
`src/folio_insights/shards/envelope.py`,
`src/folio_insights/bench/generator.py`
**Commit:** `18e48d8`
**Applied fix:** Created `src/folio_insights/vocab/_constants.py`
holding `VOCAB_VERSION`, `FI_PREFIX`, `NAMESPACES` (stdlib + rdflib only —
no pyoxigraph). `vocab/__init__.py` now re-exports those constants and
defers the pyoxigraph import to inside `load_pyoxigraph_store`.
`shards/envelope.py` and `bench/generator.py` import directly from
`_constants` (belt-and-braces against future regressions).

Verified: `from folio_insights.vocab._constants import VOCAB_VERSION`
AND `from folio_insights.vocab import VOCAB_VERSION` both leave
`pyoxigraph` absent from `sys.modules` afterwards.

### WR-02: `_pick_subtype` Uses `r <= cw` Instead of `r < cw`, Allowing Zero-Weight Items to Be Sampled

**Files modified:** `src/folio_insights/bench/generator.py`,
`tests/bench/test_pick_subtype_zero_weight.py` (new)
**Commit:** `2be51dd`
**Applied fix:** Changed the cumulative-weight loop condition from
`if r <= cw` to `if r < cw`. Added two regression tests:
  (1) Force `rng.random()` to return `0.0` against a profile where the
      first sorted key has weight `0.0` (`ConflictingAuthorities`) —
      assert the zero-weight key is not returned.
  (2) Run 1000 draws against the same profile — assert no zero-weight
      key is ever returned.

Verified: `tests/vocab/test_bench_emits_vocab_version.py::test_digest_matches_pinned_baseline`
still passes (production profiles use only non-zero weights, so the
strict-less-than change doesn't shift any output bytes).

### WR-03: `test_predicate_drift_audit.py` Uses Bare Relative Paths — Fails When pytest Is Not Invoked from Project Root

**Files modified:** `tests/vocab/test_predicate_drift_audit.py`
**Commit:** `aa251ca`
**Applied fix:** Added `_REPO_ROOT = Path(__file__).parent.parent.parent`
and derived `_SOURCE_ROOT` and `_SHAPES_TTL` constants. Replaced all
three bare `Path("src/folio_insights")` / `Path("src/folio_insights/vocab/shapes.ttl")`
occurrences with the anchored constants. Verified by running pytest from
`/tmp` (non-root cwd) — all 5 audit tests still pass.

### WR-04: `query_as_of` Return Type Annotation Omits `BNode` — Caller Type Safety Is Incorrect

**Files modified:** `src/folio_insights/temporal/as_of.py`
**Commit:** `6c21cd1`
**Applied fix:** Imported `BNode` from `rdflib`. Widened `Row.object`
from `URIRef | Literal` to `URIRef | Literal | BNode`. Widened
`query_as_of` return annotation from `list[tuple[URIRef, URIRef | Literal]]`
to `list[tuple[URIRef, URIRef | Literal | BNode]]`. Updated the docstring
to call out the `BNode` case explicitly so callers narrowing the union
guard for all three rdflib term types.

### WR-05: `fi:inFramework` Declared as ObjectProperty but Described as an Inverse Link Without `owl:inverseOf`

**Files modified:** `src/folio_insights/vocab/predicates.ttl`
**Commit:** `826a3f7`
**Applied fix:** Added `owl:inverseOf fi:framework ;` to the
`fi:inFramework` declaration, matching the D-10 pattern used for
`fi:supersedes` / `fi:supersededBy`. Rewrote the `rdfs:comment` to
reflect the now-machine-readable inverse claim. Verified: both rdflib
and pyoxigraph parse the merged graph (459 triples).

## Skipped Issues

None. All 7 in-scope findings were fixed.

---

_Fixed: 2026-05-31T23:55:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
