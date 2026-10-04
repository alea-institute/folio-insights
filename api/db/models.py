"""SQLite schema definitions for review persistence.

The canonical schema lives in the library package
(``folio_insights.persistence.review_db``) so the CLI pipeline and this API layer never
drift. Re-exported here for existing importers.
"""

from folio_insights.persistence.review_db import SCHEMA_SQL

__all__ = ["SCHEMA_SQL"]
