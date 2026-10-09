"""Mint eligibility: may this KnowledgeUnit become a shard? (drain U8, R2, KTD1).

The v1 extraction invented content: on the books UAT about nine in ten tags
named the wrong concept and offsets did not slice the text they claimed
(``docs/evidence/books/DE-RISK-FINDINGS.md``). Eligibility is where that stops.
A unit is minted only on evidence the minter re-checks itself, never on what
the extraction run says about its own output:

* **The anchor re-verifies against the source file.** The check is RUB-EXTRACT-05's
  own (``rubric.criteria.assess_anchor``): the claimed character span must slice a
  non-empty passage that equals the unit's ``source_snippet`` (and the run's stored
  anchor score, when it recorded one, must itself reach the bar), or else the
  snippet (or, lacking one, the unit text) must match the source at
  ``services.anchoring.MIN_ANCHOR_SCORE`` (0.85) by ``rapidfuzz`` partial ratio.
  The result is the VERIFIED SOURCE SLICE: a verbatim substring of the source with
  its offsets. It, never the unit's distilled text, becomes the shard's
  ``source_span`` and so its identity (KTD1).
* **The unit says something.** ``services.substance.is_substantive`` must hold for
  both the verified slice and the unit text: a heading, contents line or
  attribution is refused even when its anchor is exact.
* **Every carried FOLIO IRI is trustworthy.** A tag with an IRI must come from the
  deterministic entity ruler, or from a path the tagger B9-verifies (``llm``,
  ``semantic``, ``heading_context``) in a run that recorded B9 verification, and
  then it must also have been ruled on by the LLM judge (``judge_status ==
  "judged"``; KTD7 of Phase 10: unjudged tags are kept by the tagger but are never
  minted). Proposed-class tags carry no IRI and are not checked.
* **Prompt identity is known.** An LLM-derived unit must name the template of every
  LLM call that shaped it (U1 lineage), so its ``extraction_prompt_hash`` is real.

Refusal codes (``REFUSAL_CODES``), checked cheapest first: the unit's own fields
and lineage, then the source file, then the duplicate check. Every failing check
is recorded (``Refused.reasons``); the first is the primary ``code``. Field
inference, framework, BFO and storage refusals are added later in the pipeline
(``minting.fields``, ``minting.minter``) with their own codes.

Nothing here calls an LLM, opens storage or writes anything.
"""
from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from folio_insights.models.knowledge_unit import ConceptTag, KnowledgeType, KnowledgeUnit
from folio_insights.services.anchoring import MIN_ANCHOR_SCORE, resolve_anchor
from folio_insights.services.substance import is_substantive

# ── refusal codes ────────────────────────────────────────────────────────

METADATA_UNIT = "metadata_unit"
UNIT_TYPE_UNSUPPORTED = "unit_type_unsupported"
NO_FOLIO_CONCEPT = "no_folio_concept"
IRI_UNVERIFIED = "iri_unverified"
IRI_UNJUDGED = "iri_unjudged"
NO_PROMPT_IDENTITY = "no_prompt_identity"
SOURCE_UNAVAILABLE = "source_unavailable"
ANCHOR_UNVERIFIED = "anchor_unverified"
NOT_SUBSTANTIVE = "not_substantive"
DUPLICATE_IN_RUN = "duplicate_in_run"
# Added by later stages (minting.fields / minting.minter):
DEPENDENCY_UNRESOLVED = "dependency_unresolved"
FRAMEWORK_UNCONFIDENT = "framework_unconfident"
FIELD_INFERENCE_UNAVAILABLE = "field_inference_unavailable"
FIELD_INFERENCE_FAILED = "field_inference_failed"
FIELD_LOW_CONFIDENCE = "field_low_confidence"  # reported as field_low_confidence:<field>
BFO_UNCLASSIFIABLE = "bfo_unclassifiable"
STORAGE_REFUSED = "storage_refused"  # reported as storage_refused:<ExceptionType>

