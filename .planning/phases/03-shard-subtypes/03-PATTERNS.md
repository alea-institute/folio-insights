# Phase 03: Shard Subtypes (§6.2) — Pattern Map

**Mapped:** 2026-04-25
**Files analyzed:** 10 (2 modify, 8 create)
**Analogs found:** 10 / 10 (all in-repo; high confidence)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/folio_insights/shards/subtypes.py` (MODIFY) | model | transform/validate | `src/folio_insights/shards/envelope.py` (Pydantic v2 base) + `src/folio_insights/polysemy/distinguo.py::ForkProposal` (model_validator) | exact (both dimensions) |
| `src/folio_insights/shards/__init__.py` (MODIFY) | barrel/config | re-export | (itself) — extend existing pattern | exact |
| `tests/shards/fixtures/example_a1_simple_assertion.json` (CREATE) | test fixture | static JSON | (no JSON fixtures yet in repo — first of kind) | no analog (greenfield) |
| `tests/shards/fixtures/example_a2_conflicting_authorities.json` (CREATE) | test fixture | static JSON | (same) | no analog (greenfield) |
| `tests/shards/fixtures/example_a3_disputed_proposition.json` (CREATE) | test fixture | static JSON | (same) | no analog (greenfield) |
| `tests/shards/test_subtype_simple_assertion.py` (CREATE) | test | request-response | `tests/shards/test_envelope_roundtrip.py` | exact |
| `tests/shards/test_subtype_disputed_proposition.py` (CREATE) | test | request-response + validator-raises | `tests/shards/test_envelope_roundtrip.py` + `tests/shards/test_discriminated_union.py` (ValidationError pattern) | exact |
| `tests/shards/test_subtype_conflicting_authorities.py` (CREATE) | test | request-response + validator-raises | `tests/shards/test_envelope_roundtrip.py` + `tests/shards/test_discriminated_union.py` | exact |
| `tests/shards/test_subtype_gloss.py` (CREATE) | test | validator-raises (regex/format) | `tests/shards/test_discriminated_union.py` | role-match |
| `tests/shards/test_subtype_hypothesis.py` (CREATE) | test | request-response (defaults) | `tests/shards/test_envelope_roundtrip.py` | exact |
| `tests/shards/test_subtype_properties.py` (CREATE) | test | property-based (hypothesis) | `tests/shards/test_minting_determinism.py` | exact |

---

## Pattern Assignments

### `src/folio_insights/shards/subtypes.py` (MODIFY — model, transform/validate)

**Analogs:**
1. **`src/folio_insights/shards/envelope.py`** — Pydantic v2 conventions, ConfigDict, frozen fields, Literal enums, forward-ref + model_rebuild idiom
2. **`src/folio_insights/polysemy/distinguo.py`** — `@model_validator(mode='after')` invariant pattern + matching `validate_*_shape()` defense-in-depth function (NOTE: Phase 3 only needs the validator; no defense-in-depth function required because subtypes are not currently rehydrated via `model_construct()`)

**Module header pattern** (envelope.py:32–37):
```python
"""<Module docstring with PRD ref + key locked decisions>."""
from __future__ import annotations

from datetime import UTC, datetime  # only if needed (not for Phase 3)
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
```

For Phase 3 specifically, also import `model_validator` and any nested `re` module if regex is used:
```python
import re
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator
from folio_insights.shards.envelope import ShardEnvelope
```

**Nested-model pattern** (envelope.py:69–82, `Triple`):
```python
class Triple(BaseModel):
    """<Docstring>."""
    model_config = ConfigDict(extra="forbid")

    subject: str
    predicate: str
    object: str
    object_datatype: Optional[str] = None
```

Apply this verbatim shape to `Objection`, `Reply`, `AuthorityPosition` — each gets `model_config = ConfigDict(extra="forbid")` (CONTEXT D-02/D-04 specifies `frozen=False`, which is the Pydantic default; the explicit `frozen=False` in CONTEXT is for clarity but emit just `extra="forbid"` to match envelope.py's house style).

**Literal-enum pattern** (envelope.py:39–46, `ShardType`):
```python
# D-05: canonical discriminator alias (5 values, ordered per CONTEXT D-05).
ShardType = Literal[
    "simple_assertion",
    "disputed_proposition",
    "conflicting_authorities",
    "gloss",
    "hypothesis",
]
```

Apply to `ReconciliationStrategy` (8 values), `GlossKind` (5 values), `GenerationMethod` (3 values) — module-level type aliases declared **above** the class that uses them, with a comment naming the CONTEXT decision (`# D-04: 8-value reconciliation strategy lock (no escape hatch).`).

