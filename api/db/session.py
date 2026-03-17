"""SQLite connection management via aiosqlite."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from api.db.models import SCHEMA_SQL


async def init_db(db_path: Path) -> None:
    """Create tables if they do not exist."""
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(SCHEMA_SQL)


async def get_db(db_path: Path) -> aiosqlite.Connection:
    """Open a connection to the review database.

    Caller is responsible for closing via ``async with`` or ``.close()``.
    """
    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    # Ensure tables exist on first access
    await db.executescript(SCHEMA_SQL)
    return db
