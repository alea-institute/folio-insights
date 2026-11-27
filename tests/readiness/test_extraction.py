"""Recorded coverage is an aggregate over emitted units, never source coverage."""
import json

import pytest

from folio_insights.readiness import build_readiness_report


def inspect(tmp_path, document):
    path = tmp_path / 'extraction.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    return build_readiness_report(extraction=path).as_dict()


def test_mixed_recorded_coverage(tmp_path):
    report = inspect(tmp_path, {
        'units': [
            {'folio_tags': [{'iri': 'urn:synthetic'}], 'anchor_verified': i < 2,
             'source_file': f'synthetic-{i % 2}.txt'}
            for i in range(3)
        ] + [{'folio_tags': [{'iri': ''}], 'anchor_verified': False,
              'source_file': 'synthetic-1.txt'}],
        'total_units': 4, 'summary': {'documents_processed': 3},
        'coverage_complete': True,
    })
    coverage = report['coverage']
    assert report['inputs']['extraction'] == 'available'
    assert coverage['emitted_units'] == 4
    assert coverage['recorded_documents_processed'] == 3
    assert coverage['distinct_source_files'] == 2
    assert coverage['recorded_iri_tagging'] == {
        'numerator': 3, 'denominator': 4, 'negative_units': 1,
        'unknown_units': 0, 'fraction': 0.75,
    }
    assert coverage['recorded_anchor_flags']['fraction'] == 0.5
    assert coverage['denominator_basis'] == 'emitted_units'
    assert coverage['full_source_coverage'] is None
    assert coverage['full_source_coverage_reason'] == 'source_coverage_not_recorded'
    assert 'urn:synthetic' not in json.dumps(report)


def test_missing_fields_stay_unknown(tmp_path):
    coverage = inspect(tmp_path, {'units': [
        {}, {'folio_tags': [], 'anchor_verified': False, 'source_file': 'a'},
        {'folio_tags': [{}], 'anchor_verified': True},
    ]})['coverage']
    assert coverage['status'] == 'incomplete'
    assert coverage['distinct_source_files'] is None
    assert coverage['source_reference_unknown_units'] == 2
    assert coverage['recorded_documents_processed'] is None
    assert coverage['recorded_iri_tagging']['unknown_units'] == 2
    assert coverage['recorded_iri_tagging']['fraction'] is None
    assert coverage['recorded_anchor_flags']['unknown_units'] == 1
    assert coverage['recorded_anchor_flags']['fraction'] is None


def test_empty_is_distinct_from_missing(tmp_path):
    empty = inspect(tmp_path, {'units': []})['coverage']
    missing = build_readiness_report().as_dict()['coverage']
    assert empty['status'] == 'empty'
    assert empty['emitted_units'] == 0
    assert empty['distinct_source_files'] == 0
    assert empty['recorded_anchor_flags']['denominator'] == 0
    assert empty['recorded_anchor_flags']['fraction'] is None
    assert missing['status'] == 'unavailable'
    assert missing['emitted_units'] is None


@pytest.mark.parametrize('document', [
    [], {}, {'units': {}}, {'units': [None]},
    {'units': [], 'total_units': True}, {'units': [], 'total_units': -1},
    {'units': [], 'total_units': 0.0}, {'units': [], 'summary': None},
    {'units': [], 'summary': {'documents_processed': True}},
    {'units': [], 'summary': {'documents_processed': -1}},
    {'units': [{}], 'summary': {'documents_processed': '1'}},
    {'units': [{'folio_tags': None}]}, {'units': [{'folio_tags': [None]}]},
    {'units': [{'folio_tags': [{'iri': None}]}]},
    {'units': [{'folio_tags': [{'iri': 'good'}, {'iri': 2}]}]},
    {'units': [{'anchor_verified': 'true'}]}, {'units': [{'anchor_verified': 1}]},
    {'units': [{'source_file': False}]},
])
def test_malformed_consumed_fields_invalidate_section(tmp_path, document):
    report = inspect(tmp_path, document)
    assert report['inputs']['extraction'] == 'invalid'
    assert report['coverage']['emitted_units'] is None
    assert report['diagnostics'] == ['extraction_invalid']


def test_inconsistent_total_is_not_partial_coverage(tmp_path):
    report = inspect(tmp_path, {'units': [{}], 'total_units': 2})
    assert report['inputs']['extraction'] == 'inconsistent'
    assert report['coverage']['emitted_units'] is None


def test_unrecognized_metadata_is_never_projected(tmp_path):
    report = inspect(tmp_path, {'units': [], 'PRIVATE_SENTINEL': 'PRIVATE_SENTINEL',
                               'summary': {'PRIVATE_SENTINEL': 'PRIVATE_SENTINEL'}})
    assert 'PRIVATE_SENTINEL' not in json.dumps(report)
