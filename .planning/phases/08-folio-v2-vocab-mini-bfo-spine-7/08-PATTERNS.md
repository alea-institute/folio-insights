# Phase 8: FOLIO v2 Vocab + Mini-BFO Spine (§7) - Pattern Map

**Mapped:** 2026-05-31
**Files analyzed:** 12 (10 new, 2 modified; 2 v1-legacy marker edits)
**Analogs found:** 11 / 12 (`docs/query-as-of.md` has no in-repo prose-doc analog — see "No Analog Found")

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/folio_insights/vocab/__init__.py` | package + module-constant + loader | request-response (graph load) | `src/folio_insights/governance/shape_validation.py` (TTL loader + namespace constant) + `src/folio_insights/polysemy/distinguo.py:33` (`FI_VOCAB` constant) | role-match (loader idiom) |
| `src/folio_insights/vocab/predicates.ttl` | TTL vocab file (OWL properties) | static asset | `src/folio_insights/export/shapes.ttl` (TTL prefix discipline) | partial (export ships TTL as static asset, but content is SHACL not OWL properties) |
| `src/folio_insights/vocab/classes.ttl` | TTL vocab file (OWL classes) | static asset | `src/folio_insights/export/shapes.ttl` + Phase 7 shape TTLs (prefix block conventions) | partial |
| `src/folio_insights/vocab/bfo_spine.ttl` | TTL vocab file (mini-ontology) | static asset | `src/folio_insights/export/shapes.ttl` | partial (no BFO mapping analog in repo) |
| `src/folio_insights/vocab/bfo_mapping.ttl` | TTL alignment file (owl:equivalentClass) | static asset | `src/folio_insights/export/shapes.ttl` (header convention only) | partial |
| `src/folio_insights/vocab/shapes.ttl` | SHACL shape | request-response (validation) | `src/folio_insights/governance/shapes/governance_log_shape.ttl` + `src/folio_insights/governance/shapes/role_assertion_shape.ttl` + `src/folio_insights/governance/shapes/supersession_shape.ttl` | exact (SHACL + sh:sparql idiom + bad-case polarity) |
| `src/folio_insights/temporal/as_of.py` | service / library helper | transform (graph query → rows) | `src/folio_insights/polysemy/similarity_query.py` (SPARQL query function over a graph) + `src/folio_insights/governance/shape_validation.py` (rdflib-only module pattern) | role-match (no existing rdflib-based supersession walker) |
| `docs/query-as-of.md` | doc | static reference | none in repo (see "No Analog Found") | none |
| **MOD** `src/folio_insights/shards/envelope.py` | model (Pydantic) | request-response (construction-time validation) | self — extending existing `ShardEnvelope`; field-pattern from Phase 6 `AttestedSignature` defaults + Phase 2 `transaction_time = Field(default_factory=…)` + Phase 3 `subtypes.py @model_validator(mode="after")` (the codebase's "refuse-mismatched-value" idiom; no `@field_validator` exists in repo today) | exact (model_validator) / role-match (field_validator is greenfield) |
| **MOD** `src/folio_insights/bench/generator.py` | utility (RDF emitter) | streaming (quads) | self — adding one constant + a per-shard `fi:vocabVersion` quad next to `FI`/`CORPUS`/`SHARD` at lines 51-55 and `_emit_shard_quads` at lines 200-261 | exact |
| **MOD** `src/folio_insights/services/owl_serializer.py` | v1-legacy comment marker | n/a | self — header-only annotation; no content change | exact |
| **MOD** `src/folio_insights/export/shapes.ttl` | v1-legacy comment marker | n/a | self — header-only annotation; no content change | exact |

## Pattern Assignments

---

### `src/folio_insights/vocab/__init__.py` (package + module-constant + rdflib/pyoxigraph loaders)

**Primary analog:** `src/folio_insights/governance/shape_validation.py`
**Secondary analogs:** `src/folio_insights/polysemy/distinguo.py:33` (module-level prefix constant) and `src/folio_insights/store/pyoxigraph_store.py:95-98` (`bulk_load` for the pyoxigraph round-trip parity helper).

**Imports + namespace constant pattern** — copy from `src/folio_insights/governance/shape_validation.py:32-62`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pyshacl
from rdflib import RDF, BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD

# Phase-local namespace — mirrors revision/shape_validation.py's FI namespace
FI = Namespace("https://folio-insights.example/")

# Directory holding the per-shape TTL files.
_SHAPES_DIR = Path(__file__).parent / "shapes"
```