#: Every code, in the order the pipeline checks it.
REFUSAL_CODES: tuple[str, ...] = (
    METADATA_UNIT,
    UNIT_TYPE_UNSUPPORTED,
    NO_FOLIO_CONCEPT,
    IRI_UNVERIFIED,
    IRI_UNJUDGED,
    NO_PROMPT_IDENTITY,
    SOURCE_UNAVAILABLE,
    ANCHOR_UNVERIFIED,
    NOT_SUBSTANTIVE,
    DUPLICATE_IN_RUN,
    DEPENDENCY_UNRESOLVED,
    FRAMEWORK_UNCONFIDENT,
    FIELD_INFERENCE_UNAVAILABLE,
    FIELD_INFERENCE_FAILED,
    FIELD_LOW_CONFIDENCE,
    BFO_UNCLASSIFIABLE,
    STORAGE_REFUSED,
)

# ── tag provenance ───────────────────────────────────────────────────────

#: The deterministic entity-ruler path: its IRIs are trusted as-is (no judge applies).
RULER_PATH = "entity_ruler"
#: Paths whose carried IRIs the folio tagger B9-verifies against their evidence text
#: (``FolioTaggerStage._reconciled_to_tags``) and the LLM judge then rules on.
B9_PATHS: frozenset[str] = frozenset({"llm", "semantic", "heading_context"})
VERIFIED_PATHS: frozenset[str] = frozenset({RULER_PATH}) | B9_PATHS

#: Unit types the SimpleAssertion mapping covers (``minting.mapper.PREDICATE_BY_UNIT_TYPE``).
#: Citations and procedural rules wait on subtype routing (Phase 10 U17 Open Question 1).
SUPPORTED_UNIT_TYPES: frozenset[KnowledgeType] = frozenset(
    {KnowledgeType.ADVICE, KnowledgeType.PRINCIPLE, KnowledgeType.PITFALL}
)

#: (stage, action) lineage events written as the direct result of an LLM call. Each must
#: carry its template identity (U1, KTD2) for the unit's prompt hash to be real.
LLM_LINEAGE_EVENTS: frozenset[tuple[str, str]] = frozenset({
    ("distiller", "distill"),
    ("knowledge_classifier", "classify"),
    ("knowledge_classifier", "novelty_score"),
    ("folio_tagger", "judge"),
})
#: Lineage events by which the folio tagger marks a metadata / front-matter unit.
METADATA_LINEAGE_EVENTS: frozenset[tuple[str, str]] = frozenset({
    ("folio_tagger", "skip"),
    ("folio_tagger", "metadata-signal"),
})


@dataclass(frozen=True)
class RunEvidence:
    """What the extraction run's own summary proves about how its tags were made.

    ``b9_verified`` is true when the run's ``summary.folio_tagger`` records the B9
    carried-IRI verification count (``carried_iris_rejected``), i.e. the tagger that
    produced the tags verified every non-ruler IRI against its evidence text. A run
    from before B9 (or with no tagger metadata) cannot vouch for a non-ruler IRI.
    """

    b9_verified: bool = False
    judge_enabled: bool | None = None

    @classmethod
    def from_extraction(cls, extraction: Mapping[str, Any]) -> RunEvidence:
        summary = extraction.get("summary") if isinstance(extraction, Mapping) else None
        tagger = summary.get("folio_tagger") if isinstance(summary, Mapping) else None
        if not isinstance(tagger, Mapping):
            return cls()
        judge = tagger.get("judge_enabled")
        return cls(
            b9_verified="carried_iris_rejected" in tagger,
            judge_enabled=judge if isinstance(judge, bool) else None,
        )


