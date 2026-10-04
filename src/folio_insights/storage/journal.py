"""SQLite authoritative journal (Phase 13 KTD1-KTD3, KTD5).

One append-only table holds every committed operation for every corpus:

* ``(corpus, position)`` is the primary key. Positions are contiguous from 0
  per corpus and are the replay order for the RDF projection.
* ``(corpus, op_id)`` is unique: retrying an operation ID returns the original
  commit (same request) or raises ``OperationIdConflict`` (different request).
* ``(corpus, governance_position)`` is unique and contiguous for governance
  events, so the governance log keeps its own 0-based positions.
* ``BEFORE UPDATE`` / ``BEFORE DELETE`` triggers refuse any mutation of a
  committed row (the D-05 third defense-in-depth layer). Insert triggers
  refuse non-contiguous positions and any insert whose ``(corpus, position)``,
  ``(corpus, op_id)`` or ``(corpus, governance_position)`` already exists, so
  ``INSERT OR REPLACE`` cannot delete a committed row through its conflict
  resolution. ``storage_meta`` refuses an insert over an existing key for the
  same reason.

The triggers are created with ``IF NOT EXISTS`` on every open, so a journal
written before a trigger existed gains it on its next open without a schema
version change (no table or column changed). A future
``JOURNAL_SCHEMA_VERSION`` bump must drop and recreate the ``storage_meta``
guards inside its migration transaction, since they refuse every rewrite of
the version row.

Reads outside a write transaction use a separate read-only connection, so they
see only committed rows even while this process holds an open
``BEGIN IMMEDIATE`` on the write connection.

Shard rows keep the U17 adapter's ``original_bytes`` and
``source_schema_version`` next to the current-version ``payload`` written by
``dump_shard_record`` (KTD5). ``original_bytes`` is NULL exactly when the
original bytes are byte-identical to ``payload`` (a current-version record);
readers substitute ``payload`` (``context._stored``), so nothing is lost. Writers serialize through ``BEGIN IMMEDIATE``;
SQLite's write lock covers every corpus in the file, which is a superset of
per-corpus serialization.
"""
from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from folio_insights.storage.errors import OperationIdConflict, UnsupportedStorageSchema

JOURNAL_FILENAME = "journal.sqlite3"
JOURNAL_SCHEMA_VERSION = 1
GOVERNANCE_RECORD_SCHEMA_VERSION = 1

KIND_SHARD = "shard"
KIND_GOVERNANCE = "governance"

