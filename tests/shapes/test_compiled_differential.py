"""KTD6: the compiled engine agrees with pyshacl.

The two engines must agree on conformance and on the set of
(focus node, result path, constraint component, severity) for:

* every valid and invalid fixture;
* Hypothesis-drawn instances of every subtype;
* seeded mutations of those instances.

The corpus tier (``sh:sparql``) must reproduce pyshacl's SPARQL results over
projection-shaped graphs. Constructs the compiled engine does not implement
must refuse to compile.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pyoxigraph import RdfFormat, Store
from rdflib import Graph

from folio_insights.shapes import pyshacl_adapter
from folio_insights.shapes.compiled import CompiledSuite, UnsupportedShaclConstruct
from folio_insights.shapes.corpus import run_constraints, store_query
from folio_insights.shapes.rendering import ValidationGraph, render_shard
from folio_insights.shapes.suite import SUITE_PATHS, default_suite
from folio_insights.storage.projection import shard_triples
from tests.shapes.cases import INVALID_CASES, VALID_CASES, Case, mutate
from tests.shapes.strategies import shards
from tests.storage.conftest import shard

SH = "http://www.w3.org/ns/shacl#"


def _compiled(graph: ValidationGraph) -> set[tuple]:
    return {
        (r.focus, r.path, r.component, r.severity)
        for r in default_suite().compiled.validate(graph)
    }


def _reference(graph: ValidationGraph) -> set[tuple]:
    report = pyshacl_adapter.validate(graph, SUITE_PATHS)
    return {
        (
            r["focus"],
            r["path"],
            r["component"].removeprefix(SH),
            r["severity"].removeprefix(SH),
        )
        for r in report.results
    }


def _agree(graph: ValidationGraph) -> None:
    assert _compiled(graph) == _reference(graph)


@pytest.mark.parametrize("case", VALID_CASES + INVALID_CASES, ids=lambda c: c.name)
def test_engines_agree_on_every_fixture(case: Case) -> None:
    _agree(case.build())


_MUTATIONS = [
    lambda d: mutate(d, layer="L9"),
    lambda d: mutate(d, confidence=-0.5),
    lambda d: mutate(d, confidence="x"),
    lambda d: mutate(d, sense=["a", "b"]),
    lambda d: mutate(d, smuggled={"k": 1}),
    lambda d: {k: v for k, v in d.items() if k != "framework_id"},
    lambda d: mutate(d, valid_time_start="2030-01-01T00:00:00Z", valid_time_end="2029-01-01T00:00:00Z"),
    lambda d: mutate(d, transaction_time="yesterday"),
    lambda d: mutate(d, shard_type="unknown"),
    lambda d: mutate(d, contested=True, epistemic_status="contested", contest_votes={}),
    lambda d: mutate(d, triple={"subject": "s", "predicate": "p", "object": "o", "extra": 1}),
    lambda d: mutate(d, signatures=[{"did": "", "signature": "x", "verified": True}]),
    # Review P2-1: exotic values where naive ordering semantics diverge.
    lambda d: mutate(d, confidence=float("nan")),
    lambda d: mutate(d, confidence=True),
    lambda d: mutate(d, confidence=False),
    lambda d: mutate(d, valid_time_start="2026-01-01T00:00:00", valid_time_end="2027-01-01T00:00:00Z"),
    lambda d: mutate(d, valid_time_start="2027-01-01T00:00:00", valid_time_end="2026-01-01T00:00:00Z"),
    lambda d: mutate(d, valid_time_start="2026-01-01T05:00:00Z", valid_time_end="2026-01-01T03:00:00"),
    lambda d: mutate(d, sourceSpan="alias", bogus=None),
]


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(shards(), st.sampled_from([None, *range(len(_MUTATIONS))]))
def test_engines_agree_on_generated_instances_and_mutations(instance, mutation) -> None:  # noqa: ANN001
    data = instance.model_dump(mode="json")
    if mutation is not None:
        data = _MUTATIONS[mutation](data)
    _agree(render_shard(data)[0])


def _projection_nt(*shards_) -> str:  # noqa: ANN002
    return "".join(
        f"{s} {p} {o} .\n" for x in shards_ for s, p, o in shard_triples(x, journal_position=0)
    )


def _corpus_compare(nt: str) -> set[tuple]:
    store = Store()
    store.load(nt.encode("utf-8"), format=RdfFormat.N_TRIPLES)
    ours = {
        (r.focus, r.severity)
        for r in run_constraints(store_query(store), default_suite().sparql)
    }
    report = pyshacl_adapter.validate(Graph().parse(data=nt, format="nt"), SUITE_PATHS, local_only=False)
    theirs = {
        (r["focus"], r["severity"].removeprefix(SH))
        for r in report.results
        if r["component"] == f"{SH}SPARQLConstraintComponent"
    }
    assert ours == theirs
    return ours


T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 6, 1, tzinfo=UTC)

CORPUS_CASES = {
    "aligned_chain": (
        lambda: _projection_nt(
            shard(1, supersedes=shard(2).shard_iri, valid_time_start=T2),
            shard(2, valid_time_start=T1, valid_time_end=T2, superseded_by=shard(1).shard_iri,
                  epistemic_status="superseded"),
        ),
        set(),
    ),
    "misaligned": (
        lambda: _projection_nt(
            shard(1, supersedes=shard(2).shard_iri, valid_time_start=T2),
            shard(2, valid_time_end=T1, superseded_by=shard(1).shard_iri, epistemic_status="superseded"),
        ),
        {("1", "Violation")},
    ),
    "superseded_still_current": (
        lambda: _projection_nt(
            shard(1, supersedes=shard(2).shard_iri, valid_time_start=T2),
            shard(2, superseded_by=shard(1).shard_iri, epistemic_status="superseded"),
        ),
        {("1", "Violation")},
    ),
    "self_supersession": (lambda: _projection_nt(shard(3, supersedes=shard(3).shard_iri)), {("3", "Violation"), ("3", "Warning")}),
    "reciprocity_mismatch": (
        lambda: _projection_nt(
            shard(1, supersedes=shard(2).shard_iri, valid_time_start=T2),
            shard(2, valid_time_end=T2, superseded_by=shard(5).shard_iri, epistemic_status="superseded"),
        ),
        {("1", "Violation")},
    ),
    "missing_back_pointer": (
        lambda: _projection_nt(
            shard(1, supersedes=shard(2).shard_iri, valid_time_start=T2),
            shard(2, valid_time_end=T2),
        ),
        {("1", "Warning")},
    ),
}


@pytest.mark.parametrize("name", list(CORPUS_CASES))
def test_corpus_tier_matches_pyshacl_sparql(name: str) -> None:
    build, expected = CORPUS_CASES[name]
    found = _corpus_compare(build())
    assert {(f[1].rsplit("/", 1)[-1].lstrip("0") or "0", sev) for f, sev in found} == expected


def test_corpus_tier_focus_restriction() -> None:
    nt = _projection_nt(shard(3, supersedes=shard(3).shard_iri), shard(4, supersedes=shard(4).shard_iri))
    store = Store()
    store.load(nt.encode("utf-8"), format=RdfFormat.N_TRIPLES)
    only = run_constraints(store_query(store), default_suite().sparql, focus=[shard(4).shard_iri])
    assert {r.focus[1] for r in only} == {shard(4).shard_iri}
    assert run_constraints(store_query(store), default_suite().sparql, focus=[]) == []


@pytest.mark.parametrize(
    "snippet",
    [
        "sh:property [ sh:path ( fi:a fi:b ) ; sh:minCount 1 ]",           # sequence path
        "sh:property [ sh:path fi:a ; sh:qualifiedMinCount 1 ]",           # qualified shapes
        "sh:property [ sh:path fi:a ; sh:languageIn ( \"en\" ) ]",          # languageIn
        "sh:property [ sh:path fi:a ; sh:uniqueLang true ]",
    ],
)
def test_unimplemented_constructs_refuse_to_compile(tmp_path: Path, snippet: str) -> None:
    ttl = tmp_path / "odd.ttl"
    ttl.write_text(
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/> .\n"
        f"fi:OddShape a sh:NodeShape ; sh:targetClass fi:Shard ; {snippet} .\n"
    )
    with pytest.raises(UnsupportedShaclConstruct):
        CompiledSuite([ttl])


@pytest.mark.parametrize("mutation", range(len(_MUTATIONS)))
@pytest.mark.parametrize("tag", ["simple_assertion", "disputed_proposition", "conflicting_authorities", "gloss", "hypothesis"])
def test_engines_agree_on_every_mutation_of_every_subtype(tag: str, mutation: int) -> None:
    """Deterministic coverage of the mutation table (Hypothesis samples it)."""
    from tests.shapes.cases import dumped
    from tests.shards.conftest import _SUBTYPE_TABLE

    cls = dict(_SUBTYPE_TABLE)[tag]
    _agree(render_shard(_MUTATIONS[mutation](dumped(cls)))[0])
