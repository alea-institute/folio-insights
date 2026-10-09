"""Reconciliation proposals for cluster findings (Phase 9 U1, R4).

A contradiction between two shards that each pass unit validation is a
choice, not a bug to patch silently (PHILOSOPHY.md Part V: "a red test can be
satisfied by revising any of a set; the protocol exposes the choice"). These
functions rank candidate reconciliations, drawn ONLY from the eight
``ReconciliationStrategy`` values of ``shards.subtypes``, from the structural
differences between the shards: jurisdiction, framework, voice (speech act),
valid time, shared source and shared terms. ``unreconciled`` is always the
last option offered.

Proposals are report data. Nothing here (or anywhere in ``validation``)
applies one: a reviewer records a reconciliation through the governance path.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

from folio_insights.shards.subtypes import ReconciliationStrategy

if TYPE_CHECKING:
    from folio_insights.shards import ShardEnvelope

RECONCILIATION_STRATEGIES: tuple[str, ...] = get_args(ReconciliationStrategy)

# Speech acts that report someone's voice rather than state binding law: a
# conflict with one of these is first a question of attribution.
NON_AUTHORITATIVE_VOICES: frozenset[str] = frozenset(
    {"dictum", "pleading_argument", "practitioner_advice", "treatise_statement"}
)

JurisdictionOf = Callable[[str], "str | None"]


class Proposal(BaseModel):
    """One candidate reconciliation for a finding. Never applied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: ReconciliationStrategy
    rank: int = Field(ge=1)
    rationale: str = Field(min_length=1)

    @field_validator("strategy")
    @classmethod
    def _known(cls, value: str) -> str:
        # The Literal already refuses other values; this keeps the invariant
        # explicit should the field type ever widen.
        if value not in RECONCILIATION_STRATEGIES:
            raise ValueError(f"unknown reconciliation strategy {value!r}")
        return value


def _ranked(candidates: list[tuple[str, str]]) -> list[Proposal]:
    """Number candidates in order, keeping the first rationale per strategy and
    putting ``unreconciled`` last."""
    seen: dict[str, str] = {}
    for strategy, rationale in candidates:
        if strategy != "unreconciled":
            seen.setdefault(strategy, rationale)
    seen["unreconciled"] = (
        "Record the conflict as unreconciled and leave both shards for review; "
        "no reconciliation is chosen automatically."
    )
    return [
        Proposal(strategy=s, rank=n, rationale=r)  # type: ignore[arg-type]
        for n, (s, r) in enumerate(seen.items(), start=1)
    ]


def _shared_terms(a: ShardEnvelope, b: ShardEnvelope) -> list[str]:
    terms_a = {a.triple.subject, a.triple.object, a.reference}
    terms_b = {b.triple.subject, b.triple.object, b.reference}
    return sorted(t for t in terms_a & terms_b if t)


def propose_for_contradiction(
    a: ShardEnvelope,
    b: ShardEnvelope,
    *,
    jurisdiction_of: JurisdictionOf | None = None,
) -> list[Proposal]:
    """Ranked reconciliations for a contradiction between ``a`` and ``b``."""
    out: list[tuple[str, str]] = []
    jur_a = jurisdiction_of(a.framework_id) if jurisdiction_of else None
    jur_b = jurisdiction_of(b.framework_id) if jurisdiction_of else None
    if jur_a and jur_b and jur_a != jur_b:
        out.append((
            "jurisdictional_scoping",
            f"The shards belong to different jurisdictions ({jur_a} vs {jur_b}); "
            "scope each proposition to its own jurisdiction.",
        ))
    if a.framework_id != b.framework_id:
        out.append((
            "contextual_limitation",
            f"The shards are framed in different frameworks ({a.framework_id} vs "
            f"{b.framework_id}); limit each to the context its framework governs.",
        ))
    voices = {a.speech_act, b.speech_act}
    if voices & NON_AUTHORITATIVE_VOICES and a.speech_act != b.speech_act:
        out.append((
            "voice_attribution",
            f"The shards speak in different voices ({a.speech_act} vs {b.speech_act}); "
            "attribute the non-authoritative statement to its speaker instead of "
            "asserting it as law.",
        ))
    if a.valid_time_start and b.valid_time_start and a.valid_time_start != b.valid_time_start:
        later = a if a.valid_time_start > b.valid_time_start else b
        out.append((
            "subsequent_overruling",
            f"The shards hold at different times; the later one ({later.shard_iri}) "
            "may overrule or supersede the earlier.",
        ))
    shared = _shared_terms(a, b)
    if shared:
        out.append((
            "sense_distinction",
            f"The shards share the term(s) {', '.join(shared)}; they may use it in "
            "different senses (distinguo).",
        ))
    if a.source_uri == b.source_uri:
        out.append((
            "textual_correction",
            "Both shards come from the same source; check the source text and the "
            "extraction for a transcription or extraction error.",
        ))
        out.append((
            "retraction_later",
            "The same source may state one proposition and later retract or qualify it.",
        ))
    if not shared:
        out.append((
            "sense_distinction",
            "The shards may use a common concept in different senses (distinguo).",
        ))
    return _ranked(out)


def propose_for_conflict_set(
    shards: list[ShardEnvelope],
    *,
    jurisdiction_of: JurisdictionOf | None = None,
) -> list[Proposal]:
    """Ranked reconciliations for a minimal conflicting set of any size.

    One shard that conflicts with the TBox alone points at its own content or
    sense; two shards get ``propose_for_contradiction``; for three or more the
    pairwise candidates are merged in order of first appearance.
    """
    if not shards:
        return _ranked([])
    if len(shards) == 1:
        return _ranked([
            ("textual_correction",
             "The shard conflicts with the ontology on its own; check its source text "
             "and extraction for an error."),
            ("sense_distinction",
             "The shard may use an ontology term in a sense the ontology does not "
             "define; distinguish the senses."),
        ])
    merged: list[tuple[str, str]] = []
    for i, a in enumerate(shards):
        for b in shards[i + 1:]:
            for p in propose_for_contradiction(a, b, jurisdiction_of=jurisdiction_of):
                merged.append((p.strategy, p.rationale))
    return _ranked(merged)


def propose_for_citation(
    citing: ShardEnvelope,
    cited: ShardEnvelope,
    *,
    relation: str,
) -> list[Proposal]:
    """Ranked reconciliations for a shard citing a shard in an incompatible
    framework (``relation`` from ``crossref``)."""
    out: list[tuple[str, str]] = []
    if relation in {"unrelated_jurisdiction", "nested_jurisdiction"}:
        out.append((
            "jurisdictional_scoping",
            f"{citing.framework_id} cites {cited.framework_id} across jurisdictions; "
            "scope the dependency to the jurisdiction where it holds.",
        ))
    out.append((
        "voice_attribution",
        f"Cite the {cited.framework_id} shard as foreign or persuasive authority, "
        "attributed to its own framework, rather than as binding support.",
    ))
    out.append((
        "contextual_limitation",
        "Limit the citing shard's reliance on the cited shard to the context in which "
        "the two frameworks agree.",
    ))
    return _ranked(out)


__all__ = [
    "NON_AUTHORITATIVE_VOICES",
    "Proposal",
    "RECONCILIATION_STRATEGIES",
    "propose_for_citation",
    "propose_for_conflict_set",
    "propose_for_contradiction",
]
