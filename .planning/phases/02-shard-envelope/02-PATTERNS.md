# Phase 02: Shard Envelope (§6.1) — Pattern Map

**Mapped:** 2026-04-24
**Files analyzed:** 10 new (5 impl + 5 test/init)
**Analogs found:** 10 / 10

## File Classification

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `src/folio_insights/shards/__init__.py` | package-init | re-export (public surface) | `src/folio_insights/polysemy/__init__.py` | exact |
| `src/folio_insights/shards/envelope.py` | model (impl) | in-memory pydantic | `src/folio_insights/polysemy/dispositions.py` + `polysemy/detector.py` | exact |
| `src/folio_insights/shards/subtypes.py` | model (impl) | discriminated-union (in-memory) | `src/folio_insights/polysemy/detector.py` (Literal tags on `RuleVerdict` / `LLMVerdict`) | exact |
| `src/folio_insights/shards/minting.py` | utility | pure-function / deterministic hash | `src/folio_insights/polysemy/reviewer.py` (`_did_key_from_pub`) + `polysemy/distinguo.py` (`_escape_turtle_literal`) | role-match |
| `src/folio_insights/shards/audit.py` | model + helper | mutate-with-audit (in-memory) | `src/folio_insights/polysemy/distinguo.py` (`ForkProposal` frozen + `@model_validator` + standalone `validate_*_shape`) | exact |
| `tests/shards/__init__.py` | test package-init | n/a | `tests/polysemy/__init__.py` (empty) | exact |
| `tests/shards/test_envelope_roundtrip.py` | test | pydantic round-trip + frozen-field guard | `tests/polysemy/test_dispositions_jsonl.py` (`test_jsonl_schema_matches_phase15_contract`) | exact |
| `tests/shards/test_discriminated_union.py` | test | pydantic Union / ValidationError | `tests/polysemy/test_distinguo_emission.py` (`test_distinctionKind_enum`) | exact |
| `tests/shards/test_minting_determinism.py` | test | property test (deterministic hash) | `tests/polysemy/test_fp_rate.py` (parameterized fixture builders) — **no hypothesis precedent in repo** | role-match (patterns-only) |
| `tests/shards/test_audit_log.py` | test | mutate-with-audit + frozen sub-model | `tests/polysemy/test_distinguo_emission.py` (`test_emit_refuses_invalid_shape_defense_in_depth`) | exact |

**Notes on discretionary layout (D-11 / "Claude's Discretion"):**
- Module location resolved to `src/folio_insights/shards/` (mirrors `polysemy/` package-per-subsystem convention — not flat `core/shards.py`).
- `mint_shard_iri` is a **standalone module-level function** in `shards/minting.py` (mirrors `ensure_reviewer_did` in `reviewer.py` and `append_disposition`/`read_dispositions` in `dispositions.py` — no classmethods elsewhere in polysemy).
- `shard_type` pinning uses a **per-subclass `Literal[...]` default** (matches `RuleVerdict.kind: Literal["rule"] = "rule"` in `detector.py` — no `@model_validator` needed for the tag itself).
- `@model_validator(mode="after")` is reserved for cross-field invariants (e.g., any Phase 2 guard like "if `supersedes` is set, it must differ from `shard_iri`"). For Phase 2 scope, a validator may not be strictly needed — but the pattern is locked in `distinguo.ForkProposal` for Phase 5 `ContentEdit` hardening.

---

## Pattern Assignments

### `src/folio_insights/shards/envelope.py` (model, in-memory pydantic)

**Primary analog:** `src/folio_insights/polysemy/dispositions.py`
**Secondary analog (Literal tags):** `src/folio_insights/polysemy/detector.py`

**Module header + imports pattern** (dispositions.py lines 1-15):
```python
"""Phase 1 DispositionRecord + ProposedFork — canonical schema locks Phase 15 consumer contract.

Revision 1 note: detector_verdict is a dict snapshot (full RuleVerdict/LLMVerdict
model_dump) — NOT a float (Pitfall A6 guard). The CLI (01-05) populates it via
verdict.model_dump(); the FP audit (01-06) reads it back via read_dispositions().
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel
```

Use verbatim for `envelope.py`: module docstring explains "Phase 2 ShardEnvelope — 15-field v2.0 core data model; round-trip contract for every downstream phase", and the `from __future__ import annotations` top-line is mandatory (D-10).

**Literal tag pattern** (detector.py lines 41-50):
```python
class RuleVerdict(BaseModel):
    """Returned when rules alone decide (short-circuit paths R1 / R2 / R3,
    or all-rules-pass → tentative polysemy)."""

    kind: Literal["rule"] = "rule"
    decision: Literal["polysemy", "homonymy", "coincidence", "uncertain"]
    rule_confidence: float = Field(ge=0.0, le=1.0)
    matched_rules: list[str]
    evidence_score: float = Field(ge=0.0, le=2.0)
```