# ── outcomes ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Reason:
    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class Eligible:
    """The unit may be minted from ``verified_span`` (``source[start:end]``, verbatim).

    ``method`` is how the anchor verified: ``span`` (the claimed span slices the
    snippet), ``snippet`` (the snippet matched the source by fuzzy alignment) or
    ``unit_text`` (no snippet; the unit text itself matched). ``match`` is the
    anchor score in [0.85, 1.0]. ``tags`` are the IRI-carrying tags the minter may
    use, most confident first.
    """

    verified_span: str
    span_offsets: tuple[int, int]
    method: str
    match: float
    source_key: str
    source_sha256: str
    tags: tuple[ConceptTag, ...]

    @property
    def top_tag(self) -> ConceptTag:
        return self.tags[0]


@dataclass(frozen=True)
class Refused:
    """The unit is not minted. ``code`` is the primary (first-checked) reason."""

    code: str
    detail: str
    reasons: tuple[Reason, ...] = field(default_factory=tuple)

    @classmethod
    def of(cls, reasons: Iterable[Reason]) -> Refused:
        items = tuple(reasons)
        if not items:
            raise ValueError("a refusal needs at least one reason")
        return cls(items[0].code, items[0].detail, items)

    @classmethod
    def single(cls, code: str, detail: str) -> Refused:
        return cls.of([Reason(code, detail)])


Outcome = Eligible | Refused

#: ``source_key -> (text, "")`` or ``(None, reason)`` (``rubric.adapters.SourceResolver.resolve_path``).
SourceTextResolver = Callable[[str], tuple[str | None, str]]


def source_key(unit: KnowledgeUnit) -> str:
    """The key the unit's source text is looked up by (the ingested file path)."""
    return unit.original_span.source_file or unit.source_file


def _span_key(source: str, span: str) -> str:
    folded = unicodedata.normalize("NFC", span.replace("\r\n", "\n").replace("\r", "\n")).strip()
    return f"{source}\n{folded}"


def iri_tags(unit: KnowledgeUnit) -> tuple[ConceptTag, ...]:
    """The unit's IRI-carrying tags, most confident first (ties by IRI), one per IRI."""
    best: dict[str, ConceptTag] = {}
    for tag in unit.folio_tags:
        if not tag.iri:
            continue
        held = best.get(tag.iri)
        if held is None or tag.confidence > held.confidence:
            best[tag.iri] = tag
    return tuple(sorted(best.values(), key=lambda t: (-t.confidence, t.iri)))


# ── the checks (cheapest first) ──────────────────────────────────────────


def _metadata(unit: KnowledgeUnit) -> Reason | None:
    for event in unit.lineage:
        if (event.stage, event.action) in METADATA_LINEAGE_EVENTS:
            return Reason(METADATA_UNIT, f"the folio tagger marked it metadata ({event.action})")
    from folio_resolve import SourceClassifier

    section = " > ".join(unit.source_section) if unit.source_section else ""
    if not SourceClassifier().is_taggable(section, unit.text or ""):
        return Reason(METADATA_UNIT, "the source classifier rates its section as metadata or "
                                     "front matter, not a taggable insight source")
    return None


def _unit_type(unit: KnowledgeUnit) -> Reason | None:
    if unit.unit_type in SUPPORTED_UNIT_TYPES:
        return None
    return Reason(UNIT_TYPE_UNSUPPORTED,
                  f"unit type {unit.unit_type.value!r} has no SimpleAssertion mapping yet "
                  "(subtype routing waits on Phase 10 U17 Open Question 1)")


