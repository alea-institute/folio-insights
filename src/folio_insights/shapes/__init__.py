"""Phase 11 SHACL hybrid: hand-written shapes + Pydantic-generated shapes.

* ``fields`` / ``rendering`` — one field walk; full-fidelity validation graphs.
* ``pydantic_to_shacl`` — the generator (committed output in ``generated/``).
* ``ttl/`` — the six hand-written shapes.
* ``compiled`` — the write-path engine (pyoxigraph-parsed, no rdflib).
* ``corpus`` — ``sh:sparql`` constraints over the corpus projection.
* ``pyshacl_adapter`` — the reference engine (rdflib in-memory only), imported
  lazily by callers that need pyshacl reports.
* ``suite`` — the suite's files, digest and ``default_suite()``.
"""
from __future__ import annotations

from folio_insights.shapes.compiled import ShaclResult, UnsupportedShaclConstruct
from folio_insights.shapes.suite import (
    SUITE_PATHS,
    Report,
    ShaclSuite,
    default_suite,
    suite_digest,
)

__all__ = [
    "SUITE_PATHS",
    "Report",
    "ShaclResult",
    "ShaclSuite",
    "UnsupportedShaclConstruct",
    "default_suite",
    "suite_digest",
]