**Apply to `ShardEnvelope`:** Declare the `ShardType` alias as a module-level `Literal[...]`:
```python
ShardType = Literal[
    "simple_assertion",
    "disputed_proposition",
    "conflicting_authorities",
    "gloss",
    "hypothesis",
]
```
Then `ShardEnvelope.shard_type: ShardType` — no default on the base class (each subtype in `subtypes.py` pins its own literal default).

**Per-field `frozen=True` pattern** (D-07; no direct analog — distinguo uses model-level `ConfigDict(frozen=True)`):

Per-field `frozen` is a Pydantic v2.6+ feature. Closest in-repo frozen precedent is `distinguo.py` line 58:
```python
model_config = ConfigDict(frozen=True, extra="forbid")
```
— but that freezes the **whole model**. Phase 2 uses per-field `Field(frozen=True)` on exactly 6 identity fields (D-07), leaving mutable fields assignable. Pydantic raises `pydantic_core._pydantic_core.ValidationError` (NOT `FrozenFieldError` — that's a Pydantic v1 name; v2 raises `ValidationError` with `type="frozen_field"`). Match with: `pytest.raises(ValidationError, match="frozen")`.

Template (to write fresh in `envelope.py`):
```python
class ShardEnvelope(BaseModel):
    """15-field v2.0 Shard envelope (PRD §6.1).

    Identity-and-origin fields (6) are frozen per-field; mutable fields
    allow in-place assignment but every change must append a ContentEdit
    to content_edits (D-07/D-08).
    """

    model_config = ConfigDict(extra="forbid")  # schema drift = loud failure

    # ── IMMUTABLE identity + origin (D-07) ──
    shard_iri: str = Field(frozen=True)
    provenance_hash: str = Field(frozen=True)
    source_uri: str = Field(frozen=True)
    source_span: str = Field(frozen=True)
    extracted_at: datetime = Field(frozen=True)
    first_extractor_did: str = Field(frozen=True)

    # ── discriminator ──
    shard_type: ShardType  # pinned by subtype Literal default in subtypes.py

    # ── bitemporal (D-03/D-04) ──
    valid_time_start: datetime | None = None
    valid_time_end: datetime | None = None
    transaction_time: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )

    # ── mutable-with-audit content (D-08) ──
    # (sense, reference, elaborates, layer, framework_id, supersedes,
    #  content_edits, signatures — per PRD §6.1)
    content_edits: list[ContentEdit] = Field(default_factory=list)
    # ...remaining fields land in Phase 2; subtype-specific content in Phase 3.
```

**Mutable-default pattern** (dispositions.py line 31):
```python
frameworks: list[str] = []
```
Phase 2 standardizes on `Field(default_factory=list)` instead (D-11) — avoids the shared-mutable-default footgun when model instances are reused in tests. Precedent in `knowledge_unit.py` line 60-65:
```python
source_section: list[str] = Field(default_factory=list)
folio_tags: list[ConceptTag] = Field(default_factory=list)
```

**`ConfigDict` precedent** (distinguo.py line 58):
```python
model_config = ConfigDict(frozen=True, extra="forbid")
```
Phase 2 keeps `extra="forbid"` (schema drift = loud failure) but drops the model-level `frozen=True` in favor of per-field `Field(frozen=True)` (D-07).

---

### `src/folio_insights/shards/subtypes.py` (model, discriminated-union)

**Primary analog:** `src/folio_insights/polysemy/detector.py` (`RuleVerdict` + `LLMVerdict` sibling Literal-tagged pydantic models)

**Sibling-class Literal-tag pattern** (detector.py lines 41-70):
```python
class RuleVerdict(BaseModel):
    kind: Literal["rule"] = "rule"
    decision: Literal["polysemy", "homonymy", "coincidence", "uncertain"]
    rule_confidence: float = Field(ge=0.0, le=1.0)
    matched_rules: list[str]
    evidence_score: float = Field(ge=0.0, le=2.0)


class LLMVerdict(BaseModel):
    kind: Literal["llm"] = "llm"
    decision: Literal["polysemy", "homonymy", "coincidence", "uncertain"]
    ...
```

**Apply to each of 5 subtypes in `subtypes.py`:**
```python
class SimpleAssertionShard(ShardEnvelope):
    shard_type: Literal["simple_assertion"] = "simple_assertion"
    # Phase 3 adds subtype-specific fields

class DisputedPropositionShard(ShardEnvelope):
    shard_type: Literal["disputed_proposition"] = "disputed_proposition"

class ConflictingAuthoritiesShard(ShardEnvelope):
    shard_type: Literal["conflicting_authorities"] = "conflicting_authorities"

class GlossShard(ShardEnvelope):
    shard_type: Literal["gloss"] = "gloss"

class HypothesisShard(ShardEnvelope):
    shard_type: Literal["hypothesis"] = "hypothesis"
```

**Discriminated-union pattern** (no in-repo analog — first use; spec from CONTEXT D-05):
```python
from typing import Annotated, Union
from pydantic import Field

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
Pydantic raises `ValidationError` on parse with an unknown `shard_type` tag; test in `test_discriminated_union.py`.

---

### `src/folio_insights/shards/minting.py` (utility, deterministic hash)

**Primary analog:** `src/folio_insights/polysemy/reviewer.py` (`_did_key_from_pub` — deterministic byte-composition → encoded string)
**Secondary analog (escape/normalize helpers):** `src/folio_insights/polysemy/distinguo.py` (`_escape_turtle_literal`)

**Module docstring + deterministic helper pattern** (reviewer.py lines 1-28):
```python
"""Phase 1 reviewer did:key generator — real ed25519 + JWK persistence (OQ-4 RESOLVED).

Generates a W3C did:key (Ed25519 + multibase z-base58btc) on first CLI use.
...
Multicodec prefix for ed25519-pub is 0xed 0x01 (per did:key method spec);
full multibase string is "did:key:z" + base58btc(\\xed\\x01 || raw_public_key).
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

# multicodec varint prefix for ed25519-pub (code 0xed, 1-byte varint encoding)
_ED25519_MULTICODEC_PREFIX = b"\xed\x01"
```

**Apply to `minting.py`:** Module docstring explains the provenance-hash recipe verbatim from CONTEXT D-02 (NFC, LF, trim, RFC 3986). Constants at module top:
```python
_IRI_PREFIX = "urn:folio:shard/"
_IRI_HEX_LEN = 16  # first 16 of sha256's 64 hex chars
```

**Pure normalize-and-hash pattern** (no direct analog — compose from `_escape_turtle_literal` string-pipeline + `_did_key_from_pub` byte-composition):

Template (to write fresh):
```python
import hashlib
import unicodedata
from urllib.parse import urlsplit, urlunsplit, quote


def _normalize_uri(uri: str) -> str:
    """RFC 3986: lowercase scheme+host, percent-encode path, strip trailing slash.
    Fragment preserved (per CONTEXT D-02)."""
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = quote(parts.path, safe="/%:@")
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, parts.fragment))


def _normalize_span(span: str) -> str:
    """NFC + trim. LF-only line endings enforced by caller contract."""
    return unicodedata.normalize("NFC", span).strip()


def mint_shard_iri(source_uri: str, source_span: str) -> tuple[str, str]:
    """Deterministic provenance-hash → shard IRI (CONTEXT D-01/D-02).

    Returns (iri, provenance_hash) where:
      hash = sha256(NFC(rfc3986(uri)) + "\\n" + NFC(span).strip()).hexdigest()
      iri  = f"urn:folio:shard/{hash[:16]}"
    """
    uri_n = unicodedata.normalize("NFC", _normalize_uri(source_uri))
    span_n = _normalize_span(source_span)
    payload = (uri_n + "\n" + span_n).encode("utf-8")
    hash_hex = hashlib.sha256(payload).hexdigest()
    iri = f"{_IRI_PREFIX}{hash_hex[:_IRI_HEX_LEN]}"
    return iri, hash_hex
```

**Private-helper-convention pattern** (distinguo.py lines 130-146):
```python
def _escape_turtle_literal(s: str) -> str:
    """Minimal Turtle literal escape: backslash, double-quote, newline, carriage-return.
    ...
    """
    return (
        s.replace("\\", "\\\\")
         .replace('"', '\\"')
         .replace("\r", "\\r")
         .replace("\n", "\\n")
    )
```
Leading underscore for private helpers (`_normalize_uri`, `_normalize_span`); public functions (`mint_shard_iri`) get no underscore.

---

### `src/folio_insights/shards/audit.py` (model + helper, mutate-with-audit)

**Primary analog:** `src/folio_insights/polysemy/distinguo.py` (`ForkProposal` frozen-pydantic + `@model_validator` + standalone `validate_*_shape`)

**Frozen sub-model pattern** (distinguo.py lines 45-58):
```python
class ForkProposal(BaseModel):
    """Emission-layer fork — superset of ProposedFork with provenance fields.
    ...
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    term: str
    cluster_id: str                           # hex8, minted by 01-03 prototype_cluster
    uses_analogousTo: bool
```

**Apply to `ContentEdit`** (D-08 — audit records themselves are immutable):
```python
class ContentEdit(BaseModel):
    """One audit entry in a Shard's content_edits chain (D-08).

    Audit records themselves are frozen — the chain is append-only.
    Phase 5 wires the forward-only SHACL gate; Phase 2 ships the record
    shape and a minimal add_edit() helper.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_name: str
    old_value: Any
    new_value: Any
    edited_at: datetime
    editor_did: str
```

**`@model_validator` defense-in-depth pattern** (distinguo.py lines 70-84):
```python
@model_validator(mode="after")
def _analogia_atomic_triad(self) -> "ForkProposal":
    """Pitfall 5: analogia is atomic — no sub-property may be omitted."""
    if self.uses_analogousTo:
        if not self.prime_analogate:
            raise ValueError(
                "uses_analogousTo=True requires prime_analogate "
                "(Pitfall 5: analogia is atomic — no sub-property may be omitted)"
            )
        if not self.proportional_relation:
            raise ValueError(
                "uses_analogousTo=True requires proportional_relation "
                "(Pitfall 5: analogia is atomic — no sub-property may be omitted)"
            )
    return self
```

**Phase 2 usage:** ContentEdit Phase 2 has no cross-field invariants (all fields independent). The `@model_validator` pattern is deferred to Phase 5 (when `ContentEdit.edited_at` must be compared against the shard's own `transaction_time` for forward-only semantics). Phase 2 stub: no validator.

**Standalone validator pattern** (distinguo.py lines 99-127):
```python
def validate_fork_proposal_shape(fork: ForkProposal) -> None:
    """Defense-in-depth check.

    Model construction already guarantees the invariant, but call-sites
    that load forks via ``ForkProposal.model_construct(...)`` bypass the
    validator. Re-run the check explicitly before emit so no invalid fork
    is ever serialized to TTL.
    """
    ...
```
**Phase 2 apply:** Not strictly required for Phase 2 ContentEdit (no invariant to guard yet). Phase 5 will add `validate_content_edit_shape()` mirroring this idiom.

**Minimal `add_edit()` helper** (CONTEXT D-08 — Phase 2 minimal; Phase 5 hardens):
```python
def add_edit(
    shard: ShardEnvelope,
    field_name: str,
    new_value: Any,
    editor_did: str,
) -> None:
    """Append a ContentEdit audit record. Phase 2 minimal — Phase 5 adds
    forward-only + SHACL-gated variant."""
    old_value = getattr(shard, field_name)
    shard.content_edits.append(ContentEdit(
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        edited_at=datetime.now(UTC),
        editor_did=editor_did,
    ))
    # Phase 2 assigns via setattr IF the field is not frozen; frozen fields
    # raise ValidationError (Pydantic v2 per-field frozen).
    setattr(shard, field_name, new_value)
```
(Assignment attempt on a frozen field raises `pydantic.ValidationError` with `type="frozen_field"` — test in `test_envelope_roundtrip.py` and `test_audit_log.py`.)

---

### `src/folio_insights/shards/__init__.py` (package-init)

**Primary analog:** `src/folio_insights/polysemy/__init__.py`

**Re-export pattern** (polysemy/__init__.py lines 1-30):
```python
"""Phase 1 polysemy-distinguo spike (PRINCIPLE-06 scoping + VOCAB-02 first-use)."""
from folio_insights.polysemy.cli import polysemy as polysemy_cli_group
from folio_insights.polysemy.dispositions import (
    DispositionRecord,
    ProposedFork,
    append_disposition,
    read_dispositions,
)
from folio_insights.polysemy.reviewer import ensure_reviewer_did

__all__ = [
    "DispositionRecord",
    "ProposedFork",
    "append_disposition",
    "read_dispositions",
    "ensure_reviewer_did",
    ...
]
```

**Apply to `shards/__init__.py`:**
```python
"""Phase 2 v2.0 Shard envelope (§6.1) — 15-field Pydantic core data model."""
from folio_insights.shards.audit import ContentEdit, add_edit
from folio_insights.shards.envelope import ShardEnvelope, ShardType
from folio_insights.shards.minting import mint_shard_iri
from folio_insights.shards.subtypes import (
    ConflictingAuthoritiesShard,
    DisputedPropositionShard,
    GlossShard,
    HypothesisShard,
    Shard,
    SimpleAssertionShard,
)

__all__ = [
    "ShardEnvelope",
    "ShardType",
    "Shard",
    "SimpleAssertionShard",
    "DisputedPropositionShard",
    "ConflictingAuthoritiesShard",
    "GlossShard",
    "HypothesisShard",
    "ContentEdit",
    "add_edit",
    "mint_shard_iri",
]
```

---

### `tests/shards/test_envelope_roundtrip.py`

**Primary analog:** `tests/polysemy/test_dispositions_jsonl.py`

**Round-trip assertion pattern** (test_dispositions_jsonl.py lines 48-77):
```python
def test_jsonl_schema_matches_phase15_contract() -> None:
    rec = _sample_record()
    payload = rec.model_dump_json()
    parsed = json.loads(payload)
    assert parsed["schema_version"] == "1"
    assert set(parsed.keys()) >= {
        "schema_version",
        "cluster_id",
        ...
    }
    assert "detector_confidence" not in parsed
    assert isinstance(parsed["detector_verdict"], dict)
    # Literal enforcement:
    with pytest.raises(Exception):
        DispositionRecord.model_validate_json(
            payload.replace('"accept"', '"maybe"')
        )
```

**Apply to Phase 2 envelope round-trip:**
```python
def test_shard_round_trip_model_dump() -> None:
    """Shard(**shard.model_dump()) == shard for every subtype stub."""
    for cls, tag in [
        (SimpleAssertionShard, "simple_assertion"),
        (DisputedPropositionShard, "disputed_proposition"),
        (ConflictingAuthoritiesShard, "conflicting_authorities"),
        (GlossShard, "gloss"),
        (HypothesisShard, "hypothesis"),
    ]:
        original = _sample_shard(cls)
        dumped = original.model_dump()
        assert dumped["shard_type"] == tag
        reconstructed = cls(**dumped)
        assert reconstructed == original

def test_bitemporal_null_unbounded_round_trip() -> None:
    """valid_time_start=None, valid_time_end=None round-trips as null
    (D-03 — unbounded semantics)."""
    shard = _sample_shard(SimpleAssertionShard, valid_time_start=None, valid_time_end=None)
    parsed = json.loads(shard.model_dump_json())
    assert parsed["valid_time_start"] is None
    assert parsed["valid_time_end"] is None

def test_transaction_time_is_tz_aware_utc() -> None:
    """D-04 — datetime.now(UTC) default is tz-aware."""
    shard = _sample_shard(SimpleAssertionShard)
    assert shard.transaction_time.tzinfo is not None
    assert shard.transaction_time.utcoffset().total_seconds() == 0
```

**Frozen-field-assignment raises pattern** (no direct precedent — Pydantic v2 `ValidationError` with `type="frozen_field"`):
```python
def test_shard_iri_is_frozen() -> None:
    """D-07 — the 6 identity fields raise on assignment."""
    shard = _sample_shard(SimpleAssertionShard)
    with pytest.raises(ValidationError, match="frozen"):
        shard.shard_iri = "urn:folio:shard/deadbeef00000000"

def test_provenance_hash_is_frozen() -> None:
    shard = _sample_shard(SimpleAssertionShard)
    with pytest.raises(ValidationError, match="frozen"):
        shard.provenance_hash = "0" * 64
# ...same for source_uri, source_span, extracted_at, first_extractor_did
```

**Fixture-builder pattern** (test_dispositions_jsonl.py lines 17-45 — builder with optional overrides):
```python
def _sample_record(decision: str = "accept") -> DispositionRecord:
    return DispositionRecord(
        cluster_id="fi:PrototypeCluster_a3f81c4e",
        term="consideration",
        ...
    )
```
**Apply:** `_sample_shard(cls: type[ShardEnvelope], **overrides) -> ShardEnvelope` — one builder, all 5 subtypes, override mechanism identical to test_fp_rate.py `_sample_record`.

---

### `tests/shards/test_discriminated_union.py`

**Primary analog:** `tests/polysemy/test_distinguo_emission.py` (`test_distinctionKind_enum`)

**ValidationError on invalid Literal tag pattern** (test_distinguo_emission.py lines 98-113):
```python
def test_distinctionKind_enum() -> None:
    """A 5th distinction_kind value (not in the Literal) raises ValidationError
    at construction time — VOCAB-02 4-enum lock."""
    with pytest.raises(ValidationError) as exc_info:
        ForkProposal(
            term=TERM,
            cluster_id=CLUSTER_ID,
            uses_analogousTo=True,
            prime_analogate=PRIME_IRI,
            proportional_relation=PROP_RELATION,
            distinction_kind="analogy",  # 5th value — not in Literal
            source_frameworks=FRAMEWORKS,
            reviewer_did=REVIEWER_DID,
            created_at_iso=CREATED_AT,
        )
    assert "distinction_kind" in str(exc_info.value)
```

**Apply to Phase 2 discriminated-union tests:**
```python
from pydantic import TypeAdapter, ValidationError
from folio_insights.shards import Shard

_ADAPTER = TypeAdapter(Shard)

def test_invalid_shard_type_raises_validation_error() -> None:
    """D-05 — an unknown shard_type tag fails validation with a useful message."""
    payload = _sample_shard_dict() | {"shard_type": "nonsense"}
    with pytest.raises(ValidationError) as exc_info:
        _ADAPTER.validate_python(payload)
    assert "shard_type" in str(exc_info.value)
    assert "nonsense" in str(exc_info.value) or "discriminator" in str(exc_info.value).lower()

def test_each_subtype_parses_its_own_tag() -> None:
    """Each of 5 subtypes dispatches on its own Literal default."""
    for tag, cls in [
        ("simple_assertion", SimpleAssertionShard),
        ("disputed_proposition", DisputedPropositionShard),
        ("conflicting_authorities", ConflictingAuthoritiesShard),
        ("gloss", GlossShard),
        ("hypothesis", HypothesisShard),
    ]:
        payload = _sample_shard_dict() | {"shard_type": tag}
        parsed = _ADAPTER.validate_python(payload)
        assert isinstance(parsed, cls)
        assert parsed.shard_type == tag
```

---

### `tests/shards/test_minting_determinism.py`

**Primary analog:** `tests/polysemy/test_fp_rate.py` (parameterized fixture builders — no `hypothesis` precedent yet)

**Repo-wide `hypothesis` precedent:** `grep -rn "from hypothesis"` returns 0 hits across `src/` and `tests/`. Phase 2 is the **first** user of `hypothesis` in this repo. Planner must:

1. Add `hypothesis>=6.100` to `[project.optional-dependencies].dev` in `pyproject.toml`.
2. Import + decorate pattern (standard hypothesis idiom — no in-repo template to copy):
```python
from hypothesis import given, settings
from hypothesis import strategies as st

@settings(max_examples=1000, deadline=None)
@given(
    scheme=st.sampled_from(["http", "https", "urn"]),
    host=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-.", min_size=3, max_size=20),
    path=st.text(min_size=0, max_size=50),
    span=st.text(min_size=0, max_size=200),
)
def test_mint_is_deterministic(scheme: str, host: str, path: str, span: str) -> None:
    """Same (uri, span) → same IRI across 1000 random examples (CONTEXT D-02)."""
    uri = f"{scheme}://{host}/{path}"
    iri_a, hash_a = mint_shard_iri(uri, span)
    iri_b, hash_b = mint_shard_iri(uri, span)
    assert iri_a == iri_b
    assert hash_a == hash_b
    assert iri_a.startswith("urn:folio:shard/")
    assert len(iri_a) == len("urn:folio:shard/") + 16
```

**NFC + LF + trim + RFC 3986 variation tests** (no hypothesis — direct string-variation table; precedent pattern is the `replace(...)` chain in `_escape_turtle_literal`):
```python
def test_nfc_normalization_applied() -> None:
    """NFD 'é' (e + combining acute) yields same IRI as NFC 'é'."""
    nfd_span = "café"          # NFC é
    nfc_span = "café"          # NFD e + combining acute
    iri_a, _ = mint_shard_iri("urn:x:1", nfd_span)
    iri_b, _ = mint_shard_iri("urn:x:1", nfc_span)
    assert iri_a == iri_b

def test_crlf_normalized_to_lf_via_span_trim() -> None:
    """Trailing CRLF in span is stripped; LF-only internal separator."""
    # Implementation note: the recipe uses "\n" LF between uri and span.
    # Span itself is passed through strip() which removes trailing \r\n.
    iri_a, _ = mint_shard_iri("urn:x:1", "body text\r\n")
    iri_b, _ = mint_shard_iri("urn:x:1", "body text")
    assert iri_a == iri_b

def test_trailing_slash_and_case_normalized() -> None:
    """RFC 3986 — scheme + host lowercase; trailing slash stripped."""
    iri_a, _ = mint_shard_iri("HTTPS://Example.COM/doc/", "span")
    iri_b, _ = mint_shard_iri("https://example.com/doc", "span")
    assert iri_a == iri_b
```

---

### `tests/shards/test_audit_log.py`

**Primary analog:** `tests/polysemy/test_distinguo_emission.py` (`test_emit_refuses_invalid_shape_defense_in_depth` — model_construct bypass + frozen model)

**Frozen-model-construct assertion pattern** (test_distinguo_emission.py lines 279-297):
```python
def test_emit_refuses_invalid_shape_defense_in_depth() -> None:
    """A fork built via model_construct() (bypasses the pydantic validator)
    with uses_analogousTo=True + prime_analogate=None MUST be rejected by
    emit_fork_ttl's preflight validate_fork_proposal_shape call."""
    bypassed = ForkProposal.model_construct(
        term=TERM,
        cluster_id=CLUSTER_ID,
        uses_analogousTo=True,
        prime_analogate=None,  # would have raised via pydantic; bypassed here
        proportional_relation=PROP_RELATION,
        ...
    )
    with pytest.raises(ValueError) as exc_info:
        emit_fork_ttl(bypassed)
    assert "prime_analogate" in str(exc_info.value)
```

**Apply to Phase 2 audit-log tests:**
```python
def test_add_edit_appends_content_edit(monkeypatch) -> None:
    """add_edit() appends a ContentEdit with correct field_name/old/new/edited_at/editor_did."""
    shard = _sample_shard(SimpleAssertionShard, content_edits=[])
    assert shard.content_edits == []

    # Freeze time so edited_at is predictable.
    fixed_now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "folio_insights.shards.audit.datetime",
        _FixedDatetime(fixed_now),
    )

    add_edit(shard, field_name="sense", new_value="new sense", editor_did="did:key:zTest")

    assert len(shard.content_edits) == 1
    edit = shard.content_edits[0]
    assert edit.field_name == "sense"
    assert edit.new_value == "new sense"
    assert edit.edited_at == fixed_now
    assert edit.editor_did == "did:key:zTest"

