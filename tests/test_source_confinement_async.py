"""Offline ASGI regressions for the source release boundary."""
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from api import main as api_main


@pytest.mark.parametrize('escape', ['../outside.txt', 'sibling', 'symlink', 'absolute'])
async def test_source_denies_escape(tmp_path: Path, monkeypatch, escape: str):
    root = tmp_path / 'output'
    root.mkdir()
    outside = tmp_path / 'outside.txt'
    outside.write_text('synthetic private text')
    sibling = tmp_path / 'output-other'
    sibling.mkdir()
    (sibling / 'outside.txt').write_text('synthetic private text')
    (root / 'link.txt').symlink_to(outside)
    path = {
        '../outside.txt': '../outside.txt',
        'sibling': str(sibling / 'outside.txt'),
        'symlink': 'link.txt',
        'absolute': str(outside),
    }[escape]
    monkeypatch.setattr(api_main, '_output_dir', root)
    async with AsyncClient(transport=ASGITransport(app=api_main.app), base_url='http://test') as client:
        response = await client.get('/api/v1/source', params={'file': path})
    assert response.status_code == 200
    assert response.json()['found'] is False
    assert response.json()['text'] == ''


async def test_source_serves_confined_span(tmp_path: Path, monkeypatch):
    root = tmp_path / 'output'
    sources = root / 'sample' / 'sources'
    sources.mkdir(parents=True)
    (sources / 'sample.txt').write_text('before TARGET after')
    monkeypatch.setattr(api_main, '_output_dir', root)
    async with AsyncClient(transport=ASGITransport(app=api_main.app), base_url='http://test') as client:
        response = await client.get('/api/v1/source', params={
            'file': 'sample/sources/sample.txt', 'start': 7, 'end': 13,
        })
    data = response.json()
    assert data['found'] is True
    assert data['text'][data['span_start_in_context']:data['span_end_in_context']] == 'TARGET'
