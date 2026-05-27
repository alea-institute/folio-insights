"""Phase 4 Plan 02 — global, content-addressed shard IRI registry (§6.3).

Detects the never-expected hex32 collision deterministically and fails closed:
a (source_uri, source_span) that mints an IRI body already stored under a
*different* full SHA-256 is refused (``ShardIRICollision``) rather than
silently overwriting an existing provenance record (D-03 halt+flag, D-04
global content-addressed detection).

Unlike ``services.iri_manager.IRIManager`` (a SEPARATE, per-corpus FOLIO-entity
system that assumes its table pre-exists), this registry OWNS its global DB file
and self-bootstraps ``shard_iri_registry`` with ``CREATE TABLE IF NOT EXISTS`` on
first connect. The aiosqlite direct-SQL / no-ORM access pattern is copied from
``iri_manager.py``; the FOLIO-entity schema and semantics are NOT.

Collision-key contract (consumed from Plan 04-01 ``mint_shard_iri``):
  iri_body  = iri.removeprefix("urn:folio:shard/")   # 32-hex registry key
  full_hash = full 64-hex SHA-256                     # compared for collisions
Same body + same full hash → idempotent re-mint (return existing IRI).
Same body + different full hash → collision (raise, never overwrite).

Concurrency: ``iri_body TEXT NOT NULL UNIQUE`` makes the insert atomic at the DB
layer (T-04-06) — a racing duplicate-body insert fails the UNIQUE constraint
rather than producing two rows. All SQL is parametrized ``?`` (T-04-05).
"""
from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from folio_insights.shards.minting import _IRI_PREFIX, mint_shard_iri

logger = logging.getLogger("folio_insights")

# Default global (NOT per-corpus, D-04) registry DB location. The CLI may pass
# an explicit path; this is the standing default for the nightly verify-iris job.
DEFAULT_REGISTRY_PATH = Path.home() / ".folio-insights" / "shard_iri_registry.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS shard_iri_registry (
    iri_body    TEXT NOT NULL UNIQUE,
    full_hash   TEXT NOT NULL,
    source_uri  TEXT NOT NULL,
    source_span TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_shard_iri_body "
    "ON shard_iri_registry(iri_body)"
)


class ShardIRICollision(Exception):
    """Raised when a (source_uri, source_span) mints a hex32 IRI body that is
    already registered under a DIFFERENT full SHA-256 hash.

    Carries the offending pair plus both full hashes so the halt+flag log and
    the raised error both surface enough for human review (D-03). The registry
    NEVER overwrites the existing row when this is raised (fail closed).
    """

    def __init__(
        self,
        *,
        iri_body: str,
        source_uri: str,
        source_span: str,
        existing_full_hash: str,
        incoming_full_hash: str,
    ) -> None:
        self.iri_body = iri_body
        self.source_uri = source_uri
        self.source_span = source_span
        self.existing_full_hash = existing_full_hash
        self.incoming_full_hash = incoming_full_hash
        super().__init__(
            f"Shard IRI collision on hex32 body {iri_body!r}: "
            f"existing full_hash={existing_full_hash} "
            f"incoming full_hash={incoming_full_hash} "
            f"for (source_uri={source_uri!r}, source_span={source_span!r}). "
            "Refusing to mint (fail closed); existing provenance row NOT overwritten."
        )