def _iri_checks(unit: KnowledgeUnit, run: RunEvidence) -> list[Reason]:
    tags = iri_tags(unit)
    if not tags:
        return [Reason(NO_FOLIO_CONCEPT, "the unit carries no FOLIO IRI to state the "
                                         "proposition about")]
    reasons: list[Reason] = []
    unverified = [t for t in unit.folio_tags if t.iri and t.extraction_path not in VERIFIED_PATHS]
    if unverified:
        paths = sorted({t.extraction_path or "(none)" for t in unverified})
        reasons.append(Reason(IRI_UNVERIFIED,
                              f"{len(unverified)} IRI tag(s) came from a path that is neither the "
                              f"entity ruler nor B9-verified: {', '.join(paths)}"))
    non_ruler = [t for t in unit.folio_tags if t.iri and t.extraction_path in B9_PATHS]
    if non_ruler and not run.b9_verified:
        reasons.append(Reason(IRI_UNVERIFIED,
                              f"{len(non_ruler)} non-ruler IRI tag(s), but the run records no B9 "
                              "carried-IRI verification (summary.folio_tagger."
                              "carried_iris_rejected)"))
    unjudged = [t for t in non_ruler if t.judge_status != "judged"]
    if unjudged:
        states = sorted({str(t.judge_status) for t in unjudged})
        reasons.append(Reason(IRI_UNJUDGED,
                              f"{len(unjudged)} non-ruler IRI tag(s) were not ruled on by the "
                              f"judge (judge_status {', '.join(states)})"))
    return reasons


def _prompt_identity(unit: KnowledgeUnit) -> Reason | None:
    missing = sorted({
        f"{e.stage}.{e.action}"
        for e in unit.lineage
        if (e.stage, e.action) in LLM_LINEAGE_EVENTS and not (e.template_id and e.template_hash)
    })
    if missing:
        return Reason(NO_PROMPT_IDENTITY,
                      f"LLM lineage event(s) without a template identity: {', '.join(missing)}")
    llm_tagged = any(t.extraction_path == "llm" for t in unit.folio_tags)
    concept_recorded = any(
        e.stage == "folio_tagger" and e.template_id for e in unit.lineage
    )
    if llm_tagged and not concept_recorded:
        return Reason(NO_PROMPT_IDENTITY,
                      "LLM-path tags, but no folio_tagger lineage event names the concept "
                      "template that produced them")
    return None


def _verify_anchor(
    unit: KnowledgeUnit, source: str, raw_has_stored: bool
) -> tuple[tuple[int, int], str, float] | Reason:
    """``((start, end), method, match)`` of the verified slice, or the refusal reason.

    The decision is RUB-EXTRACT-05's ``assess_anchor``; this only recovers the
    offsets of the passage it verified.
    """
    from folio_insights.rubric.adapters import AnchorClaim, RubricUnit
    from folio_insights.rubric.criteria import assess_anchor

    span = (unit.original_span.start, unit.original_span.end)
    claim = AnchorClaim(
        source_key=source_key(unit),
        source_text=source,
        span=span,
        snippet=unit.source_snippet,
        text_as_quote=unit.text,
        stored_score=unit.anchor_score if raw_has_stored else None,
        stored_verified=unit.anchor_verified if raw_has_stored else None,
    )
    assessment = assess_anchor(RubricUnit(
        id=unit.id, text=unit.text, chapter=source_key(unit),
        content_hash=unit.content_hash or "", tags=(), anchor=claim,
    ))
    if assessment.score == 0 or not assessment.passage:
        detail = f"anchor did not verify at {MIN_ANCHOR_SCORE:.2f} (best match " \
                 f"{assessment.match:.4f}"
        if assessment.issues:
            detail += f"; {', '.join(assessment.issues)}"
        return Reason(ANCHOR_UNVERIFIED, detail + ")")
    if assessment.route == "span":
        return span, "span", assessment.match
    quote = unit.source_snippet if assessment.route == "snippet" else unit.text
    found = resolve_anchor(quote, source)
    if found is None or not found.verified or found.snippet != assessment.passage:
        # Unreachable while assess_anchor resolves the same quote the same way; refuse
        # rather than mint from a slice whose offsets are not known.
        return Reason(ANCHOR_UNVERIFIED, "the verified passage could not be located again")
    return (found.start, found.end), assessment.route, found.score


