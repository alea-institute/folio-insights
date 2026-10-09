"""SQLite connection management via aiosqlite.

Two ways to open a corpus's ``review.db``:

* :func:`get_db` (writes): creates the file and its tables when absent.
* :func:`get_db_read_only` (reads, every GET): never creates a file, a table or a trigger. An
  existing database is opened with SQLite's ``mode=ro``; tables the schema expects but the file
  lacks (an older database) are stood in for by empty connection-local ``TEMP`` tables, so a
  read answers "nothing yet" instead of failing or migrating the file. An absent database reads
  as an empty in-memory one.
"""

from __future__ import annotations

import re
from pathlib import Path

import aiosqlite

from folio_insights.persistence.review_db import SCHEMA_SQL, apply_schema

_CREATE_TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+)\b", re.IGNORECASE)


def _schema_tables() -> dict[str, str]:
    """``{table: CREATE TABLE statement}`` for every table in :data:`SCHEMA_SQL`."""
    tables: dict[str, str] = {}
    for statement in SCHEMA_SQL.split(";"):
        statement = statement.strip()
        match = _CREATE_TABLE.match(statement)
        if match:
            tables[match.group(1)] = statement
    return tables


async def init_db(db_path: Path) -> None:
    """Create tables if they do not exist."""
    new_file = not Path(db_path).exists()
    async with aiosqlite.connect(str(db_path)) as db:
        await apply_schema(db, new_file=new_file)


async def get_db(db_path: Path) -> aiosqlite.Connection:
    """Open a connection to the review database for writing.

    Caller is responsible for closing via ``async with`` or ``.close()``.
    """
    new_file = not Path(db_path).exists()
    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    # Ensure tables exist on first access. On an existing database this writes nothing
    # (every statement is IF NOT EXISTS), so a read-only review.db still opens; the legacy
    # read-only triggers go only into a database created here (see apply_schema).
    try:
        await apply_schema(db, new_file=new_file)
    except BaseException:
        await db.close()
        raise
    return db


async def get_db_read_only(db_path: Path) -> aiosqlite.Connection:
    """Open the review database for reading only; nothing on disk is created or changed.

    Any write through the returned connection fails (``attempt to write a readonly
    database``), so a read path that starts writing is caught rather than silently persisted.
    Caller is responsible for closing the connection.
    """
    path = Path(db_path)
    if not path.is_file():
        db = await aiosqlite.connect(":memory:")
        db.row_factory = aiosqlite.Row
        try:
            await db.executescript(SCHEMA_SQL)
        except BaseException:
            await db.close()
            raise
        return db
    db = await aiosqlite.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    db.row_factory = aiosqlite.Row
    try:
        cursor = await db.execute("SELECT name FROM main.sqlite_master WHERE type = 'table'")
        present = {row[0] for row in await cursor.fetchall()}
        for table, statement in _schema_tables().items():
            if table not in present:
                await db.execute(statement.replace(
                    "CREATE TABLE IF NOT EXISTS", "CREATE TEMP TABLE IF NOT EXISTS", 1))
    except BaseException:
        await db.close()
        raise
    return db
