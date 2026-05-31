"""Phase 8 Plan 08-04 Task 2 — owl:versionIRI per-file pinning (D-05 + VOCAB-01).

For each of the 5 vocab TTL files (predicates / classes / bfo_spine /
bfo_mapping / shapes), assert that:

  1. The ontology IRI ``<https://folio-insights.aleainstitute.ai/vocab/{name}>``
     declares an ``owl:versionIRI`` triple.
  2. The object IRI's string form contains the substring ``2026.05.0``
     (the current ``VOCAB_VERSION``).
  3. The object IRI follows the canonical pattern
     ``https://folio-insights.aleainstitute.ai/vocab/{VOCAB_VERSION}/{name}``.

D-05 says: "Each of the 5 vocab TTL files carries its own owl:versionIRI
that includes VOCAB_VERSION (e.g.
``<https://folio-insights.aleainstitute.ai/vocab/2026.05.0/predicates>``).
Lets downstream consumers pin to a specific vocab snapshot independently
per file."
"""

from __future__ import annotations

import pytest
from rdflib import OWL, URIRef

from folio_insights.vocab import FI_PREFIX, VOCAB_VERSION, load_graph

_ONTOLOGY_LOCAL_NAMES: tuple[str, ...] = (
    "predicates",
    "classes",
    "bfo_spine",
    "bfo_mapping",
    "shapes",
)


@pytest.fixture(scope="module")
def vocab_graph():
    return load_graph(include_bfo_mapping=True)


@pytest.mark.parametrize("name", _ONTOLOGY_LOCAL_NAMES)
def test_owl_version_iri_pins_vocab_version(name: str, vocab_graph) -> None:
    """Every vocab TTL file's owl:versionIRI must contain VOCAB_VERSION (D-05)."""
    ont_iri = URIRef(f"{FI_PREFIX}{name}")
    version_iris = list(vocab_graph.objects(ont_iri, OWL.versionIRI))

    assert version_iris, (
        f"<{ont_iri}> has no owl:versionIRI triple (D-05 / VOCAB-01 acceptance gate 1)"
    )

    for vi in version_iris:
        vi_str = str(vi)
        assert VOCAB_VERSION in vi_str, (
            f"<{ont_iri}> owl:versionIRI {vi_str!r} does not contain {VOCAB_VERSION!r}"
        )
        expected = f"{FI_PREFIX}{VOCAB_VERSION}/{name}"
        assert vi_str == expected, (
            f"<{ont_iri}> owl:versionIRI {vi_str!r} does not match canonical pattern {expected!r}"
        )