def evaluate(
    unit: KnowledgeUnit,
    source_text_resolver: SourceTextResolver,
    *,
    run: RunEvidence | None = None,
    seen: set[str] | None = None,
    stored_anchor: bool = True,
) -> Outcome:
    """Decide whether ``unit`` may be minted (module docstring).

    ``seen`` carries the duplicate keys of units already found eligible in this
    run; an eligible unit adds its own. ``stored_anchor`` says whether the run's
    record of this unit carried ``anchor_score`` / ``anchor_verified`` (an old
    run without them is judged on the fuzzy match alone, as the rubric does).
    """
    run = run or RunEvidence()
    reasons: list[Reason] = []

    for check in (_metadata, _unit_type):
        reason = check(unit)
        if reason is not None:
            reasons.append(reason)
    reasons.extend(_iri_checks(unit, run))
    reason = _prompt_identity(unit)
    if reason is not None:
        reasons.append(reason)

    key = source_key(unit)
    text, error = source_text_resolver(key)
    verified: tuple[tuple[int, int], str, float] | None = None
    if text is None:
        reasons.append(Reason(SOURCE_UNAVAILABLE,
                              f"source {key!r} could not be read ({error or 'unknown'})"))
    else:
        anchored = _verify_anchor(unit, text, stored_anchor)
        if isinstance(anchored, Reason):
            reasons.append(anchored)
        else:
            verified = anchored

    span_text = text[verified[0][0]:verified[0][1]] if (text is not None and verified) else None
    if not is_substantive(unit.text):
        reasons.append(Reason(NOT_SUBSTANTIVE, "the unit text is a heading, contents line, "
                                               "attribution or too short to be a proposition"))
    elif span_text is not None and not is_substantive(span_text):
        reasons.append(Reason(NOT_SUBSTANTIVE, "the verified source passage is a heading, "
                                               "contents line or attribution"))

    keys: list[str] = []
    if span_text is not None:
        keys.append("span:" + _span_key(key, span_text))
    keys.append("hash:" + (unit.content_hash or hashlib.sha256(unit.text.encode()).hexdigest()))
    if seen is not None and any(k in seen for k in keys):
        reasons.append(Reason(DUPLICATE_IN_RUN, "an earlier unit of this run already mints the "
                                                "same source passage or content"))

    if reasons:
        return Refused.of(reasons)
    assert text is not None and verified is not None and span_text is not None
    if seen is not None:
        seen.update(keys)
    (start, end), method, match = verified
    return Eligible(
        verified_span=span_text,
        span_offsets=(start, end),
        method=method,
        match=round(float(match), 6),
        source_key=key,
        source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        tags=iri_tags(unit),
    )


__all__ = [
    "ANCHOR_UNVERIFIED",
    "B9_PATHS",
    "BFO_UNCLASSIFIABLE",
    "DEPENDENCY_UNRESOLVED",
    "DUPLICATE_IN_RUN",
    "FIELD_INFERENCE_FAILED",
    "FIELD_INFERENCE_UNAVAILABLE",
    "FIELD_LOW_CONFIDENCE",
    "FRAMEWORK_UNCONFIDENT",
    "IRI_UNJUDGED",
    "IRI_UNVERIFIED",
    "LLM_LINEAGE_EVENTS",
    "METADATA_UNIT",
    "NOT_SUBSTANTIVE",
    "NO_FOLIO_CONCEPT",
    "NO_PROMPT_IDENTITY",
    "REFUSAL_CODES",
    "RULER_PATH",
    "SOURCE_UNAVAILABLE",
    "STORAGE_REFUSED",
    "SUPPORTED_UNIT_TYPES",
    "UNIT_TYPE_UNSUPPORTED",
    "VERIFIED_PATHS",
    "Eligible",
    "Outcome",
    "Reason",
    "Refused",
    "RunEvidence",
    "SourceTextResolver",
    "evaluate",
    "iri_tags",
    "source_key",
]
