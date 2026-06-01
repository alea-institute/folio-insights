"""FOLIO Insights v2 vocabulary package (Phase 8 anchor).

Ships the canonical fi:* TTL vocabulary as a self-contained Python sub-package:

  * VOCAB_VERSION — CalVer module constant (Phase 8 D-02).
  * FI_PREFIX     — canonical fi: namespace IRI (Phase 8 D-01).
  * NAMESPACES    — Mapping[str, rdflib.Namespace] promoted from
                    bench/generator.py:51-55 string constants so every
                    downstream module reads from one source.
  * load_graph()           — rdflib.Graph parser for the 4 (default) or 5
                             (with include_bfo_mapping=True) TTL files. The
                             opt-in toggle matches D-09's cost-amortisation
                             argument: rdflib SHACL validators that don't
                             need BFO 2020 interop skip the bfo_mapping.ttl
                             parse cost.
  * load_pyoxigraph_store() — pyoxigraph.Store loaded with all 5 TTL files
                              (the bfo_mapping cost-amortisation argument
                              only applies to the rdflib SHACL path; the
                              pyoxigraph SPARQL surface always wants the
                              full graph).

Both loaders use ``importlib.resources.files("folio_insights.vocab")`` per
D-09 — this is the first ``importlib.resources`` user in the project. The
Path(__file__).parent / "<asset>" idiom used elsewhere (e.g.
governance/shape_validation.py, services/shacl_validator.py) was a precursor;
D-09 standardises on importlib.resources because hatchling packages
.ttl files automatically and importlib.resources works correctly when the
package is loaded from a zip-installed wheel.

Decision references:
  * D-01  — canonical fi: prefix https://folio-insights.aleainstitute.ai/vocab/
  * D-01a — upstream FOLIO IRIs sacred (untouched in v1 OWL export)
  * D-01b — v1 OWL export pipeline frozen, marker-comment only
  * D-02  — VOCAB_VERSION = "2026.05.0" CalVer YYYY.MM.PATCH
  * D-05  — each TTL file carries its own owl:versionIRI containing VOCAB_VERSION
  * D-08  — 5-file TTL split (predicates, classes, bfo_spine, bfo_mapping, shapes)
  * D-09  — importlib.resources backed loaders; bfo_mapping opt-in for rdflib path
"""

from __future__ import annotations

from importlib.resources import files
from typing import TYPE_CHECKING

from rdflib import Graph

# Lightweight constants live in _constants.py so callers needing only the
# version pin (shards/envelope.py, bench/generator.py) can import without
# forcing a pyoxigraph import (WR-01). Combined with the lazy pyoxigraph
# import inside load_pyoxigraph_store, this means importing
# ``folio_insights.vocab._constants`` only pulls rdflib + stdlib.
from folio_insights.vocab._constants import FI_PREFIX, NAMESPACES, VOCAB_VERSION

if TYPE_CHECKING:
    from pyoxigraph import Store

# D-08 TTL file inventory. Order matters for deterministic parse — predicates
# first (most referenced), then classes, spine, opt-in mapping, shapes last
# (shapes reference the classes/predicates above them).
_CORE_TTL_FILES: tuple[str, ...] = (
    "predicates.ttl",
    "classes.ttl",
    "bfo_spine.ttl",
    "shapes.ttl",
)
_BFO_MAPPING_TTL: str = "bfo_mapping.ttl"


# ---------------------------------------------------------------------------
# Loaders (D-09)
# ---------------------------------------------------------------------------


def load_graph(*, include_bfo_mapping: bool = False) -> Graph:
    """Return an ``rdflib.Graph`` parsed from the vocab TTL files.

    By default, parses the 4 core TTL files (``predicates.ttl``,
    ``classes.ttl``, ``bfo_spine.ttl``, ``shapes.ttl``). Pass
    ``include_bfo_mapping=True`` to additionally parse ``bfo_mapping.ttl``
    (the BFO 2020 ``owl:equivalentClass`` rows from D-07).

    The opt-in toggle matches D-09's cost-amortisation argument: rdflib SHACL
    validators that don't need BFO 2020 interop skip the bfo_mapping parse
    cost (the file is small but the principle scales to deeper alignment
    files in future phases).
    """
    g = Graph()
    pkg = files("folio_insights.vocab")
    for name in _CORE_TTL_FILES:
        g.parse(data=(pkg / name).read_bytes(), format="turtle")
    if include_bfo_mapping:
        g.parse(data=(pkg / _BFO_MAPPING_TTL).read_bytes(), format="turtle")
    return g


def load_pyoxigraph_store() -> "Store":
    """Return an in-memory ``pyoxigraph.Store`` loaded with ALL 5 TTL files.

    Unlike ``load_graph`` the pyoxigraph path always includes ``bfo_mapping.ttl``
    because the SPARQL surface this Store backs (Phase 11 triplestore +
    downstream consumers) always wants the full BFO 2020 alignment available
    for cross-vocab queries.

    WR-01: pyoxigraph is imported lazily inside this function so importing
    ``folio_insights.vocab`` (or its lightweight ``_constants`` submodule)
    does not pull pyoxigraph into lightweight environments.
    """
    from pyoxigraph import RdfFormat, Store

    store = Store()
    pkg = files("folio_insights.vocab")
    for name in (*_CORE_TTL_FILES, _BFO_MAPPING_TTL):
        store.load(input=(pkg / name).read_bytes(), format=RdfFormat.TURTLE)
    return store


__all__ = [
    "VOCAB_VERSION",
    "FI_PREFIX",
    "NAMESPACES",
    "load_graph",
    "load_pyoxigraph_store",
]
