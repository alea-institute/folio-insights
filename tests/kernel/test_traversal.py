"""Drain U3 (R11, AE4, KTD8) — derivedFromKernel traversal and chain export.

AE4: a synthetic shard S elaborates a hypothesis H that depends on regula
VI 5.12.6 ("Nemo potest ad impossibile obligari"); S's chain is the two-hop
S -> H -> kernel 5.12.6 and exports as JSON and Turtle. The walk is
breadth-first, cycle-safe, bounded, and reports when no kernel is reached.
"""
from __future__ import annotations

import json
from importlib.resources import files

import pytest
from pyoxigraph import NamedNode, RdfFormat, parse

from folio_insights.kernel.catalog import load_catalog
from folio_insights.kernel.export import (
    CHAIN_FORMAT,
    EDGE_PREDICATES,
    chain_to_json,
    chain_to_turtle,
)
from folio_insights.kernel.traversal import (
    DerivationEdge,
    UnknownShard,
    derivation_tree,
    derived_from_kernel,
)
from folio_insights.revision.store import DEPENDENCY_FIELDS
from folio_insights.shards import HypothesisShard, ShardEnvelope, SimpleAssertionShard
from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.projection import DEPENDENCY_PREDICATES
from folio_insights.vocab._constants import FI_PREFIX

from tests.kernel.conftest import SeededCorpus
from tests.shards.conftest import _sample_shard

RDF_TYPE = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")


def _kernel(citation: str) -> str:
    maxim = load_catalog().by_citation(citation)
    assert maxim is not None
    return maxim.shard_iri


K6 = _kernel("VI 5.12.6")  # Nemo potest ad impossibile obligari.
K79 = _kernel("VI 5.12.79")
D1 = _kernel("D.50.17.1")


def _iri(n: int) -> str:
    return f"urn:folio:shard/{n:032x}"


def _shard(n: int, cls: type[ShardEnvelope] = SimpleAssertionShard, **fields) -> ShardEnvelope:
    return _sample_shard(cls, shard_iri=_iri(n), sense=f"synthetic {n}",
                         framework_id="us.common_law", **fields)


def _ae4_shards() -> tuple[ShardEnvelope, ShardEnvelope]:
    h = _shard(0xA1, HypothesisShard, epistemic_status="hypothesis",
               depends_on_axioms=[K6])
    s = _shard(0xA2, elaborates=[h.shard_iri])
    return h, s


def _store(*shards: ShardEnvelope) -> dict[str, ShardEnvelope]:
    return {s.shard_iri: s for s in shards}


# ── AE4 against a seeded corpus ─────────────────────────────────────────────


