"""The RUB-EXTRACT harness: deterministic scores, judged scores, gates and the pass rule.

``score(artifact, oracle, judged)`` returns a ``RubricReport`` that lists all 14 criteria
of ``docs/rubrics/extraction-quality-v1.md`` in catalogue order. Each one is:

* ``computed`` - its [DET] part ran here (-03, -05, -09, -10, -11);
* ``computed+judged`` - its [DET] part ran and a judged score for its LLM half was
  supplied (-05, -09 only); the effective score is the lower of the two, unit by unit
  (-05) or chapter by chapter (-09) when the judge graded at that granularity, so a judge
  can only lower a deterministic result, never raise it;
* ``judged`` - an LLM/MCP/taste criterion whose score came from the judged file;
* ``not_scored`` - nothing computed it and no judge scored it. Its score and gate are
  ``None``: the harness never reports a pass for a criterion it did not compute.

A judged score for a [DET] criterion whose deterministic part did not run is recorded
but does not make the criterion scored.

**Gates** (rubric §1): RUB-EXTRACT-06 (fabrication, judged) and -05 (anchoring) fail on
any unit at 0, and on an explicit judged ``"gate": "fail"``, which always wins: per-unit
grades above 0 never overwrite a judge's story-level fail (a fabrication is "never
averaged away", rubric §0.5). -10 and -11 fail on SHACL / structural failures. -03 is
gate-soft: a unit with an invalid or mislabeled IRI has its mapping-dimension scores
(-01, -02, -04) capped at 1. With per-unit judged scores the cap applies unit by unit;
with an aggregate judged score it applies as if that score were uniform across units
(``(n - k) * s + k * min(s, 1)`` over ``n`` units, ``k`` capped). The -06 gate needs
per-unit scores or an explicit ``"gate"`` from the judge, because a mean can hide one
fabricated unit.

RUB-EXTRACT-05 is [DET]+[LLM]: the deterministic half proves each unit has a verifying
anchor; the judged half proves the anchored passage *supports the claim*. A mechanical
pass alone leaves the gate ``pending_llm`` (the criterion is still ``computed`` with its
deterministic score) and the story is not publishable until a judge supplies -05
per-unit grades or an explicit gate. A mechanical fail is final.

**Pass rule** (rubric §0.5 item 2, §1): ``publishable`` is true only when every one of the
14 criteria has a score (all five [DET] criteria computed, judged scores for the other
nine), the hard gates -05 (both halves), -06, -10 and -11 pass, completeness
RUB-EXTRACT-08 is at least 2 in every chapter, and the weighted score normalized to 0-1
(sum of weight * score / 3 over the §3 weights, plus the RUB-EXTRACT-04 proposed-class
bonus of +0.05 per genuine gap, capped at +0.10) is at least 0.80. Otherwise it is false
and ``reasons`` lists every unmet condition. The bonus never offsets a gate.
``partial_normalized`` reports the same ratio over only the criteria that have scores,
for progress; it never decides publication.

**Completeness floor per chapter.** -08 is a per-chapter criterion, so the floor applies
to each chapter: one chapter below 2 fails the story even when the cross-chapter mean
clears it (the mean is used only for the weighted score). With ``per_chapter`` grades the
floor is checked on every chapter; an aggregate -08 score is accepted as the chapter
score of a single-chapter artifact, but over several chapters it cannot show each one
clears the floor, so the floor is reported unknown (not publishable) unless the
aggregate itself is below 2.

Judged-scores file (``--judged``)::

    {"format": 1, "rubric_version": "v1.0", "judge": "who / how",
     "scores": {"RUB-EXTRACT-01": 2.6,
                "RUB-EXTRACT-05": {"per_unit": {"<unit id>": 3, ...}},
                "RUB-EXTRACT-06": {"per_unit": {"<unit id>": 3, ...}, "gate": "pass"},
                "RUB-EXTRACT-08": {"per_chapter": {"<chapter id>": 2, ...}},
                "RUB-EXTRACT-09": {"per_chapter": {"<chapter id>": 3, ...}}},
     "bonus": {"genuine_proposed_gaps": 1}}

* An aggregate score (a bare number, or ``"score"``) is a mean on the 0-3 scale and may
  be fractional.
* ``per_unit`` (unit-scope criteria) and ``per_chapter`` (chapter-scope criteria -08 and
  -09 only) hold *grades*: integers 0, 1, 2 or 3 on the rubric scale (``3.0`` is
  accepted; ``0.3`` or ``2.5`` is invalid judged input, never rounded). ``per_unit``
  must cover exactly the artifact's units and ``per_chapter`` exactly its chapters;
  ``score`` defaults to their mean.
* Chapter IDs are the ``RubricUnit.chapter`` values, listed in the report as
  ``artifact.chapters``: a unit run's ``source_file`` per unit, a shard corpus's
  ``source_uri`` per shard.
* ``"gate"`` (``"pass"`` / ``"fail"``) is an explicit story-level verdict for a gate
  criterion; ``"fail"`` always wins.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from folio_insights.rubric.adapters import RubricArtifact
from folio_insights.rubric.criteria import (
    CATALOGUE,
    DET_CRITERIA,
    JUDGED_CRITERIA,
    MAPPING_CRITERIA,
    RUBRIC_DOC,
    RUBRIC_ID,
    RUBRIC_VERSION,
    SPECS,
    CriterionResult,
    compute_det,
)
from folio_insights.rubric.oracle import IriOracle

PASS_THRESHOLD = 0.80
COMPLETENESS_FLOOR = 2.0
COMPLETENESS_ID = "RUB-EXTRACT-08"
FABRICATION_ID = "RUB-EXTRACT-06"
HARD_GATES: tuple[str, ...] = ("RUB-EXTRACT-05", "RUB-EXTRACT-06", "RUB-EXTRACT-10", "RUB-EXTRACT-11")
# [DET] criteria that also have an LLM half a judge may score (and so only lower).
JUDGEABLE_DET: tuple[str, ...] = ("RUB-EXTRACT-05", "RUB-EXTRACT-09")
# [DET] gates whose judged [LLM] half must be supplied before the gate can be green.
LLM_GATE_HALVES: Mapping[str, str] = {
    "RUB-EXTRACT-05": "the anchored passage supports the claim",
}
PENDING_LLM = "pending_llm"
BONUS_PER_GAP = 0.05
BONUS_CAP = 0.10
JUDGED_FORMAT = 1


class JudgedScoresError(ValueError):
    """A judged-scores file is malformed or does not fit the artifact."""


@dataclass(frozen=True)
class JudgedEntry:
    """One criterion's judged score: an aggregate mean, optional integer grades per unit
    (unit-scope criteria) or per chapter (chapter-scope criteria), and an optional
    explicit story-level gate verdict."""

    score: float
    per_unit: Mapping[str, float] | None = None
    gate: str | None = None
    per_chapter: Mapping[str, float] | None = None


@dataclass(frozen=True)
class JudgedScores:
    scores: Mapping[str, JudgedEntry]
    judge: str = ""
    genuine_proposed_gaps: int = 0


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JudgedScoresError(f"{where}: expected a number 0-3, got {value!r}")
    if not 0 <= value <= 3:
        raise JudgedScoresError(f"{where}: score {value} is outside 0-3")
    return float(value)


def _grade(value: Any, where: str) -> float:
    """A per-unit / per-chapter grade: an integer 0-3 on the rubric scale."""
    integral = isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if isinstance(value, bool) or not integral or not 0 <= value <= 3:
        raise JudgedScoresError(
            f"{where}: expected an integer rubric grade 0, 1, 2 or 3, got {value!r} "
            "(per-unit and per-chapter scores are grades, not means)"
        )
    return float(value)


def _grades(value: Any, cid: str, key: str, where: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or not value:
        raise JudgedScoresError(f"{where}: {cid}.{key} must be a non-empty object")
    return {str(k): _grade(v, f"{where}: {cid}.{key}[{k}]") for k, v in value.items()}


def parse_judged(data: Any, *, where: str = "judged") -> JudgedScores:
    """Validate a judged-scores object (see the module docstring)."""
    if not isinstance(data, Mapping) or data.get("format") != JUDGED_FORMAT:
        raise JudgedScoresError(f"{where}: expected an object with format {JUDGED_FORMAT}")
    version = data.get("rubric_version", RUBRIC_VERSION)
    if version != RUBRIC_VERSION:
        raise JudgedScoresError(
            f"{where}: judged against rubric {version!r}, this harness scores {RUBRIC_VERSION!r}"
        )
    raw = data.get("scores", {})
    if not isinstance(raw, Mapping):
        raise JudgedScoresError(f"{where}: 'scores' must be an object keyed by criterion ID")
    allowed = set(JUDGED_CRITERIA) | set(JUDGEABLE_DET)
    scores: dict[str, JudgedEntry] = {}
    for cid, value in raw.items():
        if cid not in allowed:
            known = cid in DET_CRITERIA
            raise JudgedScoresError(
                f"{where}: {cid} " + ("is purely deterministic and cannot be judged"
                                      if known else "is not a RUB-EXTRACT v1.0 criterion")
            )
        if isinstance(value, Mapping):
            scope = SPECS[cid].scope
            per_unit = per_chapter = None
            if value.get("per_unit") is not None:
                if scope != "unit":
                    raise JudgedScoresError(
                        f"{where}: {cid} is a per-chapter criterion; grade it with "
                        "'per_chapter' (chapter id -> 0-3), not 'per_unit'"
                    )
                per_unit = _grades(value["per_unit"], cid, "per_unit", where)
            if value.get("per_chapter") is not None:
                if scope != "chapter":
                    raise JudgedScoresError(
                        f"{where}: {cid} is a per-unit criterion; grade it with "
                        "'per_unit' (unit id -> 0-3), not 'per_chapter'"
                    )
                per_chapter = _grades(value["per_chapter"], cid, "per_chapter", where)
            grades = per_unit if per_unit is not None else per_chapter
            if "score" in value:
                score = _number(value["score"], f"{where}: {cid}.score")
            elif grades is not None:
                score = round(sum(grades.values()) / len(grades), 6)
            else:
                raise JudgedScoresError(
                    f"{where}: {cid} needs a 'score', 'per_unit' or 'per_chapter'"
                )
            gate = value.get("gate")
            if gate is not None and gate not in ("pass", "fail"):
                raise JudgedScoresError(f"{where}: {cid}.gate must be 'pass' or 'fail'")
            scores[cid] = JudgedEntry(score=score, per_unit=per_unit, gate=gate,
                                      per_chapter=per_chapter)
        else:
            scores[cid] = JudgedEntry(score=_number(value, f"{where}: {cid}"))
    bonus = data.get("bonus", {}) or {}
    if not isinstance(bonus, Mapping):
        raise JudgedScoresError(f"{where}: 'bonus' must be an object")
    gaps = bonus.get("genuine_proposed_gaps", 0)
    if isinstance(gaps, bool) or not isinstance(gaps, int) or gaps < 0:
        raise JudgedScoresError(f"{where}: bonus.genuine_proposed_gaps must be a count >= 0")
    return JudgedScores(scores=scores, judge=str(data.get("judge", "")), genuine_proposed_gaps=gaps)


def load_judged(path: str | Path) -> JudgedScores:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise JudgedScoresError(f"judged-scores file not found: {path}") from exc
    except ValueError as exc:
        raise JudgedScoresError(f"judged-scores file is not valid JSON: {path}: {exc}") from exc
    return parse_judged(data, where=str(path))


@dataclass(frozen=True)
class CriterionReport:
    id: str
    title: str
    dimension: str
    judges: tuple[str, ...]
    weight: int
    gate_kind: str | None
    status: str  # computed | computed+judged | judged | not_scored
    score: float | None
    gate: str | None  # pass | fail | soft_fail | pending_llm | None
    reason: str
    det: CriterionResult | None = None
    judged: JudgedEntry | None = None
    notes: tuple[str, ...] = ()

    @property
    def scored(self) -> bool:
        return self.score is not None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "dimension": self.dimension,
            "judges": list(self.judges),
            "weight": self.weight,
            "gate_kind": self.gate_kind,
            "status": self.status,
            "score": self.score,
            "gate": self.gate,
            "reason": self.reason,
            "notes": list(self.notes),
        }
        if self.det is not None:
            out["det"] = self.det.as_dict()
        if self.judged is not None:
            out["judged"] = {"score": self.judged.score, "gate": self.judged.gate,
                             "per_unit": dict(self.judged.per_unit or {}),
                             "per_chapter": dict(self.judged.per_chapter or {})}
        return out


@dataclass(frozen=True)
class RubricReport:
    artifact_kind: str
    artifact_ref: str
    units: int
    criteria: tuple[CriterionReport, ...]
    gates: Mapping[str, str | None]
    partial_normalized: float | None
    covered_weight: int
    normalized: float | None
    bonus: float
    publishable: bool
    reasons: tuple[str, ...]
    judge: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)
    chapters: tuple[str, ...] = ()

    def criterion(self, cid: str) -> CriterionReport:
        for entry in self.criteria:
            if entry.id == cid:
                return entry
        raise KeyError(cid)

    @property
    def not_scored(self) -> tuple[str, ...]:
        return tuple(c.id for c in self.criteria if not c.scored)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rubric": {"id": RUBRIC_ID, "version": RUBRIC_VERSION, "doc": RUBRIC_DOC},
            "artifact": {"kind": self.artifact_kind, "ref": self.artifact_ref,
                         "units": self.units, "chapters": list(self.chapters)},
            "criteria": [c.as_dict() for c in self.criteria],
            "not_scored": list(self.not_scored),
            "gates": dict(self.gates),
            "weighted": {
                "partial_normalized": self.partial_normalized,
                "covered_weight": self.covered_weight,
                "normalized": self.normalized,
                "bonus": self.bonus,
                "threshold": PASS_THRESHOLD,
            },
            "publishable": self.publishable,
            "reasons": list(self.reasons),
            "judge": self.judge,
            "notes": list(self.notes),
        }

    def render_text(self) -> str:
        lines = [
            f"{RUBRIC_ID} {RUBRIC_VERSION}  {self.artifact_kind}  {self.artifact_ref}  "
            f"({self.units} units)",
            "",
            f"{'criterion':<16}{'status':<17}{'score':>6}  {'gate':<10}reason",
        ]
        for c in self.criteria:
            score = "-" if c.score is None else f"{c.score:.2f}"
            lines.append(f"{c.id:<16}{c.status:<17}{score:>6}  {(c.gate or '-'):<10}{c.reason}")
        lines.append("")
        partial = "-" if self.partial_normalized is None else f"{self.partial_normalized:.4f}"
        full = "-" if self.normalized is None else f"{self.normalized:.4f}"
        lines.append(f"weighted: normalized={full} partial={partial} "
                     f"(covered weight {self.covered_weight}/100, bonus {self.bonus:.2f})")
        lines.append(f"publishable: {str(self.publishable).lower()}")
        lines.extend(f"  - {reason}" for reason in self.reasons)
        return "\n".join(lines)


def _judged_gate(entry: JudgedEntry) -> str | None:
    """The gate a judged entry proves: an explicit 'fail' always wins, then any grade 0."""
    if entry.gate == "fail":
        return "fail"
    grades = entry.per_unit if entry.per_unit is not None else entry.per_chapter
    if grades is not None:
        return "fail" if any(v == 0 for v in grades.values()) else "pass"
    if entry.gate is not None:
        return entry.gate
    if entry.score == 0:
        return "fail"
    return None  # an aggregate alone cannot prove no unit is at 0


def _check_coverage(entry: JudgedEntry, cid: str, unit_ids: set[str],
                    chapter_ids: set[str]) -> None:
    for key, grades, ids in (("per_unit", entry.per_unit, unit_ids),
                             ("per_chapter", entry.per_chapter, chapter_ids)):
        if grades is None:
            continue
        given = set(grades)
        if given != ids:
            what = "units" if key == "per_unit" else "chapters"
            missing, extra = sorted(ids - given), sorted(given - ids)
            raise JudgedScoresError(
                f"{cid}.{key} must cover exactly the artifact's {what} "
                f"(missing {missing[:5]}{'...' if len(missing) > 5 else ''}, "
                f"unknown {extra[:5]}{'...' if len(extra) > 5 else ''})"
            )


def _combined_score(result: CriterionResult, entry: JudgedEntry) -> float | None:
    """The lower of the [DET] and judged scores, at the finest granularity both share."""
    if result.score is None:
        return None
    if entry.per_unit is not None and result.per_unit:
        values = [min(float(result.per_unit[uid]["score"]), grade)
                  for uid, grade in entry.per_unit.items() if "score" in result.per_unit[uid]]
        if len(values) == len(entry.per_unit):
            return round(sum(values) / len(values), 6)
    det_chapters = result.details.get("per_chapter") if result.details else None
    if entry.per_chapter is not None and det_chapters:
        values = [min(float(det_chapters[ch]["score"]), grade)
                  for ch, grade in entry.per_chapter.items()]
        return round(sum(values) / len(values), 6)
    return min(result.score, entry.score)


def _capped_mapping(entry: JudgedEntry, capped: set[str], n_units: int) -> tuple[float, str | None]:
    """A judged mapping score with RUB-EXTRACT-03's gate-soft cap applied."""
    if not capped:
        return entry.score, None
    if entry.per_unit is not None:
        values = [min(v, 1.0) if uid in capped else v for uid, v in entry.per_unit.items()]
        return round(sum(values) / len(values), 6), f"capped {len(capped)} unit(s) at 1 (per unit)"
    k = len(capped)
    value = ((n_units - k) * entry.score + k * min(entry.score, 1.0)) / n_units
    return round(value, 6), f"capped {k}/{n_units} unit(s) at 1 (aggregate judged score)"