class ShardIRIRegistry:
    """Global content-addressed store for minted shard IRIs (D-04).

    Self-bootstraps its table on every connect (the registry owns its DB file).
    """

    def __init__(self, db_path: Path | str = DEFAULT_REGISTRY_PATH) -> None:
        self._db_path = Path(db_path)

    async def _bootstrap(self, db: aiosqlite.Connection) -> None:
        """Self-bootstrap the global table + index on a live connection.

        The registry owns its DB file (D-04), so it creates its own schema
        idempotently on every connect — unlike iri_manager, which assumes a
        pre-existing table.
        """
        db.row_factory = aiosqlite.Row
        await db.execute(_CREATE_TABLE_SQL)
        await db.execute(_CREATE_INDEX_SQL)
        await db.commit()

    async def register(self, source_uri: str, source_span: str) -> str:
        """Mint + register the IRI for (source_uri, source_span); return the IRI.

        Three branches (D-04):
          * body unseen          → INSERT, return minted IRI.
          * body seen, same hash → idempotent, return existing IRI (no write).
          * body seen, diff hash → log both hashes + the pair, raise
                                    ShardIRICollision (fail closed; no overwrite).

        Idempotent on race (T-04-06): if a concurrent ``register()`` inserts the
        same body between our SELECT and INSERT, the ``UNIQUE(iri_body)``
        constraint rejects our duplicate with an ``IntegrityError``. We catch it,
        re-read the now-committed row, and fall through to the same
        idempotent/collision comparison — so a same-pair race returns the
        existing IRI instead of crashing.
        """
        iri, full_hash = mint_shard_iri(source_uri, source_span)
        iri_body = iri.removeprefix(_IRI_PREFIX)

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(self._db_path)) as db:
            await self._bootstrap(db)
            row = await self._fetch_row(db, iri_body)

            if row is None:
                try:
                    await db.execute(
                        "INSERT INTO shard_iri_registry "
                        "(iri_body, full_hash, source_uri, source_span) "
                        "VALUES (?, ?, ?, ?)",
                        (iri_body, full_hash, source_uri, source_span),
                    )
                    await db.commit()
                    return iri
                except aiosqlite.IntegrityError:
                    # A concurrent register() won the UNIQUE(iri_body) race.
                    # Re-read the committed row and resolve against it.
                    await db.rollback()
                    row = await self._fetch_row(db, iri_body)
                    if row is None:
                        raise  # not a body race — surface the real integrity error

            return self._resolve_existing(
                row, iri, iri_body, full_hash, source_uri, source_span
            )

    async def _fetch_row(
        self, db: aiosqlite.Connection, iri_body: str
    ) -> aiosqlite.Row | None:
        """Read the registry row for ``iri_body`` (None if unseen)."""
        cursor = await db.execute(
            "SELECT iri_body, full_hash, source_uri, source_span "
            "FROM shard_iri_registry WHERE iri_body = ?",
            (iri_body,),
        )
        return await cursor.fetchone()

    def _resolve_existing(
        self,
        row: aiosqlite.Row,
        iri: str,
        iri_body: str,
        full_hash: str,
        source_uri: str,
        source_span: str,
    ) -> str:
        """Compare an existing row against the incoming mint: idempotent re-mint
        (same full hash → return IRI) or fail-closed collision (different full
        hash → log both hashes + raise, never overwrite)."""
        existing_full_hash = row["full_hash"]
        if existing_full_hash == full_hash:
            # Idempotent re-mint: same content, same IRI. No write.
            return iri

        # Collision: same hex32 body, different full hash. Halt + flag.
        logger.error(
            "SHARD IRI COLLISION on hex32 body %r: existing full_hash=%s "
            "incoming full_hash=%s for (source_uri=%r, source_span=%r). "
            "Refusing to mint (fail closed); existing row NOT overwritten.",
            iri_body,
            existing_full_hash,
            full_hash,
            source_uri,
            source_span,
        )
        raise ShardIRICollision(
            iri_body=iri_body,
            source_uri=source_uri,
            source_span=source_span,
            existing_full_hash=existing_full_hash,
            incoming_full_hash=full_hash,
        )

    async def all_records(self) -> list[aiosqlite.Row]:
        """Return every stored record so verify-iris can re-mint and compare.

        Each row exposes iri_body, full_hash, source_uri, source_span (D-06 —
        verify-iris reads source_uri/source_span back out to re-mint).
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(self._db_path)) as db:
            await self._bootstrap(db)
            cursor = await db.execute(
                "SELECT iri_body, full_hash, source_uri, source_span "
                "FROM shard_iri_registry ORDER BY iri_body"
            )
            return list(await cursor.fetchall())

    async def _seed_row(
        self,
        iri_body: str,
        full_hash: str,
        source_uri: str,
        source_span: str,
    ) -> None:
        """Insert a row directly (test/seed helper — bypasses minting).

        Used to construct collision scenarios deterministically: seed a known
        hex32 body under a chosen full_hash, then register() a pair that mints
        the same body under a real (different) hash to exercise the fail-closed
        collision branch. Not part of the production mint path.
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(self._db_path)) as db:
            await self._bootstrap(db)
            await db.execute(
                "INSERT INTO shard_iri_registry "
                "(iri_body, full_hash, source_uri, source_span) "
                "VALUES (?, ?, ?, ?)",
                (iri_body, full_hash, source_uri, source_span),
            )
            await db.commit()


__all__ = ["ShardIRICollision", "ShardIRIRegistry", "DEFAULT_REGISTRY_PATH"]
