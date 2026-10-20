"""Concurrent first opens of a brand-new journal (the WAL switch must wait like other locks).

SQLite returns ``SQLITE_BUSY`` from ``PRAGMA journal_mode = WAL`` without consulting the busy
handler when another connection is switching the same new file, so two processes opening a new
corpus at once used to fail with ``database is locked`` (reported by the bridge-ingest lane,
``docs/handoffs/2026-10-09-drain-coordination.md``).
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import aiosqlite
import pytest

from folio_insights.storage.journal import Journal


def _lock_the_wal_switch(monkeypatch: pytest.MonkeyPatch, failures: int) -> list[str]:
    """Make the first *failures* WAL pragmas raise the error SQLite gives a racing opener."""
    calls: list[str] = []
    original = aiosqlite.Connection.execute

    def execute(self, sql, parameters=None):  # noqa: ANN001, ANN202
        if sql == "PRAGMA journal_mode = WAL":
            calls.append(sql)
            if len(calls) <= failures:
                async def locked():  # noqa: ANN202
                    raise sqlite3.OperationalError("database is locked")

                return _Awaitable(locked())
        return original(self, sql, parameters)

    monkeypatch.setattr(aiosqlite.Connection, "execute", execute)
    return calls


class _Awaitable:
    def __init__(self, coro) -> None:  # noqa: ANN001
        self._coro = coro

    def __await__(self):  # noqa: ANN204
        return self._coro.__await__()


async def test_open_retries_a_locked_wal_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _lock_the_wal_switch(monkeypatch, failures=3)
    journal = Journal(tmp_path / "journal.sqlite3", busy_timeout_s=5.0)
    await journal.open()
    try:
        assert len(calls) == 4
        rows = await journal.conn.execute_fetchall("PRAGMA journal_mode")
        assert rows[0][0] == "wal"
    finally:
        await journal.close()


async def test_open_gives_up_after_the_busy_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _lock_the_wal_switch(monkeypatch, failures=10**6)
    journal = Journal(tmp_path / "journal.sqlite3", busy_timeout_s=0.2)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        await journal.open()


async def test_open_does_not_retry_other_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = aiosqlite.Connection.execute
    calls: list[str] = []

    def execute(self, sql, parameters=None):  # noqa: ANN001, ANN202
        if sql == "PRAGMA journal_mode = WAL":
            calls.append(sql)

            async def broken():  # noqa: ANN202
                raise sqlite3.OperationalError("disk I/O error")

            return _Awaitable(broken())
        return original(self, sql, parameters)

    monkeypatch.setattr(aiosqlite.Connection, "execute", execute)
    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        await Journal(tmp_path / "journal.sqlite3", busy_timeout_s=5.0).open()
    assert len(calls) == 1


async def test_concurrent_first_opens_all_succeed(tmp_path: Path) -> None:
    async def open_and_close(path: Path) -> None:
        journal = Journal(path)
        await journal.open()
        await journal.close()

    for trial in range(40):
        path = tmp_path / f"c{trial}" / "journal.sqlite3"
        path.parent.mkdir()
        results = await asyncio.gather(
            *(open_and_close(path) for _ in range(12)), return_exceptions=True
        )
        assert [r for r in results if isinstance(r, BaseException)] == []
