"""Review-persistence layer (SQLite ``review.db``).

Canonical home for the review schema and discovery persistence so both the CLI
pipeline (``folio_insights.pipeline.discovery.orchestrator``) and the API layer
(``api.services.discovery_runner``) write the same tables. The ``api`` package is
not importable from the installed ``folio-insights`` console script, so the
schema lives here in the library package rather than under ``api/``.
"""

from folio_insights.persistence.review_db import SCHEMA_SQL, persist_discovery

__all__ = ["SCHEMA_SQL", "persist_discovery"]
