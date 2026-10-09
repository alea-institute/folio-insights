"""Review database schema and discovery persistence (``review.db``, SQLite).

This is the single schema of record for the reviewer database. ``api/db/models.py``
re-exports ``SCHEMA_SQL`` so the API layer and the CLI pipeline never drift, and both
the CLI ``discover`` command (through the discovery orchestrator) and the API discovery
runner persist through ``persist_discovery``. Before this, the CLI wrote JSON but no
``review.db``, so ``export`` found no tasks (B4).

``review.db`` stays a per-corpus SQLite file in the corpus output directory. It holds
mutable reviewer state (statuses, edited labels, notes) that the API routes update in
place, which the append-only Phase 13 corpus journal is not designed to hold; moving it
there would be a separate migration.

Exception: proposed-class decisions. The ``proposed_class_decisions`` table is read-only
legacy. Proposal decisions live in the append-only proposal ledger of the corpus storage
root (``folio_insights.proposals``), which the API route writes and reads. No code writes
the legacy table, and nothing drops it. Its rows reach the ledger only through the explicit
import ``scripts/apply_approvals.py import-legacy`` (``folio_insights.proposals.legacy``),
never on startup; ``read_legacy_proposed_class_rows`` reads them without opening the
database for writing.

``LEGACY_READ_ONLY_TRIGGERS_SQL`` makes the database itself refuse every INSERT, UPDATE and
DELETE on the legacy table. It is installed only where installing it rewrites nothing that
already exists: in a review.db this code creates (``apply_schema(..., new_file=True)``), and
by the explicit ``seal_legacy_proposed_class_table`` (``import-legacy --seal``). Opening an
existing review.db never writes it, so a read-only file still opens and a tracked
review.db is not rewritten by being read.

Signed decisions (drain plan U9, R16). The decision tables (``DECISION_TABLES``:
``review_decisions``, ``task_decisions``, and the ``contradictions`` resolutions and
``hierarchy_edits`` records of reviewer edits) record who authored each decision:
``decided_by`` (the handle a signers file maps the signer to), ``signer_did``,
``decision_signature`` (the signed decision, JSON), ``signature_verified`` (1 only for a
cryptographically valid signature, 0 for an unsigned decision), ``signer_registered`` (1
only when a signers file listed the signer DID; always 0 without one) and ``operator``
(the authenticated API operator who submitted it). ``decision_nonces`` records every
signer nonce a decision consumed, so a signed decision can be recorded once. The migration
(``ensure_decision_signature_schema``) only adds nullable or defaulted columns and a table,
so it is backwards compatible; it is atomic across connections (``BEGIN IMMEDIATE`` with
the column check repeated inside) and runs on the WRITE paths only (and in a database this
code creates): opening an existing review.db still writes nothing, and the read paths ask
``present_signature_columns`` which of the new columns exist before selecting them.
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
    """Persist discovered tasks, task-unit links and contradictions to ``review.db``.

    Creates the database and schema when absent. Re-runs upsert: only machine-owned
    columns change, so a reviewer's ``status``, ``edited_label`` and notes survive
    (``ON CONFLICT ... DO UPDATE``). ``job`` exposes ``task_hierarchy`` (``tasks`` and
    ``task_unit_links``) and ``contradictions``.
    """
    import aiosqlite

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not db_path.exists()

    async with aiosqlite.connect(str(db_path)) as db:
        await apply_schema(db, new_file=new_file)

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
                        INSERT OR IGNORE INTO task_unit_links (task_id, unit_id, corpus_name)
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


LEGACY_READ_ONLY_TRIGGERS_SQL = """\
-- Read-only legacy: proposed-class decisions live in the proposal ledger (see module doc).
CREATE TRIGGER IF NOT EXISTS proposed_class_decisions_read_only_insert
BEFORE INSERT ON proposed_class_decisions
BEGIN
    SELECT RAISE(ABORT, 'proposed_class_decisions is read-only legacy; proposal decisions live in the proposal ledger');
END;
CREATE TRIGGER IF NOT EXISTS proposed_class_decisions_read_only_update
BEFORE UPDATE ON proposed_class_decisions
BEGIN
    SELECT RAISE(ABORT, 'proposed_class_decisions is read-only legacy; proposal decisions live in the proposal ledger');
