---
phase: 08-folio-v2-vocab-mini-bfo-spine-7
reviewed: 2026-05-31T00:00:00Z
depth: standard
files_reviewed: 30
files_reviewed_list:
  - docs/query-as-of.md
  - src/folio_insights/bench/generator.py
  - src/folio_insights/export/shapes.ttl
  - src/folio_insights/services/owl_serializer.py
  - src/folio_insights/shards/envelope.py
  - src/folio_insights/temporal/__init__.py
  - src/folio_insights/temporal/as_of.py
  - src/folio_insights/vocab/__init__.py
  - src/folio_insights/vocab/bfo_mapping.ttl
  - src/folio_insights/vocab/bfo_spine.ttl
  - src/folio_insights/vocab/classes.ttl
  - src/folio_insights/vocab/predicates.ttl
  - src/folio_insights/vocab/shapes.ttl
  - tests/bench/fixtures/expected_digest.txt
  - tests/shards/fixtures/example_a1_simple_assertion.json
  - tests/shards/fixtures/example_a2_conflicting_authorities.json
  - tests/shards/fixtures/example_a3_disputed_proposition.json
  - tests/temporal/__init__.py
  - tests/temporal/fixtures/supersession_chain.ttl
  - tests/temporal/test_dep_leak_guard.py
  - tests/temporal/test_query_as_of.py
  - tests/temporal/test_supersession_alignment_shape.py
  - tests/vocab/__init__.py
  - tests/vocab/test_bench_emits_vocab_version.py
  - tests/vocab/test_envelope_vocab_pin.py
  - tests/vocab/test_owl_version_iri.py
  - tests/vocab/test_predicate_drift_audit.py
  - tests/vocab/test_pyoxigraph_roundtrip.py
  - tests/vocab/test_vocab_load_smoke.py
findings:
  critical: 2
  warning: 5
  info: 4
  total: 11
status: issues_found
---

# Phase 08: Code Review Report

**Reviewed:** 2026-05-31
**Depth:** standard
**Files Reviewed:** 30
**Status:** issues_found

## Summary

Phase 8 ships the FOLIO v2 TTL vocabulary (five-file split), the 9-class mini-BFO spine, the `query_as_of` temporal helper, and the two-belt vocab-version enforcement (Pydantic + SHACL). The architecture is sound and well-documented. Two issues require fixing before this code can be trusted as a correctness gate: the SHACL `fi:SupersessionAlignmentShape` uses `STR()` string comparison instead of direct xsd:dateTime numeric comparison, producing confirmed false-positive violations; and the `fi:SupersessionAlignmentShape` fails silently when the superseded shard (B) is missing its `fi:validTimeEnd` triple. Both were verified with live pyshacl invocations.

---

## Critical Issues

### CR-01: `fi:SupersessionAlignmentShape` STR() Comparison Produces False Positives for Semantically-Equal Datetimes

**File:** `src/folio_insights/vocab/shapes.ttl:166-175`

**Issue:** The SPARQL constraint in `fi:SupersessionAlignmentShape` uses `FILTER(STR(?aStart) != STR(?bEnd))` to detect misaligned supersession chains. `STR()` coerces an `xsd:dateTime` literal to its lexical form without normalizing the timezone offset. Two datetime values that represent the same UTC instant but are written in different timezone notations — e.g., `"2026-05-01T00:00:00Z"` and `"2026-04-30T22:00:00-02:00"` — will compare unequal under `STR()` even though `?aStart != ?bEnd` (direct XSD comparison) correctly treats them as equal. This was reproduced live:

```
data: A.validTimeStart = "2026-05-01T00:00:00Z"^^xsd:dateTime
      B.validTimeEnd   = "2026-04-30T22:00:00-02:00"^^xsd:dateTime  (same UTC instant)
STR() comparison: flags as MISALIGNED  ← false positive
Direct != comparison: correctly identifies as ALIGNED
```

Any shard whose chain was written with a non-UTC timezone offset will be incorrectly rejected at the storage/export boundary. The shape is supposed to be a correctness gate; a false positive makes the gate unusable for chains with timezone diversity.

**Fix:** Replace `STR(?aStart) != STR(?bEnd)` with a direct XSD comparison `?aStart != ?bEnd`. XSD dateTime comparison in SPARQL 1.1 is semantic (treats equivalent instants as equal regardless of timezone notation):

