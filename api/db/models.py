"""SQLite schema definitions for review persistence."""

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
