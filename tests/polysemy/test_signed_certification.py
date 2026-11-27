"""Portable certificates authenticate cases and sample, without certifying statistics."""
from datetime import UTC, datetime, timedelta

import pytest

from folio_insights.polysemy.fp_audit import fp_gate
from tests.polysemy._signed import signed_certificate
from tests.polysemy.test_fp_gate import _labeled_with_records

pytestmark = pytest.mark.usefixtures("registered_polysemy_reviewer")


def test_self_asserted_certificate_cannot_pass():
    labeled, records = _labeled_with_records(70, 0)
    labeled = labeled.model_copy(update={
        "certification": labeled.certification.model_copy(update={"signed_decision": None}),
    })
    report = fp_gate(records, labeled=labeled)
    assert report.status == "provisional"
    assert not report.certified
    assert "signature" in report.certification_problem


def test_signed_certificate_is_repeatable_historical_evidence():
    labeled, records = _labeled_with_records(70, 0)
    certificate = signed_certificate(labeled.certification, now=datetime.now(UTC) - timedelta(days=90))
    labeled = labeled.model_copy(update={"certification": certificate})
    for _ in range(3):
        report = fp_gate(records, labeled=labeled)
        assert report.certified and report.status == "pass"


@pytest.mark.parametrize(("field", "value"), [
    ("corpus", "another-corpus"), ("certified_by", "another-reviewer"),
    ("certified_at", datetime(2020, 1, 1, tzinfo=UTC)),
    ("sample_reviewed", tuple(f"c-{n}" for n in range(20))),
    ("cases_sha256", "f" * 64), ("note", "modified"),
])
def test_certificate_fields_cannot_be_changed(field, value):
    labeled, records = _labeled_with_records(70, 0)
    tampered = labeled.certification.model_copy(update={field: value})
    labeled = labeled.model_copy(update={"certification": tampered})
    report = fp_gate(records, labeled=labeled)
    assert not report.certified and report.status == "provisional"


def test_signed_certificate_cannot_move_to_another_corpus():
    labeled, records = _labeled_with_records(70, 0)
    labeled = labeled.model_copy(update={"corpus": "another-corpus"})
    assert fp_gate(records, labeled=labeled).status == "provisional"


def test_unregistered_certificate_and_fabricated_flags_are_not_authority(registered_polysemy_reviewer):
    labeled, records = _labeled_with_records(70, 0)
    certificate = labeled.certification.model_copy(update={"signature_verified": True})
    labeled = labeled.model_copy(update={"certification": certificate})
    registered_polysemy_reviewer.write_text("")
    report = fp_gate(records, labeled=labeled)
    assert not report.certified and report.status == "provisional"


def test_bad_statistics_still_fail_with_verified_certificate():
    labeled, records = _labeled_with_records(70, 20)
    report = fp_gate(records, labeled=labeled)
    assert report.certified and report.status == "fail"