def score(
    artifact: RubricArtifact,
    oracle: IriOracle | None = None,
    judged: JudgedScores | Mapping[str, Any] | None = None,
) -> RubricReport:
    """Score ``artifact`` against RUB-EXTRACT v1.0 (see the module docstring)."""
    if judged is not None and not isinstance(judged, JudgedScores):
        judged = parse_judged(judged)
    judged_scores: Mapping[str, JudgedEntry] = judged.scores if judged is not None else {}
    unit_ids = {u.id for u in artifact.units}
    chapters = tuple(dict.fromkeys(u.chapter for u in artifact.units))
    for cid, entry in judged_scores.items():
        _check_coverage(entry, cid, unit_ids, set(chapters))

    det = compute_det(artifact, oracle)
    iri = det["RUB-EXTRACT-03"]
    capped = set(iri.details.get("capped_units", [])) if iri.computed else set()

    reports: list[CriterionReport] = []
    for spec in CATALOGUE:
        result = det.get(spec.id)
        entry = judged_scores.get(spec.id)
        notes: list[str] = []
        if result is not None:
            if not result.computed:
                if entry is not None:
                    notes.append("judged score recorded, but the [DET] part did not run")
                reports.append(CriterionReport(
                    spec.id, spec.title, spec.dimension, spec.judges, spec.weight, spec.gate,
                    "not_scored", None, None, result.reason, det=result, judged=entry,
                    notes=tuple(notes),
                ))
                continue
            value, gate, status = result.score, result.gate, "computed"
            judged_gate = _judged_gate(entry) if entry is not None else None
            if entry is not None:
                status = "computed+judged"
                value = _combined_score(result, entry)
                if spec.gate == "gate" and judged_gate == "fail":
                    gate = "fail"
                    notes.append("the judge failed the gate (an explicit fail or a unit at 0)")
            half = LLM_GATE_HALVES.get(spec.id)
            if half and gate == "pass" and judged_gate != "pass":
                gate = PENDING_LLM
                notes.append(f"[LLM] half not judged ({half}); supply {spec.id} per_unit "
                             "grades or an explicit gate")
            reports.append(CriterionReport(
                spec.id, spec.title, spec.dimension, spec.judges, spec.weight, spec.gate,
                status, value, gate, result.reason, det=result, judged=entry, notes=tuple(notes),
            ))
            continue
        if entry is None:
            reports.append(CriterionReport(
                spec.id, spec.title, spec.dimension, spec.judges, spec.weight, spec.gate,
                "not_scored", None, None,
                f"{'+'.join(spec.judges)} judgment not supplied (--judged FILE)",
            ))
            continue
        value = entry.score
        if spec.id in MAPPING_CRITERIA and capped:
            value, note = _capped_mapping(entry, capped, len(artifact.units))
            if note:
                notes.append(note)
        gate = _judged_gate(entry) if spec.gate == "gate" else None
        if spec.gate == "gate" and gate is None:
            notes.append("gate unknown: supply per-unit scores or an explicit gate")
        reports.append(CriterionReport(
            spec.id, spec.title, spec.dimension, spec.judges, spec.weight, spec.gate,
            "judged", value, gate, "judged score supplied", judged=entry, notes=tuple(notes),
        ))

    by_id = {r.id: r for r in reports}
    gates: dict[str, str | None] = {cid: by_id[cid].gate for cid in HARD_GATES}
    gates["RUB-EXTRACT-03"] = by_id["RUB-EXTRACT-03"].gate

    scored = [r for r in reports if r.score is not None]
    covered = sum(r.weight for r in scored)
    partial = (round(sum(r.weight * r.score for r in scored) / (3 * covered), 6)
               if covered else None)
    complete = len(scored) == len(reports)
    bonus = min(BONUS_PER_GAP * (judged.genuine_proposed_gaps if judged else 0), BONUS_CAP)
    normalized = (round(sum(r.weight * r.score for r in scored) / 300 + bonus, 6)
                  if complete else None)

    reasons: list[str] = []
    missing = [r.id for r in reports if r.score is None]
    if missing:
        reasons.append(f"not scored: {', '.join(missing)}")
    for cid in HARD_GATES:
        state = gates[cid]
        if state == "fail":
            reasons.append(f"gate {cid} failed")
        elif state == PENDING_LLM:
            reasons.append(f"gate {cid} not green ([LLM] half not judged: "
                           f"{LLM_GATE_HALVES[cid]})")
        elif state != "pass":
            reasons.append(f"gate {cid} not green ({'not scored' if by_id[cid].score is None else 'unknown'})")
    reasons.extend(_completeness_reasons(by_id[COMPLETENESS_ID], chapters))
    if normalized is not None and normalized < PASS_THRESHOLD:
        reasons.append(f"weighted normalized {normalized:.4f} is below {PASS_THRESHOLD:.2f}")
    elif normalized is None:
        reasons.append("weighted normalized score needs every criterion scored")

    report_notes: list[str] = []
    if capped:
        report_notes.append(f"RUB-EXTRACT-03 gate-soft: mapping scores capped at 1 for "
                            f"{len(capped)} unit(s)")
    return RubricReport(
        artifact_kind=artifact.kind,
        artifact_ref=artifact.ref,
        units=len(artifact.units),
        criteria=tuple(reports),
        gates=gates,
        partial_normalized=partial,
        covered_weight=covered,
        normalized=normalized,
        bonus=bonus,
        publishable=not reasons,
        reasons=tuple(reasons),
        judge=judged.judge if judged else "",
        notes=tuple(report_notes),
        chapters=chapters,
    )


