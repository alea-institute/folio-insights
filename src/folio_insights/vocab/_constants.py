"""Lightweight vocab constants (Phase 8 WR-01 — Phase 9 split).

Holds the pyoxigraph-free constants from ``folio_insights.vocab``:

  * VOCAB_VERSION — CalVer module constant (Phase 8 D-02).
  * FI_PREFIX     — canonical fi: namespace IRI (Phase 8 D-01).
  * NAMESPACES    — Mapping[str, rdflib.Namespace] of canonical IRIs.

This module exists so downstream callers that only need the version pin
(e.g. ``shards/envelope.py`` for ``fi:VocabPinShape`` enforcement and
``bench/generator.py`` for the vocab_version quad) can import the
constant without forcing a ``pyoxigraph`` import. The parent
``folio_insights.vocab`` package eagerly imports ``pyoxigraph`` at module
top so its loader functions are available; this constants module is
stdlib + rdflib only and stays importable in lightweight environments
(e.g. a standalone schema validator, JVM-free web tier).

Decision references:
  * D-01  — canonical fi: prefix https://folio-insights.aleainstitute.ai/vocab/
  * D-02  — VOCAB_VERSION = "2026.05.0" CalVer YYYY.MM.PATCH
"""

from __future__ import annotations

from collections.abc import Mapping

from rdflib import Namespace

# D-02: CalVer YYYY.MM.PATCH. Patch bumps land as "2026.05.1", "2026.05.2", …
# Every owl:versionIRI in the 5 TTL files must mirror this value.
VOCAB_VERSION: str = "2026.05.0"

# D-01: canonical FOLIO Insights v2 extension namespace (PRD §7.1 verbatim).
FI_PREFIX: str = "https://folio-insights.aleainstitute.ai/vocab/"

# Canonical IRI namespace bindings (promoted from bench/generator.py:51-55).
# rdflib.Namespace objects so SPARQL builders + graph constructors share one
# vocabulary surface.
NAMESPACES: Mapping[str, Namespace] = {
    "fi": Namespace(FI_PREFIX),
    "corpus": Namespace("https://folio-insights.aleainstitute.ai/corpus/"),
    "shard": Namespace("https://folio-insights.aleainstitute.ai/shard/"),
    "concept": Namespace("https://folio-insights.aleainstitute.ai/concept/"),
    "framework": Namespace("https://folio-insights.aleainstitute.ai/framework/"),
}


__all__ = [
    "VOCAB_VERSION",
    "FI_PREFIX",
    "NAMESPACES",
]
