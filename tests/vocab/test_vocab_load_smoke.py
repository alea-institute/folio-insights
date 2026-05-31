"""Phase 8 Plan 08-01 — vocab package smoke test (RED → GREEN).

Verifies the FOLIO Insights v2 vocab package ships:
  * VOCAB_VERSION = "2026.05.0" module constant (D-02)
  * Canonical fi: prefix https://folio-insights.aleainstitute.ai/vocab/ (D-01)
  * 5 TTL files (predicates, classes, bfo_spine, bfo_mapping, shapes) each
    carrying their own owl:versionIRI containing 2026.05.0 (D-05, D-08)
  * load_graph() parses 4 TTL files (predicates+classes+bfo_spine+shapes) by
    default; opt-in include_bfo_mapping=True adds bfo_mapping.ttl (D-09)
  * load_pyoxigraph_store() parses all 5 TTL files into an in-memory pyoxigraph
    Store (D-09)
  * 9-class mini-BFO spine (D-06)
  * 9 owl:equivalentClass rows in bfo_mapping.ttl (D-07)
  * fi:supersedes + fi:supersededBy declared as an owl:inverseOf pair (D-10)
  * fi:VocabPinShape in shapes.ttl with sh:hasValue "2026.05.0" (D-04)
  * D-01b v1-legacy marker comments in services/owl_serializer.py and
    export/shapes.ttl
"""

from __future__ import annotations

from importlib.resources import files

import pytest


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


def test_vocab_version_constant() -> None:
    """D-02: VOCAB_VERSION = "2026.05.0" is the single source of truth."""
    from folio_insights.vocab import VOCAB_VERSION

    assert VOCAB_VERSION == "2026.05.0"


def test_fi_prefix_canonical() -> None:
    """D-01: canonical fi: prefix matches PRD §7.1."""
    from folio_insights.vocab import FI_PREFIX

    assert FI_PREFIX == "https://folio-insights.aleainstitute.ai/vocab/"


def test_namespaces_contains_required_keys() -> None:
    """NAMESPACES promotes bench/generator.py:51-55 constants to rdflib.Namespace."""
    from rdflib import Namespace

    from folio_insights.vocab import NAMESPACES

    for key in ("fi", "corpus", "shard", "concept", "framework"):
        assert key in NAMESPACES, f"NAMESPACES missing key {key!r}"
        assert isinstance(NAMESPACES[key], Namespace)

    assert str(NAMESPACES["fi"]) == "https://folio-insights.aleainstitute.ai/vocab/"


# ---------------------------------------------------------------------------
# rdflib loader (D-09)
# ---------------------------------------------------------------------------


def test_load_graph_returns_non_empty_rdflib_graph() -> None:
    """load_graph() returns a non-empty rdflib.Graph parsed from 4 TTL files."""
    from rdflib import Graph

    from folio_insights.vocab import load_graph

    g = load_graph()
    assert isinstance(g, Graph)
    assert len(g) > 0


def test_load_graph_include_bfo_mapping_is_strictly_larger() -> None:
    """include_bfo_mapping=True additionally parses bfo_mapping.ttl into the graph."""
    from folio_insights.vocab import load_graph

    base = load_graph()
    with_mapping = load_graph(include_bfo_mapping=True)
    assert len(with_mapping) > len(base), (
        "include_bfo_mapping=True must add the bfo_mapping.ttl triples to the "
        "default load_graph() output"
    )


# ---------------------------------------------------------------------------
# pyoxigraph loader (D-09)
# ---------------------------------------------------------------------------


def test_load_pyoxigraph_store_parses_without_error() -> None:
    """load_pyoxigraph_store() returns a pyoxigraph.Store containing all 5 TTL files."""
    import pyoxigraph

    from folio_insights.vocab import load_pyoxigraph_store

    store = load_pyoxigraph_store()
    assert isinstance(store, pyoxigraph.Store)
    # Sanity: any triples at all? The 5 TTL files together produce >0 quads.
    rows = list(store.quads_for_pattern(None, None, None, None))
    assert len(rows) > 0


# ---------------------------------------------------------------------------
# Per-file structural assertions
# ---------------------------------------------------------------------------


_VOCAB_RES = files("folio_insights.vocab")
_TTL_NAMES = (
    "predicates.ttl",
    "classes.ttl",
    "bfo_spine.ttl",
    "bfo_mapping.ttl",
    "shapes.ttl",
)


