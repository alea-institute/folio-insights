"""The books gold set: synthetic cases over real books-UAT failure modes (plan KTD5, R8).

``tests/rubric/fixtures/books_gold/<case>/`` holds one case per failure mode the books
UAT found (``docs/evidence/books/DE-RISK-FINDINGS.md``, ``pack.json``):

* ``source/`` - invented, generic litigation-practice prose (never book text);
* ``extraction.json`` - synthetic units in the pipeline's ``extraction.json`` shape that
  reproduce the failure;
* ``expected.json`` - the scores, gates and statuses the harness must produce;
* ``judged.json`` (optional) - judged scores scored alongside the deterministic ones.

Fixture texts stay short (under eight words a unit) and carry no ``source_snippet``
values, so the committed files pass ``scripts/check_exclusions.py``, whose content scan
treats any snippet value and any long ``text`` value as possible book material. Snippet
behaviour is covered by tests that build units in code.

``run_gold`` scores every case with the frozen fixture oracle
(``tests/rubric/fixtures/folio_oracle.json``) and compares the result with
``expected.json``; any difference is *drift*. It also runs the mapping-gold check over
the human corrections in ``docs/evidence/books/mapping-corrections.gold.json``: the
share of corrections where the pipeline's mapping already agrees with the reviewer's
correct IRI, compared with the recorded baseline
(``tests/rubric/fixtures/mapping_gold_expected.json``). ``folio-insights rubric gold``
exits non-zero on any drift, and so does the CI test that calls ``run_gold``.

``expected.json`` (format 1)::

    {"format": 1, "case": "...", "covers": ["EP-INSIGHTS-BOOKS-007"],
     "failure_mode": "...", "publishable": false,
     "criteria": {"RUB-EXTRACT-05": {"status": "computed", "score": 0.0, "gate": "fail",
                                     "per_unit": {"<unit id>": 0}}, ...}}

A ``per_unit`` value is a unit's score, or for RUB-EXTRACT-09 its list of flags.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from folio_insights.rubric.adapters import UnitRun
from folio_insights.rubric.harness import RubricReport, load_judged, score
from folio_insights.rubric.oracle import FixtureOracle, IriOracle

GOLD_FORMAT = 1
SCORE_TOLERANCE = 1e-6


def repo_root() -> Path:
    """The checkout this module runs from (``src/folio_insights/rubric`` -> root)."""
    return Path(__file__).resolve().parents[3]


DEFAULT_GOLD_DIR = Path("tests/rubric/fixtures/books_gold")
DEFAULT_ORACLE = Path("tests/rubric/fixtures/folio_oracle.json")
DEFAULT_CORRECTIONS = Path("docs/evidence/books/mapping-corrections.gold.json")
DEFAULT_MAPPING_EXPECTED = Path("tests/rubric/fixtures/mapping_gold_expected.json")


class GoldSetError(ValueError):
    """The gold set is missing or malformed."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GoldSetError(f"gold file not found: {path}") from exc
    except ValueError as exc:
        raise GoldSetError(f"gold file is not valid JSON: {path}: {exc}") from exc


def case_dirs(gold_dir: Path) -> list[Path]:
    if not gold_dir.is_dir():
        raise GoldSetError(f"gold set directory not found: {gold_dir}")
    cases = sorted(p for p in gold_dir.iterdir() if (p / "expected.json").is_file())
    if not cases:
        raise GoldSetError(f"no gold cases (directories with expected.json) in {gold_dir}")
    return cases


def score_case(case_dir: Path, oracle: IriOracle | None) -> RubricReport:
    artifact = UnitRun.load(case_dir / "extraction.json", sources_dir=case_dir / "source")
    judged_path = case_dir / "judged.json"
    judged = load_judged(judged_path) if judged_path.is_file() else None
    return score(artifact, oracle=oracle, judged=judged)


