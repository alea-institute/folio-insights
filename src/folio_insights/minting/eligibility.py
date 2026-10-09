"""Mint eligibility: may this KnowledgeUnit become a shard? (drain U8, R2, KTD1).

The v1 extraction invented content: on the books UAT about nine in ten tags
named the wrong concept and offsets did not slice the text they claimed
(``docs/evidence/books/DE-RISK-FINDINGS.md``). Eligibility is where that stops.
A unit is minted only on evidence the minter re-checks itself, never on what
the extraction run says about its own output:

* **The anchor re-verifies against the source file.** The check is RUB-EXTRACT-05's
  own (``rubric.criteria.assess_anchor``), recomputed here from the source text alone:
  the claimed character span must slice a non-empty passage that equals the unit's
  ``source_snippet``, or else the snippet (or, lacking one, the unit text) must match
  the source at ``services.anchoring.MIN_ANCHOR_SCORE`` (0.85) by ``rapidfuzz``
  partial ratio. The run's own ``anchor_score`` / ``anchor_verified`` never vouch for
  a unit: they are not consulted to accept it, and their absence changes nothing. A
  run that recorded its own anchor as failed (or inconsistently) is still believed
  against itself: such a unit is refused. The result is the VERIFIED SOURCE SLICE: a
  verbatim substring of the source with its offsets. It, never the unit's distilled
  text, becomes the shard's ``source_span`` and so its identity (KTD1).
* **The claim is supported by that slice** (``minting.support``). The anchor proves
  only that the passage exists; the distiller rewrites ``unit.text`` (which becomes
  ``triple.object``) after anchoring. Every number, date, amount, percentage,
  citation, case name and multi-word proper noun of the unit text must occur in the
  verified slice (``unsupported_specifics``), its content-token recall against the
  slice must reach the policy floor (``claim_unsupported``), and, when requested, an
  NLI scorer must find the slice entails it (``claim_not_entailed``).
* **The unit says something.** ``services.substance.is_substantive`` must hold for
  both the verified slice and the unit text: a heading, contents line or
  attribution is refused even when its anchor is exact.
* **Every carried FOLIO IRI is trustworthy.** A tag with an IRI must come from the
  deterministic entity ruler, or from a path the tagger B9-verifies (``llm``,
  ``semantic``, ``heading_context``) in a run that recorded B9 verification, and
  then it must also have been ruled on by the LLM judge (``judge_status ==
  "judged"``; KTD7 of Phase 10: unjudged tags are kept by the tagger but are never
  minted). With an IRI oracle (``rubric.oracle``) every carried IRI must also EXIST
  (``iri_nonexistent``) and sit in the FOLIO branch its tag claims
  (``iri_wrong_branch``; a tag that claims no branch cannot be checked and is refused
  too). Proposed-class tags carry no IRI and are not checked.
* **Prompt identity is known.** An LLM-derived unit must name the template of every
  LLM call that shaped it (U1 lineage), so its ``extraction_prompt_hash`` is real:
  each LLM lineage event carries a template identity, LLM-path tags need a
  ``folio_tagger.tag`` event naming the concept template, judged tags a
  ``folio_tagger.judge`` event naming the judge template, and an ``llm_refined``
  boundary split the boundary template.

Refusal codes (``REFUSAL_CODES``), checked cheapest first: the unit's own fields
and lineage, the IRI oracle, then the source file and the claim support, then the
duplicate check. Every failing check is recorded (``Refused.reasons``); the first
is the primary ``code``. Field inference, framework, BFO and storage refusals are
added later in the pipeline (``minting.fields``, ``minting.minter``) with their own
codes.

Nothing here calls an LLM, opens storage or writes anything (the optional
entailment scorer is a local NLI model, injected through ``SupportPolicy``).
"""
from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from folio_insights.llm.templates import BOUNDARY, BRANCH_JUDGE, CONCEPT
from folio_insights.minting.support import (
    CLAIM_NOT_ENTAILED,
    CLAIM_UNSUPPORTED,
    UNSUPPORTED_SPECIFICS,
    SupportPolicy,
    SupportResult,
    check_support,
)
from folio_insights.models.knowledge_unit import ConceptTag, KnowledgeType, KnowledgeUnit
from folio_insights.services.anchoring import MIN_ANCHOR_SCORE, resolve_anchor
from folio_insights.services.substance import is_substantive

if TYPE_CHECKING:
    from folio_insights.rubric.oracle import IriOracle

# ── refusal codes ────────────────────────────────────────────────────────