def _read_ttl(name: str) -> str:
    return (_VOCAB_RES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("ttl_name", _TTL_NAMES)
def test_each_ttl_carries_version_iri_with_vocab_version(ttl_name: str) -> None:
    """D-05: every TTL file's owl:versionIRI contains VOCAB_VERSION = 2026.05.0."""
    text = _read_ttl(ttl_name)
    assert "2026.05.0" in text, f"{ttl_name} must mention 2026.05.0 (owl:versionIRI per D-05)"
    assert "owl:versionIRI" in text, f"{ttl_name} must declare owl:versionIRI per D-05"


@pytest.mark.parametrize("ttl_name", _TTL_NAMES)
def test_each_ttl_uses_canonical_fi_prefix(ttl_name: str) -> None:
    """D-01: every TTL file carries the canonical fi: prefix in an @prefix declaration."""
    text = _read_ttl(ttl_name)
    assert "https://folio-insights.aleainstitute.ai/vocab/" in text, (
        f"{ttl_name} must declare @prefix fi: <https://folio-insights.aleainstitute.ai/vocab/>"
    )


def test_bfo_mapping_has_nine_equivalent_class_rows() -> None:
    """D-07: bfo_mapping.ttl has at least 9 owl:equivalentClass rows to BFO 2020."""
    text = _read_ttl("bfo_mapping.ttl")
    # Each row carries owl:equivalentClass + an obo/BFO_ object IRI.
    bfo_refs = text.count("obo/BFO_")
    eq_refs = text.count("owl:equivalentClass")
    assert bfo_refs >= 9, f"bfo_mapping.ttl must reference ≥9 BFO 2020 IRIs (found {bfo_refs})"
    assert eq_refs >= 9, (
        f"bfo_mapping.ttl must declare ≥9 owl:equivalentClass rows (found {eq_refs})"
    )


def test_bfo_spine_declares_nine_classes() -> None:
    """D-06: bfo_spine.ttl declares exactly the 9 mini-BFO classes."""
    text = _read_ttl("bfo_spine.ttl")
    required = [
        "fi:Continuant",
        "fi:IndependentContinuant",
        "fi:SpecificallyDependentContinuant",
        "fi:GenericallyDependentContinuant",
        "fi:Role",
        "fi:Occurrent",
        "fi:Process",
        "fi:Quality",
        "fi:Disposition",
    ]
    for class_name in required:
        assert class_name in text, f"bfo_spine.ttl must declare {class_name} (D-06)"


def test_predicates_supersession_pair_is_inverseof() -> None:
    """D-10 / VOCAB-05: fi:supersedes + fi:supersededBy declared as owl:inverseOf pair."""
    text = _read_ttl("predicates.ttl")
    assert "fi:supersedes" in text
    assert "fi:supersededBy" in text
    assert "owl:inverseOf" in text, (
        "predicates.ttl must declare an owl:inverseOf between fi:supersedes and "
        "fi:supersededBy (D-10)"
    )


def test_shapes_declares_vocab_pin_shape() -> None:
    """D-04: shapes.ttl declares fi:VocabPinShape with sh:hasValue "2026.05.0"."""
    text = _read_ttl("shapes.ttl")
    assert "fi:VocabPinShape" in text
    assert "sh:NodeShape" in text
    assert "fi:vocabVersion" in text
    assert '"2026.05.0"' in text, "VocabPinShape must pin sh:hasValue to the literal 2026.05.0"


def test_shapes_declares_signed_action_enum() -> None:
    """D-12: shapes.ttl declares fi:SignedActionEnumShape with 13-value sh:in enumeration."""
    text = _read_ttl("shapes.ttl")
    assert "fi:SignedActionEnumShape" in text
    # 13 SignedAction values from src/folio_insights/shards/envelope.py:85
    for action in (
        "role_assertion",
        "role_revocation",
        "extract",
        "promote",
        "demote",
        "contest",
        "resolve_contest",
        "distinguo",
        "supersede",
        "retract",
        "content_edit",
        "reparent",
        "reconcile",
    ):
        assert f'"{action}"' in text, f"SignedActionEnumShape missing value {action!r}"


def test_shapes_declares_role_enum() -> None:
    """D-12: shapes.ttl declares fi:RoleEnumShape with the 4-value role enumeration."""
    text = _read_ttl("shapes.ttl")
    assert "fi:RoleEnumShape" in text
    for role in ("extractor", "reviewer", "arbiter", "corpus_admin"):
        assert f'"{role}"' in text, f"RoleEnumShape missing value {role!r}"


# ---------------------------------------------------------------------------
# v1-legacy marker comments (D-01b)
# ---------------------------------------------------------------------------


def test_owl_serializer_has_v1_legacy_marker() -> None:
    """D-01b: services/owl_serializer.py carries the v1-legacy marker comment."""
    from pathlib import Path

    text = Path("src/folio_insights/services/owl_serializer.py").read_text(encoding="utf-8")
    assert "v1-legacy" in text
    assert "DO NOT migrate" in text


def test_export_shapes_has_v1_legacy_marker() -> None:
    """D-01b: export/shapes.ttl carries the v1-legacy marker comment."""
    from pathlib import Path

    text = Path("src/folio_insights/export/shapes.ttl").read_text(encoding="utf-8")
    assert "v1-legacy" in text
    assert "DO NOT migrate" in text


def test_owl_serializer_canonical_folio_iri_untouched() -> None:
    """D-01a: the upstream FOLIO canonical IRI is NOT rewritten in owl_serializer.py."""
    from pathlib import Path

    text = Path("src/folio_insights/services/owl_serializer.py").read_text(encoding="utf-8")
    # The sacred upstream IRI MUST still be present (D-01a).
    assert "https://folio.openlegalstandard.org/" in text
