"""Review persistence (the per-corpus SQLite ``review.db``).

The canonical home of the reviewer schema and of discovery persistence, so the CLI
pipeline and the API layer write the same tables. It lives in the library package
because the ``api`` package is not importable from the installed console script.
"""

from folio_insights.persistence.review_db import SCHEMA_SQL, persist_discovery

__all__ = ["SCHEMA_SQL", "persist_discovery"]