async def test_ae4_two_hop_chain_through_storage(seeded: SeededCorpus) -> None:
    h, s = _ae4_shards()
    ctx = await CorpusStorageContext.open(seeded.root, seeded.corpus)
    try:
        await ctx.ingest_shards([h, s], op_id="test:ae4")
        derivations = await derived_from_kernel(ctx, s.shard_iri)
        tree = await derivation_tree(ctx.shards, s.shard_iri)  # a ShardStore works too
    finally:
        await ctx.close()

    assert len(derivations) == 1
    d = derivations[0]
    assert d.kernel_iri == K6 and d.citation == "VI 5.12.6"
    assert d.citation_uri == "urn:folio:kernel:liber-sextus:5.12.6"
    assert d.path == (s.shard_iri, h.shard_iri, K6)
    assert d.edges == (
        DerivationEdge(s.shard_iri, h.shard_iri, "elaborates"),
        DerivationEdge(h.shard_iri, K6, "depends_on_axioms"),
    )
    assert d.depth == 2
    assert tree.derivations == (d,) and tree.kernel_reached and not tree.truncated

    data = json.loads(chain_to_json(tree))
    assert data["format"] == CHAIN_FORMAT and data["root"] == s.shard_iri
    assert data["kernel_reached"] is True
    [entry] = data["derivedFromKernel"]
    assert entry["kernel_iri"] == K6 and entry["citation"] == "VI 5.12.6"
    assert entry["path"] == [s.shard_iri, h.shard_iri, K6]
    assert entry["edges"] == [
        {"from": s.shard_iri, "to": h.shard_iri, "field": "elaborates"},
        {"from": h.shard_iri, "to": K6, "field": "depends_on_axioms"},
    ]
    assert {n["iri"]: n["kernel"] for n in data["nodes"]} == {
        s.shard_iri: False, h.shard_iri: False, K6: True,
    }
    assert {(e["from"], e["predicate"]) for e in data["edges"]} == {
        (s.shard_iri, FI_PREFIX + "elaborates"), (h.shard_iri, FI_PREFIX + "dependsOnAxiom"),
    }

    ttl = chain_to_turtle(tree)
    triples = {(t.subject.value, t.predicate.value, t.object.value)
               for t in parse(ttl, format=RdfFormat.TURTLE)}
    assert (s.shard_iri, FI_PREFIX + "elaborates", h.shard_iri) in triples
    assert (h.shard_iri, FI_PREFIX + "dependsOnAxiom", K6) in triples
    assert (K6, RDF_TYPE.value, FI_PREFIX + "CommonAxiom") in triples
    assert (K6, FI_PREFIX + "reference", "VI 5.12.6") in triples
    assert (K6, FI_PREFIX + "sourceUri", "urn:folio:kernel:liber-sextus:5.12.6") in triples
    assert (s.shard_iri, RDF_TYPE.value, FI_PREFIX + "CommonAxiom") not in triples
    assert not any("derivedFromKernel" in p for _, p, _ in triples)  # not a vocab term


# ── traversal semantics over an in-memory mapping ───────────────────────────


async def test_planted_cycle_terminates_and_still_finds_the_kernel() -> None:
    a = _shard(1, depends_on_shards=[_iri(2)])
    b = _shard(2, depends_on_shards=[_iri(1)], elaborates=[_iri(3)])
    c = _shard(3, depends_on_shards=[_iri(2)], depends_on_axioms=[K6])
    tree = await derivation_tree(_store(a, b, c), a.shard_iri)
    assert [d.kernel_iri for d in tree.derivations] == [K6]
    assert tree.derivations[0].path == (_iri(1), _iri(2), _iri(3), K6)
    assert sorted(tree.visited) == sorted([_iri(1), _iri(2), _iri(3), K6])


async def test_pure_cycle_reports_no_kernel() -> None:
    a = _shard(1, elaborates=[_iri(2)])
    b = _shard(2, elaborates=[_iri(1)])
    tree = await derivation_tree(_store(a, b), a.shard_iri)
    assert tree.derivations == () and not tree.kernel_reached and not tree.truncated
    assert json.loads(chain_to_json(tree))["derivedFromKernel"] == []


async def test_a_shard_reaching_no_kernel_reports_none() -> None:
    lone = _shard(7)
    store = _store(lone)
    assert await derived_from_kernel(store, lone.shard_iri) == []
    tree = await derivation_tree(store, lone.shard_iri)
    data = json.loads(chain_to_json(tree))
    assert data["kernel_reached"] is False and data["edges"] == []
    assert data["nodes"] == [
        {"iri": lone.shard_iri, "kernel": False, "citation": None, "citation_uri": None}
    ]
    triples = list(parse(chain_to_turtle(tree), format=RdfFormat.TURTLE))
    assert [(t.subject.value, t.object.value) for t in triples] == [
        (lone.shard_iri, FI_PREFIX + "Shard")
    ]


async def test_shortest_path_wins_and_ties_break_by_field_order() -> None:
    h = _shard(1, depends_on_axioms=[K6])
    s = _shard(2, elaborates=[h.shard_iri], depends_on_axioms=[K6, K79],
               depends_on_shards=[h.shard_iri])
    tree = await derivation_tree(_store(h, s), s.shard_iri)
    assert [(d.kernel_iri, d.path) for d in tree.derivations] == [
        (K6, (s.shard_iri, K6)), (K79, (s.shard_iri, K79)),
    ]
    # h is reached first through ``elaborates`` (the first field), not depends_on_shards
    h_edge = [e for e in tree.edges_walked if e.target == h.shard_iri][0]
    assert h_edge.field == "elaborates"


