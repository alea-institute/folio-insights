"""Phase 3 v2.0 Shard subtype field expansion (PRD §6.2) — discriminated-union variants.

Expands each of the 5 Phase 02 stubs with their PRD §6.2 subtype-specific fields,
3 nested Pydantic models (Objection, Reply, AuthorityPosition), and 3 module-level
Literal aliases (ReconciliationStrategy, GlossKind, GenerationMethod). Per-subtype
@model_validator(mode='after') invariants enforce the rules locked in 03-CONTEXT.md
D-02..D-06.

D-01: SimpleAssertionShard ships as a TRUE empty subtype (envelope-only).
D-02: DisputedPropositionShard adds utrum/objections/sed_contra/respondeo/replies/uses_distinctions.
D-03: DisputedPropositionShard validator narrows envelope.epistemic_status to
      {"hypothesis", "authority_only", "contested", "aporetic"} (4-subset of envelope's 8).
      NOTE: "authority_only" substitutes for the PRD's "attested" — the envelope ships no
      "attested" Literal value (planner-resolved 2026-04-25; see 03-CONTEXT.md D-03).
D-04: ConflictingAuthoritiesShard adds sic/non/reconciliation_strategy/reconciliation_note;
      8-value ReconciliationStrategy Literal lock (NO 9th "custom" escape hatch).
D-05: GlossShard adds glosses/gloss_kind/gloss_text; format-only IRI validator (Phase 5/13
      own referential integrity).
D-06: HypothesisShard adds generation_method/promotion_requirements/ttl_days/citation_required;
      Phase 3 ships citation_required field, Phase 7 enforces the promotion gate.
D-07: All 5 subtypes + 3 nested models live in this single file (no subtype_models.py split).
D-11 (Phase 02 carry-forward): ConfigDict(extra="forbid") inherited from ShardEnvelope on
      subtypes; nested models declare it explicitly. No pyoxigraph/rdflib/oxrdflib/owlready2
      imports (Phase 02 dep-leak guard covers this file via tests/shards/test_dep_leak_guard.py).
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from folio_insights.shards.envelope import ShardEnvelope


class SimpleAssertionShard(ShardEnvelope):
    """PRD §6.2.1 — bare envelope. The envelope carries everything (D-01)."""
    shard_type: Literal["simple_assertion"] = "simple_assertion"
    # No subtype-specific fields. No validator.


# ── Nested models for DisputedPropositionShard (D-02) ──


class Objection(BaseModel):
    """PRD §6.2.2 — single objection in a Summa-article dispute.

    REVIEW WR-01 (Phase 03): ``cites`` and ``argues`` enforce ``min_length=1``
    so empty-string IRIs/text cannot construct. Pydantic ``min_length`` does
    NOT strip whitespace, but downstream consumers that parse IRIs will reject
    blanks; this guard catches the obvious case where extraction yields ``""``.
    """
    model_config = ConfigDict(extra="forbid")

    cites: str = Field(min_length=1)           # IRI of cited authority (non-empty)
    argues: str = Field(min_length=1)          # the objection proposition (non-empty)
    strength: float = Field(ge=0.0, le=1.0)


class Reply(BaseModel):
    """PRD §6.2.2 — reply to a specific objection (by index).

    REVIEW WR-01 (Phase 03): ``argument`` enforces ``min_length=1`` so
    empty-string replies cannot construct.
    """
    model_config = ConfigDict(extra="forbid")

    objection_index: int
    replies_via: Literal[
        "distinguo",
        "authority_supersession",
        "scope_limitation",
        "factual_distinction",
    ]
    argument: str = Field(min_length=1)


# CONTEXT D-03: 4-subset narrowing of envelope.epistemic_status for DisputedProp.
# NOTE: "authority_only" substitutes for PRD's "attested" — envelope.py:139-148
# ships no "attested" Literal (planner-resolved 2026-04-25).
_DISPUTED_EPISTEMIC_STATUS_SUBSET = frozenset(
    {"hypothesis", "authority_only", "contested", "aporetic"}
)


class DisputedPropositionShard(ShardEnvelope):
    """PRD §6.2.2 — Summa-article: utrum / objections / sed contra / respondeo / replies (D-02)."""
    shard_type: Literal["disputed_proposition"] = "disputed_proposition"
    # ── Subtype-specific fields (PRD §6.2.2) ──
    utrum: str
    objections: list[Objection]
    sed_contra: Objection
    respondeo: str
    uses_distinctions: list[str] = Field(default_factory=list)
    replies: list[Reply]

    @model_validator(mode="after")
    def _disputed_invariants(self) -> "DisputedPropositionShard":
        """D-02/D-03: epistemic_status ∈ 4-subset, ≥1 objection, valid reply indices."""
        if self.epistemic_status not in _DISPUTED_EPISTEMIC_STATUS_SUBSET:
            raise ValueError(
                f"DisputedPropositionShard.epistemic_status must be one of "
                f"{sorted(_DISPUTED_EPISTEMIC_STATUS_SUBSET)}; "
                f"got {self.epistemic_status!r} (CONTEXT D-03 4-subset)."
            )
        if len(self.objections) < 1:
            raise ValueError(
                "DisputedPropositionShard.objections must have at least one element "
                "(CONTEXT D-02; PRD §6.2.2)."
            )
        n = len(self.objections)
        for idx, reply in enumerate(self.replies):
            if not (0 <= reply.objection_index < n):
                raise ValueError(
                    f"DisputedPropositionShard.replies[{idx}].objection_index="
                    f"{reply.objection_index} is out of range for objections "
                    f"of length {n} (CONTEXT D-02)."
                )
        return self


# ── Nested model for ConflictingAuthoritiesShard (D-04) ──


class AuthorityPosition(BaseModel):
    """PRD §6.2.3 — one side of a sic-et-non conflict.

    REVIEW WR-01 (Phase 03): ``authority_iri``, ``position``, and
    ``jurisdiction`` enforce ``min_length=1`` so empty-string identifiers
    cannot construct. Consistent with GlossShard.gloss_text and
    ConflictingAuthoritiesShard.reconciliation_note non-blank treatment.
    """
    model_config = ConfigDict(extra="forbid")

    authority_iri: str = Field(min_length=1)
    position: str = Field(min_length=1)
    jurisdiction: str = Field(min_length=1)
    weight: Literal["binding", "persuasive", "minority", "majority"]


# CONTEXT D-04: 8-value reconciliation strategy lock (no 9th "custom" escape hatch).
ReconciliationStrategy = Literal[
    "sense_distinction",
    "contextual_limitation",
    "voice_attribution",
    "textual_correction",
    "retraction_later",
    "subsequent_overruling",
    "jurisdictional_scoping",
    "unreconciled",
]


class ConflictingAuthoritiesShard(ShardEnvelope):
    """PRD §6.2.3 — sic-et-non with 8-value reconciliation strategy (D-04)."""
    shard_type: Literal["conflicting_authorities"] = "conflicting_authorities"
    # ── Subtype-specific fields (PRD §6.2.3) ──
    sic: list[AuthorityPosition]
    non: list[AuthorityPosition]
    reconciliation_strategy: ReconciliationStrategy
    reconciliation_note: str

    @model_validator(mode="after")
    def _sic_non_non_empty(self) -> "ConflictingAuthoritiesShard":
        """D-04: sic and non each have ≥1 element; reconciliation_note non-blank."""
        if len(self.sic) < 1:
            raise ValueError(
                "ConflictingAuthoritiesShard.sic must have at least one element "
                "(CONTEXT D-04)."
            )
        if len(self.non) < 1:
            raise ValueError(
                "ConflictingAuthoritiesShard.non must have at least one element "
                "(CONTEXT D-04)."
            )
        if not self.reconciliation_note.strip():
            raise ValueError(
                "ConflictingAuthoritiesShard.reconciliation_note must not be empty "
                "or whitespace-only (CONTEXT D-04)."
            )
        return self


# CONTEXT D-05: 5-value gloss kind enumeration.
GlossKind = Literal[
    "clarificatoria",
    "extensiva",
    "restrictiva",
    "dissentiens",
    "historica",
]


# D-05 IRI format: urn:folio:shard/<16-hex> (Phase 02 D-02 prefix) OR http(s)://...
# Format-only check; referential integrity is Phase 5 SHACL or Phase 13 storage scope.
#
# REVIEW IN-02 (Phase 03): _GLOSS_HTTP_RE is INTENTIONALLY permissive — it accepts
# any string starting with http(s):// and followed by ≥1 non-whitespace character.
# This is by design at this layer:
#   ACCEPTED (intentional):  "http://x", "https://!@#", "https://a.b/c?d=e#f"
#   REJECTED (boundary):     "https://" (no trailing chars), "http:// space" (whitespace),
#                            "ftp://...", "shard/..." (wrong/missing scheme)
# Stricter RFC 3986 parsing, host validation, and referential integrity are NOT
# this regex's job — they belong to Phase 5 SHACL constraints or Phase 13 storage.
# Boundary case "https://" is exercised in test_subtype_gloss.py rejection table
# coverage to lock the [^\s]+ ≥1-char requirement.
_GLOSS_URN_RE = re.compile(r"^urn:folio:shard/[a-f0-9]{16}$")
_GLOSS_HTTP_RE = re.compile(r"^https?://[^\s]+$")


class GlossShard(ShardEnvelope):
    """PRD §6.2.4 — layered commentary on another shard (D-05)."""
    shard_type: Literal["gloss"] = "gloss"
    # ── Subtype-specific fields (PRD §6.2.4) ──
    glosses: str                              # IRI of shard being annotated
    gloss_kind: GlossKind
    gloss_text: str

    @model_validator(mode="after")
    def _gloss_format(self) -> "GlossShard":
        """D-05: glosses IRI format + no self-glossing + non-empty gloss_text."""
        if not (_GLOSS_URN_RE.match(self.glosses) or _GLOSS_HTTP_RE.match(self.glosses)):
            raise ValueError(
                f"GlossShard.glosses must match urn:folio:shard/<16-hex> "
                f"or http(s)://... ; got {self.glosses!r} (CONTEXT D-05)."
            )
        if self.glosses == self.shard_iri:
            raise ValueError(
                "GlossShard.glosses must not equal self.shard_iri (no self-glossing; "
                "CONTEXT D-05)."
            )
        if not self.gloss_text.strip():
            raise ValueError(
                "GlossShard.gloss_text must not be empty or whitespace-only "
                "(CONTEXT D-05)."
            )
        return self


# CONTEXT D-06: 3-value generation method enumeration.
GenerationMethod = Literal["combinatorial", "inductive", "analogical"]


class HypothesisShard(ShardEnvelope):
    """PRD §6.2.5 — candidate hypothesis with TTL (D-06).

    Phase 3 ships the citation_required field; Phase 7 governance enforces the
    promotion-time gate. NO Pydantic validator blocks construction with
    citation_required=True and empty depends_on_* lists — a hypothesis can
    legitimately accumulate citations between extraction and promotion.
    """
    shard_type: Literal["hypothesis"] = "hypothesis"
    # ── Subtype-specific fields (PRD §6.2.5) ──
    generation_method: GenerationMethod
    promotion_requirements: list[str] = Field(default_factory=list)
    ttl_days: int = 90
    citation_required: bool = True

    @model_validator(mode="after")
    def _ttl_positive(self) -> "HypothesisShard":
        """D-06: ttl_days >= 1 (no zero or negative TTL). NO citation gate (Phase 7)."""
        if self.ttl_days < 1:
            raise ValueError(
                f"HypothesisShard.ttl_days must be >= 1; got {self.ttl_days} "
                "(CONTEXT D-06)."
            )
        return self


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
