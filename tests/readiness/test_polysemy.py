"""The adapter preserves R9 arithmetic without evaluating the current detector."""
import json

import pytest

from folio_insights.readiness import build_readiness_report
from tests.polysemy.test_fp_gate import _labeled_with_records


def artifacts(tmp_path, *, n=70, fps=0, certify=False, **cert):
    labeled, records = _labeled_with_records(n, fps, certify=certify, **cert)
    log = tmp_path / 'dispositions.jsonl'
    labels = tmp_path / 'labeled.json'
    log.write_text('\n'.join(r.model_dump_json() for r in records), encoding='utf-8')
    labels.write_text(labeled.model_dump_json(), encoding='utf-8')
    return log, labels


@pytest.mark.parametrize(('fps', 'certify', 'status'), [
    (0, False, 'provisional'), (0, True, 'pass'), (10, True, 'fail'),
])
def test_saved_gate_arithmetic(tmp_path, fps, certify, status):
    log, labels = artifacts(tmp_path, fps=fps, certify=certify)
    gate = build_readiness_report(dispositions=log, labeled_set=labels).as_dict()['polysemy_r9']
    assert gate['status'] == status
    assert gate['n'] == 70
    assert gate['false_positives'] == fps
    assert gate['threshold'] == 0.1
    assert gate['ci_upper'] == pytest.approx(0.0520 if fps == 0 else 0.2434, abs=0.0001)
    assert gate['fp_rate'] == fps / 70
    assert gate['certified'] is certify
    assert gate['certification_assurance'] == ('self_asserted' if certify else 'none')
    assert gate['basis'] == 'recorded_labeled_set'
    assert gate['current_detector_evaluated'] is False


@pytest.mark.parametrize('cert', [
    {'cases_sha256': 'b' * 64}, {'sample_reviewed': ['c-0']},
    {'sample_reviewed': [f'c-{n}' for n in range(0, 70, 2)]},
])
def test_invalid_certification_never_passes(tmp_path, cert):
    log, labels = artifacts(tmp_path, certify=True, **cert)
    report = build_readiness_report(dispositions=log, labeled_set=labels)
    assert report.exit_code == 0
    gate = report.as_dict()['polysemy_r9']
    assert gate['status'] == 'provisional'
    assert gate['certified'] is False
    assert gate['certification_assurance'] == 'none'
    assert 'certification_invalid' in report.diagnostics


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'extra', 'term', 'decision', 'rationale'])
def test_uncertified_pair_must_match_exactly(tmp_path, change):
    log, labels = artifacts(tmp_path)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    if change == 'missing':
        rows.pop()
    elif change == 'duplicate':
        rows.append(rows[0])
    elif change == 'extra':
        rows.append({**rows[0], 'audit_label': 'extra-case'})
    else:
        rows[0][change] = 'accept' if change == 'decision' else 'PRIVATE_SENTINEL'
    log.write_text('\n'.join(json.dumps(r) for r in rows))
    report = build_readiness_report(dispositions=log, labeled_set=labels)
    data = report.as_dict()
    assert report.exit_code == 1
    assert data['polysemy_r9']['status'] == 'unavailable'
    assert data['polysemy_r9']['n'] is None
    assert data['inputs']['dispositions'] == 'inconsistent'
    assert data['inputs']['labeled_set'] == 'inconsistent'
    assert 'PRIVATE_SENTINEL' not in json.dumps(data)


@pytest.mark.parametrize('verdict', [{}, {'decision': 'PRIVATE_SENTINEL'}, {'decision': []}])
def test_unknown_verdict_invalidates_whole_log(tmp_path, verdict):
    log, _ = artifacts(tmp_path)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    rows[-1]['detector_verdict'] = verdict
    log.write_text('\n'.join(json.dumps(r) for r in rows))
    report = build_readiness_report(dispositions=log).as_dict()
    assert report['inputs']['dispositions'] == 'invalid'
    assert report['polysemy_r9']['n'] is None


def test_malformed_tail_never_counts_valid_prefix(tmp_path):
    log, _ = artifacts(tmp_path)
    log.write_text(log.read_text() + '\nPRIVATE_SENTINEL')
    report = build_readiness_report(dispositions=log)
    assert report.exit_code == 1
    assert report.as_dict()['polysemy_r9']['n'] is None


def test_blank_lines_empty_log_and_missing_are_distinct(tmp_path):
    log, _ = artifacts(tmp_path)
    log.write_text('\n\n' + log.read_text() + '\n\n')
    full = build_readiness_report(dispositions=log).as_dict()['polysemy_r9']
    assert full['status'] == 'provisional'
    assert full['basis'] == 'recorded_log'
    log.write_text('\n\n')
    empty = build_readiness_report(dispositions=log)
    gate = empty.as_dict()['polysemy_r9']
    assert (gate['n'], gate['ci_upper'], gate['status']) == (0, 1.0, 'fail')
    assert gate['fp_rate'] is None
    assert gate['false_discovery_rate'] is None
    assert 'insufficient_evidence' in empty.diagnostics
    missing = build_readiness_report().as_dict()['polysemy_r9']
    assert missing['n'] is None
    assert missing['status'] == 'unavailable'


def test_blank_rationale_reject_excluded_by_canonical_gate(tmp_path):
    log, _ = artifacts(tmp_path)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    rows[0].update(decision='reject', rationale='   ')
    log.write_text('\n'.join(json.dumps(r) for r in rows))
    gate = build_readiness_report(dispositions=log).as_dict()['polysemy_r9']
    assert gate['n'] == 69
    assert gate['invalid_dispositions'] == 1
    assert gate['false_positives'] == 0


def test_bad_selected_labels_do_not_fall_back_to_log_only(tmp_path):
    log, labels = artifacts(tmp_path)
    labels.write_text('PRIVATE_SENTINEL')
    report = build_readiness_report(dispositions=log, labeled_set=labels).as_dict()
    assert report['inputs']['dispositions'] == 'available'
    assert report['inputs']['labeled_set'] == 'invalid'
    assert report['polysemy_r9']['n'] is None
