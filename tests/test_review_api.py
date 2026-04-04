"""Tests for the folio-insights Review Viewer API."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api import main as api_main
from api.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sample_units() -> list[dict]:
    """Return a minimal set of sample knowledge units."""
    return [
        {
            "id": "unit-001",
            "text": "Lock expert into reviewed-document list during deposition.",
            "original_span": {"start": 100, "end": 200, "source_file": "expert.md"},
            "unit_type": "advice",
            "source_file": "expert.md",
            "source_section": ["Chapter 8", "Expert Witnesses"],
            "folio_tags": [
                {
                    "iri": "https://folio.example.org/CrossExamination",
                    "label": "Cross-Examination",
                    "confidence": 0.92,
                    "extraction_path": "entity_ruler",
                    "branch": "Civil Procedure",
                }
            ],
            "surprise_score": 0.7,
            "confidence": 0.92,
            "content_hash": "abc123",
            "lineage": [],
            "cross_references": [],
        },
        {
            "id": "unit-002",
            "text": "Always prepare a timeline of key events before depositions.",
            "original_span": {"start": 300, "end": 400, "source_file": "depo.md"},
            "unit_type": "advice",
            "source_file": "depo.md",
            "source_section": ["Chapter 3", "Depositions"],
            "folio_tags": [
                {
                    "iri": "https://folio.example.org/Deposition",
                    "label": "Deposition",
                    "confidence": 0.85,
                    "extraction_path": "llm",
                    "branch": "Civil Procedure",
                }
            ],
            "surprise_score": 0.3,
            "confidence": 0.85,
            "content_hash": "def456",
            "lineage": [],
            "cross_references": [],
        },
        {
            "id": "unit-003",
            "text": "Consider Daubert challenges early in litigation strategy.",
            "original_span": {"start": 500, "end": 600, "source_file": "strategy.md"},
            "unit_type": "principle",
            "source_file": "strategy.md",
            "source_section": ["Chapter 1", "Strategy"],
            "folio_tags": [
                {
                    "iri": "https://folio.example.org/CrossExamination",
                    "label": "Cross-Examination",
                    "confidence": 0.65,
                    "extraction_path": "semantic",
                    "branch": "Civil Procedure",
                }
            ],
            "surprise_score": 0.5,
            "confidence": 0.65,
            "content_hash": "ghi789",
            "lineage": [],
            "cross_references": [],
        },
        {
            "id": "unit-004",
            "text": "Unreliable technique flagged for deep review.",
            "original_span": {"start": 700, "end": 800, "source_file": "expert.md"},
            "unit_type": "pitfall",
            "source_file": "expert.md",
            "source_section": ["Chapter 8", "Pitfalls"],
            "folio_tags": [
                {
                    "iri": "https://folio.example.org/CrossExamination",
                    "label": "Cross-Examination",
                    "confidence": 0.35,
                    "extraction_path": "heading_context",
                    "branch": "Civil Procedure",
                }
            ],
            "surprise_score": 0.9,
            "confidence": 0.35,
            "content_hash": "jkl012",
            "lineage": [],
            "cross_references": [],
        },
    ]


@pytest.fixture()
def tmp_output(tmp_path: Path):
    """Configure API to use a temp directory for output."""
    corpus_dir = tmp_path / "default"
    corpus_dir.mkdir()

    # Write sample extraction JSON
    extraction = {
        "corpus": "default",
        "generated_at": "2026-03-17T00:00:00Z",
        "total_units": 4,
        "by_confidence": {"high": 2, "medium": 1, "low": 1},
        "units": _sample_units(),
    }
    (corpus_dir / "extraction.json").write_text(json.dumps(extraction))

    # Configure API
    api_main.configure(output_dir=tmp_path, corpus_name="default")
    api_main._extraction_data.clear()
    api_main.load_extraction("default")
    return tmp_path


@pytest.fixture()
def client(tmp_output) -> TestClient:
    """FastAPI test client with sample data loaded."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_tree_endpoint(client: TestClient):
    """GET /api/v1/tree returns concept tree with unit counts."""
    resp = client.get("/api/v1/tree", params={"corpus": "default"})
    assert resp.status_code == 200
    tree = resp.json()
    assert len(tree) >= 1  # at least one branch

    # First node should be "All Units"
    all_units_node = tree[0]
    assert all_units_node["iri"] == "__all__"
    assert all_units_node["label"] == "All Units"
    assert all_units_node["unit_count"] == 4

    # Find concept nodes in branch children
    all_children = []
    for branch_node in tree:
        assert "unit_count" in branch_node
        assert "children" in branch_node
        all_children.extend(branch_node["children"])

    # Cross-Examination should have 3 units (unit-001, unit-003, unit-004)
    xexam = next((c for c in all_children if c["label"] == "Cross-Examination"), None)
    assert xexam is not None
    assert xexam["unit_count"] == 3


