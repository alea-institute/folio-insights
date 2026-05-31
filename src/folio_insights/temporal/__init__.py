"""Phase 8 temporal/ — rdflib-native valid-time query surface (VOCAB-05).

D-10 / D-04 dep-leak discipline: this package imports rdflib + stdlib ONLY.
NO pyoxigraph, oxrdflib, pyshacl; NO cross-coupling to
``folio_insights.{vocab, revision, store, governance}``. Phase 11 widens
``query_as_of`` to ``Graph | Store`` polymorphic when the persistent
pyoxigraph store lands — until then the surface stays rdflib-native so
downstream consumers can quarantine which subsystem owns which RDF library.

D-11: the user-facing ``--as-of <date>`` CLI flag and the Phase 12 UI date
picker are explicitly OUT of Phase 8 scope. ``docs/query-as-of.md`` cross-
references the Phase 11/12 placeholder where the surface ships.
"""

from __future__ import annotations

from folio_insights.temporal.as_of import query_as_of

__all__ = ["query_as_of"]
