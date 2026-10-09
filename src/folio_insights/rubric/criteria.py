"""RUB-EXTRACT v1.0 criteria: the catalogue and the deterministic ([DET]) scorers.

``docs/rubrics/extraction-quality-v1.md`` (LOCKED 2026-07-07) defines 14 criteria. Five
have a deterministic part this module computes exactly as the rubric defines it; the
rest are LLM-judged, FOLIO-MCP-judged or taste calls that only a supplied judged-scores
file can fill (``harness.py``). Every scorer is a pure function of a
``RubricArtifact`` (and, for -03, an ``IriOracle``) and returns a ``CriterionResult``.

Scales are the rubric's 0-3 (3 exemplary, 2 pass, 1 borderline, 0 fail). A per-unit
criterion reports each unit's integer score in ``per_unit`` and the mean over units as
``score`` (the rubric's roll-up: "per-chapter score = mean per-unit score"); a
per-chapter criterion reports each chapter likewise in ``details["per_chapter"]``.

**RUB-EXTRACT-03, IRI validity and branch membership** ([DET], gate-soft, 5%). Every
non-proposed ``folio_tag.iri`` must exist and sit in the branch the tag claims; a tag
with ``iri == ""`` must have ``extraction_path == "proposed_class"``. A unit with any
violation scores 0 and is ``soft_fail``: the harness caps that unit's mapping-dimension
scores (-01, -02, -04) at 1. Otherwise the unit scores 3. A tag that claims no branch
cannot be mislabeled; it is counted in ``details["branch_unclaimed"]``. Without an
oracle the criterion is not computed.

**RUB-EXTRACT-05, source anchoring** ([DET] part; [GATE] hybrid-strict, 10%). A unit
verifies when (a) its char-span slices a non-empty passage of an existing source that is
the passage it claims, or (b) an exact quoted snippet fuzzy-matches the source at
``services.anchoring.MIN_ANCHOR_SCORE`` (0.85) or better, with ``resolve_anchor`` (exact
substring, else ``rapidfuzz`` partial-ratio alignment). Per unit:

* the claimed quote is the unit's ``source_snippet``; a unit without one (the pre-anchor
  format of the books UAT) offers its own text as the quote;
* **3** the span slices the quote exactly (for a pipeline snippet, also with a recorded
  anchor score above 0.92), or the quote is found in the source at a score above 0.92
  and the span agrees;
* **2** the anchor verifies but loosely: the quote matches at 0.85-0.92, or it verifies
  only somewhere the span does not point ("span loose but non-empty");
* **0** no verifying anchor: source missing, span out of bounds or empty, the quote
  matching below 0.85, or the pipeline's own recorded anchor result below the bar.

A pipeline snippet is always ``source[start:end]`` of the best-aligned window, even when
that window did not verify, so a snippet that equals its slice is trusted only up to the
anchor score the pipeline recorded for it (a fluent paraphrase anchored at 0.62 fails).
Any unit at 0 fails the gate. Shards claim their ``source_span`` as the quote and have
no char offsets, so they are scored on (b) alone; because a verbatim span always
anchors, a shard's anchor counts only when the passage also SUPPORTS the shard's claim
(``AnchorClaim.claim``: its literal ``triple.object``, else its ``sense``) by
``minting.support.check_support``'s deterministic test (every specific of the claim
occurs in the passage, content-token recall >= 0.6); an unsupported claim scores 0
(``unsupported_specifics:<classes>`` / ``claim_unsupported:<ratio>``). The [LLM] half
(a judge's reading of that support) is not computed here; ``details["llm_component"]``
says so.

**RUB-EXTRACT-09, precision / no padding / no dup** ([DET] part, per chapter, 6%). A unit
is flagged when its ``content_hash`` repeats an earlier unit's (dedup did not hold) or
when it is a heading, contents entry or attribution line (``services.substance.
is_structural`` on the unit text, or on the passage it verifiably anchors to). With
``k`` flagged units out of ``n`` in a chapter: **3** k = 0; **2** k = 1 ("<= 1
filler/dup"); **1** k >= 2 and k / n <= 10% ("several"); **0** k / n > 10% ("noisy").
The [LLM] filler spot-check is not computed.

**RUB-EXTRACT-10, shape conformance** ([DET], [GATE], 6%) and **RUB-EXTRACT-11,
structural integrity** ([DET], [GATE], 4%) score a shard corpus's full SHACL validation
and the export structural checks: -10 **3** clean, **2** conforms with warnings, **0**
violations; -11 **3** all checks PASS, **0** any FAIL. A unit run has no RDF, so both are
not computed there.

**Interpretation notes** (where the rubric is silent): a snippet scoring above 0.92 but
below 1.0 scores 3 (the 2-band is exactly 0.85-0.92, inclusive); on -11 a WARN with no
FAIL (the v1 report's namespace check only ever warns) passes the gate and scores 2,
mirroring -10's "conforms with warnings", because the scale defines only 3 and 0.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from folio_insights.rubric.adapters import RubricArtifact, RubricUnit
from folio_insights.rubric.oracle import IriOracle, normalize_branch
from folio_insights.services.anchoring import MIN_ANCHOR_SCORE, resolve_anchor
from folio_insights.services.substance import is_structural

RUBRIC_ID = "RUB-EXTRACT"
RUBRIC_VERSION = "v1.0"
RUBRIC_DOC = "docs/rubrics/extraction-quality-v1.md"

# RUB-EXTRACT-05's upper band edge: "2 ... snippet 0.85-0.92".
SNIPPET_EXACT_BAND = 0.92
# RUB-EXTRACT-09's "several" vs "noisy" boundary (share of a chapter's units).
NOISY_SHARE = 0.10

GateState = Literal["pass", "fail", "soft_fail"]
Scope = Literal["unit", "chapter", "book"]
GateKind = Literal["gate", "gate_soft"]


@dataclass(frozen=True)
class CriterionSpec:
    id: str
    title: str
    dimension: str
    scope: Scope
    judges: tuple[str, ...]
    weight: int
    gate: GateKind | None = None

    @property
    def deterministic(self) -> bool:
        """True for the five criteria whose [DET] part this module computes."""
        return self.id in DET_CRITERIA


CATALOGUE: tuple[CriterionSpec, ...] = (
    CriterionSpec("RUB-EXTRACT-01", "Concept correctness", "A", "unit", ("MCP", "TASTE"), 10),
    CriterionSpec("RUB-EXTRACT-02", "Granularity", "A", "unit", ("DET", "MCP"), 6),
    CriterionSpec("RUB-EXTRACT-03", "IRI validity & branch membership", "A", "unit", ("DET",), 5,
                  "gate_soft"),
    CriterionSpec("RUB-EXTRACT-04", "Proposed-class discipline", "A", "unit", ("MCP", "TASTE"), 4),
    CriterionSpec("RUB-EXTRACT-05", "Source anchoring (HYBRID-STRICT)", "B", "unit",
                  ("DET", "LLM"), 10, "gate"),
    CriterionSpec("RUB-EXTRACT-06", "No fabricated content", "B", "unit", ("LLM", "TASTE"), 12,
                  "gate"),
    CriterionSpec("RUB-EXTRACT-07", "Faithful compression", "B", "unit", ("LLM", "TASTE"), 8),
    CriterionSpec("RUB-EXTRACT-08", "Section coverage & recall", "C", "chapter",
                  ("DET", "LLM", "TASTE"), 14),
    CriterionSpec("RUB-EXTRACT-09", "Precision / no padding / no dup", "C", "chapter",
                  ("DET", "LLM"), 6),
    CriterionSpec("RUB-EXTRACT-10", "Shape conformance", "D", "book", ("DET",), 6, "gate"),
    CriterionSpec("RUB-EXTRACT-11", "Structural integrity", "D", "book", ("DET",), 4, "gate"),
    CriterionSpec("RUB-EXTRACT-12", "Actionability", "E", "unit", ("TASTE",), 6),
    CriterionSpec("RUB-EXTRACT-13", "Task-discoverability", "E", "unit", ("LLM", "TASTE"), 5),
    CriterionSpec("RUB-EXTRACT-14", "Value calibration", "E", "unit", ("TASTE",), 4),
)
SPECS: Mapping[str, CriterionSpec] = {spec.id: spec for spec in CATALOGUE}
# The criteria the deterministic harness computes (R7).
DET_CRITERIA: tuple[str, ...] = (
    "RUB-EXTRACT-03", "RUB-EXTRACT-05", "RUB-EXTRACT-09", "RUB-EXTRACT-10", "RUB-EXTRACT-11",
)
# The criteria only a judged-scores file can fill (AE3's not_scored list).
JUDGED_CRITERIA: tuple[str, ...] = tuple(s.id for s in CATALOGUE if s.id not in DET_CRITERIA)
MAPPING_CRITERIA: tuple[str, ...] = tuple(s.id for s in CATALOGUE if s.dimension == "A")
assert sum(spec.weight for spec in CATALOGUE) == 100


@dataclass(frozen=True)
class CriterionResult:
    """One criterion's outcome. ``computed`` is False whenever the [DET] part did not run;
    ``score`` and ``gate`` are then ``None`` and ``reason`` says why."""

    id: str
    computed: bool
    score: float | None = None
    gate: GateState | None = None
    per_unit: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    reason: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "computed": self.computed,
            "score": self.score,
            "gate": self.gate,
            "per_unit": {k: dict(v) for k, v in self.per_unit.items()},
            "reason": self.reason,
            "details": dict(self.details),
        }


def not_computed(criterion_id: str, reason: str, **details: Any) -> CriterionResult:
    return CriterionResult(id=criterion_id, computed=False, reason=reason, details=details)


def _mean(values: list[int]) -> float:
    return round(sum(values) / len(values), 6)


# ── RUB-EXTRACT-03 ────────────────────────────────────────────────────────


def iri_validity(artifact: RubricArtifact, oracle: IriOracle | None) -> CriterionResult:
    """RUB-EXTRACT-03: every non-proposed IRI exists and sits in its claimed branch."""
    cid = "RUB-EXTRACT-03"
    if oracle is None:
        return not_computed(cid, "no IRI oracle supplied (--oracle FILE or --oracle folio)")
    if not artifact.units:
        return not_computed(cid, "the artifact has no units")
    per_unit: dict[str, dict[str, Any]] = {}
    checked = unclaimed = 0
    for unit in artifact.units:
        issues: list[str] = []
        for tag in unit.tags:
            if not tag.iri:
                if tag.extraction_path != "proposed_class":
                    issues.append(f"empty_iri_not_proposed:{tag.label or '?'}")
                continue
            checked += 1
            if not oracle.exists(tag.iri):
                issues.append(f"iri_unresolvable:{tag.iri}")
                continue
            if not tag.branch:
                unclaimed += 1
                continue
            branches = oracle.branch_of(tag.iri)
            if normalize_branch(tag.branch) not in {normalize_branch(b) for b in branches}:
                actual = "|".join(branches) or "unknown"
                issues.append(f"branch_mismatch:{tag.iri}:claimed={tag.branch}:actual={actual}")
        per_unit[unit.id] = {
            "score": 0 if issues else 3,
            "gate": "soft_fail" if issues else "pass",
            "issues": issues,
        }
    scores = [entry["score"] for entry in per_unit.values()]
    capped = sorted(uid for uid, entry in per_unit.items() if entry["issues"])
    return CriterionResult(
        id=cid,
        computed=True,
        score=_mean(scores),
        gate="soft_fail" if capped else "pass",
        per_unit=per_unit,
        reason=(f"{len(capped)} unit(s) carry an invalid or mislabeled IRI; their mapping "
                "scores are capped at 1" if capped else "every non-proposed IRI exists in its "
                "claimed branch"),
        details={"tags_checked": checked, "branch_unclaimed": unclaimed, "capped_units": capped},
    )


# ── RUB-EXTRACT-05 ────────────────────────────────────────────────────────


def _band(score: float) -> int:
    if score > SNIPPET_EXACT_BAND:
        return 3
    if score >= MIN_ANCHOR_SCORE:
        return 2
    return 0


@dataclass(frozen=True)
class AnchorAssessment:
    """How one unit's anchor verified: the score, the route, and the passage."""

    score: int
    route: str
    match: float
    passage: str  # the verified source passage ("" when nothing verified)
    issues: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"score": self.score, "route": self.route, "match": round(self.match, 4),
                "issues": list(self.issues)}


