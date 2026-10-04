"""SQLite connection management via aiosqlite."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from folio_insights.persistence.review_db import apply_schema


async def init_db(db_path: Path) -> None:
    """Create tables if they do not exist."""
    new_file = not Path(db_path).exists()
    async with aiosqlite.connect(str(db_path)) as db:
        await apply_schema(db, new_file=new_file)


async def get_db(db_path: Path) -> aiosqlite.Connection:
    """Open a connection to the review database.

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