```sparql
SELECT $this ?b ?aStart ?bEnd WHERE {
    $this fi:supersedes ?b .
    $this fi:validTimeStart ?aStart .
    ?b fi:validTimeEnd ?bEnd .
    FILTER(?aStart != ?bEnd)
}
```

---

### CR-02: `fi:SupersessionAlignmentShape` Fails Silently When Superseded Shard Lacks `fi:validTimeEnd`

**File:** `src/folio_insights/vocab/shapes.ttl:161-175`

**Issue:** The shape's `sh:sparql` SELECT requires `?b fi:validTimeEnd ?bEnd` in its WHERE clause (no OPTIONAL). When shard B — the superseded shard — is missing its `fi:validTimeEnd` triple, the SPARQL returns no rows, so pyshacl reports `conforms=True`. This means a graph where A `fi:supersedes` B and B has no `fi:validTimeEnd` (an open-ended "still current" shard) silently passes the alignment check, even though superseding a still-current shard is a chain integrity violation under PRD §21.9. Verified live:

```
data: A has fi:validTimeStart + fi:supersedes B
      B has fi:validTimeStart but NO fi:validTimeEnd
Result: conforms=True  ← shape completely blind to this case
```

The `query_as_of` FILTER relies on the chain being correct; a superseded shard with missing `fi:validTimeEnd` would cause both B and A to be returned for dates inside A's interval (B's open-ended interval covers them all), silently returning duplicate rows.

**Fix:** Extend the SPARQL to also reject A `fi:supersedes` B when B has no `fi:validTimeEnd` (B cannot be open-ended if it has been superseded):

```sparql
SELECT $this ?b WHERE {
    $this fi:supersedes ?b .
    {
        # Case 1: B has validTimeEnd but it doesn't equal A's validTimeStart
        $this fi:validTimeStart ?aStart .
        ?b fi:validTimeEnd ?bEnd .
        FILTER(?aStart != ?bEnd)
    }
    UNION
    {
        # Case 2: B is missing validTimeEnd entirely (still-current but superseded)
        $this fi:validTimeStart ?aStart .
        FILTER NOT EXISTS { ?b fi:validTimeEnd ?bEnd . }
    }
}
```

---

## Warnings

### WR-01: `vocab/__init__.py` Eagerly Imports pyoxigraph at Module Level, Coupling VOCAB_VERSION to a Storage-Layer Dependency

**File:** `src/folio_insights/vocab/__init__.py:45-46`

**Issue:** The module-level `from pyoxigraph import RdfFormat, Store` import means that any module importing `VOCAB_VERSION` from `folio_insights.vocab` (including `shards/envelope.py`, `bench/generator.py`) must have pyoxigraph installed. `VOCAB_VERSION` is a plain string constant that should be importable in lightweight environments (e.g., a standalone schema validator, a test that only instantiates `ShardEnvelope`). The eager import also means an API change in pyoxigraph 0.6.x would break `shards/envelope.py` at import time even if the envelope module never touches the store.

The fallback in `test_envelope_vocab_pin.py` and `test_bench_emits_vocab_version.py` (`except ImportError: from folio_insights.shards.envelope import VOCAB_VERSION`) is unreachable: `shards/envelope.py` itself imports `VOCAB_VERSION` from `folio_insights.vocab`, so if `folio_insights.vocab` fails to import, `folio_insights.shards.envelope` also fails.

**Fix:** Extract the constants (`VOCAB_VERSION`, `FI_PREFIX`, `NAMESPACES`) into a lightweight `folio_insights/vocab/_constants.py` module (no pyoxigraph dependency) and import them from both `vocab/__init__.py` and `shards/envelope.py`:

```python
# vocab/_constants.py — stdlib only
VOCAB_VERSION: str = "2026.05.0"
FI_PREFIX: str = "https://folio-insights.aleainstitute.ai/vocab/"
```

---

### WR-02: `_pick_subtype` Uses `r <= cw` Instead of `r < cw`, Allowing Zero-Weight Items to Be Sampled

**File:** `src/folio_insights/bench/generator.py:183-186`