@lru_cache(maxsize=8192)
def assess_anchor(unit: RubricUnit) -> AnchorAssessment:
    """RUB-EXTRACT-05's [DET] check for one unit (see the module docstring).

    Cached: -05 and -09 both read it, and units are immutable."""
    claim = unit.anchor
    source = claim.source_text
    if source is None:
        return AnchorAssessment(0, "none", 0.0, "", (claim.source_error or "source_missing",))

    issues: list[str] = []
    candidates: list[AnchorAssessment] = []
    slice_text = ""
    span_ok = False
    if claim.span is not None:
        start, end = claim.span
        if 0 <= start < end <= len(source) and source[start:end].strip():
            span_ok = True
            slice_text = source[start:end]
        else:
            issues.append("span_out_of_bounds_or_empty")

    quotes: list[tuple[str, bool]] = []  # (quote, is_pipeline_snippet)
    if claim.snippet.strip():
        quotes.append((claim.snippet, True))
    if claim.text_as_quote.strip() and not claim.snippet.strip():
        quotes.append((claim.text_as_quote, False))
    if not quotes:
        issues.append("no_quote")

    for quote, is_snippet in quotes:
        at_span = span_ok and slice_text.strip() == quote.strip()
        if at_span and is_snippet and claim.stored_score is not None:
            # A pipeline snippet equals its slice by construction, verified or not: it is
            # only as good as the anchor score the pipeline recorded for it.
            stored = max(0.0, min(1.0, float(claim.stored_score)))
            consistent = bool(claim.stored_verified) == (stored >= MIN_ANCHOR_SCORE)
            if not consistent:
                issues.append("stored_anchor_inconsistent")
                stored = 0.0
            elif stored < MIN_ANCHOR_SCORE:
                issues.append(f"stored_anchor_unverified:{stored:.4f}")
            band = 3 if stored >= 1.0 else _band(stored)
            candidates.append(AnchorAssessment(band, "span", stored,
                                               slice_text if band else "", ()))
            continue
        if at_span:
            candidates.append(AnchorAssessment(3, "span", 1.0, slice_text, ()))
            continue
        found = resolve_anchor(quote, source)
        match = found.score if found is not None else 0.0
        band = _band(match)
        if band and claim.span is not None:
            # The quote verifies, but not where the span points: "span loose".
            issues.append("span_does_not_slice_quote")
            band = min(band, 2)
        if not band:
            issues.append(f"quote_below_bar:{match:.4f}")
        candidates.append(AnchorAssessment(
            band, "snippet" if is_snippet else "unit_text", match,
            found.snippet if (band and found is not None) else "", (),
        ))

    best = max(candidates, key=lambda a: (a.score, a.match), default=None)
    if best is None:
        return AnchorAssessment(0, "none", 0.0, "", tuple(issues))
    if best.score and claim.claim.strip():
        from folio_insights.minting.support import check_support

        support = check_support(claim.claim, best.passage)
        if not support.supported:
            failed = []
            if support.missing_classes:
                failed.append("unsupported_specifics:" + ",".join(support.missing_classes))
            if not support.lexical_ok:
                failed.append(f"claim_unsupported:{support.ratio:.4f}")
            return AnchorAssessment(0, best.route, best.match, best.passage,
                                    (*issues, *failed))
    return AnchorAssessment(best.score, best.route, best.match, best.passage,
                            tuple(issues) if best.score < 3 else ())


