"""The RUB-EXTRACT harness: deterministic scores, judged scores, gates and the pass rule.

``score(artifact, oracle, judged)`` returns a ``RubricReport`` that lists all 14 criteria
of ``docs/rubrics/extraction-quality-v1.md`` in catalogue order. Each one is:

* ``computed`` - its [DET] part ran here (-03, -05, -09, -10, -11);
* ``computed+judged`` - its [DET] part ran and a judged score for its LLM half was
  supplied (-05, -09 only); the effective score is the lower of the two, so a judge can
  only lower a deterministic result, never raise it;
* ``judged`` - an LLM/MCP/taste criterion whose score came from the judged file;
* ``not_scored`` - nothing computed it and no judge scored it. Its score and gate are
  ``None``: the harness never reports a pass for a criterion it did not compute.

A judged score for a [DET] criterion whose deterministic part did not run is recorded
but does not make the criterion scored.

**Gates** (rubric §1): RUB-EXTRACT-06 (fabrication, judged) and -05 (anchoring) fail on
any unit at 0; -10 and -11 fail on SHACL / structural failures; -03 is gate-soft: a unit
with an invalid or mislabeled IRI has its mapping-dimension scores (-01, -02, -04) capped
at 1. With per-unit judged scores the cap applies unit by unit; with an aggregate judged
score it applies as if that score were uniform across units
(``(n - k) * s + k * min(s, 1)`` over ``n`` units, ``k`` capped). The -06 gate needs
per-unit scores or an explicit ``"gate"`` from the judge, because a mean can hide one
fabricated unit.

**Pass rule** (rubric §0.5 item 2, §1): ``publishable`` is true only when every one of the
14 criteria has a score (all five [DET] criteria computed, judged scores for the other
nine), the hard gates -05, -06, -10 and -11 pass, completeness RUB-EXTRACT-08 is at least
2, and the weighted score normalized to 0-1 (sum of weight * score / 3 over the §3
weights, plus the RUB-EXTRACT-04 proposed-class bonus of +0.05 per genuine gap, capped at
+0.10) is at least 0.80. Otherwise it is false and ``reasons`` lists every unmet
condition. The bonus never offsets a gate. ``partial_normalized`` reports the same ratio
over only the criteria that have scores, for progress; it never decides publication.

Judged-scores file (``--judged``)::

    {"format": 1, "rubric_version": "v1.0", "judge": "who / how",
     "scores": {"RUB-EXTRACT-01": 2.6,
                "RUB-EXTRACT-06": {"per_unit": {"<unit id>": 3, ...}},
                "RUB-EXTRACT-08": {"score": 2, "gate": "pass"}},
     "bonus": {"genuine_proposed_gaps": 1}}

``per_unit`` must cover every unit of the artifact; ``score`` defaults to its mean.
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
BONUS_PER_GAP = 0.05
BONUS_CAP = 0.10
JUDGED_FORMAT = 1


class JudgedScoresError(ValueError):
    """A judged-scores file is malformed or does not fit the artifact."""


@dataclass(frozen=True)
class JudgedEntry:
    score: float
    per_unit: Mapping[str, float] | None = None
    gate: str | None = None


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
            per_unit_raw = value.get("per_unit")
            per_unit = None
            if per_unit_raw is not None:
                if not isinstance(per_unit_raw, Mapping) or not per_unit_raw:
                    raise JudgedScoresError(f"{where}: {cid}.per_unit must be a non-empty object")
                per_unit = {str(k): _number(v, f"{where}: {cid}.per_unit[{k}]")
                            for k, v in per_unit_raw.items()}
            if "score" in value:
                score = _number(value["score"], f"{where}: {cid}.score")
            elif per_unit is not None:
                score = round(sum(per_unit.values()) / len(per_unit), 6)
            else:
                raise JudgedScoresError(f"{where}: {cid} needs a 'score' or 'per_unit'")
            gate = value.get("gate")
            if gate is not None and gate not in ("pass", "fail"):
                raise JudgedScoresError(f"{where}: {cid}.gate must be 'pass' or 'fail'")
            scores[cid] = JudgedEntry(score=score, per_unit=per_unit, gate=gate)
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
    gate: str | None
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
                             "per_unit": dict(self.judged.per_unit or {})}
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
                         "units": self.units},
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
    if entry.per_unit is not None:
        return "fail" if any(v == 0 for v in entry.per_unit.values()) else "pass"
    if entry.gate is not None:
        return entry.gate
    if entry.score == 0:
        return "fail"
    return None  # an aggregate alone cannot prove no unit is at 0


def _check_units(entry: JudgedEntry, cid: str, unit_ids: set[str]) -> None:
    if entry.per_unit is None:
        return
    given = set(entry.per_unit)
    if given != unit_ids:
        missing, extra = sorted(unit_ids - given), sorted(given - unit_ids)
        raise JudgedScoresError(
            f"{cid}.per_unit must cover exactly the artifact's units "
            f"(missing {missing[:5]}{'...' if len(missing) > 5 else ''}, "
            f"unknown {extra[:5]}{'...' if len(extra) > 5 else ''})"
        )


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
    for cid, entry in judged_scores.items():
        _check_units(entry, cid, unit_ids)

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
            if entry is not None:
                status = "computed+judged"
                value = min(value, entry.score) if value is not None else value
                if spec.gate == "gate" and _judged_gate(entry) == "fail":
                    gate = "fail"
                    notes.append("the judge failed at least one unit")
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
        elif state != "pass":
            reasons.append(f"gate {cid} not green ({'not scored' if by_id[cid].score is None else 'unknown'})")
    completeness = by_id[COMPLETENESS_ID].score
    if completeness is not None and completeness < COMPLETENESS_FLOOR:
        reasons.append(f"{COMPLETENESS_ID} {completeness:g} is below the completeness floor "
                       f"{COMPLETENESS_FLOOR:g}")
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
    )


__all__ = [
    "BONUS_CAP",
    "BONUS_PER_GAP",
    "COMPLETENESS_FLOOR",
    "HARD_GATES",
    "JUDGEABLE_DET",
    "PASS_THRESHOLD",
    "CriterionReport",
    "JudgedEntry",
    "JudgedScores",
    "JudgedScoresError",
    "RubricReport",
    "load_judged",
    "parse_judged",
    "score",
]
