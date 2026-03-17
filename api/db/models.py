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
"""