def source_anchoring(artifact: RubricArtifact) -> CriterionResult:
    """RUB-EXTRACT-05 [DET]: every unit carries a verifying anchor (the gate)."""
    cid = "RUB-EXTRACT-05"
    if not artifact.has_sources and artifact.kind == "unit_run":
        return not_computed(cid, "no source directory supplied (--sources DIR)")
    if not artifact.units:
        return not_computed(cid, "the artifact has no units")
    unresolved = sorted(u.id for u in artifact.units if u.anchor.source_text is None)
    if artifact.kind == "shard_corpus" and unresolved:
        # A shard whose source cannot be read cannot be checked; never pass it.
        return not_computed(
            cid,
            f"{len(unresolved)} shard source(s) could not be resolved; supply --sources DIR",
            unresolved=unresolved,
        )
    per_unit = {u.id: assess_anchor(u).as_dict() for u in artifact.units}
    failing = sorted(uid for uid, entry in per_unit.items() if entry["score"] == 0)
    return CriterionResult(
        id=cid,
        computed=True,
        score=_mean([entry["score"] for entry in per_unit.values()]),
        gate="fail" if failing else "pass",
        per_unit=per_unit,
        reason=(f"{len(failing)} unit(s) carry no verifying anchor" if failing
                else "every unit carries a verifying anchor"),
        details={
            "failing_units": failing,
            "threshold": MIN_ANCHOR_SCORE,
            "llm_component": "not_scored: the anchored passage supporting the claim is "
                             "RUB-EXTRACT-05's [LLM] half",
        },
    )