**Adapt for Phase 8:**
- The CONTEXT.md calls for `importlib.resources` (D-09); the codebase has zero existing users today (`grep -rn "importlib.resources"` returns empty). The `Path(__file__).parent / "<asset>"` idiom (lines 62 + `services/shacl_validator.py:23`) is the project's established analog. **Planner decision:** use `importlib.resources.files("folio_insights.vocab")` per D-09; it is a greenfield pattern but justified by the package-asset distribution requirement. Document the divergence from the `Path(__file__).parent` analog in the plan.
- **CANONICAL** `fi:` prefix is `https://folio-insights.aleainstitute.ai/vocab/` (D-01; see `polysemy/distinguo.py:33`'s `FI_VOCAB`) — **NOT** the `https://folio-insights.example/` placeholder used in Phase 7 governance shapes (which the Phase 8 drift audit / D-12 may need to reconcile separately — but the governance shapes are explicitly out-of-scope per CONTEXT.md `code_context` §"Phase 8 must NOT touch these"; leave the placeholder until a later cleanup).

**Module-constant pattern** — copy from `src/folio_insights/polysemy/distinguo.py:32-33`:

```python
# Canonical folio-insights vocabulary IRI (PRD §7.1, VOCAB-02).
FI_VOCAB = "https://folio-insights.aleainstitute.ai/vocab/"
```

Phase 8 extends to (D-02):
```python
VOCAB_VERSION = "2026.05.0"  # CalVer YYYY.MM.PATCH
FI_PREFIX = "https://folio-insights.aleainstitute.ai/vocab/"
NAMESPACES: Mapping[str, Namespace] = {...}  # promote bench/generator.py:51-55 constants here
```

**TTL load pattern** — copy from `src/folio_insights/governance/shape_validation.py:80-98`:

```python
def _load_shape_graph(filename: str) -> Graph:
    """Load a per-shape TTL file from ``governance/shapes/``."""
    path = _SHAPES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(...)
    g = Graph()
    g.parse(str(path), format="turtle")
    return g
```

Phase 8 adapts as `load_graph(*, include_bfo_mapping: bool = False) -> Graph` — the `include_bfo_mapping` opt-in matches D-09's "downstream consumers who don't care about full BFO interop don't pay the parse cost."

**Pyoxigraph round-trip pattern** — copy from `src/folio_insights/store/pyoxigraph_store.py:95-98`:

```python
def bulk_load_nquads(self, path: Path) -> None:
    """Gate 2 step 1 — single-call bulk ingest"""
    with open(path, "rb") as f:
        self._store.bulk_load(f, format=RdfFormat.N_QUADS)
```

For Phase 8 `load_pyoxigraph_store()` — switch `RdfFormat.N_QUADS` → `RdfFormat.TURTLE` and load each of the 5 TTL files in sequence.

---

### `src/folio_insights/vocab/predicates.ttl` and `classes.ttl` (TTL vocab files)

**Primary analog:** `src/folio_insights/export/shapes.ttl` (header conventions only; the Phase 7 governance shapes are NEAR analogs but use `<https://folio-insights.example/>` placeholder, not canonical).

**Prefix-block pattern** — adapt from `src/folio_insights/export/shapes.ttl:1-7`:

```turtle
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix fi: <https://folio.openlegalstandard.org/modules/folio-insights/> .
```

**Adapt for Phase 8** — the canonical `fi:` is the v2 PRD §7 IRI, NOT the v1 frozen prefix above:

```turtle
@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
```

**owl:Ontology + owl:versionIRI block** — adapt from `src/folio_insights/services/owl_serializer.py:128-148` (Python rdflib equivalent of TTL emission); the Python adds RDF triples but PRD §7 calls for TTL header per file:

```turtle
<https://folio-insights.aleainstitute.ai/vocab/predicates>
    a owl:Ontology ;
    owl:versionIRI <https://folio-insights.aleainstitute.ai/vocab/2026.05.0/predicates> ;
    rdfs:label "FOLIO Insights v2 predicates" ;
    dc:description "PRD §7.1 fi:* predicate definitions" .
```

(D-05: each of the 5 TTL files carries its own `owl:versionIRI` including `VOCAB_VERSION`.)

**Minimal-imports rule** (CONTEXT.md `## Established Patterns`): per-file prefix declarations carry only what each file needs — no kitchen-sink imports. `bfo_mapping.ttl` is the ONLY file that imports the `bfo:` namespace.

---

### `src/folio_insights/vocab/bfo_spine.ttl` and `bfo_mapping.ttl`

**Primary analog:** `src/folio_insights/export/shapes.ttl` (header only).

**Class declaration pattern** — adapt the Python class-declaration idiom in `src/folio_insights/services/owl_serializer.py:168` (Python: `g.add((task_iri, RDF.type, OWL.Class))`) to TTL:

```turtle
fi:Continuant a owl:Class ;
    rdfs:label "Continuant" ;
    rdfs:comment "Mini-BFO spine: anything that persists through time." .
```

**Mapping pattern** — `bfo_mapping.ttl` (D-07: exhaustive `owl:equivalentClass`):

```turtle
@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/> .
@prefix bfo: <http://purl.obolibrary.org/obo/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

fi:Continuant owl:equivalentClass bfo:BFO_0000002 ;
    rdfs:comment "BFO 2020 Continuant; see PURL bfo/2020/bfo.owl" .
```

(BFO 2020 IRIs from CONTEXT.md `<canonical_refs>` §"Companion BFO source": `BFO_0000002` Continuant, `BFO_0000003` Occurrent, `BFO_0000004` IndependentContinuant, `BFO_0000015` Process, `BFO_0000016` Disposition, `BFO_0000019` Quality, `BFO_0000020` SpecificallyDependentContinuant, `BFO_0000023` Role, `BFO_0000031` GenericallyDependentContinuant.)

---

### `src/folio_insights/vocab/shapes.ttl` (SHACL belt)

**Primary analog:** `src/folio_insights/governance/shapes/governance_log_shape.ttl` (BEST overall SHACL idiom — sh:sparql polarity + bad-case-matches discipline) + `src/folio_insights/governance/shapes/role_assertion_shape.ttl` (sh:property + sh:in enumeration idiom) + `src/folio_insights/governance/shapes/supersession_shape.ttl` (the predicate-name overlap with `fi:supersedes` makes this a near-twin for `fi:SupersessionAlignmentShape`).

**Prefix block + NodeShape header pattern** — copy from `src/folio_insights/governance/shapes/role_assertion_shape.ttl:34-40`:

```turtle
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix fi: <https://folio-insights.example/> .

fi:RoleAssertionShape a sh:NodeShape ;
    sh:targetClass fi:RoleAssertion ;
```

**Adapt for Phase 8:** use the CANONICAL `fi:` prefix `<https://folio-insights.aleainstitute.ai/vocab/>` (D-01), NOT the `<https://folio-insights.example/>` placeholder. The Phase 7 shapes are quarantined per CONTEXT.md "Phase 8 must NOT touch these."

**`fi:VocabPinShape` (D-04) — sh:property + value-equality pattern** — adapt from `role_assertion_shape.ttl:43-50` (sh:in enumeration) and `supersession_shape.ttl:27-33` (sh:minCount/maxCount):

```turtle
fi:VocabPinShape a sh:NodeShape ;
    sh:targetClass fi:Shard ;  # OR each shard subclass
    sh:property [
        sh:path fi:vocabVersion ;
        sh:datatype xsd:string ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:hasValue "2026.05.0" ;
        sh:message "fi:vocabVersion must equal VOCAB_VERSION constant (D-04)" ;
    ] .
```

**`fi:SupersessionAlignmentShape` (D-10) — sh:sparql bad-case pattern** — copy structure from `supersession_shape.ttl:47-58` (the old==new self-supersede check) AND `governance_log_shape.ttl:60-74` (monotonicity SPARQL):

```turtle
sh:sparql [
    sh:message "fi:SupersessionAlignmentShape: A fi:supersedes B requires B.fi:validTimeEnd == A.fi:validTimeStart" ;
    sh:prefixes fi: ;
    sh:select """
        PREFIX fi: <https://folio-insights.aleainstitute.ai/vocab/>
        SELECT $this ?a ?b ?aStart ?bEnd WHERE {
            ?a fi:supersedes ?b .
            ?a fi:validTimeStart ?aStart .
            ?b fi:validTimeEnd ?bEnd .
            FILTER(STR(?aStart) != STR(?bEnd))
        }
    """ ;
] ;
```

**Polarity discipline** (verbatim from `supersession_shape.ttl:12-16` + `governance_log_shape.ttl:17-21`): SELECT matches the **BAD** case so a non-empty result set yields `conforms=False`. Pinned against pyshacl 0.31.0 + rdflib 7.6.0.

---

### `src/folio_insights/temporal/as_of.py` (library helper)

**Primary analog:** `src/folio_insights/polysemy/similarity_query.py:30-78` (rdflib/pyoxigraph SPARQL helper function that takes a graph and returns rows).
**Secondary analog:** `src/folio_insights/governance/shape_validation.py:32-62` (the rdflib-only module idiom + D-04 boundary discipline — "stdlib + rdflib only").

**Module header pattern** — adapt from `src/folio_insights/governance/shape_validation.py:1-40`:

```python
"""Phase 7 SHACL validator wrapper for the 8 governance shapes (D-04 exempt)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pyshacl
from rdflib import RDF, BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD

FI = Namespace("https://folio-insights.example/")
```

**Adapt for Phase 8 `as_of.py`** — no pyshacl, no governance imports; pure rdflib + stdlib (per CONTEXT.md `## Integration Points`: "Imports rdflib only. Has zero coupling to vocab/, revision/, or store/"):

```python
"""Phase 8 query_as_of: walk fi:supersedes / fi:validTimeStart/End to surface
the predicate's value as it was on at_date."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import XSD

FI = Namespace("https://folio-insights.aleainstitute.ai/vocab/")  # CANONICAL (D-01)
```

**SPARQL helper function pattern** — copy from `src/folio_insights/polysemy/similarity_query.py:36-78`:

```python
_DISJOINT_ASK = """
PREFIX fi: <https://folio-insights.aleainstitute.ai/vocab/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>

ASK {{
  GRAPH <{graph}> {{
    ?shard_a fi:termOfArt "{term}" ; fi:inFramework "{fw_a}" .
    ...
  }}
}}
"""


def has_framework_conflicting_axiom(
    store: "PyoxigraphStore",
    term: str,
    frameworks: list[str],
    named_graph: str = CONSIDERATION_NAMED_GRAPH,
) -> bool:
    ...
    sorted_fw = sorted(frameworks)
```

**Adapt for Phase 8 `query_as_of`** — D-10 signature: `query_as_of(graph: Graph, predicate: URIRef, at_date: date) -> list[Row]`:

```python
_AS_OF_SELECT = """
PREFIX fi: <https://folio-insights.aleainstitute.ai/vocab/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT ?subject ?object WHERE {
  ?subject ?predicate ?object .
  ?subject fi:validTimeStart ?start .
  OPTIONAL { ?subject fi:validTimeEnd ?end . }
  FILTER (?start <= ?at && (!BOUND(?end) || ?at < ?end))
}
"""
```

The supersession-chain walk (D-10: "walking the supersession chain backward using `fi:validTimeStart` / `fi:validTimeEnd`") has no in-repo analog — see "No Analog Found" → planner implements per PRD §21.9 valid-time semantics.

**Discretion handle (CONTEXT.md `### Claude's Discretion`):** signature accepts `Graph` only (rdflib-only, V1 minimum) — Phase 11 can widen to `Graph | Store` polymorphic when the persistent store lands.

---

### **MOD** `src/folio_insights/shards/envelope.py` (Pydantic envelope edit)

**Primary analog:** self — extend the existing `ShardEnvelope` (lines 186-346) and `AttestedSignature` (lines 111-167).

**Default-factory pattern** — copy from `src/folio_insights/shards/envelope.py:301-303`:

```python
transaction_time: datetime = Field(
    default_factory=lambda: datetime.now(UTC)
)
```

**Adapt for Phase 8 D-03:**

```python
from folio_insights.vocab import VOCAB_VERSION

# Inside ShardEnvelope class body, alongside existing bitemporal fields:
vocab_version: str = Field(default_factory=lambda: VOCAB_VERSION)
```

**Validator pattern** — `field_validator` does not yet appear in the codebase (`grep -rn "field_validator" src/` is empty). The codebase's "refuse-mismatched-value" idiom is `@model_validator(mode="after")` — see `src/folio_insights/shards/envelope.py:313-346` and `src/folio_insights/shards/subtypes.py:105-127`:

```python
@model_validator(mode="after")
def _disputed_invariants(self) -> "DisputedPropositionShard":
    """D-02/D-03: epistemic_status ∈ 4-subset, ≥1 objection, valid reply indices."""
    if self.epistemic_status not in _DISPUTED_EPISTEMIC_STATUS_SUBSET:
        raise ValueError(
            f"DisputedPropositionShard.epistemic_status must be one of "
            f"{sorted(_DISPUTED_EPISTEMIC_STATUS_SUBSET)}; "
            f"got {self.epistemic_status!r} (CONTEXT D-03 4-subset)."
        )
    ...
    return self
```

**Planner decision for D-03:** CONTEXT.md D-03 calls for `field_validator("vocab_version")` specifically — a greenfield Pydantic primitive in this repo. Either:
- (a) Introduce `@field_validator("vocab_version")` per D-03 verbatim (greenfield idiom, slightly less verbose), OR
- (b) Use `@model_validator(mode="after")` matching the existing `envelope.py:313` precedent (uniform with the codebase).

Both yield identical behavior. Planner picks based on consistency vs. CONTEXT-verbatim fidelity. **Recommended:** (a) per D-03 verbatim; document in PLAN that this is the first `field_validator` in the codebase.

**Sample (option a):**
```python
from pydantic import field_validator
from folio_insights.vocab import VOCAB_VERSION

@field_validator("vocab_version")
@classmethod
def _check_vocab_pin(cls, v: str) -> str:
    if v != VOCAB_VERSION:
        raise ValueError(
            f"vocab_version must equal module constant {VOCAB_VERSION!r}; "
            f"got {v!r} (Phase 8 D-03 / D-04 two-belt enforcement)."
        )
    return v
```

---

### **MOD** `src/folio_insights/bench/generator.py` (RDF emitter edit)

**Primary analog:** self — extend the existing namespace block at lines 51-55 and the per-shard emission at `_emit_shard_quads` lines 200-261.

**Constants block** — current state at `src/folio_insights/bench/generator.py:49-57`:

```python
# Vocab namespaces — MUST match Phase 8 fi:* when those land; for Phase 0
# the generator uses stable canonical IRIs.
FI = "https://folio-insights.aleainstitute.ai/vocab/"
CORPUS = "https://folio-insights.aleainstitute.ai/corpus/"
SHARD = "https://folio-insights.aleainstitute.ai/shard/"
CONCEPT = "https://folio-insights.aleainstitute.ai/concept/"
FRAMEWORK = "https://folio-insights.aleainstitute.ai/framework/"
```

**Adapt for Phase 8 (CONTEXT.md `### Reusable Assets`):** import from the new `folio_insights.vocab` package; replace the local constants with re-exports (or import-and-alias). The file's own comment ("MUST match Phase 8 fi:* when those land") flags this swap as planned.

```python
from folio_insights.vocab import (
    VOCAB_VERSION,
    NAMESPACES,  # Mapping[str, Namespace]
)
FI = str(NAMESPACES["fi"])  # back-compat alias for the existing string-format usage
```

**Per-shard `fi:vocabVersion` emission** — adapt from `src/folio_insights/bench/generator.py:218-226` (the `framework` quad pattern):

```python
# Framework quad (deterministic per shard_idx)
fw = _FW_CHOICES[shard_idx % len(_FW_CHOICES)]
out.append(
    Quad(
        shard_iri,
        NamedNode(f"{FI}framework"),
        NamedNode(f"{FRAMEWORK}{fw}"),
        graph_iri,
    )
)
```

**Phase 8 addition** — one extra Quad per shard:

```python
out.append(
    Quad(
        shard_iri,
        NamedNode(f"{FI}vocabVersion"),
        Literal(VOCAB_VERSION),
        graph_iri,
    )
)
```

**Determinism note:** the Phase 0 D-15 contract ("same --seed produces byte-identical N-Quads") means this 1-quad-per-shard addition shifts EVERY bench digest. Plan must include the digest update + a regression test that pins the new digest.

---

### **MOD** `src/folio_insights/services/owl_serializer.py` (v1-legacy marker, header-only)

**No functional change.** Per CONTEXT.md `<specifics>` §"FOLIO canonical IRIs are sacred":

Current state at `src/folio_insights/services/owl_serializer.py:1-20`:
```python
"""OWL ontology graph construction from approved review data.
..."""

from __future__ import annotations

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DC, OWL, PROV, RDF, RDFS, SKOS, XSD

# Namespaces
FOLIO = Namespace("https://folio.openlegalstandard.org/")
FOLIO_INSIGHTS = Namespace(
    "https://folio.openlegalstandard.org/modules/folio-insights/"
)
```

**Phase 8 edit (D-01b):** insert a single comment marker after the module docstring, before the imports:

```python
# v1-legacy — DO NOT migrate to v2 prefix (Phase 8 D-01b).
# The https://folio.openlegalstandard.org/ FOLIO canonical IRIs are SACRED
# (untouched per D-01a) and the .../modules/folio-insights/ extension prefix
# below is FROZEN to the v1 OWL export pipeline. Greenfield-on-master is the
# cover; no bridge axioms, no dual-emission, no rewrite.
```

---

### **MOD** `src/folio_insights/export/shapes.ttl` (v1-legacy marker, header-only)

Current state at `src/folio_insights/export/shapes.ttl:1-7` — the `fi:` prefix here is the v1 frozen extension prefix.

**Phase 8 edit (D-01b):** insert a TTL comment at the top of the file:

```turtle
# v1-legacy — DO NOT migrate to v2 prefix (Phase 8 D-01b).
# This shapes file is owned by the v1 OWL export pipeline (services/owl_serializer.py).
# The fi: prefix below is the FROZEN v1 extension IRI, NOT the v2
# https://folio-insights.aleainstitute.ai/vocab/ canonical (D-01).

@prefix sh: <http://www.w3.org/ns/shacl#> .
...
```

---

## Shared Patterns

### Canonical `fi:` prefix discipline (D-01, D-01a, D-01b)

**Source of truth:** `src/folio_insights/polysemy/distinguo.py:32-33`
**Apply to:** every new vocab/* TTL file, the new vocab/__init__.py, the new temporal/as_of.py.

```python
FI_VOCAB = "https://folio-insights.aleainstitute.ai/vocab/"
```

**The three prefix universes (do not confuse):**
1. `https://folio.openlegalstandard.org/` — upstream FOLIO canonical (SACRED; never touched).
2. `https://folio.openlegalstandard.org/modules/folio-insights/` — v1 FROZEN (only `services/owl_serializer.py`, `export/shapes.ttl`).
3. `https://folio-insights.aleainstitute.ai/vocab/` — v2 CANONICAL (every Phase 8 new file).

Phase 7 governance shapes use `https://folio-insights.example/` as a placeholder; CONTEXT.md `## Integration Points` § "Phase 8 must NOT touch these" — leave for a later cleanup.

### Two-belt enforcement (Phase 6/7 convention)

**Sources:** `src/folio_insights/shards/envelope.py:111-167` (Pydantic belt) + `src/folio_insights/governance/shapes/*.ttl` (SHACL belt).
**Apply to:** the D-04 VocabPin gate.

Pydantic catches at construction (envelope `vocab_version` validator); SHACL catches at storage/export (`vocab/shapes.ttl::fi:VocabPinShape`). Two belts close the smuggle-raw-triples gap.

### SHACL sh:sparql polarity discipline

**Source:** `src/folio_insights/governance/shapes/governance_log_shape.ttl:12-21` + `supersession_shape.ttl:12-16`.
**Apply to:** every sh:sparql constraint in `vocab/shapes.ttl` (`fi:SupersessionAlignmentShape` especially).

```turtle
# Polarity discipline: the sh:sparql SELECT matches the BAD case so a
# non-empty result set yields conforms=False. Polarity spiked against
# pyshacl 0.31.0 + rdflib 7.6.0.
```

### Module-docstring + D-xx citation discipline

**Source:** every Phase 7 file (`governance/events.py:1-28`, `governance/shape_validation.py:1-31`, shape TTLs lines 1-28).
**Apply to:** every new Phase 8 file.

Module docstring opens with phase + scope; cites the specific D-XX decision number; documents what the file does and what it cannot do (the "CANNOT enforce" half is load-bearing — see `governance_log_shape.ttl:23-28`).

### TTL prefix-block minimalism

**Source:** Phase 7 governance shapes consistently carry only the prefixes they need (`role_assertion_shape.ttl:34-37` is 4 lines; `supersession_shape.ttl:18-21` is 4 lines).
**Apply to:** every Phase 8 TTL — `predicates.ttl` needs `fi:`, `owl:`, `rdfs:`, `xsd:`. `bfo_mapping.ttl` adds `bfo:`. `shapes.ttl` adds `sh:`. No kitchen-sink imports.

### D-04 dep-leak boundary discipline (rdflib quarantine)

**Source:** `tests/governance/test_dep_leak_guard.py:32-60` (the dep-leak test pattern) + `governance/shape_validation.py:14-31` (the exempt-module doctrine).
**Apply to:** `temporal/as_of.py` (CONTEXT.md: "Imports rdflib only. Has zero coupling to vocab/, revision/, or store/ — D-04 dep-leak discipline mirrors Phase 7 governance").

Plan should add `tests/temporal/test_dep_leak_guard.py` modeled on `tests/governance/test_dep_leak_guard.py:1-60`, with `FORBIDDEN = ["pyoxigraph", "oxrdflib", "pyshacl"]` (rdflib IS allowed; the as_of helper is rdflib-native by D-10).

---

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md or PRD §7 patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `docs/query-as-of.md` | doc | static reference | No `docs/` directory exists in the repo today (only top-level READMEs and PRD-v2.0-draft-2.md). Planner sets `docs/` precedent. Format: prose + a 20-line SPARQL block per D-10 + cross-link to Phase 11/12. |
| Supersession-chain walk inside `temporal/as_of.py` | transform | recursive graph walk | No existing rdflib-based supersession walker. Closest distant analog: the `fi:supersededBy` chain emission in `bench/generator.py:264-273`. Planner implements per PRD §21.9 + the SPARQL pattern in `docs/query-as-of.md` will be authoritative reference. |
| `importlib.resources` package-asset loader | utility | static asset | No existing user (`grep -rn "importlib.resources" src/` is empty). The project pattern is `Path(__file__).parent / "<asset>"`. D-09 explicitly calls for `importlib.resources` — first user in the codebase. |

---

## Metadata

**Analog search scope:** `src/folio_insights/{shards,governance,polysemy,revision,services,export,bench,store,temporal,vocab}/`
**Files scanned:** ~25 source files + 9 TTL files
**Pattern extraction date:** 2026-05-31
