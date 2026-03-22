"""Integration tests for OWL/Turtle/JSONLD/validation/bundle export API endpoints."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from api import main as api_main
from api.db.models import SCHEMA_SQL
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


async def _seed_corpus_with_approved_tasks(
    tmp_path: Path, client: AsyncClient
) -> str:
    """Create a corpus with approved tasks seeded in review.db."""
    resp = await client.post("/api/v1/corpora", json={"name": "Export Test"})
    assert resp.status_code == 201
    corpus_id = resp.json()["id"]
    corpus_dir = tmp_path / corpus_id

    # Write extraction.json
    extraction = {
        "corpus": corpus_id,
        "total_units": 2,
        "units": [
            {
                "id": "unit-001",
                "text": "Always prepare witnesses before direct examination.",
                "unit_type": "best_practice",
                "source_file": "trial-ch1.md",
                "confidence": 0.92,
                "folio_tags": [],
                "original_span": {"start": 0, "end": 10, "source_file": "trial-ch1.md"},
                "source_section": [],
                "surprise_score": 0.5,
                "content_hash": "a1",
                "lineage": "trial-ch1.md",
                "cross_references": [],
            },
            {
                "id": "unit-002",
                "text": "File all pretrial motions early to preserve issues.",
                "unit_type": "advice",
                "source_file": "motion-ch2.md",
                "confidence": 0.85,
                "folio_tags": [],
                "original_span": {"start": 0, "end": 10, "source_file": "motion-ch2.md"},
                "source_section": [],
                "surprise_score": 0.3,
                "content_hash": "b2",
                "lineage": "motion-ch2.md",
                "cross_references": [],
            },
        ],
    }
    (corpus_dir / "extraction.json").write_text(json.dumps(extraction))

    # Configure extraction data in API
    api_main._extraction_data.clear()
    api_main.load_extraction(corpus_id)

    # Seed SQLite with approved tasks and unit links
    import aiosqlite

    db_path = corpus_dir / "review.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(SCHEMA_SQL)
        await db.execute(
            "INSERT INTO task_decisions "
            "(task_id, corpus_name, folio_iri, label, status) "
            "VALUES ('task-001', ?, 'https://folio.openlegalstandard.org/abc123', "
            "'Witness Preparation', 'approved')",
            (corpus_id,),
        )
        await db.execute(
            "INSERT INTO task_decisions "
            "(task_id, corpus_name, folio_iri, label, parent_task_id, status) "
            "VALUES ('task-002', ?, 'https://folio.openlegalstandard.org/def456', "
            "'Motion Practice', 'task-001', 'approved')",
            (corpus_id,),
        )
        await db.execute(
            "INSERT INTO task_unit_links (task_id, unit_id, corpus_name) "
            "VALUES ('task-001', 'unit-001', ?)",
            (corpus_id,),
        )
        await db.execute(
            "INSERT INTO task_unit_links (task_id, unit_id, corpus_name) "
            "VALUES ('task-002', 'unit-002', ?)",
            (corpus_id,),
        )
        await db.commit()

    return corpus_id


async def _seed_corpus_no_approved(
    tmp_path: Path, client: AsyncClient
) -> str:
    """Create a corpus with tasks that are NOT approved."""
    resp = await client.post("/api/v1/corpora", json={"name": "No Approved"})
    assert resp.status_code == 201
    corpus_id = resp.json()["id"]
    corpus_dir = tmp_path / corpus_id

    extraction = {"corpus": corpus_id, "total_units": 0, "units": []}
    (corpus_dir / "extraction.json").write_text(json.dumps(extraction))
    api_main._extraction_data.clear()
    api_main.load_extraction(corpus_id)

    import aiosqlite

    db_path = corpus_dir / "review.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(SCHEMA_SQL)
        await db.execute(
            "INSERT INTO task_decisions "
            "(task_id, corpus_name, label, status) "
            "VALUES ('task-001', ?, 'Unapproved Task', 'unreviewed')",
            (corpus_id,),
        )
        await db.commit()

    return corpus_id


# ---------------------------------------------------------------------------
# Tests: OWL export
# ---------------------------------------------------------------------------


async def test_export_owl_returns_rdfxml(
    client: AsyncClient, configure_tmp_output: Path
):
    """GET /corpus/{id}/export/owl returns 200 with Content-Type application/rdf+xml."""
    corpus_id = await _seed_corpus_with_approved_tasks(configure_tmp_output, client)

    resp = await client.get(f"/api/v1/corpus/{corpus_id}/export/owl")
    assert resp.status_code == 200
    assert "application/rdf+xml" in resp.headers.get("content-type", "")
    assert "folio-insights" in resp.text
    assert 'Content-Disposition' in resp.headers or "owl" in resp.text


async def test_export_owl_404_no_approved(
    client: AsyncClient, configure_tmp_output: Path
):
    """GET /corpus/{id}/export/owl returns 404 when no approved tasks."""
    corpus_id = await _seed_corpus_no_approved(configure_tmp_output, client)

    resp = await client.get(f"/api/v1/corpus/{corpus_id}/export/owl")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Turtle export
# ---------------------------------------------------------------------------


async def test_export_ttl_returns_turtle(
    client: AsyncClient, configure_tmp_output: Path
):
    """GET /corpus/{id}/export/ttl returns 200 with Content-Type text/turtle."""
    corpus_id = await _seed_corpus_with_approved_tasks(configure_tmp_output, client)

    resp = await client.get(f"/api/v1/corpus/{corpus_id}/export/ttl")
    assert resp.status_code == 200
    assert "text/turtle" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Tests: JSON-LD export
# ---------------------------------------------------------------------------


async def test_export_jsonld_returns_jsonlines(
    client: AsyncClient, configure_tmp_output: Path
):
    """GET /corpus/{id}/export/jsonld returns 200 with Content-Type application/jsonlines."""
    corpus_id = await _seed_corpus_with_approved_tasks(configure_tmp_output, client)

    resp = await client.get(f"/api/v1/corpus/{corpus_id}/export/jsonld")
    assert resp.status_code == 200
    assert "application/jsonlines" in resp.headers.get("content-type", "")
    # Each line should be valid JSON
    lines = resp.text.strip().splitlines()
    assert len(lines) >= 1
    for line in lines:
        parsed = json.loads(line)
        assert "@context" in parsed


# ---------------------------------------------------------------------------
# Tests: Validation
# ---------------------------------------------------------------------------


async def test_export_validation_returns_json(
    client: AsyncClient, configure_tmp_output: Path
):
    """GET /corpus/{id}/export/validation returns JSON with conforms field."""
    corpus_id = await _seed_corpus_with_approved_tasks(configure_tmp_output, client)

    resp = await client.get(f"/api/v1/corpus/{corpus_id}/export/validation")
    assert resp.status_code == 200
    data = resp.json()
    assert "conforms" in data
    assert isinstance(data["conforms"], bool)
    assert "checks" in data
    assert isinstance(data["checks"], list)
    assert "markdown" in data


# ---------------------------------------------------------------------------
# Tests: Bundle
# ---------------------------------------------------------------------------


async def test_export_bundle_returns_zip(
    client: AsyncClient, configure_tmp_output: Path
):
    """POST /corpus/{id}/export/bundle with formats returns ZIP."""
    corpus_id = await _seed_corpus_with_approved_tasks(configure_tmp_output, client)

    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/export/bundle",
        json={"formats": ["owl", "ttl", "md"]},
    )
    assert resp.status_code == 200
    assert "application/zip" in resp.headers.get("content-type", "")

    # Verify ZIP contents
    buf = BytesIO(resp.content)
    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
        assert any(n.endswith(".owl") for n in names)
        assert any(n.endswith(".ttl") for n in names)
        assert any(n.endswith(".md") for n in names)


async def test_export_bundle_404_no_approved(
    client: AsyncClient, configure_tmp_output: Path
):
    """POST /corpus/{id}/export/bundle returns 404 when no approved tasks."""
    corpus_id = await _seed_corpus_no_approved(configure_tmp_output, client)

    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/export/bundle",
        json={"formats": ["owl"]},
    )
    assert resp.status_code == 404