END;
CREATE TRIGGER IF NOT EXISTS proposed_class_decisions_read_only_delete
BEFORE DELETE ON proposed_class_decisions
BEGIN
    SELECT RAISE(ABORT, 'proposed_class_decisions is read-only legacy; proposal decisions live in the proposal ledger');
END;
"""


async def apply_schema(db: Any, *, new_file: bool) -> None:
    """Create the review.db tables (``SCHEMA_SQL``, a no-op on an existing database) and,
    in a database this call's caller just created, the legacy read-only triggers and the
    signed-decision columns."""
    await db.executescript(SCHEMA_SQL)
    if new_file:
        await db.executescript(LEGACY_READ_ONLY_TRIGGERS_SQL)
        await ensure_decision_signature_schema(db)
        await db.commit()


#: Tables whose rows are review decisions, and the signed-decision columns each gains.
DECISION_TABLES = ("review_decisions", "task_decisions", "contradictions", "hierarchy_edits")
DECISION_SIGNATURE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("decided_by", "TEXT"),
    ("signer_did", "TEXT"),
    ("decision_signature", "TEXT"),
    ("signature_verified", "INTEGER NOT NULL DEFAULT 0"),
    ("signer_registered", "INTEGER NOT NULL DEFAULT 0"),
    ("operator", "TEXT"),
)

DECISION_NONCES_SQL = """\
CREATE TABLE IF NOT EXISTS decision_nonces (
    signer_did TEXT NOT NULL,
    nonce TEXT NOT NULL,
    body_hash TEXT NOT NULL UNIQUE,
    corpus_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    used_at TEXT NOT NULL,
    PRIMARY KEY (signer_did, nonce)
);
"""


class DecisionNonceReused(Exception):
    """A signer nonce (or the same signed body) was already consumed in this review.db."""


async def _columns(db: Any, table: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in await cursor.fetchall()}


async def present_signature_columns(db: Any, table: str) -> tuple[str, ...]:
    """The signed-decision columns ``table`` already has, in ``DECISION_SIGNATURE_COLUMNS``
    order. Read paths select only these (an absent column reads as its default: ``None``
    or 0), so reading never migrates and a partly migrated database still reads."""
    if table not in DECISION_TABLES:
        raise ValueError(f"{table!r} is not a decision table")
    have = await _columns(db, table)
    return tuple(name for name, _ in DECISION_SIGNATURE_COLUMNS if name in have)


async def decision_signature_columns(db: Any, table: str) -> bool:
    """Whether ``table`` already has every signed-decision column (read paths use this
    or ``present_signature_columns`` instead of migrating, so reading never writes)."""
    present = await present_signature_columns(db, table)
    return len(present) == len(DECISION_SIGNATURE_COLUMNS)


async def _signature_schema_missing(db: Any) -> bool:
    for table in DECISION_TABLES:
        if not await decision_signature_columns(db, table):
            return True
    cursor = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'decision_nonces'"
    )
    return await cursor.fetchone() is None


async def _add_missing_signature_schema(db: Any) -> None:
    import sqlite3

    for table in DECISION_TABLES:
        have = await _columns(db, table)
        for name, decl in DECISION_SIGNATURE_COLUMNS:
            if name in have:
                continue
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                # Another writer added it first (a connection outside this transaction
                # discipline). Anything else is a real failure.
                if name not in await _columns(db, table):
                    raise
    # ``execute``, not ``executescript``: the latter would COMMIT an open transaction first.
    await db.execute(DECISION_NONCES_SQL)


async def ensure_decision_signature_schema(db: Any) -> None:
    """Add the signed-decision columns and the ``decision_nonces`` table where missing.

    Idempotent, additive (nullable or defaulted columns only, so existing rows read as
    unsigned, ``signature_verified = 0``) and atomic across connections:

    * When nothing is missing it writes nothing and opens no transaction.
    * Otherwise, on a connection with no open transaction, it takes ``BEGIN IMMEDIATE``
      (the database write lock, waiting on the busy timeout for a concurrent writer),
      repeats the column check inside, adds only what is still missing and COMMITs. A
      second connection migrating at the same time waits, then finds nothing to add.
      The migration is committed on its own, before the caller's decision write: it is
      additive, so committing it even when that write later rolls back is harmless.
    * Inside a transaction the caller already opened (which holds the write lock once
      it has written), it migrates within that transaction and leaves committing to
      the caller.

    A duplicate-column error from a writer outside this discipline is tolerated when the
    column now exists."""
    if not await _signature_schema_missing(db):
        return
    if getattr(db, "in_transaction", False):
        await _add_missing_signature_schema(db)
        return
    await db.execute("BEGIN IMMEDIATE")
    try:
        if await _signature_schema_missing(db):
            await _add_missing_signature_schema(db)
        await db.commit()
    except BaseException:
        if getattr(db, "in_transaction", False):
            await db.rollback()
        raise


async def claim_decision_nonce(
    db: Any,
    *,
    signer_did: str,
    nonce: str,
    body_hash: str,
    corpus_name: str,
    kind: str,
    target: str,
    used_at: str,
) -> None:
    """Consume a signer nonce inside the caller's transaction, or raise
    ``DecisionNonceReused`` when this signer's nonce (or this exact signed body) was
    already used. The caller rolls back on that error, so nothing is written."""
    import sqlite3

    try:
        await db.execute(
            "INSERT INTO decision_nonces (signer_did, nonce, body_hash, corpus_name, kind, "
            "target, used_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (signer_did, nonce, body_hash, corpus_name, kind, target, used_at),
        )
    except sqlite3.IntegrityError:
        raise DecisionNonceReused(
            "this signed decision's nonce was already used; a signed decision can be "
            "recorded once"
        ) from None


def seal_legacy_proposed_class_table(db_path: Path) -> bool:
    """Install the read-only triggers on the legacy table of an existing review.db.

    Explicit and idempotent. Returns ``True`` when triggers were added, ``False`` when the
    database already had them or has no legacy table. Raises ``FileNotFoundError`` for a
    missing file (it never creates one) and ``sqlite3.Error`` for a read-only database."""
    import sqlite3

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"no review database at {path}")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        if "proposed_class_decisions" not in names:
            return False
        wanted = {
            "proposed_class_decisions_read_only_insert",
            "proposed_class_decisions_read_only_update",
            "proposed_class_decisions_read_only_delete",
        }
        if wanted <= names:
            return False
        conn.executescript(LEGACY_READ_ONLY_TRIGGERS_SQL)
        conn.commit()
        return True
    finally:
        conn.close()


LEGACY_PROPOSED_CLASS_COLUMNS = (
    "id", "concept_label", "corpus_name", "status", "reviewer_note", "reviewed_at",
)


def read_legacy_proposed_class_rows(db_path: Path) -> list[dict[str, Any]]:
    """Every row of the legacy ``proposed_class_decisions`` table, ordered by ``id``.

    The database is opened read-only (``mode=ro``), so reading never creates the file,
    the table or the read-only triggers. A missing file raises ``FileNotFoundError``;
    a database without the table returns no rows.
    """
    import sqlite3

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"no review database at {path}")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'proposed_class_decisions'"
        ).fetchone()
        if exists is None:
            return []
        cursor = conn.execute(
            f"SELECT {', '.join(LEGACY_PROPOSED_CLASS_COLUMNS)} "
            "FROM proposed_class_decisions ORDER BY id"
        )
        return [dict(zip(LEGACY_PROPOSED_CLASS_COLUMNS, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


__all__ = [
    "DECISION_NONCES_SQL",
    "DECISION_SIGNATURE_COLUMNS",
    "DECISION_TABLES",
    "DecisionNonceReused",
    "LEGACY_PROPOSED_CLASS_COLUMNS",
    "LEGACY_READ_ONLY_TRIGGERS_SQL",
    "SCHEMA_SQL",
    "apply_schema",
    "claim_decision_nonce",
    "decision_signature_columns",
    "present_signature_columns",
    "ensure_decision_signature_schema",
    "persist_discovery",
    "read_legacy_proposed_class_rows",
    "seal_legacy_proposed_class_table",
]
