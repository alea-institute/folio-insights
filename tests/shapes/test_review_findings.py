"""Phase 11 review findings, shapes side (each test failed before its fix).

* P2-1: the compiled engine reproduces pyshacl's ordering on naive vs aware
  dateTimes, NaN, infinities and bool-as-number. The model normalizes naive
  valid-time bounds to UTC, and stored naive records still load.
* P2-4: implicit ``owl:Class`` targets, custom constraint components,
  malformed counts and unknown regex flags are refused at compile time.
  ``sh:deactivated`` is honoured on shapes (``true`` or ``1``) and on
  ``sh:sparql`` constraints.
* Renderer nits: a camelCase alias of a declared field and a null-valued
  undeclared key are both reported as undeclared, and a non-string
  ``shard_type`` renders without crashing.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pyoxigraph import RdfFormat, Store
from rdflib import Graph

from folio_insights.shapes import pyshacl_adapter
from folio_insights.shapes.compiled import CompiledSuite, UnsupportedShaclConstruct, turtle_graph
from folio_insights.shapes.corpus import run_constraints, store_query
from folio_insights.shapes import rendering
from folio_insights.shapes.rendering import render_shard
from folio_insights.shapes.suite import SUITE_PATHS, default_suite
from folio_insights.shards import SimpleAssertionShard, dump_shard_record, load_shard_record
from tests.shapes.cases import dumped, mutate

SH = "http://www.w3.org/ns/shacl#"


def _agree(data: dict) -> set:
    graph, _ = render_shard(data)
    ours = {(r.focus, r.path, r.component, r.severity) for r in default_suite().compiled.validate(graph)}
    ref = {
        (r["focus"], r["path"], r["component"].removeprefix(SH), r["severity"].removeprefix(SH))
        for r in pyshacl_adapter.validate(graph, SUITE_PATHS).results
    }
    assert ours == ref
    return ours


@pytest.mark.parametrize(
    "change",
    [
        {"valid_time_start": "2026-01-01T00:00:00", "valid_time_end": "2027-01-01T00:00:00Z"},
        {"valid_time_start": "2027-01-01T00:00:00", "valid_time_end": "2026-01-01T00:00:00Z"},
        {"valid_time_start": "2026-01-01T05:00:00Z", "valid_time_end": "2026-01-01T03:00:00"},
        {"valid_time_start": "2026-01-01T00:00:00", "valid_time_end": "2026-01-01T00:00:00"},
        {"confidence": float("nan")},
        {"confidence": float("inf")},
        {"confidence": float("-inf")},
        {"confidence": True},
        {"confidence": False},
        {"ttl_days": True},
        {"confidence": 10**30},
    ],
    ids=lambda c: "-".join(f"{k}={v}" for k, v in c.items()),
)
def test_engines_agree_on_exotic_values(change: dict) -> None:
    _agree(mutate(dumped(), **change))


def test_naive_valid_time_is_normalized_to_utc_and_old_records_load() -> None:
    legacy = mutate(dumped(), valid_time_start="2026-01-01T00:00:00", valid_time_end="2027-01-01T00:00:00Z")
    loaded = load_shard_record(json.dumps(legacy).encode())
    assert loaded.shard.valid_time_start == datetime(2026, 1, 1, tzinfo=UTC)
    payload = json.loads(dump_shard_record(loaded.shard))
    assert payload["valid_time_start"] == "2026-01-01T00:00:00Z"
    assert _agree(payload) == set()
    # Naive start after aware end: caught once normalized (rdflib alone would
    # sort the naive value first and miss it).
    inverted = load_shard_record(
        json.dumps(mutate(dumped(), valid_time_start="2027-01-01T00:00:00",
                          valid_time_end="2026-01-01T00:00:00Z")).encode()
    )
    assert not default_suite().validate_shard(inverted.shard).conforms
    aware = SimpleAssertionShard(**{**dumped(), "valid_time_start": "2026-01-01T05:00:00+05:00"})
    assert aware.valid_time_start.utcoffset().total_seconds() == 5 * 3600  # aware untouched


H = (
    "@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix ex: <http://ex/> . "
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> . @prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
)


@pytest.mark.parametrize(
    "ttl",
    [
        "ex:S a sh:NodeShape, owl:Class ; sh:property [ sh:path ex:q ; sh:minCount 1 ] .",
        "ex:CC a sh:ConstraintComponent ; sh:parameter [ sh:path ex:needsQ ] ; "
        "sh:validator [ a sh:SPARQLAskValidator ; sh:ask \"ASK { $this <http://ex/q> ?x }\" ] . "
        "ex:S a sh:NodeShape ; sh:targetClass ex:C ; ex:needsQ true .",
        "ex:S a sh:NodeShape ; sh:targetClass ex:C ; sh:property [ sh:path ex:p ; sh:minCount 1.0 ] .",
        "ex:S a sh:NodeShape ; sh:targetClass ex:C ; sh:property [ sh:path ex:p ; sh:pattern \"a\" ; sh:flags \"q\" ] .",
        "ex:S a sh:NodeShape ; sh:targetClass ex:C ; sh:sparql [ sh:select \"SELECT $this WHERE {}\" ; sh:ask \"ASK {}\" ] .",
    ],
    ids=["owl_class_implicit", "custom_component", "decimal_min_count", "unknown_flag", "sparql_extra_term"],
)
def test_unsupported_shacl_refuses_to_compile(tmp_path: Path, ttl: str) -> None:
    path = tmp_path / "s.ttl"
    path.write_text(H + ttl)
    with pytest.raises(UnsupportedShaclConstruct):
        CompiledSuite([path])


def test_deactivated_shapes_and_sparql_constraints_are_skipped_like_pyshacl(tmp_path: Path) -> None:
    path = tmp_path / "d.ttl"
    path.write_text(H + (
        'ex:S a sh:NodeShape ; sh:targetClass ex:C ; sh:deactivated "1"^^xsd:boolean ; '
        "sh:property [ sh:path ex:missing ; sh:minCount 1 ] .\n"
        "ex:T a sh:NodeShape ; sh:targetClass ex:C ; "
        'sh:sparql [ sh:select "SELECT $this WHERE { $this ?p ?o }" ; sh:deactivated true ] , '
        '[ sh:select "SELECT $this WHERE { $this <http://ex/p> ?o }" ] .\n'
    ))
    data = "@prefix ex: <http://ex/> . ex:a a ex:C ; ex:p \"x\" ."
    suite = CompiledSuite([path])
    assert suite.validate(turtle_graph(data)) == []
    assert len(suite.sparql) == 1  # the deactivated sh:sparql constraint is dropped
    store = Store()
    store.load(data.encode(), format=RdfFormat.TURTLE)
    ours = run_constraints(store_query(store), suite.sparql)
    ref = pyshacl_adapter.validate(Graph().parse(data=data, format="turtle"), [path], local_only=False)
    assert {r.focus[1] for r in ours} == {r["focus"][1] for r in ref.results} == {"http://ex/a"}


def test_camel_case_alias_and_null_undeclared_keys_are_reported() -> None:
    alias = dumped()
    alias["sourceSpan"] = alias.pop("source_span")
    alias["bogus"] = None
    graph, _ = render_shard(alias)
    results = default_suite().compiled.validate(graph)
    closed = {r.path for r in results if r.component == "ClosedConstraintComponent"}
    ns = rendering.UNDECLARED_NS
    assert closed == {f"{ns}sourceSpan", f"{ns}bogus"}
    assert any(r.component == "MinCountConstraintComponent" and r.path.endswith("/sourceSpan")
               for r in results)  # the real field is still missing
    _agree(alias)


@pytest.mark.parametrize("tag", [[], {}, 7, None])
def test_non_string_shard_type_renders(tag: object) -> None:
    graph, _ = render_shard({"shard_type": tag, "sense": "x"})
    assert graph.nodes