# ── RUB-EXTRACT-09 ────────────────────────────────────────────────────────


def _precision_band(flagged: int, total: int) -> int:
    if flagged == 0:
        return 3
    if flagged == 1:
        return 2
    return 1 if flagged / total <= NOISY_SHARE else 0


def precision_no_padding(artifact: RubricArtifact) -> CriterionResult:
    """RUB-EXTRACT-09 [DET]: content_hash dedup held and no headings-as-units."""
    cid = "RUB-EXTRACT-09"
    if not artifact.units:
        return not_computed(cid, "the artifact has no units")
    seen: dict[str, str] = {}
    per_unit: dict[str, dict[str, Any]] = {}
    chapters: dict[str, list[str]] = {}
    for unit in artifact.units:
        flags: list[str] = []
        if unit.content_hash in seen:
            flags.append(f"duplicate_of:{seen[unit.content_hash]}")
        else:
            seen[unit.content_hash] = unit.id
        if is_structural(unit.text):
            flags.append("heading_as_unit")
        elif unit.anchor.source_text is not None:
            passage = assess_anchor(unit).passage
            if passage and is_structural(passage):
                flags.append("anchored_to_heading")
        per_unit[unit.id] = {"flags": flags, "chapter": unit.chapter}
        chapters.setdefault(unit.chapter, []).append(unit.id)
    per_chapter: dict[str, dict[str, Any]] = {}
    for chapter, ids in chapters.items():
        flagged = sum(1 for uid in ids if per_unit[uid]["flags"])
        per_chapter[chapter] = {"units": len(ids), "flagged": flagged,
                                "score": _precision_band(flagged, len(ids))}
    scores = [entry["score"] for entry in per_chapter.values()]
    flagged_total = sum(entry["flagged"] for entry in per_chapter.values())
    return CriterionResult(
        id=cid,
        computed=True,
        score=_mean(scores),
        gate=None,
        per_unit=per_unit,
        reason=(f"{flagged_total} duplicate or heading unit(s)" if flagged_total
                else "no duplicates and no headings-as-units"),
        details={
            "per_chapter": per_chapter,
            "llm_component": "not_scored: the filler spot-check is RUB-EXTRACT-09's [LLM] half",
        },
    )


