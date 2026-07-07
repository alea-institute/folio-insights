"""SQLite schema + discovery persistence for the review database (``review.db``).

This is the single schema of record. ``api/db/models.py`` re-exports ``SCHEMA_SQL``
from here so the API and CLI never drift. ``persist_discovery`` writes the
task/unit-link/contradiction rows that ``export`` (and the reviewer UI) read back;
without it the CLI ``discover`` command produced JSON but never a ``review.db``,
so ``export`` aborted (B4b).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS review_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id TEXT NOT NULL UNIQUE,
    corpus_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unreviewed',
    edited_text TEXT,
    original_text TEXT,
    reviewer_note TEXT DEFAULT '',
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS proposed_class_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_label TEXT NOT NULL,
    corpus_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer_note TEXT DEFAULT '',
    reviewed_at TEXT,
    UNIQUE(concept_label, corpus_name)
);

CREATE INDEX IF NOT EXISTS idx_review_corpus ON review_decisions(corpus_name);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_decisions(status);

CREATE TABLE IF NOT EXISTS task_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    corpus_name TEXT NOT NULL,
    folio_iri TEXT,
    label TEXT NOT NULL,
    parent_task_id TEXT,
    status TEXT NOT NULL DEFAULT 'unreviewed',
    is_procedural INTEGER DEFAULT 0,
    canonical_order INTEGER,
    is_manual INTEGER DEFAULT 0,
    edited_label TEXT,
    reviewer_note TEXT DEFAULT '',
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS task_unit_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    corpus_name TEXT NOT NULL,
    is_canonical INTEGER DEFAULT 0,
    assignment_source TEXT DEFAULT 'discovery',
    confidence REAL DEFAULT 0.0,
    reviewed INTEGER DEFAULT 0,
    UNIQUE(task_id, unit_id)
);

CREATE TABLE IF NOT EXISTS hierarchy_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corpus_name TEXT NOT NULL,
    edit_type TEXT NOT NULL,
    source_task_id TEXT,
    target_task_id TEXT,
    detail TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contradictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    unit_id_a TEXT NOT NULL,
    unit_id_b TEXT NOT NULL,
    corpus_name TEXT NOT NULL,
    nli_score REAL,
    contradiction_type TEXT DEFAULT 'full',
    resolution TEXT,
    resolved_text TEXT,
    resolver_note TEXT DEFAULT '',
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(unit_id_a, unit_id_b, task_id)
);

CREATE TABLE IF NOT EXISTS source_authority (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corpus_name TEXT NOT NULL,
    source_file TEXT NOT NULL,
    authority_level INTEGER DEFAULT 5,
    author TEXT DEFAULT '',
    UNIQUE(corpus_name, source_file)
);

CREATE TABLE IF NOT EXISTS iri_registry (
    entity_id TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    iri TEXT NOT NULL UNIQUE,
    corpus_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    deprecated_at TEXT,
    superseded_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_corpus ON task_decisions(corpus_name);
CREATE INDEX IF NOT EXISTS idx_task_status ON task_decisions(status);
CREATE INDEX IF NOT EXISTS idx_task_parent ON task_decisions(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tul_task ON task_unit_links(task_id);
CREATE INDEX IF NOT EXISTS idx_tul_unit ON task_unit_links(unit_id);
CREATE INDEX IF NOT EXISTS idx_contradiction_task ON contradictions(task_id);
CREATE INDEX IF NOT EXISTS idx_iri_entity ON iri_registry(entity_id);
CREATE INDEX IF NOT EXISTS idx_iri_iri ON iri_registry(iri);
"""


async def persist_discovery(db_path: Path, corpus_name: str, job: Any) -> None:
    """Persist discovered tasks, unit links, and contradictions to ``review.db``.

    Creates the DB (and schema) if absent; upserts on re-run so reviewer edits
    made via the API are not clobbered (``ON CONFLICT ... DO UPDATE`` touches only
    machine-owned columns, leaving ``status``/``edited_label``/notes intact).

    ``job`` is a ``DiscoveryJob`` exposing ``task_hierarchy`` (``.tasks`` and
    ``.task_unit_links``) and ``contradictions``.
    """
    import aiosqlite

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(SCHEMA_SQL)

        if job.task_hierarchy:
            for task in job.task_hierarchy.tasks:
                await db.execute(
                    """
                    INSERT INTO task_decisions
                        (task_id, corpus_name, folio_iri, label, parent_task_id,
                         is_procedural, canonical_order, is_manual)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        folio_iri = excluded.folio_iri,
                        label = excluded.label,
                        parent_task_id = excluded.parent_task_id,
                        is_procedural = excluded.is_procedural,
                        canonical_order = excluded.canonical_order,
                        updated_at = datetime('now')
                    """,
                    (
                        task.id,
                        corpus_name,
                        task.folio_iri,
                        task.label,
                        task.parent_task_id,
                        int(task.is_procedural),
                        task.canonical_order,
                        int(task.is_manual),
                    ),
                )

            for task_id, unit_ids in job.task_hierarchy.task_unit_links.items():
                for uid in unit_ids:
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO task_unit_links
                            (task_id, unit_id, corpus_name)
                        VALUES (?, ?, ?)
                        """,
                        (task_id, uid, corpus_name),
                    )

        for c in job.contradictions:
            await db.execute(
                """
                INSERT INTO contradictions
                    (task_id, unit_id_a, unit_id_b, corpus_name, nli_score,
                     contradiction_type)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(unit_id_a, unit_id_b, task_id) DO UPDATE SET
                    nli_score = excluded.nli_score,
                    contradiction_type = excluded.contradiction_type
                """,
                (
                    c.task_id,
                    c.unit_id_a,
                    c.unit_id_b,
                    corpus_name,
                    c.nli_score,
                    c.contradiction_type,
                ),
            )

        await db.commit()

    logger.info("Persisted discovery results to review.db for corpus '%s'", corpus_name)
