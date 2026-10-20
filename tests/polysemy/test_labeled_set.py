"""Phase 9 U6 (R9, KTD9): the labeled set and the FP gate measured on it.

The set is agent-authored synthetic paraphrase (no book or other copyrighted
text), N >= 70 per KTD9, with civil-law cases under ``us.louisiana.civil_code``
and a first-pass ``labeler: agent`` disposition on every case. It carries no
certification, so its gate can never read ``pass``.

``test_measured_gate_as_built`` pins what the detector actually produced on
2026-10-20 (recorded in the Phase 9 plan's U6 "As built" note). The fixtures
were not tuned to move it: if a detector change moves these numbers, update the
pin and the As-built note together, never the cases.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from folio_insights.llm.port import TaskLLM
from folio_insights.models.framework import FrameworkRegistry
from folio_insights.polysemy.fp_audit import wilson_score_interval
from folio_insights.polysemy.labeled_set import (
    AlwaysPolysemyLLM,
    LabeledSet,
    evaluate_labeled_set,
    load_labeled_set,
)

pytestmark = pytest.mark.polysemy_spike

LABELED_SET = Path(__file__).parent / "fixtures" / "labeled_set.json"
CIVIL = "us.louisiana.civil_code"


@pytest.fixture(scope="module")
def labeled() -> LabeledSet:
    return load_labeled_set(LABELED_SET)


@pytest.fixture(scope="module")
def evaluation(labeled: LabeledSet):  # noqa: ANN201
    mp = pytest.MonkeyPatch()

    def _no_provider(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("the labeled-set gate must never call a provider")

    mp.setattr(TaskLLM, "structured_model_sync", _no_provider)
    try:
        yield evaluate_labeled_set(labeled, llm=AlwaysPolysemyLLM())
    finally:
        mp.undo()


def test_labeled_set_shape(labeled: LabeledSet) -> None:
    assert len(labeled.cases) >= 70, "KTD9: ~70 cases for the bound to clear 10% at ~3% FP"
    gold = Counter(c.gold for c in labeled.cases)
    assert set(gold) == {"polysemy", "homonymy", "univocal"}
    civil = [c for c in labeled.cases if CIVIL in c.senses]
    assert len(civil) >= 20, len(civil)
    assert {c.disposition.labeler for c in labeled.cases} == {"agent"}
    for case in labeled.cases:
        assert case.disposition.rationale.strip()
        assert (case.disposition.decision == "accept") == (case.gold == "polysemy")
    labeled.check_registered(FrameworkRegistry.with_defaults())


def test_shipped_set_is_not_certified(labeled: LabeledSet) -> None:
    assert labeled.certification is None


def test_cases_digest_is_stable(labeled: LabeledSet) -> None:
    again = load_labeled_set(LABELED_SET)
    assert again.cases_sha256() == labeled.cases_sha256()
    assert len(labeled.cases_sha256()) == 64


def test_gate_is_computed_on_the_upper_bound(evaluation) -> None:  # noqa: ANN001
    report = evaluation.report
    assert report.n == len(evaluation.outcomes)
    assert report.invalid_dispositions == 0
    assert (report.ci_lower, report.ci_upper) == wilson_score_interval(report.false_positives, report.n)
    miscalls = sum(1 for o in evaluation.outcomes
                   if o.detector_decision == "polysemy" and o.gold != "polysemy")
    assert report.false_positives == miscalls
    assert all(r.labeler == "agent" for r in evaluation.records)
    assert evaluation.llm_label == "fake:always-polysemy"


def test_uncertified_gate_never_passes(evaluation) -> None:  # noqa: ANN001
    report = evaluation.report
    assert report.status != "pass"
    assert report.status == ("fail" if report.ci_upper > 0.10 else "provisional")
    assert not report.certified


def test_measured_gate_as_built(evaluation) -> None:  # noqa: ANN001
    """The 2026-10-20 measurement: the gate FAILS (see the plan's As-built note)."""
    report = evaluation.report
    assert (report.n, report.false_positives) == (82, 12)
    assert report.ci_upper == pytest.approx(0.2386, abs=1e-4)
    assert report.status == "fail"
    assert report.detector_positives == 16
    assert evaluation.false_negatives == 25