**Subtype expansion pattern** (envelope.py:85–99 + subtypes.py:11–13):
```python
class <SubtypeName>Shard(ShardEnvelope):
    """<PRD §6.2.X — one-line summary>."""
    shard_type: Literal["<tag>"] = "<tag>"
    # ── Subtype-specific fields (PRD §6.2.X) ──
    <field>: <type>                                  # required
    <field_with_default>: list[str] = Field(default_factory=list)
```

`ShardEnvelope` already declares `model_config = ConfigDict(extra="forbid")` (envelope.py:98), so subclasses inherit it automatically — **do NOT redeclare** `model_config` on subtype classes (it's inherited; redeclaration would be redundant and could mask future envelope changes).

**`@model_validator(mode='after')` pattern** (distinguo.py:70–84):
```python
@model_validator(mode="after")
def _<descriptive_name>(self) -> "<SubtypeName>Shard":
    """<One-line invariant description with CONTEXT D-XX ref>."""
    if <invariant_violated>:
        raise ValueError(
            "<concrete error message naming the constraint and the offending value>"
        )
    return self
```

Note: distinguo.py uses `raise ValueError(...)` — Pydantic v2 wraps this in `ValidationError` automatically. Tests assert via `pytest.raises(ValidationError, match="<substring>")` (envelope_roundtrip.py:110 pattern).

**Phase 3 validator targets** (one per subtype, lines from CONTEXT):
- `DisputedPropositionShard._epistemic_status_subset` → constrain `epistemic_status ∈ {"hypothesis", "attested", "contested", "aporetic"}` + ≥1 objection + every `Reply.objection_index` is a valid `range(len(self.objections))` index. **Caveat:** the envelope's `epistemic_status` Literal does NOT contain `"attested"` (envelope.py:139–148 has `per_se_nota_quoad_se`, `per_se_nota_quoad_nos`, `demonstrable`, `authority_only`, `aporetic`, `hypothesis`, `contested`, `superseded`). Planner must reconcile CONTEXT D-03's named subset (`{"hypothesis", "attested", "contested", "aporetic"}`) with the actual envelope Literal — recommend the planner flag this as a clarifying question in PLAN.md and propose either (a) substituting `"authority_only"` for `"attested"` or (b) extending the envelope Literal in a Phase 02 carry-forward errata. **Do not silently pick a substitute.**
- `ConflictingAuthoritiesShard._sic_non_non_empty` → `len(sic) >= 1`, `len(non) >= 1`, `reconciliation_note.strip() != ""`.
- `GlossShard._gloss_format` → `re.match(r"^urn:folio:shard/[a-f0-9]{16}$", self.glosses)` OR `re.match(r"^https?://[^\s]+$", self.glosses)` + `self.glosses != self.shard_iri` + `self.gloss_text.strip() != ""`. Reuse the IRI prefix shape from `minting.py:24` (`_IRI_PREFIX = "urn:folio:shard/"`) — but Phase 3 should re-declare the regex literally inside `subtypes.py` rather than importing the private `_IRI_PREFIX` constant (private = leading underscore, so importing crosses an encapsulation boundary).
- `HypothesisShard._ttl_positive` → `ttl_days >= 1`. **No** citation gate (CONTEXT D-06: deferred to Phase 7).
- `SimpleAssertionShard` — **no validator** (CONTEXT D-01: empty subtype).

**Discriminated-union shape (UNCHANGED — copy from current subtypes.py:36–45):**
```python
Shard = Annotated[
    Union[
        SimpleAssertionShard,
        DisputedPropositionShard,
        ConflictingAuthoritiesShard,
        GlossShard,
        HypothesisShard,
    ],
    Field(discriminator="shard_type"),
]
```

**`__all__` pattern** (subtypes.py:48–55) — extend to include nested models + type aliases:
```python
__all__ = [
    "AuthorityPosition",
    "ConflictingAuthoritiesShard",
    "DisputedPropositionShard",
    "GenerationMethod",
    "GlossKind",
    "GlossShard",
    "HypothesisShard",
    "Objection",
    "ReconciliationStrategy",
    "Reply",
    "Shard",
    "SimpleAssertionShard",
]
```

Alphabetical ordering matches existing repo convention.

---

### `src/folio_insights/shards/__init__.py` (MODIFY — barrel re-exports)

**Analog:** itself, lines 1–33 (current `__init__.py`).

**Pattern to extend:**
```python
from folio_insights.shards.subtypes import (
    AuthorityPosition,           # NEW
    ConflictingAuthoritiesShard,
    DisputedPropositionShard,
    GenerationMethod,            # NEW (type alias)
    GlossKind,                   # NEW (type alias)
    GlossShard,
    HypothesisShard,
    Objection,                   # NEW
    ReconciliationStrategy,      # NEW (type alias)
    Reply,                       # NEW
    Shard,
    SimpleAssertionShard,
)
```

Add the same 6 names to `__all__` in alphabetical order.

---

### `tests/shards/fixtures/example_a1_simple_assertion.json` (CREATE — static JSON fixture)

**No in-repo analog** — Phase 3 is the first phase to commit JSON test fixtures. CONTEXT D-09 specifies these are verbatim transcriptions of PRD §6.2 Examples A.1, A.2, A.3.

**Recommended shape** (planner extracts verbatim from `PRD-v2.0-draft-2.md` §6.2 examples):
- Each fixture contains every required envelope field (22 from envelope.py:101–211) + all subtype-specific fields.
- For `shard_iri` + `provenance_hash` fields, use **deterministic placeholder values** matching what `mint_shard_iri("urn:x:fixture-a1", "<span>")` would produce — OR — leave the fixture's IRI placeholder and have the test re-mint via `mint_shard_iri` and overwrite. CONTEXT specifies the test re-mints, so JSON can carry pre-computed IRIs and the test asserts they match.

**Test loading idiom** (planner derives — no analog yet):
```python
import json
from pathlib import Path
FIXTURE = Path(__file__).parent / "fixtures" / "example_a1_simple_assertion.json"
data = json.loads(FIXTURE.read_text())
```

---

### `tests/shards/test_subtype_simple_assertion.py` (CREATE — test, request-response)

**Analog:** `tests/shards/test_envelope_roundtrip.py:1–123`

**Imports + module setup pattern** (test_envelope_roundtrip.py:1–22):
```python
"""<Test module docstring with REQ-ID + exit criterion ref>."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from folio_insights.shards import (
    Shard,
    SimpleAssertionShard,
    mint_shard_iri,
)
from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.shards
```

**Verbatim-fixture round-trip pattern** (derived from test_envelope_roundtrip.py:39–46 + test_discriminated_union.py:24–30):
```python
def test_a1_fixture_round_trips() -> None:
    """PRD §6.2.1 Example A.1 round-trips via TypeAdapter(Shard)."""
    fixture = Path(__file__).parent / "fixtures" / "example_a1_simple_assertion.json"
    payload = json.loads(fixture.read_text())
    parsed = TypeAdapter(Shard).validate_python(payload)
    assert isinstance(parsed, SimpleAssertionShard)
    assert parsed.shard_type == "simple_assertion"
    assert parsed.model_dump() == payload  # bidirectional round-trip
```

**Edge-case pattern** (envelope_roundtrip.py:117–122 — extra="forbid" guard):
```python
def test_extra_field_rejected() -> None:
    payload = _sample_shard(SimpleAssertionShard).model_dump()
    payload["unknown"] = "nope"
    with pytest.raises(ValidationError):
        SimpleAssertionShard.model_validate(payload)
```

---

### `tests/shards/test_subtype_disputed_proposition.py` (CREATE — test, validator-raises)

**Analog:** `tests/shards/test_envelope_roundtrip.py` + `tests/shards/test_discriminated_union.py:33–43` (ValidationError-with-message assertion)

**Validator-raises pattern** (test_discriminated_union.py:33–43):
```python
def test_<invariant_name>_raises() -> None:
    """<CONTEXT D-XX> — <one-line invariant description>."""
    payload = _sample_shard(DisputedPropositionShard).model_dump()
    payload["objections"] = []  # violate ≥1 invariant
    with pytest.raises(ValidationError) as exc_info:
        DisputedPropositionShard.model_validate(payload)
    msg = str(exc_info.value)
    assert "objections" in msg.lower() or "at least one" in msg.lower()
```

**Phase 3 invariants to test** (CONTEXT D-02, D-03):
- A.3 fixture round-trips
- `epistemic_status` outside the 4-value subset raises (parametrize over invalid values from envelope's broader 8-value Literal)
- `objections=[]` raises
- `Reply.objection_index` out of range raises

**Conftest extension caveat:** `_sample_shard(DisputedPropositionShard)` currently constructs a stub (no required subtype fields). After Phase 3 adds required fields (`utrum`, `objections`, `sed_contra`, `respondeo`, `replies`), `_sample_shard` will fail unless updated. **Planner must extend `tests/shards/conftest.py`** to provide subtype-specific defaults for the 4 new-field subtypes (likely via a `_subtype_defaults: dict[type, dict]` lookup table merged into `defaults` before `cls(**defaults)`).

---

### `tests/shards/test_subtype_conflicting_authorities.py` (CREATE — test, validator-raises)

**Analog:** Same as test_subtype_disputed_proposition.py.

**Phase 3 invariants** (CONTEXT D-04):
- A.2 fixture round-trips
- All 8 `ReconciliationStrategy` values parametrized + each constructs successfully
- A 9th value (e.g., `"custom"`) raises `ValidationError` (Literal constraint)
- `sic=[]` raises; `non=[]` raises
- `reconciliation_note=""` and `reconciliation_note="   "` raise
- `AuthorityPosition.weight` outside 4-value Literal raises

**Parametrize pattern** (envelope_roundtrip.py:28–35 + 102–111):
```python
@pytest.mark.parametrize("strategy", [
    "sense_distinction", "contextual_limitation", "voice_attribution",
    "textual_correction", "retraction_later", "subsequent_overruling",
    "jurisdictional_scoping", "unreconciled",
])
def test_each_reconciliation_strategy_constructs(strategy: str) -> None:
    shard = _sample_shard(ConflictingAuthoritiesShard, reconciliation_strategy=strategy, ...)
    assert shard.reconciliation_strategy == strategy
```

---

### `tests/shards/test_subtype_gloss.py` (CREATE — test, validator-raises)

**Analog:** test_discriminated_union.py:33–43 + envelope_roundtrip.py.

**Phase 3 invariants** (CONTEXT D-05):
- All 5 `GlossKind` values construct
- Valid `glosses` IRI shapes accepted: `urn:folio:shard/<16-hex>`, `https://...`, `http://...`
- Invalid shapes rejected: empty string, `urn:folio:shard/zzz`, `ftp://...`, `urn:folio:shard/<too-short-hex>`
- `glosses == self.shard_iri` raises (self-glossing)
- `gloss_text=""` and whitespace-only raise

---

### `tests/shards/test_subtype_hypothesis.py` (CREATE — test, defaults + boundaries)

**Analog:** envelope_roundtrip.py.

**Phase 3 invariants** (CONTEXT D-06):
- All 3 `GenerationMethod` values construct
- `ttl_days` defaults to `90`
- `ttl_days = 0` raises; `ttl_days = -1` raises; `ttl_days = 1` accepts; `ttl_days = 1_000_000` accepts
- `citation_required` defaults to `True`
- `promotion_requirements` defaults to `[]`
- **Explicit non-test:** A `HypothesisShard(citation_required=True, depends_on_axioms=[], depends_on_definitions=[], depends_on_precedents=[], depends_on_shards=[])` constructs successfully (Phase 7 owns the gate, NOT Phase 3 — add a comment naming this).

---

### `tests/shards/test_subtype_properties.py` (CREATE — test, hypothesis property-based)

**Analog:** `tests/shards/test_minting_determinism.py:1–48` (hypothesis adoption pattern).

**Imports + settings pattern** (test_minting_determinism.py:10–20, 26):
```python
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from folio_insights.shards import (
    ConflictingAuthoritiesShard, DisputedPropositionShard,
    GlossShard, HypothesisShard, SimpleAssertionShard,
)
from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.shards
```

**Per-subtype @given + @settings pattern** (test_minting_determinism.py:26–47):
```python
@settings(max_examples=300, deadline=None)  # CONTEXT D-09: 300 for DisputedProp
@given(
    utrum=st.text(min_size=1, max_size=200),
    n_objections=st.integers(min_value=1, max_value=5),
    respondeo=st.text(min_size=1, max_size=500),
    # ... per-field strategies
)
def test_disputed_proposition_constructs_round_trips(
    utrum: str, n_objections: int, respondeo: str, ...
) -> None:
    objections = [Objection(cites="urn:x:1", argues="a", strength=0.5) for _ in range(n_objections)]
    shard = _sample_shard(DisputedPropositionShard, utrum=utrum, objections=objections, ...)
    rehydrated = DisputedPropositionShard.model_validate(shard.model_dump())
    assert rehydrated == shard
```

**Per-subtype example budget (CONTEXT D-09):**
- SimpleAssertion: `max_examples=100`
- DisputedProposition: `max_examples=300`
- ConflictingAuthorities: `max_examples=200`
- Gloss: `max_examples=200`
- Hypothesis: `max_examples=200`
- Total ≤ 1000; CI runtime budget < 2s.

**Strategy patterns** (test_minting_determinism.py:28–35):
- `st.sampled_from([...])` for Literal enums (matches scheme= sampled_from on line 28)
- `st.text(min_size=N, max_size=M)` for free strings
- `st.floats(min_value=0.0, max_value=1.0, allow_nan=False)` for `Objection.strength` (note: envelope.py:188 uses `Field(ge=0.0, le=1.0)`)
- `st.integers(min_value=1, max_value=10000)` for `ttl_days`
- `st.lists(<inner_strategy>, min_size=1, max_size=5)` for ≥1-element list invariants

---

## Shared Patterns

### Pattern 1: Pydantic v2 Frozen / extra=forbid Convention

**Source:** `src/folio_insights/shards/envelope.py:98`
**Apply to:** All Pydantic models declared in `subtypes.py`.

```python
class <Model>(BaseModel):
    """<docstring>."""
    model_config = ConfigDict(extra="forbid")
    # fields...
```

Subtype classes inherit `model_config` from `ShardEnvelope` (envelope.py:98) — do **not** redeclare. Nested models (`Objection`, `Reply`, `AuthorityPosition`) are NEW BaseModel subclasses and **must** declare it themselves.

### Pattern 2: `@model_validator(mode='after')` Invariant Block

**Source:** `src/folio_insights/polysemy/distinguo.py:70–84`
**Apply to:** `DisputedPropositionShard`, `ConflictingAuthoritiesShard`, `GlossShard`, `HypothesisShard` (per CONTEXT D-02..D-06).

```python
@model_validator(mode="after")
def _<descriptive_name>(self) -> "<ClassName>":
    """<One-line invariant + CONTEXT D-XX ref>."""
    if <bad_condition>:
        raise ValueError("<concrete message>")
    return self
```

Multiple invariants in one validator: keep them in a single method per subtype, raising on the first violation. (distinguo.py:70–84 demonstrates this — two checks under one `if self.uses_analogousTo:` guard.)

### Pattern 3: Module-level Literal Type Alias with CONTEXT-anchored Comment

**Source:** `src/folio_insights/shards/envelope.py:39–46` (`ShardType`); `src/folio_insights/polysemy/distinguo.py:37–42` (`DistinctionKind`)
**Apply to:** `ReconciliationStrategy`, `GlossKind`, `GenerationMethod`.

```python
# CONTEXT D-XX: <8-value lock | 5-value enum | 3-value enum>
<AliasName> = Literal[
    "<value1>",
    "<value2>",
    ...
]
```

Declare **above** the class that uses it. Re-export from `__init__.py`.

### Pattern 4: `pytest.raises(ValidationError, match=...)` for Validator Tests

**Source:** `tests/shards/test_envelope_roundtrip.py:108–111`; `tests/shards/test_discriminated_union.py:37–43`
**Apply to:** Every validator-raises test in `test_subtype_*.py`.

```python
with pytest.raises(ValidationError, match="<substring>"):
    <ClassName>.model_validate(payload_with_violation)
```

For looser matching (across Pydantic minor versions), capture and check `str(exc_info.value)` for either a field name or a phrase (test_discriminated_union.py:42–43 idiom).

### Pattern 5: `pytestmark = pytest.mark.shards` for Test Module Marking

**Source:** `tests/shards/test_envelope_roundtrip.py:22`; `tests/shards/test_minting_determinism.py:20`; `tests/shards/test_discriminated_union.py:19`
**Apply to:** All 6 new `test_subtype_*.py` files.

Module-level constant after imports:
```python
pytestmark = pytest.mark.shards
```

### Pattern 6: `@settings(max_examples=N, deadline=None)` for Hypothesis Tests

**Source:** `tests/shards/test_minting_determinism.py:26`
**Apply to:** Every `@given`-decorated test in `test_subtype_properties.py`.

```python
@settings(max_examples=N, deadline=None)
@given(...)
def test_...(...) -> None:
    ...
```

`deadline=None` is non-negotiable for CI — it avoids per-example 200ms timing flakes (test_minting_determinism.py:6–8 docstring rationale).

### Pattern 7: `_sample_shard(cls, **overrides)` Test Construction

**Source:** `tests/shards/conftest.py:31–80`
**Apply to:** Every test that constructs a subtype instance.

**Phase 3 extension required:** `_sample_shard` currently provides envelope defaults but **no subtype-specific defaults**. Once Phase 3 adds required subtype fields, callers must pass them via `**overrides`, OR — preferred — extend conftest.py with a `_SUBTYPE_DEFAULTS` lookup:

```python
_SUBTYPE_DEFAULTS: dict[type, dict[str, Any]] = {
    DisputedPropositionShard: {
        "utrum": "Whether default fixture utrum holds?",
        "objections": [Objection(cites="urn:x:1", argues="a", strength=0.5)],
        "sed_contra": Objection(cites="urn:x:2", argues="b", strength=0.8),
        "respondeo": "I respond that...",
        "replies": [Reply(objection_index=0, replies_via="distinguo", argument="...")],
    },
    # ... per subtype
}
```

Merge into `defaults` before `defaults.update(overrides)` so callers can still override.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `tests/shards/fixtures/example_a*.json` (3 files) | test fixture | static JSON | Phase 3 is the first phase to commit JSON test fixtures. Pattern is straightforward (literal JSON files), but no template exists in repo. Planner should source content verbatim from `PRD-v2.0-draft-2.md` §6.2 examples A.1, A.2, A.3, ensuring every required envelope field is present. |

---

## Cross-Cutting Caveats for Planner

1. **`epistemic_status` 4-subset mismatch** (CONTEXT D-03 vs envelope.py:139–148): The CONTEXT names `{"hypothesis", "attested", "contested", "aporetic"}` as the DisputedProp subset, but `"attested"` is **not** a value in the envelope's 8-value Literal. Planner must surface this in PLAN.md as an explicit clarifying decision (likely: substitute `"authority_only"` for `"attested"`, OR extend the envelope Literal). Do not silently choose.

2. **`conftest.py` extension is implicit but mandatory:** None of the new `test_subtype_*.py` files can call `_sample_shard(DisputedPropositionShard)` etc. without conftest.py providing subtype-specific required-field defaults. Planner must include a conftest.py edit in the same plan as the subtypes.py expansion (or as a Wave-0 prerequisite plan), otherwise every subtype test fails at construction.

3. **Dep-leak guard (CONTEXT D-11):** `subtypes.py` must NOT import `pyoxigraph`, `rdflib`, `oxrdflib`, or `owlready2`. Phase 02 ships an automated check (likely a test or import-time gate) — planner should verify it covers `subtypes.py` after Phase 3's expansion.

4. **`model_rebuild` not needed:** `subtypes.py` does NOT use forward-string-refs (envelope.py:187 does for `ContentEdit`). Phase 3's nested models (`Objection`, `Reply`, `AuthorityPosition`) are declared inline above their parent subtype, so no `model_rebuild()` call is required at module bottom.

5. **`__init__.py` `__all__` ordering:** Existing repo convention is **alphabetical** (visible in current `__init__.py:19–32`). Maintain this when adding the 6 new exports.

## Metadata

**Analog search scope:** `src/folio_insights/shards/`, `src/folio_insights/polysemy/`, `tests/shards/`
**Files scanned:** 9 (envelope.py, subtypes.py, __init__.py, minting.py, distinguo.py, test_envelope_roundtrip.py, test_minting_determinism.py, test_discriminated_union.py, conftest.py)
**Pattern extraction date:** 2026-04-25