async def test_every_dependency_field_is_walked_and_labelled() -> None:
    d = _shard(1, depends_on_definitions=[K6])
    p = _shard(2, depends_on_precedents=[D1])
    x = _shard(3, depends_on_shards=[d.shard_iri, p.shard_iri])
    tree = await derivation_tree(_store(d, p, x), x.shard_iri)
    fields = {dv.kernel_iri: [e.field for e in dv.edges] for dv in tree.derivations}
    assert fields == {
        K6: ["depends_on_shards", "depends_on_definitions"],
        D1: ["depends_on_shards", "depends_on_precedents"],
    }
    data = json.loads(chain_to_json(tree))
    assert {e["predicate"].removeprefix(FI_PREFIX) for e in data["edges"]} == {
        "dependsOnShard", "dependsOnDefinition", "dependsOnPrecedent",
    }


async def test_max_depth_bounds_the_walk_and_reports_truncation() -> None:
    a = _shard(1, elaborates=[_iri(2)])
    b = _shard(2, elaborates=[_iri(3)])
    c = _shard(3, depends_on_axioms=[K6])
    store = _store(a, b, c)
    assert (await derivation_tree(store, a.shard_iri, max_depth=3)).kernel_reached
    cut = await derivation_tree(store, a.shard_iri, max_depth=2)
    assert not cut.kernel_reached and cut.truncated
    zero = await derivation_tree(store, a.shard_iri, max_depth=0)
    assert zero.visited == (a.shard_iri,) and zero.truncated
    with pytest.raises(ValueError):
        await derivation_tree(store, a.shard_iri, max_depth=-1)


async def test_dangling_references_are_listed_not_fatal() -> None:
    gone = _iri(0xDEAD)
    s = _shard(1, depends_on_shards=[gone], depends_on_axioms=[K6])
    tree = await derivation_tree(_store(s), s.shard_iri)
    assert tree.missing == (gone,)
    assert [d.kernel_iri for d in tree.derivations] == [K6]
    assert json.loads(chain_to_json(tree))["missing"] == [gone]


async def test_kernel_root_and_unknown_root() -> None:
    tree = await derivation_tree({}, K6)  # a kernel IRI needs no stored shard
    [d] = tree.derivations
    assert d.path == (K6,) and d.edges == () and d.depth == 0
    with pytest.raises(UnknownShard, match="not a kernel IRI"):
        await derivation_tree({}, _iri(99))


async def test_unreadable_source_is_a_type_error() -> None:
    with pytest.raises(TypeError):
        await derivation_tree(object(), K6)


# ── export stability and vocabulary ─────────────────────────────────────────


async def test_exports_are_byte_stable() -> None:
    h, s = _ae4_shards()
    store = _store(h, s)
    first = await derivation_tree(store, s.shard_iri)
    second = await derivation_tree(dict(reversed(list(store.items()))), s.shard_iri)
    assert chain_to_json(first) == chain_to_json(second)
    assert chain_to_turtle(first) == chain_to_turtle(second)
    text = chain_to_json(first)
    assert text.endswith("\n") and json.dumps(json.loads(text), indent=2, sort_keys=True,
                                              ensure_ascii=False) + "\n" == text


def test_edge_predicates_match_the_projection_and_the_vocabulary() -> None:
    assert set(EDGE_PREDICATES) == {"elaborates", *DEPENDENCY_FIELDS}
    for field_name, local in DEPENDENCY_PREDICATES.items():
        assert EDGE_PREDICATES[field_name] == local
    vocab = files("folio_insights.vocab")
    declared = (vocab / "predicates.ttl").read_text("utf-8") + (
        vocab / "classes.ttl"
    ).read_text("utf-8")
    for term in [*EDGE_PREDICATES.values(), "CommonAxiom", "Shard", "reference", "sourceUri"]:
        assert f"fi:{term} a owl:" in declared, term
    assert "fi:derivedFromKernel a" not in declared  # the JSON-only view, by design

