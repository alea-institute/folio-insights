"""Exercise registration, output parity and safe errors through the root CLI."""
import json

import pytest
from click.testing import CliRunner

from folio_insights.cli import cli
from tests.readiness.test_polysemy import artifacts


def test_root_help_and_no_arguments():
    runner = CliRunner()
    assert 'readiness' in runner.invoke(cli, ['--help']).output
    result = runner.invoke(cli, ['readiness', '--format', 'json'])
    assert result.exit_code == 0
    report = json.loads(result.output)
    assert report['schema_version'] == 'folio-insights/readiness/v1'
    assert set(report['inputs'].values()) == {'not_supplied'}
    assert report['polysemy_r9']['status'] == 'unavailable'
    assert set(report) == {'schema_version', 'inputs', 'coverage', 'polysemy_r9', 'diagnostics'}


def flatten(data, prefix=''):
    for key, value in data.items():
        name = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            yield from flatten(value, name)
        else:
            yield name, value


def test_formats_agree_and_are_deterministic(tmp_path):
    extraction = tmp_path / 'extraction.json'
    extraction.write_text(json.dumps({'units': [{'folio_tags': [], 'anchor_verified': False}]}))
    log, labels = artifacts(tmp_path)
    args = ['readiness', '--extraction', str(extraction), '--dispositions', str(log),
            '--labeled-set', str(labels)]
    runner = CliRunner()
    structured = runner.invoke(cli, [*args, '--format', 'json'])
    text = runner.invoke(cli, args)
    assert structured.exit_code == text.exit_code == 0
    assert structured.output == runner.invoke(cli, [*args, '--format', 'json']).output
    assert text.output == runner.invoke(cli, args).output
    parsed = {key: json.loads(value) for key, value in
              (line.split(': ', 1) for line in text.output.splitlines())}
    assert parsed == dict(flatten(json.loads(structured.output)))


@pytest.mark.parametrize('output_format', ['text', 'json'])
def test_bad_gate_retains_good_extraction(tmp_path, output_format):
    extraction = tmp_path / 'PRIVATE_SENTINEL.json'
    extraction.write_text('{"units": []}')
    log, _ = artifacts(tmp_path)
    log.write_text(log.read_text() + '\nPRIVATE_SENTINEL')
    result = CliRunner().invoke(cli, ['readiness', '--format', output_format,
                                     '--extraction', str(extraction), '--dispositions', str(log)])
    assert result.exit_code == 1
    assert 'PRIVATE_SENTINEL' not in result.output
    assert str(tmp_path) not in result.output
    assert 'extraction' in result.output and 'empty' in result.output
    assert 'dispositions_invalid' in result.output
    assert not result.stderr


@pytest.mark.parametrize('args', [
    ['--labeled-set', 'PRIVATE_SENTINEL'], ['--format', 'PRIVATE_SENTINEL'],
    ['--PRIVATE_SENTINEL'], ['PRIVATE_SENTINEL'], ['--extraction'],
])
def test_usage_errors_are_content_free_before_reads(monkeypatch, args):
    from pathlib import Path

    def no_read(*args, **kwargs):
        raise AssertionError('must reject options before reading')

    monkeypatch.setattr(Path, 'open', no_read)
    result = CliRunner().invoke(cli, ['readiness', *args])
    assert result.exit_code == 2
    assert 'PRIVATE_SENTINEL' not in result.output
    assert result.stderr in ('Error: readiness_invalid_usage\n',
                             'Error: labeled_set_requires_dispositions\n')


@pytest.mark.parametrize('fps', [0, 10])
def test_exit_zero_is_not_a_gate_pass(tmp_path, fps):
    log, _ = artifacts(tmp_path, fps=fps)
    result = CliRunner().invoke(cli, ['readiness', '--dispositions', str(log), '--format', 'json'])
    assert result.exit_code == 0
    assert json.loads(result.output)['polysemy_r9']['status'] == ('fail' if fps else 'provisional')
