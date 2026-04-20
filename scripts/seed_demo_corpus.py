#!/usr/bin/env python3
"""Seed output/demo/ with a minimal but complete corpus fixture.

Addresses UAT Issue I-4: all bundled review.db files had zero approved
tasks, making end-to-end export validation impossible. This script
rebuilds `output/demo/` deterministically so `folio-insights export demo`
produces real OWL/TTL/JSON-LD/HTML/Markdown artifacts for UAT tests 37-41.

Run:
    python scripts/seed_demo_corpus.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_ID = "demo"
CORPUS_DIR = REPO_ROOT / "output" / CORPUS_ID
SOURCES_DIR = CORPUS_DIR / "sources"
FIXED_TIMESTAMP = "2026-04-19T12:00:00+00:00"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from api.db.models import SCHEMA_SQL  # noqa: E402

SOURCE_MARKDOWN = (
    "# Expert Witness Cross-Examination\n\n"
    "## Chapter 1: Preparation\n\n"
    "Always prepare witnesses thoroughly before direct examination. "
    "Review their prior statements, depositions, and any published works "
    "to identify potential impeachment material.\n\n"
    "## Chapter 2: Impeachment Techniques\n\n"
    "Counsel may use cross-examination to impeach an expert witness "
    "for bias, lack of foundation, or prior inconsistent statements. "
    "File all relevant pretrial motions early to preserve appellate issues.\n"
)

EXTRACTION = {
    "corpus": CORPUS_ID,
    "total_units": 2,
    "units": [
        {
            "id": "unit-demo-001",
            "text": "Always prepare witnesses thoroughly before direct examination.",
            "unit_type": "best_practice",
            "source_file": "demo-advocacy.md",
            "confidence": 0.92,
            "folio_tags": [{
                "iri": "https://folio.openlegalstandard.org/demo-witness-prep",
                "label": "Witness Preparation",
                "confidence": 0.88,
                "extraction_path": "llm",
                "branch": "Litigation",
            }],
            "original_span": {"start": 0, "end": 60, "source_file": "demo-advocacy.md"},
            "source_section": ["Chapter 1: Preparation"],
            "surprise_score": 0.4,
            "content_hash": "demohash001",
            "lineage": "demo-advocacy.md",
            "cross_references": [],
        },
        {
            "id": "unit-demo-002",
            "text": (
                "Counsel may use cross-examination to impeach an expert "
                "witness for bias, lack of foundation, or prior inconsistent statements."
            ),
            "unit_type": "advice",
            "source_file": "demo-advocacy.md",
            "confidence": 0.9,
            "folio_tags": [{
                "iri": "https://folio.openlegalstandard.org/demo-cross-exam",
                "label": "Cross-Examination",
                "confidence": 0.9,
                "extraction_path": "llm",
                "branch": "Litigation",
            }],
            "original_span": {"start": 120, "end": 300, "source_file": "demo-advocacy.md"},
            "source_section": ["Chapter 2: Impeachment Techniques"],
            "surprise_score": 0.6,
            "content_hash": "demohash002",
            "lineage": "demo-advocacy.md",
            "cross_references": [],
        },
    ],
}

TASK_INSERTS = [
    {
        "task_id": "task-demo-001",
        "corpus_name": CORPUS_ID,
        "folio_iri": "https://folio.openlegalstandard.org/demo-witness-prep",
        "label": "Witness Preparation",
        "parent_task_id": None,
        "status": "approved",
        "is_procedural": 1,
        "canonical_order": 1,
    },
    {
        "task_id": "task-demo-002",
        "corpus_name": CORPUS_ID,
        "folio_iri": "https://folio.openlegalstandard.org/demo-cross-exam",
        "label": "Cross-Examine Expert Witness",
        "parent_task_id": "task-demo-001",
        "status": "approved",
        "is_procedural": 1,
        "canonical_order": 2,
    },
]
LINK_INSERTS = [
    ("task-demo-001", "unit-demo-001", CORPUS_ID),
    ("task-demo-002", "unit-demo-002", CORPUS_ID),
]


def seed() -> None:
    if CORPUS_DIR.exists():
        shutil.rmtree(CORPUS_DIR)
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)

    (SOURCES_DIR / "demo-advocacy.md").write_text(SOURCE_MARKDOWN, encoding="utf-8")

    meta = {"id": CORPUS_ID, "name": "Demo", "created_at": FIXED_TIMESTAMP}
    (CORPUS_DIR / "corpus-meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    (CORPUS_DIR / "extraction.json").write_text(
        json.dumps(EXTRACTION, indent=2) + "\n", encoding="utf-8"
    )

    db_path = CORPUS_DIR / "review.db"
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_SQL)
        for t in TASK_INSERTS:
            conn.execute(
                "INSERT INTO task_decisions "
                "(task_id, corpus_name, folio_iri, label, parent_task_id, "
                "status, is_procedural, canonical_order) "
                "VALUES (:task_id, :corpus_name, :folio_iri, :label, "
                ":parent_task_id, :status, :is_procedural, :canonical_order)",
                t,
            )
        for link in LINK_INSERTS:
            conn.execute(
                "INSERT INTO task_unit_links (task_id, unit_id, corpus_name) "
                "VALUES (?, ?, ?)",
                link,
            )
        conn.commit()
    finally:
        conn.close()

    print(f"Seeded {CORPUS_DIR}")
    print(f"  task_decisions: {len(TASK_INSERTS)} approved")
    print(f"  task_unit_links: {len(LINK_INSERTS)}")
    print(f"  extraction units: {len(EXTRACTION['units'])}")


if __name__ == "__main__":
    seed()