_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS storage_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE IF NOT EXISTS journal (
        corpus TEXT NOT NULL,
        position INTEGER NOT NULL CHECK (position >= 0),
        op_id TEXT NOT NULL,
        request_sha256 TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('shard', 'governance')),
        subject TEXT NOT NULL,
        governance_position INTEGER
            CHECK (governance_position IS NULL OR governance_position >= 0),
        record_schema_version INTEGER NOT NULL,
        source_schema_version INTEGER,
        payload BLOB NOT NULL,
        original_bytes BLOB,
        payload_sha256 TEXT NOT NULL,
        committed_at TEXT NOT NULL,
        PRIMARY KEY (corpus, position),
        UNIQUE (corpus, op_id),
        UNIQUE (corpus, governance_position),
        CHECK ((kind = 'governance') = (governance_position IS NOT NULL))
    ) STRICT
    """,
    """
    CREATE INDEX IF NOT EXISTS journal_by_subject
        ON journal (corpus, kind, subject, position)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS journal_refuse_update
    BEFORE UPDATE ON journal
    BEGIN
        SELECT RAISE(ABORT, 'journal is append-only: UPDATE refused');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS journal_refuse_delete
    BEFORE DELETE ON journal
    BEGIN
        SELECT RAISE(ABORT, 'journal is append-only: DELETE refused');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS journal_contiguous_position
    BEFORE INSERT ON journal
    WHEN NEW.position != (
        SELECT COALESCE(MAX(position), -1) + 1 FROM journal WHERE corpus = NEW.corpus
    )
    BEGIN
        SELECT RAISE(ABORT, 'journal position must be contiguous per corpus');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS journal_contiguous_governance_position
    BEFORE INSERT ON journal
    WHEN NEW.governance_position IS NOT NULL AND NEW.governance_position != (
        SELECT COALESCE(MAX(governance_position), -1) + 1
        FROM journal WHERE corpus = NEW.corpus AND kind = 'governance'
    )
    BEGIN
        SELECT RAISE(ABORT, 'governance position must be contiguous per corpus');
    END
    """,
    # v1 of this guard OR-ed three conditions inside one EXISTS, which SQLite
    # answers with a scan of the corpus's rows: bulk ingest was quadratic. v2
    # keeps the same refusal as three indexed probes (the primary key and the
    # two UNIQUE indexes). Existing journals swap v1 for v2 on open.
    "DROP TRIGGER IF EXISTS journal_refuse_replace",
    """
    CREATE TRIGGER IF NOT EXISTS journal_refuse_replace_v2
    BEFORE INSERT ON journal
    WHEN EXISTS (
        SELECT 1 FROM journal WHERE corpus = NEW.corpus AND position = NEW.position
    ) OR EXISTS (
        SELECT 1 FROM journal WHERE corpus = NEW.corpus AND op_id = NEW.op_id
    ) OR (NEW.governance_position IS NOT NULL AND EXISTS (
        SELECT 1 FROM journal
        WHERE corpus = NEW.corpus AND governance_position = NEW.governance_position
    ))
    BEGIN
        SELECT RAISE(ABORT, 'journal is append-only: insert over a committed row refused');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS storage_meta_refuse_replace
    BEFORE INSERT ON storage_meta
    WHEN EXISTS (SELECT 1 FROM storage_meta WHERE key = NEW.key)
    BEGIN
        SELECT RAISE(ABORT, 'storage_meta is append-only: insert over an existing key refused');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS storage_meta_refuse_update
    BEFORE UPDATE ON storage_meta
    BEGIN
        SELECT RAISE(ABORT, 'storage_meta is append-only: UPDATE refused');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS storage_meta_refuse_delete
    BEFORE DELETE ON storage_meta
    BEGIN
        SELECT RAISE(ABORT, 'storage_meta is append-only: DELETE refused');
    END
    """,
)

_COLUMNS = (
    "corpus, position, op_id, request_sha256, kind, subject, governance_position, "
    "record_schema_version, source_schema_version, payload, original_bytes, "
    "payload_sha256, committed_at"
)


# SQLite's default bound-parameter limit is 32766; stay far below it.
_IN_CHUNK = 500


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class JournalRow:
    """One committed journal operation."""

    corpus: str
    position: int
    op_id: str
    request_sha256: str
    kind: str
    subject: str
    governance_position: int | None
    record_schema_version: int
    source_schema_version: int | None
    payload: bytes
    original_bytes: bytes | None
    payload_sha256: str
    committed_at: str


@dataclass(frozen=True)
class PendingRow:
    """A row to append; the transaction assigns the positions."""

    op_id: str
    request_sha256: str
    kind: str
    subject: str
    record_schema_version: int
    payload: bytes
    source_schema_version: int | None = None
    original_bytes: bytes | None = None
    governance_position: int | None = None


def _row(values: tuple) -> JournalRow:
    return JournalRow(*values)


class JournalTransaction:
    """Reads and appends inside one ``BEGIN IMMEDIATE`` write transaction."""

    def __init__(self, conn: aiosqlite.Connection, corpus: str) -> None:
        self._conn = conn
        self.corpus = corpus

    async def find_op(self, op_id: str) -> JournalRow | None:
        rows = await self._conn.execute_fetchall(
            f"SELECT {_COLUMNS} FROM journal WHERE corpus = ? AND op_id = ?",
            (self.corpus, op_id),
        )
        rows = list(rows)
        return _row(tuple(rows[0])) if rows else None

    async def head(self) -> int:
        return await _head(self._conn, self.corpus)

    async def governance_rows(self) -> list[JournalRow]:
        return await _governance_rows(self._conn, self.corpus, None)

    async def latest_shard(self, shard_iri: str) -> JournalRow | None:
        return await _latest_shard(self._conn, self.corpus, shard_iri, None)

    async def latest_shards_for(self, shard_iris: list[str]) -> dict[str, JournalRow]:
        """The newest committed revision of each of ``shard_iris`` (bulk
        ingest: one query per chunk instead of one per record)."""
        out: dict[str, JournalRow] = {}
        unique = list(dict.fromkeys(shard_iris))
        for start in range(0, len(unique), _IN_CHUNK):
            chunk = unique[start : start + _IN_CHUNK]
            marks = ", ".join("?" * len(chunk))
            rows = await self._conn.execute_fetchall(
                f"SELECT {_COLUMNS} FROM journal AS j WHERE corpus = ? AND kind = 'shard' "
                f"AND subject IN ({marks}) AND position = (SELECT MAX(position) FROM "
                "journal WHERE corpus = j.corpus AND kind = 'shard' AND subject = j.subject)",
                (self.corpus, *chunk),
            )
            for values in rows:
                row = _row(tuple(values))
                out[row.subject] = row
        return out

    async def append(self, pending: PendingRow) -> JournalRow:
        return (await self.append_many([pending]))[0]

    async def append_many(self, pendings: list[PendingRow]) -> list[JournalRow]:
        """Append ``pendings`` at the next contiguous positions in one
        ``executemany`` (the insert triggers still check every row)."""
        position = await self.head() + 1
        now = datetime.now(UTC).isoformat()
        rows = [
            (
                self.corpus,
                position + index,
                pending.op_id,
                pending.request_sha256,
                pending.kind,
                pending.subject,
                pending.governance_position,
                pending.record_schema_version,
                pending.source_schema_version,
                pending.payload,
                pending.original_bytes,
                sha256_hex(pending.payload),
                now,
            )
            for index, pending in enumerate(pendings)
        ]
        if rows:
            await self._conn.executemany(
                f"INSERT INTO journal ({_COLUMNS}) VALUES ({', '.join('?' * len(rows[0]))})",
                rows,
            )
        return [_row(values) for values in rows]


async def _head(conn: aiosqlite.Connection, corpus: str) -> int:
    rows = list(
        await conn.execute_fetchall(
            "SELECT COALESCE(MAX(position), -1) FROM journal WHERE corpus = ?", (corpus,)
        )
    )
    return int(rows[0][0])


async def _governance_rows(
    conn: aiosqlite.Connection, corpus: str, upto: int | None
) -> list[JournalRow]:
    bound = "" if upto is None else " AND position <= ?"
    params: tuple = (corpus,) if upto is None else (corpus, upto)
    rows = await conn.execute_fetchall(
        f"SELECT {_COLUMNS} FROM journal WHERE corpus = ? AND kind = 'governance'"
        f"{bound} ORDER BY governance_position",
        params,
    )
    return [_row(tuple(r)) for r in rows]


async def _latest_shard(
    conn: aiosqlite.Connection, corpus: str, shard_iri: str, upto: int | None
) -> JournalRow | None:
    bound = "" if upto is None else " AND position <= ?"
    params: tuple = (corpus, shard_iri) if upto is None else (corpus, shard_iri, upto)
    rows = list(
        await conn.execute_fetchall(
            f"SELECT {_COLUMNS} FROM journal WHERE corpus = ? AND kind = 'shard' "
            f"AND subject = ?{bound} ORDER BY position DESC LIMIT 1",
            params,
        )
    )
    return _row(tuple(rows[0])) if rows else None


class Journal:
    """An open connection to ``<root>/journal.sqlite3``."""

    def __init__(self, path: Path, *, busy_timeout_s: float = 30.0) -> None:
        self.path = path
        self._busy_timeout_s = busy_timeout_s
        self._conn: aiosqlite.Connection | None = None
        self._read_conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        """The write connection (``BEGIN IMMEDIATE`` transactions only)."""
        if self._conn is None:
            raise RuntimeError("journal is not open")
        return self._conn

    @property
    def read_conn(self) -> aiosqlite.Connection:
        """The read-only connection: sees committed rows only, never this
        process's open write transaction."""
        if self._read_conn is None:
            raise RuntimeError("journal is not open")
        return self._read_conn

    async def open(self) -> None:
        conn = await aiosqlite.connect(
            self.path, isolation_level=None, timeout=self._busy_timeout_s
        )
        try:
            await conn.execute(f"PRAGMA busy_timeout = {int(self._busy_timeout_s * 1000)}")
            await conn.execute("PRAGMA journal_mode = WAL")
            await conn.execute("PRAGMA synchronous = FULL")
            await conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in _DDL:
                    await conn.execute(statement)
                rows = list(
                    await conn.execute_fetchall(
                        "SELECT value FROM storage_meta WHERE key = 'journal_schema_version'"
                    )
                )
                if not rows:
                    await conn.execute(
                        "INSERT INTO storage_meta (key, value) VALUES "
                        "('journal_schema_version', ?)",
                        (str(JOURNAL_SCHEMA_VERSION),),
                    )
                elif rows[0][0] != str(JOURNAL_SCHEMA_VERSION):
                    raise UnsupportedStorageSchema(
                        f"journal schema version {rows[0][0]!r} is not supported "
                        f"(this code reads {JOURNAL_SCHEMA_VERSION})"
                    )
                await conn.execute("COMMIT")
            except BaseException:
                await conn.execute("ROLLBACK")
                raise
        except BaseException:
            await conn.close()
            raise
        try:
            read_conn = await aiosqlite.connect(
                self.path, isolation_level=None, timeout=self._busy_timeout_s
            )
        except BaseException:
            await conn.close()
            raise
        try:
            await read_conn.execute(
                f"PRAGMA busy_timeout = {int(self._busy_timeout_s * 1000)}"
            )
            await read_conn.execute("PRAGMA query_only = ON")
        except BaseException:
            await read_conn.close()
            await conn.close()
            raise
        self._conn = conn
        self._read_conn = read_conn

    async def close(self) -> None:
        if self._read_conn is not None:
            read_conn, self._read_conn = self._read_conn, None
            await read_conn.close()
        if self._conn is not None:
            conn, self._conn = self._conn, None
            await conn.close()

    @asynccontextmanager
    async def write(self, corpus: str) -> AsyncIterator[JournalTransaction]:
        """``BEGIN IMMEDIATE`` ... ``COMMIT``; any exception, including a
        failed ``COMMIT``, rolls back so the connection is never left inside
        an open transaction."""
        conn = self.conn
        await conn.execute("BEGIN IMMEDIATE")
        try:
            yield JournalTransaction(conn, corpus)
            await conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                await conn.execute("ROLLBACK")
            raise

    async def head(self, corpus: str) -> int:
        return await _head(self.read_conn, corpus)

    async def find_op(self, corpus: str, op_id: str) -> JournalRow | None:
        """The committed row for ``op_id`` (read connection: committed rows only)."""
        rows = list(
            await self.read_conn.execute_fetchall(
                f"SELECT {_COLUMNS} FROM journal WHERE corpus = ? AND op_id = ?",
                (corpus, op_id),
            )
        )
        return _row(tuple(rows[0])) if rows else None

    async def row_at(self, corpus: str, position: int) -> JournalRow | None:
        """The committed row at ``(corpus, position)``, or ``None``."""
        rows = list(
            await self.read_conn.execute_fetchall(
                f"SELECT {_COLUMNS} FROM journal WHERE corpus = ? AND position = ?",
                (corpus, position),
            )
        )
        return _row(tuple(rows[0])) if rows else None

    async def chain_rows(self, corpus: str, *, after: int, upto: int) -> list[JournalRow]:
        """Rows ``after < position <= upto`` with only the chain-digest columns
        populated (position, op_id, payload_sha256, committed_at)."""
        rows = await self.read_conn.execute_fetchall(
            "SELECT position, op_id, payload_sha256, committed_at FROM journal "
            "WHERE corpus = ? AND position > ? AND position <= ? ORDER BY position",
            (corpus, after, upto),
        )
        return [
            JournalRow(corpus, int(r[0]), str(r[1]), "", "", "", None, 0, None, b"", None,
                       str(r[2]), str(r[3]))
            for r in rows
        ]

    async def corpora(self) -> list[str]:
        """Every corpus with at least one committed row, sorted."""
        rows = await self.read_conn.execute_fetchall(
            "SELECT DISTINCT corpus FROM journal ORDER BY corpus"
        )
        return [str(r[0]) for r in rows]

    async def rows_after(
        self, corpus: str, after: int, *, limit: int, with_original: bool = True
    ) -> list[JournalRow]:
        """Rows past ``after`` in position order. ``with_original=False``
        leaves ``original_bytes`` unread (``None``): the projection replays
        the current-version ``payload`` only."""
        columns = _COLUMNS if with_original else _COLUMNS.replace(
            "original_bytes", "NULL AS original_bytes"
        )
        rows = await self.read_conn.execute_fetchall(
            f"SELECT {columns} FROM journal WHERE corpus = ? AND position > ? "
            "ORDER BY position LIMIT ?",
            (corpus, after, limit),
        )
        return [_row(tuple(r)) for r in rows]

    async def governance_rows(self, corpus: str, *, upto: int | None) -> list[JournalRow]:
        return await _governance_rows(self.read_conn, corpus, upto)

    async def governance_row_at(
        self, corpus: str, governance_position: int, *, upto: int | None
    ) -> JournalRow | None:
        bound = "" if upto is None else " AND position <= ?"
        params: tuple = (
            (corpus, governance_position)
            if upto is None
            else (corpus, governance_position, upto)
        )
        rows = list(
            await self.read_conn.execute_fetchall(
                f"SELECT {_COLUMNS} FROM journal WHERE corpus = ? AND kind = 'governance' "
                f"AND governance_position = ?{bound}",
                params,
            )
        )
        return _row(tuple(rows[0])) if rows else None

    async def latest_governance_position(self, corpus: str, *, upto: int | None) -> int:
        bound = "" if upto is None else " AND position <= ?"
        params: tuple = (corpus,) if upto is None else (corpus, upto)
        rows = list(
            await self.read_conn.execute_fetchall(
                "SELECT COALESCE(MAX(governance_position), -1) FROM journal "
                f"WHERE corpus = ? AND kind = 'governance'{bound}",
                params,
            )
        )
        return int(rows[0][0])

    async def latest_shard(
        self, corpus: str, shard_iri: str, *, upto: int | None
    ) -> JournalRow | None:
        return await _latest_shard(self.read_conn, corpus, shard_iri, upto)

    async def latest_shards(self, corpus: str, *, upto: int) -> list[JournalRow]:
        """The newest revision of every shard in ``corpus`` at ``position <= upto``."""
        rows = await self.read_conn.execute_fetchall(
            f"SELECT {_COLUMNS} FROM journal AS j WHERE corpus = ? AND kind = 'shard' "
            "AND position = (SELECT MAX(position) FROM journal WHERE corpus = j.corpus "
            "AND kind = 'shard' AND subject = j.subject AND position <= ?) "
            "ORDER BY subject",
            (corpus, upto),
        )
        return [_row(tuple(r)) for r in rows]


def committed_corpora(path: Path) -> list[str]:
    """Corpora with at least one committed row in the journal at ``path``,
    read-only (never creates the file). An absent journal has none."""
    import sqlite3

    if not path.is_file():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [str(r[0]) for r in conn.execute(
            "SELECT DISTINCT corpus FROM journal ORDER BY corpus"
        )]
    finally:
        conn.close()


def check_replay(existing: JournalRow, request_sha256: str) -> JournalRow:
    """Return ``existing`` for an identical retry; refuse a reused operation ID."""
    if existing.request_sha256 != request_sha256:
        raise OperationIdConflict(
            f"operation ID {existing.op_id!r} was already committed at position "
            f"{existing.position} for a different request"
        )
    return existing


__all__ = [
    "GOVERNANCE_RECORD_SCHEMA_VERSION",
    "JOURNAL_FILENAME",
    "JOURNAL_SCHEMA_VERSION",
    "KIND_GOVERNANCE",
    "KIND_SHARD",
    "Journal",
    "JournalRow",
    "JournalTransaction",
    "PendingRow",
    "check_replay",
    "committed_corpora",
    "sha256_hex",
]
