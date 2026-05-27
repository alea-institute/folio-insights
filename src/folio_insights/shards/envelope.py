"""Phase 2 v2.0 Shard envelope (PRD §6.1) — 15-field Pydantic core data model.

Round-trip + frozen identity contract for every downstream phase (3-16). The
15 envelope fields + 6 identity-and-origin fields + bitemporal triplet +
supersession link pair + contest state are locked here; subtype-specific
fields land in Phase 3.

Key locked decisions carried into this module (see 02-CONTEXT.md):

* D-03: `valid_time_start` and `valid_time_end` are `datetime | None = None`.
  Null means unbounded (Phase 13 SPARQL `--as-of` treats `null_start` as −∞
  and `null_end` as +∞).
* D-04 / D-12: `transaction_time` uses `Field(default_factory=lambda:
  datetime.now(UTC))` — tz-aware UTC on every instance.
* D-05: `ShardType` Literal is the canonical discriminator alias; subtypes
  pin each Literal default in `subtypes.py`.
* D-07: The 6 identity-and-origin fields (`shard_iri`, `provenance_hash`,
  `source_uri`, `source_span`, `extracted_at`, `first_extractor_did`) use
  per-field freeze via ``Field(frozen=...)``. Pydantic 2.7+ raises
  ``ValidationError`` with ``type="frozen_field"`` on assignment. Mutable
  fields stay assignable.
* D-08: Mutable-with-audit fields append a `ContentEdit` to `content_edits`
  on every change (helper + model land in Plan 02-02; Phase 5 wires the
  forward-only SHACL gate).
* D-10: `from __future__ import annotations` at module top.
* D-11: `Field(default_factory=list)` on every mutable list default.

This module is pure-Pydantic + stdlib: no storage-layer libraries are
pulled in at Phase 2. RDF mapping + SHACL gates are Phase 11 / Phase 13
scope.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# D-05: canonical discriminator alias (5 values, ordered per CONTEXT D-05).
ShardType = Literal[
    "simple_assertion",
    "disputed_proposition",
    "conflicting_authorities",
    "gloss",
    "hypothesis",
]


class AttestedSignature(BaseModel):
    """Permissive Phase 6 STUB — full DID-substrate shape lands in Phase 6.

    Phase 2 ships an ``extra="allow"`` placeholder so ``ShardEnvelope.signatures``
    can be typed + default-factoried without pulling forward the Phase 6 DID
    substrate. The schema will be REPLACED (not extended) in Phase 6; the
    permissive config is intentional so round-trip tests can tolerate the
    richer Phase 6 shape slotting in. All fields carry defaults so empty-list
    signatures (`default_factory=list` on the envelope) construct without
    ceremony.
    """
    model_config = ConfigDict(extra="allow")  # Phase 6 will tighten to forbid

    did: str = ""
    action: str = ""
    signed_at: Optional[datetime] = None
    signature: str = ""
    over_content_hash: str = ""


class Triple(BaseModel):
    """Fregean function-argument triple (PRD §6.1 field 1).

    The v2.0 Shard envelope is built around the Fregean sense/reference pair
    (`sense`, `reference`) + the subject/predicate/object function-argument
    triple. `object_datatype` is optional so typed literals (xsd:dateTime,
    xsd:decimal) can be distinguished from plain IRIs at Phase 11 / Phase 13.
    """
    model_config = ConfigDict(extra="forbid")

    subject: str
    predicate: str
    object: str
    object_datatype: Optional[str] = None


class ShardEnvelope(BaseModel):
    """15-field v2.0 Shard envelope (PRD §6.1).

    The 6 identity-and-origin fields use per-field freeze via
    ``Field(frozen=...)`` (D-07); mutable fields allow in-place assignment
    but every change SHOULD append a ``ContentEdit`` (D-08 — audit record
    + helper land in Plan 02-02). Phase 2 ships the shape + round-trip;
    Phase 5 wires the forward-only SHACL gate over ``content_edits``;
    Phase 11 adds SHACL hybrid validation; Phase 13 serializes to RDF-12.
    """

    # Schema drift at Phase 3 / 5 / 7 consumer boundaries raises pydantic
    # ValidationError rather than silently accepting unknown fields.
    model_config = ConfigDict(extra="forbid")

    # ── IMMUTABLE identity + origin (D-07) — 6 per-field-immutable fields ──
    shard_iri: str = Field(frozen=True)
    provenance_hash: str = Field(frozen=True)
    source_uri: str = Field(frozen=True)
    source_span: str = Field(frozen=True)
    extracted_at: datetime = Field(frozen=True)
    first_extractor_did: str = Field(frozen=True)

    # ── Discriminator (D-05 / D-06 — pinned by each subtype's Literal default) ──
    shard_type: ShardType

    # ── 15 envelope fields (PRD §6.1) ──
    # 1. Fregean function-argument triple.
    triple: Triple
    # 2. Tractarian elaboration edges (list of shard IRIs this shard refines).
    elaborates: list[str] = Field(default_factory=list)
    # 3. Sense / reference pair.
    sense: str
    reference: str
    # 4. Logical form imputed by the extractor.
    #    `source_uri` + `source_span` are declared above (both frozen).
    logical_form_imputed: str
    # 5. Carnapian layer tag.
    layer: Literal[
        "L0_primitive",
        "L1_definitional",
        "L2_composed",
        "L3_jurisdictional",
    ]
    # 6. `shard_type` discriminator already declared above (fills PRD slot 6).
    # 7. Aristotelian predication mode.
    predication_mode: Literal["per_se", "per_accidens"]
    # 8. Hume-fork tag.
    fork: Literal[
        "analytic",
        "synthetic_a_posteriori",
        "synthetic_a_priori",
    ]
    # 9. Epistemic status (Aquinas + crowdsourced extensions).
    epistemic_status: Literal[
        "per_se_nota_quoad_se",
        "per_se_nota_quoad_nos",
        "demonstrable",
        "authority_only",
        "aporetic",
        "hypothesis",
        "contested",
        "superseded",
    ]
    # 10. Vienna Circle verification method.
    verification_method: Literal[
        "textual_citation",
        "definitional_derivation",
        "inferential_chain",
        "extractor_assertion",
        "reviewer_attested",
    ]
    # 11. Explicit dependencies (Spinoza + Quine).
    depends_on_axioms: list[str] = Field(default_factory=list)
    depends_on_definitions: list[str] = Field(default_factory=list)
    depends_on_precedents: list[str] = Field(default_factory=list)
    depends_on_shards: list[str] = Field(default_factory=list)
    # 12. Framework identifier (Carnap) — NOT year-versioned (PRD §6.1 L343-346).
    framework_id: str
    # 13. Speech-act / language-game context (Wittgenstein II).
    speech_act: Literal[
        "holding",
        "dictum",
        "statutory_text",
        "statutory_definition",
        "regulatory_text",
        "pleading_argument",
        "contract_term",
        "treatise_statement",
        "restatement_black_letter",
        "practitioner_advice",
        "administrative_interpretation",
    ]
    # 14. Provenance metadata — DID-anchored.
    extractor_version: str
    extraction_prompt_hash: str
    extractor_model: str
    signatures: list[AttestedSignature] = Field(default_factory=list)
    # ``content_edits`` points at ``ContentEdit``, which ships in Plan 02-02
    # (shards/audit.py). A forward string-ref is used here to avoid a circular
    # import at module load; Plan 02-02's audit.py calls
    # ``ShardEnvelope.model_rebuild()`` at its module bottom to wire the ref.
    content_edits: list["ContentEdit"] = Field(default_factory=list)  # noqa: F821
    confidence: float = Field(ge=0.0, le=1.0)
    # 15. BFO mini-classification.
    bfo_category: Literal[
        "continuant_independent",
        "continuant_dependent",
        "occurrent_process",
        "occurrent_event",
    ]

    # ── BITEMPORAL (SHARD-10, D-03, D-04, D-12) ──
    valid_time_start: datetime | None = None
    valid_time_end: datetime | None = None
    transaction_time: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )

    # ── SUPERSESSION (link pair — chain enforcement lands in Phase 5 / 7) ──
    supersedes: str | None = None
    superseded_by: str | None = None

    # ── CONTEST STATE (first-class per PRD §6.1 field 9 extension) ──
    contested: bool = False
    contest_votes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _content_edits_forward_only(self) -> "ShardEnvelope":
        """AUTHORITATIVE forward-only gate over ``content_edits`` (D-07.1, D-08b).

        The ``content_edits`` chain must be monotonic in ``edited_at``: no edit
        may be back-dated before its predecessor (a back-dated insert is an
        "edit to a past version"). Equal adjacent timestamps are ALLOWED — a tie
        is broken by append order (D-09), so only a *strictly* decreasing
        ``edited_at`` is a violation.

        This is the authoritative, always-on monotonicity gate (mirrors the
        ``shards/subtypes.py`` ``@model_validator(mode="after")`` idiom). The
        pyshacl forward-only shape (Plan 03, ``revision/``) is *defense-in-depth*
        over the same invariant — it cannot live here because ``shards/`` is kept
        RDF-free (``tests/shards/test_dep_leak_guard.py``).

        The OTHER half of D-08 — immutability of past entries (D-08a: no mutation
        or deletion of an existing ``ContentEdit``) — is NOT carried by this
        validator. A SHACL shape / Pydantic validator sees only a single snapshot
        and cannot detect a deletion (RESEARCH L115-124). That half is carried
        structurally by ``ContentEdit`` ``frozen=True`` (an entry can't be mutated
        in place) plus the Plan 02 ``IMMUTABLE_FIELD_PATHS`` gate listing
        ``content_edits`` as a whole (append-only — reorder/remove/replace
        forbidden).
        """
        edits = self.content_edits
        for prev, curr in zip(edits, edits[1:]):
            if curr.edited_at < prev.edited_at:
                raise ValueError(
                    "content_edits must be monotonic in edited_at "
                    "(no back-dated insert — forward-only, D-08b); "
                    f"got edit at {curr.edited_at!r} after {prev.edited_at!r}."
                )
        return self


__all__ = [
    "AttestedSignature",
    "ShardEnvelope",
    "ShardType",
    "Triple",
]
