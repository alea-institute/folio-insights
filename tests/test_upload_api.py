"""Integration tests for file upload API with ZIP extraction and safety checks."""

from __future__ import annotations

import io
import zipfile
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


async def _create_corpus(client: AsyncClient, name: str = "Test Corpus") -> str:
    """Helper to create a corpus and return its id."""
    resp = await client.post("/api/v1/corpora", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_upload_single_md_file(client: AsyncClient, configure_tmp_output: Path):
    """Upload a single .md file and verify it lands in sources/."""
    corpus_id = await _create_corpus(client)

    content = b"# Hello World\n\nThis is a test document."
    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/upload",
        files=[("files", ("test.md", content, "text/markdown"))],
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["uploaded"][0]["filename"] == "test.md"

    # Verify file on disk
    source_file = configure_tmp_output / corpus_id / "sources" / "test.md"
    assert source_file.exists()
    assert source_file.read_bytes() == content


async def test_upload_multiple_files(client: AsyncClient, configure_tmp_output: Path):
    """Upload multiple files in a single request."""
    corpus_id = await _create_corpus(client)

    files = [
        ("files", ("doc1.md", b"# Doc 1", "text/markdown")),
        ("files", ("doc2.txt", b"Plain text content", "text/plain")),
        ("files", ("doc3.csv", b"a,b,c\n1,2,3", "text/csv")),
    ]

    resp = await client.post(f"/api/v1/corpus/{corpus_id}/upload", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3

    # Verify all files on disk
    sources = configure_tmp_output / corpus_id / "sources"
    assert (sources / "doc1.md").exists()
    assert (sources / "doc2.txt").exists()
    assert (sources / "doc3.csv").exists()


async def test_upload_unsupported_format(client: AsyncClient):
    """Upload a file with unsupported extension returns 400."""
    corpus_id = await _create_corpus(client)

    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/upload",
        files=[("files", ("malware.exe", b"MZ...", "application/octet-stream"))],
    )

    assert resp.status_code == 400
    assert "malware.exe" in resp.json()["detail"]


async def test_upload_to_nonexistent_corpus(client: AsyncClient):
    """Upload to a nonexistent corpus returns 404."""
    resp = await client.post(
        "/api/v1/corpus/does-not-exist/upload",
        files=[("files", ("test.md", b"# Test", "text/markdown"))],
    )
    assert resp.status_code == 404


async def test_upload_zip_extraction(client: AsyncClient, configure_tmp_output: Path):
    """Upload a ZIP archive and verify its contents are extracted."""
    corpus_id = await _create_corpus(client)

    # Create an in-memory ZIP with 2 markdown files
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("chapter1.md", "# Chapter 1\n\nIntroduction.")
        zf.writestr("chapter2.md", "# Chapter 2\n\nBody text.")
    buf.seek(0)

    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/upload",
        files=[("files", ("archive.zip", buf.getvalue(), "application/zip"))],
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2

    # Verify extracted files on disk
    sources = configure_tmp_output / corpus_id / "sources"
    assert (sources / "chapter1.md").exists()
    assert (sources / "chapter2.md").exists()
    assert (sources / "chapter1.md").read_text() == "# Chapter 1\n\nIntroduction."


async def test_zip_path_traversal_protection(client: AsyncClient, configure_tmp_output: Path):
    """ZIP with path traversal entries returns 400 and writes nothing outside corpus."""
    corpus_id = await _create_corpus(client)

    # Create a malicious ZIP with a path traversal entry
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", "I should not exist outside corpus dir")
    buf.seek(0)

    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/upload",
        files=[("files", ("evil.zip", buf.getvalue(), "application/zip"))],
    )

    assert resp.status_code == 400
    assert "escapes target directory" in resp.json()["detail"]

    # Verify evil file was NOT written outside corpus directory
    evil_path = configure_tmp_output / corpus_id / "evil.txt"
    assert not evil_path.exists()

    # Also check parent directory
    evil_parent = configure_tmp_output / "evil.txt"
    assert not evil_parent.exists()


async def test_list_files_after_upload(client: AsyncClient):
    """Files uploaded are visible in the corpus file listing."""
    corpus_id = await _create_corpus(client)

    await client.post(
        f"/api/v1/corpus/{corpus_id}/upload",
        files=[
            ("files", ("notes.md", b"# Notes", "text/markdown")),
            ("files", ("data.csv", b"col1,col2\n1,2", "text/csv")),
        ],
    )

    resp = await client.get(f"/api/v1/corpora/{corpus_id}/files")
    assert resp.status_code == 200
    files = resp.json()
    filenames = [f["filename"] for f in files]
    assert "notes.md" in filenames
    assert "data.csv" in filenames


async def test_upload_all_supported_formats(client: AsyncClient):
    """Verify all 13 supported formats are accepted (no 400 error)."""
    corpus_id = await _create_corpus(client)

    extensions = [
        ".md", ".txt", ".docx", ".pdf", ".html", ".rtf",
        ".eml", ".msg", ".xml", ".csv", ".xlsx", ".tsv", ".wpd",
    ]

    files_to_upload = [
        ("files", (f"test{ext}", b"content", "application/octet-stream"))
        for ext in extensions
    ]

    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/upload",
        files=files_to_upload,
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == len(extensions)


async def test_zip_skips_macosx_entries(client: AsyncClient, configure_tmp_output: Path):
    """ZIP extraction skips __MACOSX metadata entries."""
    corpus_id = await _create_corpus(client)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("real_file.md", "# Real content")
        zf.writestr("__MACOSX/._real_file.md", "macOS resource fork")
    buf.seek(0)

    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/upload",
        files=[("files", ("mac_archive.zip", buf.getvalue(), "application/zip"))],
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["uploaded"][0]["filename"] == "real_file.md"

    # __MACOSX directory should not be created
    sources = configure_tmp_output / corpus_id / "sources"
    assert not (sources / "__MACOSX").exists()