def _completeness_reasons(report: CriterionReport, chapters: tuple[str, ...]) -> list[str]:
    """The completeness floor, applied to every chapter (see the module docstring)."""
    if report.score is None:
        return []  # already reported as not scored
    entry = report.judged
    if entry is not None and entry.per_chapter is not None:
        return [f"{COMPLETENESS_ID} chapter {ch} scores {grade:g}, below the completeness "
                f"floor {COMPLETENESS_FLOOR:g}"
                for ch in chapters if (grade := entry.per_chapter[ch]) < COMPLETENESS_FLOOR]
    if report.score < COMPLETENESS_FLOOR:
        return [f"{COMPLETENESS_ID} {report.score:g} is below the completeness floor "
                f"{COMPLETENESS_FLOOR:g}"]
    if len(chapters) > 1:
        return [f"{COMPLETENESS_ID} completeness floor unknown: an aggregate score cannot "
                f"show each of the {len(chapters)} chapters is at least "
                f"{COMPLETENESS_FLOOR:g}; supply per_chapter grades"]
    return []


__all__ = [
    "BONUS_CAP",
    "BONUS_PER_GAP",
    "COMPLETENESS_FLOOR",
    "HARD_GATES",
    "JUDGEABLE_DET",
    "LLM_GATE_HALVES",
    "PASS_THRESHOLD",
    "PENDING_LLM",
    "CriterionReport",
    "JudgedEntry",
    "JudgedScores",
    "JudgedScoresError",
    "RubricReport",
    "load_judged",
    "parse_judged",
    "score",
]
