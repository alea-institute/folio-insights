"""Integration tests for corpus CRUD API endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from api import main as api_main
from api.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def configure_tmp_output(tmp_path: Path):
    """Point the API at a temporary directory for each test."""
    api_main.configure(output_dir=tmp_path)
    yield tmp_path


@pytest.fixture()
async def client():
    """Async HTTPX test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_create_corpus(client: AsyncClient):
    """POST /api/v1/corpora creates a new corpus and returns 201."""
    resp = await client.post("/api/v1/corpora", json={"name": "Test Corpus"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "test-corpus"
    assert data["name"] == "Test Corpus"
    assert data["file_count"] == 0
    assert "created_at" in data


async def test_create_duplicate_corpus(client: AsyncClient):
    """POST /api/v1/corpora with an existing name returns 409."""
    await client.post("/api/v1/corpora", json={"name": "Test Corpus"})
    resp = await client.post("/api/v1/corpora", json={"name": "Test Corpus"})
    assert resp.status_code == 409


async def test_list_corpora(client: AsyncClient):
    """GET /api/v1/corpora returns all created corpora."""
    await client.post("/api/v1/corpora", json={"name": "Alpha"})
    await client.post("/api/v1/corpora", json={"name": "Beta"})

    resp = await client.get("/api/v1/corpora")
    assert resp.status_code == 200
    data = resp.json()
    ids = [c["id"] for c in data]
    assert "alpha" in ids
    assert "beta" in ids


async def test_get_corpus(client: AsyncClient):
    """GET /api/v1/corpora/{id} returns corpus details."""
    await client.post("/api/v1/corpora", json={"name": "Test Corpus"})

    resp = await client.get("/api/v1/corpora/test-corpus")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "test-corpus"
    assert data["name"] == "Test Corpus"


async def test_get_nonexistent_corpus(client: AsyncClient):
    """GET /api/v1/corpora/{id} returns 404 for unknown corpus."""
    resp = await client.get("/api/v1/corpora/nope")
    assert resp.status_code == 404


async def test_list_files_empty(client: AsyncClient):
    """GET /api/v1/corpora/{id}/files returns empty list for new corpus."""
    await client.post("/api/v1/corpora", json={"name": "Test Corpus"})

    resp = await client.get("/api/v1/corpora/test-corpus/files")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_files_with_content(client: AsyncClient, configure_tmp_output: Path):
    """GET /api/v1/corpora/{id}/files returns uploaded files."""
    await client.post("/api/v1/corpora", json={"name": "Test Corpus"})

    # Manually place a file in the sources directory
    sources = configure_tmp_output / "test-corpus" / "sources"
    (sources / "example.md").write_text("# Hello")

    resp = await client.get("/api/v1/corpora/test-corpus/files")
    assert resp.status_code == 200
    files = resp.json()
    assert len(files) == 1
    assert files[0]["filename"] == "example.md"
    assert files[0]["format"] == "md"
    assert files[0]["size_bytes"] > 0


async def test_delete_corpus(client: AsyncClient, configure_tmp_output: Path):
    """DELETE /api/v1/corpora/{id} removes the corpus directory."""
    await client.post("/api/v1/corpora", json={"name": "Test Corpus"})

    resp = await client.delete("/api/v1/corpora/test-corpus")
    assert resp.status_code == 204

    # Verify gone from listing
    listing = await client.get("/api/v1/corpora")
    assert len(listing.json()) == 0

    # Verify directory removed
    assert not (configure_tmp_output / "test-corpus").exists()


async def test_delete_nonexistent_corpus(client: AsyncClient):
    """DELETE /api/v1/corpora/{id} returns 404 for unknown corpus."""
    resp = await client.delete("/api/v1/corpora/nope")
    assert resp.status_code == 404


async def test_slugify_special_characters(client: AsyncClient):
    """Corpus names with special characters are properly slugified."""
    resp = await client.post("/api/v1/corpora", json={"name": "My Test & Corpus! (v2)"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "my-test-corpus-v2"