def test_tree_all_units_untagged(tmp_path: Path):
    """Tree includes 'All Units' and no 'Untagged' when ALL units lack folio_tags."""
    corpus_dir = tmp_path / "nofolio"
    corpus_dir.mkdir()
    extraction = {
        "corpus": "nofolio",
        "total_units": 2,
        "units": [
            {"id": "u1", "text": "Hello", "folio_tags": [], "confidence": 0.0,
             "unit_type": "advice", "original_span": {}, "source_file": "",
             "source_section": [], "surprise_score": 0.0, "content_hash": "a",
             "lineage": [], "cross_references": []},
            {"id": "u2", "text": "World", "folio_tags": [], "confidence": 0.0,
             "unit_type": "advice", "original_span": {}, "source_file": "",
             "source_section": [], "surprise_score": 0.0, "content_hash": "b",
             "lineage": [], "cross_references": []},
        ],
    }
    (corpus_dir / "extraction.json").write_text(json.dumps(extraction))

    api_main.configure(output_dir=tmp_path, corpus_name="nofolio")
    api_main._extraction_data.clear()
    api_main.load_extraction("nofolio")

    client = TestClient(app)
    resp = client.get("/api/v1/tree", params={"corpus": "nofolio"})
    assert resp.status_code == 200
    tree = resp.json()

    # Should have exactly one node: "All Units"
    assert len(tree) == 1
    assert tree[0]["iri"] == "__all__"
    assert tree[0]["label"] == "All Units"
    assert tree[0]["unit_count"] == 2

    # No "Untagged" node when ALL units are untagged (no concept branches to contrast)
    labels = [n["label"] for n in tree]
    assert "Untagged" not in labels


def test_units_all_iri(client: TestClient):
    """GET /api/v1/units with concept_iri=__all__ returns all units."""
    resp = client.get(
        "/api/v1/units",
        params={"corpus": "default", "concept_iri": "__all__"},
    )
    assert resp.status_code == 200
    units = resp.json()
    assert len(units) == 4  # all sample units


def test_units_untagged_iri(tmp_path: Path):
    """GET /api/v1/units with concept_iri=__untagged__ returns only untagged units."""
    corpus_dir = tmp_path / "mixed"
    corpus_dir.mkdir()
    extraction = {
        "corpus": "mixed",
        "total_units": 3,
        "units": [
            {"id": "tagged", "text": "Tagged", "folio_tags": [
                {"iri": "http://example.org/A", "label": "A", "confidence": 0.9,
                 "extraction_path": "llm", "branch": "B"}
            ], "confidence": 0.9, "unit_type": "advice", "original_span": {},
             "source_file": "", "source_section": [], "surprise_score": 0.0,
             "content_hash": "c", "lineage": [], "cross_references": []},
            {"id": "untagged1", "text": "Untagged 1", "folio_tags": [],
             "confidence": 0.0, "unit_type": "advice", "original_span": {},
             "source_file": "", "source_section": [], "surprise_score": 0.0,
             "content_hash": "d", "lineage": [], "cross_references": []},
            {"id": "untagged2", "text": "Untagged 2", "folio_tags": [],
             "confidence": 0.0, "unit_type": "advice", "original_span": {},
             "source_file": "", "source_section": [], "surprise_score": 0.0,
             "content_hash": "e", "lineage": [], "cross_references": []},
        ],
    }
    (corpus_dir / "extraction.json").write_text(json.dumps(extraction))

    api_main.configure(output_dir=tmp_path, corpus_name="mixed")
    api_main._extraction_data.clear()
    api_main.load_extraction("mixed")

    client = TestClient(app)

    # __untagged__ returns only untagged
    resp = client.get(
        "/api/v1/units",
        params={"corpus": "mixed", "concept_iri": "__untagged__"},
    )
    assert resp.status_code == 200
    units = resp.json()
    assert len(units) == 2
    ids = {u["id"] for u in units}
    assert ids == {"untagged1", "untagged2"}

    # __all__ returns everything
    resp_all = client.get(
        "/api/v1/units",
        params={"corpus": "mixed", "concept_iri": "__all__"},
    )
    assert len(resp_all.json()) == 3


def test_units_endpoint(client: TestClient):
    """GET /api/v1/units with concept_iri filter returns matching units."""
    resp = client.get(
        "/api/v1/units",
        params={"corpus": "default", "concept_iri": "https://folio.example.org/Deposition"},
    )
    assert resp.status_code == 200
    units = resp.json()
    assert len(units) == 1
    assert units[0]["id"] == "unit-002"
    assert units[0]["review_status"] == "unreviewed"


