"""Integration tests for discovery trigger, task tree, review, contradiction, and export endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api import main as api_main
from api.db.models import SCHEMA_SQL
from api.main import app
from api.models.processing import (
    ActivityEntry,
    ProcessingJob,
    ProcessingStatus,
)
from api.routes import discovery as discovery_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def configure_tmp_output(tmp_path: Path):
    """Point the API at a temporary directory for each test."""
    api_main.configure(output_dir=tmp_path)
    discovery_mod.reset_discovery_job_manager()
    yield tmp_path


@pytest.fixture()
async def client():
    """Async HTTPX test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _create_corpus(client: AsyncClient, name: str = "Test Corpus") -> str:
    """Helper to create a corpus and return its id."""
    resp = await client.post("/api/v1/corpora", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


async def _setup_corpus_with_extraction(
    tmp_path: Path, client: AsyncClient, corpus_name: str = "test-corpus"
) -> str:
    """Create corpus with extraction output and seed SQLite with tasks."""
    corpus_id = await _create_corpus(client, name=corpus_name)
    corpus_dir = tmp_path / corpus_id

    # Write extraction.json
    extraction = {
        "corpus": corpus_id,
        "total_units": 2,
        "units": [
            {
                "id": "unit-001",
                "text": "Prepare witness before trial.",
                "unit_type": "advice",
                "source_file": "trial.md",
                "confidence": 0.9,
                "folio_tags": [],
                "original_span": {"start": 0, "end": 10, "source_file": "trial.md"},
                "source_section": [],
                "surprise_score": 0.5,
                "content_hash": "a1",
                "lineage": [],
                "cross_references": [],
            },
            {
                "id": "unit-002",
                "text": "File motions early.",
                "unit_type": "best_practice",
                "source_file": "motion.md",
                "confidence": 0.85,
                "folio_tags": [],
                "original_span": {"start": 0, "end": 10, "source_file": "motion.md"},
                "source_section": [],
                "surprise_score": 0.3,
                "content_hash": "b2",
                "lineage": [],
                "cross_references": [],
            },
        ],
    }
    (corpus_dir / "extraction.json").write_text(json.dumps(extraction))

    # Configure extraction data
    api_main._extraction_data.clear()
    api_main.load_extraction(corpus_id)

    # Seed SQLite with tasks and unit links
    import aiosqlite

    db_path = corpus_dir / "review.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(SCHEMA_SQL)
        await db.execute(
            "INSERT INTO task_decisions (task_id, corpus_name, label, status) "
            "VALUES ('task-001', ?, 'Witness Preparation', 'unreviewed')",
            (corpus_id,),
        )
        await db.execute(
            "INSERT INTO task_decisions (task_id, corpus_name, label, parent_task_id, status) "
            "VALUES ('task-002', ?, 'Motion Practice', 'task-001', 'unreviewed')",
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
        await db.execute(
            "INSERT INTO contradictions (task_id, unit_id_a, unit_id_b, corpus_name, nli_score) "
            "VALUES ('task-001', 'unit-001', 'unit-002', ?, 0.85)",
            (corpus_id,),
        )
        await db.commit()

    return corpus_id


# ---------------------------------------------------------------------------
# Tests: Discovery trigger
# ---------------------------------------------------------------------------


async def test_discover_trigger_returns_202(
    client: AsyncClient, configure_tmp_output: Path
):
    """POST /api/v1/corpus/{id}/discover returns 202 with a job_id."""
    corpus_id = await _create_corpus(client)
    corpus_dir = configure_tmp_output / corpus_id
    (corpus_dir / "extraction.json").write_text(json.dumps({"units": []}))

    with patch(
        "api.services.discovery_runner.run_discovery_with_progress",
        new_callable=AsyncMock,
    ):
        resp = await client.post(f"/api/v1/corpus/{corpus_id}/discover")

    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "pending"


async def test_discover_requires_extraction_output(
    client: AsyncClient, configure_tmp_output: Path
):
    """POST /api/v1/corpus/{id}/discover returns 404 without extraction.json."""
    corpus_id = await _create_corpus(client)

    resp = await client.post(f"/api/v1/corpus/{corpus_id}/discover")
    assert resp.status_code == 404
    assert "Extraction output not found" in resp.json()["detail"]


async def test_discover_duplicate_prevention(
    client: AsyncClient, configure_tmp_output: Path
):
    """POST twice while discovery running returns 409 on second call."""
    corpus_id = await _create_corpus(client)
    corpus_dir = configure_tmp_output / corpus_id
    (corpus_dir / "extraction.json").write_text(json.dumps({"units": []}))

    # Write a PROCESSING discovery job directly
    jm = discovery_mod.get_discovery_job_manager()
    job = ProcessingJob(
        corpus_id=f"{corpus_id}_discovery",
        status=ProcessingStatus.PROCESSING,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    await jm.save(job)

    resp = await client.post(f"/api/v1/corpus/{corpus_id}/discover")
    assert resp.status_code == 409
    assert "already in progress" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Tests: Task tree
# ---------------------------------------------------------------------------


async def test_task_tree_endpoint(
    client: AsyncClient, configure_tmp_output: Path
):
    """GET /corpus/{id}/tasks/tree returns hierarchical tree."""
    corpus_id = await _setup_corpus_with_extraction(configure_tmp_output, client)

    resp = await client.get(f"/api/v1/corpus/{corpus_id}/tasks/tree")
    assert resp.status_code == 200
    tree = resp.json()

    # Root should be Witness Preparation
    assert len(tree) == 1
    assert tree[0]["label"] == "Witness Preparation"
    assert tree[0]["id"] == "task-001"
    assert len(tree[0]["children"]) == 1
    assert tree[0]["children"][0]["label"] == "Motion Practice"


# ---------------------------------------------------------------------------
# Tests: Task review
# ---------------------------------------------------------------------------


async def test_task_review_endpoint(
    client: AsyncClient, configure_tmp_output: Path
):
    """POST /corpus/{id}/tasks/{task_id}/review updates task status."""
    corpus_id = await _setup_corpus_with_extraction(configure_tmp_output, client)

    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/tasks/task-001/review",
        json={"status": "approved", "note": "Looks good"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["review_status"] == "approved"
    assert data["id"] == "task-001"


# ---------------------------------------------------------------------------
# Tests: Contradictions
# ---------------------------------------------------------------------------


async def test_contradiction_list_endpoint(
    client: AsyncClient, configure_tmp_output: Path
):
    """GET /corpus/{id}/contradictions returns contradictions."""
    corpus_id = await _setup_corpus_with_extraction(configure_tmp_output, client)

    resp = await client.get(f"/api/v1/corpus/{corpus_id}/contradictions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["task_id"] == "task-001"
    assert data[0]["nli_score"] == 0.85


async def test_contradiction_resolve_endpoint(
    client: AsyncClient, configure_tmp_output: Path
):
    """POST /corpus/{id}/contradictions/{id}/resolve updates resolution."""
    corpus_id = await _setup_corpus_with_extraction(configure_tmp_output, client)

    # Get the contradiction ID
    list_resp = await client.get(f"/api/v1/corpus/{corpus_id}/contradictions")
    contra_id = list_resp.json()[0]["id"]

    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/contradictions/{contra_id}/resolve",
        json={"resolution": "keep_both", "note": "Valid in different contexts"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["resolution"] == "keep_both"
    assert data["resolver_note"] == "Valid in different contexts"


# ---------------------------------------------------------------------------
# Tests: Export
# ---------------------------------------------------------------------------


async def test_export_markdown_endpoint(
    client: AsyncClient, configure_tmp_output: Path
):
    """GET /corpus/{id}/export/markdown returns Markdown content."""
    corpus_id = await _setup_corpus_with_extraction(configure_tmp_output, client)

    resp = await client.get(f"/api/v1/corpus/{corpus_id}/export/markdown")
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers.get("content-type", "")
    assert "Witness Preparation" in resp.text
    assert "Task Hierarchy" in resp.text


# ---------------------------------------------------------------------------
# Tests: Statistics
# ---------------------------------------------------------------------------


async def test_discovery_stats_endpoint(
    client: AsyncClient, configure_tmp_output: Path
):
    """GET /corpus/{id}/discovery/stats returns correct counts."""
    corpus_id = await _setup_corpus_with_extraction(configure_tmp_output, client)

    resp = await client.get(f"/api/v1/corpus/{corpus_id}/discovery/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tasks"] == 2
    assert data["total_subtasks"] == 1  # task-002 has parent
    assert data["contradiction_count"] == 1
    assert data["contradictions_resolved"] == 0
    assert data["total_units_assigned"] == 2
