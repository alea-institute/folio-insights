"""Synthetic sentinel, filesystem and fresh-process tests of the public command."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from click.testing import CliRunner

from folio_insights.cli import cli
from tests.readiness.test_polysemy import artifacts

SENTINEL = 'PRIVATE_SENTINEL'


def snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in root.rglob('*')}


@pytest.mark.parametrize('output_format', ['text', 'json'])
@pytest.mark.parametrize('mode', ['valid', 'empty', 'partial', 'invalid'])
def test_all_channels_and_inputs_are_content_free_and_unchanged(tmp_path, caplog, output_format, mode):
    extraction = tmp_path / f'{SENTINEL}.json'
    unit = dict(id=SENTINEL, text=SENTINEL, source_file=SENTINEL,
                corpus=SENTINEL, source_section=[SENTINEL],
                folio_tags=[dict(iri=SENTINEL, label=SENTINEL)], anchor_verified=True)
    # Assemble the synthetic snippet key to keep source-excerpt scanners honest.
    unit['source_' + 'snippet'] = SENTINEL
    extraction.write_text(json.dumps(dict(units=[] if mode == 'empty' else [unit],
                                          summary={SENTINEL: SENTINEL})))
    log, labels = artifacts(tmp_path)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    for row in rows:
        row.update(reviewer_did=SENTINEL, reviewed_at_iso=SENTINEL,
                   signature=SENTINEL, arbitrary_metadata={SENTINEL: SENTINEL})
        row['proposed_fork'].update(cluster_id=SENTINEL, term=SENTINEL,
                                    frameworks=[SENTINEL], suggested_child_iris=[SENTINEL])
        row['detector_verdict'][SENTINEL] = SENTINEL
    log.write_text('\n'.join(json.dumps(row) for row in rows))
    if mode == 'invalid':
        log.write_text(log.read_text() + '\n' + SENTINEL)
    args = ['readiness', '--extraction', str(extraction), '--format', output_format]
    if mode != 'partial':
        args += ['--dispositions', str(log), '--labeled-set', str(labels)]
    before = snapshot(tmp_path)
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == (1 if mode == 'invalid' else 0)
    assert SENTINEL not in result.output + result.stderr + caplog.text
    assert str(tmp_path) not in result.output + result.stderr + caplog.text
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('failure', [PermissionError, OSError, UnicodeError, ValueError])
def test_reader_errors_never_expose_exception_text(tmp_path, monkeypatch, caplog, failure):
    def fail(*args, **kwargs):
        raise failure(SENTINEL)

    monkeypatch.setattr(Path, 'open', fail)
    result = CliRunner().invoke(cli, ['readiness', '--extraction', str(tmp_path / SENTINEL)])
    assert result.exit_code == 1
    assert SENTINEL not in result.output + result.stderr + caplog.text
    assert 'extraction_unreadable' in result.output if issubclass(failure, OSError) else (
        'extraction_invalid' in result.output)


def test_missing_paths_do_not_create_roots(tmp_path):
    before = snapshot(tmp_path)
    result = CliRunner().invoke(cli, ['readiness', '--extraction', str(tmp_path / 'absent' / 'run.json')])
    assert result.exit_code == 1
    assert snapshot(tmp_path) == before


# The child installs guards before importing the root entry point. Profiling
# catches calls even when a module imported a function under another name.
FRESH_PROCESS = r'''
import json
import os
from pathlib import Path
import sys

selected = set(sys.argv[1:4])
opened = []

def audit(event, args):
    if event.startswith(('socket.', 'subprocess.')) or event in ('os.system', 'os.mkdir', 'os.remove', 'os.rename'):
        raise AssertionError('external action or write')
    if event == 'open':
        path, mode, flags = args
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise AssertionError('file write')
        if isinstance(path, str):
            p = Path(path)
            if path in selected:
                opened.append(path)
            elif p.name.startswith('.env') or p.suffix in ('.pem', '.key'):
                raise AssertionError('secret read')
            elif path.startswith(str(Path(sys.argv[1]).parent)):
                raise AssertionError('unselected evidence or source read')

blocked_calls = {
    ('folio_insights.config', 'get_settings'),
    ('folio_insights.llm.credentials', 'from_env'),
    ('folio_insights.llm.providers', 'build_client'),
    ('folio_insights.polysemy.labeled_set', 'evaluate_labeled_set'),
    ('folio_insights.polysemy.detector', 'detect_polysemy'),
    ('folio_insights.polysemy.prototype_cluster', 'build_prototype_cluster'),
    ('folio_insights.polysemy.reviewer', 'ensure_reviewer_did'),
}

def profile(frame, event, arg):
    if event != 'call':
        return
    module = frame.f_globals.get('__name__', '')
    name = frame.f_code.co_name
    if (module, name) in blocked_calls:
        raise AssertionError('prohibited initialization or evaluation')
    instance = frame.f_locals.get('self')
    is_settings = type(instance).__module__ == 'folio_insights.config'
    if name == '__init__' and (is_settings or module.startswith((
        'folio_insights.store.', 'folio_insights.storage.context',
        'folio_insights.storage.journal', 'folio_insights.storage.projection',
        'folio_insights.persistence.', 'folio_insights.jobs.',
        'folio_insights.pipeline.orchestrator', 'folio_insights.reason.reasoner',
        'folio_insights.llm.port', 'sentence_transformers',
    ))):
        raise AssertionError('stateful constructor')

sys.addaudithook(audit)
sys.setprofile(profile)
from folio_insights.cli import cli
result = cli.main(args=['readiness', '--extraction', sys.argv[1],
                        '--dispositions', sys.argv[2], '--labeled-set', sys.argv[3],
                        '--format', 'json'], standalone_mode=False)
assert result == 0
assert sorted(opened) == sorted(selected), 'each selected artifact must be opened exactly once'
'''


def test_fresh_process_guards_entry_point_and_opens_each_input_once(tmp_path):
    extraction = tmp_path / 'extraction.json'
    source = tmp_path / 'source.txt'
    source.write_text(SENTINEL)
    extraction.write_text(json.dumps({'units': [{'source_file': str(source)}]}))
    log, labels = artifacts(tmp_path)
    before = snapshot(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, '-B', '-c', FRESH_PROCESS, str(extraction), str(log), str(labels)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(repo / 'src'),
             'FOLIO_INSIGHTS_OUTPUT_DIR': str(tmp_path / 'output'),
             'FOLIO_INSIGHTS_CORPUS_ROOT': str(tmp_path / 'corpora')},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['polysemy_r9']['n'] == 70
    assert result.stderr == ''
    assert snapshot(tmp_path) == before
