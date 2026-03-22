"""IRI generation and SQLite persistence for FOLIO-compatible identifiers.

Reimplements folio-python's FOLIO.generate_iri() algorithm as a standalone
function to avoid loading the full ~18K-concept ontology on every export.
Persists generated IRIs in an iri_registry table for stability across re-exports.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

# FOLIO IRI prefix -- matches folio-python's canonical format
FOLIO_IRI_PREFIX = "https://folio.openlegalstandard.org/"


def generate_folio_iri(existing_iris: set[str]) -> str:
    """Generate a FOLIO-compatible IRI using the WebProtege UUID4 algorithm.

    Reimplements folio-python folio/graph.py lines 2147-2166:
      UUID4 -> base64.urlsafe_b64encode -> rstrip("=") -> filter isalnum
      -> prepend FOLIO IRI prefix.

    Args:
        existing_iris: Set of already-used IRIs to check for collisions.

    Returns:
        A unique FOLIO-format IRI string.

    Raises:
        RuntimeError: If unable to generate a unique IRI after 16 attempts.
    """
    for _ in range(16):
        base_value = uuid.uuid4()
        base64_value = "".join(
            c
            for c in base64.urlsafe_b64encode(base_value.bytes)
            .decode("utf-8")
            .rstrip("=")
            if c.isalnum()
        )
        iri = f"{FOLIO_IRI_PREFIX}{base64_value}"
        if iri not in existing_iris:
            return iri
    raise RuntimeError("Failed to generate a unique IRI after 16 attempts.")


class IRIManager:
    """Manage IRI generation and persistence in SQLite.

    Provides stable IRIs across re-exports by persisting them in an
    iri_registry table. Supports deprecation for edited/replaced entities.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def get_or_create_iri(
        self, entity_id: str, entity_type: str, corpus_name: str
    ) -> str:
        """Return the IRI for an entity, creating one if it doesn't exist.

        If the entity already has a non-deprecated IRI in the registry,
        returns it. Otherwise generates a new FOLIO-compatible IRI,
        persists it, and returns it.
        """
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row

            # Check for existing non-deprecated IRI
            cursor = await db.execute(
                "SELECT iri FROM iri_registry "
                "WHERE entity_id = ? AND deprecated_at IS NULL",
                (entity_id,),
            )
            row = await cursor.fetchone()
            if row is not None:
                return row["iri"]

            # Load all existing IRIs to prevent collisions
            existing = await self._load_existing_iris(db)

            # Generate new IRI
            iri = generate_folio_iri(existing)

            # Persist
            await db.execute(
                "INSERT INTO iri_registry (entity_id, entity_type, iri, corpus_name) "
                "VALUES (?, ?, ?, ?)",
                (entity_id, entity_type, iri, corpus_name),
            )
            await db.commit()
            return iri

    async def deprecate_iri(
        self, entity_id: str, new_entity_id: str
    ) -> None:
        """Mark an entity's IRI as deprecated and link to its successor.

        Sets deprecated_at timestamp and superseded_by to the new entity's IRI.
        """
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row

            # Find the new entity's IRI
            cursor = await db.execute(
                "SELECT iri FROM iri_registry "
                "WHERE entity_id = ? AND deprecated_at IS NULL",
                (new_entity_id,),
            )
            row = await cursor.fetchone()
            new_iri = row["iri"] if row else None

            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "UPDATE iri_registry SET deprecated_at = ?, superseded_by = ? "
                "WHERE entity_id = ? AND deprecated_at IS NULL",
                (now, new_iri, entity_id),
            )
            await db.commit()

    async def load_all_iris(self, corpus_name: str) -> set[str]:
        """Return all non-deprecated IRIs for a corpus."""
        async with aiosqlite.connect(str(self._db_path)) as db:
            cursor = await db.execute(
                "SELECT iri FROM iri_registry "
                "WHERE corpus_name = ? AND deprecated_at IS NULL",
                (corpus_name,),
            )
            rows = await cursor.fetchall()
            return {row[0] for row in rows}

    @staticmethod
    async def _load_existing_iris(db: aiosqlite.Connection) -> set[str]:
        """Load all IRIs (across all corpora) for uniqueness checking."""
        cursor = await db.execute("SELECT iri FROM iri_registry")
        rows = await cursor.fetchall()
        return {row[0] for row in rows}
