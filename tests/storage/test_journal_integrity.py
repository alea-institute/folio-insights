"""Journal integrity: append-only triggers, unique positions, schema refusal."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from folio_insights.storage import CorpusStorageContext, UnsupportedStorageSchema
from folio_insights.storage.journal import JOURNAL_FILENAME

from tests.storage.conftest import genesis, shard

pytestmark = pytest.mark.storage


async def _seed(root: Path, admin) -> None:
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        await ctx.governance.append(genesis("corpus-a", admin))
        s = shard(1)
        await ctx.shards.put(s.shard_iri, s)
    finally:
        await ctx.close()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE journal SET payload = x'00' WHERE position = 0",
        "UPDATE journal SET position = 9 WHERE position = 1",
        "DELETE FROM journal WHERE position = 1",
        "DELETE FROM journal",
        "UPDATE storage_meta SET value = '2'",
        "DELETE FROM storage_meta",
    ],
)
async def test_committed_rows_refuse_update_and_delete(
    storage_root: Path, admin, statement: str
) -> None:
    await _seed(storage_root, admin)
    conn = sqlite3.connect(storage_root / JOURNAL_FILENAME)
    try:
        before = conn.execute("SELECT * FROM journal ORDER BY position").fetchall()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(statement)
        conn.rollback()
        after = conn.execute("SELECT * FROM journal ORDER BY position").fetchall()
        assert after == before
    finally:
        conn.close()


async def test_positions_are_unique_and_contiguous(storage_root: Path, admin) -> None:
    await _seed(storage_root, admin)
    conn = sqlite3.connect(storage_root / JOURNAL_FILENAME)
    try:
        row = conn.execute("SELECT * FROM journal WHERE position = 1").fetchone()
        for position in (1, 5):  # duplicate, then a gap
            forged = list(row)
            forged[1] = position
            forged[2] = f"forged-op-{position}"
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    f"INSERT INTO journal VALUES ({', '.join('?' * len(forged))})", forged
                )
            conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == 2
    finally:
        conn.close()


async def test_unsupported_journal_schema_is_refused(storage_root: Path) -> None:
    storage_root.mkdir(parents=True)
    conn = sqlite3.connect(storage_root / JOURNAL_FILENAME)
    conn.execute("CREATE TABLE storage_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT")
    conn.execute("INSERT INTO storage_meta VALUES ('journal_schema_version', '99')")
    conn.commit()
    conn.close()
    with pytest.raises(UnsupportedStorageSchema, match="99"):
        await CorpusStorageContext.open(storage_root, "corpus-a")