**Issue:** The weighted random selection loop uses `if r <= cw: return k`. When `r == 0.0` (which the Mersenne Twister can produce) and the first item has weight `0.0`, `cumweights[0] == 0.0`, and `0.0 <= 0.0` is `True`, so the first item is selected regardless of its weight. This gives a zero-weight item a small but non-zero probability of being selected (only when `rng.random()` returns exactly `0.0`). All production profiles use non-zero weights, so this is latent rather than active, but it silently violates the "weight proportional selection" contract and could surface if a future profile sets a weight to `0.0` as a deactivation flag.

The `return keys[-1]` fallback at line 186 is unreachable dead code: with `r < total` (guaranteed since `rng.random()` is `[0.0, 1.0)`) the loop always matches before exhaustion.

**Fix:**

```python
# Use strict less-than to exclude zero-weight items
r = self._rng.random() * total
for k, cw in zip(keys, cumweights, strict=True):
    if r < cw:
        return k
return keys[-1]  # true fallback: floating-point edge case only
```

Or use `random.choices()` directly, which handles zero weights correctly.

---

### WR-03: `test_predicate_drift_audit.py` Uses Bare Relative Paths — Fails When pytest Is Not Invoked from Project Root

**File:** `tests/vocab/test_predicate_drift_audit.py:89,180,202`

**Issue:** Three locations use `Path("src/folio_insights")` and `Path("src/folio_insights/vocab/shapes.ttl")` — relative to the process working directory, not to `__file__`. pytest does not change `os.getcwd()` to the project root; it uses `rootdir` for discovery only. If a developer runs `pytest tests/vocab/` from inside the `tests/` directory, or if a CI job sets a non-root working directory, these paths silently evaluate to non-existent paths. `pkg_root.exists()` returns `False` and `_scan_emitted_predicates` returns an empty dict, causing `test_every_emitted_predicate_is_declared_or_waived` to pass vacuously (no emitted predicates found — nothing to check). The drift audit becomes a no-op.

**Fix:** Anchor all paths to `__file__`:

```python
_REPO_ROOT = Path(__file__).parent.parent.parent  # tests/vocab/ → repo root
_SOURCE_ROOT = _REPO_ROOT / "src" / "folio_insights"
# ...
root = _SOURCE_ROOT
# ...
shapes_text = (_REPO_ROOT / "src/folio_insights/vocab/shapes.ttl").read_text(encoding="utf-8")
```

---

### WR-04: `query_as_of` Return Type Annotation Omits `BNode` — Caller Type Safety Is Incorrect

**File:** `src/folio_insights/temporal/as_of.py:100,76`

**Issue:** The function signature declares `list[tuple[URIRef, URIRef | Literal]]` and the `Row` dataclass declares `object: URIRef | Literal`. In rdflib, a SPARQL SELECT `?object` binding resolves to whatever term is in the graph at that position: `URIRef`, `Literal`, or `BNode`. If a shard's predicate object is a blank node (e.g., an embedded reification), `row.object` returns a `BNode`, but callers following the declared type annotation will not guard against it. This is a silent type lie that a strict type-checker (`mypy --strict`) or a downstream caller converting `obj` to a URI would break on.

**Fix:** Widen the annotation to include `BNode`:

```python
from rdflib import BNode, Graph, Literal, Namespace, URIRef
# ...
def query_as_of(
    graph: Graph,
    predicate: URIRef,
    at_date: date | datetime,
) -> list[tuple[URIRef, URIRef | Literal | BNode]]:
```

And in the `Row` dataclass:

```python
@dataclass(frozen=True)
class Row:
    subject: URIRef
    object: URIRef | Literal | BNode
```

---

### WR-05: `fi:inFramework` Declared as ObjectProperty but Described as an Inverse Link Without `owl:inverseOf`

**File:** `src/folio_insights/vocab/predicates.ttl:83-85`

**Issue:** The `rdfs:comment` on `fi:inFramework` says "Inverse-style link: subject is asserted relative to the referenced framework." This implies it should be declared `owl:inverseOf fi:framework`, as was done for the `fi:supersedes`/`fi:supersededBy` pair (D-10). Without the `owl:inverseOf` declaration, OWL reasoners and SPARQL entailment engines cannot infer the inverse triple, making the "inverse-style" claim misleading. Downstream consumers expecting inference-based reachability from `fi:inFramework` will get silent failures.