def test_review_approve(client: TestClient):
    """POST review with status=approved persists and appears in GET."""
    # Approve unit-001
    resp = client.post(
        "/api/v1/units/unit-001/review",
        params={"corpus": "default"},
        json={"status": "approved"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["review_status"] == "approved"

    # Verify it persists on GET
    resp2 = client.get(
        "/api/v1/units",
        params={"corpus": "default", "concept_iri": "https://folio.example.org/CrossExamination"},
    )
    approved = [u for u in resp2.json() if u["id"] == "unit-001"]
    assert len(approved) == 1
    assert approved[0]["review_status"] == "approved"


def test_review_edit(client: TestClient):
    """POST review with status=edited stores edited text and preserves original."""
    edited_text = "Lock expert into reviewed documents during depo (revised)."
    resp = client.post(
        "/api/v1/units/unit-001/review",
        params={"corpus": "default"},
        json={"status": "edited", "edited_text": edited_text, "note": "minor clarification"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["review_status"] == "edited"
    assert data["edited_text"] == edited_text
    assert data["reviewer_note"] == "minor clarification"


def test_review_persist(tmp_output: Path):
    """Review decisions persist in SQLite across client instances."""
    # Client 1: approve a unit
    client1 = TestClient(app)
    resp = client1.post(
        "/api/v1/units/unit-002/review",
        params={"corpus": "default"},
        json={"status": "approved"},
    )
    assert resp.status_code == 200

    # Client 2: fresh client, verify still approved
    client2 = TestClient(app)
    resp2 = client2.get(
        "/api/v1/units",
        params={"corpus": "default", "concept_iri": "https://folio.example.org/Deposition"},
    )
    units = resp2.json()
    assert len(units) == 1
    assert units[0]["review_status"] == "approved"


def test_bulk_approve(client: TestClient):
    """POST bulk-approve with confidence_min approves all high-confidence units."""
    resp = client.post(
        "/api/v1/units/bulk-approve",
        params={"corpus": "default"},
        json={"confidence_min": 0.8},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved_count"] == 2  # unit-001 (0.92) and unit-002 (0.85)

    # Verify via stats
    stats = client.get("/api/v1/review/stats", params={"corpus": "default"}).json()
    assert stats["approved"] == 2


def test_review_stats(client: TestClient):
    """GET /api/v1/review/stats returns correct counts after mixed reviews."""
    # Approve one
    client.post(
        "/api/v1/units/unit-001/review",
        params={"corpus": "default"},
        json={"status": "approved"},
    )
    # Reject one
    client.post(
        "/api/v1/units/unit-003/review",
        params={"corpus": "default"},
        json={"status": "rejected"},
    )
    # Edit one
    client.post(
        "/api/v1/units/unit-004/review",
        params={"corpus": "default"},
        json={"status": "edited", "edited_text": "Revised pitfall."},
    )

    resp = client.get("/api/v1/review/stats", params={"corpus": "default"})
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["total"] == 4
    assert stats["approved"] == 1
    assert stats["rejected"] == 1
    assert stats["edited"] == 1
    assert stats["unreviewed"] == 1
    assert stats["by_confidence"]["high"] == 2
    assert stats["by_confidence"]["medium"] == 1
    assert stats["by_confidence"]["low"] == 1


def test_source_context(client: TestClient, tmp_output: Path):
    """GET /api/v1/source with valid file returns text with context window."""
    # Create a sample source file
    source_file = tmp_output / "expert.md"
    content = "x" * 200 + "THE SPAN TEXT HERE" + "y" * 200
    source_file.write_text(content)

    resp = client.get(
        "/api/v1/source",
        params={"file": str(source_file), "start": 200, "end": 218},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is True
    assert "THE SPAN TEXT HERE" in data["text"]
    assert data["file_path"] == str(source_file)


def test_source_missing(client: TestClient):
    """GET /api/v1/source with nonexistent file returns found=false."""
    resp = client.get(
        "/api/v1/source",
        params={"file": "/nonexistent/file.md", "start": 0, "end": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is False
    assert "not available" in data["message"]


def test_confidence_filter(client: TestClient):
    """GET /api/v1/units with confidence=high returns only high-confidence units."""
    resp = client.get(
        "/api/v1/units",
        params={"corpus": "default", "confidence": "high"},
    )
    assert resp.status_code == 200
    units = resp.json()
    assert len(units) == 2  # unit-001 (0.92) and unit-002 (0.85)
    for u in units:
        assert u["confidence"] >= 0.8

    # Medium
    resp_med = client.get(
        "/api/v1/units",
        params={"corpus": "default", "confidence": "medium"},
    )
    medium_units = resp_med.json()
    assert len(medium_units) == 1
    assert medium_units[0]["id"] == "unit-003"

    # Low
    resp_low = client.get(
        "/api/v1/units",
        params={"corpus": "default", "confidence": "low"},
    )
    low_units = resp_low.json()
    assert len(low_units) == 1
    assert low_units[0]["id"] == "unit-004"
