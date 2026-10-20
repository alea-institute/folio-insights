"""Phase 9 U6 (R9, KTD9, decision 1): the FP gate is honest and never self-certifies."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from folio_insights.polysemy.fp_audit import (
    FP_GATE_THRESHOLD,
    Certification,
    fp_gate,
    wilson_score_interval,
)
from tests.polysemy.test_fp_rate import _sample_record

pytestmark = pytest.mark.polysemy_spike

DIGEST = "a" * 64


def _records(n: int, fps: int) -> list:
    out = [_sample_record(decision="reject", rationale="miscall") for _ in range(fps)]
    out += [_sample_record(decision="accept") for _ in range(n - fps)]
    return out


def _cert(**overrides) -> Certification:  # noqa: ANN003
    fields = dict(certified_by="did:key:z6MkHumanReviewer", certified_at=datetime(2026, 10, 21, tzinfo=UTC),
                  sample_reviewed=("case-1",), cases_sha256=DIGEST)
    fields.update(overrides)
    return Certification(**fields)


def test_threshold_is_ten_percent() -> None:
    assert FP_GATE_THRESHOLD == 0.10


def test_kt9_sizing_arithmetic() -> None:
    """KTD9: 0 FPs need N >= 35; ~3% needs ~70 for the upper bound to clear 10%."""
    assert wilson_score_interval(0, 35)[1] <= 0.10 < wilson_score_interval(0, 34)[1]
    assert wilson_score_interval(2, 70)[1] <= 0.10


def test_uncertified_under_threshold_is_provisional() -> None:
    report = fp_gate(_records(70, 0))
    assert report.ci_upper <= 0.10
    assert report.status == "provisional"
    assert not report.certified and "no certification" in report.certification_problem


def test_certified_under_threshold_passes() -> None:
    report = fp_gate(_records(70, 0), certification=_cert(), cases_sha256=DIGEST)
    assert report.status == "pass" and report.certified


def test_over_threshold_fails_even_when_certified() -> None:
    report = fp_gate(_records(70, 10), certification=_cert(), cases_sha256=DIGEST)
    assert report.ci_upper > 0.10
    assert report.status == "fail"


def test_certification_binds_to_the_cases() -> None:
    report = fp_gate(_records(70, 0), certification=_cert(), cases_sha256="b" * 64)
    assert report.status == "provisional"
    assert "digest" in report.certification_problem
    assert fp_gate(_records(70, 0), certification=_cert()).status == "provisional"


@pytest.mark.parametrize("bad", [
    {"certified_by": ""},
    {"certified_by": "agent"},
    {"certified_by": "Claude (agent)"},
    {"sample_reviewed": ()},
    {"cases_sha256": "not-a-digest"},
])
def test_certification_record_validation(bad: dict) -> None:
    with pytest.raises(ValidationError):
        _cert(**bad)


def test_gate_reads_upper_not_lower_bound() -> None:
    """Phase 1's inverted gate: 2 of 22 has a lower bound under 10% but fails."""
    report = fp_gate(_records(22, 2), certification=_cert(), cases_sha256=DIGEST)
    assert report.ci_lower < 0.10 < report.ci_upper
    assert report.status == "fail"


def test_empty_set_fails() -> None:
    assert fp_gate([]).status == "fail"


def test_false_discovery_rate_is_reported() -> None:
    records = _records(10, 2) + [_sample_record(decision="reject", rationale="agree",
                                                detector_decision="coincidence")]
    report = fp_gate(records)
    assert report.detector_positives == 10
    assert report.false_discovery_rate == pytest.approx(0.2)