**Fix:** Add the `owl:inverseOf` declaration:

```turtle
fi:inFramework a owl:ObjectProperty ;
    rdfs:label "in framework" ;
    owl:inverseOf fi:framework ;
    rdfs:comment "Inverse of fi:framework: subject is asserted relative to the referenced framework." .
```

---

## Info

### IN-01: `_pick_subtype` Dead Code — `return keys[-1]` Is Unreachable

**File:** `src/folio_insights/bench/generator.py:186`

**Issue:** The final `return keys[-1]` after the for loop is unreachable. With `r = rng.random() * total` where `rng.random()` is `[0.0, 1.0)` and `cumweights[-1] == total`, the condition `r <= cw` (or `r < cw` after the WR-02 fix) will always be satisfied before loop exhaustion. This is dead code that misleads the reader into thinking a fallback case exists.

**Fix:** Add a comment, or replace with an assertion:

```python
# This line is nominally unreachable: r < total ensures the loop above always matches.
# Kept as a safety valve for floating-point edge cases.
return keys[-1]
```

---

### IN-02: `bench/generator.py` Emits Partial Shards That Would Fail `fi:VocabPinShape` at Storage Boundary

**File:** `src/folio_insights/bench/generator.py:147-151`

**Issue:** The inner corpus loop breaks immediately when `emitted_for_corpus >= corpus_target`, potentially mid-shard (after emitting the `rdf:type`, `fi:corpus`, and `fi:framework` quads for a shard, but before emitting the `fi:vocabVersion` quad). The test (`test_bench_emits_vocab_version.py:105`) explicitly acknowledges up to 3 such truncated shards (one per corpus). These partial shards carry an `rdf:type fi:*Shard` quad (which `_count_shards` counts) but no `fi:vocabVersion` quad. If such output is ever fed into the SHACL validation pipeline (e.g., by a future Phase 11 ingestion path), `fi:VocabPinShape` would fire on the truncated shard.

**Fix:** Restructure the emit loop to break only on shard boundaries:

```python
while emitted_for_corpus < corpus_target:
    subtype = self._pick_subtype()
    shard_quads = self._emit_shard_quads(...)
    # Only emit the shard if the entire shard fits in the remaining budget,
    # OR always emit full shards and accept slight over-run.
    for quad in shard_quads:
        store.add(quad)
        emitted_for_corpus += 1
        triples_emitted += 1
    shard_idx += 1
```

---

### IN-03: `vocab/__init__.py` Exposes `load_pyoxigraph_store` in `__all__` but Does Not Export `load_graph` — Minor `__all__` Asymmetry

**File:** `src/folio_insights/vocab/__init__.py:126-132`

**Issue:** `__all__` correctly lists both `load_graph` and `load_pyoxigraph_store`. No issue with the list itself. However, the module-level `NAMESPACES` typing uses `Mapping[str, Namespace]` (imported from `typing`), while Python 3.9+ allows `collections.abc.Mapping` directly. Minor style inconsistency with the rest of the codebase.

**Fix:** Change to `from collections.abc import Mapping` (Python 3.9+ compatible; no runtime impact):

```python
from collections.abc import Mapping
```

---

### IN-04: `bfo_mapping.ttl` Declares `@prefix bfo: <http://purl.obolibrary.org/obo/>` But Never Uses It in the Body

**File:** `src/folio_insights/vocab/bfo_mapping.ttl:18`

**Issue:** The `@prefix bfo:` declaration is present but all BFO IRI references in the body use the full `<http://purl.obolibrary.org/obo/BFO_xxxxxxx>` form (per the inline NOTE at line 19). The unused prefix declaration is TTL-valid but misleading — it implies `bfo:BFO_0000002` could be used as shorthand, when it is never used. Readers may attempt to add new rows using `bfo:` only to find the pattern inconsistent with existing rows.

**Fix:** Either remove the unused `@prefix bfo:` declaration, or convert all BFO IRI literals to use the prefix consistently:

```turtle
# Option A: remove unused prefix
# (delete line 18)

# Option B: use prefix consistently
fi:Continuant owl:equivalentClass bfo:BFO_0000002 ;
    rdfs:comment "BFO 2020 Continuant (BFO_0000002)." .
```

---

_Reviewed: 2026-05-31_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
