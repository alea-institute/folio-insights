"""Tests for task-specific review endpoints: bulk approve, CRUD, hierarchy edits, source authority."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from api import main as api_main
from api.db.models import SCHEMA_SQL
from api.main import app
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


async def _create_corpus(client: AsyncClient, name: str = "Test Corpus") -> str:
    """Helper to create a corpus and return its id."""
    resp = await client.post("/api/v1/corpora", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


async def _setup_seeded_corpus(
    tmp_path: Path, client: AsyncClient
) -> str:
    """Create corpus with extraction output and seed tasks."""
    corpus_id = await _create_corpus(client, name="review-test")
    corpus_dir = tmp_path / corpus_id

    extraction = {
        "corpus": corpus_id,
        "total_units": 3,
        "units": [
            {
                "id": f"unit-{i:03d}",
                "text": f"Unit text {i}",
                "unit_type": "advice",
                "source_file": "source.md",
                "confidence": 0.9 - i * 0.1,
                "folio_tags": [],
                "original_span": {"start": 0, "end": 10, "source_file": "source.md"},
                "source_section": [],
                "surprise_score": 0.5,
                "content_hash": f"hash{i}",
                "lineage": [],
                "cross_references": [],
            }
            for i in range(1, 4)
        ],
    }
    (corpus_dir / "extraction.json").write_text(json.dumps(extraction))

    api_main._extraction_data.clear()
    api_main.load_extraction(corpus_id)

    # Write task_tree.json for bulk approve by confidence
    tree_data = [
        {"id": "task-a", "label": "Task A", "confidence": 0.95},
        {"id": "task-b", "label": "Task B", "confidence": 0.5},
        {"id": "task-c", "label": "Task C", "confidence": 0.3},
    ]
    (corpus_dir / "task_tree.json").write_text(json.dumps(tree_data))

    import aiosqlite

    db_path = corpus_dir / "review.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(SCHEMA_SQL)
        for t in [
            ("task-a", "Task A", None),
            ("task-b", "Task B", "task-a"),
            ("task-c", "Task C", "task-a"),
        ]:
            await db.execute(
                "INSERT INTO task_decisions (task_id, corpus_name, label, parent_task_id, status) "
                "VALUES (?, ?, ?, ?, 'unreviewed')",
                (t[0], corpus_id, t[1], t[2]),
            )
        # Link units
        await db.execute(
            "INSERT INTO task_unit_links (task_id, unit_id, corpus_name) "
            "VALUES ('task-a', 'unit-001', ?)",
            (corpus_id,),
        )
        await db.execute(
            "INSERT INTO task_unit_links (task_id, unit_id, corpus_name) "
            "VALUES ('task-b', 'unit-002', ?)",
            (corpus_id,),
        )
        await db.commit()

    return corpus_id


# ---------------------------------------------------------------------------
# Tests: Bulk approve
# ---------------------------------------------------------------------------


async def test_task_bulk_approve(
    client: AsyncClient, configure_tmp_output: Path
):
    """POST /corpus/{id}/tasks/bulk-approve with task_ids approves specified tasks."""
    corpus_id = await _setup_seeded_corpus(configure_tmp_output, client)

    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/tasks/bulk-approve",
        json={"task_ids": ["task-a", "task-b"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved_count"] == 2
    assert set(data["task_ids"]) == {"task-a", "task-b"}

    # Verify via single task endpoint
    task_resp = await client.get(f"/api/v1/corpus/{corpus_id}/tasks/task-a")
    assert task_resp.json()["review_status"] == "approved"


# ---------------------------------------------------------------------------
# Tests: Task CRUD
# ---------------------------------------------------------------------------


async def test_task_create_manual(
    client: AsyncClient, configure_tmp_output: Path
):
    """POST /corpus/{id}/tasks creates a manual task."""
    corpus_id = await _setup_seeded_corpus(configure_tmp_output, client)

    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/tasks",
        json={"label": "New Manual Task", "parent_task_id": "task-a"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["label"] == "New Manual Task"
    assert data["is_manual"] is True
    assert data["parent_task_id"] == "task-a"


async def test_task_delete(
    client: AsyncClient, configure_tmp_output: Path
):
    """DELETE /corpus/{id}/tasks/{task_id} removes a task and orphans its units."""
    corpus_id = await _setup_seeded_corpus(configure_tmp_output, client)

    # Verify task-b exists with a unit
    units_resp = await client.get(f"/api/v1/corpus/{corpus_id}/tasks/task-b/units")
    assert len(units_resp.json()) == 1

    # Delete task-b
    resp = await client.delete(f"/api/v1/corpus/{corpus_id}/tasks/task-b")
    assert resp.status_code == 204

    # Verify task-b no longer exists
    get_resp = await client.get(f"/api/v1/corpus/{corpus_id}/tasks/task-b")
    assert get_resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Hierarchy edits
# ---------------------------------------------------------------------------


async def test_hierarchy_edit_move(
    client: AsyncClient, configure_tmp_output: Path
):
    """POST /corpus/{id}/tasks/hierarchy-edit with move updates parent."""
    corpus_id = await _setup_seeded_corpus(configure_tmp_output, client)

    # Move task-c to be child of task-b instead of task-a
    resp = await client.post(
        f"/api/v1/corpus/{corpus_id}/tasks/hierarchy-edit",
        json={
            "edit_type": "move",
            "source_task_id": "task-c",
            "target_task_id": "task-b",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["edit_type"] == "move"

    # Verify parent changed
    task_resp = await client.get(f"/api/v1/corpus/{corpus_id}/tasks/task-c")
    assert task_resp.json()["parent_task_id"] == "task-b"


# ---------------------------------------------------------------------------
# Tests: Source authority
# ---------------------------------------------------------------------------


async def test_source_authority_upsert(
    client: AsyncClient, configure_tmp_output: Path
):
    """PUT /corpus/{id}/source-authority creates and updates authority."""
    corpus_id = await _setup_seeded_corpus(configure_tmp_output, client)

    # Create
    resp = await client.put(
        f"/api/v1/corpus/{corpus_id}/source-authority",
        json={"source_file": "mauet.md", "authority_level": 9, "author": "Mauet"},
    )
    assert resp.status_code == 200
    assert resp.json()["authority_level"] == 9

    # List
    list_resp = await client.get(f"/api/v1/corpus/{corpus_id}/source-authority")
    assert list_resp.status_code == 200
    sources = list_resp.json()
    assert len(sources) == 1
    assert sources[0]["source_file"] == "mauet.md"

    # Update
    resp2 = await client.put(
        f"/api/v1/corpus/{corpus_id}/source-authority",
        json={"source_file": "mauet.md", "authority_level": 10, "author": "Mauet"},
    )
    assert resp2.json()["authority_level"] == 10

    # Verify only one entry
    list_resp2 = await client.get(f"/api/v1/corpus/{corpus_id}/source-authority")
    assert len(list_resp2.json()) == 1