METADATA_UNIT = "metadata_unit"
UNIT_TYPE_UNSUPPORTED = "unit_type_unsupported"
NO_FOLIO_CONCEPT = "no_folio_concept"
IRI_UNVERIFIED = "iri_unverified"
IRI_UNJUDGED = "iri_unjudged"
IRI_NONEXISTENT = "iri_nonexistent"
IRI_WRONG_BRANCH = "iri_wrong_branch"
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
    IRI_NONEXISTENT,
    IRI_WRONG_BRANCH,
    NO_PROMPT_IDENTITY,
    SOURCE_UNAVAILABLE,
    ANCHOR_UNVERIFIED,
    NOT_SUBSTANTIVE,
    UNSUPPORTED_SPECIFICS,
    CLAIM_UNSUPPORTED,
    CLAIM_NOT_ENTAILED,
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
#: The boundary method an LLM call produced (``pipeline.stages.boundary_detection``); a
#: split of that method must name ``llm.templates.BOUNDARY``.
LLM_REFINED_METHOD = "llm_refined"
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
    anchor score in [0.85, 1.0], recomputed from the source. ``tags`` are the
    IRI-carrying tags the minter may use, most confident first. ``support`` is how
    well the verified slice supports the unit text (``minting.support``).
    """

    verified_span: str
    span_offsets: tuple[int, int]
    method: str
    match: float
    source_key: str
    source_sha256: str
    tags: tuple[ConceptTag, ...]
    support: SupportResult | None = None

    @property
    def top_tag(self) -> ConceptTag:
        return self.tags[0]


@dataclass(frozen=True)
class Refused:
    """The unit is not minted. ``code`` is the primary (first-checked) reason.

    ``support`` carries the claim-support metrics when the support check ran."""

    code: str
    detail: str
    reasons: tuple[Reason, ...] = field(default_factory=tuple)
    support: SupportResult | None = None

    @classmethod
    def of(cls, reasons: Iterable[Reason], *, support: SupportResult | None = None) -> Refused:
        items = tuple(reasons)
        if not items:
            raise ValueError("a refusal needs at least one reason")
        return cls(items[0].code, items[0].detail, items, support)

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


def _iri_oracle_checks(unit: KnowledgeUnit, oracle: IriOracle | None) -> list[Reason]:
    """Every carried IRI exists and sits in the branch its tag claims (RUB-EXTRACT-03's
    question, asked per unit BEFORE the write instead of after it)."""
    if oracle is None:
        return []
    from folio_insights.rubric.oracle import normalize_branch

    nonexistent = wrong = unclaimed = 0
    for tag in unit.folio_tags:
        if not tag.iri:
            continue
        if not oracle.exists(tag.iri):
            nonexistent += 1
            continue
        if not tag.branch:
            unclaimed += 1
            continue
        actual = {normalize_branch(b) for b in oracle.branch_of(tag.iri)}
        if normalize_branch(tag.branch) not in actual:
            wrong += 1
    reasons: list[Reason] = []
    if nonexistent:
        reasons.append(Reason(IRI_NONEXISTENT, f"{nonexistent} carried IRI(s) do not exist in "
                                               "the ontology the IRI oracle answers for"))
    if wrong or unclaimed:
        parts = []
        if wrong:
            parts.append(f"{wrong} IRI(s) are not in the branch their tag claims")
        if unclaimed:
            parts.append(f"{unclaimed} tag(s) claim no branch, so their branch cannot be "
                         "checked")
        reasons.append(Reason(IRI_WRONG_BRANCH, "; ".join(parts)))
    return reasons


def _has_template(unit: KnowledgeUnit, stage: str, action: str, template_id: str) -> bool:
    return any(
        e.stage == stage and e.action == action and e.template_id == template_id
        and e.template_hash for e in unit.lineage
    )


def _prompt_identity(unit: KnowledgeUnit) -> Reason | None:
    missing = sorted({
        f"{e.stage}.{e.action}"
        for e in unit.lineage
        if (e.stage, e.action) in LLM_LINEAGE_EVENTS and not (e.template_id and e.template_hash)
    })
    # An LLM-refined boundary split must name the boundary template (and only it).
    for e in unit.lineage:
        if (e.stage, e.action) == ("boundary_detection", "split") and \
                e.detail.removeprefix("method=").startswith(LLM_REFINED_METHOD) and \
                not (e.template_id == BOUNDARY.id and e.template_hash):
            missing.append("boundary_detection.split (llm_refined without the boundary "
                           "template)")
    if missing:
        return Reason(NO_PROMPT_IDENTITY,
                      f"LLM lineage event(s) without a template identity: {', '.join(missing)}")
    if any(t.extraction_path == "llm" for t in unit.folio_tags) and \
            not _has_template(unit, "folio_tagger", "tag", CONCEPT.id):
        return Reason(NO_PROMPT_IDENTITY,
                      "LLM-path tags, but no folio_tagger.tag lineage event names the concept "
                      "template that produced them")
    if any(t.iri and t.judge_status == "judged" for t in unit.folio_tags) and \
            not _has_template(unit, "folio_tagger", "judge", BRANCH_JUDGE.id):
        return Reason(NO_PROMPT_IDENTITY,
                      "judged tags, but no folio_tagger.judge lineage event names the judge "
                      "template that ruled on them")
    return None


def _stored_veto(unit: KnowledgeUnit) -> Reason | None:
    """The run's own record of a failed (or self-contradictory) anchor, believed against
    itself. A stored score never ACCEPTS a unit; this is the only use made of it."""
    stored = max(0.0, min(1.0, float(unit.anchor_score)))
    if bool(unit.anchor_verified) != (stored >= MIN_ANCHOR_SCORE):
        return Reason(ANCHOR_UNVERIFIED, "the run's own anchor record is inconsistent "
                                         "(anchor_verified disagrees with anchor_score)")
    if stored < MIN_ANCHOR_SCORE:
        return Reason(ANCHOR_UNVERIFIED, f"the run itself recorded this anchor as unverified "
                                         f"(anchor_score {stored:.4f})")
    return None


def _verify_anchor(
    unit: KnowledgeUnit, source: str, raw_has_stored: bool
) -> tuple[tuple[int, int], str, float] | Reason:
    """``((start, end), method, match)`` of the verified slice, or the refusal reason.

    The decision is RUB-EXTRACT-05's ``assess_anchor`` RECOMPUTED from the source text:
    no stored score is passed to it, so a span that slices its snippet verbatim
    verifies at 1.0 only as "this passage exists" (whether it supports the unit text is
    the claim-support check's question). ``raw_has_stored`` only enables the
    fail-closed veto of ``_stored_veto``.
    """
    from folio_insights.rubric.adapters import AnchorClaim, RubricUnit
    from folio_insights.rubric.criteria import assess_anchor

    if raw_has_stored:
        veto = _stored_veto(unit)
        if veto is not None:
            return veto
    span = (unit.original_span.start, unit.original_span.end)
    claim = AnchorClaim(
        source_key=source_key(unit),
        source_text=source,
        span=span,
        snippet=unit.source_snippet,
        text_as_quote=unit.text,
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
    oracle: IriOracle | None = None,
    support: SupportPolicy | None = None,
) -> Outcome:
    """Decide whether ``unit`` may be minted (module docstring).

    ``seen`` carries the duplicate keys of units already found eligible in this
    run; an eligible unit adds its own. ``stored_anchor`` says whether the run's
    record of this unit carried ``anchor_score`` / ``anchor_verified``; they can only
    refuse a unit (``_stored_veto``), never accept one. ``oracle`` checks every
    carried IRI's existence and branch; ``support`` is the claim-support policy
    (default ``SupportPolicy()``; its NLI scorer, when requested, must already be
    resolved).
    """
    run = run or RunEvidence()
    support = support or SupportPolicy()
    reasons: list[Reason] = []

    for check in (_metadata, _unit_type):
        reason = check(unit)
        if reason is not None:
            reasons.append(reason)
    reasons.extend(_iri_checks(unit, run))
    reasons.extend(_iri_oracle_checks(unit, oracle))
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

    measured: SupportResult | None = None
    if span_text is not None:
        measured = check_support(unit.text, span_text, support)
        reasons.extend(Reason(code, detail) for code, detail in measured.failures())

    keys: list[str] = []
    if span_text is not None:
        keys.append("span:" + _span_key(key, span_text))
    keys.append("hash:" + (unit.content_hash or hashlib.sha256(unit.text.encode()).hexdigest()))
    if seen is not None and any(k in seen for k in keys):
        reasons.append(Reason(DUPLICATE_IN_RUN, "an earlier unit of this run already mints the "
                                                "same source passage or content"))

    if reasons:
        return Refused.of(reasons, support=measured)
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
        support=measured,
    )


__all__ = [
    "ANCHOR_UNVERIFIED",
    "B9_PATHS",
    "BFO_UNCLASSIFIABLE",
    "CLAIM_NOT_ENTAILED",
    "CLAIM_UNSUPPORTED",
    "DEPENDENCY_UNRESOLVED",
    "DUPLICATE_IN_RUN",
    "FIELD_INFERENCE_FAILED",
    "FIELD_INFERENCE_UNAVAILABLE",
    "FIELD_LOW_CONFIDENCE",
    "FRAMEWORK_UNCONFIDENT",
    "IRI_NONEXISTENT",
    "IRI_UNJUDGED",
    "IRI_WRONG_BRANCH",
    "LLM_REFINED_METHOD",
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
    "UNSUPPORTED_SPECIFICS",
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
