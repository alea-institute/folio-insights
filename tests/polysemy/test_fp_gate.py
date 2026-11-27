"""Phase 9 U6 (R9, KTD9, decision 1): the FP gate is honest and never self-certifies.

The certification comes only from the labeled set, and the gate computes the
set's digest itself (PR #44 review item 2).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from folio_insights.polysemy.dispositions import DispositionRecord, ProposedFork
from folio_insights.polysemy.fp_audit import (
    AGENT_LABELER_ID,
    FP_GATE_THRESHOLD,
    Certification,
    fp_gate,
    wilson_score_interval,
)
from folio_insights.polysemy.labeled_set import LabeledSet
from tests.polysemy.test_fp_rate import _sample_record
from tests.polysemy._signed import CORPUS, DID, signed_certificate

pytestmark = [pytest.mark.polysemy_spike, pytest.mark.usefixtures("registered_polysemy_reviewer")]

CL, LA = "us.common_law", "us.louisiana.civil_code"


def _records(n: int, fps: int) -> list:
    out = [_sample_record(decision="reject", rationale="miscall") for _ in range(fps)]
    out += [_sample_record(decision="accept") for _ in range(n - fps)]
    return out


def _labeled_with_records(n: int, fps: int, *, certify: bool = True,
                          **cert: object) -> tuple[LabeledSet, list[DispositionRecord]]:
    """``n`` cases: the first ``fps`` are univocal cases the detector flagged
    (miscalls); the rest alternate polysemy (flagged, accepted) and univocal
    (not flagged, rejected)."""
    cases, flagged = [], []
    for i in range(n):
        gold = "univocal" if i < fps or i % 2 == 0 else "polysemy"
        flagged.append(i < fps or gold == "polysemy")
        cases.append({
            "id": f"c-{i}", "term": "lease", "gold": gold, "senses": {CL: ["a"], LA: ["b"]},
            "disposition": {"labeler": "agent", "decision": "accept" if gold == "polysemy" else "reject",
                            "rationale": f"r{i}"},
        })
    doc = {"format": "folio-insights/polysemy-labeled-set/v1", "cases": cases, "corpus": CORPUS}
    if certify:
        digest = LabeledSet.model_validate(doc).cases_sha256()
        fields = {"certified_by": DID, "certified_at": "2026-10-21T00:00:00Z",
                  "sample_reviewed": [c["id"] for c in cases], "cases_sha256": digest}
        fields.update(cert)
        doc["certification"] = signed_certificate(Certification.model_validate(fields))
    labeled = LabeledSet.model_validate(doc)
    records = [
        DispositionRecord(
            cluster_id=f"fi:C_{c.id}", term=c.term, proposed_fork=ProposedFork(cluster_id="x", term=c.term),
            decision=c.disposition.decision, rationale=c.disposition.rationale,
            reviewer_did=AGENT_LABELER_ID, reviewed_at_iso="2026-10-20T00:00:00+00:00",
            detector_verdict={"decision": "polysemy" if flag else "coincidence"},
            audit_label=c.id, labeler="agent",
        )
        for c, flag in zip(labeled.cases, flagged)
    ]
    return labeled, records


def _cert(**overrides) -> Certification:  # noqa: ANN003
    fields = dict(certified_by="did:key:z6MkHumanReviewer", certified_at=datetime(2026, 10, 21, tzinfo=UTC),
                  sample_reviewed=("case-1",), cases_sha256="a" * 64)
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
    labeled, records = _labeled_with_records(70, 0, certify=False)
    assert fp_gate(records, labeled=labeled).status == "provisional"


def test_certified_under_threshold_passes() -> None:
    labeled, records = _labeled_with_records(70, 0)
    report = fp_gate(records, labeled=labeled)
    assert report.status == "pass" and report.certified


def test_over_threshold_fails_even_when_certified() -> None:
    labeled, records = _labeled_with_records(70, 10)
    report = fp_gate(records, labeled=labeled)
    assert report.false_positives == 10 and report.ci_upper > 0.10
    assert report.status == "fail"


def test_certification_binds_to_the_cases() -> None:
    labeled, records = _labeled_with_records(70, 0, cases_sha256="b" * 64)
    report = fp_gate(records, labeled=labeled)
    assert report.status == "provisional"
    assert "digest" in report.certification_problem
    assert fp_gate(records).status == "provisional"  # no labeled set, no certification


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
    labeled, records = _labeled_with_records(22, 2)
    report = fp_gate(records, labeled=labeled)
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