def _close(a: float | None, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= SCORE_TOLERANCE


def compare_case(report: RubricReport, expected: Mapping[str, Any], *, case: str) -> list[str]:
    """Every difference between a case's report and its ``expected.json``."""
    drift: list[str] = []
    if expected.get("format") != GOLD_FORMAT:
        return [f"{case}: expected.json must have format {GOLD_FORMAT}"]
    if "publishable" in expected and report.publishable != expected["publishable"]:
        drift.append(f"{case}: publishable {report.publishable} != expected {expected['publishable']}")
    criteria = expected.get("criteria", {})
    missing = sorted({c.id for c in report.criteria} - set(criteria))
    if missing:
        drift.append(f"{case}: expected.json does not pin {', '.join(missing)}")
    for cid, want in criteria.items():
        try:
            got = report.criterion(cid)
        except KeyError:
            drift.append(f"{case}: unknown criterion {cid}")
            continue
        if "status" in want and got.status != want["status"]:
            drift.append(f"{case}: {cid} status {got.status} != expected {want['status']}")
        if "score" in want and not _close(got.score, want["score"]):
            drift.append(f"{case}: {cid} score {got.score} != expected {want['score']}")
        if "gate" in want and got.gate != want["gate"]:
            drift.append(f"{case}: {cid} gate {got.gate} != expected {want['gate']}")
        for uid, value in (want.get("per_unit") or {}).items():
            entry = (got.det.per_unit.get(uid) if got.det is not None else None) or {}
            actual = sorted(entry.get("flags", [])) if isinstance(value, list) else entry.get("score")
            wanted = sorted(value) if isinstance(value, list) else value
            if actual != wanted:
                drift.append(f"{case}: {cid} unit {uid} {actual} != expected {wanted}")
    return drift


def mapping_gold(corrections_path: Path, oracle: IriOracle | None = None) -> dict[str, Any]:
    """Agreement between the pipeline's mappings and the reviewer's correct IRIs.

    A correction agrees when the pipeline's IRI equals the correct IRI or, for a mapping
    recorded only by label, when the labels match (case-insensitively). With an oracle,
    each correct IRI is also checked to resolve, so a typo in the gold file is caught.
    """
    data = _load_json(corrections_path)
    corrections = data.get("corrections") if isinstance(data, Mapping) else None
    if not isinstance(corrections, list) or not corrections:
        raise GoldSetError(f"{corrections_path}: expected a non-empty 'corrections' list")
    cases: list[dict[str, Any]] = []
    for item in corrections:
        pipeline = item.get("pipeline_mapping", {}) or {}
        correct = item.get("correct_mapping", {}) or {}
        correct_iri = str(correct.get("iri", "") or "")
        if not correct_iri:
            raise GoldSetError(f"{corrections_path}: correction {item.get('ep_id')} has no correct IRI")
        p_iri = str(pipeline.get("iri", "") or "")
        p_label = str(pipeline.get("label", "") or "")
        agree = (p_iri == correct_iri) if p_iri else (
            bool(p_label) and p_label.casefold() == str(correct.get("label", "")).casefold()
        )
        case: dict[str, Any] = {
            "ep_id": item.get("ep_id"),
            "pipeline_iri": p_iri or None,
            "pipeline_label": p_label or None,
            "pipeline_branch": pipeline.get("branch_reported"),
            "correct_iri": correct_iri,
            "agree": agree,
        }
        if oracle is not None:
            case["correct_iri_resolves"] = oracle.exists(correct_iri)
            case["correct_branches"] = list(oracle.branch_of(correct_iri))
        cases.append(case)
    agree_n = sum(1 for c in cases if c["agree"])
    out: dict[str, Any] = {
        "corrections": len(cases),
        "agree": agree_n,
        "agreement_rate": round(agree_n / len(cases), 6),
        "cases": cases,
    }
    if oracle is not None:
        out["correct_iri_resolves"] = sum(1 for c in cases if c["correct_iri_resolves"])
    return out


def compare_mapping(result: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    drift: list[str] = []
    for key in ("corrections", "agree", "agreement_rate", "correct_iri_resolves"):
        if key not in expected:
            continue
        got = result.get(key)
        same = _close(got, expected[key]) if isinstance(expected[key], float) else got == expected[key]
        if not same:
            drift.append(f"mapping-gold: {key} {got} != expected baseline {expected[key]}")
    return drift


@dataclass
class CaseOutcome:
    case: str
    report: RubricReport
    drift: list[str]


@dataclass
class GoldRun:
    cases: list[CaseOutcome] = field(default_factory=list)
    mapping: dict[str, Any] = field(default_factory=dict)
    mapping_drift: list[str] = field(default_factory=list)

    @property
    def drift(self) -> list[str]:
        return [d for c in self.cases for d in c.drift] + self.mapping_drift

    @property
    def ok(self) -> bool:
        return not self.drift

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "drift": self.drift,
            "cases": [
                {"case": c.case, "publishable": c.report.publishable,
                 "drift": c.drift, "report": c.report.as_dict()}
                for c in self.cases
            ],
            "mapping_gold": self.mapping,
        }


def run_gold(
    gold_dir: Path | None = None,
    *,
    oracle_path: Path | None = None,
    corrections_path: Path | None = None,
    mapping_expected_path: Path | None = None,
) -> GoldRun:
    """Score every gold case and the mapping-gold check; collect all drift."""
    root = repo_root()
    gold_dir = gold_dir or root / DEFAULT_GOLD_DIR
    oracle = FixtureOracle.from_file(oracle_path or root / DEFAULT_ORACLE)
    run = GoldRun()
    for case_dir in case_dirs(gold_dir):
        expected = _load_json(case_dir / "expected.json")
        report = score_case(case_dir, oracle)
        run.cases.append(CaseOutcome(case_dir.name, report,
                                     compare_case(report, expected, case=case_dir.name)))
    run.mapping = mapping_gold(corrections_path or root / DEFAULT_CORRECTIONS, oracle)
    run.mapping_drift = compare_mapping(
        run.mapping, _load_json(mapping_expected_path or root / DEFAULT_MAPPING_EXPECTED)
    )
    return run


__all__ = [
    "DEFAULT_CORRECTIONS",
    "DEFAULT_GOLD_DIR",
    "DEFAULT_MAPPING_EXPECTED",
    "DEFAULT_ORACLE",
    "GOLD_FORMAT",
    "CaseOutcome",
    "GoldRun",
    "GoldSetError",
    "case_dirs",
    "compare_case",
    "compare_mapping",
    "mapping_gold",
    "repo_root",
    "run_gold",
    "score_case",
]
