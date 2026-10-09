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

from tests.rubric.conftest import CROSS, RUSSIA, SOURCE, judged_all, tag, unit, write_run

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


# ── review fixes B: gate precedence, the -05 [LLM] half, per-chapter judging, grades ──


def _judged(**scores):  # noqa: ANN003, ANN202
    return {"format": 1, "scores": scores}


def test_explicit_gate_fail_wins_over_per_unit_scores(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    """A judge's story-level 'fail' is never overwritten by non-zero per-unit grades."""
    art = _artifact(tmp_path)
    fab = score(art, oracle, _judged(**{
        "RUB-EXTRACT-06": {"per_unit": {"a": 1, "b": 1}, "gate": "fail"}}))
    assert fab.gates["RUB-EXTRACT-06"] == "fail"
    assert "gate RUB-EXTRACT-06 failed" in fab.reasons
    anchor = score(art, oracle, _judged(**{
        "RUB-EXTRACT-05": {"per_unit": {"a": 3, "b": 3}, "gate": "fail"}}))
    assert anchor.gates["RUB-EXTRACT-05"] == "fail"
    assert "gate RUB-EXTRACT-05 failed" in anchor.reasons
    # ...and an explicit 'pass' never rescues a unit graded 0.
    zero = score(art, oracle, _judged(**{
        "RUB-EXTRACT-06": {"per_unit": {"a": 3, "b": 0}, "gate": "pass"}}))
    assert zero.gates["RUB-EXTRACT-06"] == "fail"


def test_anchor_gate_needs_its_judged_llm_half(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    """-05 is [DET]+[LLM]: a mechanical pass alone is not a green gate."""
    art = _artifact(tmp_path)
    mechanical = score(art, oracle)
    c = mechanical.criterion("RUB-EXTRACT-05")
    assert c.status == "computed" and c.score == 3.0 and c.det.gate == "pass"
    assert c.gate == "pending_llm" and mechanical.gates["RUB-EXTRACT-05"] == "pending_llm"
    assert any("anchored passage supports the claim" in n for n in c.notes)
    assert any(r.startswith("gate RUB-EXTRACT-05 not green ([LLM] half not judged")
               for r in mechanical.reasons)
    # An aggregate judged score cannot show every anchor supports its claim either.
    aggregate = score(art, oracle, _judged(**{"RUB-EXTRACT-05": 3}))
    assert aggregate.criterion("RUB-EXTRACT-05").status == "computed+judged"
    assert aggregate.gates["RUB-EXTRACT-05"] == "pending_llm"
    judged = score(art, oracle, _judged(**{"RUB-EXTRACT-05": {"per_unit": {"a": 3, "b": 2}}}))
    c = judged.criterion("RUB-EXTRACT-05")
    assert c.gate == "pass" and c.status == "computed+judged"
    assert c.score == 2.5  # per unit: min(3, 3), min(3, 2)
    explicit = score(art, oracle, _judged(**{"RUB-EXTRACT-05": {"score": 3, "gate": "pass"}}))
    assert explicit.gates["RUB-EXTRACT-05"] == "pass"
    # A mechanical fail stays a fail whatever the judge says.
    units = [unit("a", EXACT), unit("p", "Lead the witness on every exhibit.", span=(0, 12))]
    failing = score(_artifact(tmp_path / "f", units), oracle,
                    _judged(**{"RUB-EXTRACT-05": {"per_unit": {"a": 3, "p": 3}}}))
    assert failing.gates["RUB-EXTRACT-05"] == "fail"


CHAPTERS = ("ch-a.txt", "ch-b.txt", "ch-c.txt")
EXACT3 = "Keep each question on cross short, and confine it to a single fact the witness must admit."


def _chaptered(tmp_path: Path, extra_unit_in: str | None = None):  # noqa: ANN202
    """Three chapters (one source file each), one distinct unit per chapter."""
    units = [unit(f"u{n}", text, source_file=ch)
             for n, (text, ch) in enumerate(zip((EXACT, EXACT2, EXACT3), CHAPTERS, strict=True))]
    if extra_unit_in:  # a content_hash duplicate of u0, placed in ``extra_unit_in``
        units.append(unit("dup", EXACT, source_file=extra_unit_in))
    run, src = write_run(tmp_path, units, {ch: SOURCE for ch in CHAPTERS})
    return UnitRun.load(run, src)


def test_completeness_floor_applies_per_chapter(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    """One chapter below 2 fails the story even when the cross-chapter mean clears it."""
    art = _chaptered(tmp_path)
    report = score(art, oracle, _judged(**{
        "RUB-EXTRACT-08": {"per_chapter": {"ch-a.txt": 3, "ch-b.txt": 3, "ch-c.txt": 1}}}))
    c = report.criterion("RUB-EXTRACT-08")
    assert c.status == "judged" and c.score == pytest.approx(2.333333)
    assert report.chapters == CHAPTERS
    floor = [r for r in report.reasons if "completeness floor" in r]
    assert floor == ["RUB-EXTRACT-08 chapter ch-c.txt scores 1, below the completeness floor 2"]
    ok = score(art, oracle, _judged(**{
        "RUB-EXTRACT-08": {"per_chapter": {"ch-a.txt": 3, "ch-b.txt": 2, "ch-c.txt": 2}}}))
    assert not [r for r in ok.reasons if "RUB-EXTRACT-08" in r]
    # An aggregate over several chapters cannot prove each chapter clears the floor.
    agg = score(art, oracle, _judged(**{"RUB-EXTRACT-08": 3}))
    assert any(r.startswith("RUB-EXTRACT-08 completeness floor unknown") for r in agg.reasons)
    low = score(art, oracle, _judged(**{"RUB-EXTRACT-08": 1.5}))
    assert any("1.5 is below the completeness floor" in r for r in low.reasons)


def test_single_chapter_aggregate_completeness_is_the_chapter_score(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    report = score(_artifact(tmp_path), oracle, _judged(**{"RUB-EXTRACT-08": 2}))
    assert not [r for r in report.reasons if "RUB-EXTRACT-08" in r]


def test_precision_judged_per_chapter_lowers_each_chapter(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    art = _chaptered(tmp_path, extra_unit_in="ch-a.txt")  # a duplicate unit in chapter a
    det = score(art, oracle).criterion("RUB-EXTRACT-09")
    assert det.det.details["per_chapter"]["ch-a.txt"]["score"] == 2
    assert det.score == pytest.approx(2.666667)
    judged = score(art, oracle, _judged(**{
        "RUB-EXTRACT-09": {"per_chapter": {"ch-a.txt": 3, "ch-b.txt": 1, "ch-c.txt": 3}}}))
    c = judged.criterion("RUB-EXTRACT-09")
    # per chapter min(det, judged): a = min(2, 3), b = min(3, 1), c = min(3, 3)
    assert c.status == "computed+judged" and c.score == 2.0


def test_judged_granularity_must_match_criterion_scope(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    with pytest.raises(JudgedScoresError, match="per-chapter criterion"):
        parse_judged(_judged(**{"RUB-EXTRACT-08": {"per_unit": {"a": 3}}}))
    with pytest.raises(JudgedScoresError, match="per-unit criterion"):
        parse_judged(_judged(**{"RUB-EXTRACT-06": {"per_chapter": {"x": 3}}}))
    with pytest.raises(JudgedScoresError, match="cover exactly the artifact's chapters"):
        score(_chaptered(tmp_path), oracle, _judged(**{
            "RUB-EXTRACT-08": {"per_chapter": {"ch-a.txt": 3, "ch-z.txt": 3}}}))


@pytest.mark.parametrize("bad", [0.3, 2.5, -1, 4, True, "3"])
def test_granular_judged_scores_are_integer_grades(bad) -> None:  # noqa: ANN001
    """A per-unit 0.3 (e.g. an averaged vote with one 'fabricates') is invalid input."""
    with pytest.raises(JudgedScoresError, match="integer rubric grade"):
        parse_judged(_judged(**{"RUB-EXTRACT-06": {"per_unit": {"a": bad}}}))
    with pytest.raises(JudgedScoresError, match="integer rubric grade"):
        parse_judged(_judged(**{"RUB-EXTRACT-08": {"per_chapter": {"c": bad}}}))


def test_integral_float_grades_are_accepted() -> None:
    judged = parse_judged(_judged(**{"RUB-EXTRACT-06": {"per_unit": {"a": 3.0, "b": 0}}}))
    assert dict(judged.scores["RUB-EXTRACT-06"].per_unit) == {"a": 3.0, "b": 0.0}
    # Aggregate scores stay means on the 0-3 scale.
    assert parse_judged(_judged(**{"RUB-EXTRACT-07": 2.4})).scores["RUB-EXTRACT-07"].score == 2.4