# ── RUB-EXTRACT-10 / -11 ──────────────────────────────────────────────────

_NO_RDF = ("a unit run has no RDF; SHACL criteria are scored on a shard corpus "
           "(folio-insights rubric score <corpus>)")


def shape_conformance(artifact: RubricArtifact) -> CriterionResult:
    """RUB-EXTRACT-10: the corpus conforms to the full SHACL suite."""
    cid = "RUB-EXTRACT-10"
    if artifact.kind != "shard_corpus":
        return not_computed(cid, _NO_RDF)
    if artifact.shacl is None:
        return not_computed(cid, "no SHACL validation result for this corpus")
    v = artifact.shacl
    score = 0 if not v.conforms else (3 if v.warnings == 0 else 2)
    return CriterionResult(
        id=cid,
        computed=True,
        score=float(score),
        gate="pass" if v.conforms else "fail",
        reason=(f"{v.violations} SHACL violation(s)" if not v.conforms
                else ("conforms" if v.warnings == 0 else f"conforms with {v.warnings} warning(s)")),
        details={"violations": v.violations, "warnings": v.warnings,
                 "suite_digest": v.suite_digest, "shards": v.shards, "events": v.events,
                 "results": [dict(r) for r in v.results[:50]]},
    )


def structural_integrity(artifact: RubricArtifact) -> CriterionResult:
    """RUB-EXTRACT-11: IRI uniqueness, referential integrity, namespace consistency."""
    cid = "RUB-EXTRACT-11"
    if artifact.kind != "shard_corpus":
        return not_computed(cid, _NO_RDF)
    if not artifact.structural:
        return not_computed(cid, "no structural check results for this corpus")
    statuses = {c.name: c.status for c in artifact.structural}
    failed = sorted(name for name, status in statuses.items() if status == "FAIL")
    warned = sorted(name for name, status in statuses.items() if status == "WARN")
    score = 0 if failed else (3 if not warned else 2)
    return CriterionResult(
        id=cid,
        computed=True,
        score=float(score),
        gate="fail" if failed else "pass",
        reason=(f"FAIL: {', '.join(failed)}" if failed
                else (f"WARN: {', '.join(warned)}" if warned else "all checks PASS")),
        details={"checks": [
            {"name": c.name, "status": c.status, "details": c.details,
             "messages": list(c.messages[:50])}
            for c in artifact.structural
        ]},
    )


def compute_det(artifact: RubricArtifact, oracle: IriOracle | None) -> dict[str, CriterionResult]:
    """All five [DET] criteria, keyed by ID."""
    return {
        "RUB-EXTRACT-03": iri_validity(artifact, oracle),
        "RUB-EXTRACT-05": source_anchoring(artifact),
        "RUB-EXTRACT-09": precision_no_padding(artifact),
        "RUB-EXTRACT-10": shape_conformance(artifact),
        "RUB-EXTRACT-11": structural_integrity(artifact),
    }


__all__ = [
    "CATALOGUE",
    "DET_CRITERIA",
    "JUDGED_CRITERIA",
    "MAPPING_CRITERIA",
    "NOISY_SHARE",
    "RUBRIC_DOC",
    "RUBRIC_ID",
    "RUBRIC_VERSION",
    "SNIPPET_EXACT_BAND",
    "SPECS",
    "AnchorAssessment",
    "CriterionResult",
    "CriterionSpec",
    "assess_anchor",
    "compute_det",
    "iri_validity",
    "not_computed",
    "precision_no_padding",
    "shape_conformance",
    "source_anchoring",
    "structural_integrity",
]
