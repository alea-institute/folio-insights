"""The harness: judged scores, the -03 cap, gates and the pass rule (R7, AE3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from folio_insights.rubric.adapters import UnitRun
from folio_insights.rubric.criteria import CATALOGUE, JUDGED_CRITERIA
from folio_insights.rubric.harness import (
    JudgedScoresError,
    load_judged,
    parse_judged,
    score,
)

from tests.rubric.conftest import CROSS, RUSSIA, judged_all, tag, unit, write_run

EXACT = "Ask leading questions so the witness can only agree."
EXACT2 = "Meet the witness a week before trial and review every exhibit together."


def _artifact(tmp_path: Path, units: list[dict] | None = None, *, sources: bool = True):  # noqa: ANN202
    units = units or [
        unit("a", EXACT, tags=[tag(CROSS, "Cross-Examination of Witness", "Event")]),
        unit("b", EXACT2),
    ]
    run, src = write_run(tmp_path, units)
    return UnitRun.load(run, src if sources else None)


def _assert_never_passes_uncomputed(report) -> None:  # noqa: ANN001
    for c in report.criteria:
        if c.status == "not_scored":
            assert c.score is None and c.gate is None, c.id
        if c.det is not None and not c.det.computed:
            assert c.status == "not_scored" and c.score is None and c.gate is None, c.id


def test_lists_all_fourteen_criteria_in_catalogue_order(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    report = score(_artifact(tmp_path), oracle)
    assert [c.id for c in report.criteria] == [s.id for s in CATALOGUE]


def test_no_judged_scores_lists_judged_criteria_as_not_scored(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    report = score(_artifact(tmp_path), oracle)
    assert set(report.not_scored) == set(JUDGED_CRITERIA) | {"RUB-EXTRACT-10", "RUB-EXTRACT-11"}
    assert report.publishable is False
    assert report.normalized is None
    assert any(r.startswith("not scored:") for r in report.reasons)
    for cid in ("RUB-EXTRACT-03", "RUB-EXTRACT-05", "RUB-EXTRACT-09"):
        assert report.criterion(cid).status == "computed"
    _assert_never_passes_uncomputed(report)


def test_nothing_computable_reports_nothing_as_passed(tmp_path: Path) -> None:
    report = score(_artifact(tmp_path, sources=False), oracle=None)
    assert report.criterion("RUB-EXTRACT-03").status == "not_scored"
    assert report.criterion("RUB-EXTRACT-05").status == "not_scored"
    assert report.criterion("RUB-EXTRACT-09").status == "computed"  # needs no sources
    assert report.gates["RUB-EXTRACT-05"] is None
    assert report.publishable is False
    _assert_never_passes_uncomputed(report)


def test_full_judged_scores_on_a_unit_run_still_not_publishable(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    report = score(_artifact(tmp_path), oracle, judged_all(3, unit_ids=["a", "b"]))
    assert report.publishable is False
    assert report.not_scored == ("RUB-EXTRACT-10", "RUB-EXTRACT-11")
    assert "gate RUB-EXTRACT-10 not green (not scored)" in report.reasons
    assert report.partial_normalized == 1.0


def test_wrong_branch_caps_judged_mapping_scores_at_one(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    units = [
        unit("ok", EXACT, tags=[tag(CROSS, "Cross-Examination of Witness", "Event")]),
        unit("bad", EXACT2, tags=[tag(RUSSIA, "Rule 26(a)(1)", "Service", "llm")]),
    ]
    judged = judged_all(3, unit_ids=["ok", "bad"])
    judged["scores"]["RUB-EXTRACT-01"] = {"per_unit": {"ok": 3, "bad": 3}}
    report = score(_artifact(tmp_path, units), oracle, judged)
    assert report.gates["RUB-EXTRACT-03"] == "soft_fail"
    assert report.criterion("RUB-EXTRACT-03").score == 1.5
    assert report.criterion("RUB-EXTRACT-01").score == 2.0  # (3 + min(3, 1)) / 2
    assert report.criterion("RUB-EXTRACT-02").score == 2.0  # aggregate 3 capped for 1 of 2
    assert report.criterion("RUB-EXTRACT-04").score == 2.0
    # Non-mapping judged criteria are untouched by the cap.
    assert report.criterion("RUB-EXTRACT-07").score == 3.0
    assert any("capped" in n for n in report.criterion("RUB-EXTRACT-02").notes)


def test_judge_can_lower_a_det_criterion_but_never_raise_it(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    units = [unit("a", EXACT), unit("p", "Lead the witness on every exhibit.", span=(0, 12))]
    art = _artifact(tmp_path, units)
    lowered = score(art, oracle, {"format": 1, "scores": {"RUB-EXTRACT-09": 1}})
    assert lowered.criterion("RUB-EXTRACT-09").status == "computed+judged"
    assert lowered.criterion("RUB-EXTRACT-09").score == 1.0
    raised = score(art, oracle, {"format": 1, "scores": {"RUB-EXTRACT-05": 3}})
    assert raised.criterion("RUB-EXTRACT-05").score == 1.5  # the DET mean, not 3
    assert raised.criterion("RUB-EXTRACT-05").gate == "fail"


def test_judge_failing_an_anchor_fails_the_gate(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    report = score(_artifact(tmp_path), oracle,
                   {"format": 1, "scores": {"RUB-EXTRACT-05": {"per_unit": {"a": 3, "b": 0}}}})
    assert report.criterion("RUB-EXTRACT-05").gate == "fail"
    assert "gate RUB-EXTRACT-05 failed" in report.reasons


def test_judged_score_for_uncomputed_det_criterion_stays_not_scored(tmp_path: Path) -> None:
    report = score(_artifact(tmp_path, sources=False), None,
                   {"format": 1, "scores": {"RUB-EXTRACT-05": 3}})
    c = report.criterion("RUB-EXTRACT-05")
    assert c.status == "not_scored" and c.score is None and c.gate is None
    assert c.judged is not None and c.notes


def test_fabrication_gate_needs_per_unit_or_explicit_gate(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    art = _artifact(tmp_path)
    aggregate = score(art, oracle, {"format": 1, "scores": {"RUB-EXTRACT-06": 2.8}})
    assert aggregate.gates["RUB-EXTRACT-06"] is None
    assert "gate RUB-EXTRACT-06 not green (unknown)" in aggregate.reasons
    explicit = score(art, oracle, {"format": 1,
                                   "scores": {"RUB-EXTRACT-06": {"score": 2.8, "gate": "pass"}}})
    assert explicit.gates["RUB-EXTRACT-06"] == "pass"
    fabricated = score(art, oracle, {"format": 1, "scores": {
        "RUB-EXTRACT-06": {"per_unit": {"a": 3, "b": 0}}}})
    assert fabricated.gates["RUB-EXTRACT-06"] == "fail"
    assert fabricated.criterion("RUB-EXTRACT-06").score == 1.5


def test_parse_judged_validation() -> None:
    with pytest.raises(JudgedScoresError, match="format"):
        parse_judged({"scores": {}})
    with pytest.raises(JudgedScoresError, match="purely deterministic"):
        parse_judged({"format": 1, "scores": {"RUB-EXTRACT-10": 3}})
    with pytest.raises(JudgedScoresError, match="not a RUB-EXTRACT"):
        parse_judged({"format": 1, "scores": {"RUB-EXTRACT-99": 3}})
    with pytest.raises(JudgedScoresError, match="outside 0-3"):
        parse_judged({"format": 1, "scores": {"RUB-EXTRACT-01": 4}})
    with pytest.raises(JudgedScoresError, match="number"):
        parse_judged({"format": 1, "scores": {"RUB-EXTRACT-01": True}})
    with pytest.raises(JudgedScoresError, match="rubric"):
        parse_judged({"format": 1, "rubric_version": "v0.9", "scores": {}})
    with pytest.raises(JudgedScoresError, match="gate"):
        parse_judged({"format": 1, "scores": {"RUB-EXTRACT-06": {"score": 2, "gate": "maybe"}}})
    with pytest.raises(JudgedScoresError, match="genuine_proposed_gaps"):
        parse_judged({"format": 1, "scores": {}, "bonus": {"genuine_proposed_gaps": -1}})


def test_per_unit_judged_scores_must_cover_the_artifact(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    with pytest.raises(JudgedScoresError, match="cover exactly"):
        score(_artifact(tmp_path), oracle,
              {"format": 1, "scores": {"RUB-EXTRACT-06": {"per_unit": {"a": 3}}}})


def test_load_judged_errors(tmp_path: Path) -> None:
    with pytest.raises(JudgedScoresError, match="not found"):
        load_judged(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(JudgedScoresError, match="not valid JSON"):
        load_judged(bad)


def test_report_serializes(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    import json

    report = score(_artifact(tmp_path), oracle)
    data = json.loads(json.dumps(report.as_dict()))
    assert data["rubric"] == {"id": "RUB-EXTRACT", "version": "v1.0",
                              "doc": "docs/rubrics/extraction-quality-v1.md"}
    assert data["publishable"] is False and len(data["criteria"]) == 14
    assert "publishable: false" in report.render_text()
