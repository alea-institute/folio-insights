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
from urllib.parse import quote

from rdflib import Namespace

# D-02: CalVer YYYY.MM.PATCH. Patch bumps land as "2026.05.1", "2026.05.2", …
# Every owl:versionIRI in the 5 TTL files must mirror this value.
VOCAB_VERSION: str = "2026.05.0"

# D-01: canonical FOLIO Insights v2 extension namespace (PRD §7.1 verbatim).
FI_PREFIX: str = "https://folio-insights.aleainstitute.ai/vocab/"

# Framework IRIs (Phase 9 U0 / KTD3): ``FRAMEWORK_NS + quote(framework_id)``.
FRAMEWORK_NS: str = "https://folio-insights.aleainstitute.ai/framework/"

# Canonical IRI namespace bindings (promoted from bench/generator.py:51-55).
# rdflib.Namespace objects so SPARQL builders + graph constructors share one
# vocabulary surface.
NAMESPACES: Mapping[str, Namespace] = {
    "fi": Namespace(FI_PREFIX),
    "corpus": Namespace("https://folio-insights.aleainstitute.ai/corpus/"),
    "shard": Namespace("https://folio-insights.aleainstitute.ai/shard/"),
    "concept": Namespace("https://folio-insights.aleainstitute.ai/concept/"),
    "framework": Namespace(FRAMEWORK_NS),
}


def framework_iri(framework_id: str) -> str:
    """The IRI of a framework (``fi:Framework`` individual) for an envelope
    ``framework_id``. Percent-encodes every reserved character, so the result
    is a valid IRI for any identifier string; a pattern-valid ID
    (``us.federal.fre``) maps to ``<framework-ns>us.federal.fre`` unchanged.
    The empty identifier has no framework IRI (it would be the namespace
    itself) and raises ``ValueError``."""
    if not framework_id:
        raise ValueError("an empty framework_id has no framework IRI")
    return FRAMEWORK_NS + quote(framework_id, safe="")


# TBox revision marker (Phase 9 review): the shipped TBox's entailments changed
# in Phase 9 U0 (EL layer split, fi:inFramework subPropertyOf) while
# VOCAB_VERSION stays pinned by every signed shard. Exports record this marker
# and the TBox digest so consumers can tell the revisions apart.
TBOX_REVISION: str = f"{VOCAB_VERSION}+phase9.1"


# Phase 9 KTD2: the envelope keeps its four-value ``bfo_category`` literal; this
# fixed table maps it to a class of the nine-class mini-BFO spine
# (bfo_spine.ttl) for the projection. ``occurrent_event`` follows the Phase 8
# D-06 fold of fi:Event into fi:Process. ``continuant_dependent`` maps to
# fi:Continuant because the spine has no dependent-continuant umbrella (D-06
# split it into SDC and GDC) and the envelope does not record which one.
BFO_CATEGORY_SPINE_CLASS: Mapping[str, str] = {
    "continuant_independent": f"{FI_PREFIX}IndependentContinuant",
    "continuant_dependent": f"{FI_PREFIX}Continuant",
    "occurrent_process": f"{FI_PREFIX}Process",
    "occurrent_event": f"{FI_PREFIX}Process",
}


__all__ = [
    "BFO_CATEGORY_SPINE_CLASS",
    "FRAMEWORK_NS",
    "TBOX_REVISION",
    "VOCAB_VERSION",
    "FI_PREFIX",
    "NAMESPACES",
    "framework_iri",
]