def test_content_edit_itself_is_frozen() -> None:
    """ContentEdit.model_config frozen=True — assignment raises."""
    edit = ContentEdit(
        field_name="sense",
        old_value="old",
        new_value="new",
        edited_at=datetime.now(UTC),
        editor_did="did:key:zTest",
    )
    with pytest.raises(ValidationError, match="frozen"):
        edit.field_name = "elaborates"

def test_add_edit_on_frozen_field_raises() -> None:
    """add_edit() on an identity field (e.g. shard_iri, D-07) raises
    ValidationError — mutable-with-audit applies to non-identity fields only."""
    shard = _sample_shard(SimpleAssertionShard)
    with pytest.raises(ValidationError, match="frozen"):
        add_edit(shard, field_name="shard_iri", new_value="urn:folio:shard/xxx", editor_did="did:key:zTest")
```

---

## Shared Patterns

### Module-top Imports and Forward-Refs
**Source:** every file in `src/folio_insights/polysemy/` (dispositions.py L7, distinguo.py L24, reviewer.py L10, fp_audit.py L22)
**Apply to:** all Phase 2 `src/folio_insights/shards/*.py` files
```python
from __future__ import annotations
```
**Rationale (D-10):** Pydantic 2.x + forward-refs; required for `Union[...]` discriminated union when subtype classes reference each other.

---

### `ConfigDict(extra="forbid")`
**Source:** `src/folio_insights/polysemy/distinguo.py` line 58
```python
model_config = ConfigDict(frozen=True, extra="forbid")
```
**Apply to:** `ShardEnvelope` (without `frozen=True` — Phase 2 uses per-field freeze per D-07) and `ContentEdit` (with `frozen=True` — audit records are immutable per D-08).
**Rationale:** Schema drift at Phase 3/5/7 consumer boundaries raises pydantic `ValidationError` rather than silently accepting unknown fields. Matches Phase 1 discipline.

---

### `Field(default_factory=list)` for mutable list defaults
**Source:** `src/folio_insights/models/knowledge_unit.py` lines 60-65
```python
source_section: list[str] = Field(default_factory=list)
folio_tags: list[ConceptTag] = Field(default_factory=list)
lineage: list[StageEvent] = Field(default_factory=list)
cross_references: list[str] = Field(default_factory=list)
```
**Apply to:** `ShardEnvelope.content_edits: list[ContentEdit] = Field(default_factory=list)` (D-08) and `ShardEnvelope.signatures: list[AttestedSignature] = Field(default_factory=list)` (deferred stub).
**Rationale (D-11):** Prefer `default_factory=list` over `= []` to avoid the shared-mutable-default footgun. Baseline `knowledge_unit.py` sets the precedent.

---

### tz-aware UTC datetime via `Field(default_factory=...)`
**Source:** `src/folio_insights/models/knowledge_unit.py` lines 47-49
```python
timestamp: str = Field(
    default_factory=lambda: datetime.now(timezone.utc).isoformat()
)
```
**Apply to:** `ShardEnvelope.transaction_time: datetime = Field(default_factory=lambda: datetime.now(UTC))` (D-04).
**Rationale (D-04, D-12):** All datetime fields tz-aware UTC. Phase 2 stores `datetime` objects (not ISO strings — Pydantic's default ISO-8601 serializer handles round-trip per D-12); `knowledge_unit.py` legacy style stored strings — Phase 2 modernizes to `datetime` objects.

**Import note:** Python 3.11+ (`requires-python = ">=3.11,<3.13"` in pyproject.toml) supports `from datetime import UTC` directly — use `UTC` over `timezone.utc`.

---

### `pytestmark` module-scoped marker
**Source:** `tests/polysemy/test_fp_rate.py` line 22, `test_distinguo_emission.py` line 27, `test_cli_review.py` line 31
```python
pytestmark = pytest.mark.polysemy_spike
```
**Apply to:** Phase 2 tests should use a new marker `pytest.mark.shards` — add to `[tool.pytest.ini_options].markers` in `pyproject.toml`:
```toml
markers = [
    ...
    "shards: Phase 2 v2.0 Shard envelope tests",
]
```
Then each test module declares:
```python
pytestmark = pytest.mark.shards
```
**Rationale:** Phase 1 isolated its tests behind `polysemy_spike` so CI could run subset gates. Phase 2 follows the pattern so Phase 2 regressions can be gated independently of Phase 1+3+ suites.

---

### Grep-guard regression tests (Phase 2 candidate, optional)
**Source:** `tests/polysemy/test_fp_rate.py` lines 104-111 (`test_wilson_score_interval_no_scipy_import`) and lines 333-343 (`test_no_detector_confidence_float_regression`), lines 345-360 (`test_no_stale_reason_attribute_regression`)
```python
def test_wilson_score_interval_no_scipy_import() -> None:
    """QUALITY-03 image-size discipline: NO scipy in fp_audit.py."""
    from folio_insights.polysemy import fp_audit
    source = pathlib.Path(fp_audit.__file__).read_text(encoding="utf-8")
    assert "import scipy" not in source
    assert "from scipy" not in source
```
**Apply to Phase 2 (suggested):**
```python
def test_no_pyoxigraph_import_in_phase2_shards() -> None:
    """Phase 2 must not leak Phase 13 storage dependency (CONTEXT Integration
    Points: 'Phase 2 does NOT write through pyoxigraph yet')."""
    from folio_insights import shards
    for module_file in pathlib.Path(shards.__file__).parent.glob("*.py"):
        source = module_file.read_text(encoding="utf-8")
        assert "import pyoxigraph" not in source, (
            f"{module_file.name}: Phase 2 must not import pyoxigraph (Phase 13 scope)"
        )
        assert "from pyoxigraph" not in source, (
            f"{module_file.name}: Phase 2 must not import pyoxigraph (Phase 13 scope)"
        )

def test_no_rdflib_import_in_phase2_shards() -> None:
    """Phase 2 must not leak RDF mapping concerns (deferred to Phase 11/13)."""
    # same pattern as above
```
**Rationale:** CONTEXT explicitly states "no Phase-13 dep leak into Phase 2" and "RDF `json_schema_extra` hints deferred to Phase 11 (SHACL) / Phase 13 (storage)". A grep-guard regression test makes the boundary mechanical.

---

### Test fixture-builder with override-kwargs
**Source:** `tests/polysemy/test_fp_rate.py` lines 38-68 (`_sample_record(*, cluster_id=..., term=..., decision=..., ...)`)
```python
def _sample_record(
    *,
    cluster_id: str = "fi:PrototypeCluster_deadbeef",
    term: str = "consideration",
    decision: str = "accept",
    rationale: str = "ok",
    detector_decision: str = "polysemy",
) -> DispositionRecord:
    return DispositionRecord(
        cluster_id=cluster_id,
        term=term,
        proposed_fork=ProposedFork(...),
        decision=decision,
        rationale=rationale,
        reviewer_did="did:key:z6Mkpz0000000000000000000000000000000000000000",
        reviewed_at_iso="2026-04-23T12:00:00+00:00",
        detector_verdict={...},
    )
```
**Apply to Phase 2 test helpers:** Provide `_sample_shard(cls: type[ShardEnvelope] = SimpleAssertionShard, **overrides) -> ShardEnvelope` in a shared `tests/shards/conftest.py` or at each test-file top. Keyword-only + explicit defaults + kwargs-override is the idiomatic phase-1 pattern.

---

## No Analog Found

Files / patterns with no close match in the codebase (planner must synthesize fresh; research the library docs if needed):

| Concern | Role | Data Flow | Reason | Guidance |
|---------|------|-----------|--------|----------|
| Pydantic v2 per-field `Field(frozen=True)` | immutability | in-memory | No precedent — polysemy uses model-level `ConfigDict(frozen=True)` | Per-field is Pydantic ≥2.6; verify with `pydantic` version in `pyproject.toml` (`>=2.7.0` ✓) |
| `typing.Annotated[Union[...], Field(discriminator=...)]` | discriminated-union routing | in-memory | First use in repo | Synthesize from CONTEXT D-05; validate with `pydantic.TypeAdapter(Shard).validate_python(...)` in tests |
| `hypothesis` property testing | test | stochastic | Zero hypothesis imports in `src/` or `tests/` | Phase 2 is first adopter; planner adds `hypothesis>=6.100` to `[dev]` deps and sets `@settings(max_examples=1000, deadline=None)` per CONTEXT "1000 random runs" lock |
| `unicodedata.normalize("NFC", ...)` | string normalization | pure-function | No precedent in repo (distinguo's `_escape_turtle_literal` only escapes, doesn't normalize) | Standard-library pattern; test vector: NFC `"café"` vs NFD `"café"` produces the same IRI |
| `urllib.parse.urlsplit` / RFC 3986 normalization | URI normalization | pure-function | No precedent (distinguo uses literal `<{IRI}>` interpolation without normalization) | Standard-library; tests: lowercase scheme+host, strip trailing `/`, preserve fragment |

---

## Metadata

**Analog search scope:** `src/folio_insights/polysemy/*.py`, `src/folio_insights/models/*.py`, `tests/polysemy/*.py`, `src/folio_insights/bench/*.py`
**Files scanned:** 15 (`dispositions.py`, `distinguo.py`, `reviewer.py`, `detector.py`, `fp_audit.py`, `polysemy/__init__.py`, `polysemy/cli.py`, `knowledge_unit.py`, `pyproject.toml`, `tests/polysemy/test_fp_rate.py`, `test_cli_review.py`, `test_dispositions_jsonl.py`, `test_distinguo_emission.py`, `polysemy/conftest.py`, `polysemy/fixture_loader.py`)
**Pattern extraction date:** 2026-04-24

**Stopped early:** yes — 5 strong analog files (`dispositions.py`, `distinguo.py`, `reviewer.py`, `detector.py`, `knowledge_unit.py`) provided full coverage of model-declaration, Literal-tag, frozen, @model_validator, and default-factory patterns. No additional searches provided new information.
